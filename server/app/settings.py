"""Runtime configuration from environment variables.

Every value has a sane default; secrets only ever come from the environment
(or the Home Assistant add-on options file) — never from the repository.
When running as a Home Assistant app, /data/options.json overrides env vars.
"""

from __future__ import annotations

import json
import os
import pathlib

_HA_OPTIONS = pathlib.Path("/data/options.json")


def _ha_options() -> dict:
    if _HA_OPTIONS.exists():
        try:
            return json.loads(_HA_OPTIONS.read_text())
        except (OSError, ValueError):
            return {}
    return {}


class Settings:
    def __init__(self) -> None:
        ha = _ha_options()

        def get(env: str, ha_key: str, default: str = "") -> str:
            if ha_key in ha and ha[ha_key] not in (None, ""):
                return str(ha[ha_key])
            return os.environ.get(env, default)

        self.version = os.environ.get("POOL_VERSION", "dev")
        self.data_dir = pathlib.Path(os.environ.get("POOL_DATA_DIR", "/data"))
        self.bind_host = os.environ.get("POOL_BIND", "0.0.0.0")
        self.bind_port = int(os.environ.get("POOL_PORT", "8080"))

        # device
        self.shelly_host = get("POOL_SHELLY_HOST", "shelly_host")
        self.shelly_password = get("POOL_SHELLY_PASSWORD", "shelly_password")
        self.poll_seconds = float(get("POOL_POLL_SECONDS", "poll_seconds", "5"))
        self.simulate = get("POOL_SIMULATE", "simulate", "0") in ("1", "true", "True")

        # auth
        self.auth_mode = get("POOL_AUTH_MODE", "auth_mode", "local")  # local|ingress
        self.ingress_role = get("POOL_INGRESS_ROLE", "ingress_role", "admin")
        self.trusted_proxies = [
            p.strip() for p in
            get("POOL_TRUSTED_PROXIES", "trusted_proxies", "").split(",") if p.strip()
        ]
        self.session_ttl_s = int(get("POOL_SESSION_TTL", "session_ttl", "1209600"))
        self.secure_cookies = get("POOL_SECURE_COOKIES", "secure_cookies", "auto")

        # backups
        self.backup_dir = pathlib.Path(
            os.environ.get("POOL_BACKUP_DIR", str(self.data_dir / "backups")))

        # optional InfluxDB mirror
        self.influx_url = get("POOL_INFLUX_URL", "influx_url")
        self.influx_token = get("POOL_INFLUX_TOKEN", "influx_token")
        self.influx_org = get("POOL_INFLUX_ORG", "influx_org")
        self.influx_bucket = get("POOL_INFLUX_BUCKET", "influx_bucket")

        # optional MQTT (Home Assistant discovery)
        self.mqtt_host = get("POOL_MQTT_HOST", "mqtt_host")
        self.mqtt_port = int(get("POOL_MQTT_PORT", "mqtt_port", "1883"))
        self.mqtt_user = get("POOL_MQTT_USER", "mqtt_user")
        self.mqtt_password = get("POOL_MQTT_PASSWORD", "mqtt_password")
        self.mqtt_prefix = get("POOL_MQTT_PREFIX", "mqtt_prefix", "pool_heating")
        self.mqtt_tls = get("POOL_MQTT_TLS", "mqtt_tls", "0") in ("1", "true", "True")

        self.log_level = os.environ.get("POOL_LOG_LEVEL", "INFO")

    @property
    def db_path(self) -> pathlib.Path:
        return self.data_dir / "pool.sqlite3"


settings = Settings()
