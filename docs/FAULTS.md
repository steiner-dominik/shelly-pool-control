# Fault reference / Störungsreferenz

Every fault class has a fixed detection rule and a **configurable response
policy** (Settings → Fault policies). Blocking faults stop the pump;
lockouts additionally require a manual reset (panel → Control, or long-press
on the physical button).

| Class | Detection | Default response | Reset |
|---|---|---|---|
| `sensor_fail_water` | both water probes invalid | `safe_off` (pump off) | auto after recovery + hold time |
| `sensor_fail_mat` | both mat probes invalid | `safe_off` | auto |
| `sensor_fail_air` | air probe invalid | `warn_only` | auto |
| `dry_run` | pump on, power < min % of nominal | off + **lockout** | manual |
| `overload` | pump on, power > max % of nominal | off + **lockout** (always) | manual |
| `no_power` | pump commanded on, ~0 W | off + **lockout** | manual |
| `mat_overtemp` | mat ≥ limit | `circulate` (cool the mat, harvest heat) | auto |
| `relay_stuck` | power flowing while commanded off | alert (relay can't open — cut the breaker!) | auto when power stops |
| `time_invalid` | no NTP sync | degrade gracefully: pure ΔT control, schedules paused | auto |

Warnings (non-blocking): `degraded_<role>` (one probe of a pair failed),
`divergence_<role>` (pair disagrees beyond threshold — check probes!),
`stuck_<probe>` (value frozen), `time_invalid`.

## Policy guidance

- **`safe_off` vs `fallback_schedule`** (dead water/mat sensor): off+alert is
  safest for the *pump*; the timed fallback schedule is safest for *water
  quality* in summer (keeps water moving, harvests some heat). That's why
  it's your choice, not a hardcode.
- **`continue_mat_only`**: heats purely on mat temperature against a
  configured assumed water temperature — availability over precision,
  clearly shown as degraded in the panel.
- **`retry` power-fault policy**: N automatic restart attempts with backoff,
  then lockout. Useful for pumps that occasionally suck air; keep `lockout`
  until you trust the installation.

## Where to look

- **Dashboard → decision feed**: the controller explains every relay
  decision ("why is it (not) running?").
- **Log → events**: complete fault/mode/decision journal (kept forever).
- **Control → faults**: active faults and lockout reset buttons.
