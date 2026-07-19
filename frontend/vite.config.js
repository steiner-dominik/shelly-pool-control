import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

// The backend serves the build output from server/app/static.
export default defineConfig({
  plugins: [svelte()],
  define: {
    __APP_VERSION__: JSON.stringify(process.env.POOL_VERSION || "dev"),
  },
  build: {
    outDir: "../server/app/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
        ws: true,
      },
      "/healthz": "http://localhost:8080",
    },
  },
});
