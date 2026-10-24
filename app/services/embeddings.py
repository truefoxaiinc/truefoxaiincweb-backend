import hashlib
import logging
import math
import numbers
import re

from openai import AsyncOpenAI, OpenAIError

from app.config import get_settings

logger = logging.getLogger(__name__)
SAFE_PROVIDER_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")


class EmbeddingProviderError(RuntimeError):
    """Raised when compatible provider embeddings are unavailable or invalid."""


def _safe_provider_error_code(error: OpenAIError) -> str:
    code = getattr(error, "code", None)
    if not isinstance(code, str):
        body = getattr(error, "body", None)
        detail = body.get("error") if isinstance(body, dict) else None
        code = detail.get("code") if isinstance(detail, dict) else None
    return code if isinstance(code, str) and SAFE_PROVIDER_CODE.fullmatch(code) else "none"


def _normalize(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / magnitude for value in vector]


def local_embedding(text: str, dimensions: int) -> list[float]:
    """Deterministic feature-hash embedding for local tests and offline development."""
    vector = [0.0] * dimensions
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    for token in tokens:
        digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign
    return _normalize(vector)


class EmbeddingService:
    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.provider = "openrouter"
        self.last_model: str | None = None
        local_mode = settings.mock_llm and settings.app_env != "production"
        self.client = (
            AsyncOpenAI(api_key=settings.openrouter_api_key, base_url=settings.openrouter_base_url)
            if settings.openrouter_api_key and not local_mode
            else None
        )
        if not self.client and local_mode:
            self.provider = "local"

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.client:
            if self.provider == "local":
                return [local_embedding(text, self.settings.embedding_dimensions) for text in texts]
            raise EmbeddingProviderError("OpenRouter embeddings are not configured")
        try:
            response = await self.client.embeddings.create(
                model=self.settings.embedding_model,
                input=texts,
                dimensions=self.settings.embedding_dimensions,
                encoding_format="float",
            )
            response_model = getattr(response, "model", None)
            if response_model != self.settings.embedding_model:
                logger.error(
                    "embedding_model_mismatch provider=openrouter configured_model=%s response_model=%s",
                    self.settings.embedding_model, response_model or "none",
                )
                raise EmbeddingProviderError("Embedding provider returned an unexpected model")
            items = sorted(response.data, key=lambda item: item.index)
            if len(items) != len(texts) or [item.index for item in items] != list(range(len(texts))):
                raise EmbeddingProviderError("Embedding provider returned an unexpected item count or order")
            vectors: list[list[float]] = []
            for item in items:
                vector = item.embedding
                if len(vector) != self.settings.embedding_dimensions:
                    raise EmbeddingProviderError("Embedding provider returned an unexpected dimension")
                if any(isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(value) for value in vector):
                    raise EmbeddingProviderError("Embedding provider returned an invalid vector")
                normalized = _normalize([float(value) for value in vector])
                if not any(normalized):
                    raise EmbeddingProviderError("Embedding provider returned a zero vector")
                vectors.append(normalized)
            self.last_model = response_model
            return vectors
        except OpenAIError as error:
            response = getattr(error, "response", None)
            status_code = getattr(error, "status_code", None) or getattr(response, "status_code", None)
            request_id = getattr(error, "request_id", None) or (response.headers.get("x-request-id") if response is not None else None)
            logger.error(
                "provider_request_failed provider=openrouter operation=embeddings.create model=%s error_type=%s status_code=%s error_code=%s request_id=%s",
                self.settings.embedding_model, type(error).__name__, status_code or "none", _safe_provider_error_code(error), request_id or "none",
            )
            raise EmbeddingProviderError("OpenRouter embedding request failed") from None

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed_many([text]))[0]
