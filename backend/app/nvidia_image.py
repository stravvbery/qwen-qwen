"""Text-to-image generation via the NVIDIA Build (NIM) image endpoints.

The NIM image catalog exposes each generator at a dedicated path under
``https://ai.api.nvidia.com/v1/genai/<vendor>/<model>``. Response shape
varies slightly between models: some return a single ``image`` base64
string, some an ``artifacts`` array, some a preview ``image_url``. This
module normalises all of that into raw image bytes so ``handlers.py``
can send a photo to Telegram via ``BufferedInputFile``.

The default model is Qwen Image (``qwen/qwen-image``), picked because the
user explicitly asked for it, but the caller can override via the
``NVIDIA_IMAGE_MODEL`` env var or the ``model`` argument.
"""

from __future__ import annotations

import base64
import binascii
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .config import settings
from .fireworks import FireworksError

log = logging.getLogger(__name__)


class NvidiaImageError(FireworksError):
    """Raised when the NVIDIA image endpoint returns a non-2xx response."""


@dataclass(slots=True)
class GeneratedImage:
    """A single image produced by the NIM ``genai`` endpoint."""

    data: bytes
    mime: str = "image/png"
    seed: int | None = None
    model: str = ""


def _auth_headers() -> dict[str, str]:
    key = settings.nvidia_api_key
    if not key:
        raise NvidiaImageError(
            "NVIDIA_API_KEY is not set on the server. "
            "Cannot generate images."
        )
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def generate_image(
    *,
    prompt: str,
    model: str | None = None,
    height: int = 1024,
    width: int = 1024,
    steps: int = 30,
    seed: int = 0,
) -> GeneratedImage:
    """Generate one image from ``prompt`` using a NIM text-to-image model.

    Parameters mirror the NIM contract: ``height``/``width`` are capped to
    1024 on most preview endpoints, ``steps`` trades quality for latency,
    and ``seed=0`` asks the server for a random seed.

    The model id is the NIM catalog slug, e.g. ``qwen/qwen-image`` or
    ``black-forest-labs/flux.1-dev``. We default to whatever is configured
    via ``NVIDIA_IMAGE_MODEL`` — Qwen Image on fresh installs.
    """
    if not prompt.strip():
        raise NvidiaImageError("Image prompt is empty — nothing to render.")

    model_id = (model or settings.nvidia_image_model).strip()
    url = f"{settings.nvidia_image_base_url.rstrip('/')}/{model_id}"

    # Single shared payload that works for Qwen Image, FLUX.1-dev, FLUX.2 and
    # Stable Diffusion 3. Fields the individual model doesn't recognise are
    # silently ignored by the NIM server — we deliberately send the union of
    # parameters so one call site handles all catalog variants.
    payload: dict[str, Any] = {
        "prompt": prompt.strip(),
        "height": height,
        "width": width,
        "cfg_scale": 3.5,
        "samples": 1,
        "seed": seed,
        "steps": steps,
        "mode": "Image Generation",
        # SD3 expects ``text_prompts`` instead of ``prompt``. Sending both
        # keeps the single-call-shape promise.
        "text_prompts": [{"text": prompt.strip(), "weight": 1.0}],
        "output_format": "png",
    }

    timeout = httpx.Timeout(
        # Image generation can take 30-90s, much longer than chat streams.
        # Respect the global request timeout ceiling but extend up to 180s.
        max(settings.request_timeout_seconds, 180.0),
        connect=15.0,
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(url, headers=_auth_headers(), json=payload)
        except httpx.HTTPError as exc:
            raise NvidiaImageError(
                f"NVIDIA image request failed: {type(exc).__name__}: {exc}"
            ) from exc

    if resp.status_code >= 400:
        raise NvidiaImageError(
            f"NVIDIA image API returned {resp.status_code}: {resp.text[:500]}"
        )

    try:
        obj = resp.json()
    except ValueError as exc:
        raise NvidiaImageError(
            f"NVIDIA image API returned non-JSON body: {resp.text[:200]}"
        ) from exc

    data, returned_seed = await _extract_bytes(obj, client_timeout=timeout)
    if not data:
        # Surface the raw payload so the user can see what the server said —
        # NIM returns safety rejections / validation errors as structured
        # fields inside ``artifacts`` and ``detail``.
        snippet = _summarise(obj)
        raise NvidiaImageError(
            f"NVIDIA image API returned no image data. "
            f"Response summary: {snippet[:400]}"
        )

    return GeneratedImage(
        data=data,
        mime="image/png",
        seed=returned_seed,
        model=model_id,
    )


async def _extract_bytes(
    obj: Any, *, client_timeout: httpx.Timeout,
) -> tuple[bytes, int | None]:
    """Normalise the NIM image response into ``(bytes, seed)``.

    Handles the four shapes NVIDIA currently returns:

    * ``{"image": "<b64>"}`` — FLUX.1-dev, Qwen Image preview.
    * ``{"artifacts": [{"image": "<b64>", "seed": ...}]}`` — SDXL.
    * ``{"image_url": "https://..."}`` — FLUX.2 preview (requires a follow-up
      GET to fetch the bytes).
    * ``{"output": "<b64>"}`` — older FLUX / SD endpoints.
    """
    seed: int | None = None

    # Shape 1: flat ``image`` / ``output`` string.
    for key in ("image", "output"):
        b64 = obj.get(key)
        if isinstance(b64, str) and b64:
            return _decode_maybe_dataurl(b64), obj.get("seed")

    # Shape 2: ``artifacts`` list.
    artifacts = obj.get("artifacts")
    if isinstance(artifacts, list) and artifacts:
        first = artifacts[0]
        if isinstance(first, dict):
            b64 = first.get("image") or first.get("base64")
            if isinstance(b64, str) and b64:
                seed = first.get("seed") if isinstance(first.get("seed"), int) else None
                return _decode_maybe_dataurl(b64), seed

    # Shape 3: ``image_url`` (download it).
    image_url = obj.get("image_url") or obj.get("url")
    if isinstance(image_url, str) and image_url.startswith(("http://", "https://")):
        seed = obj.get("seed") if isinstance(obj.get("seed"), int) else None
        async with httpx.AsyncClient(timeout=client_timeout) as client:
            try:
                r = await client.get(image_url)
            except httpx.HTTPError as exc:
                raise NvidiaImageError(
                    f"Failed to download generated image from {image_url}: {exc}"
                ) from exc
            if r.status_code >= 400:
                raise NvidiaImageError(
                    f"Download of generated image returned {r.status_code}"
                )
            return r.content, seed

    # Unknown shape — caller will surface a friendly error.
    return b"", seed


def _decode_maybe_dataurl(payload: str) -> bytes:
    """Decode a raw base64 string or a ``data:image/...;base64,...`` URL."""
    s = payload.strip()
    if s.startswith("data:"):
        # ``data:image/png;base64,....``
        try:
            s = s.split(",", 1)[1]
        except IndexError:
            return b""
    try:
        return base64.b64decode(s, validate=False)
    except (binascii.Error, ValueError):
        return b""


def _summarise(obj: Any) -> str:
    """Return a short string describing an unexpected response payload."""
    try:
        import json

        return json.dumps(obj, ensure_ascii=False)[:500]
    except (TypeError, ValueError):
        return repr(obj)[:500]


# ---------------------------------------------------------------------------
# Prompt trigger detection for Telegram handlers
# ---------------------------------------------------------------------------

# The user asked for "через слово нарисуй или создай фото". We accept a few
# common variants (English + Russian, with/without verb suffixes) so both
# ``нарисуй кота в шляпе`` and ``create a picture of a cat`` route to the
# image path.
_IMAGE_TRIGGERS: tuple[str, ...] = (
    # Russian imperative / generic verbs
    "нарисуй", "нарисуйте", "рисуй", "рисуни", "рисуешь ",
    "создай фото", "создай картинку", "создай изображение",
    "сгенерируй фото", "сгенерируй картинку", "сгенерируй изображение",
    "сделай фото", "сделай картинку", "сделай изображение",
    "сделай арт", "сгенерируй арт",
    # English (for completeness — bot works in both)
    "draw ", "generate image", "create image", "create a picture",
    "generate a picture", "make an image", "make a picture",
)


def detect_image_prompt(text: str) -> str | None:
    """Return the image-generation subject if ``text`` looks like an image
    request, else ``None``.

    We strip the trigger word plus any leading punctuation so the caller can
    feed the result straight into :func:`generate_image` without the verb.
    If the subject ends up empty the function returns ``None`` so the
    normal chat path still runs (``нарисуй`` on its own isn't a useful
    prompt).
    """
    if not text:
        return None
    haystack = text.strip().lower()
    # We match the *first* trigger whose prefix appears in the haystack —
    # if multiple triggers match we pick the longest one so ``создай фото``
    # wins over a hypothetical ``создай``.
    best_start = -1
    best_len = 0
    best_trigger = ""
    for trig in _IMAGE_TRIGGERS:
        pos = haystack.find(trig)
        if pos < 0:
            continue
        if len(trig) > best_len:
            best_start = pos
            best_len = len(trig)
            best_trigger = trig
    if best_start < 0:
        return None

    # Take everything *after* the trigger as the subject, then strip leading
    # punctuation (colon/comma/dash) and whitespace.
    raw_subject = text[best_start + best_len:].lstrip(" \t\n\r:,.-—–")
    # Guard against the degenerate "нарисуй" with no subject.
    if not raw_subject or len(raw_subject) < 2:
        log.info(
            "Image trigger %r found in %r but no subject — falling back to chat",
            best_trigger, text[:60],
        )
        return None
    return raw_subject
