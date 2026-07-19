"""Backup & restore.

A backup is a zip containing:
- ``config.json``  — parameter mirror, app settings, users (argon2 hashes),
  sensor/device mapping. Enough to rebuild a working installation.
- ``history.sqlite3`` — consistent snapshot of the full database (events,
  samples, audit) made with the SQLite backup API.

Restore applies config.json (and pushes parameters to the device) and can
optionally merge history rows from the snapshot. Scheduled backups run daily
at a configured local time with a keep-N rotation.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import pathlib
import sqlite3
import tempfile
import zipfile
import zoneinfo

from .configsvc import DEFAULTS, current_values, push_all, validate
from .db import (ConfigMirror, Setting, User, db, get_setting, journal,
                 set_setting)
from .settings import settings

BACKUP_PREFIX = "pool-backup-"


def _export_config() -> dict:
    s = db()
    try:
        users = [{"username": u.username, "role": u.role, "pw_hash": u.pw_hash,
                  "totp_secret": u.totp_secret, "disabled": u.disabled}
                 for u in s.query(User).all()]
        app_settings = {}
        for row in s.query(Setting).all():
            try:
                app_settings[row.key] = json.loads(row.value)
            except ValueError:
                continue
    finally:
        s.close()
    return {
        "app": "shelly-pool-control",
        "backup_format": 1,
        "version": settings.version,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "config": {k: v["value"] for k, v in current_values().items()},
        "settings": app_settings,
        "users": users,
    }


def create_backup() -> pathlib.Path:
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = settings.backup_dir / f"{BACKUP_PREFIX}{stamp}.zip"
    with tempfile.TemporaryDirectory() as td:
        snap = pathlib.Path(td) / "history.sqlite3"
        src = sqlite3.connect(settings.db_path)
        dst = sqlite3.connect(snap)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("config.json", json.dumps(_export_config(), indent=2))
            z.write(snap, "history.sqlite3")
    s = db()
    try:
        journal(s, "backup", {"file": path.name, "size": path.stat().st_size})
    finally:
        s.close()
    return path


def list_backups() -> list[dict]:
    if not settings.backup_dir.exists():
        return []
    out = []
    for p in sorted(settings.backup_dir.glob(f"{BACKUP_PREFIX}*.zip"), reverse=True):
        out.append({"name": p.name, "size": p.stat().st_size,
                    "mtime": p.stat().st_mtime})
    return out


def backup_path(name: str) -> pathlib.Path | None:
    if "/" in name or ".." in name or not name.startswith(BACKUP_PREFIX):
        return None
    p = settings.backup_dir / name
    return p if p.exists() else None


def rotate(keep: int) -> int:
    files = sorted(settings.backup_dir.glob(f"{BACKUP_PREFIX}*.zip"))
    removed = 0
    while len(files) > keep:
        files.pop(0).unlink()
        removed += 1
    return removed


async def restore_backup(client, data: bytes, restore_history: bool,
                         actor: str) -> dict:
    with tempfile.TemporaryDirectory() as td:
        zpath = pathlib.Path(td) / "restore.zip"
        zpath.write_bytes(data)
        try:
            z = zipfile.ZipFile(zpath)
            cfg = json.loads(z.read("config.json"))
        except (zipfile.BadZipFile, KeyError, ValueError) as e:
            return {"ok": False, "error": f"invalid_backup: {e}"}
        if cfg.get("app") != "shelly-pool-control":
            return {"ok": False, "error": "not_a_pool_backup"}

        s = db()
        try:
            # parameters
            applied = 0
            for key, value in (cfg.get("config") or {}).items():
                if key not in DEFAULTS:
                    continue
                try:
                    value = validate(key, value)
                except Exception:
                    continue
                row = s.get(ConfigMirror, key)
                if row is None:
                    s.add(ConfigMirror(key=key, value=json.dumps(value),
                                       pending=True))
                else:
                    row.value = json.dumps(value)
                    row.pending = True
                applied += 1
            # app settings (never restore cfg_rev — a new one is generated)
            for key, value in (cfg.get("settings") or {}).items():
                if key == "cfg_rev":
                    continue
                set_setting(s, key, value)
            # users: replace-by-username merge
            restored_users = 0
            for u in cfg.get("users") or []:
                if not u.get("username") or not u.get("pw_hash"):
                    continue
                row = s.query(User).filter(
                    User.username == u["username"]).first()
                if row is None:
                    row = User(username=u["username"], pw_hash=u["pw_hash"])
                    s.add(row)
                else:
                    row.pw_hash = u["pw_hash"]
                row.role = u.get("role", "viewer")
                row.totp_secret = u.get("totp_secret", "")
                row.disabled = bool(u.get("disabled", False))
                restored_users += 1
            s.commit()
            journal(s, "restore", {"actor": actor, "params": applied,
                                   "users": restored_users,
                                   "history": restore_history})
        finally:
            s.close()

        merged = 0
        if restore_history and "history.sqlite3" in z.namelist():
            hpath = pathlib.Path(td) / "history.sqlite3"
            hpath.write_bytes(z.read("history.sqlite3"))
            merged = _merge_history(hpath)

    if client is not None:
        await push_all(client)
    return {"ok": True, "params": applied, "users": restored_users,
            "history_rows": merged}


def _merge_history(snapshot: pathlib.Path) -> int:
    """Merge events/samples/audit rows from a snapshot DB (id-collision safe)."""
    conn = sqlite3.connect(settings.db_path)
    total = 0
    try:
        conn.execute("ATTACH DATABASE ? AS old", (str(snapshot),))
        for table, cols in (
            ("events", "ts, kind, data"),
            ("samples", "ts, water, mat, air, delta, power_w, relay, mode, "
                        "reason, run_s_today, heat_s_today"),
            ("audit", "ts, user, action, detail"),
        ):
            try:
                cur = conn.execute(
                    f"INSERT INTO {table} ({cols}) "
                    f"SELECT {cols} FROM old.{table} o WHERE NOT EXISTS "
                    f"(SELECT 1 FROM {table} n WHERE n.ts = o.ts)")
                total += cur.rowcount
            except sqlite3.Error:
                continue
        conn.commit()
    finally:
        conn.close()
    return total


DEFAULT_SCHEDULE = {"enabled": False, "time": "03:30", "keep": 14}


async def scheduler_loop():
    """Daily scheduled backups at the configured local time."""
    while True:
        try:
            s = db()
            try:
                plan = get_setting(s, "backup_schedule", DEFAULT_SCHEDULE)
                tzname = get_setting(s, "timezone_scheduler", "UTC")
                last = get_setting(s, "backup_last_day", "")
            finally:
                s.close()
            if plan.get("enabled"):
                try:
                    tz = zoneinfo.ZoneInfo(tzname)
                except (KeyError, zoneinfo.ZoneInfoNotFoundError):
                    tz = datetime.timezone.utc
                now = datetime.datetime.now(tz)
                today = now.strftime("%Y-%m-%d")
                hh, mm = (plan.get("time") or "03:30").split(":")
                due = now.replace(hour=int(hh), minute=int(mm),
                                  second=0, microsecond=0)
                if now >= due and last != today:
                    await asyncio.to_thread(create_backup)
                    await asyncio.to_thread(rotate, int(plan.get("keep", 14)))
                    s = db()
                    try:
                        set_setting(s, "backup_last_day", today)
                    finally:
                        s.close()
        except Exception:
            pass
        await asyncio.sleep(60)
