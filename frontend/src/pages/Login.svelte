<script>
  import { api } from "../lib/api.js";
  import { auth, refreshAuth } from "../lib/store.js";
  import { t, locale, LOCALE_NAMES } from "../lib/i18n.js";
  import { theme } from "../lib/theme.js";

  let username = $state("");
  let password = $state("");
  let totp = $state("");
  let needTotp = $state(false);
  let error = $state("");
  let busy = $state(false);

  async function submit(e) {
    e.preventDefault();
    busy = true;
    error = "";
    try {
      if ($auth.setup_required) {
        await api.post("/api/auth/setup", { username, password });
      } else {
        await api.post("/api/auth/login",
          { username, password, totp: totp || null });
      }
      await refreshAuth();
    } catch (err) {
      if (err.code === "totp_required") { needTotp = true; error = $t("login.totp_required"); }
      else if (err.code === "totp_invalid") { needTotp = true; error = $t("login.totp_invalid"); }
      else if (err.status === 429) error = $t("login.rate_limited");
      else if (err.code === "password_too_short") error = $t("login.password_too_short");
      else error = $t("login.invalid");
    } finally {
      busy = false;
    }
  }
</script>

<div class="wrap">
  <form class="card login" onsubmit={submit}>
    <div style="text-align:center; margin-bottom:10px;">
      <img src="/favicon.svg" alt="" width="64" height="64" />
      <h1>{$t("app.title")}</h1>
    </div>
    {#if $auth.setup_required}
      <h2>{$t("login.setup_title")}</h2>
      <p class="muted">{$t("login.setup_hint")}</p>
    {/if}
    <label for="u">{$t("login.username")}</label>
    <input id="u" bind:value={username} autocomplete="username" required />
    <label for="p" style="margin-top:10px">{$t("login.password")}</label>
    <input id="p" type="password" bind:value={password}
      autocomplete={$auth.setup_required ? "new-password" : "current-password"} required />
    {#if needTotp}
      <label for="o" style="margin-top:10px">{$t("login.totp")}</label>
      <input id="o" bind:value={totp} inputmode="numeric" autocomplete="one-time-code" />
    {/if}
    {#if error}<p class="badge bad" style="margin-top:10px">{error}</p>{/if}
    <button class="primary" style="width:100%; margin-top:16px" disabled={busy}>
      {#if busy}<span class="spin"></span>{:else}
        {$auth.setup_required ? $t("login.setup_submit") : $t("login.submit")}
      {/if}
    </button>
    <div class="row" style="justify-content:center; margin-top:16px">
      <select style="width:auto" bind:value={$locale} aria-label={$t("system.language")}>
        <option value="auto">🌐 Auto</option>
        {#each Object.entries(LOCALE_NAMES) as [code, name]}
          <option value={code}>{name}</option>
        {/each}
      </select>
      <select style="width:auto" bind:value={$theme} aria-label={$t("system.theme")}>
        <option value="auto">◐ {$t("system.theme_auto")}</option>
        <option value="light">☀ {$t("system.theme_light")}</option>
        <option value="dark">☾ {$t("system.theme_dark")}</option>
      </select>
    </div>
  </form>
</div>

<style>
  .wrap {
    min-height: 100vh; display: flex; align-items: center;
    justify-content: center; padding: 20px;
  }
  .login { width: 100%; max-width: 380px; padding: 26px; }
</style>
