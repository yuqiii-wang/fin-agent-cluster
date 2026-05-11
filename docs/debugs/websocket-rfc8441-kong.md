# WebSocket Connection Failures — RFC 8441 vs HTTP/1.1 via Kong

## Symptom

After the first successful query, all subsequent queries fail with every SSE event
NACKed (CENTRIFUGO_003).  No WebSocket connections appear in Centrifugo logs.
Firefox console shows:

```
Firefox can't establish a connection to the server at
wss://localhost:8443/centrifugo-sse-0/connection/websocket
```

or similar for port 22332.

---

## Root Cause

### Kong ws/wss routes require HTTP/1.1 WebSocket Upgrade

Kong 3.x routes with `protocols: [ws, wss]` are specifically designed for the
**HTTP/1.1 WebSocket Upgrade mechanism** (`Connection: Upgrade`, `Upgrade: websocket`).

Port 8443 is configured as `KONG_PROXY_LISTEN: "0.0.0.0:8443 ssl http2"`.  When
the browser connects to `wss://localhost:8443`, TLS ALPN negotiates **HTTP/2** (h2).
The browser then sends an HTTP/2 `CONNECT` request with `:protocol=websocket`
(RFC 8441 — "Bootstrapping WebSockets with HTTP/2").

Kong's Lua routing layer sees an **HTTP/2 CONNECT** method, **not** an HTTP/1.1
WebSocket upgrade.  It does not match this request to `ws/wss` protocol routes;
the WebSocket connection is silently dropped or returns 400.

Even though the underlying OpenResty 1.27.1 nginx supports RFC 8441 at the
nginx layer, Kong's Lua plugin/routing phase intercepts before nginx can handle
it natively, preventing the RFC 8441 extended CONNECT from being proxied to
centrifugo.

**Effect**: No WebSocket connections ever reach Centrifugo.  All SSE events
published by the backend NACK after 30 s (nobody is subscribed to the channel).

### Stale httpx clients in Celery workers (secondary bug)

`centrifugo_mq/client.py` cached httpx clients at module level.  Celery workers
call `asyncio.run(_run())` per task.  Each `asyncio.run()` creates a new event
loop and closes the previous one.  The cached httpx client retained a reference
to the old (closed) loop, causing:

```
[CENTRIFUGO_001] sse publish error: Event loop is closed
```

on any SSE publish from a Celery worker context after the first task ran.

---

## Investigation Steps

1. Checked centrifugo-sse-0/1 logs — only `POST /api` (backend publishes) visible,
   no WebSocket connection log entries at all.
2. Checked Kong logs — no WebSocket 101 upgrade or error logs.
3. Confirmed all thread events NACK starting from `query_node:running` (the very
   first SSE event), meaning the frontend WebSocket never connected.
4. Confirmed Kong port 8443 uses `http2` in ALPN → browser sends RFC 8441 CONNECT
   instead of HTTP/1.1 WebSocket Upgrade.
5. Confirmed port 22332 (nginx-ui) uses `listen 443 ssl` **without** `http2`,
   so browsers negotiate HTTP/1.1 → standard WebSocket Upgrade works.

---

## Fix

### 1. Restore nginx → centrifugo WebSocket proxy (`nginx-ui.conf`)

Added four `location` blocks (one per centrifugo shard/tier) with:

```nginx
location /centrifugo-sse-0/ {
    proxy_pass         http://centrifugo-sse-0:8000/;
    proxy_http_version 1.1;
    proxy_set_header   Upgrade    $http_upgrade;
    proxy_set_header   Connection "upgrade";
    proxy_set_header   Host       centrifugo-sse-0;
    proxy_set_header   Origin     $http_origin;
    proxy_read_timeout 86400s;
    proxy_send_timeout 86400s;
}
# ... same for centrifugo-sse-1, centrifugo-llm-0, centrifugo-llm-1
```

nginx-ui listens on port 443 (HTTP/1.1 TLS, no `http2` directive).  The browser
negotiates HTTP/1.1 → standard WebSocket Upgrade → nginx proxies directly to
each Centrifugo container.  Centrifugo enforces its own JWT auth so Kong is not
needed in this path.

### 2. Update CENTRIFUGO_PUBLIC_BASE

`.env`:
```
CENTRIFUGO_PUBLIC_BASE=wss://localhost:22332
```

`backend/config.py` default updated to match.

The backend now returns `ws_url = wss://localhost:22332/centrifugo-sse-{shard}/...`
to the frontend.  Browsers connect to port 22332 (nginx-ui HTTP/1.1 TLS).

### 3. Fix stale httpx client in Celery workers (`centrifugo_mq/client.py`)

Added event-loop tracking to `_get_sse_http_client()`, matching the pattern
already used in `db/redis/__init__.py`:

```python
_sse_http_client_loops: dict[int, Any] = {}

def _get_sse_http_client(shard: int) -> httpx.AsyncClient:
    import asyncio
    try:
        current_loop: Any = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    existing = _sse_http_clients.get(shard)
    cached_loop = _sse_http_client_loops.get(shard)

    if existing is not None and not existing.is_closed and cached_loop is current_loop:
        return existing

    # Loop changed (Celery asyncio.run recycled the loop) → fresh client
    _sse_http_clients[shard] = httpx.AsyncClient(timeout=5.0, limits=_HTTP_LIMITS)
    _sse_http_client_loops[shard] = current_loop
    return _sse_http_clients[shard]
```

---

## Architecture — Correct WebSocket Path

```
Browser (https://localhost:3000 or https://localhost:22332)
  │
  │  wss://localhost:22332/centrifugo-{tier}-{shard}/connection/websocket
  ▼
nginx-ui (port 22332 → container 443, HTTP/1.1 TLS, NO http2)
  │  HTTP/1.1 WebSocket Upgrade (Upgrade: websocket)
  │  proxy_pass http://centrifugo-{tier}-{shard}:8000/
  ▼
Centrifugo container (plain HTTP/1.1 WebSocket, port 8000)
  │  JWT token auth enforced by Centrifugo itself
  ▼
Subscribe to channel thread:{thread_id}
```

```
Browser REST API / RPC ACK
  │  https://localhost:8443/api/...   (HTTP/2 REST)
  ▼
Kong (port 8443, HTTP/2 ALPN)
  │  routes to FastAPI runners (HTTP/1.1 upstream)
  ▼
FastAPI
```

Kong handles all REST API traffic (HTTP/2 → HTTP/1.1 upstream).  
nginx handles WebSocket to Centrifugo (HTTP/1.1 → plain WebSocket).

---

## Key Lesson

- **Kong `protocols: [ws, wss]` = HTTP/1.1 WebSocket Upgrade only**.  Never route
  WebSocket through a Kong listener that has `http2` enabled in ALPN — browsers
  will use RFC 8441 (HTTP/2 CONNECT) instead of HTTP/1.1 Upgrade, and Kong will
  not match ws/wss routes.
- **nginx without `http2` = safe WebSocket proxy**.  Use a separate TLS listener
  without HTTP/2 (`listen 443 ssl`, no `http2`) for WebSocket proxying.
- **Celery `asyncio.run()` creates a new event loop per task**.  Any module-level
  asyncio-bound resource (httpx clients, Redis pools) must detect the loop change
  and recreate itself.  Use `asyncio.get_running_loop()` identity checks.
