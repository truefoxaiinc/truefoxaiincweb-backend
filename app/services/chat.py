import json
import re
from collections.abc import AsyncIterator

from app.schemas import ChatResponse
from app.services.llm import LLMService
from app.services.repository import ensure_conversation, recent_messages, save_message
from app.services.retrieval import retrieve

SMALL_TALK = re.compile(
    r"^(?:hi|hello|hey|hiya|howdy|good\s+(?:morning|afternoon|evening)|how\s+are\s+you|"
    r"how(?:'s| is)\s+it\s+going|thanks?|thank\s+you|bye|goodbye)[!,.?\s]*$",
    re.IGNORECASE,
)


def is_small_talk(message: str) -> bool:
    return bool(SMALL_TALK.fullmatch(message.strip()))


async def chat(message: str, conversation_id: str | None) -> ChatResponse:
    identifier = ensure_conversation(conversation_id)
    history = recent_messages(identifier)
    previous_user = next((item["content"] for item in reversed(history) if item["role"] == "user"), "")
    retrieval_query = f"{previous_user}\n{message}" if previous_user else message
    matches, citations = ([], []) if is_small_talk(message) else await retrieve(retrieval_query)
    save_message(identifier, "user", message)
    answer = await LLMService().answer(message, history, [item["content"] for item in matches])
    citation_data = [item.model_dump() for item in citations]
    save_message(identifier, "assistant", answer, citation_data)
    return ChatResponse(conversation_id=identifier, answer=answer, citations=citations)


async def stream_chat(message: str, conversation_id: str | None) -> AsyncIterator[str]:
    identifier = ensure_conversation(conversation_id)
    history = recent_messages(identifier)
    previous_user = next((item["content"] for item in reversed(history) if item["role"] == "user"), "")
    retrieval_query = f"{previous_user}\n{message}" if previous_user else message
    matches, citations = ([], []) if is_small_talk(message) else await retrieve(retrieval_query)
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
