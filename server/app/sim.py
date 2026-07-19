"""Simulated pool device.

Runs the *same* Python decision core against synthetic diurnal temperature
curves, speaking the same status/cmd/reload interface as ShellyClient. Used
for demos, development without hardware, and notification-flow testing.
Enable with POOL_SIMULATE=1. Fault injection via /api/sim endpoints.
"""

from __future__ import annotations

import asyncio
import math
import time
import zoneinfo
from datetime import datetime

from .core import decision
from .settings import settings

TZ = zoneinfo.ZoneInfo("Europe/Vienna")


class SimClient:
    def __init__(self):
        self.kvs: dict[str, str] = {}
        self.cfg: dict = {}
        self.state = decision.initial_state()
        self.acks: list[dict] = []
        self.last_result: dict | None = None
        self.cmd_queue: list[dict] = []
        self.boot_ts = time.time()
        self.cfg_rev = "0"
        # synthetic environment state
        self.water_t = 22.0
        self.mat_t = 24.0
        # fault injection overrides: slot -> value|None ("dead")
        self.overrides: dict[str, object] = {}
        self.power_override: float | None = None
        self._task: asyncio.Task | None = None

    # -- lifecycle -----------------------------------------------------------

    def start(self):
        if self._task is None:
            self._task = asyncio.get_event_loop().create_task(self._loop())

    async def close(self):
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self):
        while True:
            try:
                self._tick()
            except Exception:
                pass
            await asyncio.sleep(decision.cfg(self.cfg, "tick_s"))

    # -- synthetic physics ---------------------------------------------------

    def _env(self, now: float) -> tuple[float, float]:
        """(air_temp, sun_factor 0..1) from local wall time."""
        lt = datetime.fromtimestamp(now, TZ)
        h = lt.hour + lt.minute / 60.0
        air = 16.0 + 8.0 * math.sin((h - 9.0) / 24.0 * 2 * math.pi)
        sun = max(0.0, math.sin((h - 6.0) / 12.0 * math.pi)) if 6 <= h <= 18 else 0.0
        return air, sun

    def _advance_env(self, dt: float, pump_on: bool):
        now = time.time()
        air, sun = self._env(now)
        # mat: heats in the sun, cools toward air; pump flow pulls it toward water
        target = air + sun * 28.0
        tau = 600.0 if not pump_on else 120.0
        goal = target if not pump_on else (self.water_t + (target - self.water_t) * 0.35)
        self.mat_t += (goal - self.mat_t) * (1 - math.exp(-dt / tau))
        # water: big thermal mass; gains from mat when pumping, loses to air slowly
        if pump_on and self.mat_t > self.water_t:
            self.water_t += (self.mat_t - self.water_t) * dt / 7200.0
        self.water_t += (air - self.water_t) * dt / 172800.0

    def _sensors(self) -> dict:
        base = {
            "water_a": round(self.water_t, 2),
            "water_b": round(self.water_t + 0.1, 2),
            "mat_a": round(self.mat_t, 2),
            "mat_b": round(self.mat_t - 0.2, 2),
            "air": round(self._env(time.time())[0], 2),
        }
        for slot, v in self.overrides.items():
            base[slot] = v
        return base

    # -- core tick -----------------------------------------------------------

    def _tick(self):
        now = int(time.time())
        lt = datetime.fromtimestamp(now, TZ)
        tick_s = decision.cfg(self.cfg, "tick_s")
        pump_was_on = self.state["relay"]
        self._advance_env(tick_s, pump_was_on)

        nominal = self.state["pump_nominal"] or decision.cfg(
            self.cfg, "pump_power_nominal") or 780.0
        power = nominal if pump_was_on else 0.0
        if self.power_override is not None and pump_was_on:
            power = self.power_override

        cmds, self.cmd_queue = self.cmd_queue, []
        inputs = {
            "now": now, "dt": tick_s,
            "uptime": int(now - self.boot_ts + 3600),
            "time_valid": True,
            "local_min": lt.hour * 60 + lt.minute,
            "local_day": lt.year * 10000 + lt.month * 100 + lt.day,
            "sensors": self._sensors(),
            "power_w": power,
            "relay_actual": pump_was_on,
            "commands": cmds,
        }
        res = decision.step(inputs, self.cfg, self.state)
        self.state = res["state"]
        for ev in res["events"]:
            if ev.get("ev") == "ack":
                self.acks.append(ev)
                self.acks = self.acks[-10:]
        self.last_result = {
            "ts": now, "relay": res["relay"], "reason": res["reason"],
            "faults": res["faults"], "warnings": res["warnings"],
            "effective": res["effective"], "power_w": power,
            "sensors": inputs["sensors"], "time_valid": True,
        }

    # -- ShellyClient-compatible interface ------------------------------------

    async def get_status(self) -> dict:
        if self.last_result is None:
            self._tick()
        return {
            "script_version": settings.version + "-sim",
            "cfg_rev": self.cfg_rev,
            "mode": self.state["mode"],
            "mode_until": self.state["mode_until"],
            "relay": self.state["relay"],
            "heating": self.state["heating"],
            "run_s_today": self.state["run_s_today"],
            "heat_s_today": self.state["heat_s_today"],
            "lockouts": self.state["lockouts"],
            "pump_nominal": self.state["pump_nominal"],
            "last": self.last_result,
            "acks": self.acks,
            "dev": {"relay_id": 0, "input_pump": 0, "simulated": True,
                    "sensors": {"water_a": 100, "water_b": 101, "mat_a": 102,
                                "mat_b": 103, "air": 104}},
        }

    async def send_cmd(self, cmd: dict) -> dict:
        if not isinstance(cmd, dict) or not isinstance(cmd.get("cmd"), str):
            return {"ok": False, "error": "bad_request"}
        self.cmd_queue.append(cmd)
        self._tick()
        return {"ok": True, "queued": True}

    async def reload(self) -> None:
        cfg = {}
        for key, raw in self.kvs.items():
            if key == "pool.cfg._rev":
                self.cfg_rev = str(raw)
                continue
            if key.startswith("pool.cfg."):
                name = key[9:]
                if name in decision.DEFAULTS:
                    import json as _json
                    try:
                        v = _json.loads(raw) if isinstance(raw, str) else raw
                    except ValueError:
                        continue
                    if isinstance(v, type(decision.DEFAULTS[name])) or (
                            isinstance(v, (int, float))
                            and isinstance(decision.DEFAULTS[name], (int, float))):
                        cfg[name] = v
        self.cfg = cfg

    async def kvs_set(self, key: str, value) -> None:
        import json as _json
        self.kvs[key] = _json.dumps(value)

    async def kvs_get_many(self, match: str = "pool.*") -> dict:
        return dict(self.kvs)

    async def switch_set(self, on: bool, relay_id: int = 0) -> None:
        # emergency path: force the relay in the simulated hardware
        self.state["relay"] = on
        if not on:
            self.state["mode"] = "off"

    async def device_info(self) -> dict:
        return {"model": "SIMULATED-2PM-G4", "id": "pool-sim", "ver": "sim",
                "app": "simulator"}
