/**
 * Headless Node.js load test for the Centrifugo WebSocket pipeline.
 *
 * Bypasses the browser entirely — no per-origin WS limit, no browser memory,
 * tests up to the OS TCP socket limit (~65 535 ephemeral ports).
 *
 * Architecture mirrors the frontend exactly:
 *   POST /auth/guest      → user token
 *   POST /users/query     → thread_id
 *   POST /users/query/ack → start graph
 *   GET  /centrifugo/token → ws_url + JWT
 *   Centrifuge WS         → subscribe thread:{thread_id}
 *
 * Connection pooling:  ONE Centrifuge WS connection per shard (same as browser).
 *
 * Usage:
 *   node tests/ws_load_test.mjs [options]
 *
 * Options:
 *   --concurrency  N     Number of parallel streams to open (default: 10)
 *   --query        TEXT  Query string to send (default: "Analyse AAPL vs MSFT")
 *   --api          URL   Kong HTTP base URL (default: http://127.0.0.1:8888/api/v1)
 *   --timeout      MS    Per-stream done/fail timeout in ms (default: 120000)
 *   --ramp-delay   MS    Delay between launching each stream in ms (default: 0)
 *   --token        UUID  Reuse an existing guest token instead of creating a new one
 */

import { Centrifuge } from "centrifuge";
import WebSocket from "ws";
import { parseArgs } from "node:util";

// ── CLI args ──────────────────────────────────────────────────────────────────

const { values: args } = parseArgs({
  options: {
    concurrency:  { type: "string", default: "10" },
    query:        { type: "string", default: "Analyse AAPL vs MSFT" },
    api:          { type: "string", default: "http://127.0.0.1:8888/api/v1" },
    timeout:      { type: "string", default: "120000" },
    "ramp-delay": { type: "string", default: "0" },
    token:        { type: "string", default: "" },
  },
  strict: false,
});

const CONCURRENCY  = parseInt(args.concurrency,   10);
const QUERY_TEXT   = args.query;
const API_BASE     = args.api.replace(/\/$/, "");
const STREAM_TIMEOUT_MS = parseInt(args.timeout,  10);
const RAMP_DELAY_MS     = parseInt(args["ramp-delay"], 10);
const REUSE_TOKEN  = args.token || "";

// ── Shared shard clients (mirrors centrifugoClient.ts) ────────────────────────

/** ws_url → Centrifuge instance */
const _shardClients = new Map();

function getOrCreateShardClient(wsUrl, connectionToken) {
  // Key by both URL and token so each distinct user gets their own connection.
  // (Browser has one user per tab; load test has N users → N connections.)
  const key = `${wsUrl}::${connectionToken}`;
  const existing = _shardClients.get(key);
  if (existing) return existing;

  const client = new Centrifuge(wsUrl, {
    token: connectionToken,
    websocket: WebSocket,   // Node.js does not have a global WebSocket
  });

  client.on("disconnected", (ctx) => {
    if (ctx.code !== 0) {
      console.warn(`[shard] disconnected code=${ctx.code} reason=${ctx.reason} url=${wsUrl}`);
    }
    if (_shardClients.get(key) === client) {
      _shardClients.delete(key);
    }
  });

  client.on("error", (ctx) => {
    console.warn(`[shard] error url=${wsUrl}`, ctx.error?.message ?? ctx);
  });

  _shardClients.set(key, client);
  client.connect();
  return client;
}

function disconnectAllShards() {
  _shardClients.forEach((c) => c.disconnect());
  _shardClients.clear();
}

// ── HTTP helpers ──────────────────────────────────────────────────────────────

async function httpPost(path, body, token) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["X-User-Token"] = token;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`POST ${path} → HTTP ${res.status}: ${txt.slice(0, 200)}`);
  }
  return res.json();
}

async function httpGet(path, token) {
  const headers = {};
  if (token) headers["X-User-Token"] = token;
  const res = await fetch(`${API_BASE}${path}`, { headers });
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`GET ${path} → HTTP ${res.status}: ${txt.slice(0, 200)}`);
  }
  return res.json();
}

// ── Auth ──────────────────────────────────────────────────────────────────────

async function getGuestToken(reuseToken) {
  const headers = { "Content-Type": "application/json" };
  if (reuseToken) headers["X-User-Token"] = reuseToken;
  const res = await fetch(`${API_BASE}/auth/guest`, { method: "POST", headers });
  if (!res.ok) throw new Error(`Auth failed: HTTP ${res.status}`);
  const data = await res.json();
  return data.id ?? data.token ?? data.user_token;
}

// ── Per-stream runner ─────────────────────────────────────────────────────────

/**
 * Run one complete stream lifecycle:
 *   submit → ack → centrifugo-subscribe → wait for done/failed
 *
 * @param {number}  idx        Stream index (0-based)
 * @param {string}  userToken  Guest auth token
 * @returns {Promise<StreamResult>}
 */
async function runStream(idx, userToken) {
  const label = `[stream-${String(idx).padStart(4, "0")}]`;
  const t0 = Date.now();

  const stats = {
    idx,
    thread_id: null,
    status: "pending",
    events: [],
    tokens_received: 0,
    error: null,
    duration_ms: 0,
  };

  try {
    // 1. Submit query
    const qResp = await httpPost("/users/query", { query: QUERY_TEXT }, userToken);
    stats.thread_id = qResp.thread_id;
    stats.events.push(`submit:${qResp.status}`);

    // 2. ACK
    const ackResp = await httpPost(`/users/query/${qResp.thread_id}/ack`, {}, userToken);
    stats.events.push(`ack:${ackResp.status}`);

    // 3. Fetch Centrifugo tokens
    const ctResp = await httpGet(
      `/centrifugo/token?thread_id=${encodeURIComponent(qResp.thread_id)}`,
      userToken,
    );
    const { ws_url, connection_token, subscription_token, channel } = ctResp;

    // Rewrite to direct Kong HTTP port — no TLS, no Vite proxy needed in Node.js.
    // Backend returns wss://localhost:8443/centrifugo-{n}/... (for browser via Vite).
    // In Node.js we go straight to Kong's HTTP/1.1 WS listener on port 8888.
    const directWsUrl = ws_url.replace(/^wss?:\/\/[^/]+/, "ws://127.0.0.1:8888");

    const centrifuge = getOrCreateShardClient(directWsUrl, connection_token);

    // 4. Subscribe and wait for terminal event
    await new Promise((resolve, reject) => {
      // Hoist sub so the timeout closure can reference it (const would be TDZ).
      let sub = null;

      const timer = setTimeout(() => {
        sub?.unsubscribe();
        reject(new Error(`timeout after ${STREAM_TIMEOUT_MS}ms`));
      }, STREAM_TIMEOUT_MS);

      // Centrifuge v5: newSubscription throws if the channel is already registered
      // (can happen when a shared client reconnects with stale state).
      // Remove the stale subscription first, then create fresh.
      const stale = centrifuge.getSubscription(channel);
      if (stale) {
        stale.unsubscribe();
        centrifuge.removeSubscription(stale);
      }

      sub = centrifuge.newSubscription(channel, {
        token: subscription_token,
        recoverable: true,
        since: { epoch: "", offset: 0 },
      });

      sub.on("publication", ({ data }) => {
        const ev = data?.event;
        if (!ev) return;
        if (ev === "token" || ev === "token_batch") {
          stats.tokens_received++;
        } else {
          stats.events.push(ev);
          if (process.env.VERBOSE) {
            console.log(`${label} event=${ev}`);
          }
        }
        // Terminal events
        if (ev === "done" || ev === "completed" || ev === "failed" || ev === "cancelled") {
          clearTimeout(timer);
          stats.status = ev;
          sub.unsubscribe();
          resolve();
        }
      });

      sub.on("error", (ctx) => {
        clearTimeout(timer);
        reject(new Error(`subscription error: ${ctx.error?.message ?? JSON.stringify(ctx)}`));
      });

      sub.subscribe();
    });

  } catch (err) {
    stats.status = "error";
    stats.error = err.message;
  }

  stats.duration_ms = Date.now() - t0;
  const throughput = stats.tokens_received > 0
    ? ` tokens=${stats.tokens_received} tps=${(stats.tokens_received / (stats.duration_ms / 1000)).toFixed(1)}`
    : "";
  console.log(
    `${label} status=${stats.status} duration=${stats.duration_ms}ms${throughput}${stats.error ? " err=" + stats.error : ""}`,
  );
  return stats;
}

// ── Orchestrator ──────────────────────────────────────────────────────────────

async function main() {
  console.log(`=== ws_load_test: concurrency=${CONCURRENCY} api=${API_BASE} ===`);
  const wallStart = Date.now();

  // Each stream gets its own guest user token.  The backend allows only one
  // concurrent query per user (dedup_nack_concurrent), so sharing one token
  // across N streams would collapse them all into a single thread.
  // --token overrides only stream-0 (useful for re-attaching to a known user).
  console.log(`[auth] creating ${CONCURRENCY} guest token(s)...`);
  const userTokens = await Promise.all(
    Array.from({ length: CONCURRENCY }, (_, i) =>
      getGuestToken(i === 0 ? REUSE_TOKEN : ""),
    ),
  );
  console.log(`[auth] tokens created (sample: ${userTokens[0]})`);

  // Launch streams with optional ramp delay
  const promises = [];
  for (let i = 0; i < CONCURRENCY; i++) {
    if (RAMP_DELAY_MS > 0 && i > 0) {
      await new Promise((r) => setTimeout(r, RAMP_DELAY_MS));
    }
    promises.push(runStream(i, userTokens[i]));
  }

  const results = await Promise.allSettled(promises);
  const elapsed = Date.now() - wallStart;

  // Tear down shared WS connections
  disconnectAllShards();

  // ── Summary ──
  const stats = results.map((r) => (r.status === "fulfilled" ? r.value : { status: "crash", error: r.reason?.message }));

  const counts = {};
  let totalTokens = 0;
  let totalDuration = 0;
  let completedCount = 0;
  for (const s of stats) {
    counts[s.status] = (counts[s.status] ?? 0) + 1;
    totalTokens += s.tokens_received ?? 0;
    if (s.duration_ms) totalDuration += s.duration_ms;
    if (s.status === "done" || s.status === "completed") completedCount++;
  }

  console.log("\n=== SUMMARY ===");
  console.log(`total streams : ${CONCURRENCY}`);
  console.log(`completed     : ${completedCount}`);
  console.log(`status counts : ${JSON.stringify(counts)}`);
  console.log(`total tokens  : ${totalTokens}`);
  console.log(`avg duration  : ${completedCount > 0 ? Math.round(totalDuration / completedCount) : "N/A"} ms`);
  console.log(`wall time     : ${elapsed} ms`);
  console.log(`shards used   : ${_shardClients.size} WS connections`);
  if (completedCount < CONCURRENCY) {
    const failed = stats.filter((s) => s.error);
    for (const f of failed.slice(0, 10)) {
      console.log(`  [stream-${f.idx}] error: ${f.error}`);
    }
  }
}

main().catch((err) => {
  console.error("[fatal]", err);
  process.exit(1);
});
