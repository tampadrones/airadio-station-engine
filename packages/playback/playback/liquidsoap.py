from __future__ import annotations

import json
import os
import socket
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .base import PlaybackBackend
from .schemas import NowPlaying, PlaybackHealth, PlaybackTrack


class LiquidsoapPlaybackBackend(PlaybackBackend):
    def __init__(
        self,
        playback_root: str = "/var/lib/ai-radio/playback/stations",
        hls_root: str = "/var/lib/ai-radio/hls",
        hls_public_base_url: str = "http://localhost/hls",
        control_host: str = "liquidsoap",
        control_port: int = 1234,
        control_socket_path: str | None = "/var/lib/ai-radio/playback/liquidsoap.sock",
    ) -> None:
        self.playback_root = Path(playback_root)
        self.hls_root = Path(hls_root)
        self.hls_public_base_url = hls_public_base_url.rstrip("/")
        self.control_host = control_host
        self.control_port = int(control_port)
        self.control_socket_path = control_socket_path

    def sync_station_queue(self, station_slug: str, tracks: list[PlaybackTrack]) -> None:
        station_dir = self.playback_root / station_slug
        station_dir.mkdir(parents=True, exist_ok=True)
        (self.hls_root / station_slug).mkdir(parents=True, exist_ok=True)

        queue_m3u = station_dir / "queue.m3u"
        queue_json = station_dir / "queue.json"
        fallback_m3u = station_dir / "fallback.m3u"
        state_json = station_dir / "state.json"

        m3u_lines = ["#EXTM3U"]
        for t in tracks:
            encoded_title = f"[track_id={t.track_id}] {t.title}"
            m3u_lines.append(f"#EXTINF:{t.duration_sec or -1},{encoded_title}")
            m3u_lines.append(t.file_path)
        self._write_if_changed(queue_m3u, "\n".join(m3u_lines) + "\n")

        queue_json.write_text(
            json.dumps(
                {
                    "station_slug": station_slug,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "tracks": [asdict(t) for t in tracks],
                },
                indent=2,
            )
        )

        # Keep a short resilient fallback chain from the latest queueable tracks.
        fallback_lines = ["#EXTM3U"]
        for t in tracks[:4]:
            fallback_lines.append(f"#EXTINF:{t.duration_sec or -1},{t.title}")
            fallback_lines.append(t.file_path)
        self._write_if_changed(fallback_m3u, "\n".join(fallback_lines) + "\n")

        state = self._load_json(state_json)
        state.update(
            {
                "station_slug": station_slug,
                "playback_backend": "liquidsoap",
                "queue_exported_at": datetime.now(timezone.utc).isoformat(),
                "queue_size": len(tracks),
                "manifest_path": str(self.hls_root / station_slug / "index.m3u8"),
            }
        )
        state_json.write_text(json.dumps(state, indent=2))

    def get_now_playing(self, station_slug: str) -> NowPlaying:
        station_dir = self.playback_root / station_slug
        now_file = station_dir / "now_playing.json"
        payload = self._load_json(now_file)
        started = self._parse_dt(payload.get("started_at"))
        track_id = self._to_int(payload.get("track_id"))
        raw_title = self._to_str(payload.get("title"))
        parsed_track_id, cleaned_title = self._extract_track_info(raw_title)
        return NowPlaying(
            station_slug=station_slug,
            track_id=track_id or parsed_track_id,
            title=cleaned_title or raw_title,
            started_at=started,
            position_sec=self._to_int(payload.get("position_sec")),
            fallback_active=bool(payload.get("fallback_active", False)),
        )

    def get_stream_url(self, station_slug: str) -> str:
        return f"/hls/{station_slug}/index.m3u8"

    def get_health(self, station_slug: str) -> PlaybackHealth:
        station_dir = self.playback_root / station_slug
        state_file = station_dir / "state.json"
        queue_file = station_dir / "queue.m3u"
        state = self._load_json(state_file)

        manifest_path = state.get("manifest_path")
        manifest_age = self._manifest_age_seconds(station_slug, manifest_path if isinstance(manifest_path, str) else None)
        queue_age = self._age_seconds(queue_file)

        # Queue files can remain unchanged while playback is healthy.
        # Treat fresh manifests as the primary liveness signal.
        alive = (manifest_age is not None and manifest_age < 30) or (queue_age is not None and queue_age < 120)
        return PlaybackHealth(
            station_slug=station_slug,
            backend="liquidsoap",
            alive=alive,
            manifest_path=manifest_path if isinstance(manifest_path, str) else None,
            manifest_age_seconds=manifest_age,
            queue_export_age_seconds=queue_age,
            fallback_active=bool(state.get("fallback_active", False)),
            drift_count=int(state.get("drift_count", 0) or 0),
        )

    def skip_current(self, station_slug: str) -> None:
        command = f"/var/lib/ai-radio/hls/{station_slug}/index_m3u8.skip\n"
        response = self._send_control_command(command)
        if "Done" not in response and "OK" not in response:
            response = self._send_control_command(f"{station_slug}.skip\n")
        if "Done" not in response and "OK" not in response:
            raise RuntimeError(f"Unexpected liquidsoap response: {response.strip() or '<empty>'}")

    def _send_control_command(self, command: str) -> str:
        last_error: Exception | None = None
        if self.control_socket_path and os.path.exists(self.control_socket_path):
            try:
                return self._send_unix_command(command)
            except OSError as exc:
                last_error = exc
        try:
            return self._send_tcp_command(command)
        except OSError as exc:
            if last_error is not None:
                raise RuntimeError(
                    f"Liquidsoap control failed via socket and tcp: {last_error}; {exc}"
                ) from exc
            raise

    def _send_tcp_command(self, command: str) -> str:
        with socket.create_connection((self.control_host, self.control_port), timeout=5.0) as sock:
            return self._exchange_command(sock, command)

    def _send_unix_command(self, command: str) -> str:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(5.0)
            sock.connect(self.control_socket_path or "")
            return self._exchange_command(sock, command)

    @staticmethod
    def _exchange_command(sock: socket.socket, command: str) -> str:
        sock.settimeout(0.2)
        try:
            sock.recv(4096)
        except (TimeoutError, socket.timeout):
            pass
        sock.settimeout(5.0)
        sock.sendall(command.encode("utf-8"))
        response = sock.recv(4096).decode("utf-8", errors="ignore")
        try:
            sock.sendall(b"quit\n")
        except OSError:
            pass
        return response

    @staticmethod
    def _load_json(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _parse_dt(raw: object) -> datetime | None:
        if not isinstance(raw, str):
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _to_int(raw: object) -> int | None:
        try:
            if raw is None:
                return None
            return int(raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_str(raw: object) -> str | None:
        return raw if isinstance(raw, str) else None

    @staticmethod
    def _age_seconds(path: Path) -> int | None:
        if not path.exists():
            return None
        return int((datetime.now(timezone.utc).timestamp()) - path.stat().st_mtime)

    def _manifest_age_seconds(self, station_slug: str, manifest_path: str | None) -> int | None:
        ages: list[int] = []
        if manifest_path:
            age = self._age_seconds(Path(manifest_path))
            if age is not None:
                ages.append(age)
        media_manifest = self.hls_root / station_slug / "audio.m3u8"
        media_age = self._age_seconds(media_manifest)
        if media_age is not None:
            ages.append(media_age)
        if not ages:
            return None
        return min(ages)

    @staticmethod
    def _extract_track_info(title: str | None) -> tuple[int | None, str | None]:
        if not title:
            return None, None
        if not title.startswith("[track_id="):
            return None, title
        end = title.find("]")
        if end == -1:
            return None, title
        token = title[len("[track_id="):end]
        try:
            tid = int(token)
        except ValueError:
            return None, title
        cleaned = title[end + 1 :].strip()
        return tid, cleaned

    @staticmethod
    def _write_if_changed(path: Path, content: str) -> None:
        if path.exists():
            try:
                if path.read_text() == content:
                    return
            except OSError:
                pass
        path.write_text(content)
