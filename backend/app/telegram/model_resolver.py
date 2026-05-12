"""Smart model resolution from user text.

Scans the entire message for a known model alias (any position, not just
the start).  Supports Russian/English aliases, typos, and variations.
If no model keyword is found — picks a random model.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ModelEntry:
    id: str
    label: str
    provider: str  # "fireworks" | "freetheai"
    aliases: tuple[str, ...]  # lowercase trigger words
    supports_vision: bool = False


MODELS: list[ModelEntry] = [
    ModelEntry(
        id="accounts/fireworks/models/deepseek-v4-pro",
        label="DeepSeek V4 Pro",
        provider="fireworks",
        aliases=(
            "deepseek", "дипсик", "дипсік", "діпсік", "deep", "ds",
            "дс", "дип", "дипси", "deepseek-v4",
        ),
    ),
    ModelEntry(
        id="accounts/fireworks/models/kimi-k2p6",
        label="Kimi K2.6",
        provider="fireworks",
        aliases=(
            "kimi", "кими", "кімі", "k2", "к2",
        ),
        supports_vision=True,
    ),
    ModelEntry(
        id="accounts/fireworks/models/qwen3p6-plus",
        label="Qwen3.6 Plus",
        provider="fireworks",
        aliases=(
            "qwen", "квен", "квін", "кьюэн", "кюэн", "qwen3",
        ),
        supports_vision=True,
    ),
    ModelEntry(
        id="accounts/fireworks/models/minimax-m2p7",
        label="MiniMax M2.7",
        provider="fireworks",
        aliases=(
            "minimax", "минимакс", "мінімакс", "mm", "мм", "m2",
        ),
    ),
    ModelEntry(
        id="accounts/fireworks/models/glm-5p1",
        label="GLM 5.1",
        provider="fireworks",
        aliases=(
            "glm", "глм", "zhipu", "жипу",
        ),
    ),
    ModelEntry(
        id="cat/gpt-5.5",
        label="GPT-5.5",
        provider="freetheai",
        aliases=(
            "gpt", "гпт", "chatgpt", "чатгпт", "openai", "опенаи",
            "опенай", "gpt5", "гпт5", "гпт-5",
        ),
    ),
    ModelEntry(
        id="cat/gemini-3-flash",
        label="Gemini 3 Flash",
        provider="freetheai",
        aliases=(
            "gemini", "джемини", "джеміні", "гемини", "гугл", "google",
            "gem", "джем",
            "flash", "флеш", "geminiflash", "джеминифлеш", "gf",
            "гф", "флэш",
        ),
    ),
]

# Build a lookup: alias → ModelEntry
_ALIAS_MAP: dict[str, ModelEntry] = {}
for _m in MODELS:
    for _a in _m.aliases:
        _ALIAS_MAP[_a] = _m


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ResolveResult:
    model: ModelEntry
    prompt: str  # message text with the model keyword stripped
    was_explicit: bool  # True if user explicitly named the model


def resolve(text: str) -> ResolveResult:
    """Detect a model alias anywhere in the text, return model + cleaned prompt.

    Scans every word (and consecutive two-word pair) for a known alias.
    The matched keyword is stripped from the prompt so the AI only sees the
    actual question.  If no alias is found — picks a random model.
    """
    stripped = text.strip()
    if not stripped:
        model = random.choice(MODELS)
        return ResolveResult(model=model, prompt="", was_explicit=False)

    words = stripped.split()
    norm_words = [re.sub(r"[-.]", "", w.lower()) for w in words]

    # Try two-word match at every position first (longer match wins)
    for i in range(len(norm_words) - 1):
        two_norm = f"{norm_words[i]} {norm_words[i + 1]}"
        if two_norm in _ALIAS_MAP:
            model = _ALIAS_MAP[two_norm]
            remaining = words[:i] + words[i + 2:]
            prompt = " ".join(remaining).strip()
            return ResolveResult(model=model, prompt=prompt, was_explicit=True)

    # Try single-word match at every position
    for i, nw in enumerate(norm_words):
        if nw in _ALIAS_MAP:
            model = _ALIAS_MAP[nw]
            remaining = words[:i] + words[i + 1:]
            prompt = " ".join(remaining).strip()
            return ResolveResult(model=model, prompt=prompt, was_explicit=True)

    # No match — random model, full text is the prompt
    model = random.choice(MODELS)
    return ResolveResult(model=model, prompt=stripped, was_explicit=False)


# ---------------------------------------------------------------------------
# Vision model picker
# ---------------------------------------------------------------------------

# Preferred order when the user attaches a photo: Kimi first, Qwen as fallback.
# Only these two vision-capable models are known to reliably handle images on
# Fireworks — the other models on the bot either don't support vision at all
# or misbehave with image inputs.
_VISION_PRIORITY: tuple[str, ...] = (
    "accounts/fireworks/models/kimi-k2p6",
    "accounts/fireworks/models/qwen3p6-plus",
)


def pick_vision_model(preferred: ModelEntry | None = None) -> ModelEntry:
    """Return a vision-capable model.

    If ``preferred`` is already vision-capable — return it as-is so the user's
    explicit choice (e.g. "квен опиши фото") is honoured. Otherwise fall back
    to the first available model from :data:`_VISION_PRIORITY`.
    """
    if preferred is not None and preferred.supports_vision:
        return preferred

    by_id = {m.id: m for m in MODELS}
    for model_id in _VISION_PRIORITY:
        model = by_id.get(model_id)
        if model is not None and model.supports_vision:
            return model

    # Last-resort: any vision model we happen to know about.
    for model in MODELS:
        if model.supports_vision:
            return model

    # Should never happen: the bot ships with Kimi + Qwen as vision models.
    raise RuntimeError("No vision-capable model configured")
