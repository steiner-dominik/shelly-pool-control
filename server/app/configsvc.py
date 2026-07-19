"""Parameter registry + device config write path.

Single source of truth for what is configurable, with UI metadata (group,
unit, bounds, enums). Values are mirrored in SQLite; writes go to the device
KVS with a revision bump and are only marked *confirmed* once the device
echoes the revision in its status (spec §7.4).
"""

from __future__ import annotations

import asyncio
import json
import time

from .core.decision import DEFAULTS
from .db import ConfigMirror, db, get_setting, journal, set_setting

# key -> (group, unit, min, max, enum)
NUM = "number"
META: dict[str, dict] = {
    # heating
    "dt_start": {"group": "heating", "unit": "K", "min": 0.5, "max": 20, "step": 0.1},
    "dt_stop": {"group": "heating", "unit": "K", "min": 0.1, "max": 15, "step": 0.1},
    "target_water_max": {"group": "heating", "unit": "°C", "min": 10, "max": 40, "step": 0.5},
    "water_hyst": {"group": "heating", "unit": "K", "min": 0.1, "max": 5, "step": 0.1},
    "absolute_water_max": {"group": "heating", "unit": "°C", "min": 15, "max": 45, "step": 0.5},
    "window_start_min": {"group": "heating", "unit": "time", "min": 0, "max": 1439},
    "window_end_min": {"group": "heating", "unit": "time", "min": 0, "max": 1439},
    "min_run_s": {"group": "heating", "unit": "s", "min": 0, "max": 7200},
    "min_pause_s": {"group": "heating", "unit": "s", "min": 0, "max": 7200},
    # filtration
    "filt_target_s": {"group": "filtration", "unit": "s", "min": 0, "max": 86400},
    "filt_check_min": {"group": "filtration", "unit": "time", "min": 0, "max": 1439},
    "filt_block_max_s": {"group": "filtration", "unit": "s", "min": 300, "max": 86400},
    "filt_block_pause_s": {"group": "filtration", "unit": "s", "min": 0, "max": 14400},
    "day_reset_min": {"group": "filtration", "unit": "time", "min": 0, "max": 1439},
    # safety
    "mat_overtemp_limit": {"group": "safety", "unit": "°C", "min": 40, "max": 95, "step": 1},
    "mat_overtemp_action": {"group": "safety", "enum": ["circulate", "alert_only", "lockout"]},
    "pump_power_nominal": {"group": "safety", "unit": "W", "min": 0, "max": 5000},
    "pump_power_min_pct": {"group": "safety", "unit": "%", "min": 10, "max": 95},
    "pump_power_max_pct": {"group": "safety", "unit": "%", "min": 105, "max": 400},
    "no_power_threshold_w": {"group": "safety", "unit": "W", "min": 1, "max": 200},
    "power_grace_s": {"group": "safety", "unit": "s", "min": 5, "max": 600},
    "start_ignore_s": {"group": "safety", "unit": "s", "min": 0, "max": 60},
    "power_fault_action": {"group": "safety", "enum": ["lockout", "retry"]},
    "retry_max": {"group": "safety", "min": 1, "max": 10},
    "retry_backoff_s": {"group": "safety", "unit": "s", "min": 30, "max": 3600},
    # fault policies
    "pol_sensor_fail_water": {"group": "policies",
                              "enum": ["safe_off", "fallback_schedule", "continue_mat_only"]},
    "pol_sensor_fail_mat": {"group": "policies", "enum": ["safe_off", "fallback_schedule"]},
    "pol_sensor_fail_air": {"group": "policies", "enum": ["warn_only", "safe_off"]},
    "assumed_water_temp": {"group": "policies", "unit": "°C", "min": 5, "max": 35, "step": 0.5},
    "fallback_run_s": {"group": "policies", "unit": "s", "min": 60, "max": 14400},
    "fallback_interval_s": {"group": "policies", "unit": "s", "min": 600, "max": 86400},
    "fallback_start_min": {"group": "policies", "unit": "time", "min": 0, "max": 1439},
    "fallback_end_min": {"group": "policies", "unit": "time", "min": 0, "max": 1439},
    "fault_clear_hold_s": {"group": "policies", "unit": "s", "min": 0, "max": 3600},
    # frost & winter
    "frost_enabled": {"group": "frost"},
    "frost_threshold": {"group": "frost", "unit": "°C", "min": -5, "max": 10, "step": 0.5},
    "frost_run_s": {"group": "frost", "unit": "s", "min": 60, "max": 3600},
    "frost_interval_s": {"group": "frost", "unit": "s", "min": 600, "max": 21600},
    # sensors
    "water_min": {"group": "sensors", "unit": "°C", "min": -30, "max": 60},
    "water_max": {"group": "sensors", "unit": "°C", "min": -30, "max": 60},
    "mat_min": {"group": "sensors", "unit": "°C", "min": -40, "max": 120},
    "mat_max": {"group": "sensors", "unit": "°C", "min": -40, "max": 120},
    "air_min": {"group": "sensors", "unit": "°C", "min": -50, "max": 60},
    "air_max": {"group": "sensors", "unit": "°C", "min": -50, "max": 60},
    "roc_water": {"group": "sensors", "unit": "K", "min": 0.5, "max": 30},
    "roc_mat": {"group": "sensors", "unit": "K", "min": 0.5, "max": 50},
    "roc_air": {"group": "sensors", "unit": "K", "min": 0.5, "max": 30},
    "reset85_boot_s": {"group": "sensors", "unit": "s", "min": 0, "max": 600},
    "stuck_window_s": {"group": "sensors", "unit": "s", "min": 600, "max": 86400},
    "offset_water_a": {"group": "sensors", "unit": "K", "min": -5, "max": 5, "step": 0.1},
    "offset_water_b": {"group": "sensors", "unit": "K", "min": -5, "max": 5, "step": 0.1},
    "offset_mat_a": {"group": "sensors", "unit": "K", "min": -5, "max": 5, "step": 0.1},
    "offset_mat_b": {"group": "sensors", "unit": "K", "min": -5, "max": 5, "step": 0.1},
    "offset_air": {"group": "sensors", "unit": "K", "min": -5, "max": 5, "step": 0.1},
    "div_water": {"group": "sensors", "unit": "K", "min": 0.2, "max": 10, "step": 0.1},
    "div_mat": {"group": "sensors", "unit": "K", "min": 0.5, "max": 20, "step": 0.1},
    "agg_water": {"group": "sensors", "enum": ["avg", "min", "max", "prefer_a"]},
    "agg_mat": {"group": "sensors", "enum": ["avg", "min", "max", "prefer_a"]},
    "divpol_water": {"group": "sensors", "enum": ["conservative", "avg", "prefer_a"]},
    "divpol_mat": {"group": "sensors", "enum": ["conservative", "avg", "prefer_a"]},
    # system
    "tick_s": {"group": "system", "unit": "s", "min": 5, "max": 60},
    "boot_settle_s": {"group": "system", "unit": "s", "min": 0, "max": 300},
    "boot_policy": {"group": "system", "enum": ["resume", "always_auto", "always_off"]},
    "force_timeout_s": {"group": "system", "unit": "s", "min": 60, "max": 86400},
    "boost_timeout_s": {"group": "system", "unit": "s", "min": 0, "max": 86400},
    "sample_enabled": {"group": "system"},
    "sample_interval_s": {"group": "system", "unit": "s", "min": 300, "max": 86400},
    "sample_duration_s": {"group": "system", "unit": "s", "min": 30, "max": 1800},
}


class ValidationError(Exception):
    def __init__(self, key: str, why: str):
        self.key = key
        self.why = why
        super().__init__(f"{key}: {why}")


def schema() -> list[dict]:
    """Full parameter schema for the frontend settings UI."""
    out = []
    for key, default in DEFAULTS.items():
        m = META.get(key, {"group": "system"})
        typ = "bool" if isinstance(default, bool) else (
            "enum" if "enum" in m else NUM)
        out.append({
            "key": key, "type": typ, "default": default,
            "group": m.get("group", "system"), "unit": m.get("unit"),
            "min": m.get("min"), "max": m.get("max"),
            "step": m.get("step", 1), "enum": m.get("enum"),
        })
    return out


def validate(key: str, value):
    if key not in DEFAULTS:
        raise ValidationError(key, "unknown_key")
    default = DEFAULTS[key]
    m = META.get(key, {})
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValidationError(key, "expected_bool")
        return value
    if "enum" in m:
        if value not in m["enum"]:
            raise ValidationError(key, "invalid_choice")
        return value
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValidationError(key, "expected_number")
    if m.get("min") is not None and value < m["min"]:
        raise ValidationError(key, "below_min")
    if m.get("max") is not None and value > m["max"]:
        raise ValidationError(key, "above_max")
    if isinstance(default, int) and m.get("step", 1) == 1:
        value = int(value)
    return value


def current_values() -> dict:
    """Mirror values merged over defaults, with pending flags."""
    s = db()
    try:
        rows = {r.key: r for r in s.query(ConfigMirror).all()}
    finally:
        s.close()
    out = {}
    for key, default in DEFAULTS.items():
        row = rows.get(key)
        if row is not None:
            try:
                out[key] = {"value": json.loads(row.value), "pending": row.pending}
            except ValueError:
                out[key] = {"value": default, "pending": False}
        else:
            out[key] = {"value": default, "pending": False}
    return out


def _mirror_set(s, key: str, value, pending: bool):
    row = s.get(ConfigMirror, key)
    if row is None:
        row = ConfigMirror(key=key, value=json.dumps(value), pending=pending)
        s.add(row)
    else:
        row.value = json.dumps(value)
        row.pending = pending
        row.updated = time.time()


async def apply_changes(client, changes: dict, actor: str) -> dict:
    """Validate + write to device KVS + bump revision. Returns per-key result."""
    validated = {}
    for key, value in changes.items():
        validated[key] = validate(key, value)

    rev = str(int(time.time() * 1000))
    s = db()
    try:
        old = current_values()
        for key, value in validated.items():
            _mirror_set(s, key, value, pending=True)
        set_setting(s, "cfg_rev", rev)
        journal(s, "config", {"actor": actor, "rev": rev, "changes": {
            k: {"old": old[k]["value"], "new": v} for k, v in validated.items()}})
        s.commit()
    finally:
        s.close()

    confirmed = False
    if client is not None:
        for key, value in validated.items():
            await client.kvs_set(f"pool.cfg.{key}", value)
        await client.kvs_set("pool.cfg._rev", rev)
        try:
            await client.reload()
        except Exception:
            pass
        # quick confirmation attempts; the poller keeps checking afterwards
        for delay in (0.3, 1.0, 3.0):
            await asyncio.sleep(delay)
            try:
                status = await client.get_status()
            except Exception:
                continue
            if _rev_matches(status, rev):
                confirmed = True
                break
    if confirmed:
        mark_confirmed()
    return {"rev": rev, "confirmed": confirmed, "applied": list(validated)}


def _rev_matches(status: dict, rev: str) -> bool:
    got = str(status.get("cfg_rev", "")).strip('"')
    return got == rev


def sync_pending(status: dict) -> None:
    """Called by the poller with each device status."""
    s = db()
    try:
        rev = get_setting(s, "cfg_rev")
        if rev and _rev_matches(status, str(rev)):
            s.query(ConfigMirror).filter(
                ConfigMirror.pending.is_(True)).update({"pending": False})
            s.commit()
    finally:
        s.close()


async def push_all(client) -> None:
    """Push the whole mirror to the device (initial sync / after restore)."""
    values = current_values()
    non_default = {k: v["value"] for k, v in values.items()
                   if v["value"] != DEFAULTS[k]}
    s = db()
    try:
        rev = get_setting(s, "cfg_rev") or str(int(time.time() * 1000))
        set_setting(s, "cfg_rev", rev)
    finally:
        s.close()
    for key, value in non_default.items():
        await client.kvs_set(f"pool.cfg.{key}", value)
    await client.kvs_set("pool.cfg._rev", str(rev))
    try:
        await client.reload()
    except Exception:
        pass


async def adopt_from_device(client) -> bool:
    """First contact with a configured device and empty mirror: adopt values."""
    s = db()
    try:
        has_mirror = s.query(ConfigMirror).first() is not None
    finally:
        s.close()
    if has_mirror:
        return False
    try:
        kvs = await client.kvs_get_many("pool.cfg.*")
    except Exception:
        return False
    s = db()
    try:
        for key, raw in kvs.items():
            if key == "pool.cfg._rev":
                set_setting(s, "cfg_rev", str(raw).strip('"'))
                continue
            name = key[9:]
            if name not in DEFAULTS:
                continue
            try:
                value = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                continue
            try:
                _mirror_set(s, name, validate(name, value), pending=False)
            except ValidationError:
                continue
        s.commit()
    finally:
        s.close()
    return True


def mark_confirmed() -> None:
    s = db()
    try:
        s.query(ConfigMirror).filter(
            ConfigMirror.pending.is_(True)).update({"pending": False})
        s.commit()
    finally:
        s.close()
