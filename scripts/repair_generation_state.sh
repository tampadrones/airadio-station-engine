#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

APPLY=0
TTL_MINUTES="${GENERATION_STARTUP_STALE_TRACK_MINUTES:-30}"

for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --ttl-minutes=*) TTL_MINUTES="${arg#*=}" ;;
    *)
      echo "Usage: $0 [--apply] [--ttl-minutes=N]" >&2
      exit 2
      ;;
  esac
done

echo "[repair] mode=$([ "$APPLY" -eq 1 ] && echo apply || echo dry-run) ttl_minutes=$TTL_MINUTES"

if ! docker compose ps postgres redis api >/dev/null 2>&1; then
  echo "[repair] error: docker compose services unavailable in this directory" >&2
  exit 3
fi

echo "[repair] scanning Redis generation-related keys"
mapfile -t REDIS_KEYS_RAW < <(docker compose exec -T redis redis-cli --raw KEYS 'airadio:generation:*' || true)
REDIS_KEYS=()
for k in "${REDIS_KEYS_RAW[@]}"; do
  if [ -n "$k" ]; then
    REDIS_KEYS+=("$k")
  fi
done
echo "[repair] redis_generation_keys_count=${#REDIS_KEYS[@]}"
for k in "${REDIS_KEYS[@]}"; do
  echo "[repair] redis_key=$k"
done

if [ "${#REDIS_KEYS[@]}" -gt 0 ]; then
  echo "[repair] note: redis keys are reported only; script does not delete unknown key shapes."
fi

echo "[repair] scanning DB stale in-flight tracks (status=generating older than ttl)"
docker compose exec -T api python - <<PY
from datetime import datetime, timedelta
from app.db.session import SessionLocal
from app.models.track import Track
from app.models.enums import TrackStatus

ttl = int("${TTL_MINUTES}")
cutoff = datetime.utcnow() - timedelta(minutes=ttl)
db = SessionLocal()
try:
    rows = (
        db.query(Track.id, Track.station_id, Track.title, Track.created_at)
        .filter(Track.status == TrackStatus.generating, Track.created_at < cutoff)
        .order_by(Track.created_at.asc())
        .all()
    )
    print(f"[repair] stale_generating_tracks_count={len(rows)}")
    for rid, sid, title, created in rows[:200]:
        print(f"[repair] stale_track id={rid} station_id={sid} created_at={created} title={title!r}")
finally:
    db.close()
PY

if [ "$APPLY" -eq 0 ]; then
  echo "[repair] dry-run complete; rerun with --apply to mark stale generating tracks as failed."
  exit 0
fi

echo "[repair] applying DB stale in-flight repair"
docker compose exec -T api python - <<PY
from app.db.session import SessionLocal
from app.services.generation_maintenance import mark_stale_generating_tracks

ttl = int("${TTL_MINUTES}")
db = SessionLocal()
try:
    count = mark_stale_generating_tracks(db, max_age_minutes=ttl)
    db.commit()
    print(f"[repair] applied_stale_repairs={count}")
finally:
    db.close()
PY

echo "[repair] apply complete"
