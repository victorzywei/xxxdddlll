#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f ".env" ]]; then
  cp .env.example .env
  echo "[scripts/start.sh] Created .env from .env.example"
fi

docker compose up -d --build
