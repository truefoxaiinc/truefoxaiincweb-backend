import hashlib
import logging
import math
import re

from openai import AsyncOpenAI, OpenAIError

from app.config import get_settings

logger = logging.getLogger(__name__)


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
        self.client = (
            AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
            if settings.openai_api_key and not settings.mock_llm
            else None
        )

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.client:
            return [local_embedding(text, self.settings.embedding_dimensions) for text in texts]
        try:
            response = await self.client.embeddings.create(
                model=self.settings.embedding_model,
                input=texts,
                dimensions=self.settings.embedding_dimensions,
                encoding_format="float",
            )
            return [_normalize(item.embedding) for item in sorted(response.data, key=lambda item: item.index)]
        except OpenAIError as error:
            logger.error("embedding_provider_failed provider=openai model=%s error=%s", self.settings.embedding_model, type(error).__name__)
            return [local_embedding(text, self.settings.embedding_dimensions) for text in texts]

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed_many([text]))[0]
