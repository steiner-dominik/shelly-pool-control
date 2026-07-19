// Device wrapper around PoolCore — Shelly Gen2+ (baseline: 2PM Gen4 + Plus Add-On).
// Concatenated after core.js by build.mjs into build/pool-control.js.
//
// The Shelly is the sole control authority: this script reads sensors, runs
// PoolCore.step() and drives the relay. The server only writes KVS parameters
// and posts override *requests* to /script/<id>/cmd which are validated here.

var SCRIPT_VERSION = "__VERSION__";

// Device-level config (KVS key pool.dev, JSON) — everything mappable so a
// 1PM (single channel) or different wiring works without code changes.
var DEV = {
  relay_id: 0,        // switch id driving the pump
  input_pump: 0,      // detached input for the manual button, -1 = disabled
  state_save_s: 600,  // periodic state persistence (flash wear budget)
  sensors: {          // slot -> temperature component id, -1 = unmapped
    water_a: 100, water_b: 101, mat_a: 102, mat_b: 103, air: 104
  }
};

var CFG = {};                      // core config (KVS pool.cfg.*)
var CFG_REV = "0";                 // KVS pool.cfg._rev, echoed in status
var STATE = PoolCore.initialState();
var CMD_QUEUE = [];
var LAST_ACKS = [];
var LAST_RESULT = null;
var LAST_SAVE = 0;
var SAVE_DIRTY = false;
var TICK_HANDLE = null;
var CUR_TICK_S = 0;
var APPLIED_RELAY = null;

function digits(s) {
  // parse a small non-negative integer ("08" → 8); JSON.parse rejects leading zeros
  var n = 0;
  for (var i = 0; i < s.length; i++) {
    var c = s.charCodeAt(i);
    if (c < 48 || c > 57) return n;
    n = n * 10 + (c - 48);
  }
  return n;
}

function nowSpec() {
  // Returns {now, uptime, time_valid, local_min, local_day}
  var sys = Shelly.getComponentStatus("sys");
  var up = sys.uptime;
  var unix = sys.unixtime;
  var valid = typeof unix === "number" && unix > 1000000000;
  var localMin = 0;
  var localDay = 0;
  var now;
  if (valid) {
    now = unix;
    // sys.time is "HH:MM" local time
    if (typeof sys.time === "string" && sys.time.length >= 5) {
      localMin = digits(sys.time.slice(0, 2)) * 60
        + digits(sys.time.slice(3, 5));
    }
    // derive tz offset from local wall minutes vs UTC minutes
    var utcMin = Math.floor(unix / 60) % 1440;
    var offMin = localMin - utcMin;
    if (offMin > 840) offMin -= 1440;
    if (offMin < -720) offMin += 1440;
    localDay = Math.floor((unix + offMin * 60) / 86400);
  } else {
    // stable monotonic fallback epoch (2000-01-01 + uptime)
    now = 946684800 + up;
  }
  return { now: now, uptime: up, time_valid: valid,
           local_min: localMin, local_day: localDay };
}

function readSensors() {
  var out = {};
  for (var slot in DEV.sensors) {
    var id = DEV.sensors[slot];
    out[slot] = null;
    if (typeof id === "number" && id >= 0) {
      var st = Shelly.getComponentStatus("temperature:" + JSON.stringify(id));
      if (st !== null && st !== undefined && typeof st.tC === "number") {
        out[slot] = st.tC;
      }
    }
  }
  return out;
}

function persistState(force, ts) {
  if (!force && !SAVE_DIRTY) return;
  if (!force && ts - LAST_SAVE < 60) return;   // hard lower bound on writes
  LAST_SAVE = ts;
  SAVE_DIRTY = false;
  // reduced state only (KVS value size limit + flash wear)
  var s = {
    m: STATE.mode, pm: STATE.prev_mode, mu: STATE.mode_until,
    dk: STATE.day_key, rs: STATE.run_s_today, hs: STATE.heat_s_today,
    ls: STATE.last_stop, pn: STATE.pump_nominal, lo: STATE.lockouts
  };
  Shelly.call("KVS.Set", { key: "pool.state", value: JSON.stringify(s) });
}

function restoreState(raw, sp) {
  var s = null;
  try { s = JSON.parse(raw); } catch (e) { s = null; }
  if (s === null || typeof s !== "object") return;
  if (typeof s.m === "string") STATE.mode = s.m;
  if (typeof s.pm === "string") STATE.prev_mode = s.pm;
  if (typeof s.mu === "number") STATE.mode_until = s.mu;
  if (typeof s.dk === "number") STATE.day_key = s.dk;
  if (typeof s.rs === "number") STATE.run_s_today = s.rs;
  if (typeof s.hs === "number") STATE.heat_s_today = s.hs;
  if (typeof s.ls === "number") STATE.last_stop = s.ls;
  if (typeof s.pn === "number") STATE.pump_nominal = s.pn;
  if (s.lo !== undefined && s.lo !== null) STATE.lockouts = s.lo;
  // sanitize timestamps that are in the future (clock lost across reboot)
  if (STATE.last_stop > sp.now) STATE.last_stop = 0;
  if (STATE.mode_until > 0 && STATE.mode_until - sp.now > 86400) {
    STATE.mode_until = 0;
  }
  if (STATE.mode === "force_on" || STATE.mode === "boost") {
    if (STATE.mode_until === 0 || STATE.mode_until < sp.now) {
      STATE.mode = STATE.prev_mode;
      STATE.mode_until = 0;
    }
  }
  var bp = PoolCore.cfg(CFG, "boot_policy");
  if (bp === "always_auto") STATE.mode = "auto";
  if (bp === "always_off") STATE.mode = "off";
}

function applyKvsItems(items) {
  var newCfg = {};
  var handle = function (key, value) {
    if (key === "pool.state") return;             // handled at boot only
    if (key === "pool.cfg._rev") {
      CFG_REV = typeof value === "string" ? value : JSON.stringify(value);
      return;
    }
    if (key === "pool.dev") {
      var d = null;
      try { d = JSON.parse(value); } catch (e) { d = null; }
      if (d !== null && typeof d === "object") {
        if (typeof d.relay_id === "number") DEV.relay_id = d.relay_id;
        if (typeof d.input_pump === "number") DEV.input_pump = d.input_pump;
        if (typeof d.state_save_s === "number") DEV.state_save_s = d.state_save_s;
        if (d.sensors !== undefined && d.sensors !== null) DEV.sensors = d.sensors;
      }
      return;
    }
    if (key.indexOf("pool.cfg.") === 0) {
      var name = key.slice(9);
      if (PoolCore.DEFAULTS[name] === undefined) return;   // unknown → ignore
      var v = value;
      if (typeof v === "string") {
        try { v = JSON.parse(v); } catch (e) { return; }
      }
      if (typeof v !== typeof PoolCore.DEFAULTS[name]) return;  // schema guard
      newCfg[name] = v;
    }
  };
  if (items !== undefined && items !== null) {
    if (items.length !== undefined) {
      for (var i = 0; i < items.length; i++) handle(items[i].key, items[i].value);
    } else {
      for (var k in items) handle(k, items[k].value);
    }
  }
  CFG = newCfg;   // missing keys fall back to DEFAULTS inside the core
  armTick();
}

function loadConfig(withState) {
  Shelly.call("KVS.GetMany", { match: "pool.*" }, function (res) {
    if (res === null || res === undefined) return;
    applyKvsItems(res.items);
    if (withState) {
      var sp = nowSpec();
      var st = null;
      if (res.items !== undefined && res.items !== null) {
        if (res.items.length !== undefined) {
          for (var i = 0; i < res.items.length; i++) {
            if (res.items[i].key === "pool.state") st = res.items[i].value;
          }
        } else if (res.items["pool.state"] !== undefined) {
          st = res.items["pool.state"].value;
        }
      }
      if (st !== null) restoreState(st, sp);
    }
  });
}

function tick() {
  var sp = nowSpec();
  var sw = Shelly.getComponentStatus("switch:" + JSON.stringify(DEV.relay_id));
  var power = 0;
  var relayActual = false;
  if (sw !== null && sw !== undefined) {
    if (typeof sw.apower === "number") power = sw.apower;
    relayActual = !!sw.output;
  }
  var lastTick = STATE._lt || sp.now;
  var dtv = sp.now - lastTick;
  if (dtv < 1) dtv = CUR_TICK_S > 0 ? CUR_TICK_S : 15;

  var cmds = CMD_QUEUE;
  CMD_QUEUE = [];

  var inputs = {
    now: sp.now, dt: dtv, uptime: sp.uptime,
    time_valid: sp.time_valid,
    local_min: sp.local_min, local_day: sp.local_day,
    sensors: readSensors(),
    power_w: power,
    relay_actual: relayActual,
    commands: cmds
  };

  var res = PoolCore.step(inputs, CFG, STATE);
  STATE = res.state;
  STATE._lt = sp.now;
  LAST_RESULT = {
    ts: sp.now, relay: res.relay, reason: res.reason,
    faults: res.faults, warnings: res.warnings,
    effective: res.effective, power_w: power,
    sensors: inputs.sensors, time_valid: sp.time_valid
  };

  // collect acks + persistence triggers from events
  var mustSave = false;
  for (var i = 0; i < res.events.length; i++) {
    var ev = res.events[i];
    if (ev.ev === "ack") {
      LAST_ACKS.push(ev);
      if (LAST_ACKS.length > 10) LAST_ACKS.splice(0, LAST_ACKS.length - 10);
    }
    if (ev.ev === "mode" || ev.ev === "fault" || ev.ev === "day_reset"
        || ev.ev === "calibrated") {
      mustSave = true;
    }
    if (ev.ev === "relay") SAVE_DIRTY = true;
  }

  if (APPLIED_RELAY === null || res.relay !== APPLIED_RELAY) {
    Shelly.call("Switch.Set", { id: DEV.relay_id, on: res.relay });
    APPLIED_RELAY = res.relay;
    SAVE_DIRTY = true;
  }

  if (mustSave) {
    persistState(true, sp.now);
  } else {
    if (sp.now - LAST_SAVE >= DEV.state_save_s) SAVE_DIRTY = true;
    persistState(false, sp.now);
  }

  // watchdog heartbeat — in-memory event, no flash wear
  Shelly.emitEvent("pool_hb", { t: sp.uptime, v: SCRIPT_VERSION });
}

function armTick() {
  var t = PoolCore.cfg(CFG, "tick_s");
  if (t === CUR_TICK_S && TICK_HANDLE !== null) return;
  if (TICK_HANDLE !== null) Timer.clear(TICK_HANDLE);
  CUR_TICK_S = t;
  TICK_HANDLE = Timer.set(t * 1000, true, tick);
}

// ---- HTTP endpoints (LAN, server-facing) ----------------------------------

function buildStatus() {
  return {
    script_version: SCRIPT_VERSION,
    cfg_rev: CFG_REV,
    mode: STATE.mode,
    mode_until: STATE.mode_until,
    relay: STATE.relay,
    heating: STATE.heating,
    run_s_today: STATE.run_s_today,
    heat_s_today: STATE.heat_s_today,
    lockouts: STATE.lockouts,
    pump_nominal: STATE.pump_nominal,
    last: LAST_RESULT,
    acks: LAST_ACKS,
    dev: DEV
  };
}

HTTPServer.registerEndpoint("status", function (req, res) {
  res.code = 200;
  res.headers = [["Content-Type", "application/json"]];
  res.body = JSON.stringify(buildStatus());
  res.send();
});

HTTPServer.registerEndpoint("cmd", function (req, res) {
  var body = null;
  try { body = JSON.parse(req.body); } catch (e) { body = null; }
  var out;
  if (body === null || typeof body !== "object" || typeof body.cmd !== "string") {
    res.code = 400;
    out = { ok: false, error: "bad_request" };
  } else if (CMD_QUEUE.length >= 8) {
    res.code = 429;
    out = { ok: false, error: "queue_full" };
  } else {
    CMD_QUEUE.push(body);
    Timer.set(50, false, tick);   // apply promptly, don't wait a full tick
    res.code = 200;
    out = { ok: true, queued: true };
  }
  res.headers = [["Content-Type", "application/json"]];
  res.body = JSON.stringify(out);
  res.send();
});

HTTPServer.registerEndpoint("reload", function (req, res) {
  loadConfig(false);
  res.code = 200;
  res.headers = [["Content-Type", "application/json"]];
  res.body = JSON.stringify({ ok: true });
  res.send();
});

// ---- physical button (detached input) -------------------------------------

Shelly.addEventHandler(function (event) {
  if (DEV.input_pump < 0) return;
  if (event === undefined || event.info === undefined) return;
  var inf = event.info;
  if (event.component !== "input:" + JSON.stringify(DEV.input_pump)) return;
  if (inf.event === "single_push") {
    if (STATE.mode === "force_on") {
      CMD_QUEUE.push({ cmd: "mode", mode: STATE.prev_mode, actor: "button" });
    } else {
      CMD_QUEUE.push({ cmd: "mode", mode: "force_on", actor: "button" });
    }
    Timer.set(50, false, tick);
  } else if (inf.event === "long_push") {
    for (var cls in STATE.lockouts) {
      if (STATE.lockouts[cls]) {
        CMD_QUEUE.push({ cmd: "reset_fault", "class": cls, actor: "button" });
      }
    }
    Timer.set(50, false, tick);
  } else if (inf.event === "double_push") {
    var m = STATE.mode === "off" ? "auto" : "off";
    CMD_QUEUE.push({ cmd: "mode", mode: m, actor: "button" });
    Timer.set(50, false, tick);
  }
});

// ---- boot -----------------------------------------------------------------

loadConfig(true);
// periodic slow KVS re-read so config converges even if a reload nudge is lost
Timer.set(120000, true, function () { loadConfig(false); });
armTick();
