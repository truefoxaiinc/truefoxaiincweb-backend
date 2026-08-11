from fastapi import APIRouter

from app.config import get_settings
from app.database import database_health

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, object]:
    settings = get_settings()
    return {"status": "ok", "database": database_health(), "llm_configured": bool(settings.openai_api_key), "embedding_model": settings.embedding_model}
