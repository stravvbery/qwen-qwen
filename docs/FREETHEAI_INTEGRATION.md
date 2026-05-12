# Plan: integrate freetheai.xyz as a second model provider

**Status:** plan only — no code in this PR. Implementation is deferred to a
follow-up PR.

[freetheai.xyz](https://freetheai.xyz/docs/) is an OpenAI-compatible API
proxy that fronts hundreds of models (Claude, GPT, Gemini, Qwen, Kimi,
GLM, DeepSeek, plus distilled / community models) behind a single key.
The user signed up and confirmed a working key with these five models:

- `cat/claude-opus-4-7`
- `cat/gemini-3-1-pro`
- `cat/gpt-5.5`
- `fth/reedmayhew/gemini-3.1-pro-distill-reasoning-12B-QKVO-HF`
- `yng/gemini-3-1-pro`

All five returned `200 OK` on `pong` + `17×23 = 391` smoke tests with
latencies of 6–11 s. Rate limit on the free tier is **10 RPM, 1
concurrent**, with a daily `/checkin` required on Discord.

## 1. Why bother

The current Grebeshok Chat is hard-wired to a single Fireworks key and
five fictional Fireworks model IDs. Adding freetheai.xyz gives the user
access to flagship frontier models (Opus, GPT-5.5, Gemini 3.1 Pro) for
free, behind the same SSE/tool-calling/reasoning UX that already works.
Because the API is OpenAI-compatible the additions are mechanical: a
new client module + a provider tag on each model.

## 2. Current architecture (one provider, one key)

```
frontend/                                    backend/
  ModelPicker.tsx                              app/routes.py
    └─ shows list from /api/models               ├─ MODELS = [5 hard-coded Fireworks IDs]
                                                 ├─ POST /chats/{id}/messages
                                                 │   └─ stream_chat(model=…) from app/fireworks.py
                                                 │       └─ httpx → settings.fireworks_base_url
                                                 │                  /chat/completions
                                                 └─ has_any_provider() decides whether to enable tools
```

Everything calls `app.fireworks.stream_chat`/`chat_completion`, which
reads `settings.fireworks_api_key` and `settings.fireworks_base_url`
directly. There is no notion of "provider" — a model id is just an
opaque string passed straight through to Fireworks.

## 3. Target architecture

```
frontend stays mostly the same. Backend grows a tiny provider layer:

app/
  config.py        ── adds freetheai_api_key, freetheai_base_url
  providers/
    __init__.py    ── resolve(model_id) -> Provider
    base.py        ── Provider protocol: stream_chat(), chat_completion()
    fireworks.py   ── existing client, moved here unchanged
    freetheai.py   ── new OpenAI-compatible client (mostly a copy of
                       fireworks.py with a different base_url + auth source)
  routes.py        ── MODELS gains a `provider` tag; the route delegates
                       to providers.resolve(model_id) instead of calling
                       app.fireworks directly.
```

Key insight: because freetheai is OpenAI-compatible and we already speak
the OpenAI streaming protocol (`role`, `delta.content`,
`delta.reasoning_content`, `tool_calls[].index`, `[DONE]`), the new
client is ~95 % identical to the existing Fireworks client. The
provider abstraction is mostly so the model id-to-base-url-and-key
mapping is explicit rather than implicit.

## 4. File-by-file change list

### 4.1 `backend/app/config.py`

Add three settings (preserve the existing `fireworks_*` ones):

```python
freetheai_api_key:  str = Field(default="", alias="FREETHEAI_API_KEY")
freetheai_base_url: str = Field(
    default="https://api.freetheai.xyz/v1",
    alias="FREETHEAI_BASE_URL",
)
# Conservative client-side rate-limit knobs so we don't burn the free
# 10 RPM / 1 concurrent budget on flaky retries.
freetheai_min_interval_seconds: float = Field(
    default=6.5, alias="FREETHEAI_MIN_INTERVAL_SECONDS",
)
```

Update `backend/.env.example` (currently only documents `FIREWORKS_*`)
with the new keys and a comment pointing at https://freetheai.xyz/docs/.

### 4.2 `backend/app/providers/`

New package with three small files.

`backend/app/providers/base.py`:

```python
from collections.abc import AsyncIterator
from typing import Any, Protocol
from app.fireworks import StreamDelta  # reuse the existing dataclasses

class Provider(Protocol):
    name: str  # "fireworks" | "freetheai" – purely for logs / errors
    async def stream_chat(
        self, *, model: str, messages: list[dict[str, Any]],
        temperature: float = 0.7, max_tokens: int | None = 4096,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamDelta]: ...
    async def chat_completion(
        self, *, model: str, messages: list[dict[str, Any]],
        temperature: float = 0.7, max_tokens: int | None = 4096,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...
```

`backend/app/providers/fireworks.py`:

The current `app/fireworks.py` already speaks this protocol. Move its
body into `providers/fireworks.py` as a class with the same two
methods, keep the `StreamDelta` and `ToolCall` dataclasses where they
are (so `routes.py` does not have to change its imports for them).
Re-export from `app/fireworks.py` for backwards compatibility:

```python
# app/fireworks.py
from .providers.fireworks import FireworksProvider, FireworksError
from .providers.base import StreamDelta, ToolCall  # if we move them
```

`backend/app/providers/freetheai.py`:

```python
import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
import httpx
from .base import Provider
from ..config import settings
from ..fireworks import StreamDelta, ToolCall, FireworksError as _Err

class FreeTheAIError(_Err):
    """Same shape as FireworksError so routes.py can keep one except."""

class FreeTheAIProvider:
    name = "freetheai"
    _lock = asyncio.Lock()
    _last_call_at: float = 0.0

    def _auth(self) -> dict[str, str]:
        key = settings.freetheai_api_key
        if not key:
            raise FreeTheAIError("FREETHEAI_API_KEY is not set on the server.")
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _throttle(self) -> None:
        # Client-side spacing to keep us under 10 RPM / 1 concurrent.
        async with self._lock:
            now = asyncio.get_event_loop().time()
            wait = settings.freetheai_min_interval_seconds - (now - self._last_call_at)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call_at = asyncio.get_event_loop().time()

    async def stream_chat(self, ...): ...   # body = copy of fireworks.stream_chat,
                                            # with base_url and auth swapped, plus
                                            # `await self._throttle()` at the top.
    async def chat_completion(self, ...): ... # same, copy of fireworks.chat_completion.
```

`backend/app/providers/__init__.py`:

```python
from .base import Provider
from .fireworks import FireworksProvider
from .freetheai import FreeTheAIProvider

_FIREWORKS = FireworksProvider()
_FREETHEAI = FreeTheAIProvider()

def resolve(model_id: str) -> Provider:
    # Routing is purely by model-id prefix. Keep this list in sync with
    # routes.MODELS.
    if model_id.startswith("accounts/fireworks/"):
        return _FIREWORKS
    if model_id.startswith(("cat/", "fth/", "yng/", "rev/", "glm/", "img/", "vhr/")):
        return _FREETHEAI
    raise ValueError(f"No provider for model id {model_id!r}")
```

### 4.3 `backend/app/schemas.py`

Add a `provider` field to `ModelInfo` so the frontend can render a
provider badge ("Fireworks" vs "FreeTheAI") next to each option:

```python
class ModelInfo(BaseModel):
    id: str
    label: str
    description: str
    provider: Literal["fireworks", "freetheai"] = "fireworks"
    context_length: int | None = None
    supports_reasoning: bool = False
    supports_vision: bool = False
```

### 4.4 `backend/app/routes.py`

Two small changes:

1. Extend the `MODELS` list. Add one entry per freetheai model. Suggested
   initial set (these five are already confirmed working):

   ```python
   schemas.ModelInfo(
       id="cat/claude-opus-4-7",
       label="Claude Opus 4.7",
       description="Anthropic Claude Opus 4.7 (через freetheai.xyz).",
       provider="freetheai",
       supports_reasoning=True,
   ),
   schemas.ModelInfo(
       id="cat/gemini-3-1-pro",
       label="Gemini 3.1 Pro",
       description="Google Gemini 3.1 Pro (через freetheai.xyz).",
       provider="freetheai",
       supports_reasoning=True,
   ),
   schemas.ModelInfo(
       id="cat/gpt-5.5",
       label="GPT-5.5",
       description="OpenAI GPT-5.5 (через freetheai.xyz).",
       provider="freetheai",
       supports_reasoning=True,
   ),
   schemas.ModelInfo(
       id="yng/gemini-3-1-pro",
       label="Gemini 3.1 Pro (yng)",
       description="Альтернативная маршрутизация Gemini 3.1 Pro.",
       provider="freetheai",
       supports_reasoning=True,
   ),
   schemas.ModelInfo(
       id="fth/reedmayhew/gemini-3.1-pro-distill-reasoning-12B-QKVO-HF",
       label="Gemini 3.1 Pro Distill 12B",
       description="Reedmayhew distill 12B с reasoning.",
       provider="freetheai",
       supports_reasoning=True,
   ),
   ```

2. Replace the two `stream_chat(...)` / `chat_completion(...)` call sites
   in `event_stream` with `providers.resolve(model_id).stream_chat(...)`.
   Same for the non-streaming chat_completion path. Catch
   `FireworksError` *and* `FreeTheAIError` (or just `_Err`, the shared
   parent).

### 4.5 Frontend

Two cosmetic changes; UX is otherwise unchanged.

- `frontend/src/lib/types.ts` — add `provider: "fireworks" | "freetheai"`
  to `ModelInfo`.
- `frontend/src/components/ModelPicker.tsx` — show a small provider
  badge next to each label (e.g. a coloured chip with the provider
  initial). Filter the dropdown by provider if the list grows past
  ~10 items.

No changes needed to streaming, reasoning panel, tool-calling UI, web
search, or attachments. Vision support per model is already gated by
`supports_vision`; just keep that flag accurate for the new entries
(none of the initial five support vision — the user can extend later).

## 5. Secrets

Add a new Devin secret `FREETHEAI_API_KEY` with `save_scope=user` and
the current key (`sta_…`) as the value. The blueprint's
`backend/.env` writer should append `FREETHEAI_API_KEY=...` alongside
the existing `FIREWORKS_API_KEY=...` line. No org-level secret needed.

## 6. Rate-limit handling (free tier = 10 RPM, 1 concurrent)

- The `_throttle()` in `FreeTheAIProvider` enforces ≥ 6.5 s between
  client-initiated outbound requests. With 1 concurrent allowed, that
  keeps us under 10 RPM with margin.
- On `HTTP 429`, surface the raw error message via the existing
  `event: error` SSE event — the new MessageBubble rendering already
  shows it in a red banner.
- We do **not** auto-retry server-side. If the user hits 429 we let the
  frontend show the error so they understand the budget cap.

## 7. Daily `/checkin` requirement

freetheai.xyz requires a Discord `/checkin` slash command per UTC day
or the key starts 401'ing. Options, in order of preference:

1. **Document it.** Mention in the README that the user must run
   `/checkin` in the freetheai Discord once a day. Cheapest; matches
   reality.
2. **Health probe.** Add a small `/api/freetheai/health` endpoint that
   pings `GET /v1/models` and surfaces "key needs checkin" in the UI.
   Helpful but not necessary for v1.
3. **Auto-checkin.** Out of scope — would require a Discord bot token,
   which is more setup than it's worth.

Go with option 1 for the first cut.

## 8. Testing checklist for the implementation PR

- [ ] `pong` smoke test, web search **off**, on all five new models —
      expect `200 OK` with non-empty content within 15 s each.
- [ ] `pong` smoke test, web search **on**, on the same five — expect
      tool_status events + non-empty content. Re-uses the empty-content
      fix from PR #12.
- [ ] Frontend ModelPicker shows the new models with a "FreeTheAI"
      badge and groups them visually away from Fireworks entries.
- [ ] Hit the 10 RPM cap deliberately (12 quick sends) and confirm the
      red error banner shows the 429 text instead of an empty bubble.
- [ ] Confirm Fireworks-rooted models still work (the routing must not
      break the existing five).

## 9. Open questions

- Do we want to expose the **image generation** routes
  (`POST /v1/images/generations`, `POST /v1/images/edits`) too? That
  would need a new UI surface; skip for v1.
- Should the model list be filterable in the picker (search box) once
  it grows past ~10 entries? Yes, but as a follow-up after the basic
  integration lands.
- Long-term: it would be cleaner to make `MODELS` data-driven (load
  from a JSON or DB) so adding a model does not require a code change.
  Out of scope for the first integration PR.

## 10. Estimated diff size

- `backend/app/config.py`: +6 lines
- `backend/app/providers/`: +200 lines (new package, three files)
- `backend/app/fireworks.py`: shrinks to a re-export shim
- `backend/app/routes.py`: ~+40 lines (five model entries + provider
  dispatch)
- `backend/app/schemas.py`: +1 field
- `backend/.env.example`: +4 lines
- `frontend/src/lib/types.ts`: +1 field
- `frontend/src/components/ModelPicker.tsx`: ~+20 lines (badge + small
  filter)
- `README.md` / `SESSION_HANDOFF.md`: docs notes about the daily
  `/checkin`.

Total: roughly a single afternoon's worth of work, no migrations, no
new dependencies.
