<script>
  import { onMount } from "svelte";
  import { api } from "../lib/api.js";
  import { t } from "../lib/i18n.js";
  import { fmt } from "../lib/format.js";
  import Chart from "../components/Chart.svelte";
  import Icon from "../components/Icon.svelte";

  let range = $state("day");
  let points = $state([]);
  let loading = $state(true);
  const ranges = ["day", "week", "month", "season", "all"];

  onMount(load);
  async function load() {
    loading = true;
    try {
      const res = await api.get("/api/history?range=" + range);
      points = res.points;
    } catch { points = []; }
    loading = false;
  }

  function pick(r) { range = r; load(); }

  let runToday = $derived(points.length
    ? Math.max(...points.map((p) => p.run_s || 0)) : 0);
</script>

<h1>{$t("history.title")}</h1>

<div class="seg" style="margin-bottom:14px; max-width:480px">
  {#each ranges as r}
    <button class:active={range === r} onclick={() => pick(r)}>{$t("history." + r)}</button>
  {/each}
</div>

{#if loading}
  <div class="card"><span class="spin"></span> {$t("common.loading")}</div>
{:else if points.length === 0}
  <div class="card"><p class="muted">{$t("history.no_data")}</p></div>
{:else}
  <div class="card">
    <h2><Icon name="wave" size={18} /> {$t("history.temps")}</h2>
    <Chart {points} relayKey="relay" unit="°C"
      series={[
        { key: "water", label: $t("dashboard.water"), color: "--accent" },
        { key: "mat", label: $t("dashboard.mat"), color: "#f59e0b" },
        { key: "air", label: $t("dashboard.air"), color: "--muted" },
      ]} />
  </div>
  <div class="card">
    <h2><Icon name="bolt" size={18} /> {$t("history.pump")}</h2>
    <Chart {points} relayKey="relay" unit="W" height={160}
      series={[{ key: "power_w", label: $t("dashboard.power"), color: "--good" }]} />
    {#if range === "day"}
      <p class="muted">{$t("history.runtime")}: {$fmt.hours(runToday)}</p>
    {/if}
  </div>
{/if}
