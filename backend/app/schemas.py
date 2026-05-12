"""Pydantic request and response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ModelInfo(BaseModel):
    id: str
    label: str
    description: str
    provider: str = "fireworks"
    context_length: int | None = None
    supports_reasoning: bool = False
    supports_vision: bool = False


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chat_id: str
    role: str
    content: str
    reasoning: str | None = None
    model: str | None = None
    attachments: list[str] | None = None
    created_at: datetime


class ChatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    model: str
    system_prompt: str | None = None
    created_at: datetime
    updated_at: datetime


class ChatWithMessages(ChatOut):
    messages: list[MessageOut] = Field(default_factory=list)


class ChatCreate(BaseModel):
    title: str | None = None
    model: str
    system_prompt: str | None = None


class ChatUpdate(BaseModel):
    title: str | None = None
    model: str | None = None
    system_prompt: str | None = None


class MessageCreate(BaseModel):
    content: str = Field(default="", max_length=200_000)
    model: str | None = None  # override chat model for this send
    system_prompt: str | None = None
    attachments: list[str] | None = Field(
        default=None,
        max_length=8,
        description="Optional list of image data URLs (data:image/...;base64,...) for vision models.",
    )
    web_search: bool = Field(
        default=False,
        description="When True, force the model to search the web before answering.",
    )
