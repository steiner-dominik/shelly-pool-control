// Shared test-vector harness for the mJS decision core.
// Mirrors server/tests/vector_runner.py exactly — keep both in sync.
// Runs under Node >= 20 and Deno (node compat): `node shelly/test/run-vectors.mjs`

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..", "..");
const vectorDir = join(repo, "shared", "test-vectors");

// core.js is a plain mJS script (no modules); evaluate it in a function scope.
const coreSrc = readFileSync(join(here, "..", "src", "core.js"), "utf8");
const PoolCore = new Function(coreSrc + "\nreturn PoolCore;")();

const DEFAULT_SENSORS = { water_a: 22.0, water_b: 22.0, mat_a: 24.0, mat_b: 24.0, air: 15.0 };

let failures = 0;
let count = 0;

function check(name, idx, key, actual, expected) {
  let ok;
  if (typeof expected === "number" || typeof actual === "number") {
    ok = actual !== null && actual !== undefined
      && Math.abs(Number(actual) - Number(expected)) < 1e-9;
    if (typeof expected === "boolean" || typeof actual === "boolean") {
      ok = actual === expected;
    }
  } else {
    ok = JSON.stringify(actual) === JSON.stringify(expected);
  }
  if (!ok) {
    failures++;
    console.error(`FAIL [${name}] step ${idx}: ${key} expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

function runVector(name, vec) {
  const config = Object.assign({}, vec.config || {});
  let state = PoolCore.initialState();
  if (vec.initial_state) {
    for (const k in vec.initial_state) {
      state[k] = JSON.parse(JSON.stringify(vec.initial_state[k]));
    }
  }
  const tick = PoolCore.cfg(config, "tick_s");
  let now = vec.start_now !== undefined ? vec.start_now : 1000000000;
  const baseLocal = vec.start_local_min !== undefined ? vec.start_local_min : 720;
  const baseDay = vec.start_day !== undefined ? vec.start_day : 20260715;
  let timeValid = vec.time_valid !== undefined ? vec.time_valid : true;
  let uptime = vec.uptime !== undefined ? vec.uptime
    : PoolCore.cfg(config, "boot_settle_s") + 3600;
  let elapsed = 0;
  const sensors = Object.assign({}, DEFAULT_SENSORS);
  let explicitPower = null;

  vec.steps.forEach((st, idx) => {
    const dt = st.dt !== undefined ? st.dt : tick;
    now += dt;
    elapsed += dt;
    uptime += dt;
    const inp = st.in || {};
    if (inp.sensors) {
      for (const k in inp.sensors) sensors[k] = inp.sensors[k];
    }
    if (inp.time_valid !== undefined) timeValid = inp.time_valid;
    if (inp.uptime !== undefined) uptime = inp.uptime;
    if (inp.power_w !== undefined) explicitPower = inp.power_w;
    const totalMin = baseLocal + Math.floor(elapsed / 60);
    const localMin = totalMin % 1440;
    const localDay = baseDay + Math.floor(totalMin / 1440);
    let power;
    if (explicitPower !== null) {
      power = explicitPower;
    } else {
      const nominal = state.pump_nominal
        || PoolCore.cfg(config, "pump_power_nominal") || 800.0;
      power = state.relay ? nominal : 0.0;
    }
    const inputs = {
      now, dt, uptime,
      time_valid: timeValid,
      local_min: localMin, local_day: localDay,
      sensors: Object.assign({}, sensors),
      power_w: power,
      relay_actual: state.relay,
      commands: st.cmd || [],
    };
    const res = PoolCore.step(inputs, config, state);
    state = res.state;

    const exp = st.expect || {};
    if ("relay" in exp) check(name, idx, "relay", res.relay, exp.relay);
    if ("reason" in exp) check(name, idx, "reason", res.reason, exp.reason);
    if ("mode" in exp) check(name, idx, "mode", state.mode, exp.mode);
    if ("faults" in exp) {
      check(name, idx, "faults", res.faults, [...exp.faults].sort());
    }
    if ("faults_has" in exp) {
      for (const f of exp.faults_has) {
        if (!res.faults.includes(f)) {
          failures++;
          console.error(`FAIL [${name}] step ${idx}: fault ${f} not active (active: ${JSON.stringify(res.faults)})`);
        }
      }
    }
    if ("warnings_has" in exp) {
      for (const w of exp.warnings_has) {
        if (!res.warnings.includes(w)) {
          failures++;
          console.error(`FAIL [${name}] step ${idx}: warning ${w} missing (got: ${JSON.stringify(res.warnings)})`);
        }
      }
    }
    if ("effective" in exp) {
      for (const k in exp.effective) {
        check(name, idx, "effective." + k, res.effective[k], exp.effective[k]);
      }
    }
    if ("state" in exp) {
      for (const k in exp.state) {
        check(name, idx, "state." + k, state[k], exp.state[k]);
      }
    }
  });
}

for (const file of readdirSync(vectorDir).sort()) {
  if (!file.endsWith(".json")) continue;
  const data = JSON.parse(readFileSync(join(vectorDir, file), "utf8"));
  for (const vec of data.vectors) {
    count++;
    runVector(`${file}:${vec.name}`, vec);
  }
}

if (count === 0) {
  console.error("no test vectors found");
  process.exit(1);
}
if (failures > 0) {
  console.error(`${failures} failure(s) across ${count} vectors`);
  process.exit(1);
}
console.log(`OK — ${count} vectors passed against the mJS core`);
