# Decision Core — Normative Specification

The decision core is the single safety-critical piece of this project. It is a
**pure, deterministic function** implemented twice — in Python
(`server/app/core/decision.py`, used by the server simulator and for config
preview) and in restricted JavaScript (`shelly/src/core.js`, running on the
device). Both implementations MUST pass the shared test vectors in
`shared/test-vectors/` in CI. The vectors are the contract; this document is
its human-readable form.

```
step(inputs, config, state) → { state', relay, reason, detail,
                                faults, warnings, events }
```

No I/O, no clocks, no randomness inside the core. All time comes in through
`inputs`. The device wrapper and the simulator wrapper are thin shells around
this function.

## 1. Inputs (per tick)

| Field | Type | Meaning |
|---|---|---|
| `now` | int | epoch seconds |
| `dt` | int | seconds since previous tick |
| `uptime` | int | seconds since device boot |
| `time_valid` | bool | device has valid wall-clock time (NTP synced) |
| `local_min` | int | minutes since local midnight (0–1439), only meaningful if `time_valid` |
| `local_day` | int | local date as `YYYYMMDD`, only meaningful if `time_valid` |
| `sensors` | object | raw readings per probe slot: `water_a, water_b, mat_a, mat_b, air` → `number \| null` (null = read error / missing / unmapped) |
| `power_w` | number | measured active pump power (W) |
| `relay_actual` | bool | actual relay state reported by hardware |
| `commands` | array | pending validated commands (§7), applied this tick in order |

## 2. Configuration keys

Flat snake_case keys. Every key has a default in code; a missing key means
default. All durations in **seconds**, temperatures in **°C**, times of day in
**minutes since local midnight**.

### Loop & boot
| Key | Default | Range | Meaning |
|---|---|---|---|
| `tick_s` | 15 | 5–60 | control loop interval |
| `boot_settle_s` | 20 | 0–300 | no decisions until `uptime` exceeds this |
| `boot_policy` | `resume` | `resume\|always_auto\|always_off` | mode restored after boot |

### Sensor validation
| Key | Default | Meaning |
|---|---|---|
| `water_min` / `water_max` | −5 / 45 | plausible range, water probes |
| `mat_min` / `mat_max` | −20 / 95 | plausible range, mat probes |
| `air_min` / `air_max` | −30 / 50 | plausible range, air probe |
| `roc_water` / `roc_mat` / `roc_air` | 5 / 15 / 10 | max plausible change (K) per tick |
| `reset85_boot_s` | 120 | 85.0 °C is invalid within this time after boot |
| `stuck_window_s` | 21600 | advisory stuck detection window |
| `offset_<slot>` | 0 | per-probe calibration offset, added before validation |
| `div_water` / `div_mat` | 1.5 / 4.0 | pair divergence threshold (K) |
| `agg_water` / `agg_mat` | `avg` | pair aggregation: `avg\|min\|max\|prefer_a` |
| `divpol_water` / `divpol_mat` | `conservative` | divergent-pair policy: `conservative\|avg\|prefer_a` |

`conservative` selects the value that makes heating *less* likely:
**max** for water, **min** for mat.

### Heating (mode `auto`)
| Key | Default | Meaning |
|---|---|---|
| `dt_start` | 5.0 | start when `mat_eff − water_eff ≥ dt_start` |
| `dt_stop` | 2.0 | stop when `mat_eff − water_eff ≤ dt_stop` |
| `target_water_max` | 29.0 | stop heating at this water temp |
| `water_hyst` | 0.5 | heating may not restart until water < target − hyst |
| `absolute_water_max` | 32.0 | hard stop for any heat-motivated pumping (boost and overtemp-circulate included) |
| `window_start_min` / `window_end_min` | 510 / 1200 | heating window (08:30–20:00) |
| `min_run_s` | 600 | minimum heating runtime |
| `min_pause_s` | 300 | minimum pause after a stop |

### Filtration (mode `auto`)
| Key | Default | Meaning |
|---|---|---|
| `filt_target_s` | 14400 | daily pump-runtime target (any cause counts) |
| `filt_check_min` | 1020 | deficit-run start time (17:00) |
| `filt_block_max_s` | 7200 | max continuous deficit block |
| `filt_block_pause_s` | 900 | pause between deficit blocks |
| `day_reset_min` | 0 | daily counter reset time |

### Overtemperature
| Key | Default | Meaning |
|---|---|---|
| `mat_overtemp_limit` | 70 | mat stagnation threshold |
| `mat_overtemp_action` | `circulate` | `circulate\|alert_only\|lockout` |

### Frost protection
| Key | Default | Meaning |
|---|---|---|
| `frost_enabled` | true | active in every mode except `winter` |
| `frost_threshold` | 2.0 | air temp trigger |
| `frost_run_s` / `frost_interval_s` | 600 / 3600 | run X every Y while triggered |

### Pump power signature
| Key | Default | Meaning |
|---|---|---|
| `pump_power_nominal` | 0 | calibrated nominal W; 0 = uncalibrated → dry-run/overload detection disabled, `no_power` still active |
| `pump_power_min_pct` / `pump_power_max_pct` | 55 / 130 | dry-run / overload band, % of nominal |
| `no_power_threshold_w` | 10 | below this = electrically dead |
| `power_grace_s` | 30 | condition must persist this long |
| `start_ignore_s` | 5 | ignore power right after start (inrush) |
| `power_fault_action` | `lockout` | `lockout\|retry` |
| `retry_max` / `retry_backoff_s` | 3 / 300 | for `retry`: attempts before lockout |

### Fault policies
| Key | Default | Allowed |
|---|---|---|
| `pol_sensor_fail_water` | `safe_off` | `safe_off\|fallback_schedule\|continue_mat_only` |
| `pol_sensor_fail_mat` | `safe_off` | `safe_off\|fallback_schedule` |
| `pol_sensor_fail_air` | `warn_only` | `warn_only\|safe_off` |
| `assumed_water_temp` | 22.0 | for `continue_mat_only` |
| `fallback_run_s` | 900 | fallback schedule: run X … |
| `fallback_interval_s` | 7200 | … every Y … |
| `fallback_start_min` / `fallback_end_min` | 600 / 1020 | … inside this window (10:00–17:00) |
| `fault_clear_hold_s` | 300 | non-lockout faults auto-clear after condition gone this long |

### Modes & sampling
| Key | Default | Meaning |
|---|---|---|
| `force_timeout_s` | 3600 | default `force_on` timeout (hard max 86400) |
| `boost_timeout_s` | 14400 | `boost` auto-expiry (0 = until stopped) |
| `sample_enabled` | false | pipe-mounted-sensor sampling runs |
| `sample_interval_s` / `sample_duration_s` | 3600 / 120 | sampling cadence |

## 3. Sensor pipeline (every tick)

Per probe slot: apply offset → **invalid** if null, out of role range, exactly
85.0 within `reset85_boot_s` of boot, or |change| > `roc_<role>` vs. the
previous *valid* reading of that slot in one tick. Stuck detection (< 0.1 K
change over `stuck_window_s` while the pump state changed or a sibling moved
> 2 K) raises warning `stuck_<slot>` only.

Pair aggregation for `water` and `mat`:
- both valid, |a−b| ≤ threshold → `agg_*` policy
- both valid, divergent → warning `divergence_<role>`, value per `divpol_*`
- one valid → that one, warning `degraded_<role>`
- none valid → role **failed** → fault `sensor_fail_<role>`

`air` is a single probe: invalid → `sensor_fail_air`.

## 4. State machine

Modes: `auto | off | force_on | boost | winter`.

Relay decision priority (first match wins):

1. `uptime < boot_settle_s` → **off**, reason `settle`
2. mode `winter` → **off**, reason `winter` (frost logic disabled — circuit is drained)
3. blocking power fault active/locked (`dry_run`, `overload`, `no_power`) → **off**, reason `fault:<class>`
4. mode `force_on` → **on**, reason `force` (expires → previous mode). Power-signature faults still monitored.
5. frost protection (any mode except `winter`, incl. `off`): air ≤ threshold and due → **on**, reason `frost`
6. mode `off` → **off**, reason `off`
7. mode `boost` → heat while `water_eff < absolute_water_max` and water role usable, ignoring window and quota, reason `boost`
8. mode `auto`:
   a. mat overtemp & action `circulate` & `water_eff < absolute_water_max` → **on**, reason `overtemp_circulate` (action `lockout` → blocking fault `mat_overtemp`)
   b. blocking sensor fault with `safe_off` → **off**, reason `fault:sensor_fail_<role>`
   c. `fallback_schedule` policy active → timed pattern, reason `fallback`
   d. heating decision (§5), reason `dt_start` / `dt_stop` / `window` / `water_max` / `min_run` / `min_pause` / `quota`…
   e. filtration deficit (§6), reason `quota_deficit`
   f. otherwise **off**, reason `idle`

Every relay *change* emits an event with reason + detail. `reason` values are
stable codes asserted by the vectors; `detail` is free-form.

## 5. Heating decision

Start when **all**: `mat_eff − water_eff ≥ dt_start`; `water_eff <
target_water_max − water_hyst` (hysteresis latch: once stopped for
`water_max`, blocked until below target − hyst); window open (skipped when
`time_valid` is false — pure ΔT control); `now − last_stop ≥ min_pause_s`; no
blocking fault.

Stop when **any**: `mat_eff − water_eff ≤ dt_stop` **and** run ≥ `min_run_s`;
`water_eff ≥ target_water_max`; window closes; mode change; blocking fault
(immediate, `min_run_s` does not delay safety stops).

## 6. Filtration quota

All pump runtime (any reason) accumulates into `run_s_today`; heating runtime
additionally into `heat_s_today`. Counters reset when `local_day` changes at
`day_reset_min` (requires `time_valid`; when time is invalid counters keep
accumulating, no reset, deficit logic paused, warning `time_invalid`).

From `filt_check_min` onward, if `run_s_today < filt_target_s`, run the pump
in blocks of at most `filt_block_max_s` with `filt_block_pause_s` pauses until
the quota is met or the day resets.

## 7. Commands

Commands arrive pre-parsed; the core validates semantics and returns per-command
`ack` events (`ok` or error code). Unknown commands → `err:unknown`.

| Command | Fields | Validation |
|---|---|---|
| `mode` | `mode`, `timeout_s?` | valid mode name; `force_on` timeout clamped to 60–86400 s; entering any mode clears `boost`/`force` latches; previous mode remembered for expiry |
| `run` | `duration_s` | manual run == `force_on` with explicit timeout |
| `reset_fault` | `class` | clears a lockout only if the underlying condition is gone |
| `calibrate` | `power_w` | sets `pump_power_nominal` in state′ (wrapper persists to config) |

## 8. Faults

| Class | Blocking | Lockout | Cleared |
|---|---|---|---|
| `sensor_fail_water` | per policy | no | auto after `fault_clear_hold_s` |
| `sensor_fail_mat` | per policy | no | auto |
| `sensor_fail_air` | per policy | no | auto |
| `dry_run` | yes | per `power_fault_action` | manual reset (lockout) / auto (retry window) |
| `overload` | yes | always | manual reset |
| `no_power` | yes | per `power_fault_action` | manual reset / retry |
| `mat_overtemp` | only `lockout` action | per action | auto / manual |
| `relay_stuck` | n/a (relay won't open) | alert only | auto when power drops |
| `time_invalid` | no | no | auto when time returns |

Warnings (non-blocking, no policy): `degraded_<role>`, `divergence_<role>`,
`stuck_<slot>`, `time_invalid`.

## 9. Test-vector format

`shared/test-vectors/*.json`, each file:

```json
{ "vectors": [ {
    "name": "…", "description": "…",
    "config": { "dt_start": 4.0 },
    "start_local_min": 600, "start_day": 20260715, "time_valid": true,
    "steps": [
      { "dt": 15,
        "in":  { "sensors": { "water_a": 22.0 }, "power_w": 800 },
        "cmd": [ { "cmd": "mode", "mode": "boost" } ],
        "expect": { "relay": true, "reason": "dt_start", "mode": "auto",
                    "faults": ["dry_run"], "warnings_has": ["degraded_water"],
                    "state": { "run_s_today": 15 } } } ] } ] }
```

Runner semantics (identical in both harnesses): inputs are **sticky** across
steps (each step merges over the previous inputs); `now` advances by `dt`
(default `tick_s`); `local_min`/`local_day` are derived from
`start_local_min`/`start_day` plus elapsed time; `uptime` starts at
`boot_settle_s` + 1 unless the vector sets `"uptime": n` explicitly (then it
advances from there); unspecified sensors default to plausible idle values
(water 22, mat 24, air 15); `power_w` defaults to 0 when the relay is off and
`pump_power_nominal` (or 800) when on, unless explicitly set. `expect.faults`
is compared as the exact set of **active** fault classes; `warnings_has` /
`faults_has` check inclusion; `state` does subset comparison on the returned
state. `expect.relay` refers to the commanded relay after the step.
