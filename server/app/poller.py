"""Device poller: telemetry ingest, journaling, fault-transition notifications.

The pool keeps running autonomously when this (or the whole server) is down —
the poller is purely supervisory.
"""

from __future__ import annotations

import asyncio
import time

from . import configsvc, influx
from .db import Sample, db, journal
from .notify import FAULT_SEVERITY, notify
from .settings import settings
from .shelly import snapshot
from .ws import hub

OFFLINE_AFTER_S = 180

_prev_faults: set[str] = set()
_prev_mode: str | None = None
_prev_reason: str | None = None
_prev_relay: bool | None = None
_last_sample_ts: float = 0.0
_last_ok: float = 0.0
_offline_notified = False


def _fault_texts(cls: str, active: bool) -> tuple[str, str]:
    verb = "raised" if active else "cleared"
    return (f"Fault {verb}: {cls}",
            f"The controller reported fault '{cls}' as {verb}.")


async def _handle_status(client, status: dict) -> None:
    global _prev_faults, _prev_mode, _prev_reason, _prev_relay
    global _last_sample_ts, _offline_notified, _last_ok

    now = time.time()
    _last_ok = now
    if _offline_notified:
        _offline_notified = False
        s = db()
        try:
            journal(s, "device_online", {})
        finally:
            s.close()
        await notify("info", "Controller back online",
                     "The Shelly pool controller is reachable again.")

    snapshot.set(status)
    configsvc.sync_pending(status)

    last = status.get("last") or {}
    faults = set(last.get("faults") or [])
    mode = status.get("mode")
    reason = last.get("reason")
    relay = bool(status.get("relay"))

    s = db()
    try:
        for cls in sorted(faults - _prev_faults):
            journal(s, "fault", {"cls": cls, "active": True})
        for cls in sorted(_prev_faults - faults):
            journal(s, "fault", {"cls": cls, "active": False})
        if mode != _prev_mode and _prev_mode is not None:
            journal(s, "mode", {"from": _prev_mode, "to": mode})
        if reason != _prev_reason and reason is not None:
            journal(s, "decision", {"reason": reason, "relay": relay,
                                    "effective": last.get("effective")})
    finally:
        s.close()

    for cls in sorted(faults - _prev_faults):
        sev = FAULT_SEVERITY.get(cls, "warning")
        title, body = _fault_texts(cls, True)
        await notify(sev, title, body)
    for cls in sorted(_prev_faults - faults):
        title, body = _fault_texts(cls, False)
        await notify("info", title, body)

    # decimated history: store every 60 s, or immediately on a state change
    changed = (relay != _prev_relay or mode != _prev_mode
               or faults != _prev_faults)
    if changed or now - _last_sample_ts >= 60:
        _last_sample_ts = now
        eff = last.get("effective") or {}
        row = {
            "ts": now,
            "water": eff.get("water"), "mat": eff.get("mat"),
            "air": eff.get("air"), "delta": eff.get("delta"),
            "power_w": last.get("power_w") or 0.0,
            "relay": relay, "mode": mode or "",
            "reason": reason or "",
            "run_s_today": int(status.get("run_s_today") or 0),
            "heat_s_today": int(status.get("heat_s_today") or 0),
        }
        s = db()
        try:
            s.add(Sample(**row))
            s.commit()
        finally:
            s.close()
        await influx.write_sample(row)

    _prev_faults = faults
    _prev_mode = mode
    _prev_reason = reason
    _prev_relay = relay

    hub.publish({"type": "status", "data": snapshot.as_dict()})


async def poll_loop(client) -> None:
    global _offline_notified
    if client is None:
        return
    # initial device handshake
    try:
        snapshot.device_info = await client.device_info()
        adopted = await configsvc.adopt_from_device(client)
        if not adopted:
            await configsvc.push_all(client)
    except Exception:
        pass

    while True:
        try:
            status = await client.get_status()
            await _handle_status(client, status)
        except Exception:
            if _last_ok and time.time() - _last_ok > OFFLINE_AFTER_S \
                    and not _offline_notified:
                _offline_notified = True
                snapshot.mark_offline()
                s = db()
                try:
                    journal(s, "device_offline", {})
                finally:
                    s.close()
                await notify(
                    "warning", "Controller offline",
                    "The Shelly pool controller is unreachable. The pool "
                    "keeps running autonomously on the device itself.")
                hub.publish({"type": "status", "data": snapshot.as_dict()})
        await asyncio.sleep(settings.poll_seconds)
