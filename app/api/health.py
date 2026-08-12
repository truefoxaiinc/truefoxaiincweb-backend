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
        "services": {
            "llm_configured": bool(settings.openai_api_key) and not settings.mock_llm,
            "embedding_provider_configured": bool(settings.openai_api_key) and not settings.mock_llm,
            "chat_model": settings.chat_model,
            "embedding_model": settings.embedding_model,
            "mock_mode": settings.mock_llm,
        },
        "knowledge": {
            "document_count": database["counts"]["documents"],
            "chunk_count": database["counts"]["chunks"],
        },
    }
