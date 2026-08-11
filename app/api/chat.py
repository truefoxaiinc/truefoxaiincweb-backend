from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.schemas import ChatRequest, ChatResponse, ConversationMessage
from app.security import enforce_chat_rate_limit
from app.services.chat import chat, stream_chat
from app.services.repository import conversation_messages

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(enforce_chat_rate_limit)])
async def create_chat(request: ChatRequest) -> ChatResponse:
    return await chat(request.message, request.conversation_id)


@router.post("/chat/stream", dependencies=[Depends(enforce_chat_rate_limit)])
async def create_stream(request: ChatRequest) -> StreamingResponse:
    return StreamingResponse(stream_chat(request.message, request.conversation_id), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/conversations/{conversation_id}", response_model=list[ConversationMessage])
def get_conversation(conversation_id: str) -> list[dict[str, object]]:
    return conversation_messages(conversation_id)
