<script>
  let { name, size = 22 } = $props();
  const paths = {
    home: "M3 11.5 12 4l9 7.5M5.5 10v9h4.8v-5.4h3.4V19h4.8v-9",
    control: "M4 6h10M18 6h2M4 12h2M10 12h10M4 18h13M14 4v4M8 10v4M17 16v4",
    settings: "M12 8.5A3.5 3.5 0 1 0 12 15.5 3.5 3.5 0 0 0 12 8.5zM19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3 1a7 7 0 0 0-2-1.2L14.3 3h-4l-.4 2.5a7 7 0 0 0-2 1.2l-2.3-1-2 3.4 2 1.5A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.3-1a7 7 0 0 0 2 1.2l.4 2.5h4l.4-2.5a7 7 0 0 0 2-1.2l2.3 1 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z",
    sensors: "M12 3v8M12 11a4 4 0 1 0 4 4M8.5 6.5 12 3l3.5 3.5M4 19c2.5-2 5-2 8 0s5.5 2 8 0",
    history: "M12 8v4l3 2M12 4a8 8 0 1 0 8 8M12 4V2M12 4 9.5 5",
    log: "M6 3h9l4 4v14H6zM14 3v5h5M9 12h6M9 16h6",
    system: "M5 5h14v10H5zM9 19h6M12 15v4M8 9h4M8 11.5h8",
    wave: "M3 13c2.5-2.5 5-2.5 7.5 0s5 2.5 7.5 0M3 18c2.5-2.5 5-2.5 7.5 0s5 2.5 7.5 0",
    sun: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M19.1 4.9l-1.8 1.8M6.7 17.3l-1.8 1.8",
    pump: "M12 4a8 8 0 1 0 8 8h-8z M12 4v8",
    warn: "M12 3 2.5 20h19zM12 9.5V15M12 17.5v.2",
    bolt: "M13 2 4 14h6l-1 8 9-12h-6z",
    x: "M5 5l14 14M19 5 5 19",
    check: "M4 12.5 10 18 20 6",
    user: "M12 12a4.2 4.2 0 1 0 0-8.4A4.2 4.2 0 0 0 12 12zM4 21c.8-4 4-6 8-6s7.2 2 8 6",
    download: "M12 3v11M7.5 10 12 14.5 16.5 10M4 18.5h16",
    upload: "M12 14V3M7.5 7.5 12 3l4.5 4.5M4 18.5h16",
    stop: "M7 7h10v10H7z",
    play: "M7 5v14l12-7z",
    snow: "M12 2v20M4 6l16 12M20 6 4 18M12 6l-2-2M12 6l2-2M12 18l-2 2M12 18l2 2",
    globe: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c-3 3.5-3 14.5 0 18M12 3c3 3.5 3 14.5 0 18",
    moon: "M20 13.5A8 8 0 0 1 10.5 4 8 8 0 1 0 20 13.5z",
    shield: "M12 3 5 6v5c0 4.5 3 8.5 7 10 4-1.5 7-5.5 7-10V6z",
    clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7.5V12l3 2",
    flame: "M12 3s5 4.5 5 9.5A5 5 0 0 1 12 17.5 5 5 0 0 1 7 12.5C7 7.5 12 3 12 3zM12 21.5v-4"
  };
</script>

<svg width={size} height={size} viewBox="0 0 24 24" fill="none"
  stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
  stroke-linejoin="round" aria-hidden="true">
  <path d={paths[name] || paths.warn} />
</svg>
