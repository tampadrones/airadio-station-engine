# AI Radio MVP

Self-hosted AI radio with always-on genre stations. Python services remain the station brain; Liquidsoap executes playback and publishes HLS.

## Stack
- API/orchestrator: FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2
- Worker: station scheduler/refill/reconciliation loop (10s)
- Generator adapter: ACE-Step Gradio client (`http://10.0.0.5:7860`)
- DB: Postgres
- Queue/cache: Redis
- Playback backend: Liquidsoap (via swappable playback abstraction)
- Streaming publish: HLS at `/var/lib/ai-radio/hls/{station_slug}/`
- Frontend: Next.js public player + admin/stats

## Playback Boundary
- Python owns: queue/refill, prompt/daypart/mood, anti-repetition, QC, storage lifecycle, fallback eligibility, stats aggregation.
- Playback backend owns: dequeue execution, now-playing truth, HLS publishing, playback sidecar state.

## Quick start
1. `cp .env.example .env`
2. Edit `.env` for your host-specific values.
3. `docker compose up -d --build`
4. Open `http://localhost:8088`
5. API docs `http://localhost:8088/api/docs`

## Recommended State Layout

For migration and operations, prefer bind-mounted state over opaque Docker volumes.

The repo includes:

- `docker-compose.bind.yml`
- `state/README.md`
- `scripts/migrate_docker_volumes_to_state.sh`

To migrate an existing deployment from named volumes into the project tree:

```bash
./scripts/migrate_docker_volumes_to_state.sh
docker compose -f docker-compose.yml -f docker-compose.bind.yml up -d --build
```

After the stack is verified, the old named volumes can be removed.

## Prompt Refinement Topology
- OpenWebUI relay: `http://10.0.0.5:31028`
- Ollama GPU backend: `http://10.0.0.36`
- Set:
  - `PROMPT_REFINER_BASE_URLS=http://10.0.0.5:31028`
  - `PROMPT_REFINER_MODEL=<your model in OpenWebUI>`
- Dedicated lyrics should use the self-hosted OpenWebUI/Ollama path:
  - `LYRICS_REFINER_BASE_URLS=http://10.0.0.5:31028`
  - `LYRICS_REFINER_MODEL=<exact ID from /api/models>`
  - `LYRICS_REFINER_API_KEY=<OpenWebUI token>` or OpenWebUI email/password env vars
- Verify model IDs and auth with `python scripts/check_lyrics_refiner.py`.

## Reprofile Existing Stations
Use `POST /api/stations/reprofile` to update station profiles in place.

Example:
```bash
curl -sS http://localhost/api/stations/reprofile \
  -H 'Content-Type: application/json' \
  -d '{"dry_run":false,"include_inferred_taste_hints":true,"lyrics_mode":"vocal_forward","cohesion_spectrum":85}'
```

## Queue/Playback sidecars
Per station under `/var/lib/ai-radio/playback/stations/{station_slug}/`:
- `queue.m3u`
- `queue.json`
- `fallback.m3u`
- `state.json`
- `now_playing.json`

## Docs
- [Architecture](docs/architecture.md)
- [Setup](docs/setup.md)
- [Env Vars](docs/env-reference.md)
- [Operations](docs/operations.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Streaming](docs/streaming.md)
- [Storage lifecycle](docs/storage-lifecycle.md)
# airadio-station-engine
