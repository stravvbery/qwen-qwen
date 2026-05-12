"""Telegram message handlers — the core logic of the bot.

Handles:
- Direct messages in PM (any text → AI response)
- Inline queries (@bot query in any chat)
- Guest mode (Bot API 10.0+): receive ``guest_message`` updates from chats
  the bot is not a member of and reply via ``answerGuestQuery``.
- Status indicators (typing, searching, etc.)
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import random
import re
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot, Router, types
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from ..fireworks import FireworksError, ToolCall
from ..fireworks import stream_chat as fireworks_stream_chat
from ..freetheai_client import FreeTheAIError
from ..freetheai_client import stream_chat as freetheai_stream_chat
from ..web_tools import TOOL_DEFINITIONS, execute_tool_call, has_any_provider
from .model_resolver import (
    MODELS,
    ModelEntry,
    ResolveResult,
    pick_vision_model,
    resolve,
)

log = logging.getLogger(__name__)

router = Router()

# How often to edit the message during streaming (avoid Telegram rate limits)
_EDIT_INTERVAL = 1.5  # seconds
_MAX_MSG_LEN = 4096  # Telegram message limit

# ---------------------------------------------------------------------------
# In-memory conversation store for reply-chain context
# Maps (chat_id, message_id) → {"role": ..., "content": ..., "reply_to": ...}
# ---------------------------------------------------------------------------
_conv_store: dict[tuple[int, int], dict[str, Any]] = {}
_MAX_HISTORY = 20  # max messages in reply chain to keep context bounded

# Guest mode conversation buffer: (chat_id, user_id) → list of messages
_guest_conv: dict[tuple[int, int], list[dict[str, str]]] = {}
_GUEST_MAX_HISTORY = 10


def _build_reply_chain(chat_id: int, message: types.Message) -> list[dict[str, str]]:
    """Walk the reply chain and return conversation history oldest-first."""
    chain: list[dict[str, str]] = []

    # Walk backwards through reply_to pointers in our store
    reply_msg = message.reply_to_message
    if reply_msg:
        reply_msg_id = reply_msg.message_id
        visited: set[int] = set()
        while reply_msg_id and reply_msg_id not in visited:
            visited.add(reply_msg_id)
            entry = _conv_store.get((chat_id, reply_msg_id))
            if not entry:
                break
            chain.append({"role": entry["role"], "content": entry["content"]})
            reply_msg_id = entry.get("reply_to")
        chain.reverse()

    # Keep only the last N messages to avoid token overflow
    return chain[-_MAX_HISTORY:]


def _store_message(
    chat_id: int, message_id: int, role: str, content: str,
    reply_to: int | None = None,
) -> None:
    """Store a message in the conversation store."""
    _conv_store[(chat_id, message_id)] = {
        "role": role,
        "content": content,
        "reply_to": reply_to,
    }
    # Evict old entries if store grows too large (simple LRU-ish)
    if len(_conv_store) > 5000:
        keys = list(_conv_store.keys())
        for k in keys[:1000]:
            _conv_store.pop(k, None)


def _guest_get_history(chat_id: int, user_id: int) -> list[dict[str, str]]:
    """Return recent conversation history for a guest-mode user."""
    key = (chat_id, user_id)
    return list(_guest_conv.get(key, []))


def _guest_append(chat_id: int, user_id: int, role: str, content: str) -> None:
    """Append a message to the guest-mode conversation buffer."""
    key = (chat_id, user_id)
    buf = _guest_conv.setdefault(key, [])
    buf.append({"role": role, "content": content})
    # Keep bounded
    if len(buf) > _GUEST_MAX_HISTORY * 2:
        _guest_conv[key] = buf[-_GUEST_MAX_HISTORY:]
    # Evict old users if too many
    if len(_guest_conv) > 2000:
        keys = list(_guest_conv.keys())
        for k in keys[:500]:
            _guest_conv.pop(k, None)


_TOOLS_SYSTEM_PROMPT = (
    "You are a helpful AI assistant in a Telegram chat. "
    "You MUST use the web_search tool for ANY question about current events, "
    "weather, prices, news, dates, scores, releases, or real-time data. "
    "You HAVE the web_search and read_webpage tools available RIGHT NOW. "
    "NEVER say you cannot search — call web_search immediately. "
    "NEVER apologize about missing tools — they are available. "
    "If unsure whether info is current — ALWAYS search first, then answer."
)


# ---------------------------------------------------------------------------
# /start command
# ---------------------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: types.Message) -> None:
    models_list = "\n".join(f"• **{m.label}** — `{', '.join(m.aliases[:3])}`" for m in MODELS)
    await message.answer(
        "👋 Привет! Я **Grebeshok AI Bot**.\n\n"
        "Просто напиши мне сообщение — и я отвечу через AI.\n\n"
        "**Как выбрать модель:**\n"
        "Напиши название модели в начале сообщения:\n"
        f"{models_list}\n\n"
        "Если не указать модель — выберу случайную.\n\n"
        "**Примеры:**\n"
        "• `дипсик расскажи про квантовые компьютеры`\n"
        "• `флеш напиши код на python`\n"
        "• `что такое нейросеть?` (случайная модель)\n\n"
        "🔍 Также поддерживается поиск в интернете (автоматически).",
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# /model — show current available models
# ---------------------------------------------------------------------------

@router.message(Command("models"))
async def cmd_models(message: types.Message) -> None:
    lines = []
    for m in MODELS:
        aliases = ", ".join(m.aliases[:4])
        flags = ""
        if m.supports_tools:
            flags += " 🔍"
        if not m.in_random_pool:
            flags += " (только по запросу)"
        lines.append(f"• *{m.label}*{flags}\n  _{aliases}_")
    await message.answer(
        "🤖 *Доступные модели:*\n\n" + "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# Direct message handler — main AI flow
# ---------------------------------------------------------------------------

@router.message()
async def handle_message(message: types.Message, bot: Bot) -> None:
    """Process any text/photo message: resolve model, call AI, stream response."""
    # Accept either a plain text message or a photo (with optional caption).
    raw_text = message.text or message.caption or ""
    has_photo = bool(message.photo)

    if not raw_text.strip() and not has_photo:
        return

    chat_id = message.chat.id

    # Resolve model from the text/caption. For photo-only messages without a
    # caption we synthesise a random-model ResolveResult and rely on the
    # vision override below to swap it for Kimi/Qwen anyway.
    if raw_text.strip():
        result: ResolveResult = resolve(raw_text)
    else:
        result = ResolveResult(
            model=random.choice(MODELS), prompt="", was_explicit=False,
        )
    prompt = result.prompt or raw_text

    if not has_photo and not prompt.strip():
        await message.answer("Напиши вопрос после названия модели 😊")
        return

    # --- Vision auto-switch ---------------------------------------------
    # When the user attaches a photo, force a vision-capable model (Kimi
    # first, then Qwen as fallback). If they already picked Kimi or Qwen
    # themselves, ``pick_vision_model`` honours that choice.
    model_entry: ModelEntry = result.model
    vision_overridden = False
    image_data_url: str | None = None

    if has_photo:
        image_data_url = await _download_telegram_photo(bot, message)
        if image_data_url is None:
            await message.answer(
                "❌ Не удалось загрузить изображение из Telegram. "
                "Попробуй отправить ещё раз или другой файл."
            )
            return
        new_model = pick_vision_model(model_entry)
        if new_model.id != model_entry.id:
            vision_overridden = True
        model_entry = new_model

    # Store user message (link to the message it replies to, if any).
    # We only persist the textual part — image bytes are intentionally left
    # out of the history to keep the in-memory store bounded.
    reply_to_id = (
        message.reply_to_message.message_id if message.reply_to_message else None
    )
    stored_prompt = prompt if prompt.strip() else "[Изображение без подписи]"
    _store_message(chat_id, message.message_id, "user", stored_prompt, reply_to=reply_to_id)

    # Build conversation history from reply chain
    history = _build_reply_chain(chat_id, message)

    # Send initial status message
    model_label = model_entry.label
    if has_photo and vision_overridden:
        status_text = (
            f"🖼 Фото получено — переключаю на **{model_label}** (vision).\n"
            f"🧠 Анализирую..."
        )
    elif has_photo:
        status_text = f"🖼 **{model_label}** анализирует изображение..."
    elif result.was_explicit:
        status_text = f"🧠 **{model_label}** думает..."
    else:
        status_text = f"🎲 Случайная модель: **{model_label}**\n🧠 Думает..."

    status_msg = await message.answer(status_text, parse_mode=ParseMode.MARKDOWN)

    # Start typing indicator
    typing_task = asyncio.create_task(_keep_typing(bot, chat_id))

    async def _dm_progress(text: str) -> None:
        try:
            await status_msg.edit_text(text[:_MAX_MSG_LEN], parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass

    try:
        # Build the ``content`` payload. For vision requests we use the
        # OpenAI multimodal form so Fireworks routes both the caption and
        # the image through the VLM.
        if image_data_url is not None:
            effective_prompt = (
                prompt.strip() if prompt.strip() else "Опиши, что изображено на фото."
            )
            user_content: str | list[dict[str, Any]] = [
                {"type": "text", "text": effective_prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ]
        else:
            user_content = prompt

        response_text = await _generate_response(
            model=model_entry,
            prompt=user_content,
            history=history,
            on_progress=_dm_progress,
        )

        # Store bot response (linked to the status message id)
        _store_message(
            chat_id, status_msg.message_id, "assistant", response_text,
            reply_to=message.message_id,
        )

        # Final edit with complete response
        final_text = f"**{model_label}:**\n\n{response_text}"
        if len(final_text) > _MAX_MSG_LEN:
            chunks = _split_text(final_text, _MAX_MSG_LEN)
            await _safe_edit(chunks[0], msg=status_msg)
            for chunk in chunks[1:]:
                await _safe_send(message, chunk)
        else:
            await _safe_edit(final_text, msg=status_msg)

    except (FireworksError, FreeTheAIError) as e:
        await _safe_edit(
            f"❌ Ошибка от {model_label}:\n{str(e)[:500]}",
            msg=status_msg, parse_mode=None,
        )
    except Exception as e:
        log.exception("Unexpected error in handle_message")
        await _safe_edit(
            f"❌ Непредвиденная ошибка:\n{str(e)[:300]}",
            msg=status_msg, parse_mode=None,
        )
    finally:
        typing_task.cancel()


# ---------------------------------------------------------------------------
# Inline query handler — @bot query
# ---------------------------------------------------------------------------

@router.inline_query()
async def handle_inline_query(inline_query: InlineQuery) -> None:
    """Handle inline queries: @bot <model?> <prompt>."""
    query_text = inline_query.query.strip()

    if not query_text:
        # Show hint
        await inline_query.answer(
            results=[],
            switch_pm_text="Напиши вопрос...",
            switch_pm_parameter="start",
            cache_time=1,
        )
        return

    result = resolve(query_text)
    prompt = result.prompt or query_text

    if not prompt.strip():
        await inline_query.answer(results=[], cache_time=1)
        return

    # For inline, we generate a short preview and full answer
    model_label = result.model.label

    try:
        response_text = await _generate_response_simple(
            model=result.model,
            prompt=prompt,
        )

        # Truncate for inline display
        short = response_text[:200] + "..." if len(response_text) > 200 else response_text

        article = InlineQueryResultArticle(
            id=f"ai_{random.randint(1, 999999)}",
            title=f"🤖 {model_label}",
            description=short,
            input_message_content=InputTextMessageContent(
                message_text=f"**{model_label}:**\n\n{response_text[:_MAX_MSG_LEN - 100]}",
                parse_mode=ParseMode.MARKDOWN,
            ),
        )
        await inline_query.answer(results=[article], cache_time=1)

    except Exception as e:
        log.exception("Inline query error")
        article = InlineQueryResultArticle(
            id="error",
            title="❌ Ошибка",
            description=str(e)[:100],
            input_message_content=InputTextMessageContent(
                message_text=f"❌ Ошибка: {str(e)[:300]}",
            ),
        )
        await inline_query.answer(results=[article], cache_time=1)


# ---------------------------------------------------------------------------
# Guest mode handler — Bot API 10.0+ (May 8, 2026)
#
# When a Telegram user invokes this bot from a chat where the bot is NOT
# a member ("Guest AI Bots" feature), the Bot API delivers the request as
# ``Update.guest_message`` with a populated ``guest_query_id``. The bot has
# to reply once via ``answerGuestQuery`` with an InlineQueryResult — we use
# the same model-resolution + web-search pipeline as DM, but non-streaming.
# ---------------------------------------------------------------------------

@router.guest_message()
async def handle_guest_message(guest_message: types.Message, bot: Bot) -> None:
    """Reply to a guest-mode query with streaming progress updates.

    Flow:
    1. Send immediate placeholder via ``answerGuestQuery``.
    2. Get back ``SentGuestMessage.inline_message_id``.
    3. Stream AI response, periodically editing the inline message.
    4. Final edit with the complete answer (markdown with plain-text fallback).
    """
    guest_query_id = guest_message.guest_query_id
    if not guest_query_id:
        log.warning("guest_message update without guest_query_id; skipping")
        return

    query_text = (guest_message.text or "").strip()
    if not query_text:
        await guest_message.answer_guest_query(
            result=InlineQueryResultArticle(
                id=f"guest_empty_{random.randint(1, 999_999)}",
                title="Напиши вопрос боту",
                description="Пример: «дипсик что нового в Python 3.13?»",
                input_message_content=InputTextMessageContent(
                    message_text=(
                        "Привет! Чтобы получить ответ — добавь текст после "
                        "упоминания бота, например: «что такое нейросеть?»."
                    ),
                ),
            ),
        )
        return

    chat_id = guest_message.chat.id
    user_id = guest_message.from_user.id if guest_message.from_user else 0
    log.info(
        "Guest message: chat_id=%s user_id=%s text=%r",
        chat_id, user_id, query_text[:80],
    )

    result = resolve(query_text)
    prompt = result.prompt or query_text
    model_label = result.model.label

    # Store user message and build history
    _guest_append(chat_id, user_id, "user", prompt)
    history = _guest_get_history(chat_id, user_id)[:-1]  # exclude current msg
    log.info("Guest history for (%s, %s): %d messages", chat_id, user_id, len(history))

    # --- Step 1: send placeholder and get inline_message_id ---
    if result.was_explicit:
        status_text = f"🧠 {model_label} думает..."
    else:
        status_text = f"🎲 Случайная модель: {model_label}\n🧠 Думает..."

    try:
        sent = await guest_message.answer_guest_query(
            result=InlineQueryResultArticle(
                id=f"guest_{random.randint(1, 999_999_999)}",
                title=f"🧠 {model_label}",
                description="Генерирую ответ...",
                input_message_content=InputTextMessageContent(
                    message_text=status_text,
                ),
            ),
        )
    except Exception:
        log.exception("Failed to send initial guest query answer")
        return

    inline_msg_id: str | None = getattr(sent, "inline_message_id", None)
    if not inline_msg_id:
        log.warning("answerGuestQuery returned no inline_message_id")
        return

    # --- Step 2: stream response with periodic edits ---
    async def _guest_progress(text: str) -> None:
        try:
            await bot.edit_message_text(
                text=text[:_MAX_MSG_LEN],
                inline_message_id=inline_msg_id,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    try:
        response_text = await _generate_response(
            model=result.model,
            prompt=prompt,
            history=history,
            on_progress=_guest_progress,
        )

        # Store bot response for future context
        _guest_append(chat_id, user_id, "assistant", response_text)

        final_text = f"**{model_label}:**\n\n{response_text[:_MAX_MSG_LEN - 100]}"
        await _safe_edit(final_text, bot=bot, inline_message_id=inline_msg_id)

    except (FireworksError, FreeTheAIError) as e:
        await _safe_edit(
            f"❌ Ошибка от {model_label}: {str(e)[:300]}",
            bot=bot, inline_message_id=inline_msg_id, parse_mode=None,
        )
    except Exception as e:
        log.exception("Unexpected error in guest_message streaming")
        try:
            await _safe_edit(
                f"❌ Непредвиденная ошибка: {str(e)[:300]}",
                bot=bot, inline_message_id=inline_msg_id, parse_mode=None,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _keep_typing(bot: Bot, chat_id: int) -> None:
    """Continuously send typing action until cancelled."""
    try:
        while True:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


# Max single-photo size we will pull from Telegram. Fireworks accepts ~20 MB
# base64 payloads, but Telegram's photo delivery rarely exceeds a few MB and
# keeping this bounded protects us from pathological inputs.
_MAX_PHOTO_BYTES = 10 * 1024 * 1024


async def _download_telegram_photo(bot: Bot, message: types.Message) -> str | None:
    """Download the best-quality photo on ``message`` and return a data URL.

    Returns ``None`` if the message has no photo or download fails. The
    returned string is formatted as ``data:image/jpeg;base64,<payload>`` so
    it can be plugged straight into an OpenAI-style ``image_url`` part.
    """
    if not message.photo:
        return None

    # ``message.photo`` is a list of PhotoSize ordered smallest → largest.
    # The last entry has the highest resolution available.
    best = message.photo[-1]

    try:
        file = await bot.get_file(best.file_id)
        if not file.file_path:
            return None

        buffer = io.BytesIO()
        await bot.download_file(file.file_path, destination=buffer)
        raw = buffer.getvalue()
    except Exception:
        log.exception("Failed to download Telegram photo %s", best.file_id)
        return None

    if not raw or len(raw) > _MAX_PHOTO_BYTES:
        return None

    # Telegram re-encodes uploaded photos as JPEG, so the fixed MIME type is
    # safe regardless of the original source format.
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


# Type alias for the progress callback used by _generate_response.
_ProgressFn = Callable[[str], Awaitable[None]]


async def _noop_progress(_text: str) -> None:
    pass


def _sanitize_tg_markdown(text: str) -> str:
    """Convert standard AI markdown to Telegram-compatible Markdown V1.

    Telegram Markdown V1 rules:
      *bold*  _italic_  `code`  ```pre```  [text](url)
    AI models produce **bold**, ### headers, > quotes, etc. which break
    Telegram's parser.
    """
    # --- code blocks: protect from further transforms ---
    code_blocks: list[str] = []

    def _stash_code_block(m: re.Match[str]) -> str:
        code_blocks.append(m.group(0))
        return f"\x00CB{len(code_blocks) - 1}\x00"

    text = re.sub(r"```[\s\S]*?```", _stash_code_block, text)

    inline_codes: list[str] = []

    def _stash_inline_code(m: re.Match[str]) -> str:
        inline_codes.append(m.group(0))
        return f"\x00IC{len(inline_codes) - 1}\x00"

    text = re.sub(r"`[^`]+`", _stash_inline_code, text)

    # --- headers → bold ---
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)

    # --- **bold** or __bold__ → *bold* ---
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"__(.+?)__", r"_\1_", text)

    # --- blockquotes → plain text ---
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)

    # --- horizontal rules ---
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)

    # --- balance unclosed markers ---
    for marker in ("*", "_"):
        # Count unescaped occurrences outside code spans
        count = text.count(marker)
        if count % 2 != 0:
            # Remove the last lone marker to avoid parse error
            idx = text.rfind(marker)
            text = text[:idx] + text[idx + 1:]

    # --- restore code ---
    for i, block in enumerate(code_blocks):
        text = text.replace(f"\x00CB{i}\x00", block)
    for i, code in enumerate(inline_codes):
        text = text.replace(f"\x00IC{i}\x00", code)

    return text


async def _safe_edit(
    text: str,
    *,
    msg: types.Message | None = None,
    bot: Bot | None = None,
    inline_message_id: str | None = None,
    parse_mode: str | None = ParseMode.MARKDOWN,
) -> None:
    """Edit a message with sanitization and Markdown → plain-text fallback."""
    if parse_mode == ParseMode.MARKDOWN:
        text = _sanitize_tg_markdown(text)
    for pm in (parse_mode, None) if parse_mode else (None,):
        try:
            if inline_message_id and bot:
                await bot.edit_message_text(
                    text=text[:_MAX_MSG_LEN],
                    inline_message_id=inline_message_id,
                    parse_mode=pm,
                )
            elif msg:
                await msg.edit_text(text[:_MAX_MSG_LEN], parse_mode=pm)
            return
        except TelegramBadRequest as exc:
            if "can't parse entities" in str(exc).lower() and pm is not None:
                continue
            raise


async def _safe_send(message: types.Message, text: str) -> types.Message:
    """Send a message with sanitization and Markdown → plain-text fallback."""
    sanitized = _sanitize_tg_markdown(text)
    try:
        return await message.answer(sanitized[:_MAX_MSG_LEN], parse_mode=ParseMode.MARKDOWN)
    except TelegramBadRequest as exc:
        if "can't parse entities" in str(exc).lower():
            return await message.answer(text[:_MAX_MSG_LEN])
        raise


async def _generate_response(
    *,
    model: Any,
    prompt: str,
    history: list[dict[str, str]] | None = None,
    on_progress: _ProgressFn = _noop_progress,
) -> str:
    """Generate AI response with streaming progress callbacks and tool calling.

    ``on_progress`` is invoked periodically with a status/preview string.
    The caller decides *how* to render it (edit a chat message, edit an
    inline message, etc.).

    ``history`` is an optional list of prior messages (oldest-first) from
    the reply chain, so the model can see conversation context.
    """
    # Only enable tool-calling for models that support it.
    can_use_tools = model.supports_tools and has_any_provider()
    tools = TOOL_DEFINITIONS if can_use_tools else None

    messages: list[dict[str, Any]] = []
    if tools:
        messages.append({"role": "system", "content": _TOOLS_SYSTEM_PROMPT})
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})

    if model.provider == "freetheai":
        stream_fn = freetheai_stream_chat
    else:
        stream_fn = fireworks_stream_chat

    model_id = model.id

    # --- First pass: might get tool calls ---
    full_content = ""
    tool_calls_acc: dict[int, ToolCall] = {}
    last_edit_time = 0.0

    try:
        async for delta in stream_fn(
            model=model_id,
            messages=messages,
            tools=tools,
        ):
            for tc in delta.tool_calls:
                idx = len(tool_calls_acc)
                if tc.id:
                    tool_calls_acc[idx] = ToolCall(id=tc.id, name=tc.name, arguments=tc.arguments)
                elif tool_calls_acc:
                    last_key = max(tool_calls_acc.keys())
                    tool_calls_acc[last_key].arguments += tc.arguments

            full_content += delta.content

            now = asyncio.get_event_loop().time()
            if full_content and (now - last_edit_time) > _EDIT_INTERVAL:
                last_edit_time = now
                preview = f"🧠 {model.label} генерирует...\n\n{full_content[-500:]}"
                await on_progress(preview)
    except (FireworksError, FreeTheAIError):
        # If the primary model fails and there's a fallback, try it
        if model.fallback_id:
            log.info("Primary model %s failed, trying fallback %s", model_id, model.fallback_id)
            model_id = model.fallback_id
            full_content = ""
            tool_calls_acc = {}
            async for delta in stream_fn(
                model=model_id,
                messages=messages,
                tools=tools,
            ):
                for tc in delta.tool_calls:
                    idx = len(tool_calls_acc)
                    if tc.id:
                        tool_calls_acc[idx] = ToolCall(id=tc.id, name=tc.name, arguments=tc.arguments)
                    elif tool_calls_acc:
                        last_key = max(tool_calls_acc.keys())
                        tool_calls_acc[last_key].arguments += tc.arguments

                full_content += delta.content

                now = asyncio.get_event_loop().time()
                if full_content and (now - last_edit_time) > _EDIT_INTERVAL:
                    last_edit_time = now
                    preview = f"🧠 {model.label} генерирует...\n\n{full_content[-500:]}"
                    await on_progress(preview)
        else:
            raise

    # If first pass returned empty with no tool calls, retry once
    if not full_content.strip() and not tool_calls_acc:
        log.warning("Model %s returned empty on first pass, retrying", model_id)
        async for delta in stream_fn(
            model=model_id,
            messages=messages,
            tools=tools,
        ):
            for tc in delta.tool_calls:
                idx = len(tool_calls_acc)
                if tc.id:
                    tool_calls_acc[idx] = ToolCall(id=tc.id, name=tc.name, arguments=tc.arguments)
                elif tool_calls_acc:
                    last_key = max(tool_calls_acc.keys())
                    tool_calls_acc[last_key].arguments += tc.arguments
            full_content += delta.content

    # --- Handle tool calls (web search) ---
    if tool_calls_acc:
        for _idx, tc in tool_calls_acc.items():
            tc.arguments = _ensure_json_arguments(tc.arguments)

            await on_progress(
                f"🔍 {model.label} ищет в интернете...\n\n"
                f"{tc.name}({tc.arguments[:100]})"
            )

            tool_result = await execute_tool_call(tc.name, tc.arguments)

            messages.append({
                "role": "assistant",
                "content": full_content or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                ],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_result[:8000],
            })

        await on_progress(f"✍️ {model.label} формирует ответ с учётом поиска...")

        full_content = ""
        async for delta in stream_fn(
            model=model_id,
            messages=messages,
            tools=None,
        ):
            full_content += delta.content

            now = asyncio.get_event_loop().time()
            if full_content and (now - last_edit_time) > _EDIT_INTERVAL:
                last_edit_time = now
                preview = f"✍️ {model.label} пишет...\n\n{full_content[-500:]}"
                await on_progress(preview)

        # If second pass returned empty, nudge the model to respond
        if not full_content.strip():
            messages.append({
                "role": "user",
                "content": "Please summarize the search results and answer the original question.",
            })
            async for delta in stream_fn(
                model=model_id,
                messages=messages,
                tools=None,
            ):
                full_content += delta.content

    if not full_content.strip():
        return "Модель не смогла сгенерировать ответ. Попробуй ещё раз или выбери другую модель (/models)."
    return full_content


async def _generate_response_simple(
    *,
    model: Any,
    prompt: str,
) -> str:
    """Non-streaming AI response with optional web search.

    Used for inline queries where we have to return a single
    ``InlineQueryResult`` synchronously instead of streaming edits.
    Performs at most one round of tool calls (web_search / read_webpage)
    to keep latency bounded.
    """
    can_use_tools = model.supports_tools and has_any_provider()
    tools = TOOL_DEFINITIONS if can_use_tools else None

    messages: list[dict[str, Any]] = []
    if tools:
        messages.append({"role": "system", "content": _TOOLS_SYSTEM_PROMPT})
    messages.append({"role": "user", "content": prompt})

    if model.provider == "freetheai":
        stream_fn = freetheai_stream_chat
    else:
        stream_fn = fireworks_stream_chat

    full_content = ""
    tool_calls_acc: dict[int, ToolCall] = {}

    async for delta in stream_fn(
        model=model.id,
        messages=messages,
        tools=tools,
    ):
        for tc in delta.tool_calls:
            idx = len(tool_calls_acc)
            if tc.id:
                tool_calls_acc[idx] = ToolCall(
                    id=tc.id, name=tc.name, arguments=tc.arguments
                )
            elif tool_calls_acc:
                last_key = max(tool_calls_acc.keys())
                tool_calls_acc[last_key].arguments += tc.arguments
        full_content += delta.content

    if not tool_calls_acc:
        if not full_content.strip():
            return "Модель не смогла сгенерировать ответ. Попробуй ещё раз или выбери другую модель (/models)."
        return full_content

    for tc in tool_calls_acc.values():
        tc.arguments = _ensure_json_arguments(tc.arguments)

    messages.append(
        {
            "role": "assistant",
            "content": full_content or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in tool_calls_acc.values()
            ],
        }
    )
    for tc in tool_calls_acc.values():
        tool_result = await execute_tool_call(tc.name, tc.arguments)
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_result[:8000],
            }
        )

    full_content = ""
    async for delta in stream_fn(
        model=model.id,
        messages=messages,
        tools=None,
    ):
        full_content += delta.content

    if not full_content.strip():
        return "Модель не смогла сгенерировать ответ. Попробуй ещё раз или выбери другую модель (/models)."
    return full_content


def _ensure_json_arguments(raw: str) -> str:
    """Ensure tool-call arguments are a valid JSON object string.

    Some models produce empty strings, bare values, or malformed JSON.
    Fireworks requires a JSON object string for ``function.arguments``.
    """
    raw = raw.strip()
    if not raw:
        return "{}"
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return raw
        return json.dumps({"query": str(parsed)})
    except (json.JSONDecodeError, ValueError):
        return json.dumps({"query": raw})


def _split_text(text: str, max_len: int) -> list[str]:
    """Split text into chunks of max_len."""
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Find a good split point (newline or space)
        split_at = text.rfind("\n", 0, max_len)
        if split_at < max_len // 2:
            split_at = text.rfind(" ", 0, max_len)
        if split_at < max_len // 2:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    return chunks
