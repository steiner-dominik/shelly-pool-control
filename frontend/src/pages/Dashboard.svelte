<script>
  import { onMount } from "svelte";
  import { snapshot, auth, roleAtLeast } from "../lib/store.js";
  import { api } from "../lib/api.js";
  import { t } from "../lib/i18n.js";
  import { fmt } from "../lib/format.js";
  import { showToast } from "../lib/toast.js";
  import Icon from "../components/Icon.svelte";

  let decisions = $state([]);
  let showProbes = $state(false);
  let busyMode = $state("");

  let st = $derived($snapshot?.status || null);
  let last = $derived(st?.last || null);
  let eff = $derived(last?.effective || {});
  let faults = $derived(last?.faults || []);
  let warnings = $derived(last?.warnings || []);

  onMount(loadDecisions);
  async function loadDecisions() {
    try {
      decisions = await api.get("/api/events?kinds=decision,mode,fault&limit=12");
    } catch { /* ignore */ }
  }

  const modes = ["auto", "off", "force_on", "boost", "winter"];
  async function setMode(mode) {
    if (!roleAtLeast($auth.role, "operator")) return;
    busyMode = mode;
    try {
      await api.post("/api/control/mode", { mode });
      showToast($t("control.sent"));
      loadDecisions();
    } catch (e) {
      showToast($t("err." + e.code) !== "err." + e.code
        ? $t("err." + e.code) : $t("err.generic"));
    } finally {
      busyMode = "";
    }
  }

  function reasonText(r) {
    if (!r) return "–";
    const key = "reasons." + r;
    const out = $t(key);
    return out === key ? r : out;
  }
</script>

<h1>{$t("nav.dashboard")}</h1>

{#if !st}
  <div class="card"><span class="spin"></span> {$t("common.loading")}</div>
{:else}
  {#if faults.length}
    <div class="banner bad">
      <strong>{$t("dashboard.faults_active")}:</strong>
      {faults.map((f) => $t("faults." + f)).join(" · ")}
    </div>
  {/if}
  {#each warnings.filter((w) => w !== "time_invalid" || !st.relay) as w}
    {#if $t("warnings." + w) !== "warnings." + w}
      <div class="banner warn">{$t("warnings." + w)}</div>
    {/if}
  {/each}

  <div class="grid cols-4">
    <button class="card tile" onclick={() => (showProbes = !showProbes)}
      style="text-align:left; cursor:pointer;">
      <div class="tile-label"><Icon name="wave" size={15} /> {$t("dashboard.water")}</div>
      <div class="big-value mono">{$fmt.temp(eff.water)}</div>
      {#if showProbes && last?.sensors}
        <div class="muted mono">A {$fmt.temp(last.sensors.water_a)} · B {$fmt.temp(last.sensors.water_b)}</div>
      {/if}
    </button>
    <button class="card tile" onclick={() => (showProbes = !showProbes)}
      style="text-align:left; cursor:pointer;">
      <div class="tile-label"><Icon name="sun" size={15} /> {$t("dashboard.mat")}</div>
      <div class="big-value mono">{$fmt.temp(eff.mat)}</div>
      {#if showProbes && last?.sensors}
        <div class="muted mono">A {$fmt.temp(last.sensors.mat_a)} · B {$fmt.temp(last.sensors.mat_b)}</div>
      {/if}
    </button>
    <div class="card tile">
      <div class="tile-label"><Icon name="bolt" size={15} /> {$t("dashboard.delta")}</div>
      <div class="big-value mono" style="color:{(eff.delta ?? 0) >= 0 ? 'var(--good)' : 'var(--muted)'}">
        {$fmt.delta(eff.delta)}
      </div>
    </div>
    <div class="card tile">
      <div class="tile-label"><Icon name="clock" size={15} /> {$t("dashboard.air")}</div>
      <div class="big-value mono">{$fmt.temp(eff.air)}</div>
    </div>
  </div>

  <div class="grid cols-2">
    <div class="card">
      <div class="spread">
        <h2><Icon name="pump" size={18} /> {$t("dashboard.pump")}</h2>
        <span class="badge {st.relay ? 'good' : 'info'}">
          {st.relay ? $t("common.on") : $t("common.off")}
        </span>
      </div>
      <div class="big-value mono">{$fmt.watts(last?.power_w)}</div>
      <p class="muted" style="margin:6px 0 0">{reasonText(last?.reason)}</p>
      <table style="margin-top:10px">
        <tbody>
          <tr><td class="muted">{$t("dashboard.runtime_today")}</td>
              <td class="mono" style="text-align:right">{$fmt.hours(st.run_s_today)}</td></tr>
          <tr><td class="muted">{$t("dashboard.heating_today")}</td>
              <td class="mono" style="text-align:right">{$fmt.hours(st.heat_s_today)}</td></tr>
        </tbody>
      </table>
    </div>

    <div class="card">
      <h2><Icon name="control" size={18} /> {$t("dashboard.mode")}</h2>
      <div class="seg" role="group">
        {#each modes as m}
          <button class:active={st.mode === m}
            disabled={!roleAtLeast($auth.role, "operator") || busyMode !== ""}
            onclick={() => setMode(m)}>
            {#if busyMode === m}<span class="spin"></span>{:else}{$t("modes." + m)}{/if}
          </button>
        {/each}
      </div>
      <p class="muted" style="margin-top:10px">{$t("mode_hint." + st.mode)}</p>
      {#if st.mode_until > 0}
        <p class="badge info">{$t("dashboard.until", { time: $fmt.time(st.mode_until) })}</p>
      {/if}
    </div>
  </div>

  <div class="card">
    <h2><Icon name="log" size={18} /> {$t("dashboard.decisions")}</h2>
    {#if decisions.length === 0}
      <p class="muted">{$t("dashboard.no_decisions")}</p>
    {:else}
      <table>
        <tbody>
          {#each decisions as ev}
            <tr>
              <td class="muted mono" style="white-space:nowrap">{$fmt.dt(ev.ts)}</td>
              <td>
                {#if ev.kind === "decision"}
                  <span class="badge {ev.data.relay ? 'good' : 'info'}">
                    {ev.data.relay ? "▶" : "■"}</span>
                  {reasonText(ev.data.reason)}
                {:else if ev.kind === "mode"}
                  <span class="badge info">{$t("log.kinds.mode")}</span>
                  {$t("modes." + ev.data.from) || ev.data.from} → {$t("modes." + ev.data.to) || ev.data.to}
                {:else if ev.kind === "fault"}
                  <span class="badge {ev.data.active ? 'bad' : 'good'}">
                    {$t("log.kinds.fault")}</span>
                  {$t("faults." + ev.data.cls)}
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>

  <p class="muted" style="text-align:center">
    {$t("dashboard.last_update", { time: $snapshot.updated ? $fmt.time($snapshot.updated) : "–" })}
  </p>
{/if}

<style>
  .tile { border: 1px solid var(--line); }
</style>
