"""Async client for the NVIDIA Build / NIM OpenAI-compatible chat API.

Targets ``https://integrate.api.nvidia.com/v1/chat/completions``, which mirrors
the OpenAI chat-completions surface for every NIM-hosted language model
(DeepSeek, Mistral, Moonshot Kimi, Z.AI GLM, etc.). This client is
intentionally thin: it shares :class:`~app.fireworks.StreamDelta` and
:class:`~app.fireworks.ToolCall` so that ``handlers.py`` can round-robin
between Fireworks, FreeTheAI and NVIDIA providers with the same call shape.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .config import settings
from .fireworks import FireworksError, StreamDelta, ToolCall


class NvidiaError(FireworksError):
    """Raised when the NVIDIA Build API returns a non-2xx response."""


def _auth_headers() -> dict[str, str]:
    key = settings.nvidia_api_key
    if not key:
        raise NvidiaError(
            "NVIDIA_API_KEY is not set on the server. "
            "Set it via environment variable or .env file."
        )
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        # NVIDIA requires ``text/event-stream`` for streaming, ``application/json``
        # for normal responses. Sending both in the ``Accept`` header lets the
        # server pick the correct transport based on ``stream``.
        "Accept": "application/json, text/event-stream",
    }


_MAX_RETRIES = 2


async def stream_chat(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int | None = 4096,
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[StreamDelta]:
    """Stream chat completion chunks from NVIDIA Build.

    The NIM endpoints are OpenAI-compatible, so the payload and SSE line
    format are identical to :mod:`app.fireworks` / :mod:`app.freetheai_client`.
    """

    payload: dict[str, object] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if tools:
        payload["tools"] = tools

    url = f"{settings.nvidia_base_url.rstrip('/')}/chat/completions"
    timeout = httpx.Timeout(settings.request_timeout_seconds, connect=15.0)

    last_error: NvidiaError | None = None
    for attempt in range(_MAX_RETRIES):
        if attempt > 0:
            # Backoff on retryable errors (timeouts, 429, transient 5xx).
            await asyncio.sleep(2.0)

        try:
            async for delta in _stream_chat_once(url, payload, timeout):
                yield delta
            return
        except NvidiaError as exc:
            last_error = exc
            # Retry only on rate limits / transient server failures. Anything
            # else (401/403/400 with bad model id) should surface immediately.
            text = str(exc)
            if "429" in text or " 500" in text or " 502" in text or " 503" in text:
                continue
            raise
    if last_error:
        raise last_error


async def _stream_chat_once(
    url: str,
    payload: dict[str, object],
    timeout: httpx.Timeout,
) -> AsyncIterator[StreamDelta]:
    """Single streaming attempt against ``/v1/chat/completions``."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, headers=_auth_headers(), json=payload) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise NvidiaError(
                    f"NVIDIA API returned {resp.status_code}: "
                    f"{body.decode('utf-8', 'replace')[:500]}"
                )

            async for raw_line in resp.aiter_lines():
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    return
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue

                choices = obj.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                delta = choice.get("delta") or {}

                content_piece = delta.get("content") or ""
                # NIM exposes reasoning under the standard OpenAI field name
                # ``reasoning_content``. Some NVIDIA models (e.g. Nemotron,
                # Kimi Thinking) also emit a legacy ``reasoning`` key —
                # accept both so we never drop a thought stream.
                reasoning_piece = (
                    delta.get("reasoning_content")
                    or delta.get("reasoning")
                    or ""
                )
                finish = choice.get("finish_reason")

                tc_list: list[ToolCall] = []
                raw_tcs = delta.get("tool_calls") or []
                for tc in raw_tcs:
                    fn = tc.get("function") or {}
                    tc_list.append(
                        ToolCall(
                            id=tc.get("id") or "",
                            name=fn.get("name") or "",
                            arguments=fn.get("arguments") or "",
                        )
                    )

                if content_piece or reasoning_piece or finish or tc_list:
                    yield StreamDelta(
                        content=content_piece,
                        reasoning=reasoning_piece,
                        finish_reason=finish,
                        tool_calls=tc_list,
                    )


async def chat_completion(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int | None = 4096,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Non-streaming chat completion via NVIDIA Build.

    Used by tool-call round-trips that need a single JSON response instead of
    a stream.
    """

    payload: dict[str, object] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if tools:
        payload["tools"] = tools

    url = f"{settings.nvidia_base_url.rstrip('/')}/chat/completions"
    timeout = httpx.Timeout(settings.request_timeout_seconds, connect=15.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=_auth_headers(), json=payload)
        if resp.status_code >= 400:
            raise NvidiaError(
                f"NVIDIA API returned {resp.status_code}: {resp.text[:500]}"
            )
        return resp.json()
