#!/usr/bin/env bash
# setup/docker_services.sh — Bring up all Docker Compose services.
#
# Usage (standalone):  bash setup/docker_services.sh [--foreground]
# Usage (sourced):     source setup/docker_services.sh && setup_docker_services [--foreground]
#
# Flags:
#   --foreground   Run docker compose in the foreground (no -d).
#                  Default: detached mode (-d).

setup_docker_services() {
    local detach=1
    local sandbox_images=()
    local image=""
    local missing_sandbox_image=0
    for arg in "$@"; do
        case "$arg" in --foreground) detach=0 ;; esac
    done

    docker compose restart centrifugo-llm-0 centrifugo-llm-1 centrifugo-sse-0 centrifugo-sse-1 2>/dev/null || true
    docker compose restart nginx-internal nginx-internal-exporter nginx-frontend 2>/dev/null || true

    while IFS= read -r image; do
        [[ -n "$image" ]] && sandbox_images+=("$image")
    done < <(docker compose config --images | grep 'sandbox-runner' || true)

    for image in "${sandbox_images[@]}"; do
        if ! docker image inspect "$image" >/dev/null 2>&1; then
            missing_sandbox_image=1
            break
        fi
    done

    if [[ ${#sandbox_images[@]} -eq 0 || $missing_sandbox_image -eq 1 ]]; then
        echo "[docker_services] Prebuilding sandbox runner images..."
        docker compose build sandbox-runner-0 sandbox-runner-1
    else
        echo "[docker_services] Sandbox runner images already exist; skipping prebuild."
    fi

    echo "[docker_services] Starting Docker Compose services..."
    if [[ $detach -eq 1 ]]; then
        docker compose up -d
    else
        docker compose up
    fi
    echo "[docker_services] Done."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -e
    setup_docker_services "$@"
fi
