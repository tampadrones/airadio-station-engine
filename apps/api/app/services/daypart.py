from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


@dataclass
class DaypartBlend:
    daypart: str
    energy_modifier: float
    prompt_bias: str


DAYPARTS = [
    ("late_night", 0, 5, 0.55, "atmospheric, sparse, reflective"),
    ("morning", 5, 11, 0.85, "light, optimistic, building momentum"),
    ("midday", 11, 17, 1.0, "steady, focused, productive"),
    ("evening", 17, 24, 1.2, "energetic, emotional, richer textures"),
]


def get_daypart_blend(now_utc: datetime, timezone: str) -> DaypartBlend:
    local = now_utc.astimezone(ZoneInfo(timezone))
    hour = local.hour + local.minute / 60
    for name, start, end, energy, bias in DAYPARTS:
        if start <= hour < end:
            smooth = 1 - min(abs(((start + end) / 2) - hour) / ((end - start) / 2), 1)
            return DaypartBlend(daypart=name, energy_modifier=round(0.7 * energy + 0.3 * (0.8 + smooth * 0.4), 3), prompt_bias=bias)
    return DaypartBlend(daypart="late_night", energy_modifier=0.6, prompt_bias="minimal, atmospheric")
