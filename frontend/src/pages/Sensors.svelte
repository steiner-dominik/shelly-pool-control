<script>
  import { onMount } from "svelte";
  import { snapshot, auth, roleAtLeast } from "../lib/store.js";
  import { api } from "../lib/api.js";
  import { t } from "../lib/i18n.js";
  import { fmt } from "../lib/format.js";
  import { showToast } from "../lib/toast.js";
  import Icon from "../components/Icon.svelte";

  const roles = ["water_a", "water_b", "mat_a", "mat_b", "air"];
  let st = $derived($snapshot?.status || null);
  let last = $derived(st?.last || null);
  let isAdmin = $derived(roleAtLeast($auth.role, "admin"));

  let mapping = $state(null);
  let relayId = $state(0);
  let inputPump = $state(0);
  let busy = $state(false);

  onMount(async () => {
    if (!isAdmin) return;
    try {
      const res = await api.get("/api/device");
      const dev = res.dev || {};
      mapping = { ...{ water_a: 100, water_b: 101, mat_a: 102, mat_b: 103, air: 104 },
        ...(dev.sensors || {}) };
      relayId = dev.relay_id ?? 0;
      inputPump = dev.input_pump ?? 0;
    } catch { /* device not reachable */ }
  });

  async function saveMapping() {
    busy = true;
    try {
      await api.put("/api/device", {
        sensors: mapping, relay_id: relayId, input_pump: inputPump });
      showToast($t("common.saved"));
    } catch { showToast($t("err.generic")); }
    busy = false;
  }

  function validity(slot) {
    const raw = last?.sensors?.[slot];
    if (raw == null) return { ok: false };
    return { ok: true };
  }
</script>

<h1>{$t("sensors.title")}</h1>

<div class="card">
  <h2><Icon name="sensors" size={18} /> {$t("sensors.effective")}</h2>
  <div class="grid cols-4">
    <div><div class="tile-label">{$t("dashboard.water")}</div>
      <div class="big-value mono">{$fmt.temp(last?.effective?.water)}</div></div>
    <div><div class="tile-label">{$t("dashboard.mat")}</div>
      <div class="big-value mono">{$fmt.temp(last?.effective?.mat)}</div></div>
    <div><div class="tile-label">{$t("dashboard.air")}</div>
      <div class="big-value mono">{$fmt.temp(last?.effective?.air)}</div></div>
    <div><div class="tile-label">{$t("dashboard.delta")}</div>
      <div class="big-value mono">{$fmt.delta(last?.effective?.delta)}</div></div>
  </div>
</div>

<div class="card">
  <h2><Icon name="wave" size={18} /> {$t("sensors.probe")}</h2>
  <table>
    <thead><tr><th>{$t("sensors.role")}</th><th>{$t("sensors.value")}</th>
      {#if mapping}<th>{$t("sensors.component")}</th>{/if}</tr></thead>
    <tbody>
      {#each roles as slot}
        <tr>
          <td>{$t("sensors.roles." + slot)}</td>
          <td class="mono">
            {#if validity(slot).ok}
              {$fmt.temp(last?.sensors?.[slot])}
            {:else}
              <span class="badge bad">{$t("sensors.invalid")}</span>
            {/if}
          </td>
          {#if mapping}
            <td style="max-width:110px">
              <input type="number" min="-1" max="299" bind:value={mapping[slot]} />
            </td>
          {/if}
        </tr>
      {/each}
    </tbody>
  </table>
  {#if mapping}
    <p class="muted">{$t("sensors.mapping_hint")}</p>
    <div class="grid cols-2" style="margin-top:8px">
      <div>
        <label for="relay">{$t("sensors.relay_channel")}</label>
        <input id="relay" type="number" min="0" max="3" bind:value={relayId} />
      </div>
      <div>
        <label for="input">{$t("sensors.input_button")}</label>
        <input id="input" type="number" min="-1" max="3" bind:value={inputPump} />
      </div>
    </div>
    <div style="text-align:right; margin-top:10px">
      <button class="primary" disabled={busy} onclick={saveMapping}>
        {#if busy}<span class="spin"></span>{:else}{$t("common.save")}{/if}
      </button>
    </div>
  {/if}
</div>

<div class="card">
  <h2><Icon name="bolt" size={18} /> {$t("sensors.calibration")}</h2>
  <p class="mono">{$t("sensors.nominal")}:
    {st?.pump_nominal ? Math.round(st.pump_nominal) + " W" : "–"}</p>
  <p class="muted">{$t("control.calibrate_hint")}</p>
</div>
