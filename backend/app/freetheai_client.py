"""Async client for the freetheai.xyz OpenAI-compatible API.

Mirrors the interface of ``fireworks.py`` so that ``routes.py`` can call
either one with the same arguments.  Adds client-side rate limiting
(10 RPM / 1 concurrent on the free tier).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .config import settings
from .fireworks import FireworksError, StreamDelta, ToolCall


class FreeTheAIError(FireworksError):
    """Raised when freetheai.xyz returns a non-2xx response."""


# --- client-side throttle (10 RPM / 1 concurrent) ---------------------------

_lock = asyncio.Lock()
_last_call_at: float = 0.0


async def _throttle() -> None:
    global _last_call_at
    async with _lock:
        loop = asyncio.get_event_loop()
        now = loop.time()
        wait = settings.freetheai_min_interval_seconds - (now - _last_call_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_at = loop.time()


def _auth_headers() -> dict[str, str]:
    key = settings.freetheai_api_key
    if not key:
        raise FreeTheAIError(
            "FREETHEAI_API_KEY is not set on the server. "
            "Set it via environment variable or .env file."
        )
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
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
    """Stream chat completion chunks from freetheai.xyz."""

    await _throttle()

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

    url = f"{settings.freetheai_base_url.rstrip('/')}/chat/completions"
    timeout = httpx.Timeout(settings.request_timeout_seconds, connect=15.0)

    last_error: FreeTheAIError | None = None
    for attempt in range(_MAX_RETRIES):
        if attempt > 0:
            await asyncio.sleep(2.0)

        try:
            async for delta in _stream_chat_once(url, payload, timeout):
                yield delta
            return  # success
        except FreeTheAIError as e:
            last_error = e
            if "400" not in str(e) and "429" not in str(e):
                raise  # non-retryable error
    if last_error:
        raise last_error


async def _stream_chat_once(
    url: str,
    payload: dict[str, object],
    timeout: httpx.Timeout,
) -> AsyncIterator[StreamDelta]:
    """Single attempt at streaming chat completion."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, headers=_auth_headers(), json=payload) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise FreeTheAIError(
                    f"FreeTheAI API returned {resp.status_code}: {body.decode('utf-8', 'replace')}"
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
                reasoning_piece = delta.get("reasoning_content") or ""
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
    """Non-streaming chat completion via freetheai.xyz."""

    await _throttle()

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

    url = f"{settings.freetheai_base_url.rstrip('/')}/chat/completions"
    timeout = httpx.Timeout(settings.request_timeout_seconds, connect=15.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=_auth_headers(), json=payload)
        if resp.status_code >= 400:
            raise FreeTheAIError(
                f"FreeTheAI API returned {resp.status_code}: {resp.text[:500]}"
            )
        return resp.json()
