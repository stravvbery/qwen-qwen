"""Thin async client for the Fireworks AI chat completion API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from .config import settings


class FireworksError(RuntimeError):
    """Raised when Fireworks returns a non-2xx response."""


@dataclass(slots=True)
class StreamDelta:
    """A single chunk decoded from the SSE stream.

    ``content`` and ``reasoning`` correspond to the standard Fireworks fields
    ``choices[0].delta.content`` and ``choices[0].delta.reasoning_content``.
    """

    content: str = ""
    reasoning: str = ""
    finish_reason: str | None = None


def _auth_headers() -> dict[str, str]:
    key = settings.fireworks_api_key
    if not key:
        raise FireworksError(
            "FIREWORKS_API_KEY is not set on the server. "
            "Set it via environment variable or .env file."
        )
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def stream_chat(
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int | None = 4096,
) -> AsyncIterator[StreamDelta]:
    """Stream chat completion chunks from Fireworks.

    Yields :class:`StreamDelta` objects. Caller is responsible for accumulating
    content/reasoning strings if needed.
    """

    payload: dict[str, object] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    url = f"{settings.fireworks_base_url.rstrip('/')}/chat/completions"
    timeout = httpx.Timeout(settings.request_timeout_seconds, connect=15.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, headers=_auth_headers(), json=payload) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise FireworksError(
                    f"Fireworks API returned {resp.status_code}: {body.decode('utf-8', 'replace')}"
                )

            async for raw_line in resp.aiter_lines():
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
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

                if content_piece or reasoning_piece or finish:
                    yield StreamDelta(
                        content=content_piece,
                        reasoning=reasoning_piece,
                        finish_reason=finish,
                    )
