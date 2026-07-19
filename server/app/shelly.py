"""HTTP RPC client for the Shelly device (and the simulator drop-in).

The server never sets the relay directly in normal operation — it talks to the
on-device script's endpoints (/script/<id>/status, /cmd, /reload) and writes
parameters via KVS. The one exception: emergency stop additionally calls
Switch.Set false as belt-and-braces (spec §3).
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .settings import settings


class ShellyError(Exception):
    pass


class ShellyClient:
    def __init__(self, host: str, password: str = ""):
        self.host = host
        auth = httpx.DigestAuth("admin", password) if password else None
        self._http = httpx.AsyncClient(
            base_url=f"http://{host}", auth=auth, timeout=8.0)
        self._script_ids: dict[str, int] = {}

    async def close(self):
        await self._http.aclose()

    async def rpc(self, method: str, params: dict | None = None) -> Any:
        r = await self._http.post(f"/rpc/{method}", json=params or {})
        if r.status_code != 200:
            raise ShellyError(f"{method}: HTTP {r.status_code} {r.text[:200]}")
        return r.json()

    async def _script_id(self, name: str = "pool-control") -> int:
        if name not in self._script_ids:
            res = await self.rpc("Script.List")
            for s in res.get("scripts", []):
                self._script_ids[s["name"]] = s["id"]
            if name not in self._script_ids:
                raise ShellyError(f"script '{name}' not found on device")
        return self._script_ids[name]

    async def _script_endpoint(self, endpoint: str, method: str = "GET",
                               body: dict | None = None) -> Any:
        sid = await self._script_id()
        url = f"/script/{sid}/{endpoint}"
        if method == "GET":
            r = await self._http.get(url)
        else:
            r = await self._http.post(url, content=json.dumps(body or {}))
        if r.status_code >= 500:
            raise ShellyError(f"{url}: HTTP {r.status_code}")
        return r.json()

    async def get_status(self) -> dict:
        return await self._script_endpoint("status")

    async def send_cmd(self, cmd: dict) -> dict:
        return await self._script_endpoint("cmd", "POST", cmd)

    async def reload(self) -> None:
        await self._script_endpoint("reload", "POST", {})

    async def kvs_set(self, key: str, value) -> None:
        await self.rpc("KVS.Set", {"key": key, "value": json.dumps(value)})

    async def kvs_get_many(self, match: str = "pool.*") -> dict:
        res = await self.rpc("KVS.GetMany", {"match": match})
        items = res.get("items")
        out = {}
        if isinstance(items, list):
            for it in items:
                out[it["key"]] = it.get("value")
        elif isinstance(items, dict):
            for k, v in items.items():
                out[k] = v.get("value")
        return out

    async def switch_set(self, on: bool, relay_id: int = 0) -> None:
        await self.rpc("Switch.Set", {"id": relay_id, "on": on})

    async def device_info(self) -> dict:
        return await self.rpc("Shelly.GetDeviceInfo")


def make_client():
    """Factory: real device or simulator, per settings."""
    if settings.simulate:
        from .sim import SimClient
        return SimClient()
    if not settings.shelly_host:
        return None
    return ShellyClient(settings.shelly_host, settings.shelly_password)


class Snapshot:
    """Latest known device state, shared between poller, API and WS."""

    def __init__(self):
        self.data: dict | None = None
        self.updated: float = 0.0
        self.online: bool = False
        self.device_info: dict = {}

    def set(self, status: dict):
        self.data = status
        self.updated = time.time()
        self.online = True

    def mark_offline(self):
        self.online = False

    def as_dict(self) -> dict:
        return {
            "online": self.online,
            "updated": self.updated,
            "age_s": round(time.time() - self.updated, 1) if self.updated else None,
            "device": self.device_info,
            "status": self.data,
        }


snapshot = Snapshot()
