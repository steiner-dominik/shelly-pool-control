"""Decision core — pure, deterministic, no I/O.

This is the Python reference implementation of ``shared/logic-spec.md``.
It is mirrored 1:1 by ``shelly/src/core.js`` (restricted mJS dialect) and both
must pass the shared vectors in ``shared/test-vectors/``.

Style note: written intentionally in a "portable subset" (flat dicts, explicit
loops, no dataclasses) so the two implementations stay easy to diff.
"""

from __future__ import annotations

import copy
from typing import Any

DEFAULTS: dict[str, Any] = {
    # loop & boot
    "tick_s": 15,
    "boot_settle_s": 20,
    "boot_policy": "resume",  # resume | always_auto | always_off
    # sensor validation
    "water_min": -5.0, "water_max": 45.0,
    "mat_min": -20.0, "mat_max": 95.0,
    "air_min": -30.0, "air_max": 50.0,
    "roc_water": 5.0, "roc_mat": 15.0, "roc_air": 10.0,
    "reset85_boot_s": 120,
    "stuck_window_s": 21600,
    "offset_water_a": 0.0, "offset_water_b": 0.0,
    "offset_mat_a": 0.0, "offset_mat_b": 0.0, "offset_air": 0.0,
    "div_water": 1.5, "div_mat": 4.0,
    "agg_water": "avg", "agg_mat": "avg",       # avg | min | max | prefer_a
    "divpol_water": "conservative", "divpol_mat": "conservative",
    # heating
    "dt_start": 5.0, "dt_stop": 2.0,
    "target_water_max": 29.0, "water_hyst": 0.5,
    "absolute_water_max": 32.0,
    "window_start_min": 510, "window_end_min": 1200,
    "min_run_s": 600, "min_pause_s": 300,
    # filtration
    "filt_target_s": 14400,
    "filt_check_min": 1020,
    "filt_block_max_s": 7200, "filt_block_pause_s": 900,
    "day_reset_min": 0,
    # overtemp
    "mat_overtemp_limit": 70.0,
    "mat_overtemp_action": "circulate",  # circulate | alert_only | lockout
    # frost
    "frost_enabled": True, "frost_threshold": 2.0,
    "frost_run_s": 600, "frost_interval_s": 3600,
    # pump power signature
    "pump_power_nominal": 0.0,
    "pump_power_min_pct": 55.0, "pump_power_max_pct": 130.0,
    "no_power_threshold_w": 10.0,
    "power_grace_s": 30, "start_ignore_s": 5,
    "power_fault_action": "lockout",  # lockout | retry
    "retry_max": 3, "retry_backoff_s": 300,
    # fault policies
    "pol_sensor_fail_water": "safe_off",  # safe_off | fallback_schedule | continue_mat_only
    "pol_sensor_fail_mat": "safe_off",    # safe_off | fallback_schedule
    "pol_sensor_fail_air": "warn_only",   # warn_only | safe_off
    "assumed_water_temp": 22.0,
    "fallback_run_s": 900, "fallback_interval_s": 7200,
    "fallback_start_min": 600, "fallback_end_min": 1020,
    "fault_clear_hold_s": 300,
    # modes & sampling
    "force_timeout_s": 3600,
    "boost_timeout_s": 14400,
    "sample_enabled": False,
    "sample_interval_s": 3600, "sample_duration_s": 120,
}

MODES = ["auto", "off", "force_on", "boost", "winter"]
POWER_FAULTS = ["no_power", "dry_run", "overload"]
SLOTS = ["water_a", "water_b", "mat_a", "mat_b", "air"]


def cfg(config: dict, key: str):
    if key in config:
        return config[key]
    return DEFAULTS[key]


def initial_state() -> dict:
    return {
        "mode": "auto",
        "prev_mode": "auto",
        "mode_until": 0,
        "relay": False,
        "relay_since": 0,
        "heating": False,
        "last_stop": 0,
        "day_key": 0,
        "run_s_today": 0,
        "heat_s_today": 0,
        "faults": {},      # class -> since (epoch)
        "gone": {},        # class -> condition-last-gone epoch (for clear hold)
        "lockouts": {},    # class -> since
        "pending": {},     # power fault class -> condition-first-seen epoch
        "retry": {},       # class -> {"count": n, "next": epoch}
        "frost_last": 0,
        "fallback_last": 0,
        "sample_last": 0,
        "filt_running": False,
        "filt_block_start": 0,
        "filt_pause_until": 0,
        "prev_valid": {},  # slot -> {"t": v, "ts": epoch}
        "stuck_ref": {},   # slot -> {"t": v, "ts": epoch}
        "pump_nominal": 0.0,
    }


def _role_of(slot: str) -> str:
    if slot == "water_a" or slot == "water_b":
        return "water"
    if slot == "mat_a" or slot == "mat_b":
        return "mat"
    return "air"


def _validate_slot(slot, raw, inputs, config, state, warnings):
    """Return calibrated value or None if invalid."""
    if raw is None:
        return None
    role = _role_of(slot)
    v = float(raw) + float(cfg(config, "offset_" + slot))
    lo = cfg(config, role + "_min")
    hi = cfg(config, role + "_max")
    if v < lo or v > hi:
        return None
    if raw == 85.0 and inputs["uptime"] < cfg(config, "reset85_boot_s"):
        return None
    roc = cfg(config, "roc_" + role)
    pv = state["prev_valid"].get(slot)
    now = inputs["now"]
    dt = inputs["dt"]
    if pv is not None and (now - pv["ts"]) <= 2 * dt and abs(v - pv["t"]) > roc:
        # Spike vs. the last valid reading: reject this tick. If the value
        # persists, prev_valid ages out (> 2 ticks) and it is accepted.
        return None
    state["prev_valid"][slot] = {"t": v, "ts": now}
    # advisory stuck detection
    ref = state["stuck_ref"].get(slot)
    if ref is None or abs(v - ref["t"]) >= 0.1:
        state["stuck_ref"][slot] = {"t": v, "ts": now}
    elif now - ref["ts"] > cfg(config, "stuck_window_s"):
        warnings.append("stuck_" + slot)
    return v


def _aggregate_pair(role, a, b, config, warnings):
    """Return effective value or None if the role failed."""
    if a is not None and b is not None:
        div = cfg(config, "div_" + role)
        if abs(a - b) <= div:
            pol = cfg(config, "agg_" + role)
            if pol == "min":
                return a if a < b else b
            if pol == "max":
                return a if a > b else b
            if pol == "prefer_a":
                return a
            return (a + b) / 2.0
        warnings.append("divergence_" + role)
        pol = cfg(config, "divpol_" + role)
        if pol == "avg":
            return (a + b) / 2.0
        if pol == "prefer_a":
            return a
        # conservative: the value that makes heating LESS likely
        if role == "water":
            return a if a > b else b   # max water
        return a if a < b else b       # min mat
    if a is not None:
        warnings.append("degraded_" + role)
        return a
    if b is not None:
        warnings.append("degraded_" + role)
        return b
    return None


def _set_fault(state, cls, now, events):
    if cls not in state["faults"]:
        state["faults"][cls] = now
        events.append({"ev": "fault", "cls": cls, "active": True})
    if cls in state["gone"]:
        del state["gone"][cls]


def _cond_fault(state, cls, present, now, config, events):
    """Lifecycle for condition faults with auto-clear hold."""
    if present:
        _set_fault(state, cls, now, events)
    elif cls in state["faults"] and cls not in state["lockouts"]:
        if cls not in state["gone"]:
            state["gone"][cls] = now
        elif now - state["gone"][cls] >= cfg(config, "fault_clear_hold_s"):
            del state["faults"][cls]
            del state["gone"][cls]
            events.append({"ev": "fault", "cls": cls, "active": False})


def _lockout(state, cls, now, events):
    if cls not in state["lockouts"]:
        state["lockouts"][cls] = now
    _set_fault(state, cls, now, events)


def _in_window(local_min, start_min, end_min):
    if start_min <= end_min:
        return start_min <= local_min < end_min
    return local_min >= start_min or local_min < end_min  # over midnight


def _clamp(v, lo, hi):
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def _apply_commands(inputs, config, state, events):
    cmds = inputs.get("commands") or []
    now = inputs["now"]
    for i in range(len(cmds)):
        c = cmds[i]
        kind = c.get("cmd")
        ok = False
        err = ""
        if kind == "mode":
            m = c.get("mode")
            if m not in MODES:
                err = "bad_mode"
            else:
                if state["mode"] not in ("force_on", "boost"):
                    state["prev_mode"] = state["mode"]
                state["mode"] = m
                state["mode_until"] = 0
                if m == "force_on":
                    t = c.get("timeout_s")
                    if t is None:
                        t = cfg(config, "force_timeout_s")
                    state["mode_until"] = now + _clamp(int(t), 60, 86400)
                if m == "boost":
                    bt = cfg(config, "boost_timeout_s")
                    if bt > 0:
                        state["mode_until"] = now + int(bt)
                ok = True
                events.append({"ev": "mode", "mode": m,
                               "source": c.get("actor", "cmd")})
        elif kind == "run":
            d = c.get("duration_s")
            if d is None or int(d) <= 0:
                err = "bad_duration"
            else:
                if state["mode"] not in ("force_on", "boost"):
                    state["prev_mode"] = state["mode"]
                state["mode"] = "force_on"
                state["mode_until"] = now + _clamp(int(d), 60, 86400)
                ok = True
                events.append({"ev": "mode", "mode": "force_on",
                               "source": c.get("actor", "cmd")})
        elif kind == "reset_fault":
            cls = c.get("class")
            if cls in state["lockouts"]:
                del state["lockouts"][cls]
                if cls in state["faults"]:
                    del state["faults"][cls]
                    events.append({"ev": "fault", "cls": cls, "active": False})
                if cls in state["retry"]:
                    del state["retry"][cls]
                if cls in state["pending"]:
                    del state["pending"][cls]
                ok = True
            else:
                err = "no_lockout"
        elif kind == "calibrate":
            p = c.get("power_w")
            if p is None or float(p) <= 0:
                err = "bad_power"
            else:
                state["pump_nominal"] = float(p)
                events.append({"ev": "calibrated", "power_w": float(p)})
                ok = True
        else:
            err = "unknown"
        ack = {"ev": "ack", "ok": ok}
        if "msg_id" in c:
            ack["msg_id"] = c["msg_id"]
        if not ok:
            ack["error"] = err
        events.append(ack)


def step(inputs: dict, config: dict, state_in: dict) -> dict:
    state = copy.deepcopy(state_in)
    events: list[dict] = []
    warnings: list[str] = []
    now = inputs["now"]
    dt = inputs["dt"]
    time_valid = bool(inputs.get("time_valid"))
    local_min = inputs.get("local_min", 0)
    local_day = inputs.get("local_day", 0)

    # -- runtime accounting for the elapsed interval (previous decision) -----
    if state["relay"]:
        state["run_s_today"] += dt
        if state["heating"]:
            state["heat_s_today"] += dt

    # -- daily counter reset -------------------------------------------------
    if time_valid and local_min >= cfg(config, "day_reset_min") \
            and local_day != state["day_key"]:
        if state["day_key"] != 0:
            state["run_s_today"] = 0
            state["heat_s_today"] = 0
            events.append({"ev": "day_reset"})
        state["day_key"] = local_day

    if not time_valid:
        warnings.append("time_invalid")

    # -- commands ------------------------------------------------------------
    _apply_commands(inputs, config, state, events)

    # -- mode expiry ---------------------------------------------------------
    if state["mode"] in ("force_on", "boost") and state["mode_until"] > 0 \
            and now >= state["mode_until"]:
        events.append({"ev": "mode", "mode": state["prev_mode"],
                       "source": "timeout"})
        state["mode"] = state["prev_mode"]
        state["mode_until"] = 0

    # -- sensor pipeline -----------------------------------------------------
    sens = inputs.get("sensors") or {}
    vals = {}
    for i in range(len(SLOTS)):
        slot = SLOTS[i]
        vals[slot] = _validate_slot(slot, sens.get(slot), inputs, config,
                                    state, warnings)
    water_eff = _aggregate_pair("water", vals["water_a"], vals["water_b"],
                                config, warnings)
    mat_eff = _aggregate_pair("mat", vals["mat_a"], vals["mat_b"],
                              config, warnings)
    air_eff = vals["air"]

    _cond_fault(state, "sensor_fail_water", water_eff is None, now, config, events)
    _cond_fault(state, "sensor_fail_mat", mat_eff is None, now, config, events)
    _cond_fault(state, "sensor_fail_air", air_eff is None, now, config, events)

    # -- mat overtemperature -------------------------------------------------
    ot_action = cfg(config, "mat_overtemp_action")
    mat_hot = mat_eff is not None and mat_eff >= cfg(config, "mat_overtemp_limit")
    if mat_hot and ot_action == "lockout":
        _lockout(state, "mat_overtemp", now, events)
    else:
        _cond_fault(state, "mat_overtemp", mat_hot, now, config, events)

    # -- pump power signature (checked against the *previous* commanded state)
    power = float(inputs.get("power_w", 0.0))
    nominal = state["pump_nominal"] or cfg(config, "pump_power_nominal")
    on_for = now - state["relay_since"] if state["relay"] else 0
    checking = state["relay"] and on_for > cfg(config, "start_ignore_s")

    def _power_cond(cls):
        if not checking:
            return False
        if cls == "no_power":
            return power < cfg(config, "no_power_threshold_w")
        if nominal <= 0:
            return False
        if cls == "dry_run":
            return (power >= cfg(config, "no_power_threshold_w")
                    and power < nominal * cfg(config, "pump_power_min_pct") / 100.0)
        return power > nominal * cfg(config, "pump_power_max_pct") / 100.0

    for i in range(len(POWER_FAULTS)):
        cls = POWER_FAULTS[i]
        if _power_cond(cls):
            if cls not in state["pending"]:
                state["pending"][cls] = now
            elif now - state["pending"][cls] >= cfg(config, "power_grace_s"):
                action = cfg(config, "power_fault_action")
                if cls == "overload" or action == "lockout":
                    _lockout(state, cls, now, events)
                else:  # retry policy
                    r = state["retry"].get(cls) or {"count": 0, "next": 0}
                    r["count"] += 1
                    if r["count"] > cfg(config, "retry_max"):
                        _lockout(state, cls, now, events)
                    else:
                        r["next"] = now + cfg(config, "retry_backoff_s")
                        state["retry"][cls] = r
                        _set_fault(state, cls, now, events)
                del state["pending"][cls]
        else:
            if cls in state["pending"]:
                del state["pending"][cls]

    # retry faults auto-clear once their backoff expires (next attempt allowed)
    for i in range(len(POWER_FAULTS)):
        cls = POWER_FAULTS[i]
        if cls in state["faults"] and cls not in state["lockouts"]:
            r = state["retry"].get(cls)
            if r is not None and now >= r["next"]:
                del state["faults"][cls]
                events.append({"ev": "fault", "cls": cls, "active": False})

    # relay commanded off but the pump draws power → welded relay
    stuck_cond = (not state["relay"]
                  and now - state["last_stop"] > cfg(config, "power_grace_s")
                  and power >= cfg(config, "no_power_threshold_w"))
    _cond_fault(state, "relay_stuck", stuck_cond, now, config, events)

    # -- relay decision ------------------------------------------------------
    relay = False
    reason = "idle"
    detail = ""
    heating = False

    power_block = False
    for i in range(len(POWER_FAULTS)):
        if POWER_FAULTS[i] in state["faults"]:
            power_block = True
            reason = "fault:" + POWER_FAULTS[i]
            break
    ot_locked = "mat_overtemp" in state["lockouts"]

    window_ok = (not time_valid) or _in_window(
        local_min, cfg(config, "window_start_min"), cfg(config, "window_end_min"))
    delta = None
    if water_eff is not None and mat_eff is not None:
        delta = mat_eff - water_eff

    frost_active = False
    if cfg(config, "frost_enabled") and state["mode"] != "winter" \
            and air_eff is not None and air_eff <= cfg(config, "frost_threshold"):
        if now - state["frost_last"] < cfg(config, "frost_run_s"):
            frost_active = True
        elif now - state["frost_last"] >= cfg(config, "frost_interval_s"):
            state["frost_last"] = now
            frost_active = True

    if inputs["uptime"] < cfg(config, "boot_settle_s"):
        reason = "settle"
    elif state["mode"] == "winter":
        reason = "winter"
    elif power_block or ot_locked:
        if ot_locked:
            reason = "fault:mat_overtemp"
        # relay stays off; reason already set for power faults
    elif state["mode"] == "force_on":
        relay = True
        reason = "force"
    elif frost_active:
        relay = True
        reason = "frost"
    elif state["mode"] == "off":
        reason = "off"
    elif state["mode"] == "boost":
        if water_eff is None:
            reason = "fault:sensor_fail_water"
        elif water_eff >= cfg(config, "absolute_water_max"):
            reason = "abs_water_max"
        elif delta is not None and delta > cfg(config, "dt_stop"):
            relay = True
            heating = True
            reason = "boost"
        else:
            reason = "boost_wait"
    else:  # auto
        relay, reason, heating = _auto_decision(
            inputs, config, state, events, water_eff, mat_eff, delta,
            window_ok, time_valid, local_min, now)

    # -- apply relay change --------------------------------------------------
    if relay != state["relay"]:
        events.append({"ev": "relay", "on": relay, "reason": reason})
        state["relay_since"] = now
        if not relay:
            state["last_stop"] = now
            state["filt_running"] = False
    state["relay"] = relay
    state["heating"] = heating
    if not relay:
        state["filt_running"] = False

    active = []
    for cls in state["faults"]:
        active.append(cls)
    active.sort()

    return {
        "state": state,
        "relay": relay,
        "reason": reason,
        "detail": detail,
        "faults": active,
        "warnings": warnings,
        "events": events,
        "effective": {"water": water_eff, "mat": mat_eff, "air": air_eff,
                      "delta": delta},
    }


def _auto_decision(inputs, config, state, events, water_eff, mat_eff, delta,
                   window_ok, time_valid, local_min, now):
    """Relay decision for mode=auto. Returns (relay, reason, heating)."""
    # 8a. overtemp circulate
    if "mat_overtemp" in state["faults"] \
            and cfg(config, "mat_overtemp_action") == "circulate" \
            and water_eff is not None \
            and water_eff < cfg(config, "absolute_water_max"):
        return True, "overtemp_circulate", False

    # 8b/8c. sensor-failure policies
    water_failed = water_eff is None
    mat_failed = mat_eff is None
    if water_failed or mat_failed:
        pol = cfg(config, "pol_sensor_fail_water") if water_failed \
            else cfg(config, "pol_sensor_fail_mat")
        if water_failed and mat_failed:
            # both roles dead: fallback only if BOTH policies allow it
            pw = cfg(config, "pol_sensor_fail_water")
            pm = cfg(config, "pol_sensor_fail_mat")
            if pw == "fallback_schedule" and pm == "fallback_schedule":
                pol = "fallback_schedule"
            else:
                pol = "safe_off"
        if pol == "fallback_schedule":
            return _fallback_pattern(config, state, time_valid, local_min, now)
        if pol == "continue_mat_only" and water_failed and not mat_failed:
            water_eff = cfg(config, "assumed_water_temp")
            delta = mat_eff - water_eff
            # fall through to the heating decision with the assumed value
        else:
            cls = "sensor_fail_water" if water_failed else "sensor_fail_mat"
            return False, "fault:" + cls, False

    if cfg(config, "pol_sensor_fail_air") == "safe_off" \
            and "sensor_fail_air" in state["faults"]:
        return False, "fault:sensor_fail_air", False

    # 8d. heating decision
    run_len = now - state["relay_since"]
    if state["relay"] and state["heating"]:
        if water_eff >= cfg(config, "target_water_max"):
            return False, "water_max", False
        if not window_ok:
            return False, "window", False
        if delta <= cfg(config, "dt_stop"):
            if run_len >= cfg(config, "min_run_s"):
                return False, "dt_stop", False
            return True, "min_run", True
        return True, "heating", True
    if delta >= cfg(config, "dt_start"):
        if water_eff >= cfg(config, "target_water_max") - cfg(config, "water_hyst"):
            start_ok = False
            reason = "water_max"
        elif not window_ok:
            start_ok = False
            reason = "window"
        elif now - state["last_stop"] < cfg(config, "min_pause_s") \
                and state["last_stop"] > 0:
            start_ok = False
            reason = "min_pause"
        else:
            start_ok = True
            reason = "dt_start"
        if start_ok:
            return True, "dt_start", True
        # heating blocked; deficit/sampling may still run below
        blocked_reason = reason
    else:
        blocked_reason = "idle"

    # 8e. filtration deficit
    if time_valid and local_min >= cfg(config, "filt_check_min") \
            and state["run_s_today"] < cfg(config, "filt_target_s"):
        if now < state["filt_pause_until"]:
            return False, "quota_pause", False
        if not state["filt_running"]:
            state["filt_running"] = True
            state["filt_block_start"] = now
        if now - state["filt_block_start"] >= cfg(config, "filt_block_max_s"):
            state["filt_running"] = False
            state["filt_pause_until"] = now + cfg(config, "filt_block_pause_s")
            return False, "quota_pause", False
        return True, "quota_deficit", False

    # sampling runs (optional, default off)
    if cfg(config, "sample_enabled"):
        if now - state["sample_last"] < cfg(config, "sample_duration_s"):
            return True, "sample", False
        if now - state["sample_last"] >= cfg(config, "sample_interval_s"):
            state["sample_last"] = now
            return True, "sample", False

    return False, blocked_reason, False


def _fallback_pattern(config, state, time_valid, local_min, now):
    """Timed fallback schedule when ΔT control is impossible."""
    if time_valid and not _in_window(local_min,
                                     cfg(config, "fallback_start_min"),
                                     cfg(config, "fallback_end_min")):
        return False, "fallback_wait", False
    if now - state["fallback_last"] < cfg(config, "fallback_run_s"):
        return True, "fallback", False
    if now - state["fallback_last"] >= cfg(config, "fallback_interval_s"):
        state["fallback_last"] = now
        return True, "fallback", False
    return False, "fallback_wait", False
