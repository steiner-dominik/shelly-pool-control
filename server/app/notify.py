"""Notification engine — pluggable channels: SMTP email, Telegram, webhook.

Channel config lives in the settings table (managed from the panel, never in
git). Events: fault raised/cleared, device offline/online, backup failures.
Per-channel minimum severity and quiet hours.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import smtplib
import zoneinfo
from email.message import EmailMessage

import httpx

from .db import db, get_setting

SEVERITY = {"info": 0, "warning": 1, "critical": 2}

FAULT_SEVERITY = {
    "sensor_fail_water": "critical", "sensor_fail_mat": "critical",
    "sensor_fail_air": "warning",
    "dry_run": "critical", "overload": "critical", "no_power": "critical",
    "mat_overtemp": "warning", "relay_stuck": "critical",
    "device_offline": "warning",
}

DEFAULT_CHANNELS = {
    "smtp": {"enabled": False, "host": "", "port": 587, "user": "",
             "password": "", "starttls": True, "from": "", "to": "",
             "min_severity": "warning"},
    "telegram": {"enabled": False, "bot_token": "", "chat_id": "",
                 "min_severity": "warning"},
    "webhook": {"enabled": False, "url": "", "min_severity": "info"},
    "quiet_hours": {"enabled": False, "start": "22:00", "end": "07:00",
                    "timezone": "UTC", "suppress_below": "critical"},
}


def get_channels() -> dict:
    s = db()
    try:
        stored = get_setting(s, "notify_channels", {})
    finally:
        s.close()
    merged = json.loads(json.dumps(DEFAULT_CHANNELS))
    for k, v in (stored or {}).items():
        if k in merged and isinstance(v, dict):
            merged[k].update(v)
    return merged


def _quiet_now(cfg: dict, severity: str) -> bool:
    q = cfg.get("quiet_hours", {})
    if not q.get("enabled"):
        return False
    if SEVERITY.get(severity, 0) >= SEVERITY.get(q.get("suppress_below", "critical"), 2):
        return False
    try:
        tz = zoneinfo.ZoneInfo(q.get("timezone", "UTC"))
    except (KeyError, zoneinfo.ZoneInfoNotFoundError):
        tz = datetime.timezone.utc
    now = datetime.datetime.now(tz)
    cur = now.hour * 60 + now.minute
    sh, sm = (q.get("start", "22:00")).split(":")
    eh, em = (q.get("end", "07:00")).split(":")
    start, end = int(sh) * 60 + int(sm), int(eh) * 60 + int(em)
    if start <= end:
        return start <= cur < end
    return cur >= start or cur < end


async def notify(severity: str, title: str, body: str) -> None:
    cfg = get_channels()
    if _quiet_now(cfg, severity):
        return
    tasks = []
    for name in ("smtp", "telegram", "webhook"):
        ch = cfg[name]
        if not ch.get("enabled"):
            continue
        if SEVERITY.get(severity, 0) < SEVERITY.get(ch.get("min_severity", "info"), 0):
            continue
        tasks.append(send_to_channel(name, ch, severity, title, body))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def send_to_channel(name: str, ch: dict, severity: str,
                          title: str, body: str) -> None:
    if name == "smtp":
        await asyncio.to_thread(_send_smtp, ch, title, body)
    elif name == "telegram":
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{ch['bot_token']}/sendMessage",
                json={"chat_id": ch["chat_id"],
                      "text": f"🏊 {title}\n{body}"})
    elif name == "webhook":
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(ch["url"], json={
                "source": "shelly-pool-control", "severity": severity,
                "title": title, "body": body})


def _send_smtp(ch: dict, title: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = f"[Pool] {title}"
    msg["From"] = ch["from"]
    msg["To"] = ch["to"]
    msg.set_content(body)
    with smtplib.SMTP(ch["host"], int(ch.get("port", 587)), timeout=15) as s:
        if ch.get("starttls", True):
            s.starttls()
        if ch.get("user"):
            s.login(ch["user"], ch["password"])
        s.send_message(msg)


async def test_channel(name: str) -> dict:
    cfg = get_channels()
    if name not in ("smtp", "telegram", "webhook"):
        return {"ok": False, "error": "unknown_channel"}
    try:
        await send_to_channel(name, cfg[name], "info",
                              "Test notification",
                              "This is a test from shelly-pool-control.")
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
