import json
from collections.abc import AsyncIterator

from app.schemas import ChatResponse
from app.services.llm import LLMService
from app.services.repository import ensure_conversation, recent_messages, save_message
from app.services.retrieval import retrieve


async def chat(message: str, conversation_id: str | None) -> ChatResponse:
    identifier = ensure_conversation(conversation_id)
    history = recent_messages(identifier)
    matches, citations = await retrieve(message)
    save_message(identifier, "user", message)
    answer = await LLMService().answer(message, history, [item["content"] for item in matches])
    citation_data = [item.model_dump() for item in citations]
    save_message(identifier, "assistant", answer, citation_data)
    return ChatResponse(conversation_id=identifier, answer=answer, citations=citations)


async def stream_chat(message: str, conversation_id: str | None) -> AsyncIterator[str]:
    identifier = ensure_conversation(conversation_id)
    history = recent_messages(identifier)
    matches, citations = await retrieve(message)
    save_message(identifier, "user", message)
    citation_data = [item.model_dump() for item in citations]
    yield _event("meta", {"conversation_id": identifier, "citations": citation_data})
    pieces: list[str] = []
    async for delta in LLMService().stream(message, history, [item["content"] for item in matches]):
        pieces.append(delta)
        yield _event("delta", {"text": delta})
    answer = "".join(pieces).strip()
    save_message(identifier, "assistant", answer, citation_data)
    yield _event("done", {"conversation_id": identifier})


def _event(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
