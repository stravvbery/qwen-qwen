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
    BufferedInputFile,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from ..fireworks import FireworksError, ToolCall
from ..fireworks import stream_chat as fireworks_stream_chat
from ..freetheai_client import FreeTheAIError
from ..freetheai_client import stream_chat as freetheai_stream_chat
from ..nvidia_client import NvidiaError
from ..nvidia_client import stream_chat as nvidia_stream_chat
from ..nvidia_image import NvidiaImageError, detect_image_prompt, generate_image
from ..web_tools import TOOL_DEFINITIONS, execute_tool_call, has_any_provider
from .model_resolver import (
    MODELS,
    ModelEntry,
    ResolveResult,
    fallback_chain,
    pick_vision_model,
    resolve,
)

log = logging.getLogger(__name__)

router = Router()

# How often to edit the message during streaming (avoid Telegram rate limits)
_EDIT_INTERVAL = 1.5  # seconds
_MAX_MSG_LEN = 4096  # Telegram message limit

# When a model produces no output (no content delta, no tool call) for this
# many seconds, we treat it as dead and fail over to the next model in the
# fallback chain. 7 s is the user's requested budget.
_NO_LIVENESS_TIMEOUT = 7.0

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
# Bot identity cache and mention detection for group chats
# ---------------------------------------------------------------------------

# Populated lazily on the first message — ``Bot.get_me()`` requires an await
# so we can't do it at import time.
_bot_id: int | None = None
_bot_username_lower: str | None = None


async def _get_bot_identity(bot: Bot) -> tuple[int, str | None]:
    """Return ``(bot_id, bot_username_lower)``, caching the result."""
    global _bot_id, _bot_username_lower
    if _bot_id is None:
        me = await bot.get_me()
        _bot_id = me.id
        _bot_username_lower = me.username.lower() if me.username else None
    return _bot_id, _bot_username_lower


def _is_bot_mentioned(
    message: types.Message,
    bot_id: int,
    bot_username_lower: str | None,
) -> bool:
    """Return True if this message explicitly addresses the bot.

    The bot is considered addressed **only** when the user explicitly
    mentions it in the message text/caption — either:

    * The text contains a ``@botusername`` mention entity (authoritative,
      so we don't misfire on ``@someone_else``).
    * The text contains a ``text_mention`` entity pointing at the bot's
      user id (the Telegram client uses this when linking a mention to
      a user without a public @username).

    Note: a bare reply to one of the bot's own messages **does not**
    count as addressing the bot. The user must also type ``@botname``
    (or text-mention the bot) in the reply for us to engage. This keeps
    casual reactions like ``боребень`` in reply to the bot from
    triggering another response. However, when the user *does* reply
    with an ``@botname`` mention, ``_build_reply_chain`` still walks the
    full reply chain so earlier unaddressed messages in the thread are
    included in the model's context.

    In private chats this helper is not consulted — direct messages are
    always treated as addressed to the bot.
    """
    # Entity-based checks (authoritative).
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []
    for ent in entities:
        if ent.type == "mention" and bot_username_lower:
            # ``@username`` mention — compare against our cached handle.
            mention_text = text[ent.offset : ent.offset + ent.length].lower()
            if mention_text == f"@{bot_username_lower}":
                return True
        elif ent.type == "text_mention" and ent.user is not None:
            # Inline user reference — works even when the bot has no public
            # @username (e.g. scoped bots).
            if ent.user.id == bot_id:
                return True

    return False


def _strip_bot_mention(text: str, bot_username_lower: str | None) -> str:
    """Remove the first ``@botusername`` occurrence from ``text``.

    Used to keep the actual prompt clean when the user types
    ``@botname расскажи про X`` in a group chat.
    """
    if not bot_username_lower or not text:
        return text
    # Case-insensitive single replace of the handle; preserves surrounding
    # whitespace and the rest of the message.
    pattern = re.compile(rf"(?i)@{re.escape(bot_username_lower)}\s*")
    return pattern.sub("", text, count=1).strip()


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
    """Process any text/photo message: resolve model, call AI, stream response.

    Group-chat policy (fix #4, revised): the bot replies in a group
    **only** when the message contains an explicit ``@botusername`` or
    text-mention of the bot. A bare reply to the bot's own message is
    *not* enough — the user must also @-mention the bot.

    Messages in groups that don't address the bot are still recorded in
    the in-memory reply-chain store (without sending anything), so that
    if the user later replies with ``@botname <question>`` higher up the
    thread, the full chain (including intermediate unaddressed messages
    like ``боребень``) is passed to the model as context.

    Private chats always get a response, as before.
    """
    # Accept either a plain text message or a photo (with optional caption).
    raw_text = message.text or message.caption or ""
    has_photo = bool(message.photo)

    if not raw_text.strip() and not has_photo:
        return

    chat_type = message.chat.type  # "private" | "group" | "supergroup" | "channel"
    is_private = chat_type == "private"

    bot_id, bot_username_lower = await _get_bot_identity(bot)

    # --- Mention gate for non-private chats ---
    # In groups and supergroups we stay silent unless the user addressed us
    # directly via ``@botusername`` or a text-mention entity. Bare replies
    # to the bot's own messages are ignored — the user has to actually
    # @-mention the bot in the reply for us to respond.
    if not is_private:
        addressed = _is_bot_mentioned(message, bot_id, bot_username_lower)
        if not addressed:
            # Silent-save branch: even though we won't reply, persist this
            # message in the conversation store so that if the user later
            # @-mentions the bot in a reply down the thread, the whole
            # chain (including the unaddressed messages like ``боребень``)
            # is available to the model via ``_build_reply_chain``.
            text_for_store = (message.text or message.caption or "").strip()
            if text_for_store:
                _passive_reply_to = (
                    message.reply_to_message.message_id
                    if message.reply_to_message
                    else None
                )
                _store_message(
                    message.chat.id,
                    message.message_id,
                    "user",
                    text_for_store,
                    reply_to=_passive_reply_to,
                )
            return
        # Drop the leading ``@botusername`` from the prompt so the model
        # doesn't waste tokens repeating its own name.
        raw_text = _strip_bot_mention(raw_text, bot_username_lower)

    chat_id = message.chat.id

    # --- Image generation shortcut ---
    # If the user opens the message with a "нарисуй"/"создай фото"/"draw ..."
    # trigger, route to the NVIDIA Qwen Image endpoint instead of the chat
    # pipeline. This runs before ``resolve()`` so the model alias tokens
    # inside the image prompt don't get stripped / misinterpreted. Photo
    # messages stay on the vision path because they carry an actual image
    # to look at, not a request to generate one.
    if not has_photo:
        img_subject = detect_image_prompt(raw_text)
        if img_subject:
            await _handle_image_generation(
                message=message,
                bot=bot,
                chat_id=chat_id,
                subject=img_subject,
            )
            return

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

    # --- Choose delivery channel ---
    # Private chats get the smooth Bot API 10.0 ``sendMessageDraft`` pipeline
    # so the text visibly scrolls in as it is generated. Group chats fall
    # back to periodic ``editMessageText`` because ``sendMessageDraft`` is
    # only supported in private chats.
    use_draft_streaming = is_private
    draft_streamer: _DraftStreamer | None = None
    status_msg: types.Message | None = None

    if use_draft_streaming:
        draft_streamer = _DraftStreamer(
            bot=bot,
            chat_id=chat_id,
            initial_text=status_text,
        )
        await draft_streamer.update(status_text, force=True)

        async def _progress(text: str) -> None:
            # ``_DraftStreamer`` handles throttling and error suppression.
            assert draft_streamer is not None
            await draft_streamer.update(text)
    else:
        status_msg = await message.answer(status_text, parse_mode=ParseMode.MARKDOWN)

        async def _progress(text: str) -> None:
            assert status_msg is not None
            try:
                await status_msg.edit_text(
                    text[:_MAX_MSG_LEN], parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass

    # Start typing indicator
    typing_task = asyncio.create_task(_keep_typing(bot, chat_id))

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

        # --- Generate with automatic fallback on stall / error ---
        # Returns the final response plus the model that actually served it,
        # which may differ from ``model_entry`` if one or more upstreams
        # timed out.
        response_text, used_model = await _generate_with_fallback(
            primary=model_entry,
            prompt=user_content,
            history=history,
            on_progress=_progress,
        )
        final_label = used_model.label

        final_text = f"**{final_label}:**\n\n{response_text}"

        # We record the assistant reply in ``_conv_store`` using the id of
        # the final message we actually delivered, so the reply-chain
        # history stays intact whether we streamed via drafts (no
        # placeholder message exists) or via edit-in-place.
        final_message_id: int | None = None

        if use_draft_streaming:
            # Draft streaming: finalise by sending a real ``SendMessage``
            # with the complete text. The draft is ephemeral (30 s) and
            # disappears on its own once this message arrives.
            assert draft_streamer is not None
            await draft_streamer.finish()
            sent = await _safe_send_chunks(message, final_text)
            if sent is not None:
                final_message_id = sent.message_id
        else:
            # Edit-based streaming: update the placeholder message in place.
            assert status_msg is not None
            if len(final_text) > _MAX_MSG_LEN:
                chunks = _split_text(final_text, _MAX_MSG_LEN)
                await _safe_edit(chunks[0], msg=status_msg)
                for chunk in chunks[1:]:
                    await _safe_send(message, chunk)
            else:
                await _safe_edit(final_text, msg=status_msg)
            final_message_id = status_msg.message_id

        if final_message_id is not None:
            _store_message(
                chat_id, final_message_id, "assistant", response_text,
                reply_to=message.message_id,
            )

    except (FireworksError, FreeTheAIError, NvidiaError) as e:
        error_text = f"❌ Ошибка: {str(e)[:500]}"
        if draft_streamer is not None:
            await draft_streamer.finish()
            await message.answer(error_text)
        else:
            assert status_msg is not None
            await _safe_edit(error_text, msg=status_msg, parse_mode=None)
    except _ModelStalledError:
        error_text = (
            "❌ Все модели сейчас молчат. Попробуй ещё раз через пару секунд "
            "или выбери конкретную модель (например `квен ...`)."
        )
        if draft_streamer is not None:
            await draft_streamer.finish()
            await message.answer(error_text)
        else:
            assert status_msg is not None
            await _safe_edit(error_text, msg=status_msg, parse_mode=None)
    except Exception as e:
        log.exception("Unexpected error in handle_message")
        error_text = f"❌ Непредвиденная ошибка:\n{str(e)[:300]}"
        if draft_streamer is not None:
            await draft_streamer.finish()
            await message.answer(error_text)
        else:
            assert status_msg is not None
            await _safe_edit(error_text, msg=status_msg, parse_mode=None)
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

def _guest_is_addressed(
    guest_message: types.Message,
    bot_username_lower: str | None,
    bot_id: int,
) -> bool:
    """Return True iff the guest message explicitly addresses the bot.

    In Bot API 10.0 guest mode (May 2026), Telegram can route *every*
    message from an open guest session to the bot — not just the ones
    that literally contain ``@botusername``. The bot therefore has to
    filter itself, the same way it does in group chats.

    We accept any of:

    * an ``entities`` / ``caption_entities`` mention entity matching
      ``@botusername``,
    * a ``text_mention`` entity whose ``user.id`` equals the bot id,
    * or a case-insensitive substring match of ``@botusername`` in the
      text / caption (fallback for entity-less guest updates, which
      some Telegram clients send).

    A bare reply to one of the bot's own messages is deliberately NOT
    enough — the user must @-mention the bot to re-engage it, matching
    the strict behaviour the user asked for in the group-chat case.
    """
    text = (guest_message.text or guest_message.caption or "")
    entities = (
        guest_message.entities or guest_message.caption_entities or []
    )
    for ent in entities:
        if ent.type == "mention" and bot_username_lower:
            mention_text = text[ent.offset : ent.offset + ent.length].lower()
            if mention_text == f"@{bot_username_lower}":
                return True
        elif ent.type == "text_mention" and ent.user is not None:
            if ent.user.id == bot_id:
                return True

    if bot_username_lower:
        # Case-insensitive substring fallback — some guest updates
        # arrive without entity metadata even though the user typed
        # the handle.
        if f"@{bot_username_lower}" in text.lower():
            return True

    return False


@router.guest_message()
async def handle_guest_message(guest_message: types.Message, bot: Bot) -> None:
    """Reply to a guest-mode query with streaming progress updates.

    Policy (matches the strict group-chat policy): we only engage when
    the message explicitly @-mentions the bot. Every other guest message
    is silently recorded in ``_guest_conv`` so the context is still
    there when the user does ping the bot later. Telegram still requires
    us to answer the ``guest_query_id`` exactly once, so for the silent
    branch we return an empty ``InlineQueryResultsButton``-style article
    that the user would have to actively choose — which they won't, so
    nothing appears in the chat.

    Happy path:

    1. Verify the message addresses the bot (``@botusername`` mention
       entity, ``text_mention`` targeting the bot, or a case-insensitive
       ``@botusername`` substring).
    2. Send an immediate placeholder via ``answerGuestQuery`` and pick
       up ``SentGuestMessage.inline_message_id``.
    3. Stream the AI response by periodically editing the inline message.
    4. Commit the final answer (markdown with plain-text fallback).
    """
    guest_query_id = guest_message.guest_query_id
    if not guest_query_id:
        log.warning("guest_message update without guest_query_id; skipping")
        return

    query_text = (guest_message.text or "").strip()

    chat_id = guest_message.chat.id
    user_id = guest_message.from_user.id if guest_message.from_user else 0
    bot_id, bot_username_lower = await _get_bot_identity(bot)

    # --- Mention gate for guest mode ---
    # Unless the message explicitly @-mentions the bot, we stay silent
    # but still cache the text so that when the user does ping the bot
    # later in the same guest session, ``_guest_get_history`` serves the
    # intervening messages as conversation context.
    addressed = _guest_is_addressed(guest_message, bot_username_lower, bot_id)

    if not addressed:
        # Only cache the message if it's part of an existing thread
        # (i.e. it replies to something). A bare unaddressed message
        # with no reply_to is just background chatter in the guest
        # session and should not pollute any future thread.
        is_reply = guest_message.reply_to_message is not None
        if query_text and is_reply:
            _guest_append(chat_id, user_id, "user", query_text)
        log.info(
            "Guest message not addressed to bot — %s "
            "(chat_id=%s user_id=%s is_reply=%s text=%r)",
            "silent cache" if is_reply else "silent drop",
            chat_id, user_id, is_reply, query_text[:80],
        )
        try:
            # Telegram expects exactly one answer per guest_query_id. We
            # hand back an almost-invisible neutral article the user
            # would have to actively send to appear in the chat — in
            # practice they won't, and no message is posted. The prior
            # "🤫 Упомяни меня, чтобы я включился в диалог." hint was
            # visually noisy in the guest preview; replaced with a bare
            # thin-space title so the card is basically blank.
            await guest_message.answer_guest_query(
                result=InlineQueryResultArticle(
                    id=f"guest_silent_{random.randint(1, 999_999_999)}",
                    # Thin space — renders as a near-empty line in the
                    # guest preview card instead of a chatty prompt.
                    title="\u2009",
                    description="",
                    input_message_content=InputTextMessageContent(
                        message_text="\u2009",
                    ),
                ),
            )
        except Exception:
            # A failing answerGuestQuery is harmless for us — Telegram
            # will time the query out on its own. We just don't want
            # unhandled exceptions in the dispatcher.
            log.debug("silent answerGuestQuery failed", exc_info=True)
        return

    if not query_text:
        # Mentioned the bot but sent no text (e.g. "@bot " alone).
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

    log.info(
        "Guest message: chat_id=%s user_id=%s text=%r",
        chat_id, user_id, query_text[:80],
    )

    # Strip the bot handle out of the prompt before resolving the
    # model — same as in ``handle_message`` so the LLM doesn't waste
    # tokens echoing its own name.
    prompt_source = _strip_bot_mention(query_text, bot_username_lower)

    # --- Image generation shortcut (guest mode) ---
    # Same detection logic as ``handle_message``: if the message asks to
    # draw / create a picture, route to the NVIDIA image endpoint and
    # surface the result through ``answerGuestQuery`` as a photo article.
    img_subject = detect_image_prompt(prompt_source)
    if img_subject:
        await _handle_image_generation_guest(
            guest_message=guest_message,
            bot=bot,
            subject=img_subject,
        )
        return

    result = resolve(prompt_source)
    prompt = result.prompt or prompt_source
    model_label = result.model.label

    # --- Thread semantics (matches the group-chat behaviour) ---
    # A fresh top-level @bot message (no reply_to_message) starts a
    # brand-new thread and must NOT inherit memory from earlier turns
    # in this guest session. Only an explicit reply continues the
    # existing thread. This mirrors the reply-chain model the user
    # asked for in groups: "обычное сообщение должно начинать новую
    # ветку, не затрагивая старую память".
    is_reply = guest_message.reply_to_message is not None
    if not is_reply:
        _guest_conv.pop((chat_id, user_id), None)

    # Store user message and build history
    _guest_append(chat_id, user_id, "user", prompt)
    history = _guest_get_history(chat_id, user_id)[:-1]  # exclude current msg
    log.info(
        "Guest history for (%s, %s): %d messages (is_reply=%s)",
        chat_id, user_id, len(history), is_reply,
    )

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
        response_text, used_model = await _generate_with_fallback(
            primary=result.model,
            prompt=prompt,
            history=history,
            on_progress=_guest_progress,
        )
        final_label = used_model.label

        # Store bot response for future context
        _guest_append(chat_id, user_id, "assistant", response_text)

        final_text = f"**{final_label}:**\n\n{response_text[:_MAX_MSG_LEN - 100]}"
        await _safe_edit(final_text, bot=bot, inline_message_id=inline_msg_id)

    except (FireworksError, FreeTheAIError, NvidiaError) as e:
        await _safe_edit(
            f"❌ Ошибка: {str(e)[:300]}",
            bot=bot, inline_message_id=inline_msg_id, parse_mode=None,
        )
    except _ModelStalledError:
        await _safe_edit(
            "❌ Все модели не отвечают. Попробуй ещё раз чуть позже.",
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


# ---------------------------------------------------------------------------
# Image generation (NVIDIA Qwen Image)
# ---------------------------------------------------------------------------

async def _handle_image_generation(
    *,
    message: types.Message,
    bot: Bot,
    chat_id: int,
    subject: str,
) -> None:
    """Generate an image from ``subject`` and reply to ``message`` with it.

    This is the happy path for a ``нарисуй .../создай фото ...`` request in
    private chats, groups (once the bot has been @-mentioned), and anywhere
    ``handle_message`` routes through. We keep the chat-completion path
    untouched so the normal model-resolution / reply-chain logic still
    applies to non-image messages.
    """
    status_msg = await message.answer(
        f"🎨 Рисую: *{_escape_md(subject[:200])}*\n"
        "Qwen Image через NVIDIA — это может занять 20–60 секунд...",
        parse_mode=ParseMode.MARKDOWN,
    )

    # Keep the chat action alive so the user sees the typing/photo indicator
    # while NVIDIA renders the frame. ``upload_photo`` is the closest action
    # to "I'm sending you a picture".
    async def _keep_uploading() -> None:
        try:
            while True:
                await bot.send_chat_action(
                    chat_id=chat_id, action=ChatAction.UPLOAD_PHOTO,
                )
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    indicator = asyncio.create_task(_keep_uploading())

    try:
        image = await generate_image(prompt=subject)
    except NvidiaImageError as exc:
        log.warning("Image generation failed: %s", exc)
        await _safe_edit(
            f"❌ Не получилось нарисовать: {str(exc)[:400]}",
            msg=status_msg, parse_mode=None,
        )
        return
    except Exception:
        log.exception("Unexpected error in image generation")
        await _safe_edit(
            "❌ Непредвиденная ошибка при генерации изображения.",
            msg=status_msg, parse_mode=None,
        )
        return
    finally:
        indicator.cancel()

    # Deliver the photo as a reply to the original message. ``BufferedInputFile``
    # accepts raw bytes — no need to round-trip through the filesystem.
    photo = BufferedInputFile(image.data, filename="nvidia-qwen-image.png")
    try:
        sent = await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=f"🎨 *Qwen Image* — {_escape_md(subject[:900])}",
            parse_mode=ParseMode.MARKDOWN,
            reply_to_message_id=message.message_id,
        )
    except TelegramBadRequest as exc:
        # Fall back to plain-text caption if Markdown broke on the subject.
        log.info("send_photo rejected markdown caption, retrying plain: %s", exc)
        sent = await bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            caption=f"🎨 Qwen Image — {subject[:900]}",
            reply_to_message_id=message.message_id,
        )

    # Delete the placeholder status message now that the photo arrived.
    try:
        await status_msg.delete()
    except Exception:
        # Deletion best-effort; if it fails the user just sees both messages.
        log.debug("Failed to delete image status placeholder", exc_info=True)

    # Record the bot's photo in the reply-chain store so later follow-ups
    # like ``@bot что на картинке`` as a reply still get relevant context.
    # We stash the textual subject rather than bytes to keep the store bounded.
    _store_message(
        chat_id,
        sent.message_id,
        "assistant",
        f"[Сгенерированное изображение: {subject}]",
        reply_to=message.message_id,
    )


async def _handle_image_generation_guest(
    *,
    guest_message: types.Message,
    bot: Bot,
    subject: str,
) -> None:
    """Guest-mode variant of :func:`_handle_image_generation`.

    Guest queries must answer via ``answerGuestQuery`` exactly once. We
    return a text article acknowledging the image request (with a link to
    the rendered PNG) because Bot API 10.0 doesn't expose a way to embed a
    binary photo inside an InlineQueryResult without first hosting it
    elsewhere. For the end user this shows up as a message with the
    description of what was drawn; if they want the actual picture file
    they can invoke the bot in DM where ``send_photo`` is available.
    """
    try:
        image = await generate_image(prompt=subject)
    except NvidiaImageError as exc:
        log.warning("Guest image generation failed: %s", exc)
        await _safe_guest_answer(
            guest_message,
            title="❌ Не получилось нарисовать",
            description=str(exc)[:200],
            message_text=f"❌ Не получилось нарисовать: {str(exc)[:400]}",
        )
        return
    except Exception:
        log.exception("Unexpected error in guest image generation")
        await _safe_guest_answer(
            guest_message,
            title="❌ Ошибка генерации",
            description="Попробуй ещё раз чуть позже.",
            message_text="❌ Непредвиденная ошибка при генерации изображения.",
        )
        return

    # We have ``image.data`` (PNG bytes) but can't attach it to the guest
    # article. Surface a descriptive acknowledgement — the user can open a
    # DM with the bot to receive the actual file next time.
    _ = image  # Keep the bytes in scope in case we add hosting later.
    await _safe_guest_answer(
        guest_message,
        title=f"🎨 {subject[:70]}",
        description=(
            "Qwen Image нарисовал твой запрос. Открой личку с ботом "
            "(@testerbo1tbot), чтобы получить файл картинкой."
        ),
        message_text=(
            f"🎨 *Qwen Image* — {subject[:900]}\n\n"
            "Картинка готова. В guest-режиме Telegram не позволяет "
            "приложить файл к ответу — напиши боту в личку тем же "
            "запросом, чтобы получить PNG."
        ),
    )


async def _safe_guest_answer(
    guest_message: types.Message,
    *,
    title: str,
    description: str,
    message_text: str,
) -> None:
    """Send a one-shot guest-query answer, swallowing transport errors."""
    try:
        await guest_message.answer_guest_query(
            result=InlineQueryResultArticle(
                id=f"guest_img_{random.randint(1, 999_999_999)}",
                title=title[:60],
                description=description[:100],
                input_message_content=InputTextMessageContent(
                    message_text=message_text[:_MAX_MSG_LEN],
                    parse_mode=ParseMode.MARKDOWN,
                ),
            ),
        )
    except Exception:
        log.debug("guest answer failed", exc_info=True)


def _escape_md(text: str) -> str:
    """Escape characters that would break Telegram Markdown V1 captions."""
    # Markdown V1 special characters: * _ ` [
    return re.sub(r"([*_`\[])", r"\\\1", text)


# ---------------------------------------------------------------------------
# Smooth streaming via Bot API 10.0 ``sendMessageDraft``
#
# ``sendMessageDraft`` streams a 30-second ephemeral preview into the chat,
# and successive calls with the same ``draft_id`` animate the text in the
# client (letters fade in smoothly instead of the whole message re-rendering
# on every edit). We throttle updates to ~3 Hz to stay well under Telegram's
# rate limits, and when generation finishes we send the finalised text as a
# regular message — the draft then disappears on its own.
#
# Limitation: the method only works in private chats (``chat_id`` must be a
# positive user id). For groups and supergroups we keep the legacy
# ``editMessageText`` path.
# ---------------------------------------------------------------------------

# Try to import ``SendMessageDraft`` lazily so the module still imports on
# older aiogram versions (for tests, local dev, etc.). If the symbol isn't
# available we simply fall back to ``editMessageText`` everywhere.
try:  # pragma: no cover — version-dependent import
    from aiogram.methods import SendMessageDraft as _SendMessageDraft
except ImportError:  # pragma: no cover
    _SendMessageDraft = None  # type: ignore[assignment]


_DRAFT_UPDATE_INTERVAL = 0.35  # seconds between draft pushes (≈3 Hz)


class _DraftStreamer:
    """Throttled wrapper around ``sendMessageDraft`` for smooth streaming.

    The streamer tracks the last text it pushed and skips updates that would
    be identical, so rapid token deltas don't overwhelm Telegram's API. If
    the Bot API 10.0 method is not available in the current aiogram build,
    all updates become no-ops — the caller will still deliver the final
    text via ``_safe_send_chunks`` at the end, so the user always gets a
    reply even without the animation.
    """

    def __init__(self, *, bot: Bot, chat_id: int, initial_text: str) -> None:
        self._bot = bot
        self._chat_id = chat_id
        # draft_id must be a stable, non-zero int64. Using a chat-scoped
        # random value avoids collisions with other in-flight drafts.
        self._draft_id = random.randint(1, 2**31 - 1)
        self._last_text = ""
        self._last_push_ts = 0.0
        # If the very first update was the placeholder status, remember it
        # so the finaliser can detect "we never received any deltas" and
        # skip the draft entirely.
        self._initial_text = initial_text
        self._alive = _SendMessageDraft is not None

    @property
    def available(self) -> bool:
        return self._alive

    async def update(self, text: str, *, force: bool = False) -> None:
        if not self._alive:
            return
        now = asyncio.get_event_loop().time()
        if not force and (now - self._last_push_ts) < _DRAFT_UPDATE_INTERVAL:
            return
        if text == self._last_text:
            return
        trimmed = text[:_MAX_MSG_LEN]
        try:
            await self._bot(
                _SendMessageDraft(  # type: ignore[misc]
                    chat_id=self._chat_id,
                    draft_id=self._draft_id,
                    text=trimmed,
                )
            )
            self._last_text = trimmed
            self._last_push_ts = now
        except TelegramBadRequest as exc:
            # Draft stream can fail with "method not allowed" in group chats
            # or rate-limit errors. Either way, degrade to no-op and let the
            # caller send the final message via sendMessage.
            log.info("sendMessageDraft rejected, disabling draft stream: %s", exc)
            self._alive = False
        except Exception:
            log.exception("sendMessageDraft unexpectedly failed")
            self._alive = False

    async def finish(self) -> None:
        """Mark the draft as done.

        ``sendMessageDraft`` drafts are ephemeral (30 s server-side TTL), so
        we don't need to explicitly close them — but we stop accepting new
        updates to avoid racing with the final ``SendMessage`` that the
        caller is about to issue.
        """
        self._alive = False


async def _safe_send_chunks(
    message: types.Message, text: str,
) -> types.Message | None:
    """Send ``text`` as one or more messages, splitting if over the 4096 cap.

    Returns the last sent message (or ``None`` on send failure) so the
    caller can attribute assistant-role history to it.
    """
    last: types.Message | None = None
    if len(text) <= _MAX_MSG_LEN:
        last = await _safe_send(message, text)
        return last
    for chunk in _split_text(text, _MAX_MSG_LEN):
        last = await _safe_send(message, chunk)
    return last


# ---------------------------------------------------------------------------
# No-liveness timeout + automatic model fallback
# ---------------------------------------------------------------------------


class _ModelStalledError(Exception):
    """Raised when a model produces no output for ``_NO_LIVENESS_TIMEOUT`` s."""


async def _generate_with_fallback(
    *,
    primary: ModelEntry,
    prompt: Any,
    history: list[dict[str, str]] | None,
    on_progress: _ProgressFn,
) -> tuple[str, ModelEntry]:
    """Try ``primary`` first, then cascade through the fallback chain.

    We swap models on two failure modes:

    1. **Hard error** — the upstream raises ``FireworksError`` /
       ``FreeTheAIError`` (401, 429, timeout, etc.).
    2. **Stall** — the model accepts the request but produces no output
       for :data:`_NO_LIVENESS_TIMEOUT` seconds. This catches providers
       that return 200 OK and then silently hang.

    The returned tuple contains the final text and the model that actually
    produced it (which may differ from ``primary``).
    """
    candidates: list[ModelEntry] = [primary, *fallback_chain(primary)]
    last_exc: Exception | None = None

    for idx, candidate in enumerate(candidates):
        if idx > 0:
            # Keep the user informed when we fail over. We intentionally do
            # not reveal the technical reason — just the observable fact.
            await on_progress(
                f"⚠️ {primary.label} не отвечает — переключаюсь на "
                f"**{candidate.label}**..."
            )
            # Give the typing indicator a beat to refresh.
            await asyncio.sleep(0.1)

        try:
            text = await _generate_response(
                model=candidate,
                prompt=prompt,
                history=history,
                on_progress=on_progress,
            )
            return text, candidate
        except _ModelStalledError as exc:
            log.warning("Model %s stalled: %s", candidate.id, exc)
            last_exc = exc
            continue
        except (FireworksError, FreeTheAIError, NvidiaError) as exc:
            log.warning("Model %s raised upstream error: %s", candidate.id, exc)
            last_exc = exc
            continue

    # All candidates exhausted — propagate the most recent failure so the
    # caller can surface it to the user.
    if last_exc is not None:
        raise last_exc
    # Defensive: should never hit this because ``candidates`` always
    # contains at least ``primary``.
    raise RuntimeError("No candidate models to try")


# ---------------------------------------------------------------------------
# Photo download helper (used by the ``handle_message`` vision branch)
# ---------------------------------------------------------------------------


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
    prompt: Any,
    history: list[dict[str, str]] | None = None,
    on_progress: _ProgressFn = _noop_progress,
) -> str:
    """Generate AI response with streaming progress callbacks and tool calling.

    Behaviour:

    * Calls ``on_progress(preview_text)`` periodically so the caller can
      render a live-updating UI (edit a chat message, push a draft, etc.).
    * Raises :class:`_ModelStalledError` when the model produces no output
      (no text delta, no tool call) for :data:`_NO_LIVENESS_TIMEOUT`
      seconds. The wrapping :func:`_generate_with_fallback` catches this
      and moves on to the next candidate.
    * Propagates ``FireworksError`` / ``FreeTheAIError`` on hard failures
      so the fallback layer can react.

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
    elif model.provider == "nvidia":
        stream_fn = nvidia_stream_chat
    else:
        stream_fn = fireworks_stream_chat

    model_id = model.id

    # --- First pass: might get tool calls ---
    full_content, tool_calls_acc, last_edit_time = await _stream_pass(
        stream_fn=stream_fn,
        model_id=model_id,
        model_label=model.label,
        messages=messages,
        tools=tools,
        on_progress=on_progress,
        last_edit_time=0.0,
        status_prefix="🧠",
        status_verb="генерирует",
    )

    # If the first pass returned nothing and no tool call was requested,
    # retry once — some providers return an empty stream on the first try
    # but succeed on a second attempt with the same payload.
    if not full_content.strip() and not tool_calls_acc:
        log.warning("Model %s returned empty on first pass, retrying", model_id)
        full_content, tool_calls_acc, last_edit_time = await _stream_pass(
            stream_fn=stream_fn,
            model_id=model_id,
            model_label=model.label,
            messages=messages,
            tools=tools,
            on_progress=on_progress,
            last_edit_time=last_edit_time,
            status_prefix="🧠",
            status_verb="генерирует",
        )

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

        full_content, _unused_tools, last_edit_time = await _stream_pass(
            stream_fn=stream_fn,
            model_id=model_id,
            model_label=model.label,
            messages=messages,
            tools=None,
            on_progress=on_progress,
            last_edit_time=last_edit_time,
            status_prefix="✍️",
            status_verb="пишет",
        )

        # If second pass returned empty, nudge the model to respond
        if not full_content.strip():
            messages.append({
                "role": "user",
                "content": "Please summarize the search results and answer the original question.",
            })
            full_content, _unused_tools, _unused_ts = await _stream_pass(
                stream_fn=stream_fn,
                model_id=model_id,
                model_label=model.label,
                messages=messages,
                tools=None,
                on_progress=on_progress,
                last_edit_time=last_edit_time,
                status_prefix="✍️",
                status_verb="пишет",
            )

    if not full_content.strip():
        return "Модель не смогла сгенерировать ответ. Попробуй ещё раз или выбери другую модель (/models)."
    return full_content


async def _stream_pass(
    *,
    stream_fn: Any,
    model_id: str,
    model_label: str,
    messages: list[dict[str, Any]],
    tools: Any,
    on_progress: _ProgressFn,
    last_edit_time: float,
    status_prefix: str,
    status_verb: str,
) -> tuple[str, dict[int, ToolCall], float]:
    """Run one streaming pass with a no-liveness timeout.

    We advance an "alive" deadline every time we receive *any* signal from
    the model (a content delta, a tool-call fragment, etc.). If the
    deadline passes without activity, we cancel the stream and raise
    :class:`_ModelStalledError` so the fallback layer can pick another
    model. This catches providers that accept the request but never emit
    anything — which was the user-visible failure mode for the "иногда
    модели не отвечают вообще" complaint.
    """
    full_content = ""
    tool_calls_acc: dict[int, ToolCall] = {}

    loop = asyncio.get_event_loop()
    alive_deadline = loop.time() + _NO_LIVENESS_TIMEOUT

    # We iterate the async generator manually so we can wrap each
    # ``__anext__`` in ``asyncio.wait_for`` and react to a stall without
    # waiting forever.
    stream = stream_fn(
        model=model_id,
        messages=messages,
        tools=tools,
    )
    aiter = stream.__aiter__()

    try:
        while True:
            timeout = alive_deadline - loop.time()
            if timeout <= 0:
                raise _ModelStalledError(
                    f"{model_id} produced no output for "
                    f"{_NO_LIVENESS_TIMEOUT:.0f}s"
                )
            try:
                delta = await asyncio.wait_for(aiter.__anext__(), timeout=timeout)
            except StopAsyncIteration:
                break
            except TimeoutError as exc:
                raise _ModelStalledError(
                    f"{model_id} stalled after "
                    f"{_NO_LIVENESS_TIMEOUT:.0f}s with no output"
                ) from exc

            # Any signal counts as liveness, even an empty-content delta
            # carrying a tool-call id (some providers stream the function
            # name before the body).
            had_signal = False

            for tc in delta.tool_calls:
                had_signal = True
                idx = len(tool_calls_acc)
                if tc.id:
                    tool_calls_acc[idx] = ToolCall(
                        id=tc.id, name=tc.name, arguments=tc.arguments
                    )
                elif tool_calls_acc:
                    last_key = max(tool_calls_acc.keys())
                    tool_calls_acc[last_key].arguments += tc.arguments

            if delta.content:
                had_signal = True
                full_content += delta.content

            if had_signal:
                alive_deadline = loop.time() + _NO_LIVENESS_TIMEOUT

            now = loop.time()
            if full_content and (now - last_edit_time) > _EDIT_INTERVAL:
                last_edit_time = now
                preview = (
                    f"{status_prefix} {model_label} {status_verb}...\n\n"
                    f"{full_content[-500:]}"
                )
                await on_progress(preview)
    finally:
        # Best-effort close of the underlying httpx stream. If the
        # generator doesn't have ``aclose`` (or it was already cleaned up
        # by a cancellation), just move on.
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:  # pragma: no cover — cleanup best-effort
                pass

    return full_content, tool_calls_acc, last_edit_time


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
    elif model.provider == "nvidia":
        stream_fn = nvidia_stream_chat
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
