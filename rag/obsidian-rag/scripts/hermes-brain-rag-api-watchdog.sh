#!/usr/bin/env bash
set -Eeuo pipefail

HEALTH_URL="${HERMES_BRAIN_RAG_HEALTH_URL:-http://127.0.0.1:8000/api/health}"
STATE_DIR="${HERMES_BRAIN_RAG_STATE_DIR:-${HOME}/.hermes/state}"
LOG_DIR="${HERMES_BRAIN_RAG_LOG_DIR:-${HOME}/.hermes/logs}"
FAIL_STAMP="${STATE_DIR}/hermes-brain-rag-watchdog.last_failure"
START_STAMP="${STATE_DIR}/hermes-brain-rag-watchdog.last_start"
PID_FILE="${STATE_DIR}/hermes-brain-rag-api.pid"
FAIL_NOTIFY_SECONDS="${HERMES_BRAIN_RAG_FAIL_NOTIFY_SECONDS:-1800}"

mkdir -p "$STATE_DIR" "$LOG_DIR"

health_check() {
  python3 - "$HEALTH_URL" <<'PY' >/dev/null 2>&1
import sys, urllib.request
urllib.request.urlopen(sys.argv[1], timeout=3).read()
PY
}

find_rag_dir() {
  if [ -n "${HERMES_BRAIN_RAG_DIR:-}" ] && [ -f "${HERMES_BRAIN_RAG_DIR}/docker-compose.yml" ]; then
    printf '%s\n' "$HERMES_BRAIN_RAG_DIR"
    return 0
  fi

  for candidate in \
    "${HOME}/hermes-infra/hermes-related-code/rag/obsidian-rag" \
    "${HOME}/workspace/hermes-related-code/rag/obsidian-rag" \
    "/workspace/hermes-related-code/rag/obsidian-rag"; do
    if [ -f "${candidate}/docker-compose.yml" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  return 1
}

compose_cmd() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    return 127
  fi
}

notify_failure() {
  local message="$1"
  local now last=0
  now="$(date +%s)"
  if [ -f "$FAIL_STAMP" ]; then
    last="$(cat "$FAIL_STAMP" 2>/dev/null || printf '0')"
  fi
  if [ $((now - last)) -ge "$FAIL_NOTIFY_SECONDS" ]; then
    printf '%s\n' "$now" > "$FAIL_STAMP"
    printf 'Hermes Brain RAG API watchdog failed: %s\n' "$message"
  fi
}

wait_for_health() {
  local attempts="${1:-30}"
  local i=1
  while [ "$i" -le "$attempts" ]; do
    if health_check; then
      return 0
    fi
    i=$((i + 1))
    sleep 2
  done
  return 1
}

start_with_compose() {
  local rag_dir="$1"
  cd "$rag_dir"
  compose_cmd -f docker-compose.yml up -d rag-api
}

start_with_local_uvicorn() {
  local rag_dir="$1"
  local python_bin="${HERMES_BRAIN_RAG_PYTHON:-}"
  if [ -z "$python_bin" ]; then
    for candidate in \
      "${HOME}/hermes-infra/.venv/bin/python" \
      "${HOME}/workspace/.venv/bin/python" \
      "/workspace/.venv/bin/python" \
      "$(command -v python3 || true)"; do
      if [ -n "$candidate" ] && [ -x "$candidate" ]; then
        python_bin="$candidate"
        break
      fi
    done
  fi

  if [ -z "$python_bin" ] || [ ! -x "$python_bin" ]; then
    return 127
  fi

  # Detach explicitly so a cron/script runner exiting does not SIGHUP the API.
  nohup bash -c '
    set -Eeuo pipefail
    rag_dir="$1"
    python_bin="$2"
    cd "$rag_dir"
    set -a
    [ -f deep_notes/.env ] && . deep_notes/.env
    set +a
    export API_PORT="${API_PORT:-8000}"
    export QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}"
    export COLLECTION_NAME="${COLLECTION_NAME:-hermes_brain}"
    export EMBED_PROVIDER="${EMBED_PROVIDER:-ollama}"
    export EMBED_MODEL="${EMBED_MODEL:-bge-m3}"
    export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
    exec "$python_bin" -m uvicorn deep_notes.api:app --host 127.0.0.1 --port 8000
  ' _ "$rag_dir" "$python_bin" >> "${LOG_DIR}/hermes-brain-rag-api.log" 2>&1 < /dev/null &
  printf '%s\n' "$!" > "$PID_FILE"
}

main() {
  if health_check; then
    exit 0
  fi

  local rag_dir
  if ! rag_dir="$(find_rag_dir)"; then
    notify_failure "RAG repo directory not found"
    exit 0
  fi

  if compose_cmd version >/dev/null 2>&1; then
    if ! start_with_compose "$rag_dir" >> "${LOG_DIR}/hermes-brain-rag-watchdog.log" 2>&1; then
      notify_failure "docker compose up -d rag-api failed; see ${LOG_DIR}/hermes-brain-rag-watchdog.log"
      exit 0
    fi
    if wait_for_health 20; then
      date +%s > "$START_STAMP"
      printf 'Hermes Brain RAG API started via Docker Compose and is healthy at %s\n' "$HEALTH_URL"
      exit 0
    fi
    notify_failure "docker compose started rag-api, but ${HEALTH_URL} did not become healthy"
    exit 0
  fi

  if start_with_local_uvicorn "$rag_dir"; then
    if wait_for_health 30; then
      date +%s > "$START_STAMP"
      printf 'Hermes Brain RAG API started via local uvicorn fallback and is healthy at %s\n' "$HEALTH_URL"
      exit 0
    fi
    notify_failure "local uvicorn fallback started, but ${HEALTH_URL} did not become healthy"
    exit 0
  fi

  notify_failure "neither docker compose nor a usable Python runtime is available"
}

main "$@"
