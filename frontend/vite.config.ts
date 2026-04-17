import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      // Route all API traffic through Kong (port 8888) instead of FastAPI directly.
      // Kong enforces CORS, rate-limiting, and correlation-ID headers globally.
      "/api": {
        target: "http://127.0.0.1:8888",
        changeOrigin: true,
      },
    },
  },
});
