#!/usr/bin/env sh
set -e
python kong-api-gateway/build.py
docker compose up -d
./sql/setup_db_schema.sh
