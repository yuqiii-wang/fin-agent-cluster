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

    echo "[tls] Generating self-signed TLS certificate for localhost"
    mkdir -p "$cert_dir"
    openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
        -keyout "$key_file" -out "$cert_file" \
        -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
    echo "[tls] Certificate written to $cert_file"

    # If Kong is already running, force-recreate it so it loads the new cert.
    # Kong reads SSL cert/key files only at nginx worker spawn — a running
    # container keeps the old cert until restarted.  The bind-mount
    # (./certs:/certs:ro) ensures the container always sees the latest files,
    # but the process must be cycled to pick them up.
    if docker compose ps --status running kong 2>/dev/null | grep -q "kong"; then
        echo "[tls] Kong is running — restarting to load new certificate..."
        docker compose up -d --force-recreate kong
        echo "[tls] Kong restarted."
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -e
    setup_tls "$@"
fi
