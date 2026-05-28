# nginx-frontend Stale DNS Routing Bug — Centrifugo Shard Cross-Routing

## Date
2026-05-27

## Symptom
- 100% ACK failure from frontend → backend through Centrifugo SSE
- `CENTRIFUGO_003` logs on all tasks (max retries exhausted, 30s total wait each)
- centrifugo-sse-0 logs showed subscriptions for channels belonging to shard-1 (redis-1), with rapid "client insufficient state (epoch)" reconnect loops
- TCP table inside nginx-frontend showed NO connections to `172.18.0.15:8000` (centrifugo-sse-1) but connections to `172.18.0.4:8000` (centrifugo-sse-0)
- nginx-frontend error log: tried `http://172.18.0.7:8000/` (itself!) for `/centrifugo-sse-0/` — stale DNS had sse-0's old IP which became nginx-frontend's current IP after restart

## Root Cause
nginx-frontend resolves container hostnames **once at startup** (static DNS). After container restarts in a certain order, the in-memory DNS table points to stale IPs:

| Container | Expected IP | nginx had (stale) |
|---|---|---|
| centrifugo-sse-0 | `172.18.0.4` | `172.18.0.7` (became nginx-frontend!) |
| centrifugo-sse-1 | `172.18.0.15` | `172.18.0.4` (became centrifugo-sse-0!) |

Result: ALL shard-1 WebSocket traffic routed to centrifugo-sse-0 (wrong shard, different Redis cluster). Frontend subscribed on sse-0 channel, backend published to sse-1 → events never reached client → ACK never sent → CENTRIFUGO_003 exhausted.

## Shard Assignment
Thread hash → shard 1 → centrifugo-sse-1 (redis-1). Both active test threads hashed to shard 1, so 100% of traffic was affected.

## Fix

### nginx.conf — Dynamic DNS Resolution
Use Docker's embedded DNS resolver with a `resolver` directive and **variable-based `proxy_pass`** so nginx re-resolves hostnames on each request interval instead of caching at startup:

```nginx
server {
    # ... TLS config ...
    resolver 127.0.0.11 valid=10s ipv6=off;  # Docker embedded DNS

    location /centrifugo-sse-0/ {
        set $upstream_centrifugo_sse_0 centrifugo-sse-0:8000;
        rewrite ^/centrifugo-sse-0/(.*) /$1 break;  # strip location prefix
        proxy_pass              http://$upstream_centrifugo_sse_0;
        proxy_http_version      1.1;
        proxy_set_header        Upgrade    $http_upgrade;
        proxy_set_header        Connection "upgrade";
        proxy_set_header        Host       centrifugo-sse-0;
        proxy_set_header        Origin     $http_origin;
        proxy_read_timeout      86400s;
        proxy_send_timeout      86400s;
    }
    # (same pattern for sse-1, llm-0, llm-1)
}
```

**Critical nginx behavior**: when `proxy_pass` uses a variable (`$upstream`), nginx does NOT strip the location prefix from the URI. Must use `rewrite ^/prefix/(.*) /$1 break;` explicitly to strip it before `proxy_pass`.

**Without `rewrite`**: `/centrifugo-sse-1/health` is forwarded to centrifugo as `/centrifugo-sse-1/health` → centrifugo returns `404 page not found`.  
**With `rewrite ... break`**: URI is rewritten to `/health` before `proxy_pass` sends it → centrifugo returns `{}`.

### Why `set $var + rewrite + proxy_pass` triggers dynamic DNS
- Without variables: nginx resolves upstream at config load time, caches forever.
- With `set $var = hostname:port` + `proxy_pass http://$var`: nginx resolves the hostname per the `resolver valid=Ns` interval at request time.

## Debugging Commands Used

```bash
# Check TCP connections from inside nginx-frontend
docker exec fin-trading-cluster-nginx-frontend-1 cat /proc/net/tcp6

# Check which centrifugo container receives connections from nginx-frontend
docker logs fin-trading-cluster-centrifugo-sse-1-1 --since "2026-05-27T14:00:00Z" 2>&1 | grep "172.18.0.7"

# Verify health proxy after fix
curl -k -s "https://localhost:22332/centrifugo-sse-1/health"   # → {}
curl -k -s "https://localhost:22332/centrifugo-sse-0/health"   # → {}

# Test and reload nginx config
docker exec fin-trading-cluster-nginx-frontend-1 nginx -t
docker exec fin-trading-cluster-nginx-frontend-1 nginx -s reload
```

## Prevention
The `resolver 127.0.0.11 valid=10s ipv6=off;` + variable `proxy_pass` pattern should be applied to ALL container hostname upstreams in nginx-frontend.conf to prevent stale DNS after any container restart.
