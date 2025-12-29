import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
      "@sdk": path.resolve(__dirname, "../../libs/sdk_ts/src/index.ts"),
    },
  },
  server: {
    host: true,
    port: 5173,
    strictPort: true,
    hmr: {
      host: "localhost",
      port: 5173,
      clientPort: 5173,
    },
    watch: {
      usePolling: true,
      interval: 300,
    },
    fs: {
      allow: [path.resolve(__dirname, "../..")],
    },
  },
});
