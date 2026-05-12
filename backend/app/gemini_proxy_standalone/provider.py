"""Standalone Gemini API provider with automatic key rotation.

Adapted from the telegram bot's Gemini provider. Uses httpx (async) for HTTP
requests. Supports both streaming and non-streaming responses, converts
OpenAI-style messages to Gemini format, and includes native google_search
tool for grounding.

No external dependencies beyond httpx and the Python standard library.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-2.0-flash"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_CONNECT_TIMEOUT = 15.0

# Cooldown durations (seconds)
RATE_LIMIT_COOLDOWN = 60.0  # 429 errors
SERVER_ERROR_COOLDOWN = 300.0  # 500+ errors

# HTTP statuses that trigger key rotation
RETRYABLE_STATUSES = {429, 403, 500, 502, 503}


# ---------------------------------------------------------------------------
# Key health tracking
# ---------------------------------------------------------------------------


class KeyStatus(Enum):
    """Health status of an API key."""

    HEALTHY = "healthy"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"


@dataclass
class KeyState:
    """Tracks the state of a single API key."""

    key: str
    status: KeyStatus = KeyStatus.HEALTHY
    last_used: float = 0.0
    cooldown_until: float = 0.0
    request_count: int = 0
    error_count: int = 0

    @property
    def is_available(self) -> bool:
        """Check if the key is available (healthy or cooldown expired)."""
        if self.status == KeyStatus.HEALTHY:
            return True
        return time.time() >= self.cooldown_until


# ---------------------------------------------------------------------------
# Main provider class
# ---------------------------------------------------------------------------


class GeminiKeyRotationProxy:
    """Gemini API proxy with automatic round-robin key rotation.

    Features:
    - Accepts a list of API keys on init
    - Round-robin rotation with health tracking
    - Auto-cooldown on rate limit (429) or server errors (500+)
    - Auto-recovery after cooldown expires
    - Async, uses httpx
    - Supports both streaming and non-streaming responses
    - Converts OpenAI-style messages to Gemini format
    - Includes native google_search tool for grounding
    """

    def __init__(
        self,
        api_keys: list[str],
        *,
        rate_limit_cooldown: float = RATE_LIMIT_COOLDOWN,
        server_error_cooldown: float = SERVER_ERROR_COOLDOWN,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        default_model: str = DEFAULT_MODEL,
        enable_google_search: bool = True,
    ) -> None:
        """Initialize the proxy with a list of API keys.

        Args:
            api_keys: List of Gemini API keys for rotation.
            rate_limit_cooldown: Seconds to disable a key after 429 error.
            server_error_cooldown: Seconds to disable a key after 500+ error.
            timeout: Total request timeout in seconds.
            connect_timeout: Connection timeout in seconds.
            default_model: Default model ID (e.g. "gemini-2.0-flash").
            enable_google_search: Whether to include google_search tool.
        """
        if not api_keys:
            raise ValueError("At least one API key is required")

        self._keys: list[KeyState] = [KeyState(key=k) for k in api_keys]
        self._current_index: int = 0
        self._lock = asyncio.Lock()
        self._rate_limit_cooldown = rate_limit_cooldown
        self._server_error_cooldown = server_error_cooldown
        self._timeout = httpx.Timeout(timeout, connect=connect_timeout)
        self._default_model = default_model
        self._enable_google_search = enable_google_search

    # ------------------------------------------------------------------
    # Key rotation logic
    # ------------------------------------------------------------------

    def _recover_expired_keys(self) -> None:
        """Re-enable keys whose cooldown has expired."""
        now = time.time()
        for key_state in self._keys:
            if key_state.status != KeyStatus.HEALTHY:
                if now >= key_state.cooldown_until:
                    key_state.status = KeyStatus.HEALTHY

    def _get_next_key(self) -> KeyState | None:
        """Select the next healthy key using round-robin.

        Returns None if all keys are on cooldown.
        """
        self._recover_expired_keys()

        num_keys = len(self._keys)
        for _ in range(num_keys):
            key_state = self._keys[self._current_index]
            self._current_index = (self._current_index + 1) % num_keys
            if key_state.status == KeyStatus.HEALTHY:
                key_state.last_used = time.time()
                return key_state

        return None

    def _mark_rate_limited(self, key_state: KeyState) -> None:
        """Mark a key as rate limited with cooldown."""
        key_state.status = KeyStatus.RATE_LIMITED
        key_state.cooldown_until = time.time() + self._rate_limit_cooldown
        key_state.error_count += 1
        logger.warning(
            "Key ...%s marked as rate-limited, cooldown %.0fs",
            key_state.key[-6:],
            self._rate_limit_cooldown,
        )

    def _mark_error(self, key_state: KeyState) -> None:
        """Mark a key as having a server error with a longer cooldown."""
        key_state.status = KeyStatus.ERROR
        key_state.cooldown_until = time.time() + self._server_error_cooldown
        key_state.error_count += 1
        logger.warning(
            "Key ...%s marked as error, cooldown %.0fs",
            key_state.key[-6:],
            self._server_error_cooldown,
        )

    def _mark_success(self, key_state: KeyState) -> None:
        """Mark a successful request."""
        key_state.request_count += 1

    # ------------------------------------------------------------------
    # Public API: non-streaming
    # ------------------------------------------------------------------

    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = 4096,
    ) -> str:
        """Generate a non-streaming response.

        Args:
            messages: OpenAI-style messages list.
            model: Model ID (uses default_model if not specified).
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.

        Returns:
            The generated text response.

        Raises:
            RuntimeError: If all keys are exhausted or non-retryable error.
        """
        model = model or self._default_model
        last_error: Exception | None = None

        for _ in range(len(self._keys)):
            async with self._lock:
                key_state = self._get_next_key()

            if key_state is None:
                raise RuntimeError("No available Gemini API keys (all on cooldown)")

            try:
                result = await self._request_generate(
                    key_state=key_state,
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                self._mark_success(key_state)
                return result
            except _RetryableError as e:
                last_error = e
                continue

        raise RuntimeError(
            f"All {len(self._keys)} Gemini keys failed. Last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # Public API: streaming
    # ------------------------------------------------------------------

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = 4096,
    ) -> AsyncIterator[str]:
        """Stream a response, yielding text chunks.

        Args:
            messages: OpenAI-style messages list.
            model: Model ID (uses default_model if not specified).
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.

        Yields:
            Text chunks as they arrive from the API.

        Raises:
            RuntimeError: If all keys are exhausted or non-retryable error.
        """
        model = model or self._default_model
        last_error: Exception | None = None

        for _ in range(len(self._keys)):
            async with self._lock:
                key_state = self._get_next_key()

            if key_state is None:
                raise RuntimeError("No available Gemini API keys (all on cooldown)")

            try:
                async for chunk in self._request_stream(
                    key_state=key_state,
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    yield chunk

                self._mark_success(key_state)
                return
            except _RetryableError as e:
                last_error = e
                continue

        raise RuntimeError(
            f"All {len(self._keys)} Gemini keys failed. Last error: {last_error}"
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_status(self) -> list[dict[str, Any]]:
        """Return status of all keys for diagnostics."""
        now = time.time()
        return [
            {
                "key_suffix": ks.key[-6:],
                "status": ks.status.value,
                "available": ks.is_available,
                "cooldown_remaining": max(0.0, ks.cooldown_until - now),
                "request_count": ks.request_count,
                "error_count": ks.error_count,
            }
            for ks in self._keys
        ]

    # ------------------------------------------------------------------
    # Internal: message conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_messages(
        messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Convert OpenAI-style messages to Gemini format.

        Returns:
            Tuple of (contents, system_instruction).
            system_instruction is extracted from system messages.
        """
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_parts.append(content)
                continue

            # Map roles: assistant -> model, everything else -> user
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({
                "role": gemini_role,
                "parts": [{"text": content}],
            })

        system_instruction = "\n".join(system_parts) if system_parts else None
        return contents, system_instruction

    # ------------------------------------------------------------------
    # Internal: build payload
    # ------------------------------------------------------------------

    def _build_payload(
        self,
        contents: list[dict[str, Any]],
        system_instruction: str | None,
        temperature: float,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        """Build the request payload for the Gemini API."""
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

        # Add google_search tool for grounding
        if self._enable_google_search:
            payload["tools"] = [{"google_search": {}}]

        return payload

    # ------------------------------------------------------------------
    # Internal: non-streaming request
    # ------------------------------------------------------------------

    async def _request_generate(
        self,
        *,
        key_state: KeyState,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int | None,
    ) -> str:
        """Make a non-streaming request to the Gemini API."""
        url = f"{GEMINI_API_BASE}/models/{model}:generateContent"
        params = {"key": key_state.key}

        contents, system_instruction = self._convert_messages(messages)
        payload = self._build_payload(contents, system_instruction, temperature, max_tokens)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, params=params, json=payload)

                if resp.status_code == 200:
                    data = resp.json()
                    return self._extract_text(data)

                if resp.status_code == 429:
                    self._mark_rate_limited(key_state)
                    raise _RetryableError(
                        f"Rate limited (429): {resp.text[:200]}"
                    )

                if resp.status_code >= 500:
                    self._mark_error(key_state)
                    raise _RetryableError(
                        f"Server error ({resp.status_code}): {resp.text[:200]}"
                    )

                if resp.status_code in RETRYABLE_STATUSES:
                    self._mark_rate_limited(key_state)
                    raise _RetryableError(
                        f"Retryable error ({resp.status_code}): {resp.text[:200]}"
                    )

                # Non-retryable error
                raise RuntimeError(
                    f"Gemini API error ({resp.status_code}): {resp.text[:500]}"
                )

        except httpx.HTTPError as e:
            self._mark_rate_limited(key_state)
            raise _RetryableError(f"HTTP error: {e}") from e

    # ------------------------------------------------------------------
    # Internal: streaming request
    # ------------------------------------------------------------------

    async def _request_stream(
        self,
        *,
        key_state: KeyState,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int | None,
    ) -> AsyncIterator[str]:
        """Make a streaming request to the Gemini API."""
        url = f"{GEMINI_API_BASE}/models/{model}:streamGenerateContent"
        params = {"alt": "sse", "key": key_state.key}

        contents, system_instruction = self._convert_messages(messages)
        payload = self._build_payload(contents, system_instruction, temperature, max_tokens)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                async with client.stream("POST", url, params=params, json=payload) as resp:
                    if resp.status_code == 429:
                        self._mark_rate_limited(key_state)
                        await resp.aread()
                        raise _RetryableError(
                            f"Rate limited (429): {resp.text[:200]}"
                        )

                    if resp.status_code >= 500:
                        self._mark_error(key_state)
                        await resp.aread()
                        raise _RetryableError(
                            f"Server error ({resp.status_code}): {resp.text[:200]}"
                        )

                    if resp.status_code in RETRYABLE_STATUSES:
                        self._mark_rate_limited(key_state)
                        await resp.aread()
                        raise _RetryableError(
                            f"Retryable error ({resp.status_code}): {resp.text[:200]}"
                        )

                    if resp.status_code >= 400:
                        await resp.aread()
                        raise RuntimeError(
                            f"Gemini API error ({resp.status_code}): {resp.text[:500]}"
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

                        text = self._extract_text(obj)
                        if text:
                            yield text

        except httpx.HTTPError as e:
            self._mark_rate_limited(key_state)
            raise _RetryableError(f"HTTP error: {e}") from e

    # ------------------------------------------------------------------
    # Internal: response extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        """Extract text from a Gemini API response object."""
        candidates = data.get("candidates", [])
        if not candidates:
            return ""

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])

        text_parts = []
        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])

        return "".join(text_parts)


# ---------------------------------------------------------------------------
# Internal exception for retry logic
# ---------------------------------------------------------------------------


class _RetryableError(Exception):
    """Signals that the request should be retried with another key."""
