"""Smart model resolution from user text.

Scans the entire message for a known model alias (any position, not just
the start).  Supports Russian/English aliases, typos, and variations.
If no model keyword is found — picks a random model from the pool.
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
    supports_tools: bool = True  # whether the model can use web_search tools
    in_random_pool: bool = True  # whether included in random selection
    fallback_id: str = ""  # fallback model id if primary fails


MODELS: list[ModelEntry] = [
    # --- Fireworks (all support tools via our proxy) ---
    ModelEntry(
        id="accounts/fireworks/models/deepseek-v4-pro",
        label="DeepSeek V4 Pro",
        provider="fireworks",
        aliases=(
            "deepseek", "дипсик", "дипсік", "діпсік", "deep", "ds",
            "дс", "дип", "дипси", "deepseek-v4",
        ),
        in_random_pool=False,  # too slow for random, explicit only
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
        supports_tools=False,
    ),

    # --- FreeTheAI: bbg backend ---
    ModelEntry(
        id="bbg/deepseek-ai/DeepSeek-V4-Flash",
        label="DeepSeek V4 Flash",
        provider="freetheai",
        aliases=("дипсик1", "dsflash", "дсфлеш", "deepseekflash"),
        supports_tools=False,
    ),

    # --- FreeTheAI: bbl backend (tools work) ---
    ModelEntry(
        id="bbl/gemini-3.0-flash",
        label="Gemini 3 Flash",
        provider="freetheai",
        aliases=(
            "gemini", "джемини", "джеміні", "гемини", "гугл", "google",
            "gem", "джем",
            "flash", "флеш", "geminiflash", "джеминифлеш", "gf",
            "гф", "флэш",
        ),
        supports_tools=True,
        fallback_id="cat/gemini-3-flash",
    ),
    ModelEntry(
        id="bbl/gpt-5-mini",
        label="GPT-5 Mini",
        provider="freetheai",
        aliases=(
            "gptmini", "гптмини", "gpt5mini", "гпт5мини", "мини",
        ),
        supports_tools=True,
    ),

    # --- FreeTheAI: cat backend ---
    ModelEntry(
        id="cat/gpt-5.5",
        label="GPT-5.5",
        provider="freetheai",
        aliases=(
            "gpt", "гпт", "chatgpt", "чатгпт", "openai", "опенаи",
            "опенай", "gpt5", "гпт5", "гпт-5",
        ),
        supports_tools=False,
    ),
    ModelEntry(
        id="cat/claude-4-5-sonnet",
        label="Claude 4.5 Sonnet",
        provider="freetheai",
        aliases=(
            "claude", "клод", "клауд", "sonnet", "сонет", "антропик",
            "anthropic",
        ),
        supports_tools=False,
    ),
]

# Build a lookup: alias → ModelEntry
_ALIAS_MAP: dict[str, ModelEntry] = {}
for _m in MODELS:
    for _a in _m.aliases:
        _ALIAS_MAP[_a] = _m

# Pool for random selection (excludes models flagged out)
_RANDOM_POOL: list[ModelEntry] = [m for m in MODELS if m.in_random_pool]

# Models that support web search tools
SEARCH_MODELS: list[ModelEntry] = [m for m in MODELS if m.supports_tools]


# ---------------------------------------------------------------------------
# Search-need detection
# ---------------------------------------------------------------------------

_SEARCH_KEYWORDS = re.compile(
    r"(?i)"
    r"(?:погод[аеу]|weather|новост[ьией]|news|курс|price|цен[аеуы]|"
    r"сколько стоит|стоимость|сегодня|вчера|завтра|"
    r"today|yesterday|tomorrow|текущ|актуальн|последни[йехм]|"
    r"свежи[йехм]|latest|current|recent|"
    r"дата выход|когда выйд|release date|when.+(?:release|come out)|"
    r"счёт|score|результат матч|"
    r"что случил|что произош|what happened|"
    r"градус|температур|скок|скольк|щас?\b|сейчас|"
    r"degrees|temperature|forecast|прогноз)"
)


def needs_search(text: str) -> bool:
    """Heuristic: does the user's query likely need up-to-date info?"""
    return bool(_SEARCH_KEYWORDS.search(text))


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
    If the query needs current info and the random model can't search,
    a search-capable model is chosen instead.
    """
    stripped = text.strip()
    if not stripped:
        model = random.choice(_RANDOM_POOL)
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

    # No explicit model — pick random, but prefer search-capable if needed
    if needs_search(stripped) and SEARCH_MODELS:
        model = random.choice(SEARCH_MODELS)
    else:
        model = random.choice(_RANDOM_POOL)
    return ResolveResult(model=model, prompt=stripped, was_explicit=False)
