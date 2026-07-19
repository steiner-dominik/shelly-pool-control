<script>
  import { t } from "../lib/i18n.js";
  let { open = $bindable(false), title, message, danger = false,
    doubleConfirm = false, message2 = "", onconfirm } = $props();
  let stage = $state(0);
  let dialog = $state(null);

  $effect(() => {
    if (!dialog) return;
    if (open && !dialog.open) { stage = 0; dialog.showModal(); }
    if (!open && dialog.open) dialog.close();
  });

  function confirm() {
    if (doubleConfirm && stage === 0) { stage = 1; return; }
    open = false;
    onconfirm?.();
  }
</script>

<dialog bind:this={dialog} onclose={() => (open = false)}>
  <h2>{title}</h2>
  <p>{stage === 1 && message2 ? message2 : message}</p>
  <div class="row" style="justify-content: flex-end; margin-top: 14px;">
    <button onclick={() => (open = false)}>{$t("common.cancel")}</button>
    <button class={danger ? "danger" : "primary"} onclick={confirm}>
      {stage === 1 ? $t("common.confirm") + "!" : $t("common.confirm")}
    </button>
  </div>
</dialog>
