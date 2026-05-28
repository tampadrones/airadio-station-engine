from __future__ import annotations

from typing import Any

import httpx

from app.core.settings import Settings


def check_generator_health(settings: Settings) -> dict[str, Any]:
    base_url = settings.generator_base_url.rstrip("/")
    status_url = f"{base_url}/gradio_api/queue/status"
    timeout_seconds = max(2, min(int(settings.generator_timeout_seconds), 10))
    out: dict[str, Any] = {
        "configured_env_var": "GENERATOR_BASE_URL",
        "generator_base_url": base_url,
        "generator_predict_path": settings.generator_predict_path,
        "generator_status_url": status_url,
        "reachable": False,
        "http_status": None,
        "error": None,
    }
    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            resp = client.get(status_url)
        out["http_status"] = int(resp.status_code)
        out["reachable"] = resp.is_success
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out

