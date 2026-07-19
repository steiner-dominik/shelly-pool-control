"""Optional InfluxDB v2 mirror — plain line protocol via HTTP, no extra deps.

SQLite stays authoritative; this is a fire-and-forget copy for people who
want Grafana dashboards on their existing Influx.
"""

from __future__ import annotations

import time

import httpx

from .settings import settings

_last_error: str | None = None
_last_ok: float = 0.0


def enabled() -> bool:
    return bool(settings.influx_url and settings.influx_token
                and settings.influx_org and settings.influx_bucket)


def status() -> dict:
    return {"enabled": enabled(), "last_ok": _last_ok, "last_error": _last_error}


def _esc(v: str) -> str:
    return v.replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")


async def write_sample(sample: dict) -> None:
    global _last_error, _last_ok
    if not enabled():
        return
    ts = int(sample["ts"] * 1e9)
    fields = []
    for key in ("water", "mat", "air", "delta", "power_w"):
        v = sample.get(key)
        if v is not None:
            fields.append(f"{key}={float(v)}")
    fields.append(f"relay={'true' if sample.get('relay') else 'false'}")
    fields.append(f"run_s_today={int(sample.get('run_s_today', 0))}i")
    line = (f"pool,mode={_esc(sample.get('mode') or 'unknown')},"
            f"reason={_esc(sample.get('reason') or 'unknown')} "
            + ",".join(fields) + f" {ts}")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{settings.influx_url.rstrip('/')}/api/v2/write",
                params={"org": settings.influx_org,
                        "bucket": settings.influx_bucket,
                        "precision": "ns"},
                headers={"Authorization": f"Token {settings.influx_token}"},
                content=line)
            if r.status_code >= 300:
                _last_error = f"HTTP {r.status_code}: {r.text[:200]}"
            else:
                _last_ok = time.time()
                _last_error = None
    except Exception as e:
        _last_error = str(e)[:300]
