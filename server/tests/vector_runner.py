"""Shared test-vector runner (Python side).

Semantics are defined in shared/logic-spec.md §9 and mirrored exactly by
shelly/test/run-vectors.mjs. Keep both in sync.
"""

from __future__ import annotations

import copy
import json
import pathlib

from app.core.decision import DEFAULTS, cfg, initial_state, step

VECTOR_DIR = pathlib.Path(__file__).resolve().parents[2] / "shared" / "test-vectors"

DEFAULT_SENSORS = {"water_a": 22.0, "water_b": 22.0,
                   "mat_a": 24.0, "mat_b": 24.0, "air": 15.0}


class VectorFailure(AssertionError):
    pass


def load_vectors():
    out = []
    for f in sorted(VECTOR_DIR.glob("*.json")):
        data = json.loads(f.read_text())
        for vec in data["vectors"]:
            out.append((f.name, vec))
    return out


def _check(name, idx, key, actual, expected):
    if isinstance(expected, float) or isinstance(actual, float):
        ok = actual is not None and abs(float(actual) - float(expected)) < 1e-9
    else:
        ok = actual == expected
    if not ok:
        raise VectorFailure(
            f"[{name}] step {idx}: {key} expected {expected!r}, got {actual!r}")


def run_vector(name: str, vec: dict):
    config = dict(vec.get("config") or {})
    state = initial_state()
    for k, v in (vec.get("initial_state") or {}).items():
        state[k] = copy.deepcopy(v)
    tick = cfg(config, "tick_s")
    now = vec.get("start_now", 1000000000)
    base_local = vec.get("start_local_min", 720)
    base_day = vec.get("start_day", 20260715)  # mid-month: day math is naive
    time_valid = vec.get("time_valid", True)
    uptime = vec.get("uptime", cfg(config, "boot_settle_s") + 3600)
    elapsed = 0
    sensors = dict(DEFAULT_SENSORS)
    explicit_power = None

    for idx, st in enumerate(vec["steps"]):
        dt = st.get("dt", tick)
        now += dt
        elapsed += dt
        uptime += dt
        inp = st.get("in") or {}
        if "sensors" in inp:
            for k, v in inp["sensors"].items():
                sensors[k] = v
        if "time_valid" in inp:
            time_valid = inp["time_valid"]
        if "uptime" in inp:
            uptime = inp["uptime"]
        if "power_w" in inp:
            explicit_power = inp["power_w"]
        total_min = base_local + elapsed // 60
        local_min = total_min % 1440
        local_day = base_day + total_min // 1440
        if explicit_power is not None:
            power = explicit_power
        else:
            nominal = state["pump_nominal"] or cfg(config, "pump_power_nominal") or 800.0
            power = nominal if state["relay"] else 0.0
        inputs = {
            "now": now, "dt": dt, "uptime": uptime,
            "time_valid": time_valid,
            "local_min": local_min, "local_day": local_day,
            "sensors": dict(sensors),
            "power_w": power,
            "relay_actual": state["relay"],
            "commands": st.get("cmd") or [],
        }
        res = step(inputs, config, state)
        state = res["state"]

        exp = st.get("expect") or {}
        if "relay" in exp:
            _check(name, idx, "relay", res["relay"], exp["relay"])
        if "reason" in exp:
            _check(name, idx, "reason", res["reason"], exp["reason"])
        if "mode" in exp:
            _check(name, idx, "mode", state["mode"], exp["mode"])
        if "faults" in exp:
            _check(name, idx, "faults", res["faults"], sorted(exp["faults"]))
        if "faults_has" in exp:
            for f in exp["faults_has"]:
                if f not in res["faults"]:
                    raise VectorFailure(
                        f"[{name}] step {idx}: fault {f!r} not active "
                        f"(active: {res['faults']})")
        if "warnings_has" in exp:
            for w in exp["warnings_has"]:
                if w not in res["warnings"]:
                    raise VectorFailure(
                        f"[{name}] step {idx}: warning {w!r} missing "
                        f"(got: {res['warnings']})")
        if "effective" in exp:
            for k, v in exp["effective"].items():
                _check(name, idx, "effective." + k, res["effective"].get(k), v)
        if "state" in exp:
            for k, v in exp["state"].items():
                _check(name, idx, "state." + k, state.get(k), v)


def run_all():
    vectors = load_vectors()
    assert vectors, "no test vectors found"
    for name, vec in vectors:
        run_vector(f"{name}:{vec['name']}", vec)
    return len(vectors)


# make DEFAULTS importable for sanity checks in tests
__all__ = ["run_all", "run_vector", "load_vectors", "DEFAULTS"]
