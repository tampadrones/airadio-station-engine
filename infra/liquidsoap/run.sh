#!/bin/sh
set -eu

ROOT="/var/lib/ai-radio"
INCLUDE_FILE="$ROOT/playback/liquidsoap_stations.liq"

mkdir -p "$ROOT/hls" "$ROOT/playback/stations"
until [ -f "$INCLUDE_FILE" ]; do
  sleep 1
done

last_sig=""
child_pid=""

start_liquidsoap() {
  liquidsoap /etc/liquidsoap/radio.liq &
  child_pid=$!
}

stop_liquidsoap() {
  if [ -n "${child_pid}" ] && kill -0 "${child_pid}" 2>/dev/null; then
    kill "${child_pid}" 2>/dev/null || true
    wait "${child_pid}" 2>/dev/null || true
  fi
  child_pid=""
}

current_sig() {
  sha1sum "$INCLUDE_FILE" 2>/dev/null | awk '{print $1}'
}

start_liquidsoap
last_sig="$(current_sig)"

while true; do
  if [ -n "${child_pid}" ] && ! kill -0 "${child_pid}" 2>/dev/null; then
    start_liquidsoap
    last_sig="$(current_sig)"
  fi

  new_sig="$(current_sig)"
  if [ "${new_sig}" != "${last_sig}" ]; then
    stop_liquidsoap
    start_liquidsoap
    last_sig="${new_sig}"
  fi

  sleep 2
done
