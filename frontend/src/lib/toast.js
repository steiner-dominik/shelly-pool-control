import { writable } from "svelte/store";

export const toast = writable(null);
let timer = null;

export function showToast(message, ms = 2600) {
  toast.set(message);
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => toast.set(null), ms);
}
