from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class Citation(BaseModel):
    document_id: str
    title: str
    source: str
    chunk_id: str
    score: float
    excerpt: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, max_length=100)


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    citations: list[Citation]


class DocumentResponse(BaseModel):
    id: str
    title: str
    source: str
    mime_type: str
    chunk_count: int
    created_at: str


class TextIngestRequest(BaseModel):
    title: str = Field(min_length=2, max_length=240)
    text: str = Field(min_length=20, max_length=500_000)
    source: str = Field(default="manual", max_length=1000)
    metadata: dict[str, str] = Field(default_factory=dict)


class UrlIngestRequest(BaseModel):
    url: HttpUrl
    title: str | None = Field(default=None, max_length=240)


class ConversationMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    citations: list[Citation]
    created_at: str
