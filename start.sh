#!/bin/bash
set -e

[ ! -f .env ] && echo "Error: .env file not found" && exit 1

# Clear Python cache
find . \( -type f -name "*.pyc" -o -type d -name __pycache__ \) -exec rm -rf {} + 2>/dev/null || true

# Kill all related processes
taskkill //F //IM ollama.exe >/dev/null 2>&1 || true
taskkill //F //IM node.exe >/dev/null 2>&1 || true
taskkill //F //IM python.exe >/dev/null 2>&1 || true
netstat -ano 2>/dev/null | awk '/:11434.*LISTENING/{print $5}' | tr -d '\r' | xargs -r -I{} taskkill //F //PID {} >/dev/null 2>&1 || true

# Start all processes
ollama serve

cd frontend && npm run dev
cd ..

python run.py
