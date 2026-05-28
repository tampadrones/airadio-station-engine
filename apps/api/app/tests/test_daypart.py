from datetime import datetime, timezone

from app.services.daypart import get_daypart_blend


def test_daypart_blend_morning():
    now = datetime(2026, 1, 1, 13, 0, tzinfo=timezone.utc)
    blend = get_daypart_blend(now, "America/New_York")
    assert blend.daypart in {"morning", "midday"}
    assert 0.5 < blend.energy_modifier < 1.4
