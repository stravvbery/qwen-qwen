"""Gemini 3.1 Flash proxy with automatic key rotation.

Manages multiple Google AI Studio API keys and rotates them when one hits
rate limits or errors. Provides the same streaming interface as fireworks.py.

Keys are tried round-robin; if a key fails with 429 (rate limit) or 403
(quota exceeded), it's temporarily disabled and the next key is tried.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import settings
from .fireworks import FireworksError, StreamDelta, ToolCall

log = logging.getLogger(__name__)

# How long to disable a key after a rate-limit error (seconds)
_COOLDOWN_SECONDS = 60.0

# Gemini API base
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_MODEL_ID = "gemini-3.1-flash-lite-preview"


class GeminiError(FireworksError):
    """Raised when all Gemini keys are exhausted or a non-retryable error occurs."""


# ---------------------------------------------------------------------------
# Key pool management
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class KeyState:
    key: str
    project_name: str
    disabled_until: float = 0.0  # timestamp when key becomes available again
    request_count: int = 0
    error_count: int = 0


class KeyPool:
    """Round-robin key pool with cooldown on rate-limited keys."""

    def __init__(self, keys: list[tuple[str, str]]) -> None:
        """keys: list of (api_key, project_name) tuples."""
        self._states = [KeyState(key=k, project_name=name) for k, name in keys]
        self._index = 0
        self._lock = asyncio.Lock()

    @property
    def size(self) -> int:
        return len(self._states)

    def _is_available(self, state: KeyState) -> bool:
        return time.time() >= state.disabled_until

    async def get_key(self) -> KeyState:
        """Get the next available key. Raises GeminiError if all keys are on cooldown."""
        async with self._lock:
            n = len(self._states)
            for _ in range(n):
                state = self._states[self._index]
                self._index = (self._index + 1) % n
                if self._is_available(state):
                    return state

            # All keys on cooldown — find the one that recovers soonest
            soonest = min(self._states, key=lambda s: s.disabled_until)
            wait = soonest.disabled_until - time.time()
            if wait > 0:
                log.warning(
                    "All Gemini keys on cooldown. Waiting %.1fs for %s",
                    wait, soonest.project_name,
                )
                # Release lock while waiting
            else:
                return soonest

        # Wait outside the lock
        await asyncio.sleep(wait)
        return soonest

    def mark_success(self, state: KeyState) -> None:
        state.request_count += 1

    def mark_failed(self, state: KeyState, cooldown: float = _COOLDOWN_SECONDS) -> None:
        state.error_count += 1
        state.disabled_until = time.time() + cooldown
        log.warning(
            "Gemini key %s (%s) disabled for %.0fs (errors: %d)",
            state.key[:10] + "...", state.project_name, cooldown, state.error_count,
        )

    def status(self) -> list[dict[str, Any]]:
        """Return status of all keys for diagnostics."""
        now = time.time()
        return [
            {
                "project": s.project_name,
                "available": self._is_available(s),
                "cooldown_remaining": max(0, s.disabled_until - now),
                "requests": s.request_count,
                "errors": s.error_count,
            }
            for s in self._states
        ]


# ---------------------------------------------------------------------------
# Singleton pool — initialized lazily from settings
# ---------------------------------------------------------------------------

_pool: KeyPool | None = None


def _get_pool() -> KeyPool:
    global _pool
    if _pool is None:
        keys = settings.gemini_api_keys_parsed()
        if not keys:
            raise GeminiError("No GEMINI_API_KEYS configured.")
        _pool = KeyPool(keys)
        log.info("Gemini key pool initialized with %d keys", _pool.size)
    return _pool


def get_pool_status() -> list[dict[str, Any]]:
    """Get key pool diagnostics."""
    try:
        return _get_pool().status()
    except GeminiError:
        return []


# ---------------------------------------------------------------------------
# Message format conversion (OpenAI → Gemini)
# ---------------------------------------------------------------------------


def _convert_messages(messages: list[dict[str, Any]]) -> tuple[list[dict], str | None]:
    """Convert OpenAI-format messages to Gemini format.

    Returns (contents, system_instruction).
    """
    system_instruction = None
    contents: list[dict] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "system":
            system_instruction = content
            continue

        # Map roles: user → user, assistant → model
        gemini_role = "model" if role == "assistant" else "user"
        contents.append({
            "role": gemini_role,
            "parts": [{"text": content}],
        })

    return contents, system_instruction


# ---------------------------------------------------------------------------
# Streaming API
# ---------------------------------------------------------------------------

_RETRYABLE_STATUSES = {429, 403, 500, 503}


async def stream_chat(
    *,
    model: str = _MODEL_ID,
    messages: list[dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int | None = 4096,
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[StreamDelta]:
    """Stream Gemini response with automatic key rotation on failure.

    Interface matches fireworks.stream_chat for compatibility.
    """
    pool = _get_pool()
    contents, system_instruction = _convert_messages(messages)

    # Try up to pool.size keys
    last_error: Exception | None = None
    for attempt in range(pool.size + 1):
        key_state = await pool.get_key()

        try:
            async for delta in _stream_with_key(
                key_state=key_state,
                model=model,
                contents=contents,
                system_instruction=system_instruction,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                yield delta

            # Success
            pool.mark_success(key_state)
            return

        except _RetryableError as e:
            pool.mark_failed(key_state)
            last_error = e
            log.info(
                "Gemini key %s failed (attempt %d/%d): %s — rotating...",
                key_state.project_name, attempt + 1, pool.size, e,
            )
            continue

        except Exception as e:
            # Non-retryable error — don't rotate, just raise
            raise GeminiError(f"Gemini API error: {e}") from e

    raise GeminiError(
        f"All {pool.size} Gemini keys failed. Last error: {last_error}"
    )


class _RetryableError(Exception):
    """Internal: signals that we should try the next key."""


async def _stream_with_key(
    *,
    key_state: KeyState,
    model: str,
    contents: list[dict],
    system_instruction: str | None,
    temperature: float,
    max_tokens: int | None,
) -> AsyncIterator[StreamDelta]:
    """Stream from Gemini with a specific key."""
    url = f"{_GEMINI_BASE}/models/{model}:streamGenerateContent"
    params = {"alt": "sse", "key": key_state.key}

    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
        },
    }
    if max_tokens:
        payload["generationConfig"]["maxOutputTokens"] = max_tokens
    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}],
        }

    timeout = httpx.Timeout(120.0, connect=15.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, params=params, json=payload) as resp:
            if resp.status_code in _RETRYABLE_STATUSES:
                body = await resp.aread()
                raise _RetryableError(
                    f"HTTP {resp.status_code}: {body.decode('utf-8', 'replace')[:300]}"
                )
            if resp.status_code >= 400:
                body = await resp.aread()
                raise GeminiError(
                    f"Gemini API returned {resp.status_code}: "
                    f"{body.decode('utf-8', 'replace')[:500]}"
                )

            async for raw_line in resp.aiter_lines():
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]" or not data:
                    continue

                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue

                # Parse Gemini response format
                candidates = obj.get("candidates") or []
                if not candidates:
                    continue

                candidate = candidates[0]
                content = candidate.get("content") or {}
                parts = content.get("parts") or []
                finish_reason = candidate.get("finishReason")

                text_pieces = []
                for part in parts:
                    if "text" in part:
                        text_pieces.append(part["text"])

                content_text = "".join(text_pieces)

                if content_text or finish_reason:
                    yield StreamDelta(
                        content=content_text,
                        reasoning="",
                        finish_reason=finish_reason,
                        tool_calls=[],
                    )


# ---------------------------------------------------------------------------
# Non-streaming completion (for simple requests)
# ---------------------------------------------------------------------------


async def chat_completion(
    *,
    model: str = _MODEL_ID,
    messages: list[dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int | None = 4096,
) -> str:
    """Non-streaming completion — collects full response text."""
    full = ""
    async for delta in stream_chat(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    ):
        full += delta.content
    return full
