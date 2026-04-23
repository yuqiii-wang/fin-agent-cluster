import { defineConfig, createLogger, type Logger } from "vite";
import react from "@vitejs/plugin-react";
import { appendFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

// ---------------------------------------------------------------------------
// File logger — mirrors Vite dev-server output to logs/vite.log so the
// console stays clean while providing a persistent record for debugging
// proxy errors, HMR failures, and SSE connection events.
// ---------------------------------------------------------------------------
const logsDir = resolve(__dirname, "../logs");
const logFile = resolve(logsDir, "vite.log");
try { mkdirSync(logsDir, { recursive: true }); } catch { /* already exists */ }

function writeLog(level: string, msg: string): void {
  const ts = new Date().toISOString();
  // Strip ANSI colour codes so the file remains readable.
  const clean = msg.replace(/\x1B\[[0-9;]*m/g, "").trim();
  const entry = JSON.stringify({
    timestamp: ts,
    level: level.toUpperCase(),
    logger: "vite",
    component: "Vite",
    message: clean,
  });
  try {
    appendFileSync(logFile, entry + "\n", "utf-8");
  } catch { /* non-fatal: log write failure must not crash the dev server */ }
}

const baseLogger = createLogger();
const fileLogger: Logger = {
  ...baseLogger,
  info(msg, opts)     { baseLogger.info(msg, opts);     writeLog("info",  msg); },
  warn(msg, opts)     { baseLogger.warn(msg, opts);     writeLog("warn",  msg); },
  warnOnce(msg, opts) { baseLogger.warnOnce(msg, opts); writeLog("warn",  msg); },
  error(msg, opts)    { baseLogger.error(msg, opts);    writeLog("error", msg); },
};

export default defineConfig({
  customLogger: fileLogger,
  clearScreen: false,
  logLevel: "info",
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      // Route all API traffic through Kong (port 8888) instead of FastAPI directly.
      // Kong enforces CORS, rate-limiting, and correlation-ID headers globally.
      "/api": {
        target: "http://127.0.0.1:8888",
        changeOrigin: true,
        configure(proxy) {
          proxy.on("proxyReq", (_proxyReq, req) => {
            fileLogger.info(`[proxy →] ${req.method} ${req.url}`);
          });
          proxy.on("proxyRes", (proxyRes, req) => {
            fileLogger.info(`[proxy ←] ${proxyRes.statusCode} ${req.url}`);
          });
          proxy.on("error", (err, req) => {
            fileLogger.error(`[proxy ✗] ${(req as { url?: string }).url ?? ""}: ${err.message}`);
          });
        },
      },
    },
  },
});
