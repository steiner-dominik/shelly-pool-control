"""SQLite persistence via SQLAlchemy.

Small, append-mostly schema. History is kept forever by design (§ "History is
kept forever" in the spec) — at one sample/minute this grows a few MB per
season, which SQLite handles trivially.
"""

from __future__ import annotations

import datetime
import json
import time

from sqlalchemy import (Boolean, Float, Integer, String, Text, create_engine,
                        event)
from sqlalchemy.orm import (DeclarativeBase, Mapped, Session, mapped_column,
                            sessionmaker)

from .settings import settings


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    pw_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="viewer")  # admin|operator|viewer
    totp_secret: Mapped[str] = mapped_column(String(64), default="")
    created: Mapped[float] = mapped_column(Float, default=time.time)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)


class WebSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    csrf: Mapped[str] = mapped_column(String(64))
    created: Mapped[float] = mapped_column(Float, default=time.time)
    expires: Mapped[float] = mapped_column(Float, index=True)
    ip: Mapped[str] = mapped_column(String(64), default="")


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    user: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[str] = mapped_column(Text, default="")


class Event(Base):
    """Journal of device events: mode changes, faults, decisions, offline."""
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    data: Mapped[str] = mapped_column(Text, default="{}")


class Sample(Base):
    """Telemetry history, one row per stored poll (decimated)."""
    __tablename__ = "samples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[float] = mapped_column(Float, index=True)
    water: Mapped[float | None] = mapped_column(Float, nullable=True)
    mat: Mapped[float | None] = mapped_column(Float, nullable=True)
    air: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_w: Mapped[float] = mapped_column(Float, default=0)
    relay: Mapped[bool] = mapped_column(Boolean, default=False)
    mode: Mapped[str] = mapped_column(String(16), default="")
    reason: Mapped[str] = mapped_column(String(48), default="")
    run_s_today: Mapped[int] = mapped_column(Integer, default=0)
    heat_s_today: Mapped[int] = mapped_column(Integer, default=0)


class ConfigMirror(Base):
    """Server-side mirror of the device KVS parameters."""
    __tablename__ = "config_mirror"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)           # JSON-encoded
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    updated: Mapped[float] = mapped_column(Float, default=time.time)


class Setting(Base):
    """Server-side app settings (timezone, notification channels, backup plan)."""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)           # JSON-encoded


engine = None
SessionLocal: sessionmaker[Session] | None = None


def init_db(db_url: str | None = None):
    global engine, SessionLocal
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    url = db_url or f"sqlite:///{settings.db_path}"
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    return engine


def db() -> Session:
    assert SessionLocal is not None, "init_db() not called"
    return SessionLocal()


def get_setting(s: Session, key: str, default=None):
    row = s.get(Setting, key)
    if row is None:
        return default
    try:
        return json.loads(row.value)
    except ValueError:
        return default


def set_setting(s: Session, key: str, value) -> None:
    row = s.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=json.dumps(value))
        s.add(row)
    else:
        row.value = json.dumps(value)
    s.commit()


def audit(s: Session, user: str, action: str, detail: dict | str = "") -> None:
    if isinstance(detail, dict):
        detail = json.dumps(detail)
    s.add(Audit(user=user, action=action, detail=detail))
    s.commit()


def journal(s: Session, kind: str, data: dict) -> None:
    s.add(Event(kind=kind, data=json.dumps(data)))
    s.commit()


def iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(
        ts, tz=datetime.timezone.utc).isoformat()
