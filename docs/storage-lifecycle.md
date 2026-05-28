# Storage Lifecycle

## Layout
`/var/lib/ai-radio/`
- `hot/stations/{station_slug}/tracks`
- `hot/hls/{station_slug}`
- `warm/library/{station_slug}`
- `warm/signature`
- `cold/previews`, `cold/manifests`, `cold/exports`
- `temp`
- `failed`
- `playback/stations/{station_slug}` (queue/state sidecars)

## Retention defaults
- Hot non-promoted aired tracks: 48h
- Warm promoted tracks: 90-180d (default 120)
- Previews: 90d+
- Metadata: long-term in DB

## Eviction order
1. failed generations
2. aired low-score tracks
3. old non-promoted tracks
4. near-duplicates
5. low-replay warm tracks

## Jobs
- Periodic cleanup job (default every 5 minutes via `STORAGE_CLEANUP_INTERVAL_SECONDS`)
- Nightly reconciliation for orphan files and DB/file drift
- Quota checks produce `storage_quota_warning` events

## Cap behavior
- `GENERATED_STORAGE_CAP_GB` enforces a global generated-media cap (default 10GB).
- Cap accounting includes `hot`, `warm`, `cold`, `temp`, `failed`, and (by default) `ACE_STEP_EXPORT_DIR`.
- Oldest-first eviction path:
1. prune oldest files from `ACE_STEP_EXPORT_DIR` mirror cache
2. mark oldest aired/failed tracks as deleted and detach media refs
3. delete detached deleted-track files
