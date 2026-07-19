// Extensible i18n: JSON locale files, browser-language default, quick chooser.
// Add a language: drop src/locales/<code>.json and add it to LOCALES below
// (see docs/TRANSLATIONS.md).
import { derived, writable } from "svelte/store";
import en from "../locales/en.json";
import de from "../locales/de.json";

export const LOCALES = { en, de };
export const LOCALE_NAMES = { en: "English", de: "Deutsch" };

const KEY = "pool.locale";
const fromUrl = new URLSearchParams(location.search).get("lang");
export const locale = writable(
  fromUrl && (LOCALES[fromUrl] || fromUrl === "auto") ? fromUrl
    : localStorage.getItem(KEY) || "auto");

function effective(loc) {
  if (loc !== "auto") return LOCALES[loc] ? loc : "en";
  const nav = (navigator.language || "en").slice(0, 2).toLowerCase();
  return LOCALES[nav] ? nav : "en";
}

export const lang = derived(locale, effective);

function lookup(dict, key) {
  let cur = dict;
  for (const part of key.split(".")) {
    if (cur == null || typeof cur !== "object") return undefined;
    cur = cur[part];
  }
  return typeof cur === "string" ? cur : undefined;
}

export const t = derived(locale, (loc) => {
  const code = effective(loc);
  return (key, params = {}) => {
    let str = lookup(LOCALES[code], key) ?? lookup(LOCALES.en, key) ?? key;
    for (const [k, v] of Object.entries(params)) {
      str = str.replaceAll(`{${k}}`, String(v));
    }
    return str;
  };
});

export function initI18n() {
  locale.subscribe((v) => {
    localStorage.setItem(KEY, v);
    document.documentElement.lang = effective(v);
  });
}
