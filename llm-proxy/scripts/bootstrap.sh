#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT"

# copy templates on first run
[[ -f .env ]] || cp .env.example .env
[[ -f llm.env ]] || cp llm.env.example llm.env

# create host dirs for bind mounts
mkdir -p ./cache ./logs ./crash_dumps

echo "Bootstrap done."
echo "Next: docker compose --env-file .env up -d --build"
