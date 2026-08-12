import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.knowledge import router as knowledge_router
from app.api.website import router as website_router
from app.config import get_settings
from app.database import migrate

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrate()
    runtime = get_settings()
    if runtime.mock_llm:
        logger.warning("startup_llm_unavailable reason=mock_mode model=%s", runtime.chat_model)
    elif not runtime.openai_api_key:
        logger.warning("startup_llm_unavailable reason=missing_api_key model=%s", runtime.chat_model)
    else:
        logger.info("startup_llm_configured provider=openai model=%s embedding_model=%s base_url_custom=%s", runtime.chat_model, runtime.embedding_model, bool(runtime.openai_base_url))
    yield


settings = get_settings()
app = FastAPI(
    title="Truefox AI RAG API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.app_env != "production" else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_frontend_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Key"],
)
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(knowledge_router)
app.include_router(website_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "Truefox AI RAG API", "health": "/health"}
