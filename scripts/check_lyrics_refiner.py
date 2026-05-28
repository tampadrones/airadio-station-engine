#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.core.settings import Settings  # noqa: E402


def _presence(value: str | None) -> str:
    return "set" if str(value or "").strip() else "unset"


def _extract_model_ids(payload: Any) -> list[str]:
    candidates: list[Any] = []
    if isinstance(payload, dict):
        for key in ("data", "models"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates.extend(value)
        if not candidates:
            candidates.append(payload)
    elif isinstance(payload, list):
        candidates.extend(payload)

    ids: list[str] = []
    for item in candidates:
        if isinstance(item, str):
            model_id = item.strip()
        elif isinstance(item, dict):
            model_id = str(item.get("id") or item.get("name") or item.get("model") or "").strip()
        else:
            model_id = ""
        if model_id and model_id not in ids:
            ids.append(model_id)
    return ids


def _headers(token: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _signin_token(client: httpx.Client, base_url: str, email: str, password: str) -> str | None:
    resp = client.post(
        f"{base_url}/api/v1/auths/signin",
        json={"email": email, "password": password},
    )
    print(f"signin_status={resp.status_code}")
    if resp.status_code >= 400:
        print(resp.text[:1000])
        return None
    payload = resp.json()
    return str(payload.get("token", "")).strip() if isinstance(payload, dict) else None


def main() -> int:
    settings = Settings()
    base_urls = [x.strip().rstrip("/") for x in settings.lyrics_refiner_base_urls.split(",") if x.strip()]
    base_url = base_urls[0] if base_urls else ""
    model = settings.lyrics_refiner_model.strip()
    token = settings.lyrics_refiner_api_key.strip()
    email = settings.lyrics_refiner_auth_email.strip()
    password = settings.lyrics_refiner_auth_password.strip()
    timeout = int(settings.lyrics_refiner_timeout_seconds)

    print(f"base_url={base_url or 'unset'}")
    print(f"model={model or 'unset'}")
    print(f"api_key={_presence(token)}")
    print(f"auth_email={_presence(email)}")
    print(f"auth_password={_presence(password)}")
    print(f"timeout_seconds={timeout}")
    print(f"temperature={settings.lyrics_refiner_temperature}")

    if not base_url:
        print("ERROR: LYRICS_REFINER_BASE_URLS is unset")
        return 2
    if not model:
        print("ERROR: LYRICS_REFINER_MODEL is unset")
        return 2

    try:
        with httpx.Client(timeout=timeout) as client:
            if not token and email and password:
                token = _signin_token(client, base_url, email, password) or ""
                if not token:
                    print("ERROR: OpenWebUI sign-in failed")
                    return 3

            models_resp = client.get(f"{base_url}/api/models", headers=_headers(token))
            print(f"models_status={models_resp.status_code}")
            print(models_resp.text[:1000])
            if models_resp.status_code in {401, 403}:
                print("ERROR: OpenWebUI authentication failed")
                return 3
            if models_resp.status_code >= 400:
                print("ERROR: failed to fetch OpenWebUI models")
                return 4

            model_ids = _extract_model_ids(models_resp.json())
            print("available_model_ids:")
            for model_id in model_ids:
                print(f"- {model_id}")
            if model not in model_ids:
                print(f"ERROR: configured model not found: {model}")
                return 5

            payload = {
                "model": model,
                "temperature": settings.lyrics_refiner_temperature,
                "max_tokens": 80,
                "messages": [
                    {"role": "system", "content": "Return JSON only with keys title and lyrics."},
                    {
                        "role": "user",
                        "content": 'Write four clean test lyric lines. Return {"title":"...","lyrics":"..."}',
                    },
                ],
            }
            chat_resp = client.post(f"{base_url}/api/chat/completions", headers=_headers(token), json=payload)
            print(f"chat_status={chat_resp.status_code}")
            print(chat_resp.text[:1000])
            if chat_resp.status_code in {401, 403}:
                print("ERROR: OpenWebUI chat authentication failed")
                return 3
            if chat_resp.status_code >= 400:
                print("ERROR: OpenWebUI chat request failed")
                return 4
    except httpx.TimeoutException:
        print("ERROR: request timed out")
        return 4
    except httpx.HTTPError as exc:
        print(f"ERROR: request failed: {exc.__class__.__name__}")
        return 4
    except Exception as exc:
        print(f"ERROR: {exc.__class__.__name__}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
