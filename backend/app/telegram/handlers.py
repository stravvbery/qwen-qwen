"""Telegram message handlers — the core logic of the bot.

Handles:
- Direct messages in PM (any text → AI response)
- Inline queries (@bot query in any chat)
- Status indicators (typing, searching, etc.)
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from aiogram import Bot, Router, types
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from ..fireworks import FireworksError, StreamDelta, ToolCall
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
        "• `клод расскажи про квантовые компьютеры`\n"
        "• `дипсик напиши код на python`\n"
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

    try:
        response_text = await _generate_response(
            bot=bot,
            chat_id=message.chat.id,
            status_msg=status_msg,
            model=result.model,
            prompt=prompt,
        )

        # Final edit with complete response
        final_text = f"**{model_label}:**\n\n{response_text}"
        if len(final_text) > _MAX_MSG_LEN:
            # Split into chunks
            chunks = _split_text(final_text, _MAX_MSG_LEN)
            await status_msg.edit_text(chunks[0], parse_mode=ParseMode.MARKDOWN)
            for chunk in chunks[1:]:
                await message.answer(chunk, parse_mode=ParseMode.MARKDOWN)
        else:
            await status_msg.edit_text(final_text, parse_mode=ParseMode.MARKDOWN)

    except (FireworksError, FreeTheAIError) as e:
        await status_msg.edit_text(
            f"❌ Ошибка от **{model_label}**:\n`{str(e)[:500]}`",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        log.exception("Unexpected error in handle_message")
        await status_msg.edit_text(
            f"❌ Непредвиденная ошибка:\n`{str(e)[:300]}`",
            parse_mode=ParseMode.MARKDOWN,
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


async def _generate_response(
    *,
    bot: Bot,
    chat_id: int,
    status_msg: types.Message,
    model: Any,
    prompt: str,
) -> str:
    """Generate AI response with streaming updates and tool calling."""
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": prompt},
    ]

    # Decide whether to send tools
    tools = TOOL_DEFINITIONS if has_any_provider() else None

    # Pick the right stream function
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
        # Accumulate tool calls
        for tc in delta.tool_calls:
            idx = len(tool_calls_acc)
            if tc.id:
                tool_calls_acc[idx] = ToolCall(id=tc.id, name=tc.name, arguments=tc.arguments)
            elif tool_calls_acc:
                last_key = max(tool_calls_acc.keys())
                tool_calls_acc[last_key].arguments += tc.arguments

        full_content += delta.content

        # Periodic edit to show progress
        now = asyncio.get_event_loop().time()
        if full_content and (now - last_edit_time) > _EDIT_INTERVAL:
            last_edit_time = now
            preview = f"🧠 **{model.label}** генерирует...\n\n{full_content[-500:]}"
            try:
                await status_msg.edit_text(
                    preview[:_MAX_MSG_LEN],
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass  # Telegram rate limit or same content

    # --- Handle tool calls (web search) ---
    if tool_calls_acc:
        for _idx, tc in tool_calls_acc.items():
            # Update status: searching
            try:
                await status_msg.edit_text(
                    f"🔍 **{model.label}** ищет в интернете...\n\n"
                    f"`{tc.name}({tc.arguments[:100]})`",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass

            tool_result = await execute_tool_call(tc.name, tc.arguments)

            # Build messages with tool result and ask for final answer
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

        # Second pass — get final answer with search results
        try:
            await status_msg.edit_text(
                f"✍️ **{model.label}** формирует ответ с учётом поиска...",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

        full_content = ""
        async for delta in stream_fn(
            model=model.id,
            messages=messages,
            tools=None,  # no more tools in second pass
        ):
            full_content += delta.content

            now = asyncio.get_event_loop().time()
            if full_content and (now - last_edit_time) > _EDIT_INTERVAL:
                last_edit_time = now
                preview = f"✍️ **{model.label}** пишет...\n\n{full_content[-500:]}"
                try:
                    await status_msg.edit_text(
                        preview[:_MAX_MSG_LEN],
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except Exception:
                    pass

    return full_content or "(пустой ответ)"


async def _generate_response_simple(
    *,
    model: Any,
    prompt: str,
) -> str:
    """Simple non-streaming generation for inline queries."""
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": prompt},
    ]

    if model.provider == "freetheai":
        stream_fn = freetheai_stream_chat
    else:
        stream_fn = fireworks_stream_chat

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
