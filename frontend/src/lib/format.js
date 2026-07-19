// Formatting with configurable timezone (auto = browser). All timestamps are
// UTC epoch seconds internally; only rendering applies a zone.
import { derived, writable } from "svelte/store";
import { lang } from "./i18n.js";

const KEY = "pool.tz";
export const timezone = writable(localStorage.getItem(KEY) || "auto");
timezone.subscribe((v) => localStorage.setItem(KEY, v));

export const fmt = derived([timezone, lang], ([tz, lg]) => {
  const zone = tz === "auto" ? undefined : tz;
  const timeF = new Intl.DateTimeFormat(lg, {
    hour: "2-digit", minute: "2-digit", timeZone: zone });
  const dtF = new Intl.DateTimeFormat(lg, {
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
    timeZone: zone });
  const fullF = new Intl.DateTimeFormat(lg, {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: zone });
  return {
    time: (ts) => timeF.format(new Date(ts * 1000)),
    dt: (ts) => dtF.format(new Date(ts * 1000)),
    full: (ts) => fullF.format(new Date(ts * 1000)),
    temp: (v) => (v == null ? "–" : `${v.toFixed(1)} °C`),
    delta: (v) => (v == null ? "–" : `${v >= 0 ? "+" : ""}${v.toFixed(1)} K`),
    watts: (v) => (v == null ? "–" : `${Math.round(v)} W`),
    mins: (s) => `${Math.round((s || 0) / 60)} min`,
    hours: (s) => {
      const m = Math.round((s || 0) / 60);
      return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`;
    },
  };
});

export function minutesToHHMM(min) {
  const h = String(Math.floor(min / 60)).padStart(2, "0");
  const m = String(min % 60).padStart(2, "0");
  return `${h}:${m}`;
}

export function hhmmToMinutes(str) {
  const [h, m] = str.split(":").map(Number);
  return (h || 0) * 60 + (m || 0);
}
