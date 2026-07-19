<script>
  import { snapshot, auth, roleAtLeast } from "../lib/store.js";
  import { api } from "../lib/api.js";
  import { t } from "../lib/i18n.js";
  import { fmt } from "../lib/format.js";
  import { showToast } from "../lib/toast.js";
  import Icon from "../components/Icon.svelte";
  import Confirm from "../components/Confirm.svelte";

  let st = $derived($snapshot?.status || null);
  let lockouts = $derived(Object.entries(st?.lockouts || {})
    .filter(([, v]) => v).map(([k]) => k));
  let faults = $derived(st?.last?.faults || []);
  let canOperate = $derived(roleAtLeast($auth.role, "operator"));

  let estopOpen = $state(false);
  let busy = $state("");

  async function run(minutes) {
    busy = "run" + minutes;
    try {
      await api.post("/api/control/run", { duration_min: minutes });
      showToast($t("control.sent"));
    } catch { showToast($t("err.generic")); }
    busy = "";
  }

  async function resetFault(cls) {
    busy = "reset" + cls;
    try {
      const res = await api.post("/api/control/reset_fault", { cls });
      showToast(res.ok !== false ? $t("control.sent") : $t("err.generic"));
    } catch { showToast($t("err.generic")); }
    busy = "";
  }

  async function estop() {
    try {
      await api.post("/api/control/estop");
      showToast($t("control.sent"));
    } catch { showToast($t("err.generic")); }
  }

  async function calibrate() {
    busy = "cal";
    try {
      const res = await api.post("/api/control/calibrate");
      showToast($t("control.calibrated", { watts: Math.round(res.power_w) }));
    } catch { showToast($t("err.generic")); }
    busy = "";
  }

  const durations = [15, 30, 60, 120];
</script>

<h1>{$t("control.title")}</h1>

<div class="card">
  <h2><Icon name="play" size={18} /> {$t("control.run_title")}</h2>
  <p class="muted">{$t("control.run_hint")}</p>
  <div class="row">
    {#each durations as d}
      <button disabled={!canOperate || busy !== ""} onclick={() => run(d)}>
        {#if busy === "run" + d}<span class="spin"></span>{:else}
          {$t("control.start_run", { min: d })}{/if}
      </button>
    {/each}
  </div>
</div>

<div class="card">
  <h2><Icon name="warn" size={18} /> {$t("control.fault_title")}</h2>
  {#if faults.length === 0 && lockouts.length === 0}
    <p class="muted">{$t("control.no_faults")}</p>
  {:else}
    <p class="muted">{$t("control.reset_hint")}</p>
    <table>
      <tbody>
        {#each [...new Set([...faults, ...lockouts])] as cls}
          <tr>
            <td>
              <span class="badge {lockouts.includes(cls) ? 'bad' : 'warn'}">
                {lockouts.includes(cls) ? "🔒" : "⚠"}
              </span>
              {$t("faults." + cls)}
            </td>
            <td style="text-align:right">
              {#if lockouts.includes(cls)}
                <button disabled={!canOperate || busy !== ""}
                  onclick={() => resetFault(cls)}>
                  {#if busy === "reset" + cls}<span class="spin"></span>
                  {:else}{$t("control.reset")}{/if}
                </button>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</div>

<div class="card">
  <h2><Icon name="bolt" size={18} /> {$t("control.calibrate")}</h2>
  <p class="muted">{$t("control.calibrate_hint")}</p>
  <div class="spread">
    <span class="mono">
      {$t("sensors.nominal")}: {st?.pump_nominal ? Math.round(st.pump_nominal) + " W" : "–"}
    </span>
    <button disabled={!canOperate || busy !== ""} onclick={calibrate}>
      {#if busy === "cal"}<span class="spin"></span>{:else}{$t("control.calibrate")}{/if}
    </button>
  </div>
</div>

<div class="card" style="border-color: var(--bad)">
  <h2 style="color:var(--bad)"><Icon name="stop" size={18} /> {$t("control.estop")}</h2>
  <p class="muted">{$t("control.estop_hint")}</p>
  <button class="danger" disabled={!canOperate} onclick={() => (estopOpen = true)}>
    ⏻ {$t("control.estop")}
  </button>
</div>

<Confirm bind:open={estopOpen} danger doubleConfirm
  title={$t("control.estop")}
  message={$t("control.estop_confirm1")}
  message2={$t("control.estop_confirm2")}
  onconfirm={estop} />
