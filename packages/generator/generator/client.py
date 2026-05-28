from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from urllib.parse import quote, urlencode

import httpx


class FailureReason(str, Enum):
    timeout = "timeout"
    connection_error = "connection_error"
    malformed_response = "malformed_response"
    empty_audio = "empty_audio"
    file_write_failure = "file_write_failure"
    duplicate_rejection = "duplicate_rejection"
    qc_rejection = "qc_rejection"
    gradio_error = "gradio_error"


@dataclass
class GenerationRequest:
    prompt: str
    negative_prompt: str | None = None
    lyrics: str | None = None
    duration_sec: int = 200
    seed: int | None = None
    ace_params: dict[str, Any] | None = None
    ace_format_payload: dict[str, Any] | None = None


@dataclass
class GenerationResult:
    ok: bool
    audio_url: str | None = None
    model: str | None = None
    seed: int | None = None
    raw: dict[str, Any] | None = None
    failure_reason: FailureReason | None = None
    error_message: str | None = None


class AceStepClient:
    SAFE_MAX_DURATION_SEC = 180
    SAFE_MAX_INFERENCE_STEPS = 6

    def __init__(
        self,
        base_url: str,
        timeout_seconds: int = 180,
        max_retries: int = 3,
        backoff_seconds: int = 2,
        predict_path: str = "/api/predict",
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.predict_path = predict_path if predict_path.startswith("/") else f"/{predict_path}"
        self._blocked_until: datetime | None = None
        self._gradio_template: list[Any] | None = None
        self._gradio_input_index: dict[str, int] | None = None
        self._gradio_fn_index: int | None = None

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(self.base_url)
                return resp.status_code < 500
        except Exception:
            return False

    async def generate(self, req: GenerationRequest) -> GenerationResult:
        if self._blocked_until and datetime.now(timezone.utc) < self._blocked_until:
            return GenerationResult(
                ok=False,
                failure_reason=FailureReason.connection_error,
                error_message="Generator endpoint temporarily blocked after redirect/TLS failure.",
            )

        # Gradio ACE-Step (port 7865) flow.
        if self.predict_path.startswith("/gradio_api/call/"):
            last: GenerationResult | None = None
            current_req = req
            applied_oom_fallback = False
            for attempt in range(self.max_retries + 1):
                result = await self._generate_via_gradio_call_once(current_req)
                if result.ok:
                    return result
                if (not applied_oom_fallback) and self._is_gpu_oom_result(result):
                    fallback_req = self._build_oom_fallback_request(current_req)
                    if fallback_req is not None:
                        current_req = fallback_req
                        applied_oom_fallback = True
                        continue
                last = result
                if attempt == self.max_retries:
                    return result
                if result.failure_reason not in {
                    FailureReason.timeout,
                    FailureReason.connection_error,
                    FailureReason.empty_audio,
                    FailureReason.malformed_response,
                }:
                    return result
                await asyncio.sleep(self.backoff_seconds * (attempt + 1))
            return last or GenerationResult(ok=False, failure_reason=FailureReason.malformed_response, error_message="Unknown gradio failure")

        # Legacy direct REST flow.
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                payload = {
                    "prompt": req.prompt,
                    "negative_prompt": req.negative_prompt or "",
                    "duration": req.duration_sec,
                    "seed": req.seed,
                }
                async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
                    resp = await client.post(f"{self.base_url}{self.predict_path}", json=payload)
                if 300 <= resp.status_code < 400:
                    location = resp.headers.get("location", "")
                    if location.startswith("https://") and self.base_url.startswith("http://"):
                        self._blocked_until = datetime.now(timezone.utc) + timedelta(seconds=90)
                        return GenerationResult(
                            ok=False,
                            failure_reason=FailureReason.connection_error,
                            error_message=f"Generator redirected HTTP to HTTPS ({location}) but HTTPS endpoint is not reachable. Set GENERATOR_BASE_URL to a reachable endpoint.",
                        )
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError("server error", request=resp.request, response=resp)
                data = resp.json()
                audio_url = self._extract_audio_url(data)
                if not audio_url:
                    return GenerationResult(ok=False, failure_reason=FailureReason.malformed_response, raw=data, error_message="No audio field")
                return GenerationResult(ok=True, audio_url=audio_url, raw=data, model=self._extract_model(data), seed=self._extract_seed(data))
            except httpx.TimeoutException as exc:
                last_err = exc
                if attempt == self.max_retries:
                    return GenerationResult(ok=False, failure_reason=FailureReason.timeout, error_message=str(exc))
            except httpx.ConnectError as exc:
                last_err = exc
                if attempt == self.max_retries:
                    return GenerationResult(ok=False, failure_reason=FailureReason.connection_error, error_message=str(exc))
            except Exception as exc:
                last_err = exc
                if attempt == self.max_retries:
                    return GenerationResult(ok=False, failure_reason=FailureReason.malformed_response, error_message=str(exc))
            await asyncio.sleep(self.backoff_seconds * (attempt + 1))
        return GenerationResult(ok=False, failure_reason=FailureReason.malformed_response, error_message=str(last_err))

    def _is_gpu_oom_result(self, result: GenerationResult) -> bool:
        if result.failure_reason not in {FailureReason.empty_audio, FailureReason.malformed_response, FailureReason.connection_error}:
            return False
        msg = (result.error_message or "").lower()
        return ("cuda out of memory" in msg) or ("outofmemoryerror" in msg) or ("tried to allocate" in msg)

    def _build_oom_fallback_request(self, req: GenerationRequest) -> GenerationRequest | None:
        target_duration = min(int(req.duration_sec), 180)
        if target_duration >= int(req.duration_sec):
            return None

        fallback_ace_params = dict(req.ace_params or {})
        fallback_ace_payload = dict(req.ace_format_payload or {})

        fallback_ace_params["dit_inference_steps"] = min(int(fallback_ace_params.get("dit_inference_steps", 8)), 6)
        fallback_ace_payload["duration"] = target_duration
        fallback_ace_payload["inference_steps"] = min(int(fallback_ace_payload.get("inference_steps", 8)), 6)
        fallback_ace_payload["use_cot_caption"] = False
        fallback_ace_payload["use_cot_lyrics"] = False
        fallback_ace_payload["use_constrained_decoding"] = False

        return replace(
            req,
            duration_sec=target_duration,
            ace_params=fallback_ace_params,
            ace_format_payload=fallback_ace_payload,
        )

    async def _generate_via_gradio_call_once(self, req: GenerationRequest) -> GenerationResult:
        try:
            template = await self._load_gradio_template()
            data = list(template)
            labels = self._gradio_input_index or {}
            safe_duration_sec = max(30, min(int(req.duration_sec), self.SAFE_MAX_DURATION_SEC))

            def set_by_label(label: str, value: Any) -> bool:
                key = label.strip().lower()
                idx = labels.get(key)
                if idx is None:
                    return False
                if 0 <= idx < len(data):
                    data[idx] = value
                    return True
                return False

            # Core fields.
            if not set_by_label("music caption", req.prompt):
                data[0] = req.prompt
            has_lyrics = bool((req.lyrics or "").strip())
            if not set_by_label("lyrics", req.lyrics or ""):
                data[1] = req.lyrics or ""
            if not set_by_label("bpm (beats per minute)", 120):
                data[2] = 120
            if has_lyrics:
                if not set_by_label("vocal language", "en"):
                    data[5] = "en"
                if not set_by_label("task_type", "lyrics2music"):
                    data[20] = "lyrics2music"
            else:
                if not set_by_label("task_type", "text2music"):
                    data[20] = "text2music"
            if not set_by_label("audio duration (seconds)", safe_duration_sec):
                data[11] = safe_duration_sec
            # Keep generation batch size conservative for low-VRAM / legacy CUDA
            # deployments to avoid quantized dispatch crashes in ACE-Step.
            set_by_label("batch size", 1)
            if not set_by_label("audio format", "wav"):
                data[30] = "wav"
            if not set_by_label("mp3 sample rate", 44100):
                data[32] = 44100
            if req.negative_prompt:
                if not set_by_label("lm negative prompt", req.negative_prompt):
                    data[38] = req.negative_prompt
            if req.seed is not None:
                if not set_by_label("random seed", False):
                    data[8] = False
                if not set_by_label("seed", int(req.seed)):
                    data[9] = int(req.seed)

            # Extended ACE-Step controls from caller, keyed by human label aliases.
            ace = req.ace_params or {}
            if ace:
                alias = {
                    "bpm": "bpm (beats per minute)",
                    "key": "key",
                    "keyscale": "key",
                    "time_signature": "time signature",
                    "vocal_language": "vocal language",
                    "dit_inference_steps": "dit inference steps",
                    "dit_guidance_scale": "dit guidance scale (base model only)",
                    "use_adg": "use adg (angle domain guidance)",
                    "cfg_interval_start": "cfg interval start",
                    "cfg_interval_end": "cfg interval end",
                    "shift": "shift",
                    "inference_method": "inference method",
                    "sampler_mode": "sampler mode",
                    "audio_format": "audio format",
                    "mp3_bitrate": "mp3 bitrate",
                    "mp3_sample_rate": "mp3 sample rate",
                    "lm_temperature": "lm temperature",
                    "lm_cfg_scale": "lm cfg scale",
                    "lm_top_k": "lm top-k",
                    "lm_top_p": "lm top-p (nucleus sampling)",
                    "enable_normalization": "enable normalization",
                    "target_peak_db": "target peak (db)",
                    "fade_in_duration": "fade in (seconds)",
                    "fade_out_duration": "fade out (seconds)",
                    "latent_shift": "latent shift",
                    "latent_rescale": "latent rescale",
                    "quality_score_sensitivity": "quality score sensitivity",
                    "autogen": "autogen",
                    "velocity_norm_threshold": "velocity norm threshold",
                    "velocity_ema_factor": "velocity ema factor",
                    "timesteps": "timesteps",
                    "repainting_start": "repainting start",
                    "repainting_end": "repainting end",
                    "chunk_mask_mode": "chunk mask mode",
                    "repaint_latent_crossfade_frames": "repaint latent crossfade frames",
                    "repaint_wav_crossfade_sec": "repaint wav crossfade sec",
                    "repaint_mode": "repaint mode",
                    "repaint_strength": "repaint strength",
                    "audio_cover_strength": "audio cover strength",
                    "cover_noise_strength": "cover noise strength",
                    # Gradio labels (ACE-Step 7865) use "Think" (not "Thinking") and
                    # "CoT ..." variants.
                    "thinking": "think",
                    "use_cot_metas": "cot metas (chain-of-thought metadata)",
                    # ACE-Step UI exposes CaptionRewrite rather than a distinct "CoT caption" toggle.
                    "use_cot_caption": "captionrewrite",
                    # No dedicated CoT lyrics toggle in the current UI.
                    "use_cot_language": "cot language detection",
                    "use_constrained_decoding": "constrained decoding debug",
                    "cot_bpm": "cot bpm",
                    "cot_keyscale": "cot keyscale",
                    "cot_timesignature": "cot timesignature",
                    "cot_duration": "cot duration",
                    "cot_vocal_language": "cot vocal language",
                    "cot_caption": "cot caption",
                    "cot_lyrics": "cot lyrics",
                    "parallelthinking": "parallelthinking",
                    "lora_loaded": "lora loaded",
                    "use_lora": "use lora",
                    "lora_scale": "lora scale",
                    "lora_weights_hash": "lora weights hash",
                }
                fallback_idx = {
                    "bpm": 2,
                    "dit_inference_steps": 6,
                    "dit_guidance_scale": 7,
                    "lm_temperature": 33,
                    "lm_cfg_scale": 35,
                    "lm_top_k": 36,
                    "lm_top_p": 37,
                    "enable_normalization": 51,
                    "target_peak_db": 52,
                    "fade_in_duration": 53,
                    "fade_out_duration": 54,
                    "latent_shift": 55,
                    "latent_rescale": 56,
                    "quality_score_sensitivity": 47,
                    "thinking": 34,
                    "use_cot_metas": 39,
                    "use_cot_caption": 40,
                    "use_cot_language": 41,
                    "use_constrained_decoding": 43,
                    "parallelthinking": 44,
                }
                for k, v in ace.items():
                    if v is None:
                        continue
                    if str(k).strip().lower() == "dit_inference_steps":
                        v = min(int(v), self.SAFE_MAX_INFERENCE_STEPS)
                    norm_key = str(k).strip().lower()
                    label = alias.get(norm_key)
                    if not label:
                        continue
                    if not set_by_label(label, v):
                        idx = fallback_idx.get(norm_key)
                        if idx is not None and 0 <= idx < len(data):
                            data[idx] = v

            # Full ACE-Step JSON payload template support (acestep-format.json style).
            payload = req.ace_format_payload or {}
            if payload:
                payload_alias = {
                    "task_type": "task_type",
                    "instruction": "instruction",
                    "reference_audio": "reference audio",
                    "src_audio": "source audio",
                    "audio_codes": "audio codes",
                    "caption": "music caption",
                    "global_caption": "global caption",
                    "lyrics": "lyrics",
                    "instrumental": "instrumental",
                    "vocal_language": "vocal language",
                    "bpm": "bpm (beats per minute)",
                    "keyscale": "key",
                    "timesignature": "time signature",
                    "duration": "audio duration (seconds)",
                    "enable_normalization": "enable normalization",
                    "normalization_db": "target peak (db)",
                    "fade_in_duration": "fade in (seconds)",
                    "fade_out_duration": "fade out (seconds)",
                    "latent_shift": "latent shift",
                    "latent_rescale": "latent rescale",
                    "inference_steps": "dit inference steps",
                    "seed": "seed",
                    "guidance_scale": "dit guidance scale (base model only)",
                    "use_adg": "use adg (angle domain guidance)",
                    "cfg_interval_start": "cfg interval start",
                    "cfg_interval_end": "cfg interval end",
                    "shift": "shift",
                    "infer_method": "inference method",
                    "sampler_mode": "sampler mode",
                    "velocity_norm_threshold": "velocity norm threshold",
                    "velocity_ema_factor": "velocity ema factor",
                    "timesteps": "timesteps",
                    "repainting_start": "repainting start",
                    "repainting_end": "repainting end",
                    "chunk_mask_mode": "chunk mask mode",
                    "repaint_latent_crossfade_frames": "repaint latent crossfade frames",
                    "repaint_wav_crossfade_sec": "repaint wav crossfade sec",
                    "repaint_mode": "repaint mode",
                    "repaint_strength": "repaint strength",
                    "audio_cover_strength": "audio cover strength",
                    "cover_noise_strength": "cover noise strength",
                    "thinking": "think",
                    "lm_temperature": "lm temperature",
                    "lm_cfg_scale": "lm cfg scale",
                    "lm_top_k": "lm top-k",
                    "lm_top_p": "lm top-p (nucleus sampling)",
                    "lm_negative_prompt": "lm negative prompt",
                    "use_cot_metas": "cot metas (chain-of-thought metadata)",
                    "use_cot_caption": "captionrewrite",
                    "use_cot_language": "cot language detection",
                    "use_constrained_decoding": "constrained decoding debug",
                    "cot_bpm": "cot bpm",
                    "cot_keyscale": "cot keyscale",
                    "cot_timesignature": "cot timesignature",
                    "cot_duration": "cot duration",
                    "cot_vocal_language": "cot vocal language",
                    "cot_caption": "cot caption",
                    "cot_lyrics": "cot lyrics",
                    "parallelthinking": "parallelthinking",
                    "lora_loaded": "lora loaded",
                    "use_lora": "use lora",
                    "lora_scale": "lora scale",
                    "lora_weights_hash": "lora weights hash",
                    "audio_format": "audio format",
                }
                payload_fallback_idx = {
                    "caption": 0,
                    "lyrics": 1,
                    "bpm": 2,
                    "vocal_language": 5,
                    "inference_steps": 6,
                    "guidance_scale": 7,
                    "seed": 9,
                    "duration": 11,
                    "task_type": 20,
                    "audio_format": 30,
                    "lm_temperature": 33,
                    "lm_cfg_scale": 35,
                    "lm_top_k": 36,
                    "lm_top_p": 37,
                    "lm_negative_prompt": 38,
                    "use_cot_metas": 39,
                    "use_cot_caption": 40,
                    "use_cot_language": 41,
                    "use_constrained_decoding": 43,
                    "parallelthinking": 44,
                    "enable_normalization": 51,
                    "normalization_db": 52,
                    "fade_in_duration": 53,
                    "fade_out_duration": 54,
                    "latent_shift": 55,
                    "latent_rescale": 56,
                    "thinking": 34,
                }
                for k, v in payload.items():
                    if v is None:
                        continue
                    norm_key = str(k).strip().lower()
                    if norm_key == "duration":
                        v = safe_duration_sec
                    elif norm_key == "inference_steps":
                        v = min(int(v), self.SAFE_MAX_INFERENCE_STEPS)
                    label = payload_alias.get(norm_key)
                    if label and set_by_label(label, v):
                        continue
                    idx = payload_fallback_idx.get(norm_key)
                    if idx is not None and 0 <= idx < len(data):
                        data[idx] = v

            # Final hardening after all overlays.
            set_by_label("audio duration (seconds)", safe_duration_sec)
            set_by_label("dit inference steps", self.SAFE_MAX_INFERENCE_STEPS)

            async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
                queue_result = await self._generate_via_gradio_queue(client, data, req)
                if queue_result is not None:
                    return queue_result

                submit = await client.post(f"{self.base_url}{self.predict_path}", json={"data": data})
                submit.raise_for_status()
                submit_json = submit.json()
                event_id = submit_json.get("event_id")
                if not isinstance(event_id, str) or not event_id:
                    return GenerationResult(ok=False, failure_reason=FailureReason.malformed_response, raw=submit_json, error_message="Missing event_id")

                stream_url = f"{self.base_url}{self.predict_path}/{event_id}"
                saw_non_null_payload = False
                last_non_null_payload: Any = None
                stream_started = time.monotonic()
                stream_deadline = stream_started + float(max(30, int(self.timeout_seconds)))
                try:
                    async with client.stream("GET", stream_url, timeout=httpx.Timeout(connect=10.0, read=15.0, write=30.0, pool=10.0)) as stream:
                        stream.raise_for_status()
                        async for line in stream.aiter_lines():
                            if time.monotonic() >= stream_deadline:
                                break
                            if not line:
                                continue
                            if line.startswith("data:"):
                                payload = line[5:].strip()
                            elif line[0] in "[{":
                                # Some Gradio proxies deliver plain JSON lines.
                                payload = line.strip()
                            else:
                                continue
                            if payload == "null":
                                continue
                            try:
                                parsed = json.loads(payload)
                            except json.JSONDecodeError:
                                continue
                            saw_non_null_payload = True
                            last_non_null_payload = parsed
                            audio_url = self._extract_audio_url(parsed)
                            if audio_url:
                                return GenerationResult(ok=True, audio_url=audio_url, raw={"event_id": event_id, "payload": parsed}, model="ace-step-gradio", seed=req.seed)
                except (httpx.TimeoutException, httpx.RemoteProtocolError):
                    # Quiet or abruptly-closed SSE streams are common on this
                    # endpoint; fall through to the terminal fetch below.
                    pass

                # Some Gradio proxies keep the SSE connection open with progress/heartbeat
                # events even after the generation result is ready. After a bounded wall-clock
                # read window, do one terminal fetch for the finalized payload.
                try:
                    final_resp = await client.get(stream_url, timeout=20)
                    if final_resp.status_code < 500:
                        body = final_resp.text.strip()
                        if body:
                            final_parsed: Any | None = None
                            try:
                                final_parsed = json.loads(body)
                            except json.JSONDecodeError:
                                for raw_line in body.splitlines():
                                    line2 = raw_line.strip()
                                    if not line2:
                                        continue
                                    if line2.startswith("data:"):
                                        line2 = line2[5:].strip()
                                    if not line2 or line2 == "null":
                                        continue
                                    try:
                                        final_parsed = json.loads(line2)
                                        break
                                    except json.JSONDecodeError:
                                        continue
                            if final_parsed is not None:
                                audio_url = self._extract_audio_url(final_parsed)
                                if audio_url:
                                    return GenerationResult(
                                        ok=True,
                                        audio_url=audio_url,
                                        raw={"event_id": event_id, "payload": final_parsed, "fallback_fetch": True},
                                        model="ace-step-gradio",
                                        seed=req.seed,
                                    )
                                saw_non_null_payload = saw_non_null_payload or True
                                last_non_null_payload = final_parsed
                except Exception:
                    pass

            if not saw_non_null_payload:
                return GenerationResult(
                    ok=False,
                    failure_reason=FailureReason.timeout,
                    error_message="No non-null payload observed in Gradio stream",
                )
            snippet = ""
            try:
                snippet = json.dumps(last_non_null_payload)[:240] if last_non_null_payload is not None else ""
            except Exception:
                snippet = str(last_non_null_payload)[:240]
            return GenerationResult(
                ok=False,
                failure_reason=FailureReason.empty_audio,
                error_message=f"No audio URL in Gradio stream; last payload: {snippet}" if snippet else "No audio URL in Gradio stream",
            )
        except httpx.TimeoutException as exc:
            return GenerationResult(ok=False, failure_reason=FailureReason.timeout, error_message=str(exc))
        except httpx.ConnectError as exc:
            return GenerationResult(ok=False, failure_reason=FailureReason.connection_error, error_message=str(exc))
        except Exception as exc:
            return GenerationResult(ok=False, failure_reason=FailureReason.malformed_response, error_message=str(exc))

    async def _generate_via_gradio_queue(
        self,
        client: httpx.AsyncClient,
        data: list[Any],
        req: GenerationRequest,
    ) -> GenerationResult | None:
        if self._gradio_fn_index is None:
            return None

        session_hash = f"airadio{uuid.uuid4().hex[:10]}"
        try:
            join = await client.post(
                f"{self.base_url}/gradio_api/queue/join",
                json={
                    "data": data,
                    "fn_index": self._gradio_fn_index,
                    "session_hash": session_hash,
                },
            )
        except httpx.HTTPError:
            return None

        if join.status_code in {404, 405}:
            return None
        join.raise_for_status()

        saw_non_null_payload = False
        last_non_null_payload: Any = None
        stream_started = time.monotonic()
        stream_deadline = stream_started + float(max(30, int(self.timeout_seconds)))
        queue_url = f"{self.base_url}/gradio_api/queue/data?{urlencode({'session_hash': session_hash})}"

        try:
            async with client.stream(
                "GET",
                queue_url,
                timeout=httpx.Timeout(connect=10.0, read=40.0, write=30.0, pool=10.0),
            ) as stream:
                stream.raise_for_status()
                async for line in stream.aiter_lines():
                    if time.monotonic() >= stream_deadline:
                        break
                    if not line or not line.startswith("data:"):
                        continue

                    payload = line[5:].strip()
                    if not payload:
                        continue
                    try:
                        parsed = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    msg = parsed.get("msg")
                    if msg in {"heartbeat", "estimation", "process_starts", "progress"}:
                        continue

                    output = parsed.get("output") if isinstance(parsed, dict) else None
                    if isinstance(output, dict):
                        candidate = output.get("data")
                        if candidate is not None:
                            saw_non_null_payload = True
                            last_non_null_payload = candidate
                            audio_url = self._extract_audio_url(candidate)
                            if audio_url:
                                return GenerationResult(
                                    ok=True,
                                    audio_url=audio_url,
                                    raw={"session_hash": session_hash, "payload": parsed},
                                    model="ace-step-gradio",
                                    seed=req.seed,
                                )

                    if msg == "process_completed":
                        success = bool(parsed.get("success"))
                        if success:
                            snippet = ""
                            try:
                                snippet = json.dumps(last_non_null_payload)[:240] if last_non_null_payload is not None else ""
                            except Exception:
                                snippet = str(last_non_null_payload)[:240]
                            return GenerationResult(
                                ok=False,
                                failure_reason=FailureReason.empty_audio,
                                error_message=f"No audio URL in Gradio queue response; last payload: {snippet}" if snippet else "No audio URL in Gradio queue response",
                            )

                        error_message = None
                        raw_error = None
                        if isinstance(output, dict):
                            raw_error = output.get("error")
                        # Check for specific Gradio error types
                        if isinstance(raw_error, str) and "NSFW" in raw_error:
                            return GenerationResult(
                                ok=False,
                                failure_reason=FailureReason.gradio_error,
                                error_message=raw_error.strip(),
                                raw={"session_hash": session_hash, "payload": parsed},
                            )
                        if isinstance(raw_error, str) and raw_error.strip():
                            error_message = raw_error.strip()
                        return GenerationResult(
                            ok=False,
                            failure_reason=FailureReason.malformed_response,
                            error_message=error_message or "Gradio queue processing failed",
                            raw={"session_hash": session_hash, "payload": parsed},
                        )

                    if msg == "close_stream":
                        break
        except (httpx.TimeoutException, httpx.RemoteProtocolError):
            pass

        if not saw_non_null_payload:
            return GenerationResult(
                ok=False,
                failure_reason=FailureReason.timeout,
                error_message="No non-null payload observed in Gradio queue stream",
            )

        snippet = ""
        try:
            snippet = json.dumps(last_non_null_payload)[:240] if last_non_null_payload is not None else ""
        except Exception:
            snippet = str(last_non_null_payload)[:240]
        return GenerationResult(
            ok=False,
            failure_reason=FailureReason.empty_audio,
            error_message=f"No audio URL in Gradio queue stream; last payload: {snippet}" if snippet else "No audio URL in Gradio queue stream",
        )

    async def _load_gradio_template(self) -> list[Any]:
        if self._gradio_template is not None:
            return self._gradio_template
        async with httpx.AsyncClient(timeout=20) as client:
            cfg = (await client.get(f"{self.base_url}/config")).json()
        components = {c.get("id"): c for c in cfg.get("components", [])}
        dep = next((d for d in cfg.get("dependencies", []) if d.get("api_name") == "generation_wrapper"), None)
        if not dep:
            raise ValueError("generation_wrapper not found in Gradio config")
        template = []
        index_map: dict[str, int] = {}
        self._gradio_fn_index = dep.get("id")
        for cid in dep.get("inputs", []):
            comp = components.get(cid, {})
            props = comp.get("props") or {}
            template.append(props.get("value"))
            label = props.get("label")
            if isinstance(label, str) and label.strip():
                index_map[label.strip().lower()] = len(template) - 1
        if len(template) < 40:
            raise ValueError("Unexpected Gradio generation template shape")
        self._gradio_template = template
        self._gradio_input_index = index_map
        return template

    def _extract_audio_url(self, data: Any) -> str | None:
        def _is_audio_url(v: str) -> bool:
            return "/gradio_api/file=" in v or v.endswith(".wav") or v.endswith(".mp3")

        def _normalize_audio_ref(v: str) -> str | None:
            raw = v.strip()
            if not raw:
                return None
            if raw.startswith("http") and _is_audio_url(raw):
                return raw
            # Gradio often emits local tempfile paths; map to file-serving route.
            if raw.startswith("/tmp/") or raw.startswith("/var/"):
                return f"{self.base_url}/gradio_api/file={quote(raw, safe='/=._-')}"
            if raw.startswith("/gradio_api/file="):
                return f"{self.base_url}{raw}"
            if raw.startswith("/") and _is_audio_url(raw):
                return f"{self.base_url}{raw}"
            return None

        if isinstance(data, dict):
            for key in ["audio_url", "url", "audio", "path", "name"]:
                val = data.get(key)
                if isinstance(val, str):
                    normalized = _normalize_audio_ref(val)
                    if normalized:
                        return normalized
            for value in data.values():
                nested = self._extract_audio_url(value)
                if nested:
                    return nested
        if isinstance(data, list):
            for item in data:
                nested = self._extract_audio_url(item)
                if nested:
                    return nested
        if isinstance(data, str):
            normalized = _normalize_audio_ref(data)
            if normalized:
                return normalized
        return None

    def _extract_model(self, data: dict[str, Any]) -> str | None:
        for key in ["model", "model_name", "generator_model"]:
            val = data.get(key)
            if isinstance(val, str):
                return val
        return None

    def _extract_seed(self, data: dict[str, Any]) -> int | None:
        val = data.get("seed")
        if isinstance(val, int):
            return val
        return None
