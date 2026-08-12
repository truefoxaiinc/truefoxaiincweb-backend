import math
import re

from app.config import get_settings
from app.schemas import Citation
from app.services.embeddings import EmbeddingService
from app.services.repository import all_chunks


def cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    denominator = math.sqrt(sum(v * v for v in left)) * math.sqrt(sum(v * v for v in right))
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator if denominator else 0.0


async def retrieve(query: str) -> tuple[list[dict[str, object]], list[Citation]]:
    settings = get_settings()
    query_embedding = await EmbeddingService().embed_one(query)
    ranked: list[tuple[float, dict[str, object]]] = []
    query_terms = set(re.findall(r"[a-z0-9]+", query.lower())) - {"a", "an", "and", "are", "do", "for", "i", "is", "me", "of", "the", "to", "what", "you", "your"}
    for chunk in all_chunks():
        semantic = cosine(query_embedding, chunk["embedding"])
        text_terms = set(re.findall(r"[a-z0-9]+", f"{chunk['title']} {chunk['content']}".lower()))
        lexical = len(query_terms & text_terms) / max(1, len(query_terms))
        score = semantic * 0.72 + lexical * 0.28
        if semantic >= settings.rag_min_score or lexical >= 0.2:
            ranked.append((score, chunk))
    ranked.sort(key=lambda item: item[0], reverse=True)
    matches: list[dict[str, object]] = []
    citations: list[Citation] = []
    used_chars = 0
    for score, chunk in ranked[: settings.rag_top_k]:
        content = str(chunk["content"])
        if used_chars + len(content) > settings.max_context_chars:
            content = content[: max(0, settings.max_context_chars - used_chars)]
        if not content:
            break
        citation = Citation(
            document_id=str(chunk["document_id"]), title=str(chunk["title"]), source=str(chunk["source"]),
            chunk_id=str(chunk["id"]), score=round(score, 4), excerpt=content[:240],
        )
        matches.append({**chunk, "content": content, "score": score})
        citations.append(citation)
        used_chars += len(content)
    return matches, citations
