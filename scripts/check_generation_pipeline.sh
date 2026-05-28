#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PASS=1

check() {
  local label="$1"
  shift
  echo "[check] $label"
  if "$@"; then
    echo "[pass] $label"
  else
    echo "[fail] $label"
    PASS=0
  fi
}

check "api health" curl -fsS "http://127.0.0.1:8000/api/health"
check "generator health endpoint" curl -fsS "http://127.0.0.1:8000/api/health/generator"
check "generation stats endpoint" curl -fsS "http://127.0.0.1:8000/api/stats/generation"

echo "[check] redis generation keys"
docker compose exec -T redis redis-cli --raw KEYS 'airadio:generation:*' || true

echo "[check] dry-run generation state repair"
./scripts/repair_generation_state.sh || PASS=0

check "ace-step accepts generation_wrapper request from api container" \
  docker compose exec -T api python - <<'PY'
import os, sys, httpx
base = os.getenv("GENERATOR_BASE_URL", "").rstrip("/")
if not base:
    print("GENERATOR_BASE_URL is empty")
    sys.exit(1)
url = f"{base}/gradio_api/call/generation_wrapper"
with httpx.Client(timeout=10.0, follow_redirects=True) as client:
    resp = client.post(url, json={"data": []})
print(f"POST {url} -> {resp.status_code}")
if resp.status_code != 200:
    sys.exit(1)
payload = resp.json()
if not payload.get("event_id"):
    print("missing event_id")
    sys.exit(1)
PY

echo "[check] recent generator/worker logs"
docker compose logs --since=10m api worker | grep -Ei "generator|generation|event_id|queue|error|traceback|failed|stale" || true

if [ "$PASS" -eq 1 ]; then
  echo "[result] generation pipeline checks PASSED"
  exit 0
fi

echo "[result] generation pipeline checks FAILED"
exit 1
