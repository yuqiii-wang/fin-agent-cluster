#!/bin/bash
set -e

[ ! -f .env ] && echo "Error: .env file not found" && exit 1

# Clear Python cache
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true

# Kill all related processes
taskkill //F //IM ollama.exe >/dev/null 2>&1 || true
taskkill //F //IM node.exe >/dev/null 2>&1 || true
taskkill //F //IM python.exe >/dev/null 2>&1 || true
netstat -ano 2>/dev/null | awk '/:11434.*LISTENING/{print $5}' | tr -d '\r' | xargs -r -I{} taskkill //F //PID {} >/dev/null 2>&1 || true

# Start all processes
ollama serve
ollama create qwen3.5-27b-instruct -f ollama/Modelfile
ollama create qwen3-0.6b-emb -f ollama/Modelfile.embed
ollama run qwen3.5-27b-instruct "ok" >/dev/null
ollama run qwen3-0.6b-emb "hello from startup health check" >/dev/null

cd frontend && npm run dev
cd ..

python run.py
