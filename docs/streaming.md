# Streaming (Liquidsoap Backend)

## Current backend
- Playback backend: `LiquidsoapPlaybackBackend` in `packages/playback`.
- Worker exports queue files; Liquidsoap consumes them.

## Station wiring
For each station slug:
- Input: `/var/lib/ai-radio/playback/stations/{slug}/queue.m3u`
- Fallback: `/var/lib/ai-radio/playback/stations/{slug}/fallback.m3u`
- Sidecars: `now_playing.json`, `state.json`
- HLS output: `/var/lib/ai-radio/hls/{slug}/index.m3u8`

## Why this shape
This keeps business logic in Python while isolating playback execution in a swappable backend contract.

## Future custom streamer
Implement `PlaybackBackend` methods:
- `sync_station_queue`
- `get_now_playing`
- `get_stream_url`
- `get_health`
Then switch backend provider without changing scheduler/refill logic.
