import json
import logging
from collections.abc import AsyncIterator

from app.schemas import ChatResponse
from app.services.intent import Intent
from app.services.llm import LLMService
from app.services.query_resolver import ResolvedQuery, resolve_query
from app.services.repository import ensure_conversation, recent_messages, save_message
from app.services.retrieval import retrieve

logger = logging.getLogger(__name__)


async def _prepare(message: str, conversation_id: str | None) -> tuple[str, list[dict[str, str]], ResolvedQuery, list[dict[str, object]], list]:
    identifier = ensure_conversation(conversation_id)
    history = recent_messages(identifier, limit=8)
    resolved = resolve_query(message, history)
    if resolved.intent == Intent.SMALL_TALK:
        return identifier, history, resolved, [], []
    matches, citations = await retrieve(resolved.retrieval_query, intent=resolved.intent, entity=resolved.entity)
    return identifier, history, resolved, matches, citations


async def chat(message: str, conversation_id: str | None) -> ChatResponse:
    identifier, history, resolved, matches, citations = await _prepare(message, conversation_id)
    save_message(identifier, "user", message)
    relevant_history = history[-6:] if resolved.used_context or resolved.intent == Intent.SMALL_TALK else []
    answer = await LLMService().answer(resolved.retrieval_query, relevant_history, [str(item["content"]) for item in matches], intent=resolved.intent, entity=resolved.entity, conversation_id=identifier)
    citation_data = [item.model_dump() for item in citations]
    save_message(identifier, "assistant", answer, citation_data)
    logger.info("chat_completed intent=%s entity=%s context_chunks=%d contextual=%s", resolved.intent, resolved.entity or "none", len(matches), resolved.used_context)
    return ChatResponse(conversation_id=identifier, answer=answer, citations=citations)


async def stream_chat(message: str, conversation_id: str | None) -> AsyncIterator[str]:
    identifier, history, resolved, matches, citations = await _prepare(message, conversation_id)
    save_message(identifier, "user", message)
    citation_data = [item.model_dump() for item in citations]
    yield _event("meta", {"conversation_id": identifier, "citations": citation_data})
    pieces: list[str] = []
    relevant_history = history[-6:] if resolved.used_context or resolved.intent == Intent.SMALL_TALK else []
    async for delta in LLMService().stream(resolved.retrieval_query, relevant_history, [str(item["content"]) for item in matches], intent=resolved.intent, entity=resolved.entity, conversation_id=identifier):
        pieces.append(delta)
        yield _event("delta", {"text": delta})
    save_message(identifier, "assistant", "".join(pieces).strip(), citation_data)
    yield _event("done", {"conversation_id": identifier})


def _event(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
