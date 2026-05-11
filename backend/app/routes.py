"""HTTP routes for the chat API."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from . import schemas
from .db import get_session
from .fireworks import FireworksError, StreamDelta, ToolCall, stream_chat
from .models import Chat, Message
from .web_tools import TOOL_DEFINITIONS, execute_tool_call, has_any_provider

router = APIRouter(prefix="/api", tags=["chat"])


# --- model catalog -----------------------------------------------------------

# Curated list — only the models the user picked. Kept server-side so the
# browser cannot point the proxy at arbitrary models with the same API key.
MODELS: list[schemas.ModelInfo] = [
    schemas.ModelInfo(
        id="accounts/fireworks/models/deepseek-v4-pro",
        label="DeepSeek V4 Pro",
        description="Сильная reasoning-модель с контекстом 1M токенов.",
        context_length=1_048_576,
        supports_reasoning=True,
    ),
    schemas.ModelInfo(
        id="accounts/fireworks/models/kimi-k2p6",
        label="Kimi K2.6",
        description="Универсальная мультимодальная модель: текст + изображения, инструменты.",
        context_length=262_144,
        supports_reasoning=True,
        supports_vision=True,
    ),
    schemas.ModelInfo(
        id="accounts/fireworks/models/qwen3p6-plus",
        label="Qwen3.6 Plus",
        description="Qwen 3.6 Plus — быстрая мультимодальная модель общего назначения.",
        context_length=None,
        supports_reasoning=True,
        supports_vision=True,
    ),
    schemas.ModelInfo(
        id="accounts/fireworks/models/minimax-m2p7",
        label="MiniMax M2.7",
        description="MiniMax M2.7 — мощный generalist.",
        context_length=196_608,
        supports_reasoning=False,
    ),
    schemas.ModelInfo(
        id="accounts/fireworks/models/glm-5p1",
        label="GLM 5.1",
        description="GLM 5.1 — новый generalist от Zhipu.",
        context_length=None,
        supports_reasoning=True,
    ),
]

_MODEL_IDS = {m.id for m in MODELS}
_MODELS_BY_ID = {m.id: m for m in MODELS}


def _ensure_model(model_id: str) -> None:
    if model_id not in _MODEL_IDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown model: {model_id}",
        )


# Max raw size of a single attachment in bytes (~6 MB before base64 padding).
_MAX_ATTACHMENT_BYTES = 6 * 1024 * 1024


def _validate_attachments(
    model_id: str, attachments: list[str] | None
) -> list[str] | None:
    """Validate image attachments against the chosen model and basic safety limits.

    Returns the normalised list (stripped, non-empty) or ``None``.
    """

    if not attachments:
        return None
    cleaned = [a.strip() for a in attachments if a and a.strip()]
    if not cleaned:
        return None

    model = _MODELS_BY_ID.get(model_id)
    if model is None or not model.supports_vision:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model {model_id} does not support image attachments.",
        )

    for url in cleaned:
        if not (url.startswith("data:image/") or url.startswith("https://")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Attachment must be an https URL or data:image/...;base64 URL.",
            )
        if len(url) > _MAX_ATTACHMENT_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Attachment is too large.",
            )
    return cleaned


# --- routes ------------------------------------------------------------------


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/models", response_model=list[schemas.ModelInfo])
async def list_models() -> list[schemas.ModelInfo]:
    return MODELS


@router.get("/search/status")
async def search_status() -> dict[str, object]:
    """Return which search providers are configured."""
    from .config import settings

    return {
        "enabled": has_any_provider(),
        "providers": {
            "tavily": bool(settings.tavily_api_key),
            "serper": bool(settings.serper_api_key),
            "firecrawl": bool(settings.firecrawl_api_key),
        },
    }


@router.get("/chats", response_model=list[schemas.ChatOut])
async def list_chats(db: AsyncSession = Depends(get_session)) -> list[Chat]:
    result = await db.execute(select(Chat).order_by(Chat.updated_at.desc()))
    return list(result.scalars())


@router.post("/chats", response_model=schemas.ChatOut, status_code=status.HTTP_201_CREATED)
async def create_chat(
    payload: schemas.ChatCreate,
    db: AsyncSession = Depends(get_session),
) -> Chat:
    _ensure_model(payload.model)
    chat = Chat(
        title=payload.title or "Новый чат",
        model=payload.model,
        system_prompt=payload.system_prompt,
    )
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    return chat


async def _get_chat_or_404(chat_id: str, db: AsyncSession) -> Chat:
    chat = await db.get(Chat, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@router.get("/chats/{chat_id}", response_model=schemas.ChatWithMessages)
async def get_chat(chat_id: str, db: AsyncSession = Depends(get_session)) -> Chat:
    result = await db.execute(
        select(Chat).where(Chat.id == chat_id).options(selectinload(Chat.messages))
    )
    chat = result.scalar_one_or_none()
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@router.patch("/chats/{chat_id}", response_model=schemas.ChatOut)
async def update_chat(
    chat_id: str,
    payload: schemas.ChatUpdate,
    db: AsyncSession = Depends(get_session),
) -> Chat:
    chat = await _get_chat_or_404(chat_id, db)
    if payload.title is not None:
        chat.title = payload.title.strip() or chat.title
    if payload.model is not None:
        _ensure_model(payload.model)
        chat.model = payload.model
    if payload.system_prompt is not None:
        chat.system_prompt = payload.system_prompt or None
    await db.commit()
    await db.refresh(chat)
    return chat


@router.delete("/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(chat_id: str, db: AsyncSession = Depends(get_session)) -> None:
    chat = await _get_chat_or_404(chat_id, db)
    await db.execute(delete(Chat).where(Chat.id == chat.id))
    await db.commit()


def _message_content(m: Message) -> str | list[dict[str, object]]:
    """Build the Fireworks ``content`` field for a single stored message.

    User messages with image attachments get an OpenAI-style multimodal
    content list. All other messages keep the plain-string form.
    """

    if m.role == "user" and m.attachments:
        parts: list[dict[str, object]] = []
        if m.content:
            parts.append({"type": "text", "text": m.content})
        for url in m.attachments:
            parts.append({"type": "image_url", "image_url": {"url": url}})
        return parts
    return m.content


def _build_messages(chat: Chat, history: list[Message]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    if chat.system_prompt:
        out.append({"role": "system", "content": chat.system_prompt})
    for m in history:
        if m.role not in {"user", "assistant", "system"}:
            continue
        if m.role == "assistant" and not m.content:
            continue
        out.append({"role": m.role, "content": _message_content(m)})
    return out


def _sse(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chats/{chat_id}/messages")
async def post_message(
    chat_id: str,
    payload: schemas.MessageCreate,
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Append a user message and stream the assistant response as SSE.

    Event stream:
        - ``meta`` (once): ``{user_message, assistant_message_id}``
        - ``delta``: ``{content?, reasoning?}``
        - ``title``: ``{title}`` (once, after the first assistant turn)
        - ``done``: ``{finish_reason}``
        - ``error``: ``{message}``
    """

    chat = await _get_chat_or_404(chat_id, db)
    model_id = payload.model or chat.model
    _ensure_model(model_id)

    attachments = _validate_attachments(model_id, payload.attachments)

    if not payload.content.strip() and not attachments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message must include text or at least one attachment.",
        )

    if chat.model != model_id:
        chat.model = model_id
    if payload.system_prompt is not None:
        chat.system_prompt = payload.system_prompt or None

    user_msg = Message(
        chat_id=chat.id,
        role="user",
        content=payload.content,
        model=model_id,
        attachments=attachments,
    )
    db.add(user_msg)
    await db.flush()

    result = await db.execute(
        select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at)
    )
    history = list(result.scalars())

    assistant_msg = Message(chat_id=chat.id, role="assistant", content="", model=model_id)
    db.add(assistant_msg)
    await db.flush()

    fw_messages = _build_messages(chat, history)
    user_msg_id = user_msg.id
    assistant_msg_id = assistant_msg.id
    chat_id_val = chat.id
    user_created = user_msg.created_at
    assistant_created = assistant_msg.created_at
    should_title = chat.title in {"", "Новый чат"} and not any(
        m.role == "assistant" and m.content for m in history
    )
    if should_title:
        text_stripped = payload.content.strip()
        if text_stripped:
            first_user_excerpt = text_stripped.splitlines()[0][:60]
        elif attachments:
            first_user_excerpt = f"Изображение ({len(attachments)})"
        else:
            first_user_excerpt = None
    else:
        first_user_excerpt = None

    await db.commit()

    use_tools = payload.web_search or has_any_provider()
    tools = TOOL_DEFINITIONS if use_tools else None
    force_search = payload.web_search

    async def event_stream() -> AsyncIterator[str]:
        from .db import SessionLocal

        content_buf: list[str] = []
        reasoning_buf: list[str] = []
        finish_reason: str | None = None
        current_messages = list(fw_messages)

        if force_search:
            current_messages.append({
                "role": "system",
                "content": (
                    "The user has enabled web search for this turn. Use the "
                    "web_search tool to ground your answer in current sources "
                    "when relevant, optionally followed by read_webpage on the "
                    "most useful link. After the search results are returned, "
                    "stop calling tools and write the final answer for the "
                    "user. Do not search more than necessary."
                ),
            })

        yield _sse(
            "meta",
            {
                "user_message": {
                    "id": user_msg_id,
                    "chat_id": chat_id_val,
                    "role": "user",
                    "content": payload.content,
                    "attachments": attachments,
                    "created_at": user_created.isoformat(),
                    "model": model_id,
                },
                "assistant_message_id": assistant_msg_id,
                "model": model_id,
            },
        )

        max_tool_rounds = 5

        try:
            for _round in range(max_tool_rounds):
                # Tool calls are merged by their stable ``index`` field, since
                # OpenAI-style streams emit ``id``/``name`` only on the first
                # fragment and split ``arguments`` across many chunks for that
                # same index.
                pending_tool_calls: dict[int, ToolCall] = {}

                async for delta in stream_chat(
                    model=model_id,
                    messages=current_messages,
                    tools=tools,
                ):
                    assert isinstance(delta, StreamDelta)
                    if delta.content:
                        content_buf.append(delta.content)
                    if delta.reasoning:
                        reasoning_buf.append(delta.reasoning)
                    if delta.finish_reason:
                        finish_reason = delta.finish_reason
                    if delta.content or delta.reasoning:
                        yield _sse(
                            "delta",
                            {
                                "content": delta.content,
                                "reasoning": delta.reasoning,
                            },
                        )

                    for tc in delta.tool_calls:
                        existing = pending_tool_calls.get(tc.index)
                        if existing is None:
                            pending_tool_calls[tc.index] = ToolCall(
                                id=tc.id,
                                name=tc.name,
                                arguments=tc.arguments,
                                index=tc.index,
                            )
                        else:
                            if tc.id and not existing.id:
                                existing.id = tc.id
                            if tc.name and not existing.name:
                                existing.name = tc.name
                            if tc.arguments:
                                existing.arguments += tc.arguments

                if not pending_tool_calls:
                    break

                # Drop malformed entries (missing id or name) — submitting
                # them back to the model would either be rejected or trigger
                # another tool-call loop.
                valid_calls = [
                    tc for tc in pending_tool_calls.values() if tc.id and tc.name
                ]
                if not valid_calls:
                    break

                assistant_tc_msg: dict[str, object] = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": tc.arguments or "{}",
                            },
                        }
                        for tc in valid_calls
                    ],
                }
                current_messages.append(assistant_tc_msg)

                for tc in valid_calls:
                    yield _sse(
                        "tool_status",
                        {"tool": tc.name, "status": "running", "arguments": tc.arguments},
                    )

                    result = await execute_tool_call(tc.name, tc.arguments)

                    yield _sse(
                        "tool_status",
                        {
                            "tool": tc.name,
                            "status": "done",
                            "result_preview": result[:300] if result else "",
                        },
                    )

                    current_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": result,
                    })

                content_buf.clear()
                reasoning_buf.clear()
                finish_reason = None
            else:
                # Hit max_tool_rounds without the model producing a final
                # textual answer. Force one more pass with tools disabled so
                # the model must summarise the tool results instead of
                # endlessly requesting more searches.
                content_buf.clear()
                reasoning_buf.clear()
                finish_reason = None
                async for delta in stream_chat(
                    model=model_id,
                    messages=current_messages,
                    tools=None,
                ):
                    assert isinstance(delta, StreamDelta)
                    if delta.content:
                        content_buf.append(delta.content)
                    if delta.reasoning:
                        reasoning_buf.append(delta.reasoning)
                    if delta.finish_reason:
                        finish_reason = delta.finish_reason
                    if delta.content or delta.reasoning:
                        yield _sse(
                            "delta",
                            {
                                "content": delta.content,
                                "reasoning": delta.reasoning,
                            },
                        )

        except FireworksError as exc:
            async with SessionLocal() as session:
                msg = await session.get(Message, assistant_msg_id)
                if msg is not None:
                    msg.content = "".join(content_buf)
                    msg.reasoning = "".join(reasoning_buf) or None
                    await session.commit()
            yield _sse("error", {"message": str(exc)})
            return
        except Exception as exc:  # pragma: no cover - safety net
            yield _sse("error", {"message": f"Internal error: {exc!s}"})
            return

        final_content = "".join(content_buf)
        final_reasoning = "".join(reasoning_buf) or None

        async with SessionLocal() as session:
            msg = await session.get(Message, assistant_msg_id)
            if msg is not None:
                msg.content = final_content
                msg.reasoning = final_reasoning
                await session.commit()

            new_title: str | None = None
            if should_title and first_user_excerpt:
                new_title = first_user_excerpt
                chat_db = await session.get(Chat, chat_id_val)
                if chat_db is not None:
                    chat_db.title = new_title
                    await session.commit()

        if new_title:
            yield _sse("title", {"title": new_title})

        yield _sse(
            "done",
            {
                "finish_reason": finish_reason,
                "assistant_message": {
                    "id": assistant_msg_id,
                    "chat_id": chat_id_val,
                    "role": "assistant",
                    "content": final_content,
                    "reasoning": final_reasoning,
                    "model": model_id,
                    "created_at": assistant_created.isoformat(),
                },
            },
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
