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
  // Load .env / .env.local so VITE_KONG_URL is visible at config time.
  const env = loadEnv(mode, process.cwd(), "");
  // directMode: VITE_KONG_URL is set → browser talks directly to Kong 8443.
  //   REST:  browser → Kong :8443 (HTTPS/HTTP2, absolute URL, CORS allowed)
  //   WS:    browser → Kong :8443 (WSS direct, no Vite proxy hop)
  //   Effect: all 6-fetch / HTTP1.1 limits are bypassed entirely.
  //
  // proxyMode (default, VITE_KONG_URL empty):
  //   REST:  browser → Vite :3000 (relative /api/*) → Kong :8443 (HTTPS/HTTP2)
  //   WS:    browser → Vite :3000 (WSS) → Kong :8888 (WS, HTTP/1.1 hop)
  //   Effect: system proxy (:7890) is bypassed; WS has one HTTP/1.1 hop.
  const directMode = !!env.VITE_KONG_URL;

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
        // Centrifugo WebSocket paths — proxied server-side so the browser never
        // opens a direct connection (bypasses system proxy at :7890).
        // WebSocket targets Kong HTTP port 8888 (HTTP/1.1) because node-http-proxy
        // cannot reliably forward WS upgrades through a TLS target (https://).
        // TLS end-to-end: browser → Vite (WSS) → Kong (plain WS).
        //
        // In directMode these entries are absent: stream.ts uses the backend-returned
        // wss://localhost:8443 URL directly — fully WSS, no HTTP/1.1 hop.
        "/centrifugo-0": {
          target: "http://127.0.0.1:8888",
          changeOrigin: true,
          ws: true,
          agent: false,
        },
        "/centrifugo-1": {
          target: "http://127.0.0.1:8888",
          changeOrigin: true,
          ws: true,
          agent: false,
        },
      }),
    },
  },
  };
});
