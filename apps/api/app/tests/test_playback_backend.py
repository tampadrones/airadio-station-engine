from pathlib import Path

from playback.liquidsoap import LiquidsoapPlaybackBackend
from playback.schemas import PlaybackTrack


def test_sync_station_queue_writes_files(tmp_path: Path):
    backend = LiquidsoapPlaybackBackend(
        playback_root=str(tmp_path / "playback" / "stations"),
        hls_root=str(tmp_path / "hls"),
        hls_public_base_url="http://localhost/hls",
    )
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    backend.sync_station_queue(
        "synthwave-fm",
        [PlaybackTrack(track_id=1, title="Track A", file_path=str(audio), duration_sec=200)],
    )

    station_dir = tmp_path / "playback" / "stations" / "synthwave-fm"
    assert (station_dir / "queue.m3u").exists()
    assert (station_dir / "queue.json").exists()
    assert (station_dir / "fallback.m3u").exists()
    assert (station_dir / "state.json").exists()
