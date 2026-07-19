// Build the deployable Shelly scripts:
//   build/pool-control.js  = core.js + device.js, comments stripped, version stamped
//   build/pool-watchdog.js = watchdog.js
// Enforces a per-script size budget (Shelly Gen2+ script slots are limited).
// Usage: node shelly/build.mjs [--version 2026.07.19.1]

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
let version = "dev";
const vi = args.indexOf("--version");
if (vi >= 0 && args[vi + 1]) version = args[vi + 1];

// Conservative minify: strip comments and trailing whitespace, drop blank
// lines. No renaming — the result stays reviewable on the device.
function strip(src) {
  let out = [];
  let inBlock = false;
  for (let line of src.split("\n")) {
    if (inBlock) {
      const end = line.indexOf("*/");
      if (end < 0) continue;
      line = line.slice(end + 2);
      inBlock = false;
    }
    // remove // comments (naive but safe here: sources avoid "//" in strings)
    const idx = line.indexOf("//");
    if (idx >= 0 && !line.slice(0, idx).includes('"//"')) line = line.slice(0, idx);
    const bs = line.indexOf("/*");
    if (bs >= 0) {
      const be = line.indexOf("*/", bs + 2);
      if (be >= 0) line = line.slice(0, bs) + line.slice(be + 2);
      else { line = line.slice(0, bs); inBlock = true; }
    }
    line = line.trim();
    if (line === "") continue;
    out.push(line);
  }
  return out.join("\n");
}

const MAX_BYTES = Number(process.env.SHELLY_SCRIPT_MAX_BYTES || 30720);

const core = readFileSync(join(here, "src", "core.js"), "utf8");
const device = readFileSync(join(here, "src", "device.js"), "utf8");
const watchdog = readFileSync(join(here, "src", "watchdog.js"), "utf8");

const banner = `// pool-control ${version} — https://github.com/steiner-dominik/shelly-pool-control (MIT)\n`;
const control = banner + strip(core + "\n" + device).replaceAll("__VERSION__", version);
const wd = `// pool-watchdog ${version} — https://github.com/steiner-dominik/shelly-pool-control (MIT)\n`
  + strip(watchdog).replaceAll("__VERSION__", version);

mkdirSync(join(here, "build"), { recursive: true });
writeFileSync(join(here, "build", "pool-control.js"), control);
writeFileSync(join(here, "build", "pool-watchdog.js"), wd);

let failed = false;
for (const [name, body] of [["pool-control.js", control], ["pool-watchdog.js", wd]]) {
  const size = Buffer.byteLength(body, "utf8");
  const pct = ((size / MAX_BYTES) * 100).toFixed(1);
  console.log(`${name}: ${size} bytes (${pct}% of ${MAX_BYTES} budget)`);
  if (size > MAX_BYTES) {
    console.error(`ERROR: ${name} exceeds the script size budget`);
    failed = true;
  }
}
if (failed) process.exit(1);
console.log(`built version ${version} → shelly/build/`);
