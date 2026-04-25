#!/usr/bin/env bash
# setup/tls.sh — Generate self-signed TLS certificate for localhost.
#
# Usage (standalone):  bash setup/tls.sh [--force]
# Usage (sourced):     source setup/tls.sh && setup_tls [--force]
#
# Flags:
#   --force-tls   Regenerate the certificate even if it already exists.
#                 Default: skip if both files are already present.

setup_tls() {
    local force=0
    for arg in "$@"; do
        case "$arg" in --force-tls) force=1 ;; esac
    done

    local cert_dir="certs"
    local cert_file="$cert_dir/localhost.crt"
    local key_file="$cert_dir/localhost.key"

    if [[ $force -eq 0 ]] && [[ -f "$cert_file" ]] && [[ -f "$key_file" ]]; then
        echo "[tls] Certificate already exists — skipping (--force to regenerate)"
        return 0
    fi

    echo "[tls] Generating self-signed TLS certificate for localhost (HTTP/2 SSE port 8889)"
    mkdir -p "$cert_dir"
    openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
        -keyout "$key_file" -out "$cert_file" \
        -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
    echo "[tls] Certificate written to $cert_file"
    echo "[tls] ACTION REQUIRED: visit https://localhost:8889 in your browser and"
    echo "[tls]   accept the cert warning once before using the perf-test panel."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -e
    setup_tls "$@"
fi
