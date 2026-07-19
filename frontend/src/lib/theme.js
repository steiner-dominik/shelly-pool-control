// Theme: auto (system) / light / dark with quick chooser; persisted locally.
import { writable } from "svelte/store";

const KEY = "pool.theme";
const fromUrl = new URLSearchParams(location.search).get("theme");
export const theme = writable(
  ["light", "dark", "auto"].includes(fromUrl) ? fromUrl
    : localStorage.getItem(KEY) || "auto");

const media = window.matchMedia("(prefers-color-scheme: dark)");

function apply(value) {
  const effective = value === "auto" ? (media.matches ? "dark" : "light") : value;
  document.documentElement.dataset.theme = effective;
}

export function initTheme() {
  theme.subscribe((v) => {
    localStorage.setItem(KEY, v);
    apply(v);
  });
  media.addEventListener("change", () => {
    apply(localStorage.getItem(KEY) || "auto");
  });
}
