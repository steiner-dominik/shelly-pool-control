<script>
  import { onMount } from "svelte";
  import { api } from "../lib/api.js";
  import { auth, roleAtLeast } from "../lib/store.js";
  import { t } from "../lib/i18n.js";
  import { fmt } from "../lib/format.js";
  import Icon from "../components/Icon.svelte";

  let tab = $state("events");
  let rows = $state([]);
  let loading = $state(true);
  let kindFilter = $state("");
  let isAdmin = $derived(roleAtLeast($auth.role, "admin"));

  onMount(load);
  async function load() {
    loading = true;
    try {
      if (tab === "events") {
        rows = await api.get("/api/events?limit=300"
          + (kindFilter ? "&kinds=" + kindFilter : ""));
      } else {
        rows = await api.get("/api/audit?limit=300");
      }
    } catch { rows = []; }
    loading = false;
  }

  function pick(name) { tab = name; load(); }

  function describe(ev) {
    const d = ev.data || {};
    switch (ev.kind) {
      case "fault":
        return ($t("faults." + d.cls) || d.cls) + " — "
          + (d.active ? "⚠" : "✓");
      case "mode": return `${d.from} → ${d.to}`;
      case "decision": {
        const key = "reasons." + d.reason;
        const label = $t(key) === key ? d.reason : $t(key);
        return (d.relay ? "▶ " : "■ ") + label;
      }
      case "config":
        return Object.entries(d.changes || {})
          .map(([k, v]) => `${k}: ${JSON.stringify(v.old)} → ${JSON.stringify(v.new)}`)
          .join(", ");
      default: return JSON.stringify(d);
    }
  }

  function exportCsv() {
    const head = tab === "events" ? "ts,kind,data" : "ts,user,action,detail";
    const lines = rows.map((r) => tab === "events"
      ? `${new Date(r.ts * 1000).toISOString()},${r.kind},"${JSON.stringify(r.data).replaceAll('"', '""')}"`
      : `${new Date(r.ts * 1000).toISOString()},${r.user},${r.action},"${String(r.detail).replaceAll('"', '""')}"`);
    const blob = new Blob([head + "\n" + lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `pool-${tab}-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }
</script>

<h1>{$t("log.title")}</h1>

<div class="spread" style="margin-bottom:14px">
  <div class="seg" style="max-width:280px">
    <button class:active={tab === "events"} onclick={() => pick("events")}>
      {$t("log.events")}</button>
    {#if isAdmin}
      <button class:active={tab === "audit"} onclick={() => pick("audit")}>
        {$t("log.audit")}</button>
    {/if}
  </div>
  <div class="row">
    {#if tab === "events"}
      <select style="width:auto" bind:value={kindFilter} onchange={load}>
        <option value="">— {$t("log.kind")} —</option>
        {#each ["fault", "mode", "decision", "config", "backup", "restore", "device_offline", "device_online"] as k}
          <option value={k}>{$t("log.kinds." + k)}</option>
        {/each}
      </select>
    {/if}
    <button onclick={exportCsv}><Icon name="download" size={16} /> {$t("log.export")}</button>
  </div>
</div>

<div class="card">
  {#if loading}
    <span class="spin"></span>
  {:else}
    <table>
      <thead><tr><th>{$t("log.when")}</th><th>{$t("log.kind")}</th>
        <th>{$t("log.what")}</th></tr></thead>
      <tbody>
        {#each rows as r}
          <tr>
            <td class="muted mono" style="white-space:nowrap">{$fmt.full(r.ts)}</td>
            {#if tab === "events"}
              <td><span class="badge {r.kind === 'fault' ? (r.data?.active ? 'bad' : 'good') : 'info'}">
                {$t("log.kinds." + r.kind) || r.kind}</span></td>
              <td style="word-break:break-word">{describe(r)}</td>
            {:else}
              <td><span class="badge info">{r.user}</span></td>
              <td style="word-break:break-word">{r.action}
                <span class="muted">{r.detail}</span></td>
            {/if}
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</div>
