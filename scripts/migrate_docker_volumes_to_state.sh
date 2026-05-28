#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-airadio}"
POSTGRES_VOLUME="${PROJECT_NAME}_postgres_data"
STORAGE_VOLUME="${PROJECT_NAME}_airadio_storage"

STATE_POSTGRES="$ROOT_DIR/state/postgres"
STATE_STORAGE="$ROOT_DIR/state/storage"

echo "Project root: $ROOT_DIR"
echo "Using volumes:"
echo "  - $POSTGRES_VOLUME"
echo "  - $STORAGE_VOLUME"

mkdir -p "$STATE_POSTGRES" "$STATE_STORAGE"

echo
echo "Stopping compose services for a consistent copy..."
docker compose stop

copy_volume() {
  local volume_name="$1"
  local target_dir="$2"

  echo
  echo "Copying $volume_name -> $target_dir"
  docker run --rm \
    -v "${volume_name}:/from:ro" \
    -v "${target_dir}:/to" \
    alpine:3.20 \
    sh -lc 'cd /from && tar cf - . | tar xf - -C /to'
}

copy_volume "$POSTGRES_VOLUME" "$STATE_POSTGRES"
copy_volume "$STORAGE_VOLUME" "$STATE_STORAGE"

echo
echo "State copy complete."
echo "Next start command:"
echo "  docker compose -f docker-compose.yml -f docker-compose.bind.yml up -d --build"
echo
echo "If the stack comes up cleanly, you can later remove the old named volumes:"
echo "  docker volume rm $POSTGRES_VOLUME $STORAGE_VOLUME"
