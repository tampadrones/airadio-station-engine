from __future__ import annotations


def anti_repetition_notes(recent_tracks: list[dict], cohesion_spectrum: int = 80, discovery_depth: int = 20) -> str:
    if not recent_tracks:
        return "avoid obvious hooks repetition; vary rhythm and instrumentation"
    bpms = [t.get("bpm") for t in recent_tracks if t.get("bpm")]
    avg_bpm = sum(bpms) / len(bpms) if bpms else 110
    energy = [t.get("energy_score") for t in recent_tracks if t.get("energy_score") is not None]
    avg_energy = sum(energy) / len(energy) if energy else 0.5
    bpm_span = max(4, int(14 - (cohesion_spectrum / 10) + (discovery_depth / 20)))
    energy_span = max(0.08, 0.25 - (cohesion_spectrum / 1000) + (discovery_depth / 1200))
    return (
        f"avoid BPM in [{int(avg_bpm - bpm_span)}, {int(avg_bpm + bpm_span)}], "
        f"avoid energy around {avg_energy:.2f} within +/- {energy_span:.2f}, "
        "vary vocal/instrument balance and texture tags"
    )


def is_too_similar(candidate_fingerprint: str, recent_fingerprints: list[str]) -> bool:
    return candidate_fingerprint in set(recent_fingerprints)
