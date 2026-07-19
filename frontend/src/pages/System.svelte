<script>
  import { onMount } from "svelte";
  import { api } from "../lib/api.js";
  import { auth, snapshot, refreshAuth, roleAtLeast, disconnectLive } from "../lib/store.js";
  import { t, locale, LOCALE_NAMES } from "../lib/i18n.js";
  import { theme } from "../lib/theme.js";
  import { timezone, fmt } from "../lib/format.js";
  import { showToast } from "../lib/toast.js";
  import { APP_VERSION } from "../lib/version.js";
  import Icon from "../components/Icon.svelte";
  import Confirm from "../components/Confirm.svelte";

  let sys = $state(null);
  let isAdmin = $derived(roleAtLeast($auth.role, "admin"));

  // users
  let users = $state([]);
  let newUser = $state({ username: "", password: "", role: "viewer" });

  // backups
  let backups = $state([]);
  let schedule = $state({ enabled: false, time: "03:30", keep: 14 });
  let restoreFile = $state(null);
  let restoreHistory = $state(false);
  let restoreOpen = $state(false);

  // notifications
  let channels = $state(null);

  // account
  let pw = $state({ old: "", new: "" });
  let totpInfo = $state(null);
  let totpCode = $state("");

  // sim
  const slots = ["water_a", "water_b", "mat_a", "mat_b", "air"];
  let simPower = $state("");

  let busy = $state("");

  const tzs = (Intl.supportedValuesOf ? Intl.supportedValuesOf("timeZone") : [
    "Europe/Vienna", "Europe/Berlin", "UTC"]);

  onMount(load);
  async function load() {
    try { sys = await api.get("/api/system"); } catch { sys = null; }
    if (isAdmin) {
      try { users = await api.get("/api/users"); } catch { users = []; }
      try { backups = await api.get("/api/backup/list"); } catch { backups = []; }
      try { schedule = await api.get("/api/backup/schedule"); } catch { /* keep */ }
      try { channels = await api.get("/api/settings/notify"); } catch { channels = null; }
    }
  }

  async function act(name, fn) {
    busy = name;
    try { await fn(); } catch (e) {
      showToast($t("common.error") + (e.code ? ": " + e.code : ""));
    }
    busy = "";
  }

  const addUser = () => act("adduser", async () => {
    await api.post("/api/users", newUser);
    newUser = { username: "", password: "", role: "viewer" };
    users = await api.get("/api/users");
    showToast($t("common.saved"));
  });

  const delUser = (u) => act("del" + u.id, async () => {
    await api.del("/api/users/" + u.id);
    users = await api.get("/api/users");
  });

  const backupNow = () => act("backup", async () => {
    await api.post("/api/backup/create");
    backups = await api.get("/api/backup/list");
    showToast($t("common.saved"));
  });

  const saveSchedule = () => act("sched", async () => {
    await api.put("/api/backup/schedule", schedule);
    showToast($t("common.saved"));
  });

  const delBackup = (name) => act("delb" + name, async () => {
    await api.del("/api/backup/" + name);
    backups = await api.get("/api/backup/list");
  });

  async function doRestore() {
    if (!restoreFile) return;
    await act("restore", async () => {
      const fd = new FormData();
      fd.append("file", restoreFile);
      const res = await api.post("/api/backup/restore?restore_history=" + restoreHistory, fd);
      showToast($t("system.restore_done", { params: res.params, users: res.users }));
      load();
    });
  }

  const saveNotify = () => act("notify", async () => {
    await api.put("/api/settings/notify", { channels });
    showToast($t("common.saved"));
  });

  const testNotify = (ch) => act("test" + ch, async () => {
    const res = await api.post("/api/settings/notify/test/" + ch);
    showToast(res.ok ? "✓ " + $t("common.ok") : "✗ " + (res.error || $t("err.generic")));
  });

  const changePw = () => act("pw", async () => {
    await api.post("/api/auth/password", pw);
    pw = { old: "", new: "" };
    showToast($t("common.saved"));
  });

  const totpSetup = () => act("totp", async () => {
    totpInfo = await api.post("/api/auth/totp/setup");
  });

  const totpEnable = () => act("totpe", async () => {
    await api.post("/api/auth/totp/enable", { code: totpCode });
    totpInfo = null; totpCode = "";
    showToast($t("common.saved"));
  });

  const totpDisable = () => act("totpd", async () => {
    await api.post("/api/auth/totp/disable");
    showToast($t("common.saved"));
  });

  const killProbe = (slot) => act("kill" + slot, () =>
    api.post("/api/sim/sensor", { slot, dead: true }));
  const restoreProbe = (slot) => act("res" + slot, () =>
    api.post("/api/sim/sensor", { slot }));
  const setSimPower = () => act("simp", () =>
    api.post("/api/sim/power", { value: simPower === "" ? null : Number(simPower) }));
  const simReset = () => act("simr", () => api.post("/api/sim/reset"));

  async function logout() {
    try { await api.post("/api/auth/logout"); } catch { /* ignore */ }
    disconnectLive();
    await refreshAuth();
  }

  function fmtBytes(n) {
    return n > 1048576 ? (n / 1048576).toFixed(1) + " MB"
      : Math.round(n / 1024) + " kB";
  }
</script>

<h1>{$t("system.title")}</h1>

<div class="card">
  <h2><Icon name="globe" size={18} /> {$t("system.appearance")}</h2>
  <div class="grid cols-2">
    <div>
      <label for="th">{$t("system.theme")}</label>
      <select id="th" bind:value={$theme}>
        <option value="auto">{$t("system.theme_auto")}</option>
        <option value="light">{$t("system.theme_light")}</option>
        <option value="dark">{$t("system.theme_dark")}</option>
      </select>
    </div>
    <div>
      <label for="lg">{$t("system.language")}</label>
      <select id="lg" bind:value={$locale}>
        <option value="auto">{$t("system.lang_auto")}</option>
        {#each Object.entries(LOCALE_NAMES) as [code, name]}
          <option value={code}>{name}</option>
        {/each}
      </select>
    </div>
    <div style="grid-column: 1 / -1;">
      <label for="tz">{$t("system.timezone")}</label>
      <select id="tz" bind:value={$timezone}>
        <option value="auto">{$t("system.tz_auto")}</option>
        {#each tzs as z}<option value={z}>{z}</option>{/each}
      </select>
    </div>
  </div>
</div>

<div class="card">
  <div class="spread">
    <h2><Icon name="system" size={18} /> {$t("system.device")}</h2>
    <span class="badge {$snapshot?.online ? 'good' : 'bad'}">
      {$snapshot?.online ? $t("system.online") : $t("system.offline")}
    </span>
  </div>
  <table>
    <tbody>
      <tr><td class="muted">{$t("system.model")}</td>
        <td class="mono">{sys?.device?.model || "–"} {sys?.shelly_host ? `(${sys.shelly_host})` : ""}</td></tr>
      <tr><td class="muted">{$t("system.firmware")}</td>
        <td class="mono">{sys?.device?.ver || "–"}</td></tr>
      <tr><td class="muted">{$t("system.script")}</td>
        <td class="mono">{$snapshot?.status?.script_version || "–"}</td></tr>
      <tr><td class="muted">{$t("system.server")} {$t("system.version")}</td>
        <td class="mono">{sys?.version || APP_VERSION}</td></tr>
      <tr><td class="muted">{$t("system.influx")}</td>
        <td>{sys?.influx?.enabled ? "✓" : "–"}
          {#if sys?.influx?.last_error}<span class="badge bad">{sys.influx.last_error}</span>{/if}</td></tr>
      <tr><td class="muted">{$t("system.mqtt")}</td>
        <td>{sys?.mqtt?.enabled ? "✓" : "–"}</td></tr>
    </tbody>
  </table>
</div>

{#if isAdmin}
  <div class="card">
    <h2><Icon name="download" size={18} /> {$t("system.backups")}</h2>
    <div class="row" style="margin-bottom:10px">
      <button class="primary" disabled={busy !== ""} onclick={backupNow}>
        {#if busy === "backup"}<span class="spin"></span>{:else}{$t("system.backup_now")}{/if}
      </button>
    </div>
    {#if backups.length}
      <table>
        <tbody>
          {#each backups as b}
            <tr>
              <td class="mono" style="word-break:break-all">{b.name}</td>
              <td class="muted mono">{fmtBytes(b.size)}</td>
              <td style="text-align:right; white-space:nowrap">
                <a class="btn" href={"/api/backup/download/" + b.name} download>
                  <Icon name="download" size={15} /></a>
                <button onclick={() => delBackup(b.name)}><Icon name="x" size={15} /></button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}

    <h3 style="margin-top:16px; font-size:.95rem">{$t("system.backup_schedule")}</h3>
    <div class="row">
      <select style="width:auto" bind:value={schedule.enabled}>
        <option value={true}>{$t("common.enabled")}</option>
        <option value={false}>{$t("common.disabled")}</option>
      </select>
      <input type="time" style="width:auto" bind:value={schedule.time} />
      <label style="margin:0" for="bk">{$t("system.backup_keep")}</label>
      <input id="bk" type="number" style="width:80px" min="1" max="365" bind:value={schedule.keep} />
      <button disabled={busy !== ""} onclick={saveSchedule}>{$t("common.save")}</button>
    </div>

    <h3 style="margin-top:16px; font-size:.95rem">{$t("system.restore")}</h3>
    <div class="row">
      <input type="file" accept=".zip" style="width:auto"
        onchange={(e) => (restoreFile = e.target.files[0])} />
      <label style="margin:0; display:flex; align-items:center; gap:6px">
        <input type="checkbox" style="width:auto" bind:checked={restoreHistory} />
        {$t("system.restore_history")}
      </label>
      <button class="danger" disabled={!restoreFile || busy !== ""}
        onclick={() => (restoreOpen = true)}>
        {#if busy === "restore"}<span class="spin"></span>{:else}{$t("system.restore")}{/if}
      </button>
    </div>
  </div>

  <div class="card">
    <h2><Icon name="user" size={18} /> {$t("system.users")}</h2>
    <table>
      <thead><tr><th>{$t("system.user_name")}</th><th>{$t("system.user_role")}</th>
        <th>{$t("system.user_2fa")}</th><th></th></tr></thead>
      <tbody>
        {#each users as u}
          <tr>
            <td>{u.username}</td>
            <td><span class="badge info">{$t("system.roles." + u.role)}</span></td>
            <td>{u.totp ? "✓" : "–"}</td>
            <td style="text-align:right">
              {#if u.username !== $auth.user}
                <button onclick={() => delUser(u)}><Icon name="x" size={15} /></button>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    <h3 style="margin-top:14px; font-size:.95rem">{$t("system.new_user")}</h3>
    <div class="row">
      <input style="width:auto" placeholder={$t("system.user_name")}
        bind:value={newUser.username} autocomplete="off" />
      <input style="width:auto" type="password" placeholder={$t("system.user_password")}
        bind:value={newUser.password} autocomplete="new-password" />
      <select style="width:auto" bind:value={newUser.role}>
        {#each ["viewer", "operator", "admin"] as r}
          <option value={r}>{$t("system.roles." + r)}</option>
        {/each}
      </select>
      <button disabled={!newUser.username || !newUser.password || busy !== ""}
        onclick={addUser}>{$t("common.add")}</button>
    </div>
  </div>

  {#if channels}
    <div class="card">
      <h2><Icon name="log" size={18} /> {$t("system.notifications")}</h2>
      {#each [["smtp", "system.notify_smtp"], ["telegram", "system.notify_telegram"], ["webhook", "system.notify_webhook"]] as [ch, label]}
        <div style="border-top:1px solid var(--line); padding:12px 0">
          <div class="spread">
            <strong>{$t(label)}</strong>
            <div class="row">
              <select style="width:auto" bind:value={channels[ch].enabled}>
                <option value={true}>{$t("common.enabled")}</option>
                <option value={false}>{$t("common.disabled")}</option>
              </select>
              <select style="width:auto" bind:value={channels[ch].min_severity}>
                {#each ["info", "warning", "critical"] as s}
                  <option value={s}>{$t("system.severity." + s)}</option>
                {/each}
              </select>
              <button disabled={busy !== ""} onclick={() => testNotify(ch)}>
                {$t("common.test")}</button>
            </div>
          </div>
          {#if channels[ch].enabled}
            <div class="grid cols-2" style="margin-top:8px">
              {#if ch === "smtp"}
                <input placeholder="host" bind:value={channels.smtp.host} />
                <input placeholder="port" type="number" bind:value={channels.smtp.port} />
                <input placeholder="user" bind:value={channels.smtp.user} />
                <input placeholder="password" type="password" bind:value={channels.smtp.password} />
                <input placeholder="from@example.com" bind:value={channels.smtp.from} />
                <input placeholder="to@example.com" bind:value={channels.smtp.to} />
              {:else if ch === "telegram"}
                <input placeholder="bot token" bind:value={channels.telegram.bot_token} />
                <input placeholder="chat id" bind:value={channels.telegram.chat_id} />
              {:else}
                <input placeholder="https://…" bind:value={channels.webhook.url}
                  style="grid-column: 1 / -1" />
              {/if}
            </div>
          {/if}
        </div>
      {/each}
      <div class="spread" style="padding-top:10px">
        <strong>{$t("system.quiet")}</strong>
        <div class="row">
          <select style="width:auto" bind:value={channels.quiet_hours.enabled}>
            <option value={true}>{$t("common.enabled")}</option>
            <option value={false}>{$t("common.disabled")}</option>
          </select>
          <input type="time" style="width:auto" bind:value={channels.quiet_hours.start} />
          <input type="time" style="width:auto" bind:value={channels.quiet_hours.end} />
        </div>
      </div>
      <div style="text-align:right; margin-top:12px">
        <button class="primary" disabled={busy !== ""} onclick={saveNotify}>
          {$t("common.save")}</button>
      </div>
    </div>
  {/if}

  {#if sys?.simulate}
    <div class="card">
      <h2>🧪 {$t("system.sim")}</h2>
      <div class="row">
        {#each slots as slot}
          <div class="row" style="gap:4px">
            <span class="badge info">{$t("sensors.roles." + slot)}</span>
            <button onclick={() => killProbe(slot)} title={$t("system.sim_kill")}>✕</button>
            <button onclick={() => restoreProbe(slot)} title={$t("system.sim_restore")}>↺</button>
          </div>
        {/each}
      </div>
      <div class="row" style="margin-top:10px">
        <input type="number" style="width:120px" placeholder="W"
          bind:value={simPower} />
        <button onclick={setSimPower}>{$t("system.sim_power")}</button>
        <button onclick={simReset}>{$t("system.sim_reset")}</button>
      </div>
    </div>
  {/if}
{/if}

{#if !$auth.via_ingress}
  <div class="card">
    <h2><Icon name="shield" size={18} /> {$t("system.account")} — {$auth.user}</h2>
    <div class="grid cols-2">
      <div>
        <label for="op">{$t("system.old_password")}</label>
        <input id="op" type="password" bind:value={pw.old} autocomplete="current-password" />
      </div>
      <div>
        <label for="np">{$t("system.new_password")}</label>
        <input id="np" type="password" bind:value={pw.new} autocomplete="new-password" />
      </div>
    </div>
    <div class="row" style="margin-top:10px; justify-content:space-between">
      <button disabled={!pw.old || !pw.new || busy !== ""} onclick={changePw}>
        {$t("system.change_password")}</button>
      <div class="row">
        {#if totpInfo}
          <span class="mono" style="user-select:all">{totpInfo.secret}</span>
        {/if}
        {#if !totpInfo}
          <button onclick={totpSetup}>{$t("system.totp_setup")}</button>
          <button onclick={totpDisable}>{$t("system.totp_disable")}</button>
        {/if}
      </div>
    </div>
    {#if totpInfo}
      <p class="muted">{$t("system.totp_scan")}</p>
      <div class="row">
        <input style="width:140px" inputmode="numeric" bind:value={totpCode} placeholder="123456" />
        <button class="primary" disabled={!totpCode} onclick={totpEnable}>
          {$t("common.confirm")}</button>
      </div>
    {/if}
    <div style="margin-top:16px; text-align:right">
      <button onclick={logout}>⎋ {$t("nav.logout")}</button>
    </div>
  </div>
{/if}

<Confirm bind:open={restoreOpen} danger
  title={$t("system.restore")}
  message={$t("system.restore_confirm")}
  onconfirm={doRestore} />
