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
    provider: str  # "fireworks" | "freetheai" | "nvidia"
    aliases: tuple[str, ...]  # lowercase trigger words
    supports_tools: bool = True  # whether the model can use web_search tools
    in_random_pool: bool = True  # whether included in random selection
    fallback_id: str = ""  # fallback model id if primary fails
    supports_vision: bool = False  # whether the model accepts image inputs


# Model ID conventions:
#   Fireworks: ``accounts/fireworks/models/<slug>``
#   FreeTheAI: ``bbl/<slug>`` or ``cat/<slug>``
#   NVIDIA Build: ``<vendor>/<slug>`` (OpenAI-compatible chat completions at
#     integrate.api.nvidia.com). Catalog slugs like ``deepseek-ai/deepseek-v3.1``
#     are passed as-is to the /v1/chat/completions endpoint.
MODELS: list[ModelEntry] = [
    # --- NVIDIA Build (primary provider for DeepSeek V4 Pro / GLM) ---
    # Aliases ``deepseek``/``дипсик``/``glm``/``глм``/``kimi``/``кими`` now
    # resolve to the NVIDIA-hosted variants; the Fireworks entries below act
    # as automatic fallbacks via the stall/error chain.
    ModelEntry(
        id="deepseek-ai/deepseek-v3.1",
        label="DeepSeek V4 Pro",
        provider="nvidia",
        aliases=(
            "deepseek", "дипсик", "дипсік", "діпсік", "deep", "ds",
            "дс", "дип", "дипси", "deepseek-v4",
        ),
        # Kept out of the random pool for parity with the old Fireworks
        # behaviour — it's still the slowest reasoning model we expose and
        # users generally pick it explicitly.
        in_random_pool=False,
    ),
    ModelEntry(
        id="deepseek-ai/deepseek-v3-flash",
        label="DeepSeek Flash",
        provider="nvidia",
        aliases=(
            "deepseekflash", "дипсикфлеш", "дипсик-флеш", "ds-flash",
            "ds flash", "dsflash", "dsf", "dsfl", "дсфл", "дсфлеш",
            "deepseek flash", "дипсик флеш",
        ),
    ),
    ModelEntry(
        id="mistralai/mistral-medium-3.5-instruct",
        label="Mistral Medium 3.5",
        provider="nvidia",
        aliases=(
            "mistral", "мистраль", "містраль", "mistralmedium",
            "мистральмедиум", "mistral35", "мистраль35",
            "mistralmedium35", "mm35", "мм35",
        ),
    ),
    ModelEntry(
        id="moonshotai/kimi-k2.5",
        label="Kimi K2.6",
        provider="nvidia",
        aliases=(
            "kimi", "кими", "кімі", "k2", "к2", "moonshot", "мунщот",
        ),
        # NVIDIA NIM Kimi supports OpenAI-style tool calling.
        supports_tools=True,
    ),
    ModelEntry(
        id="z-ai/glm-4.7",
        label="GLM 5.1",
        provider="nvidia",
        aliases=(
            "glm", "глм", "zhipu", "жипу", "z-ai", "zai",
        ),
        supports_tools=True,
    ),

    # --- Fireworks (fallback for the NVIDIA entries above + primary for
    # the models NVIDIA doesn't host) ---
    ModelEntry(
        id="accounts/fireworks/models/deepseek-v4-pro",
        label="DeepSeek V4 Pro (FW)",
        provider="fireworks",
        aliases=(
            # Secondary aliases so power users can force the Fireworks
            # variant when the NVIDIA one is misbehaving.
            "deepseek-fw", "дипсик-fw", "dsfw",
        ),
        in_random_pool=False,
    ),
    ModelEntry(
        id="accounts/fireworks/models/kimi-k2p6",
        label="Kimi K2.6 (FW)",
        provider="fireworks",
        aliases=(
            "kimifw", "кимифw", "k2fw", "к2fw",
        ),
        supports_tools=False,
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
        label="GLM 5.1 (FW)",
        provider="fireworks",
        aliases=(
            "glmfw", "глмfw",
        ),
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

# Index for quick lookup by id (used by the fallback chain)
_BY_ID: dict[str, ModelEntry] = {m.id: m for m in MODELS}


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


# ---------------------------------------------------------------------------
# Vision model picker
# ---------------------------------------------------------------------------

# Preferred order when the user attaches a photo: Kimi first, Qwen as fallback.
# Only these two models on Fireworks reliably handle image inputs — the
# remaining models either don't support vision at all or misbehave on images.
_VISION_PRIORITY: tuple[str, ...] = (
    "accounts/fireworks/models/kimi-k2p6",
    "accounts/fireworks/models/qwen3p6-plus",
)


def pick_vision_model(preferred: ModelEntry | None = None) -> ModelEntry:
    """Return a vision-capable model.

    If ``preferred`` is already vision-capable, return it untouched so an
    explicit user choice (e.g. caption ''квен опиши фото'') is honoured.
    Otherwise fall back to the first available model from
    :data:`_VISION_PRIORITY`.
    """
    if preferred is not None and preferred.supports_vision:
        return preferred

    for model_id in _VISION_PRIORITY:
        model = _BY_ID.get(model_id)
        if model is not None and model.supports_vision:
            return model

    # Last-resort: any vision-capable model we know about.
    for model in MODELS:
        if model.supports_vision:
            return model

    # Should never happen: the bot ships with Kimi + Qwen as vision models.
    raise RuntimeError("No vision-capable model configured")


# ---------------------------------------------------------------------------
# Fallback chain — ordered list of models to try when the current one stalls.
# ---------------------------------------------------------------------------

# Ordered by observed responsiveness on our Fireworks / FreeTheAI / NVIDIA
# proxies.  Fast text-only models come first (they usually answer within
# a few seconds); providers are interleaved so a whole-provider outage
# still has a live fallback. Vision fallbacks are handled separately below.
#
# DeepSeek V4 Pro (NVIDIA + Fireworks copies) is intentionally kept out of
# this chain because it's a slow reasoning model and would not help with a
# "no-liveness" timeout. If the user explicitly picks DeepSeek we'll still
# try it first, then fall through to these faster candidates.
_FALLBACK_CHAIN_IDS: tuple[str, ...] = (
    "accounts/fireworks/models/qwen3p6-plus",
    "accounts/fireworks/models/minimax-m2p7",
    "z-ai/glm-4.7",
    "moonshotai/kimi-k2.5",
    "deepseek-ai/deepseek-v3-flash",
    "mistralai/mistral-medium-3.5-instruct",
    "accounts/fireworks/models/kimi-k2p6",
    "accounts/fireworks/models/glm-5p1",
    "bbl/gemini-3.0-flash",
    "cat/gpt-5.5",
    "cat/claude-4-5-sonnet",
    "bbl/gpt-5-mini",
)


def fallback_chain(primary: ModelEntry) -> list[ModelEntry]:
    """Return an ordered list of fallback models to try after ``primary``.

    The list excludes ``primary`` itself and any model not in the registry.
    Vision-capable models are kept at the top of the chain when ``primary``
    supports vision, so a stalled vision request fails over to another VLM
    rather than to a text-only model that would drop the image.

    Same-family precedence: if ``primary`` has a known Fireworks twin
    (e.g. NVIDIA DeepSeek V4 Pro → Fireworks DeepSeek V4 Pro) we try the
    twin before the generic fast fallbacks so a provider-specific outage
    stays invisible to the user — they still get an answer from the same
    model family.
    """
    chain: list[ModelEntry] = []
    seen = {primary.id}

    # Same-family twin: matches on model ``label`` prefix (e.g. both
    # ``DeepSeek V4 Pro`` and ``DeepSeek V4 Pro (FW)`` share the prefix).
    # This is cheap and deliberately tolerant — when a twin exists it goes
    # first so provider-level outages don't force a model swap.
    family_key = primary.label.split(" (")[0].lower()
    for candidate in MODELS:
        if candidate.id in seen:
            continue
        if candidate.provider == primary.provider:
            continue
        if candidate.label.split(" (")[0].lower() == family_key:
            chain.append(candidate)
            seen.add(candidate.id)
            break  # one twin is enough

    for model_id in _FALLBACK_CHAIN_IDS:
        if model_id in seen:
            continue
        candidate = _BY_ID.get(model_id)
        if candidate is None:
            continue
        if primary.supports_vision and not candidate.supports_vision:
            # For a vision request, prefer other VLMs; skip text-only models
            # here and we'll re-add them at the end as best-effort text
            # fallbacks below.
            continue
        chain.append(candidate)
        seen.add(model_id)

    # If this was a vision request, append text-only models at the tail so
    # we still have something to try if every VLM is down (the request will
    # silently lose the image, but at least the user gets an answer).
    if primary.supports_vision:
        for model_id in _FALLBACK_CHAIN_IDS:
            if model_id in seen:
                continue
            candidate = _BY_ID.get(model_id)
            if candidate is None:
                continue
            chain.append(candidate)
            seen.add(model_id)

    return chain
