# High-Concurrency WebSocket Streaming Guide

A guide derived from debugging a 200-stream concurrent perf test in a
FastAPI + LangGraph + Centrifugo fintech service.

---

## Full Centrifugo End-to-End Flow

### System Overview

```
Browser
  │
  ├─ HTTP  ──→ nginx-internal :8888  ──→ FastAPI-runner    :8432-:8435  (all HTTP endpoints)
  │
  ├─ WS    ──→ nginx-internal :8888  ──→ Centrifugo-0 :8000  (shard 0 — redis-0)
  │                                  ──→ Centrifugo-1 :8000  (shard 1 — redis-1)
  │
Celery workers (WSL2 prefork, queue: stream:ingest)
  │
  └─ XADD ──→ Redis-0/Redis-1  fin:llm:tokens
                   │
                   └─ XREADGROUP ──→ Centrifugo native consumer  ──→ WS publish
```

**Two delivery paths — never mix:**

| Path | Writer | Transport | Reader |
|---|---|---|---|
| **Token** (high-frequency) | Celery `xadd_sharded(thread_id)` | Redis Stream `fin:llm:tokens` | Centrifugo native consumer → WS |
| **Lifecycle** (low-frequency) | FastAPI `publish_to_channel(thread_id, payload)` | HTTP `POST centrifugo-{n}:8000/api` | Centrifugo HTTP API → WS |

FastAPI is **never** in the token delivery path.

---

### Step 1 — Frontend submits a query

```
Browser → POST /api/v1/users/query   (X-User-Token: <jwt>)
        → nginx-internal :8888
        → round-robin to runner-upstream (FastAPI :8432–:8435)
        → backend/api/queries.py
            INSERT user_queries (status='received')
            set_query_phase("received")
            emit_query_received()   ← publish_to_channel → Centrifugo HTTP API
            emit_query_status()     ← same path
        → return {thread_id, status:"received"}
```

Frontend immediately sets session status `"received"` from the HTTP response —
no need to wait for the WebSocket event.

---

### Step 2 — Frontend fetches Centrifugo JWT tokens

```
Browser → GET /api/v1/centrifugo/llm-token?thread_id=<uuid>   (X-User-Token: <jwt>)
        → nginx-internal :8888
        → route-centrifugo-llm  (rate-limit: 6000/min)
        → runner-upstream (FastAPI :8432-:8435)
        → backend/api/centrifugo.py :: get_centrifugo_token()
```

**Inside `get_centrifugo_token()`:**

```python
shard = get_shard_index(thread_id)          # SHA-256(thread_id) % 2
channel = f"thread:{thread_id}"

# Points browser to the correct shard through nginx-internal
ws_url = f"{CENTRIFUGO_PUBLIC_BASE}/centrifugo-{shard}/connection/websocket"

connection_token = make_connection_token(user_id, CENTRIFUGO_SECRET)
# JWT claims: {"sub": user_id, "iat": now, "exp": now+3600}

subscription_token = make_subscription_token(user_id, thread_id, CENTRIFUGO_SECRET)
# JWT claims: {"sub": user_id, "channel": "thread:{thread_id}", "iat": now, "exp": now+3600}

return {ws_url, connection_token, subscription_token, shard_index, channel}
```

Both tokens are HS256 JWTs signed with `CENTRIFUGO_TOKEN_HMAC_SECRET_KEY` — the same
key configured in each Centrifugo node under `client.token.hmac_secret_key`.
No external JWT library used — pure Python `hmac` + `hashlib`.

**Shard routing is deterministic:**

```
SHA-256(thread_id) % 2 == 0  →  ws_url = .../centrifugo-0/connection/websocket
SHA-256(thread_id) % 2 == 1  →  ws_url = .../centrifugo-1/connection/websocket
```

The same hash is used by `RedisRouter._shard_index()` (for Redis key routing) and
`get_shard_index()` (for Centrifugo publish routing) — guaranteeing token events
written to `redis-N` are consumed by `centrifugo-N`.

---

### Step 3 — Browser opens WebSocket via nginx-internal

```
Browser → WebSocket upgrade
        → ws://localhost:8888/centrifugo-{shard}/connection/websocket
        → nginx-internal :8888
        → /centrifugo-{shard}/ location  (proxy_pass, WebSocket upgrade headers)
        → centrifugo-{n}:8000/connection/websocket
```

nginx-internal config for Centrifugo (gateway/nginx-internal.conf):

```nginx
location ~ ^/centrifugo-([01])/(.*) {
    proxy_pass http://centrifugo-$1:8000/$2$is_args$args;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;   # hold WS connection open for full stream duration
    proxy_send_timeout 3600s;
}
```

**Centrifugo validates the connection JWT:**
- Extracts `sub` (user_id) from `connection_token`
- Verifies HS256 signature against `token_hmac_secret_key`
- Associates the TCP connection with that user

**Centrifugo validates the subscription JWT:**
- Client calls `newSubscription("thread:{thread_id}", {token: subscription_token})`
- Centrifugo checks `channel` claim in the subscription token matches requested channel
- Grants subscription — client now receives all publications on `thread:{thread_id}`

**With shared shard client (`centrifugoClient.ts`):**
```
200 streams, same user → 2 WebSocket connections (1 per shard)
Each connection has up to 100 active subscriptions (one per stream on that shard)
Centrifugo multiplexes publications per-subscription over the shared WS frame
```

---

### Step 4 — Frontend subscribes with history recovery

```typescript
const sub = centrifuge.newSubscription(channel, {
  token: subscription_token,
  recoverable: true,
  since: { epoch: '', offset: 0 },  // ← deliver ALL history from the beginning
});
sub.subscribe();
```

`since: {epoch:'', offset:0}` forces Centrifugo to deliver its full channel history
on subscription.  This covers events (e.g. `query_received`, `started`) that were
published *before* the WebSocket connected — critical because the graph can start
running within milliseconds of the query submit while the WS bootstrap takes ~100ms.

Centrifugo namespace `thread` config:
```json
{
  "name": "thread",
  "history_size": 2000,
  "history_ttl": "600s",
  "force_recovery": true
}
```

---

### Step 5 — Frontend ACKs the query

```
sub.on("publication", ctx => dispatch(ctx.data))
  → dispatch sees event="query_received"
  → onQueryReceived() handler
  → POST /api/v1/users/query/{thread_id}/ack   (X-User-Token)
  → nginx-internal → runner-upstream
  → backend/api/queries.py :: ack_query()
      SELECT FOR UPDATE (dedup guard)
      UPDATE user_queries SET status='running'
      asyncio.create_task(run_graph_async(thread_id, query))
      mark_task_active()
      emit_query_ack_confirmed()    ← publish_to_channel
```

---

### Step 6 — LangGraph graph runs; Celery takes over token delivery

```
run_graph_async(thread_id, query)
  set_query_phase("preparing") + emit_query_status("preparing")  ← Centrifugo HTTP API

  graph.ainvoke()
    stream_runner node
      dispatch_scheduled_ingest(run_id, stream_configs)
        ─ all streams register in Redis hash fin:stream:sched:state:{run_id}:{stream_id}
        ─ first registrant wins SETNX coordinator lock
        ─ coordinator waits 500ms rendezvous, then dispatches:

      run_fanout_batch.delay(run_id, configs)   ← Celery task dispatch
```

**Celery task `run_fanout_batch`** (`backend/streaming/workers/fanout.py`):
```python
@celery_engine.task(queue="stream:ingest", acks_late=True)
def run_fanout_batch(run_id, stream_configs, timeout_secs, ...):
    asyncio.run(_fanout_async(run_id, stream_configs, timeout_secs))

async def _fanout_async(run_id, stream_configs, timeout_secs):
    # All N streams run concurrently in ONE asyncio event loop
    # Mock LLM is fully I/O-bound → no prefork starvation
    await asyncio.gather(*[
        _ingest_one(cfg, semaphore, ...)
        for cfg in stream_configs
    ])

async def _ingest_one(cfg, sem, ...):
    for token in mock_llm_generator():
        async with sem:    # _XADD_CONCURRENCY = 100 cap
            await xadd_sharded(
                thread_id=cfg["thread_id"],
                stream=STREAM_TOKEN,      # "fin:llm:tokens"
                entry={
                    "method": "publish",
                    "payload": json.dumps({
                        "channel": f"thread:{cfg['thread_id']}",
                        "data": {"event": "token", "token": tok, ...}
                    })
                }
            )
    # Push done signal to BLPOP waiter
    await redis_client.rpush(done_key, result_json)
```

---

### Step 7 — Redis Stream → Centrifugo native consumer → Browser

```
fin:llm:tokens (on redis-N)
  │
  XREADGROUP "centrifugo-N-token" num_workers=32
  │
  Centrifugo-N internal consumer
    │  Entry format:
    │    method:  "publish"
    │    payload: '{"channel":"thread:<uuid>","data":{"event":"token","token":"..."}}'
    │
    Centrifugo publishes to channel thread:<uuid>
    │
    WebSocket frame → Browser
      │
      sub.on("publication", ctx => dispatch(ctx.data))
        → case "token": handlers.onToken(ctx.data)
        → case "token_batch": handlers.onTokenBatch(ctx.data)
```

**Key: FastAPI never touches this path.**  Redis entry format must exactly match
Centrifugo v6 async consumer protocol: two fields `method` + `payload` where
`payload` is a JSON string (not an object).

---

### Step 8 — Lifecycle events via FastAPI → Centrifugo HTTP API

Lifecycle events (low-frequency: `started`, `ingest_complete`, `stream_stopped`, `done`) go
through a different path — FastAPI calls the Centrifugo internal HTTP API directly:

```python
# backend/centrifugo/client.py :: publish_to_channel()
await httpx_client.post(
    f"http://centrifugo-{shard}:8000/api",
    headers={
        "Authorization": f"apikey {CENTRIFUGO_API_KEY}",
        "Content-Type": "application/json",
    },
    json={
        "method": "publish",
        "params": {
            "channel": f"thread:{thread_id}",
            "data": payload,          # {"event": "ingest_complete", ...}
        },
    },
)
```

- Internal Docker network, not exposed externally
- `CENTRIFUGO_API_KEY` in config — different from the JWT secret
- Fire-and-forget: errors are `WARNING` logged, never raised
- One retry on `RemoteProtocolError` / `ConnectError` (stale keep-alive after Centrifugo restart)

---

### Step 9 — Stream completes; cleanup

```
Celery fanout finishes → RPUSH done_key → FastAPI BLPOP unblocks

FastAPI concurrency_task (backend/graph/agents/streamer/tasks/concurrency.py)
  emit_ingest_complete()    ← publish_lifecycle → Centrifugo HTTP API
  emit_stream_stopped()     ← same

run_graph_async continues after graph.ainvoke()
  UPDATE status='completed' (atomic ownership claim)
  emit_done()               ← publish_lifecycle → Centrifugo HTTP API

Browser receives event="done"
  → handlers.onDone()
  → sub.unsubscribe() + sub.removeAllListeners()
  ← does NOT disconnect shared shard client
```

---

### nginx-internal Route Map (Centrifugo-related)

```
nginx-internal :8888
├─ GET  /api/v1/centrifugo/llm-token        → fastapi-runner
├─ WS   /centrifugo-0/*   strip_path   → centrifugo-0:8000   (ws, timeout 1h)
└─ WS   /centrifugo-1/*   strip_path   → centrifugo-1:8000   (ws, timeout 1h)
```

nginx-internal upstream map:

| Location | Upstream | Protocol | timeout |
|---|---|---|---|
| `/centrifugo-0/` | `centrifugo-0:8000` | `ws` | 3 600 s |
| `/centrifugo-1/` | `centrifugo-1:8000` | `ws` | 3 600 s |
| `/api/` | `:8432–:8435` round-robin | `http/1.1` | 30 s |

nginx-internal only handles **WebSocket upgrade** and **HTTP token bootstrap**.  It does
not proxy the Centrifugo internal publish API — that uses Docker internal DNS
(`centrifugo-{n}:8000`) directly from FastAPI.

---

### Shard Routing Consistency Guarantee

All three routing functions use identical logic: `SHA-256(id) % num_shards`.

| Layer | Function | Input | Output |
|---|---|---|---|
| Redis key routing | `RedisRouter._shard_index(stream_id)` | `stream_id` | redis-N client |
| Redis key routing | `RedisRouter._shard_index(thread_id)` | `thread_id` | redis-N client |
| Centrifugo shard | `get_shard_index(thread_id)` | `thread_id` | centrifugo-N URL |
| Done-key routing | `get_client_for_stream(stream_id)` | `stream_id` | redis-N for BLPOP |
| Token XADD | `xadd_sharded(thread_id, ...)` | `thread_id` | redis-N for XADD |

The invariant: `xadd_sharded(thread_id)` writes to `redis-N` where `N = SHA-256(thread_id) % 2`.
`centrifugo-N` consumes exclusively from `redis-N`.  So the token always lands on the
Centrifugo node that owns the subscriber's WebSocket channel.

**If any routing function is wrong**, tokens land on the wrong Redis shard → consumed
by the wrong Centrifugo node → never delivered to the subscriber (silent 0-token failure).

---

### Vite Dev Proxy (local dev only)

In production, the browser hits nginx-internal directly.  In dev, Vite rewrites the WS URL:

```typescript
// stream.ts :: openStream()
const localWsUrl = ws_url.replace(
  /^wss?:\/\/[^/]+/,
  `${wsProtocol}//${window.location.host}`  // replaces backend host with localhost:3000
);
```

Vite `vite.config.ts` proxy:
```
ws://localhost:3000/centrifugo-0/...  →  ws://localhost:8888/centrifugo-0/...
ws://localhost:3000/centrifugo-1/...  →  ws://localhost:8888/centrifugo-1/...
ws://localhost:3000/api/v1/...        →  http://localhost:8888/api/v1/...
```

This bypasses system HTTP proxies (e.g. Clash on `:7890`) which intercept
`localhost` traffic and break WebSocket upgrades.

---

## Problem: Browser WebSocket Connection Limit

### Symptom

200 concurrent streams launched; only **196–198** reached the "stable" / completed
state.  The remaining 2–4 were stuck at "received" with **0 tokens**.

Backend logs showed all 200 streams were fully dispatched and produced 6 000 tokens
each.  The issue was invisible from the server side.

### Diagnosis

| Observation | Source |
|---|---|
| 104 + 94 = 198 `client subscribed to channel` log lines during the test | `docker logs centrifugo-0` / `centrifugo-1` |
| Zero Centrifugo log entries for the failing `thread_id` | `grep 0c038af6 centrifugo-0 logs` → no matches |
| Backend produced 6 000 tokens, SSE lifecycle events published correctly | `streaming.log`, `sse_notifications.log` |
| Centrifugo token fetch returned HTTP 200 for the failing stream | `vite.log` |
| No WebSocket upgrade request ever reached Centrifugo | Absence of subscription event in container logs |

### Root Cause

Each stream opened its own `new Centrifuge(wsUrl)` connection.

```
200 streams × 1 WebSocket = 200 WebSocket connections
All routed through: localhost:3000 (Vite dev proxy) → nginx-internal → Centrifugo
```

**Firefox default**: `network.websocket.max-connections = 200` per origin.
At exactly 200 concurrent streams the limit is hit; excess connections are silently
refused by the browser before the WebSocket upgrade is even attempted.  The
Centrifugo token fetch still succeeds (HTTP/1.1 request, not a WebSocket) which is
why the stream reaches "received" but receives 0 tokens.

---

## Fix: Shared Centrifuge Connection Per Shard

### Architecture

Instead of 1 WebSocket per stream, maintain **1 WebSocket per Centrifugo shard**.
The project has 2 shards → 2 WebSocket connections total, regardless of concurrency.

```
Before:  200 streams → 200 WebSocket connections (hits browser limit)
After:   200 streams → 2 WebSocket connections (1 per shard)
```

Each stream still gets its own `newSubscription(channel, { token })` call on the
shared connection.  Centrifuge.js supports multiple subscriptions on a single
connection natively.

### Implementation

**`frontend/src/api/centrifugoClient.ts`** — module-level shared client pool:

```typescript
const _shardClients = new Map<string, Centrifuge>();

export function getOrCreateShardClient(wsUrl: string, connectionToken: string): Centrifuge {
  const existing = _shardClients.get(wsUrl);
  if (existing) return existing;
  const client = new Centrifuge(wsUrl, { token: connectionToken });
  client.on("disconnected", (ctx) => {
    if (_shardClients.get(wsUrl) === client) _shardClients.delete(wsUrl);
  });
  _shardClients.set(wsUrl, client);
  client.connect();
  return client;
}

export function resetShardClients(): void {
  _shardClients.forEach((c) => c.disconnect());
  _shardClients.clear();
}
```

**`frontend/src/api/stream.ts`** — `openStream` uses shared connection:

```typescript
// Before (per-stream connection):
centrifuge = new Centrifuge(localWsUrl, { token: connection_token });
centrifuge.connect();

// After (shared shard connection):
const centrifuge = getOrCreateShardClient(localWsUrl, connection_token);
```

Cleanup only unsubscribes the channel; it does **not** disconnect the shared client:

```typescript
const cleanup = () => {
  manualClose = true;
  sub?.unsubscribe();
  sub?.removeAllListeners();
  // Do NOT call centrifuge.disconnect() — other subscriptions are still active.
};
```

`onClose` is triggered from `sub.on("unsubscribed")` rather than
`centrifuge.on("disconnected")` so that shared-client disconnections do not
incorrectly fire session close handlers for all streams on that shard:

```typescript
sub.on("unsubscribed", (ctx) => {
  if (!manualClose && !closed) {
    handlers.onClose?.();
    closed = true;
  }
});
```

**`useSessionManager.ts`** — call `resetShardClients()` at test end:

```typescript
const freezeAll = useCallback(() => {
  cleanups.current.forEach((fn) => fn());
  cleanups.current.clear();
  resetShardClients();   // ← disconnect shared WS connections eagerly
  // ...
}, []);

const handleRestart = useCallback(async () => {
  cleanups.current.forEach((fn) => fn());
  cleanups.current.clear();
  resetShardClients();   // ← reset before spawning new streams
  // ...
}, []);
```

---

## Connection Token Reuse

The Centrifuge **connection token** is a per-user JWT with a long TTL (≥ 1 h).
It is the same for every stream belonging to the same user session, making it safe
to share across all subscriptions on a single connection.

The **subscription token** is per-channel and per-stream; each `newSubscription`
call still uses its own independently fetched token.

---

## Other Fixes Applied During This Investigation

### 1. Stable-signal auth header (422 → 200)

`POST /users/query/{threadId}/perf-stable` was missing the `X-User-Token` header.
FastAPI returned 422; the backend never received the stable signal; streams ran
until timeout instead of stopping gracefully.

Fix: added `headers: { "X-User-Token": userToken }` in `queries.ts → stablePerfStream`.

### 2. Group stability blocked by stuck sessions

`concurrencyGroupStable` used `allConcurrent.every(s => s.digest_start_ms != null && isStable)`.
Sessions that never received a WebSocket delivery (0 tokens, no `digest_start_ms`) would
permanently block the group condition from firing, preventing the 196 healthy streams
from completing.

Fix: 8-second startup grace period — sessions still within the grace window but without
`digest_start_ms` are excluded from the group requirement:

```typescript
const STARTUP_GRACE_MS = 8_000;
const participatingConcurrent = allConcurrent.filter(
  (s) => s.digest_start_ms != null || (tickNow - s.start_ms) < STARTUP_GRACE_MS,
);
```

### 3. Done-key routing (stream_id, not thread_id)

Fanout RPUSH and coordinator BLPOP used `thread_id` for shard selection but the key
is named by `stream_id`.  Under high concurrency this caused cross-shard misroutes
where BLPOP waited on a shard that never received the RPUSH.

Fix: `RedisRouter.get_client_for_stream(stream_id)` — SHA-256(stream_id) % 2.

### 4. `_push_timeout_for_ids` silent skip

When coordinator state was missing for a stream_id the helper silently skipped
pushing the timeout signal, leaving the BLPOP hanging and the session stuck.

Fix: raise `KeyError` instead of silently skipping so the error surfaces in logs.

---

## Diagnostics Checklist

When a subset of concurrent streams receive 0 tokens:

1. **Count Centrifugo subscriptions** vs expected stream count:
   ```bash
   docker logs centrifugo-0 2>&1 | grep 'client subscribed to channel' | wc -l
   docker logs centrifugo-1 2>&1 | grep 'client subscribed to channel' | wc -l
   ```
   If count < N streams, the browser is dropping WebSocket connections silently.

2. **Search for the failing thread_id** in Centrifugo logs:
   ```bash
   docker logs centrifugo-0 2>&1 | grep '<thread_id>'
   ```
   No output → browser never established the WebSocket despite fetching the token.

3. **Check the Vite log** for the token fetch HTTP status vs WebSocket upgrade:
   Token 200 OK but no WS frame → browser connection limit hit.

4. **Check nginx-internal rate limits** on centrifugo token endpoint (`6000/min`) and
   perf-stable route if running 200+ streams.

---

## Architecture Tiers for Higher Concurrency

The table below shows how the architecture scales as stream count grows.

| Tier | WebSocket connections | Browser limit | Max streams | Notes |
|---|---|---|---|---|
| **Naïve** (1 WS/stream) | N | ~200 per origin | ~196 in Firefox | Hits browser limit silently |
| **Current: 1 WS/shard** | 2 (1 per Centrifugo shard) | N/A | 10 000+ | Centrifuge.js multiplexes subscriptions |
| **WebSocket over HTTP/2** | 1 TCP (many WS streams) | None | Unlimited | Requires TLS; Centrifugo v6.5.0+ |

### How many subscriptions per connection?

Centrifuge.js has no hard cap on subscriptions per connection.  The practical limit
is Centrifugo server-side resources (goroutines, memory per channel).  Default
`channel_max_length = 255`, max channels per connection controlled by
`client.channel_limit` (default 128 in Centrifugo — tune upward for ≥ 200 streams
on a single shard).

Check / increase in `centrifugo-{n}/config.json`:

```json
{
  "client": {
    "channel_limit": 1024
  }
}
```

### WebSocket over HTTP/2 (RFC 8441) — the long-term path

Centrifugo v6.5.0+ experimentally supports WebSocket over HTTP/2 (RFC 8441).
Each WebSocket session becomes a separate HTTP/2 stream inside **one** TCP
connection, completely eliminating the per-origin WS limit and reducing TLS
handshake overhead.

Requirements:
- Set Go env: `GODEBUG=http2xconnect=1` in the Centrifugo container
- TLS must be enabled on the Centrifugo endpoint (or enable H2C via `http_server.h2c_external: true`)
- Reverse proxy (nginx) must support RFC 8441 WebSocket-over-HTTP/2 proxying
- All major browsers support it: Chrome 67+, Firefox 65+, Safari 14.1+, Edge 79+

For this project's dev setup (plain HTTP through Vite proxy → nginx-internal → Centrifugo),
**1 WS per shard** is sufficient and simpler.  HTTP/2 upgrade is the path once moving
to production TLS.

---

## Browser WebSocket Limits Reference

| Browser | Default per-origin WS limit | Change location |
|---|---|---|
| Firefox | 200 | `about:config` → `network.websocket.max-connections` |
| Chrome / Edge | ~255 (OS TCP socket limit enforced) | No setting; OS-controlled |
| Safari | ~100–256 (macOS dependent) | No setting |

**Key insight**: limits are per *origin* (`scheme + host + port`).  `localhost:3000`
and `localhost:3001` are separate origins — splitting traffic across ports bypasses the
limit.

---

## Better Ways to Test High Concurrency

Testing 200+ concurrent streams from a single browser tab is unreliable due to
the connection limit.  Use these alternatives instead:

### 1. Node.js headless test script (no browser limit)

```typescript
// scripts/perf_concurrency.ts
import { Centrifuge } from "centrifuge";
import fetch from "node-fetch";

const N = 500;
const BASE = "http://localhost:8888";

async function main() {
  // 1. Login and obtain user token
  const { token: userToken } = await (await fetch(`${BASE}/users/guest-login`, { method: "POST" })).json();

  // 2. Submit N stream queries
  const threads = await Promise.all(
    Array.from({ length: N }, (_, i) =>
      fetch(`${BASE}/users/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-Token": userToken },
        body: JSON.stringify({ query: `DO STREAMING PERFORMANCE TEST NOW|...` }),
      }).then((r) => r.json())
    )
  );

  // 3. Open shared Centrifuge connections (1 per shard ws_url)
  const sharedClients = new Map<string, Centrifuge>();
  let received = 0;

  await Promise.all(threads.map(async ({ thread_id }) => {
    const { ws_url, connection_token, subscription_token, channel } =
      await fetch(`${BASE}/centrifugo/llm-token?thread_id=${thread_id}`, {
        headers: { "X-User-Token": userToken },
      }).then((r) => r.json());

    let client = sharedClients.get(ws_url);
    if (!client) {
      client = new Centrifuge(ws_url, { token: connection_token });
      sharedClients.set(ws_url, client);
      client.connect();
    }
    const sub = client.newSubscription(channel, { token: subscription_token, recoverable: true });
    sub.on("publication", (ctx) => {
      if (ctx.data?.event === "stream_stopped") received++;
    });
    sub.subscribe();
  }));

  // 4. Wait for all to complete
  while (received < N) await new Promise((r) => setTimeout(r, 500));
  console.log(`All ${N} streams completed`);
  sharedClients.forEach((c) => c.disconnect());
}

main();
```

Run with: `npx tsx scripts/perf_concurrency.ts`

Node.js has no per-origin WebSocket connection limit (OS limit ~65 535 ports).

### 2. k6 load test

[k6](https://k6.io/) is purpose-built for WebSocket load testing:

```javascript
// scripts/k6_ws_perf.js
import { WebSocket } from "k6/experimental/websockets";
import http from "k6/http";

export const options = { vus: 200, duration: "90s" };

export default function () {
  const token = http.post(`${BASE}/users/guest-login`).json("token");
  const { thread_id } = http.post(`${BASE}/users/query`, ...).json();
  const { ws_url, connection_token, channel } = http.get(
    `${BASE}/centrifugo/llm-token?thread_id=${thread_id}`,
    { headers: { "X-User-Token": token } }
  ).json();

  const ws = new WebSocket(ws_url, null, {
    headers: { Authorization: `Bearer ${connection_token}` },
  });
  ws.onmessage = (e) => { /* count tokens */ };
  ws.onclose = () => { /* mark done */ };
}
```

Run: `k6 run scripts/k6_ws_perf.js` — each VU is an independent OS thread, no
browser limit applies.

### 3. Increase Firefox limit for manual browser tests

For quick manual validation beyond 200 streams:
1. Open `about:config` in Firefox
2. Search `network.websocket.max-connections`
3. Set to `1000` or higher

This bypasses the per-origin limit without changing any code.  Useful for
verifying the UI rendering at 500+ concurrent streams.

### 4. Multiple browser windows on different ports

Each Vite dev-server port is a separate origin.  Splitting 400 streams across
two browser windows at `localhost:3000` and `localhost:3001` gives each 200
connections — both under the limit.  Not scalable, but zero infrastructure change.

---

## Centrifugo Performance Tuning

These settings are relevant for the project's `centrifugo-{n}/config.json`:

```json
{
  "client": {
    "channel_limit": 1024,
    "user_connection_limit": 0
  },
  "websocket": {
    "read_buffer_size": 512,
    "write_buffer_size": 512,
    "use_write_buffer_pool": true,
    "compression": false,
    "compression_min_size": 1024
  },
  "channel": {
    "namespaces": [
      {
        "name": "thread",
        "history_size": 2000,
        "history_ttl": "600s",
        "force_recovery": true
      }
    ]
  }
}
```

| Option | Rationale |
|---|---|
| `client.channel_limit` | Default is 128 — must exceed max streams per user session |
| `websocket.read_buffer_size=512` | Reduces per-connection memory; token messages are small |
| `websocket.use_write_buffer_pool=true` | Pool write buffers instead of 1 per connection; reduces GC |
| `websocket.compression=false` | For LLM token streams (already text JSON, high-entropy), compression adds CPU with marginal savings |
| `websocket.compression_min_size=1024` | If compression is enabled, skip it for small messages |

### Protobuf binary protocol

Switch from JSON to Protobuf framing for ~30–50% bandwidth reduction and lower
server CPU per broadcast.  Client side: pass `centrifuge-protobuf` as the
WebSocket subprotocol:

```typescript
const client = new Centrifuge(wsUrl, {
  token: connectionToken,
  websocketImplementation: WebSocket,
  // Use Protobuf binary protocol
});
// Centrifuge.js >= v5 auto-negotiates Protobuf when the URL has ?cf_protocol=protobuf
// or when built with the protobuf bundle: import { Centrifuge } from "centrifuge/build/protobuf";
```

Useful once token-per-second rate exceeds ~5 000/s across all streams.

### Redis consumer group tuning

Each Centrifugo node consumes `fin:llm:tokens` with `num_workers=32`.  For 200+
streams each producing 100 tps:

```
200 streams × 100 tps = 20 000 tokens/s → 10 000/shard
```

At 10 000 msgs/s, `num_workers=32` is sufficient.  If latency spikes under load,
increase to 64 and monitor Redis Stream lag:

```bash
redis-cli -h redis-0 XINFO GROUPS fin:llm:tokens
# Check: lag field — should stay near 0
```
