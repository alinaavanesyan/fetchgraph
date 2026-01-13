#!/usr/bin/env bash
set -euo pipefail

if [[ $# -gt 0 ]]; then
  echo "This image must run via the bundled entrypoint without extra arguments. Received: $*" >&2
  exit 1
fi

if [[ -n "${WEB_CONCURRENCY:-}" && "${WEB_CONCURRENCY}" != "1" ]]; then
  echo "WEB_CONCURRENCY must be unset or set to 1 for the single-worker runtime" >&2
  exit 1
fi

if [[ -n "${PROMETHEUS_MULTIPROC_DIR:-}" ]]; then
  echo "PROMETHEUS_MULTIPROC_DIR is unsupported; run with a single worker and single-process Prometheus" >&2
  exit 1
fi

if [[ -n "${GUNICORN_CMD_ARGS:-}" ]]; then
  echo "Gunicorn is unsupported for this service; use the bundled uvicorn single-worker runtime" >&2
  exit 1
fi

if [[ -n "${UVICORN_WORKERS:-}" && "${UVICORN_WORKERS}" != "1" ]]; then
  echo "UVICORN_WORKERS must be unset or 1 for the single-worker runtime" >&2
  exit 1
fi

HOST="${LLM_HOST:-0.0.0.0}"
LLM_PORT="${LLM_PORT:-${PORT:-8002}}"
APP_MODULE="${APP_MODULE:-llm.main:app}"

exec uvicorn "$APP_MODULE" --host "$HOST" --port "$LLM_PORT"
