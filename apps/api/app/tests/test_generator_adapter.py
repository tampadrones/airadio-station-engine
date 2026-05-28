import pytest
import httpx
import json

from generator.client import AceStepClient, GenerationRequest


@pytest.mark.asyncio
async def test_generator_adapter_success(monkeypatch):
    async def handler(request):
        return httpx.Response(200, json={"audio_url": "http://example.com/audio.wav", "seed": 11})

    transport = httpx.MockTransport(handler)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    client = AceStepClient("http://fake")
    result = await client.generate(GenerationRequest(prompt="x"))
    assert result.ok
    assert result.audio_url.endswith(".wav")


@pytest.mark.asyncio
async def test_generator_adapter_malformed(monkeypatch):
    async def handler(request):
        return httpx.Response(200, json={"unexpected": "shape"})

    transport = httpx.MockTransport(handler)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    client = AceStepClient("http://fake", max_retries=0)
    result = await client.generate(GenerationRequest(prompt="x"))
    assert not result.ok
    assert result.failure_reason.value == "malformed_response"


@pytest.mark.asyncio
async def test_gradio_request_includes_lyrics(monkeypatch):
    captured: dict[str, object] = {"lyrics": "", "vocal_language": None, "task_type": None}

    async def handler(request):
        if request.method == "POST" and request.url.path.endswith("/gradio_api/call/generation_wrapper"):
            payload = json.loads(request.content.decode("utf-8"))
            captured["lyrics"] = payload["data"][1]
            captured["vocal_language"] = payload["data"][5]
            captured["task_type"] = payload["data"][20]
            return httpx.Response(200, json={"event_id": "evt-1"})
        if request.method == "GET" and request.url.path.endswith("/gradio_api/call/generation_wrapper/evt-1"):
            return httpx.Response(200, text='data: {"audio_url":"http://example.com/audio.wav"}\n\n')
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    client = AceStepClient("http://fake", predict_path="/gradio_api/call/generation_wrapper")
    async def fake_template():
        return [None] * 40

    monkeypatch.setattr(client, "_load_gradio_template", fake_template)
    result = await client.generate(GenerationRequest(prompt="caption", lyrics="line one"))
    assert result.ok
    assert captured["lyrics"] == "line one"
    assert captured["vocal_language"] == "en"
    assert captured["task_type"] == "lyrics2music"


@pytest.mark.asyncio
async def test_gradio_request_uses_text2music_without_lyrics(monkeypatch):
    captured: dict[str, object] = {"task_type": None}

    async def handler(request):
        if request.method == "POST" and request.url.path.endswith("/gradio_api/call/generation_wrapper"):
            payload = json.loads(request.content.decode("utf-8"))
            captured["task_type"] = payload["data"][20]
            return httpx.Response(200, json={"event_id": "evt-2"})
        if request.method == "GET" and request.url.path.endswith("/gradio_api/call/generation_wrapper/evt-2"):
            return httpx.Response(200, text='data: {"audio_url":"http://example.com/audio.wav"}\n\n')
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    client = AceStepClient("http://fake", predict_path="/gradio_api/call/generation_wrapper")

    async def fake_template():
        return [None] * 64

    monkeypatch.setattr(client, "_load_gradio_template", fake_template)
    result = await client.generate(GenerationRequest(prompt="caption", lyrics=None))
    assert result.ok
    assert captured["task_type"] == "text2music"


@pytest.mark.asyncio
async def test_gradio_request_applies_ace_params(monkeypatch):
    captured: dict[str, object] = {"bpm": None, "steps": None, "temp": None}

    async def handler(request):
        if request.method == "POST" and request.url.path.endswith("/gradio_api/call/generation_wrapper"):
            payload = json.loads(request.content.decode("utf-8"))
            captured["bpm"] = payload["data"][2]
            captured["steps"] = payload["data"][6]
            captured["temp"] = payload["data"][33]
            return httpx.Response(200, json={"event_id": "evt-3"})
        if request.method == "GET" and request.url.path.endswith("/gradio_api/call/generation_wrapper/evt-3"):
            return httpx.Response(200, text='data: {"audio_url":"http://example.com/audio.wav"}\n\n')
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    client = AceStepClient("http://fake", predict_path="/gradio_api/call/generation_wrapper")

    async def fake_template():
        return [None] * 64

    monkeypatch.setattr(client, "_load_gradio_template", fake_template)
    result = await client.generate(
        GenerationRequest(
            prompt="caption",
            lyrics="line one",
            ace_params={"bpm": 142, "dit_inference_steps": 12, "lm_temperature": 0.77},
        )
    )
    assert result.ok
    assert captured["bpm"] == 142
    assert captured["steps"] == 6
    assert captured["temp"] == 0.77


@pytest.mark.asyncio
async def test_gradio_stream_plain_json_line_and_tmp_path_normalization(monkeypatch):
    async def handler(request):
        if request.method == "POST" and request.url.path.endswith("/gradio_api/call/generation_wrapper"):
            return httpx.Response(200, json={"event_id": "evt-plain"})
        if request.method == "GET" and request.url.path.endswith("/gradio_api/call/generation_wrapper/evt-plain"):
            return httpx.Response(200, text='{"path":"/tmp/gradio/out.wav"}\n')
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    client = AceStepClient("http://fake", predict_path="/gradio_api/call/generation_wrapper")

    async def fake_template():
        return [None] * 64

    monkeypatch.setattr(client, "_load_gradio_template", fake_template)
    result = await client.generate(GenerationRequest(prompt="caption"))
    assert result.ok
    assert result.audio_url == "http://fake/gradio_api/file=/tmp/gradio/out.wav"


@pytest.mark.asyncio
async def test_gradio_request_applies_ace_format_payload(monkeypatch):
    captured: dict[str, object] = {"caption": None, "lyrics": None, "task_type": None, "bpm": None}

    async def handler(request):
        if request.method == "POST" and request.url.path.endswith("/gradio_api/call/generation_wrapper"):
            payload = json.loads(request.content.decode("utf-8"))
            captured["caption"] = payload["data"][0]
            captured["lyrics"] = payload["data"][1]
            captured["bpm"] = payload["data"][2]
            captured["task_type"] = payload["data"][20]
            return httpx.Response(200, json={"event_id": "evt-template"})
        if request.method == "GET" and request.url.path.endswith("/gradio_api/call/generation_wrapper/evt-template"):
            return httpx.Response(200, text='data: {"audio_url":"http://example.com/audio.wav"}\n\n')
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    client = AceStepClient("http://fake", predict_path="/gradio_api/call/generation_wrapper")

    async def fake_template():
        return [None] * 64

    monkeypatch.setattr(client, "_load_gradio_template", fake_template)
    result = await client.generate(
        GenerationRequest(
            prompt="base caption",
            lyrics="base lyrics",
            ace_format_payload={
                "caption": "template caption",
                "lyrics": "template lyrics",
                "task_type": "lyrics2music",
                "bpm": 145,
            },
        )
    )
    assert result.ok
    assert captured["caption"] == "template caption"
    assert captured["lyrics"] == "template lyrics"
    assert captured["task_type"] == "lyrics2music"
    assert captured["bpm"] == 145


@pytest.mark.asyncio
async def test_gradio_retries_empty_stream_then_succeeds(monkeypatch):
    state = {"stream_calls": 0}

    async def handler(request):
        if request.method == "POST" and request.url.path.endswith("/gradio_api/call/generation_wrapper"):
            return httpx.Response(200, json={"event_id": "evt-retry"})
        if request.method == "GET" and request.url.path.endswith("/gradio_api/call/generation_wrapper/evt-retry"):
            state["stream_calls"] += 1
            if state["stream_calls"] == 1:
                return httpx.Response(200, text='data: {"status":"running"}\n\n')
            return httpx.Response(200, text='data: {"audio_url":"http://example.com/audio.wav"}\n\n')
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    client = AceStepClient("http://fake", predict_path="/gradio_api/call/generation_wrapper", max_retries=1, backoff_seconds=0)

    async def fake_template():
        return [None] * 64

    monkeypatch.setattr(client, "_load_gradio_template", fake_template)
    result = await client.generate(GenerationRequest(prompt="caption"))
    assert result.ok
    assert state["stream_calls"] == 2


@pytest.mark.asyncio
async def test_gradio_heartbeat_only_returns_timeout(monkeypatch):
    async def handler(request):
        if request.method == "POST" and request.url.path.endswith("/gradio_api/call/generation_wrapper"):
            return httpx.Response(200, json={"event_id": "evt-heartbeat"})
        if request.method == "GET" and request.url.path.endswith("/gradio_api/call/generation_wrapper/evt-heartbeat"):
            return httpx.Response(200, text="event: heartbeat\ndata: null\n\n")
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    client = AceStepClient("http://fake", predict_path="/gradio_api/call/generation_wrapper", max_retries=0)

    async def fake_template():
        return [None] * 64

    monkeypatch.setattr(client, "_load_gradio_template", fake_template)
    result = await client.generate(GenerationRequest(prompt="caption"))
    assert not result.ok
    assert result.failure_reason.value == "timeout"


@pytest.mark.asyncio
async def test_gradio_fallback_fetch_extracts_audio(monkeypatch):
    state = {"calls": 0}

    async def handler(request):
        if request.method == "POST" and request.url.path.endswith("/gradio_api/call/generation_wrapper"):
            return httpx.Response(200, json={"event_id": "evt-final"})
        if request.method == "GET" and request.url.path.endswith("/gradio_api/call/generation_wrapper/evt-final"):
            state["calls"] += 1
            if state["calls"] == 1:
                # First streaming pass has no payload.
                return httpx.Response(200, text="")
            # Fallback GET contains final JSON path.
            return httpx.Response(200, text='{"path":"/tmp/gradio/final.wav"}')
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    client = AceStepClient("http://fake", predict_path="/gradio_api/call/generation_wrapper", max_retries=0)

    async def fake_template():
        return [None] * 64

    monkeypatch.setattr(client, "_load_gradio_template", fake_template)
    result = await client.generate(GenerationRequest(prompt="caption"))
    assert result.ok
    assert result.audio_url == "http://fake/gradio_api/file=/tmp/gradio/final.wav"


@pytest.mark.asyncio
async def test_gradio_queue_data_extracts_audio_and_preserves_real_error_path(monkeypatch):
    async def handler(request):
        if request.method == "POST" and request.url.path.endswith("/gradio_api/queue/join"):
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["fn_index"] == 117
            assert payload["session_hash"].startswith("airadio")
            return httpx.Response(200, json={"event_id": "evt-queue"})
        if request.method == "GET" and request.url.path.endswith("/gradio_api/queue/data"):
            body = (
                'data: {"msg":"process_starts","event_id":"evt-queue"}\n\n'
                'data: {"msg":"process_completed","event_id":"evt-queue","output":{"data":[{"path":"/tmp/gradio/queued.wav"}]},"success":true}\n\n'
                'data: {"msg":"close_stream","event_id":null}\n\n'
            )
            return httpx.Response(200, text=body)
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    client = AceStepClient("http://fake", predict_path="/gradio_api/call/generation_wrapper", max_retries=0)

    async def fake_template():
        client._gradio_fn_index = 117
        return [None] * 64

    monkeypatch.setattr(client, "_load_gradio_template", fake_template)
    result = await client.generate(GenerationRequest(prompt="caption"))
    assert result.ok
    assert result.audio_url == "http://fake/gradio_api/file=/tmp/gradio/queued.wav"


@pytest.mark.asyncio
async def test_gradio_queue_data_surfaces_server_error(monkeypatch):
    async def handler(request):
        if request.method == "POST" and request.url.path.endswith("/gradio_api/queue/join"):
            return httpx.Response(200, json={"event_id": "evt-error"})
        if request.method == "GET" and request.url.path.endswith("/gradio_api/queue/data"):
            body = (
                'data: {"msg":"process_completed","event_id":"evt-error","output":{"error":"read-only export path"},"success":false}\n\n'
                'data: {"msg":"close_stream","event_id":null}\n\n'
            )
            return httpx.Response(200, text=body)
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    client = AceStepClient("http://fake", predict_path="/gradio_api/call/generation_wrapper", max_retries=0)

    async def fake_template():
        client._gradio_fn_index = 117
        return [None] * 64

    monkeypatch.setattr(client, "_load_gradio_template", fake_template)
    result = await client.generate(GenerationRequest(prompt="caption"))
    assert not result.ok
    assert result.failure_reason.value == "malformed_response"
    assert result.error_message == "read-only export path"
