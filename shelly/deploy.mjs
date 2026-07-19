// Upload the built scripts to a Shelly Gen2+ device via HTTP RPC.
// Handles the device's digest authentication (RFC 7616, SHA-256).
//
// Usage:
//   node shelly/build.mjs && node shelly/deploy.mjs --host 192.168.1.50 [--password ...]
// Options:
//   --host <ip|hostname>      required
//   --password <admin pw>     if device auth is enabled (user is always "admin")
//   --no-start                upload only, don't (re)start the scripts

import { readFileSync } from "node:fs";
import { createHash, randomBytes } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
function arg(name, fallback = null) {
  const i = args.indexOf("--" + name);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
}
const host = arg("host");
const password = arg("password");
const noStart = args.includes("--no-start");
if (!host) {
  console.error("usage: node shelly/deploy.mjs --host <ip> [--password <pw>] [--no-start]");
  process.exit(2);
}

const sha256 = (s) => createHash("sha256").update(s).digest("hex");
let digestState = null;

function digestHeader(method, uri) {
  if (!digestState) return null;
  const { realm, nonce } = digestState;
  const cnonce = randomBytes(8).toString("hex");
  digestState.nc += 1;
  const nc = digestState.nc.toString(16).padStart(8, "0");
  const ha1 = sha256(`admin:${realm}:${password}`);
  const ha2 = sha256(`${method}:${uri}`);
  const resp = sha256(`${ha1}:${nonce}:${nc}:${cnonce}:auth:${ha2}`);
  return `Digest username="admin", realm="${realm}", nonce="${nonce}", uri="${uri}", `
    + `qop=auth, nc=${nc}, cnonce="${cnonce}", response="${resp}", algorithm=SHA-256`;
}

async function rpc(method, params = {}) {
  const uri = "/rpc/" + method;
  const url = `http://${host}${uri}`;
  const body = JSON.stringify(params);
  const doFetch = () => {
    const headers = { "Content-Type": "application/json" };
    const auth = digestHeader("POST", uri);
    if (auth) headers.Authorization = auth;
    return fetch(url, { method: "POST", headers, body });
  };
  let res = await doFetch();
  if (res.status === 401) {
    if (!password) throw new Error("device requires authentication — pass --password");
    const www = res.headers.get("www-authenticate") || "";
    const get = (k) => (www.match(new RegExp(`${k}="?([^",]+)"?`)) || [])[1];
    digestState = { realm: get("realm"), nonce: get("nonce"), nc: 0 };
    res = await doFetch();
  }
  if (!res.ok) throw new Error(`${method} → HTTP ${res.status}: ${await res.text()}`);
  return res.json();
}

async function ensureScript(name) {
  const list = await rpc("Script.List");
  const found = (list.scripts || []).find((s) => s.name === name);
  if (found) return found.id;
  const created = await rpc("Script.Create", { name });
  return created.id;
}

async function putCode(id, code) {
  const CHUNK = 1024;
  for (let i = 0; i < code.length; i += CHUNK) {
    await rpc("Script.PutCode", {
      id,
      code: code.slice(i, i + CHUNK),
      append: i > 0,
    });
  }
}

async function deploy(name, file) {
  const code = readFileSync(join(here, "build", file), "utf8");
  const id = await ensureScript(name);
  console.log(`${name}: script id ${id}, uploading ${code.length} bytes…`);
  await rpc("Script.Stop", { id }).catch(() => {});
  await putCode(id, code);
  await rpc("Script.SetConfig", { id, config: { enable: true } });
  if (!noStart) {
    await rpc("Script.Start", { id });
    console.log(`${name}: started`);
  }
  return id;
}

const info = await rpc("Shelly.GetDeviceInfo");
console.log(`device: ${info.model || "?"} ${info.id || ""} fw ${info.ver || "?"}`);
await deploy("pool-control", "pool-control.js");
await deploy("pool-watchdog", "pool-watchdog.js");
console.log("done. Verify in the device UI that both scripts are enabled (autostart).");
