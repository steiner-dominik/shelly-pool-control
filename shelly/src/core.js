// Decision core — mJS port of server/app/core/decision.py.
// MUST stay behavior-identical; both run shared/test-vectors/ in CI.
//
// Written in the restricted mJS dialect of Shelly Gen2+ scripting:
// no classes, no destructuring, no Array.map/filter, no Object.keys,
// no delete (cleared entries are set to 0/null instead — "active" means
// truthy), for-in for object iteration, JSON round-trip for deep copy.

var PoolCore = {};

PoolCore.DEFAULTS = {
  tick_s: 15,
  boot_settle_s: 20,
  boot_policy: "resume",
  water_min: -5.0, water_max: 45.0,
  mat_min: -20.0, mat_max: 95.0,
  air_min: -30.0, air_max: 50.0,
  roc_water: 5.0, roc_mat: 15.0, roc_air: 10.0,
  reset85_boot_s: 120,
  stuck_window_s: 21600,
  offset_water_a: 0.0, offset_water_b: 0.0,
  offset_mat_a: 0.0, offset_mat_b: 0.0, offset_air: 0.0,
  div_water: 1.5, div_mat: 4.0,
  agg_water: "avg", agg_mat: "avg",
  divpol_water: "conservative", divpol_mat: "conservative",
  dt_start: 5.0, dt_stop: 2.0,
  target_water_max: 29.0, water_hyst: 0.5,
  absolute_water_max: 32.0,
  window_start_min: 510, window_end_min: 1200,
  min_run_s: 600, min_pause_s: 300,
  filt_target_s: 14400,
  filt_check_min: 1020,
  filt_block_max_s: 7200, filt_block_pause_s: 900,
  day_reset_min: 0,
  mat_overtemp_limit: 70.0,
  mat_overtemp_action: "circulate",
  frost_enabled: true, frost_threshold: 2.0,
  frost_run_s: 600, frost_interval_s: 3600,
  pump_power_nominal: 0.0,
  pump_power_min_pct: 55.0, pump_power_max_pct: 130.0,
  no_power_threshold_w: 10.0,
  power_grace_s: 30, start_ignore_s: 5,
  power_fault_action: "lockout",
  retry_max: 3, retry_backoff_s: 300,
  pol_sensor_fail_water: "safe_off",
  pol_sensor_fail_mat: "safe_off",
  pol_sensor_fail_air: "warn_only",
  assumed_water_temp: 22.0,
  fallback_run_s: 900, fallback_interval_s: 7200,
  fallback_start_min: 600, fallback_end_min: 1020,
  fault_clear_hold_s: 300,
  force_timeout_s: 3600,
  boost_timeout_s: 14400,
  sample_enabled: false,
  sample_interval_s: 3600, sample_duration_s: 120
};

PoolCore.MODES = ["auto", "off", "force_on", "boost", "winter"];
PoolCore.POWER_FAULTS = ["no_power", "dry_run", "overload"];
PoolCore.SLOTS = ["water_a", "water_b", "mat_a", "mat_b", "air"];

PoolCore.cfg = function (config, key) {
  if (config[key] !== undefined) return config[key];
  return PoolCore.DEFAULTS[key];
};

PoolCore.initialState = function () {
  return {
    mode: "auto", prev_mode: "auto", mode_until: 0,
    relay: false, relay_since: 0, heating: false,
    last_stop: 0, day_key: 0,
    run_s_today: 0, heat_s_today: 0,
    faults: {}, gone: {}, lockouts: {}, pending: {}, retry: {},
    frost_last: 0, fallback_last: 0, sample_last: 0,
    filt_running: false, filt_block_start: 0, filt_pause_until: 0,
    prev_valid: {}, stuck_ref: {},
    pump_nominal: 0.0
  };
};

function _roleOf(slot) {
  if (slot === "water_a" || slot === "water_b") return "water";
  if (slot === "mat_a" || slot === "mat_b") return "mat";
  return "air";
}

function _validateSlot(slot, raw, inputs, config, state, warnings) {
  if (raw === null || raw === undefined) return null;
  var role = _roleOf(slot);
  var v = raw + PoolCore.cfg(config, "offset_" + slot);
  var lo = PoolCore.cfg(config, role + "_min");
  var hi = PoolCore.cfg(config, role + "_max");
  if (v < lo || v > hi) return null;
  if (raw === 85.0 && inputs.uptime < PoolCore.cfg(config, "reset85_boot_s")) {
    return null;
  }
  var roc = PoolCore.cfg(config, "roc_" + role);
  var pv = state.prev_valid[slot];
  var now = inputs.now;
  var dtv = inputs.dt;
  if (pv !== undefined && pv !== null && (now - pv.ts) <= 2 * dtv
      && Math.abs(v - pv.t) > roc) {
    return null;
  }
  state.prev_valid[slot] = { t: v, ts: now };
  var ref = state.stuck_ref[slot];
  if (ref === undefined || ref === null || Math.abs(v - ref.t) >= 0.1) {
    state.stuck_ref[slot] = { t: v, ts: now };
  } else if (now - ref.ts > PoolCore.cfg(config, "stuck_window_s")) {
    warnings.push("stuck_" + slot);
  }
  return v;
}

function _aggregatePair(role, a, b, config, warnings) {
  var pol;
  if (a !== null && b !== null) {
    var div = PoolCore.cfg(config, "div_" + role);
    if (Math.abs(a - b) <= div) {
      pol = PoolCore.cfg(config, "agg_" + role);
      if (pol === "min") return a < b ? a : b;
      if (pol === "max") return a > b ? a : b;
      if (pol === "prefer_a") return a;
      return (a + b) / 2.0;
    }
    warnings.push("divergence_" + role);
    pol = PoolCore.cfg(config, "divpol_" + role);
    if (pol === "avg") return (a + b) / 2.0;
    if (pol === "prefer_a") return a;
    if (role === "water") return a > b ? a : b;
    return a < b ? a : b;
  }
  if (a !== null) { warnings.push("degraded_" + role); return a; }
  if (b !== null) { warnings.push("degraded_" + role); return b; }
  return null;
}

function _isActive(map, cls) {
  return map[cls] !== undefined && map[cls] !== null && map[cls] !== 0;
}

function _setFault(state, cls, now, events) {
  if (!_isActive(state.faults, cls)) {
    state.faults[cls] = now;
    events.push({ ev: "fault", cls: cls, active: true });
  }
  if (_isActive(state.gone, cls)) state.gone[cls] = 0;
}

function _condFault(state, cls, present, now, config, events) {
  if (present) {
    _setFault(state, cls, now, events);
  } else if (_isActive(state.faults, cls) && !_isActive(state.lockouts, cls)) {
    if (!_isActive(state.gone, cls)) {
      state.gone[cls] = now;
    } else if (now - state.gone[cls] >= PoolCore.cfg(config, "fault_clear_hold_s")) {
      state.faults[cls] = 0;
      state.gone[cls] = 0;
      events.push({ ev: "fault", cls: cls, active: false });
    }
  }
}

function _lockout(state, cls, now, events) {
  if (!_isActive(state.lockouts, cls)) state.lockouts[cls] = now;
  _setFault(state, cls, now, events);
}

function _inWindow(localMin, startMin, endMin) {
  if (startMin <= endMin) return localMin >= startMin && localMin < endMin;
  return localMin >= startMin || localMin < endMin;
}

function _clampNum(v, lo, hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

function _applyCommands(inputs, config, state, events) {
  var cmds = inputs.commands || [];
  var now = inputs.now;
  for (var i = 0; i < cmds.length; i++) {
    var c = cmds[i];
    var kind = c.cmd;
    var ok = false;
    var err = "";
    if (kind === "mode") {
      var m = c.mode;
      var known = false;
      for (var j = 0; j < PoolCore.MODES.length; j++) {
        if (PoolCore.MODES[j] === m) known = true;
      }
      if (!known) {
        err = "bad_mode";
      } else {
        if (state.mode !== "force_on" && state.mode !== "boost") {
          state.prev_mode = state.mode;
        }
        state.mode = m;
        state.mode_until = 0;
        if (m === "force_on") {
          var t = c.timeout_s;
          if (t === undefined || t === null) {
            t = PoolCore.cfg(config, "force_timeout_s");
          }
          state.mode_until = now + _clampNum(Math.floor(t), 60, 86400);
        }
        if (m === "boost") {
          var bt = PoolCore.cfg(config, "boost_timeout_s");
          if (bt > 0) state.mode_until = now + Math.floor(bt);
        }
        ok = true;
        events.push({ ev: "mode", mode: m, source: c.actor || "cmd" });
      }
    } else if (kind === "run") {
      var d = c.duration_s;
      if (d === undefined || d === null || Math.floor(d) <= 0) {
        err = "bad_duration";
      } else {
        if (state.mode !== "force_on" && state.mode !== "boost") {
          state.prev_mode = state.mode;
        }
        state.mode = "force_on";
        state.mode_until = now + _clampNum(Math.floor(d), 60, 86400);
        ok = true;
        events.push({ ev: "mode", mode: "force_on", source: c.actor || "cmd" });
      }
    } else if (kind === "reset_fault") {
      var cls = c["class"];
      if (_isActive(state.lockouts, cls)) {
        state.lockouts[cls] = 0;
        if (_isActive(state.faults, cls)) {
          state.faults[cls] = 0;
          events.push({ ev: "fault", cls: cls, active: false });
        }
        if (state.retry[cls] !== undefined) state.retry[cls] = null;
        if (_isActive(state.pending, cls)) state.pending[cls] = 0;
        ok = true;
      } else {
        err = "no_lockout";
      }
    } else if (kind === "calibrate") {
      var p = c.power_w;
      if (p === undefined || p === null || p <= 0) {
        err = "bad_power";
      } else {
        state.pump_nominal = p;
        events.push({ ev: "calibrated", power_w: p });
        ok = true;
      }
    } else {
      err = "unknown";
    }
    var ack = { ev: "ack", ok: ok };
    if (c.msg_id !== undefined) ack.msg_id = c.msg_id;
    if (!ok) ack.error = err;
    events.push(ack);
  }
}

function _powerCond(cls, checking, power, nominal, config) {
  if (!checking) return false;
  if (cls === "no_power") {
    return power < PoolCore.cfg(config, "no_power_threshold_w");
  }
  if (nominal <= 0) return false;
  if (cls === "dry_run") {
    return power >= PoolCore.cfg(config, "no_power_threshold_w")
      && power < nominal * PoolCore.cfg(config, "pump_power_min_pct") / 100.0;
  }
  return power > nominal * PoolCore.cfg(config, "pump_power_max_pct") / 100.0;
}

function _fallbackPattern(config, state, timeValid, localMin, now) {
  if (timeValid && !_inWindow(localMin,
      PoolCore.cfg(config, "fallback_start_min"),
      PoolCore.cfg(config, "fallback_end_min"))) {
    return { relay: false, reason: "fallback_wait", heating: false };
  }
  if (now - state.fallback_last < PoolCore.cfg(config, "fallback_run_s")) {
    return { relay: true, reason: "fallback", heating: false };
  }
  if (now - state.fallback_last >= PoolCore.cfg(config, "fallback_interval_s")) {
    state.fallback_last = now;
    return { relay: true, reason: "fallback", heating: false };
  }
  return { relay: false, reason: "fallback_wait", heating: false };
}

function _autoDecision(inputs, config, state, events, waterEff, matEff, delta,
                       windowOk, timeValid, localMin, now) {
  if (_isActive(state.faults, "mat_overtemp")
      && PoolCore.cfg(config, "mat_overtemp_action") === "circulate"
      && waterEff !== null
      && waterEff < PoolCore.cfg(config, "absolute_water_max")) {
    return { relay: true, reason: "overtemp_circulate", heating: false };
  }

  var waterFailed = waterEff === null;
  var matFailed = matEff === null;
  if (waterFailed || matFailed) {
    var pol = waterFailed ? PoolCore.cfg(config, "pol_sensor_fail_water")
                          : PoolCore.cfg(config, "pol_sensor_fail_mat");
    if (waterFailed && matFailed) {
      var pw = PoolCore.cfg(config, "pol_sensor_fail_water");
      var pm = PoolCore.cfg(config, "pol_sensor_fail_mat");
      if (pw === "fallback_schedule" && pm === "fallback_schedule") {
        pol = "fallback_schedule";
      } else {
        pol = "safe_off";
      }
    }
    if (pol === "fallback_schedule") {
      return _fallbackPattern(config, state, timeValid, localMin, now);
    }
    if (pol === "continue_mat_only" && waterFailed && !matFailed) {
      waterEff = PoolCore.cfg(config, "assumed_water_temp");
      delta = matEff - waterEff;
    } else {
      var cls = waterFailed ? "sensor_fail_water" : "sensor_fail_mat";
      return { relay: false, reason: "fault:" + cls, heating: false };
    }
  }

  if (PoolCore.cfg(config, "pol_sensor_fail_air") === "safe_off"
      && _isActive(state.faults, "sensor_fail_air")) {
    return { relay: false, reason: "fault:sensor_fail_air", heating: false };
  }

  var runLen = now - state.relay_since;
  var blockedReason = "idle";
  if (state.relay && state.heating) {
    if (waterEff >= PoolCore.cfg(config, "target_water_max")) {
      return { relay: false, reason: "water_max", heating: false };
    }
    if (!windowOk) {
      return { relay: false, reason: "window", heating: false };
    }
    if (delta <= PoolCore.cfg(config, "dt_stop")) {
      if (runLen >= PoolCore.cfg(config, "min_run_s")) {
        return { relay: false, reason: "dt_stop", heating: false };
      }
      return { relay: true, reason: "min_run", heating: true };
    }
    return { relay: true, reason: "heating", heating: true };
  }
  if (delta >= PoolCore.cfg(config, "dt_start")) {
    var startOk = false;
    var reason = "";
    if (waterEff >= PoolCore.cfg(config, "target_water_max")
        - PoolCore.cfg(config, "water_hyst")) {
      reason = "water_max";
    } else if (!windowOk) {
      reason = "window";
    } else if (now - state.last_stop < PoolCore.cfg(config, "min_pause_s")
        && state.last_stop > 0) {
      reason = "min_pause";
    } else {
      startOk = true;
      reason = "dt_start";
    }
    if (startOk) {
      return { relay: true, reason: "dt_start", heating: true };
    }
    blockedReason = reason;
  }

  if (timeValid && localMin >= PoolCore.cfg(config, "filt_check_min")
      && state.run_s_today < PoolCore.cfg(config, "filt_target_s")) {
    if (now < state.filt_pause_until) {
      return { relay: false, reason: "quota_pause", heating: false };
    }
    if (!state.filt_running) {
      state.filt_running = true;
      state.filt_block_start = now;
    }
    if (now - state.filt_block_start >= PoolCore.cfg(config, "filt_block_max_s")) {
      state.filt_running = false;
      state.filt_pause_until = now + PoolCore.cfg(config, "filt_block_pause_s");
      return { relay: false, reason: "quota_pause", heating: false };
    }
    return { relay: true, reason: "quota_deficit", heating: false };
  }

  if (PoolCore.cfg(config, "sample_enabled")) {
    if (now - state.sample_last < PoolCore.cfg(config, "sample_duration_s")) {
      return { relay: true, reason: "sample", heating: false };
    }
    if (now - state.sample_last >= PoolCore.cfg(config, "sample_interval_s")) {
      state.sample_last = now;
      return { relay: true, reason: "sample", heating: false };
    }
  }

  return { relay: false, reason: blockedReason, heating: false };
}

PoolCore.step = function (inputs, config, stateIn) {
  var state = JSON.parse(JSON.stringify(stateIn));
  var events = [];
  var warnings = [];
  var now = inputs.now;
  var dtv = inputs.dt;
  var timeValid = !!inputs.time_valid;
  var localMin = inputs.local_min || 0;
  var localDay = inputs.local_day || 0;
  var i, cls;

  if (state.relay) {
    state.run_s_today += dtv;
    if (state.heating) state.heat_s_today += dtv;
  }

  if (timeValid && localMin >= PoolCore.cfg(config, "day_reset_min")
      && localDay !== state.day_key) {
    if (state.day_key !== 0) {
      state.run_s_today = 0;
      state.heat_s_today = 0;
      events.push({ ev: "day_reset" });
    }
    state.day_key = localDay;
  }

  if (!timeValid) warnings.push("time_invalid");

  _applyCommands(inputs, config, state, events);

  if ((state.mode === "force_on" || state.mode === "boost")
      && state.mode_until > 0 && now >= state.mode_until) {
    events.push({ ev: "mode", mode: state.prev_mode, source: "timeout" });
    state.mode = state.prev_mode;
    state.mode_until = 0;
  }

  var sens = inputs.sensors || {};
  var vals = {};
  for (i = 0; i < PoolCore.SLOTS.length; i++) {
    var slot = PoolCore.SLOTS[i];
    vals[slot] = _validateSlot(slot, sens[slot], inputs, config, state, warnings);
  }
  var waterEff = _aggregatePair("water", vals.water_a, vals.water_b, config, warnings);
  var matEff = _aggregatePair("mat", vals.mat_a, vals.mat_b, config, warnings);
  var airEff = vals.air;

  _condFault(state, "sensor_fail_water", waterEff === null, now, config, events);
  _condFault(state, "sensor_fail_mat", matEff === null, now, config, events);
  _condFault(state, "sensor_fail_air", airEff === null, now, config, events);

  var otAction = PoolCore.cfg(config, "mat_overtemp_action");
  var matHot = matEff !== null
    && matEff >= PoolCore.cfg(config, "mat_overtemp_limit");
  if (matHot && otAction === "lockout") {
    _lockout(state, "mat_overtemp", now, events);
  } else {
    _condFault(state, "mat_overtemp", matHot, now, config, events);
  }

  var power = inputs.power_w || 0.0;
  var nominal = state.pump_nominal || PoolCore.cfg(config, "pump_power_nominal");
  var onFor = state.relay ? now - state.relay_since : 0;
  var checking = state.relay && onFor > PoolCore.cfg(config, "start_ignore_s");

  for (i = 0; i < PoolCore.POWER_FAULTS.length; i++) {
    cls = PoolCore.POWER_FAULTS[i];
    if (_powerCond(cls, checking, power, nominal, config)) {
      if (!_isActive(state.pending, cls)) {
        state.pending[cls] = now;
      } else if (now - state.pending[cls] >= PoolCore.cfg(config, "power_grace_s")) {
        var action = PoolCore.cfg(config, "power_fault_action");
        if (cls === "overload" || action === "lockout") {
          _lockout(state, cls, now, events);
        } else {
          var r = state.retry[cls];
          if (r === undefined || r === null) r = { count: 0, next: 0 };
          r.count += 1;
          if (r.count > PoolCore.cfg(config, "retry_max")) {
            _lockout(state, cls, now, events);
          } else {
            r.next = now + PoolCore.cfg(config, "retry_backoff_s");
            state.retry[cls] = r;
            _setFault(state, cls, now, events);
          }
        }
        state.pending[cls] = 0;
      }
    } else if (_isActive(state.pending, cls)) {
      state.pending[cls] = 0;
    }
  }

  for (i = 0; i < PoolCore.POWER_FAULTS.length; i++) {
    cls = PoolCore.POWER_FAULTS[i];
    if (_isActive(state.faults, cls) && !_isActive(state.lockouts, cls)) {
      var rr = state.retry[cls];
      if (rr !== undefined && rr !== null && now >= rr.next) {
        state.faults[cls] = 0;
        events.push({ ev: "fault", cls: cls, active: false });
      }
    }
  }

  var stuckCond = !state.relay
    && now - state.last_stop > PoolCore.cfg(config, "power_grace_s")
    && power >= PoolCore.cfg(config, "no_power_threshold_w");
  _condFault(state, "relay_stuck", stuckCond, now, config, events);

  var relay = false;
  var reason = "idle";
  var heating = false;

  var powerBlock = false;
  for (i = 0; i < PoolCore.POWER_FAULTS.length; i++) {
    if (_isActive(state.faults, PoolCore.POWER_FAULTS[i])) {
      powerBlock = true;
      reason = "fault:" + PoolCore.POWER_FAULTS[i];
      break;
    }
  }
  var otLocked = _isActive(state.lockouts, "mat_overtemp");

  var windowOk = !timeValid || _inWindow(localMin,
    PoolCore.cfg(config, "window_start_min"),
    PoolCore.cfg(config, "window_end_min"));
  var delta = null;
  if (waterEff !== null && matEff !== null) delta = matEff - waterEff;

  var frostActive = false;
  if (PoolCore.cfg(config, "frost_enabled") && state.mode !== "winter"
      && airEff !== null
      && airEff <= PoolCore.cfg(config, "frost_threshold")) {
    if (now - state.frost_last < PoolCore.cfg(config, "frost_run_s")) {
      frostActive = true;
    } else if (now - state.frost_last >= PoolCore.cfg(config, "frost_interval_s")) {
      state.frost_last = now;
      frostActive = true;
    }
  }

  if (inputs.uptime < PoolCore.cfg(config, "boot_settle_s")) {
    reason = "settle";
  } else if (state.mode === "winter") {
    reason = "winter";
  } else if (powerBlock || otLocked) {
    if (otLocked) reason = "fault:mat_overtemp";
  } else if (state.mode === "force_on") {
    relay = true;
    reason = "force";
  } else if (frostActive) {
    relay = true;
    reason = "frost";
  } else if (state.mode === "off") {
    reason = "off";
  } else if (state.mode === "boost") {
    if (waterEff === null) {
      reason = "fault:sensor_fail_water";
    } else if (waterEff >= PoolCore.cfg(config, "absolute_water_max")) {
      reason = "abs_water_max";
    } else if (delta !== null && delta > PoolCore.cfg(config, "dt_stop")) {
      relay = true;
      heating = true;
      reason = "boost";
    } else {
      reason = "boost_wait";
    }
  } else {
    var d = _autoDecision(inputs, config, state, events, waterEff, matEff,
      delta, windowOk, timeValid, localMin, now);
    relay = d.relay;
    reason = d.reason;
    heating = d.heating;
  }

  if (relay !== state.relay) {
    events.push({ ev: "relay", on: relay, reason: reason });
    state.relay_since = now;
    if (!relay) {
      state.last_stop = now;
      state.filt_running = false;
    }
  }
  state.relay = relay;
  state.heating = heating;
  if (!relay) state.filt_running = false;

  var active = [];
  for (var k in state.faults) {
    if (_isActive(state.faults, k)) active.push(k);
  }
  // insertion sort (mJS has no Array.sort)
  for (i = 1; i < active.length; i++) {
    var key = active[i];
    var j2 = i - 1;
    while (j2 >= 0 && active[j2] > key) {
      active[j2 + 1] = active[j2];
      j2 -= 1;
    }
    active[j2 + 1] = key;
  }

  return {
    state: state,
    relay: relay,
    reason: reason,
    detail: "",
    faults: active,
    warnings: warnings,
    events: events,
    effective: { water: waterEff, mat: matEff, air: airEff, delta: delta }
  };
};
