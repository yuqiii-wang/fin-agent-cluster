import { defineConfig, loadEnv, createLogger, type Logger } from "vite";
import react from "@vitejs/plugin-react";
import { appendFileSync, mkdirSync, readFileSync } from "node:fs";
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

export default defineConfig(({ mode }) => {
  // Load .env / .env.local so VITE_API_URL is visible at config time.
  const env = loadEnv(mode, process.cwd(), "");
  // directMode: VITE_API_URL is set → browser talks directly to nginx-api :8443.
  //   REST:  browser → nginx-api :8443 (HTTPS/HTTP2, absolute URL, CORS allowed)
  //
  // proxyMode (default, VITE_API_URL empty):
  //   REST:  browser → Vite :3000 (relative /api/*) → nginx-api :8443 (HTTPS/HTTP2)
  const directMode = !!env.VITE_API_URL;

  return {
  customLogger: fileLogger,
  clearScreen: false,
  logLevel: "info",
  plugins: [react()],
  server: {
    port: 3000,
    // Serve over HTTPS so the browser negotiates HTTP/2 with Kong on port 8443.
    // Self-signed localhost cert — generated once via setup/tls.sh.
    https: {
      key: readFileSync(resolve(__dirname, "../certs/localhost.key")),
      cert: readFileSync(resolve(__dirname, "../certs/localhost.crt")),
    },
    proxy: {
      // REST proxy — only active in proxyMode; in directMode KONG_ORIGIN makes
      // all fetch() calls use absolute https://localhost:8443/... URLs that
      // bypass Vite entirely.
      ...(!directMode && {
        "/api": {
          target: "https://127.0.0.1:8443",
          changeOrigin: true,
          secure: false,    // allow self-signed TLS cert
          agent: false,
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
      }),
    },
  },
  };
});
