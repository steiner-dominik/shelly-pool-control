"""REST + WebSocket API for the panel."""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import (APIRouter, Depends, HTTPException, Request, Response,
                     UploadFile, WebSocket, WebSocketDisconnect)
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import backup as backup_mod
from . import configsvc, influx, notify, totp
from .auth import (Identity, any_users_exist, check_rate_limit, create_session,
                   current_identity, destroy_session, hash_password, log_audit,
                   record_login_result, require_auth, require_role,
                   verify_password, client_ip)
from .db import Audit, Event, User, db, get_setting, set_setting
from .settings import settings
from .shelly import snapshot
from .ws import hub

router = APIRouter(prefix="/api")

# device client is injected at startup (main.py)
device = {"client": None}


def _client():
    return device["client"]


async def _refresh_snapshot():
    """Pull fresh status right after a command so the UI reacts instantly."""
    client = _client()
    if client is None:
        return
    try:
        status = await client.get_status()
        snapshot.set(status)
        hub.publish({"type": "status", "data": snapshot.as_dict()})
    except Exception:
        pass


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

class LoginBody(BaseModel):
    username: str
    password: str
    totp: str | None = None


class SetupBody(BaseModel):
    username: str
    password: str


@router.get("/auth/state")
async def auth_state(request: Request):
    ident = current_identity(request)
    return {
        "setup_required": not any_users_exist() and settings.auth_mode != "ingress",
        "authenticated": ident is not None,
        "user": ident.username if ident else None,
        "role": ident.role if ident else None,
        "csrf": ident.csrf if ident else None,
        "via_ingress": ident.via_ingress if ident else False,
        "version": settings.version,
        "simulate": settings.simulate,
    }


@router.post("/auth/setup")
async def auth_setup(body: SetupBody, request: Request, response: Response):
    if any_users_exist():
        raise HTTPException(409, "already_configured")
    if len(body.password) < 8:
        raise HTTPException(400, "password_too_short")
    if not body.username.strip():
        raise HTTPException(400, "username_required")
    s = db()
    try:
        user = User(username=body.username.strip(),
                    pw_hash=hash_password(body.password), role="admin")
        s.add(user)
        s.commit()
        s.refresh(user)
    finally:
        s.close()
    log_audit(user.username, "setup", "initial admin created")
    return create_session(user, request, response)


@router.post("/auth/login")
async def auth_login(body: LoginBody, request: Request, response: Response):
    ip = client_ip(request)
    check_rate_limit(ip, body.username)
    s = db()
    try:
        user = s.query(User).filter(User.username == body.username).first()
    finally:
        s.close()
    ok = user is not None and not user.disabled \
        and verify_password(user.pw_hash, body.password)
    if ok and user.totp_secret and not user.totp_secret.startswith("pending:"):
        if not totp.verify(user.totp_secret, body.totp or ""):
            record_login_result(ip, body.username, False)
            raise HTTPException(401, "totp_required" if not body.totp
                                else "totp_invalid")
    record_login_result(ip, body.username, ok)
    if not ok:
        log_audit(body.username, "login_failed", ip)
        raise HTTPException(401, "invalid_credentials")
    log_audit(user.username, "login", ip)
    return create_session(user, request, response)


@router.post("/auth/logout")
async def auth_logout(request: Request, response: Response,
                      ident: Identity = Depends(require_auth)):
    destroy_session(request, response)
    log_audit(ident.username, "logout")
    return {"ok": True}


class PasswordBody(BaseModel):
    old: str
    new: str


@router.post("/auth/password")
async def change_password(body: PasswordBody,
                          ident: Identity = Depends(require_auth)):
    if ident.user_id is None:
        raise HTTPException(400, "ingress_user")
    if len(body.new) < 8:
        raise HTTPException(400, "password_too_short")
    s = db()
    try:
        user = s.get(User, ident.user_id)
        if not verify_password(user.pw_hash, body.old):
            raise HTTPException(403, "wrong_password")
        user.pw_hash = hash_password(body.new)
        s.commit()
    finally:
        s.close()
    log_audit(ident.username, "password_changed")
    return {"ok": True}


@router.post("/auth/totp/setup")
async def totp_setup(ident: Identity = Depends(require_auth)):
    if ident.user_id is None:
        raise HTTPException(400, "ingress_user")
    secret = totp.new_secret()
    s = db()
    try:
        user = s.get(User, ident.user_id)
        user.totp_secret = "pending:" + secret
        s.commit()
    finally:
        s.close()
    return {"secret": secret,
            "uri": totp.provisioning_uri(secret, ident.username)}


class TotpBody(BaseModel):
    code: str


@router.post("/auth/totp/enable")
async def totp_enable(body: TotpBody, ident: Identity = Depends(require_auth)):
    s = db()
    try:
        user = s.get(User, ident.user_id)
        if not user.totp_secret.startswith("pending:"):
            raise HTTPException(400, "no_pending_totp")
        secret = user.totp_secret[8:]
        if not totp.verify(secret, body.code):
            raise HTTPException(400, "totp_invalid")
        user.totp_secret = secret
        s.commit()
    finally:
        s.close()
    log_audit(ident.username, "totp_enabled")
    return {"ok": True}


@router.post("/auth/totp/disable")
async def totp_disable(ident: Identity = Depends(require_auth)):
    s = db()
    try:
        user = s.get(User, ident.user_id)
        user.totp_secret = ""
        s.commit()
    finally:
        s.close()
    log_audit(ident.username, "totp_disabled")
    return {"ok": True}


# ---------------------------------------------------------------------------
# live status + websocket
# ---------------------------------------------------------------------------

@router.get("/status")
async def get_status(_: Identity = Depends(require_auth)):
    return snapshot.as_dict()


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    # session cookie is validated manually (WebSocket has no Depends auth here)
    ident = current_identity(websocket)  # Request-compatible: cookies/headers
    if ident is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    q = hub.subscribe()
    try:
        await websocket.send_text(json.dumps(
            {"type": "status", "data": snapshot.as_dict()}))
        while True:
            msg = await q.get()
            await websocket.send_text(msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe(q)


# ---------------------------------------------------------------------------
# control (operator+)
# ---------------------------------------------------------------------------

class ModeBody(BaseModel):
    mode: str
    timeout_s: int | None = None


@router.post("/control/mode")
async def set_mode(body: ModeBody,
                   ident: Identity = Depends(require_role("operator"))):
    client = _client()
    if client is None:
        raise HTTPException(503, "no_device")
    cmd = {"cmd": "mode", "mode": body.mode, "actor": f"user:{ident.username}"}
    if body.timeout_s:
        cmd["timeout_s"] = body.timeout_s
    res = await client.send_cmd(cmd)
    await _refresh_snapshot()
    log_audit(ident.username, "mode", body.mode)
    return res


class RunBody(BaseModel):
    duration_min: int


@router.post("/control/run")
async def manual_run(body: RunBody,
                     ident: Identity = Depends(require_role("operator"))):
    client = _client()
    if client is None:
        raise HTTPException(503, "no_device")
    res = await client.send_cmd({"cmd": "run",
                                 "duration_s": body.duration_min * 60,
                                 "actor": f"user:{ident.username}"})
    await _refresh_snapshot()
    log_audit(ident.username, "manual_run", f"{body.duration_min} min")
    return res


class FaultBody(BaseModel):
    cls: str


@router.post("/control/reset_fault")
async def reset_fault(body: FaultBody,
                      ident: Identity = Depends(require_role("operator"))):
    client = _client()
    if client is None:
        raise HTTPException(503, "no_device")
    res = await client.send_cmd({"cmd": "reset_fault", "class": body.cls,
                                 "actor": f"user:{ident.username}"})
    await _refresh_snapshot()
    log_audit(ident.username, "reset_fault", body.cls)
    return res


@router.post("/control/calibrate")
async def calibrate(ident: Identity = Depends(require_role("operator"))):
    client = _client()
    if client is None:
        raise HTTPException(503, "no_device")
    # ask the script to run and measure; here we trigger a manual run and
    # store the measured steady-state power after a short delay
    await client.send_cmd({"cmd": "run", "duration_s": 120,
                           "actor": f"user:{ident.username}"})
    await asyncio.sleep(10)
    status = await client.get_status()
    power = ((status.get("last") or {}).get("power_w")) or 0
    if power <= 5:
        raise HTTPException(409, "no_power_reading")
    res = await client.send_cmd({"cmd": "calibrate", "power_w": power,
                                 "actor": f"user:{ident.username}"})
    await configsvc.apply_changes(client, {"pump_power_nominal": power},
                                  f"user:{ident.username}")
    log_audit(ident.username, "calibrate", f"{power} W")
    return {"ok": True, "power_w": power, "res": res}


@router.post("/control/estop")
async def emergency_stop(ident: Identity = Depends(require_role("operator"))):
    client = _client()
    if client is None:
        raise HTTPException(503, "no_device")
    # belt and braces per spec §3: mode off via the script AND direct relay off
    try:
        await client.send_cmd({"cmd": "mode", "mode": "off",
                               "actor": f"user:{ident.username}"})
    finally:
        await client.switch_set(False)
    await _refresh_snapshot()
    log_audit(ident.username, "emergency_stop")
    return {"ok": True}


# ---------------------------------------------------------------------------
# configuration (admin)
# ---------------------------------------------------------------------------

@router.get("/config")
async def get_config(_: Identity = Depends(require_role("admin"))):
    return {"schema": configsvc.schema(), "values": configsvc.current_values()}


class ConfigBody(BaseModel):
    changes: dict


@router.put("/config")
async def put_config(body: ConfigBody,
                     ident: Identity = Depends(require_role("admin"))):
    if not body.changes:
        raise HTTPException(400, "no_changes")
    try:
        result = await configsvc.apply_changes(
            _client(), body.changes, f"user:{ident.username}")
    except configsvc.ValidationError as e:
        raise HTTPException(400, str(e))
    log_audit(ident.username, "config", body.changes)
    return result


@router.get("/device")
async def get_device(_: Identity = Depends(require_role("admin"))):
    client = _client()
    dev = None
    if snapshot.data:
        dev = snapshot.data.get("dev")
    info = {}
    if client is not None:
        try:
            info = await client.device_info()
        except Exception:
            info = {}
    return {"dev": dev, "info": info,
            "shelly_host": settings.shelly_host,
            "simulate": settings.simulate}


class DeviceBody(BaseModel):
    relay_id: int | None = None
    input_pump: int | None = None
    sensors: dict | None = None
    state_save_s: int | None = None


@router.put("/device")
async def put_device(body: DeviceBody,
                     ident: Identity = Depends(require_role("admin"))):
    client = _client()
    if client is None:
        raise HTTPException(503, "no_device")
    current = (snapshot.data or {}).get("dev") or {}
    dev = {
        "relay_id": body.relay_id if body.relay_id is not None
        else current.get("relay_id", 0),
        "input_pump": body.input_pump if body.input_pump is not None
        else current.get("input_pump", 0),
        "state_save_s": body.state_save_s if body.state_save_s is not None
        else current.get("state_save_s", 600),
        "sensors": body.sensors if body.sensors is not None
        else current.get("sensors", {}),
    }
    await client.kvs_set("pool.dev", dev)
    await client.reload()
    log_audit(ident.username, "device_config", dev)
    return {"ok": True, "dev": dev}


# ---------------------------------------------------------------------------
# history / events / audit
# ---------------------------------------------------------------------------

RANGES = {"day": 86400, "week": 7 * 86400, "month": 31 * 86400,
          "season": 184 * 86400, "all": 0}


@router.get("/history")
async def history(range: str = "day", _: Identity = Depends(require_auth)):
    span = RANGES.get(range)
    if span is None:
        raise HTTPException(400, "bad_range")
    since = time.time() - span if span else 0
    # bucket into ≤ 720 points
    bucket = max(60, int((span or (time.time() - 1735689600)) / 720))
    from sqlalchemy import text
    s = db()
    try:
        rows = s.execute(
            text(
                "SELECT CAST(ts/:b AS INTEGER)*:b AS t, "
                "AVG(water) w, AVG(mat) m, AVG(air) a, AVG(delta) d, "
                "AVG(power_w) p, MAX(relay) r, MAX(run_s_today) rs, "
                "MAX(heat_s_today) hs "
                "FROM samples WHERE ts >= :since GROUP BY t ORDER BY t"),
            {"b": bucket, "since": since}).mappings().all()
    finally:
        s.close()
    return {"bucket_s": bucket, "points": [
        {"ts": r["t"], "water": r["w"], "mat": r["m"], "air": r["a"],
         "delta": r["d"], "power_w": r["p"], "relay": bool(r["r"]),
         "run_s": r["rs"], "heat_s": r["hs"]}
        for r in rows]}


@router.get("/events")
async def events(limit: int = 200, before: float | None = None,
                 kinds: str | None = None,
                 _: Identity = Depends(require_auth)):
    s = db()
    try:
        q = s.query(Event).order_by(Event.ts.desc())
        if before:
            q = q.filter(Event.ts < before)
        if kinds:
            q = q.filter(Event.kind.in_(kinds.split(",")))
        rows = q.limit(min(limit, 1000)).all()
    finally:
        s.close()
    return [{"id": r.id, "ts": r.ts, "kind": r.kind,
             "data": json.loads(r.data)} for r in rows]


@router.get("/audit")
async def audit_log(limit: int = 200, before: float | None = None,
                    _: Identity = Depends(require_role("admin"))):
    s = db()
    try:
        q = s.query(Audit).order_by(Audit.ts.desc())
        if before:
            q = q.filter(Audit.ts < before)
        rows = q.limit(min(limit, 1000)).all()
    finally:
        s.close()
    return [{"id": r.id, "ts": r.ts, "user": r.user, "action": r.action,
             "detail": r.detail} for r in rows]


# ---------------------------------------------------------------------------
# users (admin)
# ---------------------------------------------------------------------------

class UserBody(BaseModel):
    username: str
    password: str | None = None
    role: str = "viewer"
    disabled: bool = False


@router.get("/users")
async def list_users(_: Identity = Depends(require_role("admin"))):
    s = db()
    try:
        return [{"id": u.id, "username": u.username, "role": u.role,
                 "disabled": u.disabled,
                 "totp": bool(u.totp_secret
                              and not u.totp_secret.startswith("pending:"))}
                for u in s.query(User).order_by(User.username).all()]
    finally:
        s.close()


@router.post("/users")
async def create_user(body: UserBody,
                      ident: Identity = Depends(require_role("admin"))):
    if body.role not in ("admin", "operator", "viewer"):
        raise HTTPException(400, "bad_role")
    if not body.password or len(body.password) < 8:
        raise HTTPException(400, "password_too_short")
    s = db()
    try:
        if s.query(User).filter(User.username == body.username).first():
            raise HTTPException(409, "user_exists")
        s.add(User(username=body.username.strip(),
                   pw_hash=hash_password(body.password), role=body.role,
                   disabled=body.disabled))
        s.commit()
    finally:
        s.close()
    log_audit(ident.username, "user_created", body.username)
    return {"ok": True}


@router.put("/users/{user_id}")
async def update_user(user_id: int, body: UserBody,
                      ident: Identity = Depends(require_role("admin"))):
    s = db()
    try:
        user = s.get(User, user_id)
        if user is None:
            raise HTTPException(404, "not_found")
        if body.role in ("admin", "operator", "viewer"):
            user.role = body.role
        user.disabled = body.disabled
        if body.password:
            if len(body.password) < 8:
                raise HTTPException(400, "password_too_short")
            user.pw_hash = hash_password(body.password)
        s.commit()
        name = user.username
    finally:
        s.close()
    log_audit(ident.username, "user_updated", name)
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int,
                      ident: Identity = Depends(require_role("admin"))):
    if ident.user_id == user_id:
        raise HTTPException(400, "cannot_delete_self")
    s = db()
    try:
        user = s.get(User, user_id)
        if user is None:
            raise HTTPException(404, "not_found")
        name = user.username
        s.delete(user)
        s.commit()
    finally:
        s.close()
    log_audit(ident.username, "user_deleted", name)
    return {"ok": True}


# ---------------------------------------------------------------------------
# backups (admin)
# ---------------------------------------------------------------------------

@router.get("/backup/list")
async def backups_list(_: Identity = Depends(require_role("admin"))):
    return backup_mod.list_backups()


@router.post("/backup/create")
async def backups_create(ident: Identity = Depends(require_role("admin"))):
    path = await asyncio.to_thread(backup_mod.create_backup)
    log_audit(ident.username, "backup_created", path.name)
    return {"ok": True, "name": path.name}


@router.get("/backup/download/{name}")
async def backups_download(name: str,
                           _: Identity = Depends(require_role("admin"))):
    path = backup_mod.backup_path(name)
    if path is None:
        raise HTTPException(404, "not_found")
    return FileResponse(path, filename=name, media_type="application/zip")


@router.delete("/backup/{name}")
async def backups_delete(name: str,
                         ident: Identity = Depends(require_role("admin"))):
    path = backup_mod.backup_path(name)
    if path is None:
        raise HTTPException(404, "not_found")
    path.unlink()
    log_audit(ident.username, "backup_deleted", name)
    return {"ok": True}


@router.post("/backup/restore")
async def backups_restore(file: UploadFile, restore_history: bool = False,
                          ident: Identity = Depends(require_role("admin"))):
    data = await file.read()
    if len(data) > 200 * 1024 * 1024:
        raise HTTPException(413, "too_large")
    result = await backup_mod.restore_backup(
        _client(), data, restore_history, f"user:{ident.username}")
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "restore_failed"))
    log_audit(ident.username, "backup_restored", file.filename or "")
    return result


@router.get("/backup/schedule")
async def backup_schedule_get(_: Identity = Depends(require_role("admin"))):
    s = db()
    try:
        return get_setting(s, "backup_schedule", backup_mod.DEFAULT_SCHEDULE)
    finally:
        s.close()


class ScheduleBody(BaseModel):
    enabled: bool
    time: str
    keep: int


@router.put("/backup/schedule")
async def backup_schedule_put(body: ScheduleBody,
                              ident: Identity = Depends(require_role("admin"))):
    if not (1 <= body.keep <= 365):
        raise HTTPException(400, "bad_keep")
    try:
        hh, mm = body.time.split(":")
        assert 0 <= int(hh) < 24 and 0 <= int(mm) < 60
    except (ValueError, AssertionError):
        raise HTTPException(400, "bad_time")
    s = db()
    try:
        set_setting(s, "backup_schedule", body.model_dump())
    finally:
        s.close()
    log_audit(ident.username, "backup_schedule", body.model_dump())
    return {"ok": True}


# ---------------------------------------------------------------------------
# app settings + notifications (admin)
# ---------------------------------------------------------------------------

@router.get("/settings/app")
async def app_settings_get(_: Identity = Depends(require_auth)):
    s = db()
    try:
        return {"timezone_scheduler": get_setting(s, "timezone_scheduler", "UTC")}
    finally:
        s.close()


class AppSettingsBody(BaseModel):
    timezone_scheduler: str | None = None


@router.put("/settings/app")
async def app_settings_put(body: AppSettingsBody,
                           ident: Identity = Depends(require_role("admin"))):
    s = db()
    try:
        if body.timezone_scheduler is not None:
            import zoneinfo
            try:
                zoneinfo.ZoneInfo(body.timezone_scheduler)
            except (KeyError, zoneinfo.ZoneInfoNotFoundError):
                raise HTTPException(400, "bad_timezone")
            set_setting(s, "timezone_scheduler", body.timezone_scheduler)
    finally:
        s.close()
    log_audit(ident.username, "app_settings", body.model_dump(exclude_none=True))
    return {"ok": True}


@router.get("/settings/notify")
async def notify_get(_: Identity = Depends(require_role("admin"))):
    channels = notify.get_channels()
    # never send secrets back in full
    red = json.loads(json.dumps(channels))
    for ch, fields in (("smtp", ["password"]), ("telegram", ["bot_token"])):
        for f in fields:
            if red[ch].get(f):
                red[ch][f] = "•••"
    return red


class NotifyBody(BaseModel):
    channels: dict


@router.put("/settings/notify")
async def notify_put(body: NotifyBody,
                     ident: Identity = Depends(require_role("admin"))):
    current = notify.get_channels()
    for name, cfg in body.channels.items():
        if name not in current or not isinstance(cfg, dict):
            continue
        for k, v in cfg.items():
            if v == "•••":       # unchanged masked secret
                continue
            if k in current[name]:
                current[name][k] = v
    s = db()
    try:
        set_setting(s, "notify_channels", current)
    finally:
        s.close()
    log_audit(ident.username, "notify_settings", list(body.channels))
    return {"ok": True}


@router.post("/settings/notify/test/{channel}")
async def notify_test(channel: str,
                      ident: Identity = Depends(require_role("admin"))):
    res = await notify.test_channel(channel)
    log_audit(ident.username, "notify_test", channel)
    return res


# ---------------------------------------------------------------------------
# system
# ---------------------------------------------------------------------------

@router.get("/system")
async def system(_: Identity = Depends(require_auth)):
    return {
        "version": settings.version,
        "simulate": settings.simulate,
        "device": snapshot.device_info,
        "online": snapshot.online,
        "influx": influx.status(),
        "mqtt": {"enabled": bool(settings.mqtt_host)},
        "auth_mode": settings.auth_mode,
        "shelly_host": settings.shelly_host if not settings.simulate else "(simulated)",
    }


# ---------------------------------------------------------------------------
# simulator fault injection (admin, sim mode only)
# ---------------------------------------------------------------------------

class SimOverride(BaseModel):
    slot: str
    value: float | None = None
    dead: bool = False


@router.post("/sim/sensor")
async def sim_sensor(body: SimOverride,
                     _: Identity = Depends(require_role("admin"))):
    if not settings.simulate:
        raise HTTPException(400, "not_simulating")
    client = _client()
    if body.dead:
        client.overrides[body.slot] = None
    elif body.value is None:
        client.overrides.pop(body.slot, None)
    else:
        client.overrides[body.slot] = body.value
    return {"ok": True, "overrides": client.overrides}


class SimPower(BaseModel):
    value: float | None = None


@router.post("/sim/power")
async def sim_power(body: SimPower,
                    _: Identity = Depends(require_role("admin"))):
    if not settings.simulate:
        raise HTTPException(400, "not_simulating")
    _client().power_override = body.value
    return {"ok": True}


@router.post("/sim/reset")
async def sim_reset(_: Identity = Depends(require_role("admin"))):
    if not settings.simulate:
        raise HTTPException(400, "not_simulating")
    client = _client()
    client.overrides = {}
    client.power_override = None
    return {"ok": True}
