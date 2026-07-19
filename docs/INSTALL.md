# Installation

## 1. Hardware

| Part | Notes |
|---|---|
| Shelly 2PM or 1PM (Gen2 or newer) | Pump on channel 1 (`switch:0` by default, configurable) |
| Shelly Sensor Add-On | max. 5× DS18B20 per Add-On (firmware limit) |
| DS18B20 probes | recommended: 2× water, 2× mat, 1× shaded outside air. Fewer probes work — unmapped roles are allowed |
| Pump | switched directly by the relay; check the nameplate current against the relay rating and consider a contactor for heavy induction motors |

Wire the probes, then add them in the Shelly web UI (Add-On → add
peripheral). Note the component IDs (`temperature:100` …). Label the physical
probes (W1, W2, M1, M2, A1).

**Configure the Shelly's built-in protections** (Settings → safety) as a
hardware-level backstop independent of any script: overpower limit (e.g.
1200 W for an 800 W pump), overcurrent, overtemperature auto-off.

Enable **device authentication** (Settings → Auth) and NTP/timezone.

## 2. Shelly scripts

Either take `dist-shelly-scripts.zip` from the
[latest release](https://github.com/steiner-dominik/shelly-pool-control/releases/latest)
and paste the two files in the Shelly web UI (Scripts → Add script — names
**must** be `pool-control` and `pool-watchdog`), enabling *Run on startup*
for both — or deploy from a checkout:

```bash
node shelly/build.mjs
node shelly/deploy.mjs --host <shelly-ip> --password '<admin-pw>'
```

The control script starts with safe defaults (everything off until sensors
deliver plausible values; conservative fault policies).

## 3. Panel container

See the [Quick start](../README.md#-quick-start-no-hardware-needed). Set
`POOL_SHELLY_HOST` (+ `POOL_SHELLY_PASSWORD`) in `.env`, start the
container, create the admin account.

- **Sensors page** → map roles to the component IDs from step 1, set the
  relay channel (2PM channel 1 = `0`) and button input.
- **Control page** → run *pump power calibration* once water is flowing:
  this stores the nominal power draw that dry-run/overload detection needs.
- **Settings page** → review every group; each parameter shows unit, range,
  default and help text.

## 4. Reverse proxy (remote access)

Terminate TLS at your proxy and forward to the container. Example (Caddy):

```
pool.example.com {
    reverse_proxy pool-control:8080
}
```

Set `POOL_TRUSTED_PROXIES` to the proxy's IP/CIDR so the app trusts
`X-Forwarded-For/-Proto` from it (correct client IPs in the audit log,
Secure cookies). Never expose port 8080 directly to the internet.

## 5. Home Assistant (optional)

- Panel inside HA: install via
  [home-assistant-apps](https://github.com/steiner-dominik/home-assistant-apps).
- Native entities: set `POOL_MQTT_*` to your broker — a *Pool Heating*
  device appears via MQTT Discovery.

## 6. Go live

Work through the German rollout checklist in [ROLLOUT.md](ROLLOUT.md) —
conservative first config, 48 h observation, dry-run detection verification.
