# Troubleshooting

## Queue starvation
- Check `/api/stats/stations` queue depth and buffer metrics.
- Verify queue export age in `/api/stats/playback`.

## Generator timeout
- `generation_failed` with `error_code=timeout` in `/api/logs`.
- Increase `GENERATOR_TIMEOUT_SECONDS` or fix network path to generator.
- Run `./scripts/check_generator_connectivity.sh` to verify `GENERATOR_BASE_URL`, TCP connectivity, and Gradio readiness from the `api` container.

## Playback drift (backend vs DB)
- Symptom: `stream_error` with `backend_db_drift`.
- Check station `now_playing.json` and DB `station_playback_state`.
- Confirm exported `queue.json` track IDs and titles align with backend metadata.

## Fallback active too often
- Inspect `fallback_active` in `/api/stats/playback`.
- Raise target queue depth and reduce generator failures.

## Missing HLS segments
- Check Liquidsoap container logs.
- Verify `/var/lib/ai-radio/hls/{station_slug}` updates and nginx alias path.

## Storage cleanup deleting needed files
- Current safety skips deletion if file path is still referenced by ready/queued/generating/current playback tracks.
- Verify duplicate file-path references and status transitions in DB.
