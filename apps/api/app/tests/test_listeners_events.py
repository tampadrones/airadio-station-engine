from app.services.listeners import handle_listener_event, get_listener_rollups


def test_listener_events_rollup():
    handle_listener_event("synthwave-fm", "session-a", "stream_error")
    handle_listener_event("synthwave-fm", "session-a", "rebuffer")
    handle_listener_event("synthwave-fm", "session-a", "completion")
    rollups = get_listener_rollups()
    assert int(rollups["stream_errors"]) >= 1
    assert int(rollups["rebuffer_events"]) >= 1
    assert float(rollups["completion_rate"]) >= 0.0
