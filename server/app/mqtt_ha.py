"""Optional MQTT bridge with Home Assistant Discovery.

The *server* is the MQTT client (the Shelly script stays HTTP-only and
remains the validator of every command). When MQTT is configured, the pool
appears in Home Assistant as one device with native entities; commands from
HA are forwarded to the on-device script like any other client.
"""

from __future__ import annotations

import asyncio
import json
import threading

from .settings import settings

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover
    mqtt = None


class HaBridge:
    def __init__(self, client, loop: asyncio.AbstractEventLoop):
        self.device_client = client
        self.loop = loop
        self.mq = None
        self.prefix = settings.mqtt_prefix
        self.avail_topic = f"{self.prefix}/availability"
        self._started = False

    def enabled(self) -> bool:
        return bool(mqtt is not None and settings.mqtt_host)

    def start(self):
        if not self.enabled() or self._started:
            return
        self._started = True
        self.mq = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                              client_id="shelly-pool-control")
        if settings.mqtt_user:
            self.mq.username_pw_set(settings.mqtt_user, settings.mqtt_password)
        if settings.mqtt_tls:
            self.mq.tls_set()
        self.mq.will_set(self.avail_topic, "offline", retain=True)
        self.mq.on_connect = self._on_connect
        self.mq.on_message = self._on_message
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self.mq.connect(settings.mqtt_host, settings.mqtt_port, 60)
            self.mq.loop_forever(retry_first_connection=True)
        except Exception:
            pass

    def _on_connect(self, *_args, **_kw):
        self.mq.subscribe(f"{self.prefix}/cmd/#")
        self.mq.publish(self.avail_topic, "online", retain=True)
        self._publish_discovery()

    def _on_message(self, _client, _userdata, msg):
        try:
            payload = msg.payload.decode()
        except UnicodeDecodeError:
            return
        parts = msg.topic.split("/")
        if len(parts) < 3:
            return
        what = parts[2]
        cmd = None
        if what == "mode" and payload in ("auto", "off", "force_on", "boost", "winter"):
            cmd = {"cmd": "mode", "mode": payload, "actor": "ha"}
        elif what == "run":
            try:
                cmd = {"cmd": "run", "duration_s": int(float(payload)) * 60,
                       "actor": "ha"}
            except ValueError:
                return
        elif what == "reset_fault":
            cmd = {"cmd": "reset_fault", "class": payload, "actor": "ha"}
        if cmd is not None and self.device_client is not None:
            asyncio.run_coroutine_threadsafe(
                self.device_client.send_cmd(cmd), self.loop)

    def _dev(self) -> dict:
        return {
            "identifiers": ["shelly_pool_control"],
            "name": "Pool Heating",
            "manufacturer": "shelly-pool-control",
            "model": "Solar pool controller",
            "sw_version": settings.version,
        }

    def _disc(self, component: str, object_id: str, cfg: dict):
        base = {
            "availability_topic": self.avail_topic,
            "device": self._dev(),
            "unique_id": f"pool_heating_{object_id}",
            "object_id": f"pool_heating_{object_id}",
        }
        base.update(cfg)
        self.mq.publish(
            f"homeassistant/{component}/pool_heating/{object_id}/config",
            json.dumps(base), retain=True)

    def _publish_discovery(self):
        st = f"{self.prefix}/state"
        temp = {"state_topic": st, "device_class": "temperature",
                "unit_of_measurement": "°C", "state_class": "measurement"}
        self._disc("sensor", "water", dict(temp, name="Water temperature",
                   value_template="{{ value_json.water }}"))
        self._disc("sensor", "mat", dict(temp, name="Mat temperature",
                   value_template="{{ value_json.mat }}"))
        self._disc("sensor", "air", dict(temp, name="Air temperature",
                   value_template="{{ value_json.air }}"))
        self._disc("sensor", "delta", dict(temp, name="ΔT mat−water",
                   value_template="{{ value_json.delta }}"))
        self._disc("sensor", "power", {
            "state_topic": st, "name": "Pump power",
            "device_class": "power", "unit_of_measurement": "W",
            "state_class": "measurement",
            "value_template": "{{ value_json.power_w }}"})
        self._disc("sensor", "runtime_today", {
            "state_topic": st, "name": "Runtime today",
            "unit_of_measurement": "min", "state_class": "total_increasing",
            "value_template": "{{ value_json.run_min_today }}"})
        self._disc("sensor", "reason", {
            "state_topic": st, "name": "Decision reason",
            "value_template": "{{ value_json.reason }}"})
        self._disc("binary_sensor", "pump", {
            "state_topic": st, "name": "Pump", "device_class": "running",
            "payload_on": "on", "payload_off": "off",
            "value_template": "{{ value_json.pump }}"})
        self._disc("binary_sensor", "fault", {
            "state_topic": st, "name": "Fault", "device_class": "problem",
            "payload_on": "on", "payload_off": "off",
            "value_template": "{{ value_json.fault }}"})
        self._disc("select", "mode", {
            "state_topic": st, "name": "Mode",
            "command_topic": f"{self.prefix}/cmd/mode",
            "options": ["auto", "off", "force_on", "boost", "winter"],
            "value_template": "{{ value_json.mode }}"})
        self._disc("button", "run_30", {
            "name": "Run pump 30 min",
            "command_topic": f"{self.prefix}/cmd/run", "payload_press": "30"})

    def publish_state(self, snap: dict):
        if not self._started or self.mq is None:
            return
        status = snap.get("status") or {}
        last = status.get("last") or {}
        eff = last.get("effective") or {}
        payload = {
            "water": eff.get("water"), "mat": eff.get("mat"),
            "air": eff.get("air"), "delta": eff.get("delta"),
            "power_w": last.get("power_w"),
            "pump": "on" if status.get("relay") else "off",
            "fault": "on" if (last.get("faults") or []) else "off",
            "mode": status.get("mode"),
            "reason": last.get("reason"),
            "run_min_today": round((status.get("run_s_today") or 0) / 60),
        }
        try:
            self.mq.publish(f"{self.prefix}/state", json.dumps(payload))
        except Exception:
            pass


bridge: HaBridge | None = None
