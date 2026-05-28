from __future__ import annotations

import asyncio, os
import copy
import hashlib
import json
import logging
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from generator.client import AceStepClient, FailureReason, GenerationRequest, GenerationResult
from observability.metrics import (
    generation_failure_total,
    generation_jobs_active,
    generation_success_total,
    station_buffer_seconds,
    station_failed_generations,
    station_generation_in_progress,
    station_queue_depth,
    station_ready_tracks,
)
from app.core.settings import get_settings
from app.models.audio_asset import AudioAsset
from app.models.enums import Severity, StorageClass, TrackStatus
from app.models.ops_event import OpsEvent
from app.models.station import Station
from app.models.track import Track
from app.models.track_analysis import TrackAnalysis
from app.models.track_feedback import TrackFeedback
from app.models.track_generation import TrackGeneration
from app.models.track_promotion import TrackPromotion
from app.services.anti_repetition import anti_repetition_notes, is_too_similar
from app.services.daypart import get_daypart_blend
from app.services.listeners import should_generate_for_station
from app.services.ops_events import emit_event
from app.services.prompt_builder import build_negative_prompt, build_prompt
from app.services.prompt_preprocessor import preprocess_generation, suggest_track_title
from app.services.qc import analyze_audio
from app.services.station_profile import normalize_station_profile
from app.services.storage import move_to_failed, station_track_dir
from app.services.voice_profiles import choose_voice_profile

logger = logging.getLogger(__name__)


class StationEngine:
    def __init__(self) -> None:
        s = get_settings()
        self.settings = s
        self.client = AceStepClient(
            base_url=s.generator_base_url,
            timeout_seconds=s.generator_timeout_seconds,
            max_retries=s.generator_max_retries,
            backoff_seconds=s.generator_retry_backoff_seconds,
            predict_path=s.generator_predict_path,
        )
        self._generation_slots = asyncio.Semaphore(max(1, int(s.generator_max_concurrent_jobs)))
        self._locks: dict[int, asyncio.Lock] = {}
        self._ace_format_template, self._ace_format_template_path = self._load_ace_format_template()

    @staticmethod
    def _load_ace_format_template() -> tuple[dict | None, str | None]:
        candidates = [
            Path("/workspace/acestep-format.json"),
            Path("/workspace/acestep-format.json"),
            Path.cwd() / "acestep-format.json",
            Path.cwd() / "acestep-format.json",
        ]
        for path in candidates:
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("ace_format_template_invalid_json", extra={"path": str(path)})
                continue
            if not isinstance(payload, dict):
                logger.warning("ace_format_template_not_object", extra={"path": str(path)})
                continue
            required = {"task_type", "instruction", "caption", "lyrics", "duration"}
            missing = sorted([k for k in required if k not in payload])
            if missing:
                logger.warning(
                    "ace_format_template_missing_keys",
                    extra={"path": str(path), "missing": missing},
                )
            logger.info("ace_format_template_loaded", extra={"path": str(path)})
            return payload, str(path)
        logger.warning("ace_format_template_not_found")
        return None, None

    @staticmethod
    def _slug_token(value: str, fallback: str) -> str:
        token = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
        return token[:80] or fallback

    def _mirror_generated_track_for_ace_ui(
        self,
        *,
        station: Station,
        track: Track,
        source_path: Path,
        ace_payload: dict[str, object] | None,
        meta_payload: dict[str, object] | None,
    ) -> Path | None:
        if not bool(self.settings.ace_step_export_enabled):
            return None
        export_root = Path(str(self.settings.ace_step_export_dir or "").strip())
        if not str(export_root):
            return None
        station_token = self._slug_token(station.slug or station.name or "station", "station")
        title_token = self._slug_token(track.title or f"track-{track.id}", f"track-{track.id}")
        station_dir = export_root / station_token
        station_dir.mkdir(parents=True, exist_ok=True)
        # Validate export directory is writable
        if not os.access(export_root, os.W_OK):
            logger.warning("ace_step_export_dir_not_writable", extra={"path": str(export_root)})
            return None
        if not os.access(station_dir, os.W_OK):
            logger.warning("ace_step_station_dir_not_writable", extra={"path": str(station_dir)})
            return None
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        suffix = source_path.suffix if source_path.suffix else ".wav"
        dest = station_dir / f"{stamp}_{int(track.id)}_{title_token}{suffix}"
        shutil.copy2(source_path, dest)
        if ace_payload:
            sidecar = dest.with_suffix(".acestep.json")
            sidecar.write_text(json.dumps(ace_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if meta_payload:
            meta_sidecar = dest.with_suffix(".meta.json")
            meta_sidecar.write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return dest

    def _fit_gate_reason(self, qc) -> str | None:
        min_fit = float(self.settings.station_min_fit_score)
        min_qc = float(self.settings.station_min_qc_score)
        if qc.station_fit_score < min_fit:
            return "station_fit_below_threshold"
        if qc.qc_score < min_qc:
            return "qc_score_below_threshold"
        return None

    @staticmethod
    def _normalize_timesignature(value: object, default: str = "4/4") -> str:
        if isinstance(value, int):
            return f"{value}/4"
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return default
            if "/" in cleaned:
                return cleaned
            if cleaned.isdigit():
                return f"{cleaned}/4"
        return default

    def _normalize_ace_format_payload(self, payload: dict[str, object]) -> dict[str, object]:
        out = copy.deepcopy(payload)
        bpm_raw = out.get("bpm", 120)
        try:
            bpm = int(bpm_raw)  # type: ignore[arg-type]
        except Exception:
            bpm = 120
        out["bpm"] = self._clamp_int(bpm, 60, 220)

        duration_raw = out.get("duration", 200)
        try:
            duration = int(duration_raw)  # type: ignore[arg-type]
        except Exception:
            duration = 200
        out["duration"] = self._clamp_int(duration, 60, 600)

        seed_raw = out.get("seed")
        try:
            if seed_raw is None:
                out["seed"] = int(time.time_ns() % (2**32))
            else:
                out["seed"] = int(seed_raw) % (2**32)
        except Exception:
            out["seed"] = int(time.time_ns() % (2**32))

        out["timesignature"] = self._normalize_timesignature(out.get("timesignature"), default="4/4")
        out["cot_timesignature"] = self._normalize_timesignature(out.get("cot_timesignature"), default=str(out["timesignature"]))

        keyscale = str(out.get("keyscale", "") or "").strip()
        if not keyscale:
            keyscale = str(out.get("cot_keyscale", "") or "").strip() or "C major"
        out["keyscale"] = keyscale
        out["cot_keyscale"] = str(out.get("cot_keyscale", "") or "").strip() or keyscale

        out["cot_bpm"] = int(out.get("cot_bpm") or out["bpm"])
        out["cot_duration"] = int(out.get("cot_duration") or out["duration"])
        out["cot_vocal_language"] = str(out.get("cot_vocal_language") or out.get("vocal_language") or "unknown")

        task_type = str(out.get("task_type") or "").strip().lower()
        lyrics_text = str(out.get("lyrics") or "").strip()
        if task_type == "lyrics2music" and not lyrics_text:
            out["task_type"] = "text2music"
            out["instrumental"] = True
        elif task_type == "text2music" and lyrics_text:
            out["task_type"] = "lyrics2music"
            out["instrumental"] = False

        if not isinstance(out.get("audio_codes"), str):
            out["audio_codes"] = ""
        return out

    def _generation_call_timeout_seconds(self) -> float:
        # Bound the full client.generate wall-clock time so a streaming heartbeat
        # cannot pin a station task forever.
        per_attempt = max(30, int(self.settings.generator_timeout_seconds)) + 20.0
        retries = max(0, int(self.settings.generator_max_retries))
        backoff_total = float(max(0, int(self.settings.generator_retry_backoff_seconds))) * (retries * (retries + 1) / 2.0)
        total = per_attempt * (retries + 1) + backoff_total
        hard_cap = max(60.0, float(getattr(self.settings, "generation_max_wall_clock_seconds", 300)))
        # Enforce a strict upper bound so single-track generation never exceeds
        # the intended operational ceiling.
        return min(hard_cap, max(60.0, total))

    @staticmethod
    def _bpm_range_for_genre(genre: str, daypart: str) -> tuple[int, int]:
        g = (genre or "").lower()
        if "trap" in g or "rap" in g:
            return (132, 156)
        if "synthwave" in g:
            return (96, 122)
        if "lofi" in g or "lo-fi" in g or "chill" in g:
            return (72, 96)
        if "rock" in g or "metal" in g:
            return (108, 150)
        if daypart in {"late_night", "night"}:
            return (82, 112)
        return (92, 132)

    @staticmethod
    def _clamp_int(value: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, int(value)))

    @staticmethod
    def _base_duration_for_genre(genre: str) -> int:
        g = (genre or "").lower()
        if "trap" in g or "rap" in g:
            return 185
        if "synthwave" in g:
            return 205
        if "lofi" in g or "lo-fi" in g or "chill" in g:
            return 220
        if "rock" in g or "metal" in g:
            return 210
        return 200

    def _resolve_target_duration_sec(
        self,
        *,
        genre: str,
        daypart: str,
        mood: str,
        station_profile: dict,
        lyrics_present: bool,
        topic: str,
    ) -> int:
        energy_var = int(station_profile.get("energy_variability", 30))
        mood_vol = int(station_profile.get("mood_volatility", 30))
        vocal_ratio = int(station_profile.get("vocal_ratio", 40))
        lyrics_mode = str(station_profile.get("lyrics_mode", "mixed"))

        base = int(station_profile.get("target_duration_sec", self._base_duration_for_genre(genre)))
        if lyrics_mode == "instrumental_only" or (not lyrics_present and vocal_ratio < 45):
            base -= 8
        elif lyrics_mode == "vocal_forward" or vocal_ratio >= 65:
            base += 12

        mood_offsets = {"baseline": 0, "rise": -8, "peak": -18, "release": 14}
        base += int(mood_offsets.get(str(mood).lower(), 0))
        if daypart in {"late_night", "night"}:
            base += 6

        jitter_cfg = int(station_profile.get("duration_jitter_sec", 12))
        jitter_from_sliders = int(round((energy_var * 0.12) + (mood_vol * 0.08)))
        jitter = self._clamp_int(max(jitter_cfg, jitter_from_sliders), 0, 45)
        digest = hashlib.sha1(f"{datetime.utcnow().isoformat()}|{genre}|{mood}|{topic}".encode("utf-8")).digest()
        offset = (digest[1] % (2 * jitter + 1)) - jitter if jitter > 0 else 0
        target = base + offset

        min_sec = int(station_profile.get("duration_min_sec", 320))
        max_sec = int(station_profile.get("duration_max_sec", 320))
        min_sec = self._clamp_int(min_sec, 120, 320)
        max_sec = self._clamp_int(max_sec, 120, 320)
        if min_sec > max_sec:
            min_sec, max_sec = max_sec, min_sec
        target = self._clamp_int(target, min_sec, max_sec)
        return self._clamp_int(target, 150, 320)

    @staticmethod
    def _pick_keyscale(*, genre: str, mood: str, topic: str) -> str:
        g = (genre or "").lower()
        mood_is_bright = str(mood).lower() in {"rise", "peak"}
        if "trap" in g or "rap" in g:
            pool = ["F minor", "D minor", "G minor", "A minor", "C minor"]
        elif "synthwave" in g:
            pool = ["D major", "A minor", "E minor", "G major", "B minor"]
        elif "lofi" in g or "lo-fi" in g or "chill" in g:
            pool = ["C major", "A minor", "D minor", "F major", "E minor"]
        elif "rock" in g or "metal" in g:
            pool = ["E minor", "A minor", "D minor", "G major", "B minor"]
        else:
            pool = ["D minor", "A minor", "C major", "G major"]
        if mood_is_bright:
            pool = [k for k in pool if "major" in k.lower()] + [k for k in pool if "minor" in k.lower()]
        digest = hashlib.sha1(f"{genre}|{mood}|{topic}".encode("utf-8")).digest()
        return pool[digest[2] % len(pool)]

    @staticmethod
    def _apply_ace_overrides(params: dict[str, object], station_profile: dict) -> dict[str, object]:
        overrides = station_profile.get("ace_overrides", {})
        if not isinstance(overrides, dict):
            return params
        allowed = {
            "bpm",
            "seed",
            "keyscale",
            "time_signature",
            "vocal_language",
            "dit_inference_steps",
            "dit_guidance_scale",
            "use_adg",
            "cfg_interval_start",
            "cfg_interval_end",
            "shift",
            "inference_method",
            "sampler_mode",
            "audio_format",
            "mp3_sample_rate",
            "lm_temperature",
            "lm_cfg_scale",
            "lm_top_k",
            "lm_top_p",
            "enable_normalization",
            "target_peak_db",
            "fade_in_duration",
            "fade_out_duration",
            "latent_shift",
            "latent_rescale",
            "quality_score_sensitivity",
            "autogen",
            "velocity_norm_threshold",
            "velocity_ema_factor",
            "timesteps",
            "repainting_start",
            "repainting_end",
            "chunk_mask_mode",
            "repaint_latent_crossfade_frames",
            "repaint_wav_crossfade_sec",
            "repaint_mode",
            "repaint_strength",
            "audio_cover_strength",
            "cover_noise_strength",
            "thinking",
            "use_cot_metas",
            "use_cot_caption",
            "use_cot_lyrics",
            "use_cot_language",
            "use_constrained_decoding",
            "cot_bpm",
            "cot_keyscale",
            "cot_timesignature",
            "cot_duration",
            "cot_vocal_language",
            "cot_caption",
            "cot_lyrics",
            "lora_loaded",
            "use_lora",
            "lora_scale",
            "lora_weights_hash",
        }
        for k, v in overrides.items():
            key = str(k).strip()
            if not key or key not in allowed:
                continue
            params[key] = v
        return params

    def _build_ace_params(
        self,
        *,
        genre: str,
        daypart: str,
        mood: str,
        station_profile: dict,
        lyrics_present: bool,
        topic: str,
        duration_sec: int,
        fast_mode: bool = False,
    ) -> dict[str, object]:
        cohesion = int(station_profile.get("cohesion_spectrum", 80))
        discovery = int(station_profile.get("discovery_depth", 20))
        mood_vol = int(station_profile.get("mood_volatility", 30))
        energy_var = int(station_profile.get("energy_variability", 30))
        vocal_ratio = int(station_profile.get("vocal_ratio", 40))
        genre_mode = str(station_profile.get("genre_mode", "single_genre"))

        bpm_min, bpm_max = self._bpm_range_for_genre(genre, daypart)
        seed_src = f"{datetime.utcnow().isoformat()}|{genre}|{mood}|{topic}"
        digest = hashlib.sha1(seed_src.encode("utf-8")).digest()
        span = max(1, bpm_max - bpm_min)
        bpm = int(bpm_min + (digest[0] % (span + 1)))

        dit_steps = max(8, min(20, int(round(8 + (cohesion / 18) + (discovery / 42)))))
        dit_guidance = round(max(5.0, min(8.5, 5.6 + (cohesion / 40.0) - (discovery / 100.0))), 2)
        lm_temp = round(max(0.65, min(1.0, 0.68 + (discovery / 210.0) + (mood_vol / 500.0))), 2)
        lm_top_k = int(max(0, min(80, round((discovery - 20) * 0.9))))
        lm_top_p = round(max(0.82, min(0.98, 0.84 + (discovery / 420.0))), 2)
        lm_cfg = round(max(1.6, min(3.2, 1.7 + (cohesion / 90.0))), 2)
        shift = round(max(2.0, min(4.2, 2.6 + (energy_var / 125.0))), 2)
        quality_sensitivity = round(max(0.3, min(0.85, 0.45 + (cohesion / 250.0) - (discovery / 700.0))), 2)
        fade_out = round(max(0.0, min(1.8, 0.2 + (mood_vol / 150.0))), 2)
        cfg_start = round(max(0.0, min(0.25, discovery / 500.0)), 2)
        cfg_end = round(max(0.82, min(1.0, 1.0 - (discovery / 900.0))), 2)
        keyscale = self._pick_keyscale(genre=genre, mood=mood, topic=topic)
        repaint_strength = round(max(0.32, min(0.72, 0.38 + (discovery / 290.0) - (cohesion / 500.0))), 2)
        # ACE-Step accepts conservative|balanced|aggressive.
        repaint_mode = "balanced" if cohesion >= 45 else "aggressive"
        cot_caption = f"{genre} {mood} arrangement, {daypart} vibe, topic {topic}"

        sample_rate = self._clamp_int(int(self.settings.generation_mp3_sample_rate), 16000, 48000)
        mp3_bitrate_kbps = self._clamp_int(int(self.settings.generation_mp3_bitrate_kbps), 64, 320)
        params = {
            "bpm": bpm,
            "keyscale": keyscale,
            "time_signature": "4/4",
            "vocal_language": "en" if lyrics_present else "unknown",
            "dit_inference_steps": dit_steps,
            "dit_guidance_scale": dit_guidance,
            "use_adg": bool(cohesion >= 60),
            "cfg_interval_start": cfg_start,
            "cfg_interval_end": cfg_end,
            "shift": shift,
            "inference_method": "ode",
            "sampler_mode": "euler",
            # Keep ACE-Step generation on WAV for maximum backend compatibility.
            # We can still store MP3 locally by transcoding after download.
            "audio_format": "wav",
            "mp3_bitrate": f"{mp3_bitrate_kbps}k",
            "mp3_sample_rate": sample_rate,
            "lm_temperature": lm_temp,
            "lm_cfg_scale": lm_cfg,
            "lm_top_k": lm_top_k,
            "lm_top_p": lm_top_p,
            "enable_normalization": True,
            "target_peak_db": -1.0,
            "fade_in_duration": 0.0,
            "fade_out_duration": fade_out,
            "latent_shift": 0.0,
            "latent_rescale": round(max(0.9, min(1.2, 1.0 + ((energy_var - 45) / 500.0))), 2),
            "quality_score_sensitivity": quality_sensitivity,
            "autogen": False,
            "velocity_norm_threshold": 0.0,
            "velocity_ema_factor": 0.0,
            "chunk_mask_mode": "auto",
            "repaint_latent_crossfade_frames": int(max(6, min(16, 8 + (cohesion // 18)))),
            "repaint_wav_crossfade_sec": 0.0,
            "repaint_mode": repaint_mode,
            "repaint_strength": repaint_strength,
            "audio_cover_strength": 1.0,
            "cover_noise_strength": 0.0,
            "thinking": bool(cohesion >= 40 or discovery >= 35),
            "use_cot_metas": True,
            "use_cot_caption": bool(genre_mode != "single_genre" or discovery >= 45),
            "use_cot_lyrics": bool(lyrics_present and vocal_ratio >= 25),
            "use_cot_language": bool(lyrics_present),
            "use_constrained_decoding": bool(cohesion >= 50),
            "cot_bpm": bpm,
            "cot_keyscale": keyscale,
            "cot_timesignature": "4/4",
            "cot_duration": int(duration_sec),
            "cot_vocal_language": "en" if lyrics_present else "unknown",
            "cot_caption": cot_caption[:240],
            "cot_lyrics": "",
            "lora_loaded": False,
            "use_lora": False,
            "lora_scale": 1.0,
            "lora_weights_hash": "",
        }
        if fast_mode:
            params["dit_inference_steps"] = 8
            params["dit_guidance_scale"] = round(min(6.0, float(params["dit_guidance_scale"])), 2)
            params["use_adg"] = False
            params["thinking"] = False
            params["use_cot_metas"] = False
            params["use_cot_caption"] = False
            params["use_cot_lyrics"] = False
            params["use_cot_language"] = False
            params["use_constrained_decoding"] = False
            params["repaint_mode"] = "balanced"
            params["repaint_strength"] = round(min(0.30, float(params["repaint_strength"])), 2)
            params["lm_temperature"] = round(min(0.78, float(params["lm_temperature"])), 2)
            params["lm_top_p"] = round(min(0.90, float(params["lm_top_p"])), 2)
        return self._apply_ace_overrides(params, station_profile)

    def _normalized_storage_format(self) -> str:
        raw = str(self.settings.generation_storage_format or "wav").strip().lower()
        if raw in {"mp3", "wav"}:
            return raw
        return "wav"

    def _convert_wav_to_mp3(self, source_wav: Path, target_mp3: Path) -> bool:
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source_wav),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            f"{int(self.settings.generation_mp3_bitrate_kbps)}k",
            "-ar",
            str(int(self.settings.generation_mp3_sample_rate)),
            str(target_mp3),
        ]
        try:
            subprocess.run(cmd, check=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "mp3_transcode_failed",
                extra={"event_type": "mp3_transcode_failed", "details": {"error": str(exc), "source": str(source_wav)}},
            )
            return False
        return target_mp3.exists() and target_mp3.stat().st_size > 0

    @staticmethod
    def _should_use_fast_mode(
        db: Session,
        *,
        station: Station,
        ready_count: int,
        queued_count: int,
    ) -> bool:
        timeout_count = (
            db.query(func.count(OpsEvent.id))
            .filter(
                OpsEvent.station_id == station.id,
                OpsEvent.event_type == "generation_failed",
                OpsEvent.error_code == "timeout",
                OpsEvent.timestamp >= datetime.utcnow() - timedelta(hours=2),
            )
            .scalar()
            or 0
        )
        no_buffer = (ready_count + queued_count) == 0
        min_ready = max(1, int(station.min_ready_tracks or 1))
        low_queue = queued_count < min_ready
        timeout_pressure = timeout_count >= 1 and queued_count < max(2, int(station.target_queue_depth or 2))
        return bool(no_buffer or low_queue or timeout_pressure)

    @staticmethod
    def _feedback_topic_from_generation_or_title(generation: TrackGeneration | None, title: str | None) -> str:
        if generation and isinstance(generation.recent_context, dict):
            pre = generation.recent_context.get("preprocessor", {})
            diagnostics = pre.get("diagnostics", {}) if isinstance(pre, dict) else {}
            topic = str((diagnostics or {}).get("song_topic", "")).strip()
            if topic:
                return topic
        return " ".join(re.findall(r"[A-Za-z0-9']+", title or "")[:4]).strip()

    def _build_feedback_bias(self, db: Session, station: Station) -> dict[str, list[str] | str]:
        rows = (
            db.query(TrackFeedback, Track, TrackGeneration)
            .join(Track, Track.id == TrackFeedback.track_id)
            .outerjoin(TrackGeneration, TrackGeneration.track_id == Track.id)
            .filter(TrackFeedback.station_id == station.id)
            .order_by(TrackFeedback.updated_at.desc())
            .limit(120)
            .all()
        )
        if not rows:
            return {
                "liked_topics": [],
                "disliked_topics": [],
                "liked_hints": [],
                "disliked_hints": [],
                "liked_moods": [],
                "disliked_moods": [],
            }

        liked_topics: dict[str, int] = {}
        disliked_topics: dict[str, int] = {}
        liked_hints: dict[str, int] = {}
        disliked_hints: dict[str, int] = {}
        liked_moods: dict[str, int] = {}
        disliked_moods: dict[str, int] = {}

        for feedback, track, generation in rows:
            vote = int(feedback.vote or 0)
            if vote not in {-1, 1}:
                continue
            topic = self._feedback_topic_from_generation_or_title(generation, track.title).strip()
            mood = str((generation.mood_state if generation else "") or "").strip().lower()

            hint_items: list[str] = []
            if generation:
                if generation.genre:
                    hint_items.append(str(generation.genre).strip())
                if generation.mood_state:
                    hint_items.append(f"{generation.mood_state} mood")
                if isinstance(generation.recent_context, dict):
                    pre = generation.recent_context.get("preprocessor", {})
                    ace_params = pre.get("ace_params", {}) if isinstance(pre, dict) else {}
                    bpm = ace_params.get("bpm") if isinstance(ace_params, dict) else None
                    keyscale = ace_params.get("keyscale") if isinstance(ace_params, dict) else None
                    if isinstance(bpm, int):
                        hint_items.append(f"{bpm} bpm feel")
                    if isinstance(keyscale, str) and keyscale.strip():
                        hint_items.append(f"{keyscale.strip()} tonality")

            target_topics = liked_topics if vote > 0 else disliked_topics
            target_hints = liked_hints if vote > 0 else disliked_hints
            target_moods = liked_moods if vote > 0 else disliked_moods
            if topic:
                target_topics[topic] = target_topics.get(topic, 0) + 1
            for hint in hint_items:
                cleaned = " ".join(hint.split())
                if not cleaned:
                    continue
                target_hints[cleaned] = target_hints.get(cleaned, 0) + 1
            if mood in {"baseline", "rise", "peak", "release"}:
                target_moods[mood] = target_moods.get(mood, 0) + 1

        def top_items(counter: dict[str, int], *, limit: int) -> list[str]:
            items = sorted(counter.items(), key=lambda kv: kv[1], reverse=True)
            return [name for name, _ in items[:limit]]

        return {
            "liked_topics": top_items(liked_topics, limit=5),
            "disliked_topics": top_items(disliked_topics, limit=5),
            "liked_hints": top_items(liked_hints, limit=6),
            "disliked_hints": top_items(disliked_hints, limit=6),
            "liked_moods": top_items(liked_moods, limit=3),
            "disliked_moods": top_items(disliked_moods, limit=3),
        }

    def _build_ace_format_payload(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        lyrics: str | None,
        mood: str,
        topic: str,
        ace_params: dict[str, object],
        duration_sec: int,
    ) -> dict[str, object] | None:
        if not self._ace_format_template:
            return None
        payload = copy.deepcopy(self._ace_format_template)
        if not isinstance(payload, dict):
            return None

        mood_topic_suffix = f" Mood: {mood}. Topic: {topic}."
        payload["caption"] = f"{prompt}{mood_topic_suffix}"
        payload["global_caption"] = ""
        payload["lyrics"] = lyrics or ""
        payload["instrumental"] = not bool((lyrics or "").strip())
        payload["task_type"] = "lyrics2music" if lyrics else "text2music"
        payload["vocal_language"] = str(ace_params.get("vocal_language", "unknown"))
        payload["duration"] = int(duration_sec)
        # Auto-generation should not send template semantic code hints; they are
        # effectively static and make payloads huge without improving variety.
        payload["audio_codes"] = ""
        payload["lm_negative_prompt"] = negative_prompt or ""
        payload["audio_format"] = str(ace_params.get("audio_format", "wav"))
        payload["seed"] = int(ace_params.get("seed", int(time.time_ns() % (2**32))))

        mapped = {
            "bpm": "bpm",
            "keyscale": "keyscale",
            "timesignature": "time_signature",
            "inference_steps": "dit_inference_steps",
            "guidance_scale": "dit_guidance_scale",
            "use_adg": "use_adg",
            "cfg_interval_start": "cfg_interval_start",
            "cfg_interval_end": "cfg_interval_end",
            "shift": "shift",
            "infer_method": "inference_method",
            "sampler_mode": "sampler_mode",
            "lm_temperature": "lm_temperature",
            "lm_cfg_scale": "lm_cfg_scale",
            "lm_top_k": "lm_top_k",
            "lm_top_p": "lm_top_p",
            "enable_normalization": "enable_normalization",
            "normalization_db": "target_peak_db",
            "fade_in_duration": "fade_in_duration",
            "fade_out_duration": "fade_out_duration",
            "latent_shift": "latent_shift",
            "latent_rescale": "latent_rescale",
            "velocity_norm_threshold": "velocity_norm_threshold",
            "velocity_ema_factor": "velocity_ema_factor",
            "timesteps": "timesteps",
            "repainting_start": "repainting_start",
            "repainting_end": "repainting_end",
            "chunk_mask_mode": "chunk_mask_mode",
            "repaint_latent_crossfade_frames": "repaint_latent_crossfade_frames",
            "repaint_wav_crossfade_sec": "repaint_wav_crossfade_sec",
            "repaint_mode": "repaint_mode",
            "repaint_strength": "repaint_strength",
            "audio_cover_strength": "audio_cover_strength",
            "cover_noise_strength": "cover_noise_strength",
            "thinking": "thinking",
            "use_cot_metas": "use_cot_metas",
            "use_cot_caption": "use_cot_caption",
            "use_cot_lyrics": "use_cot_lyrics",
            "use_cot_language": "use_cot_language",
            "use_constrained_decoding": "use_constrained_decoding",
            "cot_bpm": "cot_bpm",
            "cot_keyscale": "cot_keyscale",
            "cot_timesignature": "cot_timesignature",
            "cot_duration": "cot_duration",
            "cot_vocal_language": "cot_vocal_language",
            "cot_caption": "cot_caption",
            "cot_lyrics": "cot_lyrics",
            "lora_loaded": "lora_loaded",
            "use_lora": "use_lora",
            "lora_scale": "lora_scale",
            "lora_weights_hash": "lora_weights_hash",
        }
        for dst, src in mapped.items():
            if src in ace_params:
                payload[dst] = ace_params[src]
        return self._normalize_ace_format_payload(payload)

    @staticmethod
    def _ace_payload_snapshot(payload: dict[str, object] | None) -> dict[str, object] | None:
        if not payload or not isinstance(payload, dict):
            return None
        out: dict[str, object] = {}
        for k, v in payload.items():
            if k == "audio_codes" and isinstance(v, str):
                out[k] = f"<omitted:{len(v)} chars>"
                continue
            out[k] = v
        return out

    async def refill_station_if_needed(
        self,
        db: Session,
        station: Station,
        *,
        station_current_listeners: int | None = None,
        any_active_listeners: bool | None = None,
    ) -> dict:
        lock = self._locks.setdefault(station.id, asyncio.Lock())
        if lock.locked():
            return {"skipped": True, "reason": "generation_in_progress"}

        async with lock:
            self._backfill_legacy_titles(db, station)
            aired_count = db.query(func.count(Track.id)).filter(Track.station_id == station.id, Track.status == TrackStatus.aired).scalar() or 0
            ready_count = db.query(func.count(Track.id)).filter(Track.station_id == station.id, Track.status == TrackStatus.ready).scalar() or 0
            queued_count = db.query(func.count(Track.id)).filter(Track.station_id == station.id, Track.status.in_([TrackStatus.ready, TrackStatus.queued])).scalar() or 0
            generating_count = db.query(func.count(Track.id)).filter(Track.station_id == station.id, Track.status == TrackStatus.generating).scalar() or 0
            buffer_seconds = (
                db.query(func.coalesce(func.sum(Track.duration_sec), 0))
                .filter(Track.station_id == station.id, Track.status.in_([TrackStatus.ready, TrackStatus.queued]))
                .scalar()
                or 0
            )
            station_queue_depth.labels(station.slug).set(queued_count)
            station_ready_tracks.labels(station.slug).set(ready_count)
            station_buffer_seconds.labels(station.slug).set(buffer_seconds)
            station_generation_in_progress.labels(station.slug).set(1 if generating_count > 0 else 0)
            if generating_count > 0:
                return {"skipped": True, "reason": "generation_in_progress_db"}

            activation_refill = False
            activation_cutoff = datetime.utcnow() - timedelta(minutes=max(1, int(self.settings.station_activation_refill_minutes)))
            if (
                station.is_enabled
                and station.created_at
                and station.updated_at
                and station.updated_at >= activation_cutoff
                and station.updated_at > (station.created_at + timedelta(seconds=30))
                and queued_count < max(1, int(station.target_queue_depth))
            ):
                activation_refill = True

            should_generate, reason = should_generate_for_station(
                station.slug,
                ready_tracks=int(ready_count),
                idle_grace_minutes=self.settings.station_idle_grace_minutes,
                idle_min_ready_tracks=self.settings.station_idle_min_ready_tracks,
                station_current_listeners=station_current_listeners,
                any_active_listeners=any_active_listeners,
            )
            if not should_generate and not activation_refill:
                return {"skipped": True, "reason": reason}
            if not should_generate and activation_refill and any_active_listeners:
                return {"skipped": True, "reason": "activation_suppressed_active_elsewhere"}

            idle_bootstrap = reason == "bootstrap_min_ready"
            desired_queue_depth = (
                max(1, int(station.target_queue_depth))
                if activation_refill
                else max(1, int(self.settings.station_idle_min_ready_tracks))
                if idle_bootstrap
                else max(1, int(station.target_queue_depth))
            )
            healthy_reason = "activation_queue_healthy" if activation_refill else ("idle_buffer_healthy" if idle_bootstrap else "queue_healthy")

            if queued_count >= desired_queue_depth:
                return {"skipped": True, "reason": healthy_reason}

            missing = max(desired_queue_depth - queued_count, 1)
            to_generate = min(missing, max(1, self.settings.station_refill_max_generations_per_cycle))
            generated = 0
            failed = 0

            for _ in range(to_generate):
                station_generation_in_progress.labels(station.slug).set(1)
                generation_jobs_active.inc()
                ok = await self._generate_one_track(db, station)
                generation_jobs_active.dec()
                station_generation_in_progress.labels(station.slug).set(0)
                if ok:
                    generated += 1
                else:
                    failed += 1

            return {"generated": generated, "failed": failed}

    @staticmethod
    def _is_legacy_title(title: str | None, station_name: str) -> bool:
        t = (title or "").strip()
        if not t:
            return True
        if t == f"{station_name} Track":
            return True
        if re.match(rf"^{re.escape(station_name)}\s+\d{{2}}:\d{{2}}:\d{{2}}$", t):
            return True
        return False

    @staticmethod
    def _is_low_quality_title(title: str | None, station_name: str) -> bool:
        t = (title or "").strip()
        if not t:
            return True
        low = t.lower()
        tokens = re.findall(r"[a-z0-9']+", low)
        station_tokens = [x.lower() for x in re.findall(r"[A-Za-z0-9']+", station_name)]
        if any(token in low.split() for token in ["custom", "baseline", "track", "station"]):
            return True
        # Token-normalized station-name placeholders (handles punctuation/hyphens).
        if station_tokens and all(tok in tokens for tok in station_tokens):
            if len(tokens) <= len(station_tokens) + 2:
                return True
        # Titles that are mostly station name + one weak token are low-quality.
        if low.startswith(station_name.lower()):
            remaining = low.replace(station_name.lower(), "", 1).strip()
            if remaining in {"", "custom", "baseline", "track"} or len(tokens) <= 4:
                return True
        # "Evening <Station Name>" and similar short placeholders are also low-quality.
        if station_name.lower() in low and len(tokens) <= 4:
            return True
        return False

    def _title_from_generation(self, track_id: int, station_name: str, gen: TrackGeneration) -> str:
        ctx = gen.recent_context if isinstance(gen.recent_context, dict) else {}
        pre = ctx.get("preprocessor", {}) if isinstance(ctx, dict) else {}
        diagnostics = pre.get("diagnostics", {}) if isinstance(pre, dict) else {}
        if isinstance(diagnostics, dict):
            hinted = str(diagnostics.get("suggested_title", "")).strip()
            if hinted and not self._is_low_quality_title(hinted, station_name):
                return " ".join(hinted.split())[:200]
            topic = str(diagnostics.get("song_topic", "")).strip()
        else:
            topic = ""

        if not topic:
            m = re.search(r"\btopic:\s*([^|.]+)", gen.prompt_text or "", flags=re.IGNORECASE)
            if m:
                topic = m.group(1).strip()
        if not topic:
            topic = gen.genre or station_name

        title = suggest_track_title(
            genre=gen.genre or "",
            mood=gen.mood_state or "baseline",
            topic=topic,
            daypart=gen.daypart or "evening",
            personality=gen.personality or station_name,
            salt=f"legacy-{track_id}",
        )
        title = self._enforce_title_quality(
            title=title,
            station_name=station_name,
            genre=gen.genre or "",
            topic=topic,
            salt=f"legacy-{track_id}",
        )
        return " ".join(title.split())[:200] or f"{station_name} Track"

    @staticmethod
    def _topic_from_existing_title(title: str | None, station_name: str) -> str:
        raw = str(title or "").strip()
        if not raw:
            return ""
        parts = re.findall(r"[A-Za-z0-9']+", raw)
        station_parts = {x.lower() for x in re.findall(r"[A-Za-z0-9']+", station_name)}
        banned = {"custom", "baseline", "track", "station", "radio", "song", "music"}
        kept = [p for p in parts if p.lower() not in station_parts and p.lower() not in banned]
        return " ".join(kept[:4]).strip()

    def _title_from_station_fallback(self, track: Track, station: Station) -> str:
        profile = normalize_station_profile(station.station_profile or {})
        topic_ideas = profile.get("topic_ideas", []) if isinstance(profile, dict) else []
        topic = self._topic_from_existing_title(track.title, station.name)
        if not topic and isinstance(topic_ideas, list) and topic_ideas:
            topic = str(topic_ideas[track.id % len(topic_ideas)]).strip()
        if not topic:
            topic = station.genre or station.name
        mood = str(profile.get("mood_seed", "baseline"))
        title = suggest_track_title(
            genre=station.genre or "",
            mood=mood,
            topic=topic,
            daypart="evening",
            personality=station.personality or station.name,
            salt=f"fallback-{track.id}",
        )
        title = self._enforce_title_quality(
            title=title,
            station_name=station.name,
            genre=station.genre or "",
            topic=topic,
            salt=f"fallback-{track.id}",
        )
        return " ".join(title.split())[:200] or f"{station.name} Track"

    def _enforce_title_quality(self, *, title: str, station_name: str, genre: str, topic: str, salt: str) -> str:
        candidate = " ".join((title or "").split()).strip()
        if candidate and not self._is_low_quality_title(candidate, station_name):
            return candidate[:200]

        tokens = [t.title() for t in re.findall(r"[A-Za-z0-9']+", topic or "") if t.lower() not in {"baseline", "custom", "track", "station", "radio", "song", "music"}]
        lead = " ".join(tokens[:2]).strip()
        pool = ["Afterglow", "Ignition", "Velocity", "Arcade", "Neon", "Overdrive", "Rally", "Pulse"]
        g = (genre or "").lower()
        if "rock" in g or "metal" in g:
            pool = ["Voltage", "Afterburn", "Thunderland", "Ironline", "Rally", "Ignition", "Skyfire", "Breakout"]
        elif "trap" in g or "rap" in g:
            pool = ["Respawn", "Overclock", "Bossfight", "Levelup", "Raid", "Checkpoint", "Afterparty", "Speedrun"]
        elif "synthwave" in g:
            pool = ["Neonline", "Afterglow", "Midnight", "Skyline", "Driftline", "Pulse", "Chromeline", "Drive"]
        elif "lofi" in g or "lo-fi" in g:
            pool = ["Windowlight", "Softfocus", "Lowtide", "Nightdesk", "Drift", "Stillframe", "Paperlantern", "Hushline"]

        digest = hashlib.sha1(f"{station_name}|{genre}|{topic}|{salt}".encode("utf-8")).digest()
        a = pool[digest[0] % len(pool)]
        b = pool[digest[1] % len(pool)]
        if not lead:
            lead = a
        forced = f"{lead} {b}".strip()
        if self._is_low_quality_title(forced, station_name):
            forced = f"{a} {b}".strip()
        return forced[:200] or "Untitled Signal"

    @staticmethod
    def _normalize_title_key(title: str | None) -> str:
        raw = " ".join((title or "").split()).strip().lower()
        if not raw:
            return ""
        # Ignore trailing reused suffix variants when checking collisions.
        raw = re.sub(r"(?:\s*\(reused(?:\s*#\d+)?\))+\s*$", "", raw, flags=re.IGNORECASE).strip()
        return raw

    def _ensure_unique_title(
        self,
        *,
        db: Session,
        station: Station,
        base_title: str,
        genre: str,
        mood: str,
        topic: str,
        daypart: str,
        personality: str,
    ) -> str:
        existing_rows = (
            db.query(Track.title)
            .filter(
                Track.station_id == station.id,
                Track.status.in_(
                    [
                        TrackStatus.pending,
                        TrackStatus.generating,
                        TrackStatus.ready,
                        TrackStatus.queued,
                        TrackStatus.aired,
                    ]
                ),
            )
            .order_by(Track.created_at.desc())
            .limit(300)
            .all()
        )
        existing = {self._normalize_title_key(title) for (title,) in existing_rows if title}
        candidate = " ".join((base_title or "").split()).strip()[:200] or f"{station.name} Track"
        if self._normalize_title_key(candidate) not in existing:
            return candidate

        # Retry with varied salts to force a nearby but distinct title.
        for attempt in range(1, 8):
            alt = suggest_track_title(
                genre=genre,
                mood=mood,
                topic=topic,
                daypart=daypart,
                personality=personality,
                salt=f"{datetime.utcnow().isoformat()}|dup|{attempt}",
            )
            alt = self._enforce_title_quality(
                title=alt,
                station_name=station.name,
                genre=genre,
                topic=topic,
                salt=f"dup-{attempt}",
            )
            key = self._normalize_title_key(alt)
            if key and key not in existing:
                return alt[:200]

        # Guaranteed disambiguation fallback.
        suffix = datetime.utcnow().strftime("%H%M")
        final = f"{candidate} {suffix}".strip()
        return final[:200]

    def _backfill_legacy_titles(self, db: Session, station: Station) -> int:
        rows = (
            db.query(Track, TrackGeneration)
            .outerjoin(TrackGeneration, TrackGeneration.track_id == Track.id)
            .filter(
                Track.station_id == station.id,
                Track.status.in_([TrackStatus.ready, TrackStatus.queued, TrackStatus.aired]),
            )
            .order_by(Track.created_at.desc())
            .limit(120)
            .all()
        )
        return self._apply_title_backfill_rows(db=db, station=station, rows=rows)

    def backfill_titles_for_station(self, db: Session, station: Station, *, limit: int = 0) -> dict[str, int]:
        q = (
            db.query(Track, TrackGeneration)
            .outerjoin(TrackGeneration, TrackGeneration.track_id == Track.id)
            .filter(
                Track.station_id == station.id,
                Track.status.in_([TrackStatus.ready, TrackStatus.queued, TrackStatus.aired]),
            )
            .order_by(Track.created_at.desc())
        )
        if limit > 0:
            q = q.limit(limit)
        rows = q.all()
        changed = self._apply_title_backfill_rows(db=db, station=station, rows=rows)
        return {"scanned": len(rows), "updated": changed}

    def _apply_title_backfill_rows(self, db: Session, station: Station, rows: list[tuple[Track, TrackGeneration | None]]) -> int:
        changed = 0
        for track, gen in rows:
            if not (self._is_legacy_title(track.title, station.name) or self._is_low_quality_title(track.title, station.name)):
                continue
            new_title = self._title_from_generation(track.id, station.name, gen) if gen else self._title_from_station_fallback(track, station)
            if new_title and new_title != track.title:
                track.title = new_title
                db.add(track)
                changed += 1
        if changed:
            db.commit()
            emit_event(
                db,
                service="worker",
                event_type="stats_snapshot_written",
                message=f"Backfilled {changed} legacy track title(s)",
                station_id=station.id,
            )
        return changed

    async def _generate_one_track(self, db: Session, station: Station) -> bool:
        s = self.settings
        now = datetime.utcnow()
        blend = get_daypart_blend(now, s.timezone)

        recent = (
            db.query(Track, TrackAnalysis, TrackGeneration)
            .outerjoin(TrackAnalysis, Track.id == TrackAnalysis.track_id)
            .outerjoin(TrackGeneration, TrackGeneration.track_id == Track.id)
            .filter(Track.station_id == station.id)
            .order_by(Track.created_at.desc())
            .limit(3)
            .all()
        )

        recent_ctx = []
        fingerprints = []
        recent_generations = []
        for tr, analysis, generation in recent:
            item = {"title": tr.title}
            if analysis:
                item.update({"bpm": analysis.bpm, "energy_score": analysis.energy_score, "tags": list((analysis.tags or {}).keys())})
                if analysis.similarity_fingerprint:
                    fingerprints.append(analysis.similarity_fingerprint)
            if generation and isinstance(generation.recent_context, dict):
                pre = generation.recent_context.get("preprocessor", {})
                diagnostics = pre.get("diagnostics", {}) if isinstance(pre, dict) else {}
                topic = str((diagnostics or {}).get("song_topic", "")).strip()
                if topic:
                    item["song_topic"] = topic
                voice_profile = diagnostics.get("voice_profile", {}) if isinstance(diagnostics, dict) else {}
                song_brief = diagnostics.get("song_brief", {}) if isinstance(diagnostics, dict) else {}
                recent_generation_item = {"diagnostics": diagnostics}
                if isinstance(voice_profile, dict):
                    voice_id = str(voice_profile.get("id") or "").strip()
                    if voice_id:
                        item["voice_profile_id"] = voice_id
                        recent_generation_item["voice_profile_id"] = voice_id
                if isinstance(song_brief, dict) and song_brief:
                    recent_generation_item["song_brief"] = song_brief
                if len(recent_generation_item) > 1 or isinstance(diagnostics, dict):
                    recent_generations.append(recent_generation_item)
            recent_ctx.append(item)

        profile = normalize_station_profile(station.station_profile or {})
        feedback_bias = self._build_feedback_bias(db, station)
        liked_topics = [str(x).strip() for x in feedback_bias.get("liked_topics", []) if str(x).strip()]
        disliked_topics = [str(x).strip() for x in feedback_bias.get("disliked_topics", []) if str(x).strip()]
        liked_hints = [str(x).strip() for x in feedback_bias.get("liked_hints", []) if str(x).strip()]
        disliked_hints = [str(x).strip() for x in feedback_bias.get("disliked_hints", []) if str(x).strip()]
        liked_moods = [str(x).strip().lower() for x in feedback_bias.get("liked_moods", []) if str(x).strip()]
        disliked_moods = [str(x).strip().lower() for x in feedback_bias.get("disliked_moods", []) if str(x).strip()]

        combined_topics = [*liked_topics, *[str(x) for x in profile.get("topic_ideas", [])]]
        profile["topic_ideas"] = list(dict.fromkeys([x for x in combined_topics if x]))[:8]
        combined_hints = [*liked_hints, *[str(x) for x in profile.get("taste_hints", [])]]
        profile["taste_hints"] = list(dict.fromkeys([x for x in combined_hints if x]))[:8]
        profile = normalize_station_profile(profile)

        mood = str(profile.get("mood_seed", "baseline"))
        if liked_moods and mood.lower() == "baseline":
            mood = liked_moods[0]
        if mood.lower() in set(disliked_moods):
            alternatives = [m for m in ["rise", "peak", "release", "baseline"] if m not in set(disliked_moods)]
            if alternatives:
                mood = alternatives[0]

        recent_for_guidance = list(recent_ctx)
        for topic in disliked_topics[:3]:
            recent_for_guidance.append({"title": f"avoid {topic}", "song_topic": topic})

        anti = anti_repetition_notes(
            recent_ctx,
            cohesion_spectrum=int(profile.get("cohesion_spectrum", 80)),
            discovery_depth=int(profile.get("discovery_depth", 20)),
        )
        voice_profile = choose_voice_profile(
            station.genre,
            profile,
            recent_generations,
            salt=f"{station.id}|{datetime.utcnow().isoformat()}|{len(recent_ctx)}",
        )
        prompt = build_prompt(
            genre=station.genre,
            personality=station.personality,
            daypart=blend.daypart,
            daypart_bias=blend.prompt_bias,
            mood=mood,
            recent_tracks=recent_for_guidance,
            anti_repetition_notes=anti,
            station_profile=profile,
            voice_profile=voice_profile,
        )
        negative_prompt = build_negative_prompt(genre=station.genre, station_profile=profile, voice_profile=voice_profile)
        avoid_terms = [*disliked_topics[:3], *disliked_hints[:3]]
        if avoid_terms:
            negative_prompt = f"{negative_prompt}. Avoid repeating these listener-disliked directions: {', '.join(avoid_terms)}."
        preprocessed = await preprocess_generation(
            settings=s,
            station_name=station.name,
            station_description=station.description,
            genre=station.genre,
            personality=station.personality,
            daypart=blend.daypart,
            mood=mood,
            station_profile=profile,
            base_prompt=prompt,
            negative_prompt=negative_prompt,
            recent_tracks=recent_for_guidance,
            voice_profile=voice_profile,
            recent_generations=recent_generations,
        )
        prompt = preprocessed.prompt
        negative_prompt = preprocessed.negative_prompt
        lyrics = preprocessed.lyrics
        song_topic = str((preprocessed.diagnostics or {}).get("song_topic", "")).strip() or mood
        target_duration_sec = self._resolve_target_duration_sec(
            genre=station.genre,
            daypart=blend.daypart,
            mood=mood,
            station_profile=profile,
            lyrics_present=bool(lyrics),
            topic=song_topic,
        )
        ready_count = db.query(func.count(Track.id)).filter(Track.station_id == station.id, Track.status == TrackStatus.ready).scalar() or 0
        queued_count = (
            db.query(func.count(Track.id))
            .filter(Track.station_id == station.id, Track.status.in_([TrackStatus.ready, TrackStatus.queued]))
            .scalar()
            or 0
        )
        fast_mode = self._should_use_fast_mode(
            db,
            station=station,
            ready_count=ready_count,
            queued_count=queued_count,
        )
        if fast_mode:
            fast_target_raw = profile.get("fast_mode_target_duration_sec")
            if fast_target_raw is not None:
                fast_target = int(fast_target_raw)
                target_duration_sec = self._clamp_int(min(target_duration_sec, fast_target), 120, 320)
        # Keep station duration planning aligned with generator-side safety caps so
        # QC fit scoring is measured against the actual generation target.
        target_duration_sec = self._clamp_int(
            min(target_duration_sec, int(self.settings.generator_safe_max_duration_sec)),
            120,
            320,
        )
        ace_params = self._build_ace_params(
            genre=station.genre,
            daypart=blend.daypart,
            mood=mood,
            station_profile=profile,
            lyrics_present=bool(lyrics),
            topic=song_topic,
            duration_sec=target_duration_sec,
            fast_mode=fast_mode,
        )
        ace_format_payload = self._build_ace_format_payload(
            prompt=prompt,
            negative_prompt=negative_prompt,
            lyrics=lyrics,
            mood=mood,
            topic=song_topic,
            ace_params=ace_params,
            duration_sec=target_duration_sec,
        )
        raw_title = str((preprocessed.diagnostics or {}).get("suggested_title", "")).strip()
        base_title = " ".join(raw_title.split())[:200] if raw_title else f"{station.name} Track"
        track_title = self._ensure_unique_title(
            db=db,
            station=station,
            base_title=base_title,
            genre=station.genre,
            mood=mood,
            topic=song_topic,
            daypart=blend.daypart,
            personality=station.personality,
        )

        track = Track(
            station_id=station.id,
            title=track_title,
            status=TrackStatus.generating,
            storage_class=StorageClass.temp,
        )
        db.add(track)
        db.commit()
        db.refresh(track)

        diagnostics = dict(preprocessed.diagnostics or {})
        diagnostics["target_duration_sec"] = int(target_duration_sec)
        diagnostics["fast_mode"] = bool(fast_mode)
        diagnostics["music_caption"] = preprocessed.music_caption
        diagnostics["technical_parameters"] = preprocessed.technical_parameters or {}
        diagnostics["feedback_bias"] = {
            "liked_topics": liked_topics[:3],
            "disliked_topics": disliked_topics[:3],
            "liked_hints": liked_hints[:3],
            "disliked_hints": disliked_hints[:3],
            "liked_moods": liked_moods[:2],
            "disliked_moods": disliked_moods[:2],
        }
        diagnostics["voice_profile"] = voice_profile
        diagnostics["ace_payload_snapshot"] = self._ace_payload_snapshot(ace_format_payload)
        diagnostics["ace_template_path"] = self._ace_format_template_path or ""

        gen_meta = TrackGeneration(
            track_id=track.id,
            prompt_text=prompt,
            negative_prompt_text=negative_prompt,
            generator_model="ace-step",
            generator_host=s.generator_base_url,
            genre=station.genre,
            personality=station.personality,
            mood_state=mood,
            daypart=blend.daypart,
            recent_context={
                "tracks": recent_ctx,
                "preprocessor": {
                    "source": preprocessed.source,
                    "diagnostics": diagnostics,
                    "lyrics_present": bool(lyrics),
                    "ace_params": ace_params,
                    "ace_format_template_used": bool(ace_format_payload),
                    "ace_format_template_path": self._ace_format_template_path or "",
                },
            },
        )
        db.add(gen_meta)
        db.commit()

        started = datetime.utcnow()
        emit_event(db, service="worker", event_type="generation_started", message="Generation started", station_id=station.id, track_id=track.id)
        logger.info(
            "ace_generation_payload",
            extra={
                "event_type": "generation_payload",
                "details": {
                    "station_slug": station.slug,
                    "track_id": track.id,
                    "payload": diagnostics.get("ace_payload_snapshot"),
                },
            },
        )
        request = GenerationRequest(
            prompt=prompt,
            negative_prompt=negative_prompt,
            lyrics=lyrics,
            duration_sec=int(target_duration_sec),
            ace_params=ace_params,
            ace_format_payload=ace_format_payload,
        )
        wall_clock_timeout = self._generation_call_timeout_seconds()
        try:
            wait_started = time.monotonic()
            async with self._generation_slots:
                queued_wait_ms = int((time.monotonic() - wait_started) * 1000)
                if queued_wait_ms >= 2000:
                    emit_event(
                        db,
                        service="worker",
                        event_type="station_queue_low",
                        message="Generation waited for available generator slot",
                        severity=Severity.info,
                        station_id=station.id,
                        track_id=track.id,
                        details={"wait_ms": queued_wait_ms},
                    )
                result = await asyncio.wait_for(self.client.generate(request), timeout=wall_clock_timeout)
        except TimeoutError:
            result = GenerationResult(
                ok=False,
                failure_reason=FailureReason.timeout,
                error_message="Generator call exceeded wall-clock timeout",
            )

        # ACE-Step can intermittently return internal torch dispatch errors for
        # full-format payloads. Retry once with a minimal request profile before
        # failing the track.
        retry_msg = (result.error_message or "").lower()
        if (
            (not result.ok or not result.audio_url)
            and "linearactivationquantizedtensor dispatch" in retry_msg
        ):
            emit_event(
                db,
                service="worker",
                event_type="generation_retried",
                message="Retrying generation with minimal ACE payload profile",
                severity=Severity.warning,
                station_id=station.id,
                track_id=track.id,
                details={"retry_reason": "linearactivationquantizedtensor_dispatch"},
            )
            retry_request = GenerationRequest(
                prompt=prompt,
                negative_prompt=negative_prompt,
                lyrics=lyrics,
                duration_sec=int(target_duration_sec),
                ace_params=dict(ace_params or {}),
                ace_format_payload=None,
            )
            try:
                wait_started = time.monotonic()
                async with self._generation_slots:
                    queued_wait_ms = int((time.monotonic() - wait_started) * 1000)
                    if queued_wait_ms >= 2000:
                        emit_event(
                            db,
                            service="worker",
                            event_type="station_queue_low",
                            message="Generation retry waited for available generator slot",
                            severity=Severity.info,
                            station_id=station.id,
                            track_id=track.id,
                            details={"wait_ms": queued_wait_ms},
                        )
                    result = await asyncio.wait_for(self.client.generate(retry_request), timeout=wall_clock_timeout)
            except TimeoutError:
                result = GenerationResult(
                    ok=False,
                    failure_reason=FailureReason.timeout,
                    error_message="Generator retry exceeded wall-clock timeout",
                )
            retry_msg = (result.error_message or "").lower()
            if (not result.ok or not result.audio_url) and "linearactivationquantizedtensor dispatch" in retry_msg:
                emit_event(
                    db,
                    service="worker",
                    event_type="generation_retried",
                    message="Retrying generation in text2music fallback mode",
                    severity=Severity.warning,
                    station_id=station.id,
                    track_id=track.id,
                    details={"retry_reason": "linearactivationquantizedtensor_dispatch_text2music_fallback"},
                )
                fallback_ace_params = dict(ace_params or {})
                fallback_ace_params["task_type"] = "text2music"
                fallback_request = GenerationRequest(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    lyrics=None,
                    duration_sec=int(target_duration_sec),
                    ace_params=fallback_ace_params,
                    ace_format_payload=None,
                )
                try:
                    wait_started = time.monotonic()
                    async with self._generation_slots:
                        queued_wait_ms = int((time.monotonic() - wait_started) * 1000)
                        if queued_wait_ms >= 2000:
                            emit_event(
                                db,
                                service="worker",
                                event_type="station_queue_low",
                                message="Generation fallback waited for available generator slot",
                                severity=Severity.info,
                                station_id=station.id,
                                track_id=track.id,
                                details={"wait_ms": queued_wait_ms},
                            )
                        result = await asyncio.wait_for(self.client.generate(fallback_request), timeout=wall_clock_timeout)
                except TimeoutError:
                    result = GenerationResult(
                        ok=False,
                        failure_reason=FailureReason.timeout,
                        error_message="Generator text2music fallback exceeded wall-clock timeout",
                    )

        if not result.ok or not result.audio_url:
            track.status = TrackStatus.failed
            db.commit()
            generation_failure_total.labels(result.failure_reason.value if result.failure_reason else "unknown").inc()
            station_failed_generations.labels(station.slug).inc()
            emit_event(
                db,
                service="worker",
                event_type="generation_failed",
                message=result.error_message or "Generation failed",
                severity=Severity.error,
                station_id=station.id,
                track_id=track.id,
                error_code=result.failure_reason.value if result.failure_reason else "unknown",
                details={
                    "failure_reason": result.failure_reason.value if result.failure_reason else "unknown",
                    "error_message": result.error_message,
                    "wall_clock_timeout_seconds": wall_clock_timeout if result.failure_reason == FailureReason.timeout else None,
                },
            )
            if self._should_fallback_reuse(db, station):
                self._reuse_fallback_track(db, station)
            return False

        out_dir = station_track_dir(station.slug)
        wav_path = out_dir / f"track_{track.id}.wav"
        target_format = self._normalized_storage_format()
        target_path = out_dir / f"track_{track.id}.{target_format}"

        try:
            async with httpx.AsyncClient(timeout=s.generator_timeout_seconds) as client:
                resp = await client.get(result.audio_url)
                resp.raise_for_status()
                wav_path.write_bytes(resp.content)
        except Exception:
            track.status = TrackStatus.failed
            db.commit()
            emit_event(db, service="worker", event_type="generation_failed", message="File write failure", severity=Severity.error, station_id=station.id, track_id=track.id, error_code="file_write_failure")
            return False

        qc = analyze_audio(str(wav_path), target_duration_sec=int(target_duration_sec))
        if is_too_similar(qc.fingerprint, fingerprints):
            track.status = TrackStatus.failed
            db.commit()
            move_to_failed(str(wav_path))
            emit_event(db, service="worker", event_type="track_reuse_blocked", message="Duplicate rejection", severity=Severity.warning, station_id=station.id, track_id=track.id, error_code="duplicate_rejection")
            return False

        if not qc.passed:
            track.status = TrackStatus.failed
            db.commit()
            move_to_failed(str(wav_path))
            generation_failure_total.labels("qc_rejection").inc()
            emit_event(db, service="worker", event_type="qc_failed", message=qc.reason or "QC failed", severity=Severity.warning, station_id=station.id, track_id=track.id, error_code="qc_rejection")
            return False

        fit_reason = self._fit_gate_reason(qc)
        if fit_reason:
            track.status = TrackStatus.failed
            db.commit()
            move_to_failed(str(wav_path))
            generation_failure_total.labels(fit_reason).inc()
            emit_event(
                db,
                service="worker",
                event_type="qc_failed",
                message=f"Rejected by fit gate: {fit_reason}",
                severity=Severity.warning,
                station_id=station.id,
                track_id=track.id,
                error_code=fit_reason,
                details={
                    "station_fit_score": qc.station_fit_score,
                    "qc_score": qc.qc_score,
                    "min_fit_score": float(self.settings.station_min_fit_score),
                    "min_qc_score": float(self.settings.station_min_qc_score),
                },
            )
            return False

        final_path = wav_path
        final_format = "wav"
        final_bitrate_kbps = 1411
        if target_format == "mp3":
            if self._convert_wav_to_mp3(wav_path, target_path):
                final_path = target_path
                final_format = "mp3"
                final_bitrate_kbps = self._clamp_int(int(self.settings.generation_mp3_bitrate_kbps), 64, 320)
                wav_path.unlink(missing_ok=True)
            else:
                emit_event(
                    db,
                    service="worker",
                    event_type="stats_snapshot_written",
                    message="MP3 transcode failed; kept WAV output",
                    severity=Severity.warning,
                    station_id=station.id,
                    track_id=track.id,
                    error_code="mp3_transcode_failed",
                )

        elapsed = (datetime.utcnow() - started).total_seconds()
        gen_meta.generation_seconds = elapsed
        gen_meta.seed = result.seed

        asset = AudioAsset(
            file_path=str(final_path),
            file_size_bytes=final_path.stat().st_size,
            audio_format=final_format,
            sample_rate=int(self.settings.generation_mp3_sample_rate) if final_format == "mp3" else 44100,
            channels=2,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)

        track.status = TrackStatus.ready
        track.storage_class = StorageClass.hot
        track.file_path = str(final_path)
        track.audio_asset_id = asset.id
        track.audio_format = final_format
        track.duration_sec = qc.duration_sec
        track.file_size_bytes = final_path.stat().st_size
        track.sample_rate = int(self.settings.generation_mp3_sample_rate) if final_format == "mp3" else 44100
        track.channels = 2
        track.bitrate_kbps = final_bitrate_kbps
        track.expires_at = datetime.utcnow() + timedelta(hours=s.hot_retention_hours)

        db.add(
            TrackAnalysis(
                track_id=track.id,
                bpm=qc.bpm,
                key_signature="unknown",
                energy_score=qc.energy,
                brightness_score=0.5,
                density_score=0.5,
                vocal_presence_score=0.5,
                station_fit_score=qc.station_fit_score,
                qc_score=qc.qc_score,
                replay_score=qc.replay_score,
                similarity_fingerprint=qc.fingerprint,
                embedding_ref=None,
                tags={"mood": mood, "daypart": blend.daypart},
            )
        )
        db.commit()

        ace_export_payload: dict[str, object] | None = None
        if isinstance(ace_format_payload, dict) and ace_format_payload:
            ace_export_payload = copy.deepcopy(ace_format_payload)
        elif isinstance(ace_params, dict):
            ace_export_payload = {
                "prompt": prompt,
                "negative_prompt": negative_prompt or "",
                "lyrics": lyrics or "",
                "duration": int(target_duration_sec),
                "seed": result.seed,
                "ace_params": dict(ace_params),
            }

        ace_export_meta = {
            "station_slug": station.slug,
            "station_name": station.name,
            "track_id": int(track.id),
            "track_title": track.title,
            "created_at_utc": datetime.utcnow().isoformat() + "Z",
            "generator_host": s.generator_base_url,
            "generator_predict_path": s.generator_predict_path,
            "generation_seconds": elapsed,
            "result_seed": result.seed,
            "qc": {
                "duration_sec": qc.duration_sec,
                "bpm": qc.bpm,
                "energy": qc.energy,
                "qc_score": qc.qc_score,
                "station_fit_score": qc.station_fit_score,
                "replay_score": qc.replay_score,
                "fingerprint": qc.fingerprint,
            },
            "prompt_bundle": {
                "prompt": prompt,
                "music_caption": preprocessed.music_caption,
                "technical_parameters": preprocessed.technical_parameters or {},
                "negative_prompt": negative_prompt or "",
                "lyrics": lyrics or "",
            },
            "ace_params": dict(ace_params),
            "ace_payload_snapshot": diagnostics.get("ace_payload_snapshot") if isinstance(diagnostics, dict) else None,
        }

        mirrored_path: Path | None = None
        try:
            mirrored_path = self._mirror_generated_track_for_ace_ui(
                station=station,
                track=track,
                source_path=final_path,
                ace_payload=ace_export_payload,
                meta_payload=ace_export_meta,
            )
        except Exception as exc:  # noqa: BLE001
            emit_event(
                db,
                service="worker",
                event_type="stats_snapshot_written",
                message="Ace-Step export mirror failed",
                severity=Severity.warning,
                station_id=station.id,
                track_id=track.id,
                error_code="ace_step_export_failed",
                details={"error": str(exc)},
            )
        if mirrored_path:
            emit_event(
                db,
                service="worker",
                event_type="stats_snapshot_written",
                message="Ace-Step export mirror written",
                station_id=station.id,
                track_id=track.id,
                details={
                    "path": str(mirrored_path),
                    "acestep_json_path": str(mirrored_path.with_suffix(".acestep.json")),
                    "meta_json_path": str(mirrored_path.with_suffix(".meta.json")),
                },
            )

        generation_success_total.inc()
        emit_event(
            db,
            service="worker",
            event_type="generation_completed",
            message="Generation completed",
            station_id=station.id,
            track_id=track.id,
            duration_ms=int(elapsed * 1000),
            details={"duration_sec": qc.duration_sec, "qc_score": qc.qc_score, "fit_score": qc.station_fit_score},
        )
        emit_event(db, service="worker", event_type="qc_passed", message="QC passed", station_id=station.id, track_id=track.id)
        return True

    def _should_fallback_reuse(self, db: Session, station: Station) -> bool:
        ready_count = db.query(func.count(Track.id)).filter(Track.station_id == station.id, Track.status == TrackStatus.ready).scalar() or 0
        return ready_count <= 1

    @staticmethod
    def _score_reuse_candidate(
        *,
        track: Track,
        analysis: TrackAnalysis | None,
        generation: TrackGeneration | None,
        promotion: TrackPromotion | None,
        target_daypart: str,
        target_mood: str,
    ) -> float:
        score = 0.0
        title = (track.title or "").lower()
        if "(reused)" in title:
            score -= 4.0
        else:
            score += 1.0

        if analysis:
            score += max(0.0, min(1.0, float(analysis.station_fit_score or 0.0))) * 3.0
            score += max(0.0, min(1.0, float(analysis.qc_score or 0.0))) * 2.0
            score += max(0.0, min(1.0, float(analysis.replay_score or 0.0))) * 2.0
            tags = analysis.tags if isinstance(analysis.tags, dict) else {}
            if str(tags.get("daypart", "")).strip().lower() == target_daypart:
                score += 1.0
            if str(tags.get("mood", "")).strip().lower() == target_mood:
                score += 1.0

        if generation:
            if (generation.daypart or "").strip().lower() == target_daypart:
                score += 0.75
            if (generation.mood_state or "").strip().lower() == target_mood:
                score += 0.75
        if promotion:
            if promotion.promoted_to_library:
                score += 1.0
            if promotion.signature_track:
                score += 1.5
            if promotion.pinned:
                score += 0.5

        aired_at = track.aired_at or track.created_at
        if aired_at:
            age_hours = max(0.0, (datetime.utcnow() - aired_at).total_seconds() / 3600.0)
            score += min(1.5, age_hours / 48.0)
        return score

    @staticmethod
    def _reuse_origin_track_id(track: Track) -> int:
        path = str(track.file_path or "")
        name = Path(path).name
        m = re.match(r"^reused_(\d+)_", name)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return int(track.id)
        return int(track.id)

    def _pick_reuse_candidate(self, db: Session, station: Station) -> Track | None:
        now = datetime.utcnow()
        profile = normalize_station_profile(station.station_profile or {})
        target_mood = str(profile.get("mood_seed", "baseline")).strip().lower() or "baseline"
        target_daypart = get_daypart_blend(now, self.settings.timezone).daypart.strip().lower()
        too_recent_cutoff = now - timedelta(hours=6)

        rows = (
            db.query(Track, TrackAnalysis, TrackGeneration, TrackPromotion)
            .outerjoin(TrackAnalysis, TrackAnalysis.track_id == Track.id)
            .outerjoin(TrackGeneration, TrackGeneration.track_id == Track.id)
            .outerjoin(TrackPromotion, TrackPromotion.track_id == Track.id)
            .filter(
                Track.station_id == station.id,
                Track.status == TrackStatus.aired,
                Track.file_path.is_not(None),
            )
            .order_by(func.coalesce(Track.aired_at, Track.created_at).desc())
            .limit(120)
            .all()
        )
        if not rows:
            return None

        recent_reuse_cutoff = now - timedelta(hours=2)
        recent_rows = (
            db.query(Track)
            .filter(
                Track.station_id == station.id,
                (
                    Track.status.in_([TrackStatus.ready, TrackStatus.queued])
                    | (
                        (Track.status == TrackStatus.aired)
                        & (func.coalesce(Track.aired_at, Track.created_at) >= recent_reuse_cutoff)
                    )
                ),
            )
            .order_by(func.coalesce(Track.aired_at, Track.created_at).desc())
            .limit(max(12, int(station.target_queue_depth) * 3))
            .all()
        )
        blocked_origin_ids = {self._reuse_origin_track_id(t) for t in recent_rows}

        existing_non_reused = any("(reused)" not in (str(t.title or "").lower()) for t, _a, _g, _p in rows)
        scored_unblocked: list[tuple[float, datetime, Track]] = []
        scored_recent_unblocked: list[tuple[float, datetime, Track]] = []
        scored_blocked: list[tuple[float, datetime, Track]] = []
        scored_recent_blocked: list[tuple[float, datetime, Track]] = []

        for track, analysis, generation, promotion in rows:
            if not track.file_path or not Path(track.file_path).exists():
                continue
            if existing_non_reused and "(reused)" in (str(track.title or "").lower()):
                continue

            origin_id = self._reuse_origin_track_id(track)
            aired_at = track.aired_at or track.created_at
            score = self._score_reuse_candidate(
                track=track,
                analysis=analysis,
                generation=generation,
                promotion=promotion,
                target_daypart=target_daypart,
                target_mood=target_mood,
            )
            row = (score, aired_at or datetime.min, track)
            is_blocked = origin_id in blocked_origin_ids
            if aired_at and aired_at >= too_recent_cutoff:
                if is_blocked:
                    scored_recent_blocked.append(row)
                else:
                    scored_recent_unblocked.append(row)
            else:
                if is_blocked:
                    scored_blocked.append(row)
                else:
                    scored_unblocked.append(row)

        scored = scored_unblocked or scored_recent_unblocked or scored_blocked or scored_recent_blocked
        if not scored:
            return None
        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return scored[0][2]

    def _reuse_fallback_track(self, db: Session, station: Station) -> None:
        candidate = self._pick_reuse_candidate(db, station)
        if candidate:
            if not candidate.file_path or not Path(candidate.file_path).exists():
                return
            candidate_origin_id = self._reuse_origin_track_id(candidate)
            active_rows = (
                db.query(Track)
                .filter(
                    Track.station_id == station.id,
                    Track.status.in_([TrackStatus.ready, TrackStatus.queued]),
                    Track.file_path.is_not(None),
                )
                .order_by(Track.created_at.desc())
                .limit(32)
                .all()
            )
            active_origin_ids = {self._reuse_origin_track_id(t) for t in active_rows}
            if candidate_origin_id in active_origin_ids:
                emit_event(
                    db,
                    service="worker",
                    event_type="track_reuse_blocked",
                    message="Skipped fallback reuse due to active queue duplicate",
                    severity=Severity.info,
                    station_id=station.id,
                    track_id=candidate.id,
                    details={"origin_track_id": candidate_origin_id},
                )
                return
            suffix = Path(str(candidate.file_path or "")).suffix or ".wav"
            copied_path = station_track_dir(station.slug) / f"reused_{candidate.id}_{time.time_ns()}{suffix}"
            shutil.copy2(candidate.file_path, copied_path)
            asset = AudioAsset(
                file_path=str(copied_path),
                file_size_bytes=copied_path.stat().st_size,
                audio_format=candidate.audio_format,
                sample_rate=candidate.sample_rate,
                channels=candidate.channels,
            )
            db.add(asset)
            db.commit()
            db.refresh(asset)
            reuse_title = self._build_reuse_title(candidate.title)
            clone = Track(
                station_id=station.id,
                audio_asset_id=asset.id,
                title=reuse_title,
                status=TrackStatus.ready,
                storage_class=StorageClass.hot,
                duration_sec=candidate.duration_sec,
                audio_format=candidate.audio_format,
                bitrate_kbps=candidate.bitrate_kbps,
                sample_rate=candidate.sample_rate,
                channels=candidate.channels,
                file_path=str(copied_path),
                file_size_bytes=copied_path.stat().st_size,
            )
            db.add(clone)
            db.commit()
            emit_event(db, service="worker", event_type="track_reused", message="Emergency fallback reuse", severity=Severity.warning, station_id=station.id, track_id=clone.id)

    @staticmethod
    def _build_reuse_title(candidate_title: str | None) -> str:
        raw = (candidate_title or "").strip() or "Recovered Track"
        # Prevent "(reused) (reused) ..." growth across fallback chains.
        base = re.sub(r"(?:\s*\(reused(?:\s*#\d+)?\))+\s*$", "", raw, flags=re.IGNORECASE).strip() or "Recovered Track"
        suffix = " (reused)"
        max_base_len = max(1, 200 - len(suffix))
        return f"{base[:max_base_len].rstrip()}{suffix}"
