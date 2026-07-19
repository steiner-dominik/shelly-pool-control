import { mount } from "svelte";
import App from "./App.svelte";
import "./styles.css";
import { initTheme } from "./lib/theme.js";
import { initI18n } from "./lib/i18n.js";
import { startVersionWatch } from "./lib/version.js";

initTheme();
initI18n();
startVersionWatch();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

mount(App, { target: document.getElementById("app") });
