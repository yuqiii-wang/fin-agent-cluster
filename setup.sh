#!/usr/bin/env sh
set -e

# ---------------------------------------------------------------------------
# TLS certificate — enables HTTP/2 on Kong's SSE port 8889.
# HTTP/2 multiplexes all EventSource connections over a single TCP connection,
# removing the browser's hard 6-connection-per-origin limit so bulk launch of
# 10+ streams all open immediately instead of queuing behind the cap.
# The cert is self-signed for localhost/127.0.0.1; Kong presents it on 8889.
# First-time setup: visit https://localhost:8889 in your browser and accept
# the cert warning once (Chrome: "Advanced → Proceed to localhost (unsafe)").
# ---------------------------------------------------------------------------
CERT_DIR="certs"
CERT_FILE="$CERT_DIR/localhost.crt"
KEY_FILE="$CERT_DIR/localhost.key"

if [ ! -f "$CERT_FILE" ] || [ ! -f "$KEY_FILE" ]; then
  echo "[setup] Generating self-signed TLS certificate for localhost (HTTP/2 SSE port 8889)"
  mkdir -p "$CERT_DIR"
  openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
    -keyout "$KEY_FILE" -out "$CERT_FILE" \
    -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
  echo "[setup] Certificate written to $CERT_FILE"
  echo "[setup] ACTION REQUIRED: visit https://localhost:8889 in your browser and"
  echo "[setup]   accept the cert warning once before using the perf-test panel."
fi

# ---------------------------------------------------------------------------
# Frontend .env.local — configure SSE to use Kong's HTTPS+HTTP/2 port 8889.
# HTTP/2 allows unlimited concurrent SSE streams from the browser to Kong
# without hitting the HTTP/1.1 6-connection-per-origin cap.
# ---------------------------------------------------------------------------
if [ ! -f frontend/.env.local ]; then
  echo "[setup] Writing frontend/.env.local (VITE_SSE_URL=https://localhost:8889)"
  printf 'VITE_SSE_URL=https://localhost:8889\n' > frontend/.env.local
fi

python kong-api-gateway/build.py
docker compose up -d
./sql/setup_db_schema.sh

# Start all processes
ollama serve
ollama create qwen3.5-27b-instruct -f ollama/Modelfile
ollama create qwen3-0.6b-emb -f ollama/Modelfile.embed
ollama run qwen3.5-27b-instruct "ok" >/dev/null
ollama run qwen3-0.6b-emb "hello from startup health check" >/dev/null
