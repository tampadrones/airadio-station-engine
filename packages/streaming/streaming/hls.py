from __future__ import annotations

import subprocess
from pathlib import Path


def build_station_hls(station_slug: str, track_paths: list[str], hls_root: str) -> str:
    station_dir = Path(hls_root) / station_slug
    station_dir.mkdir(parents=True, exist_ok=True)
    playlist = station_dir / "index.m3u8"
    concat_file = station_dir / "concat.txt"

    valid_paths = [p for p in track_paths if Path(p).exists()]
    if not valid_paths:
        playlist.write_text("#EXTM3U\n#EXT-X-VERSION:3\n")
        return str(playlist)

    concat_file.write_text("\n".join([f"file '{p}'" for p in valid_paths]))
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-f",
        "hls",
        "-hls_time",
        "6",
        "-hls_list_size",
        "10",
        "-hls_flags",
        "delete_segments+append_list+omit_endlist",
        str(playlist),
    ]
    subprocess.run(cmd, check=False)
    return str(playlist)
