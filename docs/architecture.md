# Architecture

## Core services
- `apps/api`: station/admin/stats/log APIs.
- `apps/worker`: queue refill + playback reconciliation + storage jobs.
- `packages/generator`: ACE-Step adapter with retries/timeouts/failure classification.
- `packages/playback`: pluggable playback backend interface; current implementation is Liquidsoap file sidecar integration.
- `packages/observability`: metrics registry.

## B-now / C-later boundary
### B-now (implemented)
- Python computes and exports ordered playable queues.
- Liquidsoap consumes exported queues and publishes HLS.
- Worker reconciles backend now-playing into DB truth (`station_playback_state`).

### C-later (planned)
- Custom streamer backend implementing `PlaybackBackend` without changing scheduler or business logic.

## Data flow
1. Worker checks queue depth, refills when low.
2. Tracks pass QC and become ready.
3. Worker exports queue/fallback sidecars to playback root.
4. Liquidsoap plays queue, writes `now_playing.json` / `state.json`, emits HLS.
5. Worker reconciles backend state into DB, marks track play transitions, creates play events.
