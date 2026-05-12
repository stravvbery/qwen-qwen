"""Smart model resolution from user text.

Parses the first word(s) of a message to detect which AI model the user wants.
Supports Russian/English aliases, typos, and variations.
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
    ),
    ModelEntry(
        id="accounts/fireworks/models/qwen3p6-plus",
        label="Qwen3.6 Plus",
        provider="fireworks",
        aliases=(
            "qwen", "квен", "квін", "кьюэн", "кюэн", "qwen3",
        ),
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
        id="cat/claude-opus-4-7",
        label="Claude Opus 4.7",
        provider="freetheai",
        aliases=(
            "claude", "клод", "клауд", "клоде", "клауде", "клоуд",
            "cloud", "opus", "опус", "антропик", "anthropic",
            "клауді", "кло", "клау",
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
        id="pool/gemini-3-1-pro",
        label="Gemini 3.1 Pro",
        provider="freetheai",
        aliases=(
            "gemini", "джемини", "джеміні", "гемини", "гугл", "google",
            "gem", "джем",
        ),
    ),
    ModelEntry(
        id="gemini/gemini-2.0-flash",
        label="Gemini 2.0 Flash",
        provider="gemini",
        aliases=(
            "flash", "флеш", "geminiflash", "джеминифлеш", "gf",
            "гф", "флэш", "2flash",
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
    """Parse user text: detect model keyword at the start, return model + cleaned prompt."""
    stripped = text.strip()
    if not stripped:
        model = random.choice(MODELS)
        return ResolveResult(model=model, prompt="", was_explicit=False)

    # Try to match first 1-2 words as a model alias
    # Split on whitespace, take up to 2 tokens from the start
    words = stripped.split(None, 2)

    # Try two-word match first (e.g. "deep seek ...")
    if len(words) >= 2:
        two_word = f"{words[0]} {words[1]}".lower()
        # Normalize: remove hyphens, dots
        two_norm = re.sub(r"[-.]", "", two_word)
        if two_norm in _ALIAS_MAP:
            model = _ALIAS_MAP[two_norm]
            prompt = words[2] if len(words) > 2 else ""
            return ResolveResult(model=model, prompt=prompt, was_explicit=True)

    # Try single-word match
    first = words[0].lower()
    first_norm = re.sub(r"[-.]", "", first)

    if first_norm in _ALIAS_MAP:
        model = _ALIAS_MAP[first_norm]
        rest = stripped[len(words[0]):].strip()
        return ResolveResult(model=model, prompt=rest, was_explicit=True)

    # No match — random model, full text is the prompt
    model = random.choice(MODELS)
    return ResolveResult(model=model, prompt=stripped, was_explicit=False)
