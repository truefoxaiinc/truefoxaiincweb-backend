from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import StreamingResponse

from app.schemas import ChatRequest, ChatResponse, ConversationMessage
from app.security import enforce_chat_rate_limit
from app.services.chat import chat, stream_chat
from app.services.repository import authorize_conversation, conversation_messages

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(enforce_chat_rate_limit)])
async def create_chat(
    request: ChatRequest,
    response: Response,
    x_conversation_capability: str = Header(default=""),
) -> ChatResponse:
    response.headers["Cache-Control"] = "no-store"
    return await chat(request.message, request.conversation_id, x_conversation_capability)


@router.post("/chat/stream", dependencies=[Depends(enforce_chat_rate_limit)])
async def create_stream(
    request: ChatRequest,
    x_conversation_capability: str = Header(default=""),
) -> StreamingResponse:
    if request.conversation_id is not None and not authorize_conversation(request.conversation_id, x_conversation_capability):
        raise HTTPException(status_code=404, detail="Conversation not found or unauthorized")
    if request.conversation_id is None and x_conversation_capability:
        raise HTTPException(status_code=404, detail="Conversation not found or unauthorized")
    return StreamingResponse(stream_chat(request.message, request.conversation_id, x_conversation_capability), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.get("/conversations/{conversation_id}", response_model=list[ConversationMessage])
def get_conversation(conversation_id: str, x_conversation_capability: str = Header(default="")) -> list[dict[str, object]]:
    if not authorize_conversation(conversation_id, x_conversation_capability):
        raise HTTPException(status_code=404, detail="Conversation not found or unauthorized")
    return conversation_messages(conversation_id)
