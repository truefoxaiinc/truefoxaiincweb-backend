import json
import logging
from collections.abc import AsyncIterator

from fastapi import HTTPException

from app.config import get_settings
from app.schemas import ChatResponse
from app.services.intent import Intent
from app.services.llm import LLMService
from app.services.query_resolver import ResolvedQuery, resolve_query
from app.services.repository import authorize_conversation, create_conversation, recent_messages, save_message, touch_conversation
from app.services.retrieval import retrieve

logger = logging.getLogger(__name__)


def _get_conversation(conversation_id: str | None, capability: str) -> tuple[str, str | None]:
    if conversation_id is None and not capability:
        return create_conversation(get_settings().conversation_capability_ttl_hours)
    if not conversation_id or not capability or not authorize_conversation(conversation_id, capability):
        raise HTTPException(status_code=404, detail="Conversation not found or unauthorized")
    touch_conversation(conversation_id)
    return conversation_id, None


async def _prepare(message: str, conversation_id: str, new_capability: str | None) -> tuple[str, str | None, list[dict[str, str]], ResolvedQuery, list[dict[str, object]], list]:
    identifier = conversation_id
    history = recent_messages(identifier, limit=8)
    resolved = resolve_query(message, history)
    if resolved.intent == Intent.SMALL_TALK:
        return identifier, new_capability, history, resolved, [], []
    matches, citations = await retrieve(resolved.retrieval_query, intent=resolved.intent, entity=resolved.entity)
    return identifier, new_capability, history, resolved, matches, citations


async def chat(message: str, conversation_id: str | None, capability: str = "") -> ChatResponse:
    identifier, new_capability = _get_conversation(conversation_id, capability)
    identifier, new_capability, history, resolved, matches, citations = await _prepare(message, identifier, new_capability)
    save_message(identifier, "user", message)
    relevant_history = history[-6:] if resolved.used_context or resolved.intent == Intent.SMALL_TALK else []
    answer = await LLMService().answer(resolved.retrieval_query, relevant_history, [str(item["content"]) for item in matches], intent=resolved.intent, entity=resolved.entity, conversation_id=identifier)
    citation_data = [item.model_dump() for item in citations]
    save_message(identifier, "assistant", answer, citation_data)
    logger.info("chat_completed intent=%s entity=%s context_chunks=%d contextual=%s", resolved.intent, resolved.entity or "none", len(matches), resolved.used_context)
    return ChatResponse(conversation_id=identifier, capability_token=new_capability, answer=answer, citations=citations)


async def stream_chat(message: str, conversation_id: str | None, capability: str = "") -> AsyncIterator[str]:
    identifier, new_capability = _get_conversation(conversation_id, capability)
    identifier, new_capability, history, resolved, matches, citations = await _prepare(message, identifier, new_capability)
    save_message(identifier, "user", message)
    citation_data = [item.model_dump() for item in citations]
    meta = {"conversation_id": identifier, "citations": citation_data}
    if new_capability:
        meta["capability_token"] = new_capability
    yield _event("meta", meta)
    pieces: list[str] = []
    relevant_history = history[-6:] if resolved.used_context or resolved.intent == Intent.SMALL_TALK else []
    async for delta in LLMService().stream(resolved.retrieval_query, relevant_history, [str(item["content"]) for item in matches], intent=resolved.intent, entity=resolved.entity, conversation_id=identifier):
        pieces.append(delta)
        yield _event("delta", {"text": delta})
    save_message(identifier, "assistant", "".join(pieces).strip(), citation_data)
    yield _event("done", {"conversation_id": identifier})


def _event(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
