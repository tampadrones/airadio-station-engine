from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf


@dataclass
class QCResult:
    passed: bool
    reason: str | None
    duration_sec: int
    loudness: float
    bpm: float
    energy: float
    qc_score: float
    station_fit_score: float
    replay_score: float
    fingerprint: str


def analyze_audio(path: str, target_duration_sec: int = 320) -> QCResult:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return QCResult(False, "empty_audio", 0, -99, 0, 0, 0, 0, 0, "")

    data, sr = sf.read(path)
    if data.ndim > 1:
        mono = data.mean(axis=1)
    else:
        mono = data
    duration = int(len(mono) / sr)
    rms = float(np.sqrt(np.mean(np.square(mono))) + 1e-9)
    loudness = 20 * np.log10(rms)
    silence_ratio = float(np.mean(np.abs(mono) < 1e-4))
    clipped_ratio = float(np.mean(np.abs(mono) > 0.999))

    # Lightweight BPM proxy via zero-crossing density.
    zcr = float(((mono[:-1] * mono[1:]) < 0).mean())
    bpm = max(60.0, min(180.0, 60 + zcr * 500))
    energy = float(min(1.0, max(0.0, rms * 4)))

    duration_ok = 150 <= duration <= 320
    silent = silence_ratio > 0.4
    clipped = clipped_ratio > 0.03

    qc_score = max(0.0, min(1.0, 1.0 - (0.4 if silent else 0) - (0.3 if clipped else 0) - min(abs(duration - target_duration_sec) / 400, 0.3)))
    station_fit = max(0.0, min(1.0, 1.0 - abs(duration - target_duration_sec) / 200 - abs(energy - 0.6) * 0.5))
    replay = max(0.0, min(1.0, qc_score * 0.7 + station_fit * 0.3))

    digest = hashlib.sha1(np.round(mono[: min(len(mono), sr * 10)], 3).tobytes()).hexdigest()

    if not duration_ok:
        return QCResult(False, "duration_out_of_bounds", duration, loudness, bpm, energy, qc_score, station_fit, replay, digest)
    if silent:
        return QCResult(False, "near_silence", duration, loudness, bpm, energy, qc_score, station_fit, replay, digest)
    if clipped:
        return QCResult(False, "clipping_detected", duration, loudness, bpm, energy, qc_score, station_fit, replay, digest)

    return QCResult(True, None, duration, loudness, bpm, energy, qc_score, station_fit, replay, digest)
