from app.services.listeners import should_generate_for_station


class DummyRedis:
    def __init__(self, current: int, last_active: str | None = None):
        self.current = current
        self.last_active = last_active

    def zremrangebyscore(self, *_args, **_kwargs):
        return 0

    def zcard(self, *_args, **_kwargs):
        return self.current

    def get(self, key: str):
        if key.endswith(":last_active"):
            return self.last_active
        return None


def test_should_generate_when_active_listeners(monkeypatch):
    import app.services.listeners as mod

    monkeypatch.setattr(mod, "get_redis", lambda: DummyRedis(current=2))
    ok, reason = should_generate_for_station("synthwave-fm", ready_tracks=3)
    assert ok is True
    assert reason == "active_listeners"


def test_should_not_generate_when_idle_with_buffer(monkeypatch):
    import app.services.listeners as mod

    monkeypatch.setattr(mod, "get_redis", lambda: DummyRedis(current=0, last_active=None))
    ok, reason = should_generate_for_station("synthwave-fm", ready_tracks=2, idle_min_ready_tracks=1)
    assert ok is False
    assert reason.startswith("idle_")


def test_should_bootstrap_when_idle_and_empty(monkeypatch):
    import app.services.listeners as mod

    monkeypatch.setattr(mod, "get_redis", lambda: DummyRedis(current=0, last_active=None))
    ok, reason = should_generate_for_station("synthwave-fm", ready_tracks=0, idle_min_ready_tracks=1)
    assert ok is True
    assert reason == "bootstrap_min_ready"


def test_should_suppress_bootstrap_when_active_elsewhere():
    ok, reason = should_generate_for_station(
        "synthwave-fm",
        ready_tracks=0,
        idle_min_ready_tracks=1,
        station_current_listeners=0,
        any_active_listeners=True,
    )
    assert ok is False
    assert reason == "bootstrap_suppressed_active_elsewhere"
