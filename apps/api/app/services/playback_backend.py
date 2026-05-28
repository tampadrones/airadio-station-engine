from __future__ import annotations

from pathlib import Path

from playback.base import PlaybackBackend
from playback.liquidsoap import LiquidsoapPlaybackBackend

from app.core.settings import get_settings


def get_playback_backend() -> PlaybackBackend:
    s = get_settings()
    backend = (getattr(s, "playback_backend", "liquidsoap") or "liquidsoap").lower()
    if backend == "liquidsoap":
        return LiquidsoapPlaybackBackend(
            playback_root=str(Path(s.playback_root) / "stations"),
            hls_root=s.hls_root,
            hls_public_base_url=s.hls_public_base_url,
            control_host=s.liquidsoap_control_host,
            control_port=s.liquidsoap_control_port,
            control_socket_path=s.liquidsoap_control_socket_path,
        )
    raise ValueError(f"Unsupported playback backend: {backend}")
