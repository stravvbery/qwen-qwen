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
import logging
import random
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
from .model_resolver import MODELS, ResolveResult, resolve

log = logging.getLogger(__name__)

router = Router()

# How often to edit the message during streaming (avoid Telegram rate limits)
_EDIT_INTERVAL = 1.5  # seconds
_MAX_MSG_LEN = 4096  # Telegram message limit


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
        lines.append(f"• **{m.label}** [{m.provider}]\n  _{aliases}_")
    await message.answer(
        "🤖 **Доступные модели:**\n\n" + "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# Direct message handler — main AI flow
# ---------------------------------------------------------------------------

@router.message()
async def handle_message(message: types.Message, bot: Bot) -> None:
    """Process any text message: resolve model, call AI, stream response."""
    if not message.text:
        return

    # Resolve model from message text
    result: ResolveResult = resolve(message.text)
    prompt = result.prompt or message.text  # fallback to full text if prompt is empty

    if not prompt.strip():
        await message.answer("Напиши вопрос после названия модели 😊")
        return

    # Send initial status message
    model_label = result.model.label
    if result.was_explicit:
        status_text = f"🧠 **{model_label}** думает..."
    else:
        status_text = f"🎲 Случайная модель: **{model_label}**\n🧠 Думает..."

    status_msg = await message.answer(status_text, parse_mode=ParseMode.MARKDOWN)

    # Start typing indicator
    typing_task = asyncio.create_task(_keep_typing(bot, message.chat.id))

    async def _dm_progress(text: str) -> None:
        try:
            await status_msg.edit_text(text[:_MAX_MSG_LEN], parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass

    try:
        response_text = await _generate_response(
            model=result.model,
            prompt=prompt,
            on_progress=_dm_progress,
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

    result = resolve(query_text)
    prompt = result.prompt or query_text
    model_label = result.model.label

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
            on_progress=_guest_progress,
        )

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


# Type alias for the progress callback used by _generate_response.
_ProgressFn = Callable[[str], Awaitable[None]]


async def _noop_progress(_text: str) -> None:
    pass


async def _safe_edit(
    text: str,
    *,
    msg: types.Message | None = None,
    bot: Bot | None = None,
    inline_message_id: str | None = None,
    parse_mode: str | None = ParseMode.MARKDOWN,
) -> None:
    """Edit a message with automatic Markdown → plain-text fallback."""
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
    """Send a message with automatic Markdown → plain-text fallback."""
    try:
        return await message.answer(text[:_MAX_MSG_LEN], parse_mode=ParseMode.MARKDOWN)
    except TelegramBadRequest as exc:
        if "can't parse entities" in str(exc).lower():
            return await message.answer(text[:_MAX_MSG_LEN])
        raise


async def _generate_response(
    *,
    model: Any,
    prompt: str,
    on_progress: _ProgressFn = _noop_progress,
) -> str:
    """Generate AI response with streaming progress callbacks and tool calling.

    ``on_progress`` is invoked periodically with a status/preview string.
    The caller decides *how* to render it (edit a chat message, edit an
    inline message, etc.).
    """
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": prompt},
    ]

    tools = TOOL_DEFINITIONS if has_any_provider() else None

    if model.provider == "freetheai":
        stream_fn = freetheai_stream_chat
    else:
        stream_fn = fireworks_stream_chat

    # --- First pass: might get tool calls ---
    full_content = ""
    tool_calls_acc: dict[int, ToolCall] = {}
    last_edit_time = 0.0

    async for delta in stream_fn(
        model=model.id,
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

    # --- Handle tool calls (web search) ---
    if tool_calls_acc:
        for _idx, tc in tool_calls_acc.items():
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
            model=model.id,
            messages=messages,
            tools=None,
        ):
            full_content += delta.content

            now = asyncio.get_event_loop().time()
            if full_content and (now - last_edit_time) > _EDIT_INTERVAL:
                last_edit_time = now
                preview = f"✍️ {model.label} пишет...\n\n{full_content[-500:]}"
                await on_progress(preview)

    return full_content or "(пустой ответ)"


async def _generate_response_simple(
    *,
    model: Any,
    prompt: str,
) -> str:
    """Non-streaming AI response with optional web search.

    Used for inline queries and Bot API 10.0 guest mode where we have to
    return a single ``InlineQueryResult`` synchronously instead of streaming
    edits. Performs at most one round of tool calls (web_search / read_webpage)
    to keep latency bounded.
    """
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": prompt},
    ]

    if model.provider == "freetheai":
        stream_fn = freetheai_stream_chat
    else:
        stream_fn = fireworks_stream_chat

    tools = TOOL_DEFINITIONS if has_any_provider() else None

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
        return full_content or "(пустой ответ)"

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

    return full_content or "(пустой ответ)"


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
