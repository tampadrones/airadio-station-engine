#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/apox/airadio"
LOG_DIR="$ROOT/state"
LOG_FILE="$LOG_DIR/boot-health.log"

mkdir -p "$LOG_DIR"

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"
}

api_ok() {
  curl -m 8 -fsS "http://127.0.0.1:8000/api/stats/stations" >/dev/null
}

web_ok() {
  curl -m 8 -fsS "http://127.0.0.1:3001" >/dev/null
}

proxy_ok() {
  curl -m 8 -fsS "http://127.0.0.1:8088" >/dev/null
}

docker_ok() {
  docker info >/dev/null 2>&1
}

ensure_docker() {
  if docker_ok; then
    return 0
  fi

  log "[boot-health] docker daemon unavailable; attempting startup"

  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    systemctl start docker >>"$LOG_FILE" 2>&1 || true
  elif command -v sudo >/dev/null 2>&1; then
    sudo -n systemctl start docker >>"$LOG_FILE" 2>&1 || true
  fi

  for _ in $(seq 1 20); do
    if docker_ok; then
      log "[boot-health] docker daemon reachable"
      return 0
    fi
    sleep 1
  done

  log "[boot-health] docker daemon still unavailable"
  return 1
}

log "[boot-health] starting"
sleep 25

cd "$ROOT"
ensure_docker || exit 1
docker compose up -d postgres redis api worker web liquidsoap nginx >>"$LOG_FILE" 2>&1 || true

for attempt in $(seq 1 10); do
  if api_ok && web_ok && proxy_ok; then
    log "[boot-health] healthy on attempt $attempt"
    exit 0
  fi

  log "[boot-health] unhealthy on attempt $attempt; applying recovery"
  ensure_docker || exit 1
  docker compose ps >>"$LOG_FILE" 2>&1 || true

  if [[ "$attempt" -eq 2 || "$attempt" -eq 6 ]]; then
    docker compose up -d postgres redis api worker >>"$LOG_FILE" 2>&1 || true
  fi
  if [[ "$attempt" -eq 3 || "$attempt" -eq 7 ]]; then
    docker compose up -d --force-recreate web nginx >>"$LOG_FILE" 2>&1 || true
  fi
  if [[ "$attempt" -eq 4 || "$attempt" -eq 8 ]]; then
    docker compose restart api worker web nginx >>"$LOG_FILE" 2>&1 || true
  fi

  sleep 15
done

log "[boot-health] failed to restore healthy state after retries"
exit 1
