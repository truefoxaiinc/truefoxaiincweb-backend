from fastapi import APIRouter

from app.config import get_settings
from app.database import database_health

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, object]:
    settings = get_settings()
    database = database_health()
    return {
        "status": "ok" if database["status"] == "ok" else "degraded",
        "database": database,
        "llm": {
            "configured": bool(settings.openai_api_key) and not settings.mock_llm,
            "provider": "openai",
            "model": settings.chat_model,
            "mock_mode": settings.mock_llm,
        },
        "embeddings": {
            "configured": bool(settings.openai_api_key) and not settings.mock_llm,
            "provider": "openai",
            "model": settings.embedding_model,
        },
        "knowledge": {
            "document_count": database["counts"]["documents"],
            "chunk_count": database["counts"]["chunks"],
        },
    }
