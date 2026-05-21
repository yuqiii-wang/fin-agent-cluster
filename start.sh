#!/bin/bash
set -e

[ ! -f .env ] && echo "Error: .env file not found" && exit 1

# --prod: build the React app and serve it via nginx (no Vite dev server).
# default: start Vite dev server as before.
PROD_MODE=false
for arg in "$@"; do [[ "$arg" == "--prod" ]] && PROD_MODE=true; done

# Clear Python cache

# Kill all related processes
taskkill //F //IM ollama.exe >/dev/null 2>&1 || true
netstat -ano | grep ":3000" | awk '{print $5}' | sort -u | xargs -r -I{} taskkill //F //PID {}
ps -elf | grep python | awk '{print $4}' | xargs kill -9

# Start all processes
ollama serve

# UI Start
netstat -ano 2>/dev/null | awk '/:11434.*LISTENING/{print $5}' | tr -d '\r' | xargs -r -I{} taskkill //F //PID {} >/dev/null 2>&1 || true
if [ "$PROD_MODE" = true ]; then
  # The UI is served from nginx on port 22332; API calls go to nginx-api on 8443.
  # CORS for https://localhost:22332 is allowed in nginx-api.conf.
  cd frontend && VITE_API_URL=https://localhost:8443 npm run build
else
  cd frontend && npm run dev
fi
cd ..

find . \( -type f -name "*.pyc" -o -type d -name __pycache__ \) -exec rm -rf {} + 2>/dev/null || true
python run.py
