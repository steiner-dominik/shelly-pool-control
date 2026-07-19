"""Application assembly."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import pathlib

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import api, backup, mqtt_ha, poller
from .auth import cleanup_sessions
from .db import init_db
from .settings import settings
from .shelly import make_client, snapshot
from .ws import hub

log = logging.getLogger("pool")

STATIC_DIR = pathlib.Path(__file__).parent / "static"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=settings.log_level)
    init_db()
    client = make_client()
    api.device["client"] = client
    tasks = []
    if client is not None:
        if settings.simulate:
            client.start()
        tasks.append(asyncio.create_task(poller.poll_loop(client)))
    tasks.append(asyncio.create_task(backup.scheduler_loop()))
    tasks.append(asyncio.create_task(_session_gc()))

    loop = asyncio.get_event_loop()
    mqtt_ha.bridge = mqtt_ha.HaBridge(client, loop)
    mqtt_ha.bridge.start()
    tasks.append(asyncio.create_task(_mqtt_state_loop()))

    log.info("shelly-pool-control %s started (simulate=%s, device=%s)",
             settings.version, settings.simulate,
             settings.shelly_host or "-")
    yield
    for t in tasks:
        t.cancel()
    if client is not None:
        await client.close()


async def _session_gc():
    while True:
        try:
            cleanup_sessions()
        except Exception:
            pass
        await asyncio.sleep(3600)


async def _mqtt_state_loop():
    q = hub.subscribe()
    while True:
        try:
            import json
            msg = json.loads(await q.get())
            if msg.get("type") == "status" and mqtt_ha.bridge:
                mqtt_ha.bridge.publish_state(msg["data"])
        except Exception:
            await asyncio.sleep(1)


app = FastAPI(title="shelly-pool-control", version=settings.version,
              lifespan=lifespan, docs_url=None, redoc_url=None,
              openapi_url=None)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if settings.auth_mode != "ingress":
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "connect-src 'self' ws: wss:; frame-ancestors "
        + ("*" if settings.auth_mode == "ingress" else "'self'"))
    return response


@app.get("/healthz")
async def healthz():
    return {"ok": True, "version": settings.version,
            "device_online": snapshot.online}


@app.get("/api/version")
async def version():
    # polled by the PWA to detect new releases and trigger a full reload
    return JSONResponse({"version": settings.version},
                        headers={"Cache-Control": "no-store"})


app.include_router(api.router)

# ---- frontend ---------------------------------------------------------------
# Vite build output; hashed assets get long-lived caching, entry points none.
if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"),
              name="assets")

_NO_CACHE = {"Cache-Control": "no-cache, must-revalidate"}


@app.get("/{path:path}")
async def spa(path: str):
    if path in ("", "index.html"):
        return FileResponse(STATIC_DIR / "index.html", headers=_NO_CACHE)
    target = (STATIC_DIR / path).resolve()
    if target.is_file() and STATIC_DIR.resolve() in target.parents:
        headers = _NO_CACHE if path in ("sw.js", "manifest.webmanifest") else {}
        return FileResponse(target, headers=headers)
    if path.startswith("api/"):
        return JSONResponse({"detail": "not_found"}, status_code=404)
    return FileResponse(STATIC_DIR / "index.html", headers=_NO_CACHE)
