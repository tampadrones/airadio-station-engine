from __future__ import annotations

import re


def _clean_words(value: str) -> list[str]:
    stop = {"a", "an", "and", "or", "the", "to", "of", "in", "on", "for", "with", "track", "song"}
    return [w for w in re.findall(r"[a-z0-9']+", (value or "").lower()) if w not in stop]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def anti_repetition_notes(recent_tracks: list[dict], cohesion_spectrum: int = 80, discovery_depth: int = 20) -> str:
    if not recent_tracks:
        return "avoid obvious hooks repetition; vary rhythm, voice profile, topic premise, lyric images, and instrumentation"
    bpms = [t.get("bpm") for t in recent_tracks if t.get("bpm")]
    avg_bpm = sum(bpms) / len(bpms) if bpms else 110
    energy = [t.get("energy_score") for t in recent_tracks if t.get("energy_score") is not None]
    avg_energy = sum(energy) / len(energy) if energy else 0.5
    topics = []
    voices = []
    titles = []
    texture_tags = []
    for item in recent_tracks[:5]:
        title = str(item.get("title", "") or "").strip()
        topic = str(item.get("song_topic") or item.get("topic") or "").strip()
        voice = str(item.get("voice_profile_id") or "").strip()
        if title:
            titles.append(title)
        if topic:
            topics.append(topic)
        if voice:
            voices.append(voice)
        tags = item.get("tags", [])
        if isinstance(tags, list):
            texture_tags.extend(str(x).strip() for x in tags if str(x).strip())
    bpm_span = max(4, int(14 - (cohesion_spectrum / 10) + (discovery_depth / 20)))
    energy_span = max(0.08, 0.25 - (cohesion_spectrum / 1000) + (discovery_depth / 1200))
    clauses = [
        f"avoid BPM in [{int(avg_bpm - bpm_span)}, {int(avg_bpm + bpm_span)}]",
        f"avoid energy around {avg_energy:.2f} within +/- {energy_span:.2f}",
        "vary vocal/instrument balance and texture tags",
    ]
    if topics:
        clauses.append(f"do not reuse recent topic premises: {', '.join(dict.fromkeys(topics[:4]))}")
    if voices:
        clauses.append(f"rotate away from recent voice profiles: {', '.join(dict.fromkeys(voices[:4]))}")
    if titles:
        clauses.append(f"avoid title/chorus concepts resembling: {', '.join(titles[:4])}")
    if texture_tags:
        clauses.append(f"change at least one core texture from: {', '.join(dict.fromkeys(texture_tags[:6]))}")
    return (
        "; ".join(clauses)
    )


def is_too_similar(candidate_fingerprint: str, recent_fingerprints: list[str]) -> bool:
    candidate = str(candidate_fingerprint or "").strip()
    if not candidate:
        return False
    recent = [str(x or "").strip() for x in recent_fingerprints if str(x or "").strip()]
    if candidate in set(recent):
        return True
    # Audio fingerprints are currently SHA-like hashes, so near-match distance is
    # not meaningful. For non-hash textual fingerprints, use token overlap.
    if re.fullmatch(r"[a-fA-F0-9]{32,128}", candidate):
        return False
    return is_text_too_similar(candidate, recent)


def is_text_too_similar(candidate_text: str, recent_texts: list[str], *, threshold: float = 0.72) -> bool:
    candidate_words = set(_clean_words(candidate_text))
    if len(candidate_words) < 3:
        return False
    candidate_norm = " ".join(_clean_words(candidate_text))
    for recent in recent_texts:
        recent_words = set(_clean_words(recent))
        if len(recent_words) < 3:
            continue
        recent_norm = " ".join(_clean_words(recent))
        if candidate_norm and recent_norm and (candidate_norm in recent_norm or recent_norm in candidate_norm):
            return True
        if _jaccard(candidate_words, recent_words) >= threshold:
            return True
    return False
