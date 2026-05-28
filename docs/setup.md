# Setup

## Prerequisites
- Docker + Docker Compose
- Access to ACE-Step Gradio host (`http://10.0.0.5:7860` by default)
- If using prompt refinement: OpenWebUI relay host (`http://10.0.0.5`) with Ollama backend on `http://10.0.0.36`

## Local run
1. `cp .env.example .env`
2. Edit `.env` for your environment.
3. `docker compose up -d --build`
4. Open `http://localhost:8088`

## Consolidated state mode

The default compose file uses Docker named volumes. For easier backup and migration,
the repo also includes `docker-compose.bind.yml`, which moves persistent state into:

- `./state/postgres`
- `./state/storage`

To migrate an existing stack:

```bash
./scripts/migrate_docker_volumes_to_state.sh
docker compose -f docker-compose.yml -f docker-compose.bind.yml up -d --build
```

For a fresh deployment that should start in consolidated mode, create the folders
and use the override from day one:

```bash
mkdir -p state/postgres state/storage
docker compose -f docker-compose.yml -f docker-compose.bind.yml up -d --build
```

## Services
- `api` FastAPI
- `worker` scheduler/refill/reconcile
- `liquidsoap` playback executor + HLS publisher
- `nginx` reverse proxy + HLS serving

## Key config
- `GENERATOR_BASE_URL`
- `PROMPT_REFINER_BASE_URLS` (example: `http://10.0.0.5`)
- `PROMPT_REFINER_MODEL` (OpenWebUI/Ollama model name)
- `LYRICS_REFINER_BASE_URLS` (example: `http://10.0.0.5`)
- `LYRICS_REFINER_MODEL` (recommended: `qwen2.5` for lyric drafting)
- `PLAYBACK_ROOT=/var/lib/ai-radio/playback`
- `HLS_ROOT=/var/lib/ai-radio/hls`
- `WORKER_TICK_SECONDS=10`
