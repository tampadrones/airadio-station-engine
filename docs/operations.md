# Operations Guide

## Worker cadence
`WORKER_TICK_SECONDS=10` (default).

Each tick:
1. refill queue if below thresholds
2. export playback queue files
3. reconcile backend now-playing with DB playback state
4. emit ops events for drift/fallback/stream issues

## Playback health APIs
- `GET /api/stats/playback`
- `GET /api/stats/stations` (includes manifest/queue export age, fallback flag)
- `GET /api/stations/{slug}/now-playing` (backend-derived)

## Playback files
`/var/lib/ai-radio/playback/stations/{station_slug}/`
- `queue.m3u` exported by Python
- `fallback.m3u` exported by Python
- `queue.json` exported by Python
- `now_playing.json` written by Liquidsoap
- `state.json` written by Liquidsoap and updated by Python export metadata

## Stream publishing
Liquidsoap writes HLS to `/var/lib/ai-radio/hls/{station_slug}/`. Nginx serves this via `/hls/`.

## Persistence model

The stack can run in either of these modes:

- default: Docker named volumes (`airadio_postgres_data`, `airadio_airadio_storage`)
- consolidated: bind mounts under `./state/` using `docker-compose.bind.yml`

The consolidated mode is recommended for migration, inspection, and backup workflows.
