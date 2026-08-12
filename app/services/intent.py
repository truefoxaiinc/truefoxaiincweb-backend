import re
from dataclasses import dataclass
from enum import StrEnum


class Intent(StrEnum):
    SMALL_TALK = "SMALL_TALK"
    COMPANY_OVERVIEW = "COMPANY_OVERVIEW"
    SERVICES = "SERVICES"
    PRODUCTS = "PRODUCTS"
    PRODUCT_DETAIL = "PRODUCT_DETAIL"
    SERVICE_DETAIL = "SERVICE_DETAIL"
    CAREERS = "CAREERS"
    CONTACT = "CONTACT"
    DEMO = "DEMO"
    FOLLOW_UP = "FOLLOW_UP"
    UNKNOWN = "UNKNOWN"


KNOWN_ENTITIES = {
    "attention minder": "Attention Minder",
    "ai development": "AI Development",
    "artificial intelligence": "AI Development",
    "software development": "Software Development",
    "web development": "Web Development",
    "website development": "Web Development",
    "cloud": "Cloud",
    "automation": "Automation",
    "ai agents": "AI Agents",
    "agentic ai": "AI Agents",
}


@dataclass(frozen=True)
class QueryIntent:
    intent: Intent
    entity: str | None = None
    confidence: float = 0.7


def normalize_query(text: str) -> str:
    normalized = text.lower().replace("true fox", "truefox")
    normalized = re.sub(r"[^a-z0-9'+]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def detect_entity(text: str) -> str | None:
    normalized = normalize_query(text)
    for alias, entity in sorted(KNOWN_ENTITIES.items(), key=lambda item: len(item[0]), reverse=True):
        if alias in normalized:
            return entity
    return None


def classify_intent(text: str) -> QueryIntent:
    query = normalize_query(text)
    entity = detect_entity(query)
    if re.fullmatch(r"(?:hi|hello|hey|hiya|howdy|good (?:morning|afternoon|evening)|how are you|"
                    r"how(?:'s| is) it going|what(?:'s| is) your name|who are you|thanks?|thank you|bye|goodbye)[! ]*", query):
        return QueryIntent(Intent.SMALL_TALK, confidence=0.99)
    if entity:
        kind = Intent.PRODUCT_DETAIL if entity == "Attention Minder" else Intent.SERVICE_DETAIL
        return QueryIntent(kind, entity, 0.98)
    if re.search(r"\b(career|careers|job|jobs|vacancy|vacancies|apply|application|hiring)\b", query):
        return QueryIntent(Intent.CAREERS, confidence=0.95)
    if re.search(r"\b(contact|email|phone|address|location|office|reach)\b", query):
        return QueryIntent(Intent.CONTACT, confidence=0.95)
    if re.search(r"\b(demo|demonstration|book a demo|schedule)\b", query):
        return QueryIntent(Intent.DEMO, confidence=0.95)
    if re.search(r"\b(products?|apps?)\b", query):
        return QueryIntent(Intent.PRODUCTS, confidence=0.9)
    if re.search(r"\b(services?|capabilit(?:y|ies)|what do you do|solutions?)\b", query):
        return QueryIntent(Intent.SERVICES, confidence=0.9)
    if re.search(r"\b(truefox|company|about you|who is truefox)\b", query):
        return QueryIntent(Intent.COMPANY_OVERVIEW, confidence=0.85)
    if _depends_on_context(query):
        return QueryIntent(Intent.FOLLOW_UP, confidence=0.85)
    return QueryIntent(Intent.UNKNOWN, confidence=0.5)


def _depends_on_context(query: str) -> bool:
    return bool(re.fullmatch(
        r"(?:tell me more|more|what about (?:that|it)|how does (?:that|it) work|how it works|"
        r"what are (?:its|the) features|features|pricing|price|is it available(?: in [a-z ]+)?|"
        r"what technologies do you use for (?:that|it)|availability)[?.! ]*",
        query,
    ))
