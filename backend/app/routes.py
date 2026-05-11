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
from .fireworks import FireworksError, StreamDelta, stream_chat
from .models import Chat, Message

router = APIRouter(prefix="/api", tags=["chat"])


# --- model catalog -----------------------------------------------------------

# Curated list — only the four models the user picked. Kept server-side so the
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
        description="Универсальная модель, поддерживает картинки и инструменты.",
        context_length=262_144,
        supports_reasoning=True,
    ),
    schemas.ModelInfo(
        id="accounts/fireworks/models/qwen3p6-plus",
        label="Qwen3.6 Plus",
        description="Qwen 3.6 Plus — быстрая модель общего назначения.",
        context_length=None,
        supports_reasoning=True,
    ),
    schemas.ModelInfo(
        id="accounts/fireworks/models/minimax-m2p7",
        label="MiniMax M2.7",
        description="MiniMax M2.7 — мощный generalist.",
        context_length=196_608,
        supports_reasoning=False,
    ),
]

_MODEL_IDS = {m.id for m in MODELS}


def _ensure_model(model_id: str) -> None:
    if model_id not in _MODEL_IDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown model: {model_id}",
        )


# --- routes ------------------------------------------------------------------


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/models", response_model=list[schemas.ModelInfo])
async def list_models() -> list[schemas.ModelInfo]:
    return MODELS


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


def _build_messages(chat: Chat, history: list[Message]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if chat.system_prompt:
        out.append({"role": "system", "content": chat.system_prompt})
    for m in history:
        if m.role not in {"user", "assistant", "system"}:
            continue
        if m.role == "assistant" and not m.content:
            continue
        out.append({"role": m.role, "content": m.content})
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

    if chat.model != model_id:
        chat.model = model_id
    if payload.system_prompt is not None:
        chat.system_prompt = payload.system_prompt or None

    user_msg = Message(chat_id=chat.id, role="user", content=payload.content, model=model_id)
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
    first_user_excerpt = payload.content.strip().splitlines()[0][:60] if should_title else None

    await db.commit()

    async def event_stream() -> AsyncIterator[str]:
        # Use a fresh session inside the streaming generator — the dependency-
        # provided session is closed once this function returns.
        from .db import SessionLocal

        content_buf: list[str] = []
        reasoning_buf: list[str] = []
        finish_reason: str | None = None

        yield _sse(
            "meta",
            {
                "user_message": {
                    "id": user_msg_id,
                    "chat_id": chat_id_val,
                    "role": "user",
                    "content": payload.content,
                    "created_at": user_created.isoformat(),
                    "model": model_id,
                },
                "assistant_message_id": assistant_msg_id,
                "model": model_id,
            },
        )

        try:
            async for delta in stream_chat(model=model_id, messages=fw_messages):
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
