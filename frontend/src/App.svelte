<script>
  import { onMount } from "svelte";
  import { auth, refreshAuth, snapshot } from "./lib/store.js";
  import { t } from "./lib/i18n.js";
  import { toast } from "./lib/toast.js";
  import Icon from "./components/Icon.svelte";
  import Login from "./pages/Login.svelte";
  import Dashboard from "./pages/Dashboard.svelte";
  import Control from "./pages/Control.svelte";
  import Settings from "./pages/Settings.svelte";
  import Sensors from "./pages/Sensors.svelte";
  import History from "./pages/History.svelte";
  import Log from "./pages/Log.svelte";
  import System from "./pages/System.svelte";

  let route = $state(location.hash.slice(1) || "/");
  onMount(() => {
    refreshAuth();
    const onHash = () => (route = location.hash.slice(1) || "/");
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  });

  const pages = [
    { path: "/", icon: "home", label: "nav.dashboard", comp: Dashboard, min: "viewer" },
    { path: "/control", icon: "control", label: "nav.control", comp: Control, min: "viewer" },
    { path: "/settings", icon: "settings", label: "nav.settings", comp: Settings, min: "admin" },
    { path: "/sensors", icon: "sensors", label: "nav.sensors", comp: Sensors, min: "viewer" },
    { path: "/history", icon: "history", label: "nav.history", comp: History, min: "viewer" },
    { path: "/log", icon: "log", label: "nav.log", comp: Log, min: "viewer" },
    { path: "/system", icon: "system", label: "nav.system", comp: System, min: "viewer" },
  ];
  const rank = { viewer: 0, operator: 1, admin: 2 };
  let visible = $derived(pages.filter((p) => rank[$auth.role] >= rank[p.min]));
  let current = $derived(pages.find((p) => p.path === route) || pages[0]);
</script>

{#if $auth.loading}
  <div style="display:flex;justify-content:center;align-items:center;height:100vh">
    <span class="spin"></span>
  </div>
{:else if !$auth.authenticated}
  <Login />
{:else}
  <div class="layout">
    <nav class="nav">
      <div class="brand">
        <img src="/favicon.svg" alt="" width="28" height="28" />
        {$t("app.title")}
      </div>
      {#each visible as p}
        <a href={"#" + p.path} class:active={route === p.path}
           aria-current={route === p.path ? "page" : undefined}>
          <Icon name={p.icon} />
          <span>{$t(p.label)}</span>
        </a>
      {/each}
    </nav>
    <main class="content">
      {#if $snapshot && !$snapshot.online}
        <div class="banner warn">⚠ {$t("dashboard.offline_banner")}</div>
      {/if}
      {#if $auth.simulate}
        <div class="banner info">🧪 {$t("dashboard.sim_banner")}</div>
      {/if}
      {#if rank[$auth.role] >= rank[current.min]}
        {@const Page = current.comp}
        <Page />
      {:else}
        <div class="banner bad">{$t("err.insufficient_role")}</div>
      {/if}
    </main>
  </div>
{/if}

{#if $toast}
  <div class="toast">{$toast}</div>
{/if}
