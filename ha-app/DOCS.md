# Shelly Pool Control

Supervisory panel for a solar pool heating controlled by a **Shelly 2PM/1PM
Gen2+** with the Sensor Add-On. The safety-critical control loop runs on the
Shelly itself (`pool-control.js` script) — this app provides monitoring,
settings, history, users, notifications and backups.

Full documentation:
<https://github.com/steiner-dominik/shelly-pool-control>

## Setup

1. Install the `pool-control` and `pool-watchdog` scripts on your Shelly
   (see the main repository's install guide).
2. Set `shelly_host` (and `shelly_password` if device auth is enabled — it
   should be).
3. Open the panel from the sidebar. With ingress (default), Home Assistant
   handles authentication and you are mapped to the `ingress_role`.

## Options

| Option | Description |
|---|---|
| `shelly_host` | IP/hostname of the Shelly running the control script |
| `shelly_password` | Device admin password (if auth enabled) |
| `poll_seconds` | Status poll interval |
| `simulate` | Built-in simulator instead of real hardware (demo) |
| `auth_mode` | `ingress` (HA authenticates) or `local` (panel login page) |
| `ingress_role` | Role given to ingress users: admin / operator / viewer |
| `influx_*` | Optional InfluxDB v2 mirror of the telemetry |
| `mqtt_*` | Optional MQTT bridge with Home Assistant Discovery entities |

## MQTT entities

When `mqtt_host` is configured the panel publishes a native Home Assistant
device **Pool Heating** via MQTT Discovery: temperatures, ΔT, pump state and
power, runtime, mode select and a manual-run button. Commands from HA go
through the same validated command path as the panel — the Shelly remains the
control authority.

## Data

`/data` holds the SQLite database (settings, users, full history) and
scheduled backups. It is included in Home Assistant backups automatically.
