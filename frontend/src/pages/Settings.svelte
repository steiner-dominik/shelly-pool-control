<script>
  import { onMount } from "svelte";
  import { api } from "../lib/api.js";
  import { t } from "../lib/i18n.js";
  import { minutesToHHMM, hhmmToMinutes } from "../lib/format.js";
  import { showToast } from "../lib/toast.js";
  import Icon from "../components/Icon.svelte";

  let schema = $state([]);
  let values = $state({});
  let edits = $state({});
  let openGroup = $state("heating");
  let busy = $state(false);
  let loaded = $state(false);

  const groupOrder = ["heating", "filtration", "safety", "policies", "frost",
    "sensors", "system"];

  onMount(load);
  async function load() {
    const res = await api.get("/api/config");
    schema = res.schema;
    values = res.values;
    edits = {};
    loaded = true;
  }

  let groups = $derived(groupOrder.map((g) => ({
    name: g,
    params: schema.filter((p) => p.group === g),
  })).filter((g) => g.params.length));

  function currentValue(p) {
    return p.key in edits ? edits[p.key] : values[p.key]?.value;
  }

  function setEdit(p, v) {
    if (v === values[p.key]?.value) delete edits[p.key];
    else edits[p.key] = v;
    edits = { ...edits };
  }

  function numInput(p, e) {
    const v = e.target.value;
    if (v === "") return;
    setEdit(p, p.unit === "time" ? hhmmToMinutes(v) : Number(v));
  }

  let dirtyCount = $derived(Object.keys(edits).length);

  async function save() {
    busy = true;
    try {
      const res = await api.put("/api/config", { changes: edits });
      showToast(res.confirmed ? $t("settings.saved_confirmed")
        : $t("settings.saved_pending"));
      await load();
    } catch (e) {
      showToast($t("common.error") + ": " + e.code);
    }
    busy = false;
  }

  function fmtSeconds(s) {
    if (s % 3600 === 0 && s >= 3600) return s / 3600 + " h";
    if (s % 60 === 0 && s >= 60) return s / 60 + " min";
    return s + " s";
  }
</script>

<h1>{$t("settings.title")}</h1>
<p class="muted">{$t("settings.pending_hint")}</p>

{#if !loaded}
  <div class="card"><span class="spin"></span> {$t("common.loading")}</div>
{:else}
  {#each groups as g}
    <div class="card">
      <button class="ghost spread" style="width:100%; border:none; padding:2px 0;"
        onclick={() => (openGroup = openGroup === g.name ? "" : g.name)}>
        <h2 style="margin:0"><Icon name={g.name === "frost" ? "snow" : g.name === "safety" ? "shield" : g.name === "heating" ? "flame" : "settings"} size={18} />
          {$t("settings.groups." + g.name)}</h2>
        <span class="muted">{openGroup === g.name ? "▾" : "▸"}</span>
      </button>
      {#if openGroup === g.name}
        <div class="params">
          {#each g.params as p}
            {@const v = currentValue(p)}
            <div class="param" class:dirty={p.key in edits}>
              <div class="spread">
                <label for={"f_" + p.key}>
                  {$t("settings.params." + p.key + ".label")}
                  {#if values[p.key]?.pending}
                    <span class="badge warn">{$t("common.pending")}</span>
                  {/if}
                </label>
                <span class="muted mono" style="font-size:.75rem">
                  {$t("common.default")}:
                  {p.type === "bool" ? (p.default ? "✓" : "✗")
                    : p.unit === "time" ? minutesToHHMM(p.default)
                    : p.unit === "s" ? fmtSeconds(p.default) : p.default}
                  {p.unit && p.unit !== "time" && p.unit !== "s" ? p.unit : ""}
                </span>
              </div>
              {#if p.type === "bool"}
                <select id={"f_" + p.key} value={v ? "1" : "0"}
                  onchange={(e) => setEdit(p, e.target.value === "1")}>
                  <option value="1">{$t("common.enabled")}</option>
                  <option value="0">{$t("common.disabled")}</option>
                </select>
              {:else if p.type === "enum"}
                <select id={"f_" + p.key} value={v}
                  onchange={(e) => setEdit(p, e.target.value)}>
                  {#each p.enum as opt}<option value={opt}>{opt}</option>{/each}
                </select>
              {:else if p.unit === "time"}
                <input id={"f_" + p.key} type="time" value={minutesToHHMM(v)}
                  onchange={(e) => numInput(p, e)} />
              {:else}
                <div class="row" style="flex-wrap:nowrap">
                  <input id={"f_" + p.key} type="number" value={v}
                    min={p.min} max={p.max} step={p.step}
                    onchange={(e) => numInput(p, e)} />
                  {#if p.unit}<span class="muted" style="white-space:nowrap">{p.unit}</span>{/if}
                </div>
                <span class="muted" style="font-size:.72rem">
                  {$t("settings.range", { min: p.min, max: p.max, unit: p.unit === "s" ? "s" : (p.unit || "") })}
                </span>
              {/if}
              <p class="muted help">{$t("settings.params." + p.key + ".help")}</p>
            </div>
          {/each}
        </div>
      {/if}
    </div>
  {/each}

  {#if dirtyCount > 0}
    <div class="savebar">
      <span>{dirtyCount} ✎</span>
      <button onclick={() => (edits = {})}>{$t("settings.discard")}</button>
      <button class="primary" disabled={busy} onclick={save}>
        {#if busy}<span class="spin"></span>{:else}{$t("settings.save_group")}{/if}
      </button>
    </div>
  {/if}
{/if}

<style>
  .params { display: grid; gap: 16px; margin-top: 12px; }
  @media (min-width: 720px) { .params { grid-template-columns: 1fr 1fr; } }
  .param { padding: 10px; border-radius: 10px; border: 1px solid transparent; }
  .param.dirty { border-color: var(--accent); background: var(--accent-soft); }
  .help { margin: 6px 0 0; font-size: .78rem; }
  .savebar {
    position: fixed; bottom: calc(var(--nav-h) + 14px + env(safe-area-inset-bottom));
    left: 50%; transform: translateX(-50%);
    display: flex; gap: 10px; align-items: center;
    background: var(--card); border: 1px solid var(--line);
    border-radius: 14px; box-shadow: var(--shadow); padding: 10px 16px; z-index: 50;
  }
  @media (min-width: 880px) { .savebar { bottom: 24px; } }
</style>
