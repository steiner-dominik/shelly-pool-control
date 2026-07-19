<script>
  // Dependency-free canvas line chart (temps) with optional relay band.
  import { fmt } from "../lib/format.js";
  let { points = [], series = [], relayKey = null, unit = "°C", height = 240 }
    = $props();
  let canvas = $state(null);
  let wrap = $state(null);

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function draw() {
    if (!canvas || !wrap) return;
    const dpr = window.devicePixelRatio || 1;
    const w = wrap.clientWidth;
    const h = height;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);
    if (!points.length) return;

    const padL = 38, padR = 8, padT = 10, padB = 22;
    const xs = points.map((p) => p.ts);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    let vmin = Infinity, vmax = -Infinity;
    for (const p of points) {
      for (const s of series) {
        const v = p[s.key];
        if (v != null) { vmin = Math.min(vmin, v); vmax = Math.max(vmax, v); }
      }
    }
    if (!isFinite(vmin)) return;
    const span = Math.max(1, vmax - vmin);
    vmin -= span * 0.1; vmax += span * 0.1;

    const X = (ts) => padL + ((ts - x0) / Math.max(1, x1 - x0)) * (w - padL - padR);
    const Y = (v) => padT + (1 - (v - vmin) / (vmax - vmin)) * (h - padT - padB);

    // relay on/off band
    if (relayKey) {
      ctx.fillStyle = cssVar("--accent-soft");
      let start = null;
      for (let i = 0; i < points.length; i++) {
        const on = !!points[i][relayKey];
        if (on && start === null) start = points[i].ts;
        if ((!on || i === points.length - 1) && start !== null) {
          const end = points[i].ts;
          ctx.fillRect(X(start), padT, Math.max(2, X(end) - X(start)), h - padT - padB);
          start = null;
        }
      }
    }

    // grid + y labels
    ctx.strokeStyle = cssVar("--line");
    ctx.fillStyle = cssVar("--muted");
    ctx.font = "11px " + cssVar("--font");
    ctx.lineWidth = 1;
    const steps = 4;
    for (let i = 0; i <= steps; i++) {
      const v = vmin + ((vmax - vmin) * i) / steps;
      const y = Y(v);
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(w - padR, y); ctx.stroke();
      ctx.fillText(v.toFixed(1), 2, y + 4);
    }
    // x labels
    const fm = $fmt;
    const nLabels = Math.min(5, points.length);
    for (let i = 0; i < nLabels; i++) {
      const ts = x0 + ((x1 - x0) * i) / Math.max(1, nLabels - 1);
      const label = (x1 - x0) > 86400 * 2 ? fm.dt(ts) : fm.time(ts);
      const tw = ctx.measureText(label).width;
      ctx.fillText(label, Math.min(Math.max(padL, X(ts) - tw / 2), w - tw - 4), h - 6);
    }

    // series lines
    for (const s of series) {
      ctx.strokeStyle = s.color.startsWith("--") ? cssVar(s.color) : s.color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      let started = false;
      for (const p of points) {
        const v = p[s.key];
        if (v == null) { started = false; continue; }
        if (!started) { ctx.moveTo(X(p.ts), Y(v)); started = true; }
        else ctx.lineTo(X(p.ts), Y(v));
      }
      ctx.stroke();
    }
  }

  $effect(() => {
    points; series; $fmt;
    draw();
    const obs = new ResizeObserver(draw);
    if (wrap) obs.observe(wrap);
    const mo = new MutationObserver(draw);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => { obs.disconnect(); mo.disconnect(); };
  });
</script>

<div bind:this={wrap} style="width:100%">
  <canvas bind:this={canvas}></canvas>
  <div class="row" style="gap:14px; margin-top:6px;">
    {#each series as s}
      <span class="muted" style="display:flex;align-items:center;gap:5px;">
        <span style="width:14px;height:3px;border-radius:2px;background:{s.color.startsWith('--') ? `var(${s.color})` : s.color};display:inline-block"></span>
        {s.label} <span class="muted">({unit})</span>
      </span>
    {/each}
  </div>
</div>
