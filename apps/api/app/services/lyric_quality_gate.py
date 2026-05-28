from __future__ import annotations

import hashlib
import re
from typing import Any


GENERIC_FILLER = {
    "we rise",
    "we shine",
    "city lights",
    "signal strong",
    "hold the line",
    "never fade",
    "through the night",
    "feel alive",
    "right here right now",
}

META_LEAKAGE = {
    "song concept",
    "vocal profile",
    "theme anchors",
    "style anchor",
    "avoid verbatim",
}

ABSTRACT_WORDS = {
    "dream",
    "dreams",
    "hope",
    "truth",
    "heart",
    "soul",
    "feeling",
    "feel",
    "moment",
    "forever",
    "always",
    "never",
    "love",
    "pain",
    "light",
    "dark",
    "freedom",
    "destiny",
    "memory",
    "memories",
    "energy",
    "vibe",
    "alive",
}

SECTION_RE = re.compile(r"^\s*\[([A-Z0-9 -]+)\]\s*$")


def _words(value: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (value or "").lower())


def _content_lines(lyrics: str) -> list[str]:
    lines: list[str] = []
    for raw in (lyrics or "").splitlines():
        line = " ".join(raw.strip().split())
        if not line or SECTION_RE.match(line):
            continue
        lines.append(line)
    return lines


def _sections(lyrics: str) -> dict[str, list[str]]:
    current = "UNSECTIONED"
    out: dict[str, list[str]] = {}
    for raw in (lyrics or "").splitlines():
        line = " ".join(raw.strip().split())
        if not line:
            continue
        m = SECTION_RE.match(line.upper())
        if m:
            current = m.group(1).strip()
            out.setdefault(current, [])
            continue
        out.setdefault(current, []).append(line)
    return out


def _brief_terms(song_brief: dict | None) -> dict[str, set[str]]:
    brief = song_brief if isinstance(song_brief, dict) else {}
    fields = {
        "topic": brief.get("topic", ""),
        "setting": brief.get("setting", ""),
        "conflict": brief.get("conflict", ""),
        "hook_concept": brief.get("hook_concept", ""),
    }
    imagery = brief.get("imagery_bank", [])
    if isinstance(imagery, list):
        fields["imagery_bank"] = " ".join(str(x) for x in imagery)
    return {
        key: {w for w in _words(str(value)) if len(w) >= 4}
        for key, value in fields.items()
    }


def _line_signature(lines: list[str]) -> str:
    joined = "\n".join(line.lower() for line in lines)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def _recent_signatures(recent_generations: list | None) -> set[str]:
    signatures: set[str] = set()
    for item in recent_generations or []:
        if not isinstance(item, dict):
            continue
        sig = item.get("lyric_signature")
        if not isinstance(sig, dict):
            diagnostics = item.get("diagnostics", {})
            if isinstance(diagnostics, dict):
                quality = diagnostics.get("lyric_quality", {})
                sig = quality.get("signature") if isinstance(quality, dict) else None
        if isinstance(sig, dict):
            line_sig = str(sig.get("line_signature", "") or "").strip()
            chorus_sig = str(sig.get("chorus_signature", "") or "").strip()
            if line_sig:
                signatures.add(line_sig)
            if chorus_sig:
                signatures.add(chorus_sig)
    return signatures


def evaluate_lyrics_quality(
    *,
    lyrics: str | None,
    song_brief: dict | None,
    voice_profile: dict | None,
    recent_generations: list | None = None,
) -> dict:
    _ = voice_profile
    text = (lyrics or "").strip()
    reasons: list[str] = []
    score = 1.0
    if not text:
        return {
            "passed": False,
            "score": 0.0,
            "reasons": ["empty_lyrics"],
            "signature": {"line_count": 0, "unique_line_ratio": 0.0},
        }

    lowered = text.lower()
    lines = _content_lines(text)
    sections = _sections(text)
    line_counts: dict[str, int] = {}
    for line in lines:
        key = line.lower()
        line_counts[key] = line_counts.get(key, 0) + 1
    repeated_lines = [line for line, count in line_counts.items() if count > 1]
    unique_ratio = len(line_counts) / max(1, len(lines))

    chorus_lines: list[str] = []
    for name, section_lines in sections.items():
        if "CHORUS" in name:
            chorus_lines.extend(line.lower() for line in section_lines)
    chorus_counts: dict[str, int] = {}
    for line in chorus_lines:
        chorus_counts[line] = chorus_counts.get(line, 0) + 1
    repeated_chorus = [line for line, count in chorus_counts.items() if count > 1]

    filler_hits = sorted(phrase for phrase in GENERIC_FILLER if phrase in lowered)
    meta_hits = sorted(phrase for phrase in META_LEAKAGE if phrase in lowered)

    if repeated_chorus:
        reasons.append("repeated_chorus_lines")
        score -= 0.25
    if len(repeated_lines) >= 2 or unique_ratio < 0.72:
        reasons.append("repeated_full_lines")
        score -= 0.20
    if filler_hits:
        reasons.append("generic_filler_phrases")
        score -= min(0.35, 0.10 * len(filler_hits))
    if meta_hits:
        reasons.append("meta_prompt_leakage")
        score -= 0.35

    all_words = _words(text)
    abstract_count = sum(1 for word in all_words if word in ABSTRACT_WORDS)
    brief = song_brief if isinstance(song_brief, dict) else {}
    imagery_terms = _brief_terms(brief).get("imagery_bank", set())
    concrete_hits = sum(1 for word in all_words if word in imagery_terms)
    abstract_ratio = abstract_count / max(1, len(all_words))
    if len(all_words) >= 24 and abstract_ratio > 0.18 and concrete_hits < 2:
        reasons.append("too_abstract_not_enough_imagery")
        score -= 0.18

    brief_terms = _brief_terms(brief)
    brief_hits: dict[str, int] = {}
    for field, terms in brief_terms.items():
        if not terms:
            continue
        brief_hits[field] = len(set(all_words) & terms)
    required_fields = [field for field in ["topic", "setting", "conflict", "hook_concept"] if brief_terms.get(field)]
    missed = [field for field in required_fields if brief_hits.get(field, 0) == 0]
    if len(required_fields) >= 2 and len(missed) >= 2:
        reasons.append("song_brief_underused")
        score -= 0.25

    line_signature = _line_signature(lines)
    chorus_signature = _line_signature(chorus_lines)
    recent_sigs = _recent_signatures(recent_generations)
    if line_signature in recent_sigs or (chorus_signature and chorus_signature in recent_sigs):
        reasons.append("too_similar_to_recent_lyrics")
        score -= 0.30

    score = max(0.0, min(1.0, score))
    passed = score >= 0.68 and not any(
        reason in reasons
        for reason in {
            "empty_lyrics",
            "meta_prompt_leakage",
            "generic_filler_phrases",
            "song_brief_underused",
            "too_similar_to_recent_lyrics",
        }
    )
    signature = {
        "line_count": len(lines),
        "unique_line_ratio": round(unique_ratio, 3),
        "repeated_line_count": len(repeated_lines),
        "repeated_chorus_count": len(repeated_chorus),
        "generic_filler_hits": filler_hits,
        "meta_leakage_hits": meta_hits,
        "brief_hits": brief_hits,
        "abstract_ratio": round(abstract_ratio, 3),
        "concrete_imagery_hits": concrete_hits,
        "line_signature": line_signature,
        "chorus_signature": chorus_signature,
    }
    return {
        "passed": bool(passed),
        "score": round(score, 3),
        "reasons": reasons,
        "signature": signature,
    }
