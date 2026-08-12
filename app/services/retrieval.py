import logging
import math
import re
from dataclasses import asdict, dataclass

from app.config import get_settings
from app.schemas import Citation
from app.services.embeddings import EmbeddingService
from app.services.intent import Intent, normalize_query
from app.services.repository import all_chunks

logger = logging.getLogger(__name__)

COMMON_TERMS = {
    "a", "about", "ai", "an", "and", "are", "business", "company", "do", "for", "i", "in", "is",
    "me", "of", "our", "product", "products", "provide", "providing", "service", "services", "solution", "solutions", "technology",
    "the", "to", "truefox", "what", "with", "you", "your",
}

INTENT_TYPES = {
    Intent.COMPANY_OVERVIEW: {"company"}, Intent.SERVICES: {"service"}, Intent.SERVICE_DETAIL: {"service"},
    Intent.PRODUCTS: {"product"}, Intent.PRODUCT_DETAIL: {"product"}, Intent.CAREERS: {"career"},
    Intent.CONTACT: {"contact"}, Intent.DEMO: {"contact", "demo"},
}


@dataclass(frozen=True)
class CandidateScore:
    document_id: str
    title: str
    source: str
    semantic: float
    lexical: float
    title_match: float
    entity_match: float
    intent_boost: float
    penalty: float
    final: float
    accepted: bool
    reason: str


def cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    denominator = math.sqrt(sum(v * v for v in left)) * math.sqrt(sum(v * v for v in right))
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator if denominator else 0.0


def distinctive_terms(text: str) -> set[str]:
    return {_stem(token) for token in re.findall(r"[a-z0-9]+", normalize_query(text)) if token not in COMMON_TERMS}


def _stem(token: str) -> str:
    if token.startswith("appl"):
        return "apply"
    if token.startswith("provid"):
        return "provide"
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
    if token.endswith("s") and len(token) > 4:
        return token[:-1]
    return token


async def retrieve(
    query: str,
    *,
    intent: Intent = Intent.UNKNOWN,
    entity: str | None = None,
    include_debug: bool = False,
) -> tuple[list[dict[str, object]], list[Citation]] | tuple[list[dict[str, object]], list[Citation], list[dict[str, object]]]:
    settings = get_settings()
    query_embedding = await EmbeddingService().embed_one(query)
    query_terms = distinctive_terms(query)
    normalized = normalize_query(query)
    scored: list[tuple[CandidateScore, dict[str, object]]] = []
    for chunk in all_chunks():
        metadata = chunk.get("metadata", {})
        content = f"{chunk['title']} {metadata.get('heading', '')} {chunk['content']}"
        content_terms = distinctive_terms(content)
        overlap = query_terms & content_terms
        lexical = len(overlap) / max(1, len(query_terms)) if query_terms else 0.0
        title = normalize_query(str(chunk["title"]))
        heading = normalize_query(str(metadata.get("heading", "")))
        exact_label = any(label and (label in normalized or normalized in label) for label in (title, heading))
        label_terms = distinctive_terms(f"{title} {heading}")
        title_match = 1.0 if exact_label else len(query_terms & label_terms) / max(1, len(query_terms))
        chunk_entity = normalize_query(str(metadata.get("entity_name", "")))
        entity_match = 1.0 if entity and chunk_entity == normalize_query(entity) else 0.0
        document_type = str(metadata.get("document_type", ""))
        expected = INTENT_TYPES.get(intent, set())
        intent_boost = 1.0 if document_type in expected else 0.0
        penalty = 0.22 if expected and document_type and document_type not in expected else 0.0
        semantic = max(0.0, cosine(query_embedding, chunk["embedding"]))
        final = semantic * 0.5 + lexical * 0.2 + title_match * 0.16 + entity_match * 0.1 + intent_boost * 0.34 - penalty
        category_query = not query_terms and intent_boost == 1.0
        strong_match = entity_match == 1.0 or category_query or (title_match >= 0.8 and lexical >= 0.33)
        enough_signal = len(overlap) >= 1 and (len(query_terms) == 1 or lexical >= 0.34)
        accepted = (final >= settings.rag_min_score and (semantic >= 0.2 or enough_signal)) or (strong_match and final >= settings.rag_min_score - 0.08)
        reason = "accepted" if accepted else "below-quality-gate"
        scored.append((CandidateScore(str(chunk["document_id"]), str(chunk["title"]), str(chunk["source"]), round(semantic, 4), round(lexical, 4), round(title_match, 4), entity_match, intent_boost, penalty, round(final, 4), accepted, reason), chunk))
    scored.sort(key=lambda item: item[0].final, reverse=True)
    accepted = [(score, chunk) for score, chunk in scored if score.accepted]
    if not accepted:
        logger.info("retrieval_no_results intent=%s entity=%s candidates=%d", intent, entity or "none", len(scored))
    matches: list[dict[str, object]] = []
    citations: list[Citation] = []
    documents: set[str] = set()
    used_chars = 0
    for score, chunk in accepted:
        if len(matches) >= settings.rag_top_k:
            break
        content = str(chunk["content"])
        remaining = settings.max_context_chars - used_chars
        if remaining < 100:
            break
        content = content[:remaining]
        matches.append({**chunk, "content": content, "score": score.final, "score_detail": asdict(score)})
        if score.document_id not in documents and len(citations) < 3:
            citations.append(Citation(document_id=score.document_id, title=score.title, source=score.source, chunk_id=str(chunk["id"]), score=score.final, excerpt=content[:240]))
            documents.add(score.document_id)
        used_chars += len(content)
    if include_debug:
        return matches, citations, [asdict(score) for score, _ in scored[:10]]
    return matches, citations


async def debug_retrieve(query: str, *, intent: Intent = Intent.UNKNOWN, entity: str | None = None) -> dict[str, object]:
    matches, _, candidates = await retrieve(query, intent=intent, entity=entity, include_debug=True)
    return {"query": query, "intent": intent, "entity": entity, "accepted": len(matches), "candidates": candidates}
