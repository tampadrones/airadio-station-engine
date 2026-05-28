#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[diag] checking generator connectivity from api container"

if ! docker compose ps api >/dev/null 2>&1; then
  echo "[diag] error: docker compose is not available from this directory" >&2
  exit 2
fi

if ! docker compose ps --status running api | grep -q "api"; then
  echo "[diag] error: api container is not running" >&2
  exit 3
fi

docker compose exec -T api python - <<'PY'
import os
import socket
import sys
from urllib.parse import urlparse

import httpx

env_var = "GENERATOR_BASE_URL"
base_url = (os.getenv(env_var, "") or "").strip()
predict_path = (os.getenv("GENERATOR_PREDICT_PATH", "") or "").strip() or "/gradio_api/call/generation_wrapper"
timeout_sec = int((os.getenv("GENERATOR_TIMEOUT_SECONDS", "10") or "10").strip())

print(f"[diag] {env_var}={base_url}")
print(f"[diag] GENERATOR_PREDICT_PATH={predict_path}")
print(f"[diag] GENERATOR_TIMEOUT_SECONDS={timeout_sec}")

if not base_url:
    print(f"[diag] fail: {env_var} is empty", file=sys.stderr)
    sys.exit(10)

parsed = urlparse(base_url)
host = parsed.hostname
port = parsed.port or (443 if parsed.scheme == "https" else 80)
if not host:
    print("[diag] fail: invalid GENERATOR_BASE_URL", file=sys.stderr)
    sys.exit(11)

try:
    with socket.create_connection((host, port), timeout=5):
        print(f"[diag] tcp ok: {host}:{port}")
except OSError as exc:
    print(f"[diag] fail: tcp connect failed to {host}:{port}: {exc}", file=sys.stderr)
    sys.exit(12)

timeout = max(2, min(timeout_sec, 20))
status_url = base_url.rstrip("/") + "/gradio_api/queue/status"
predict_url = base_url.rstrip("/") + predict_path

try:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        status_resp = client.get(status_url)
        print(f"[diag] GET {status_url} -> {status_resp.status_code}")
        predict_resp = client.get(predict_url)
        print(f"[diag] GET {predict_url} -> {predict_resp.status_code}")
except Exception as exc:
    print(f"[diag] fail: http request error: {exc}", file=sys.stderr)
    sys.exit(13)

if status_resp.status_code // 100 != 2:
    print("[diag] fail: queue status endpoint is not ready", file=sys.stderr)
    sys.exit(14)

if predict_resp.status_code not in (200, 405):
    print("[diag] fail: predict endpoint did not return expected readiness code", file=sys.stderr)
    sys.exit(15)

print("[diag] success: generator connectivity looks healthy")
sys.exit(0)
PY
