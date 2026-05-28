from __future__ import annotations

from datetime import datetime

MOOD_ORDER = ["baseline", "rise", "peak", "release"]


def next_mood(current: str, now: datetime) -> str:
    if current not in MOOD_ORDER:
        return "baseline"
    idx = MOOD_ORDER.index(current)
    # Slow bounded progression to avoid abrupt jumps.
    if now.minute % 20 != 0:
        return current
    return MOOD_ORDER[(idx + 1) % len(MOOD_ORDER)]
