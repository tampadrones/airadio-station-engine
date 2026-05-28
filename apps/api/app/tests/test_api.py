from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint():
    client = TestClient(app)
    res = client.get('/api/health')
    assert res.status_code == 200
    assert res.json()['status'] == 'ok'


def test_backfill_titles_endpoint_empty_ok():
    client = TestClient(app)
    res = client.post('/api/stations/backfill-titles', json={})
    assert res.status_code == 200
    payload = res.json()
    assert payload["ok"] is True
    assert isinstance(payload["total_scanned"], int)
    assert isinstance(payload["total_updated"], int)
    assert payload["total_scanned"] >= 0
    assert payload["total_updated"] >= 0
