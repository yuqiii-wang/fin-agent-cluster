#!/usr/bin/env bash
# setup/ollama_models.sh — Ensure Ollama is running and required models are loaded.
#
# Usage (standalone):  bash setup/ollama_models.sh [--skip]
# Usage (sourced):     source setup/ollama_models.sh && setup_ollama_models [--skip]
#
# Flags:
#   --skip-ollama   Do nothing and return immediately.
#                  Default: start ollama and create/warm the required models.

setup_ollama_models() {
    local skip=0
    for arg in "$@"; do
        case "$arg" in --skip-ollama) skip=1 ;; esac
    done

    if [[ $skip -eq 1 ]]; then
        echo "[ollama_models] --skip set — skipping Ollama setup"
        return 0
    fi

    if ! pgrep -x ollama >/dev/null 2>&1; then
        echo "[ollama_models] Starting Ollama..."
        ollama serve
    else
        echo "[ollama_models] Ollama already running — skipping serve"
    fi

    echo "[ollama_models] Creating models..."
    ollama create qwen3.5-27b-instruct -f ollama/Modelfile
    ollama create qwen3-0.6b-emb -f ollama/Modelfile.embed

    echo "[ollama_models] Warming up models..."
    ollama run qwen3.5-27b-instruct "ok" >/dev/null
    ollama run qwen3-0.6b-emb "hello from startup health check" >/dev/null

    echo "[ollama_models] Done."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -e
    setup_ollama_models "$@"
fi
