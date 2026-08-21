from dataclasses import dataclass

from app.services.intent import Intent, classify_intent, detect_entity


@dataclass(frozen=True)
class ResolvedQuery:
    original: str
    retrieval_query: str
    intent: Intent
    entity: str | None
    used_context: bool


def resolve_query(message: str, history: list[dict[str, str]]) -> ResolvedQuery:
    detected = classify_intent(message)
    if detected.intent != Intent.FOLLOW_UP:
        return ResolvedQuery(message, message, detected.intent, detected.entity, False)
    subject = _recent_subject(history)
    if not subject:
        return ResolvedQuery(message, message, Intent.UNKNOWN, None, False)
    rewritten = f"{message.rstrip(' ?.!')} about {subject}"
    resolved = classify_intent(rewritten)
    intent = resolved.intent if resolved.intent != Intent.UNKNOWN else detected.intent
    return ResolvedQuery(message, rewritten, intent, subject, True)


def _recent_subject(history: list[dict[str, str]]) -> str | None:
    recent = history[-8:]
    for item in reversed(recent):
        if item.get("role") != "user":
            continue
        entity = detect_entity(item.get("content", ""))
        if entity:
            return entity
    for item in reversed(recent):
        entity = detect_entity(item.get("content", ""))
        if entity:
            return entity
        intent = classify_intent(item.get("content", ""))
        subjects = {
            Intent.PRODUCTS: "Truefox AI products",
            Intent.SERVICES: "Truefox AI services",
            Intent.CAREERS: "Truefox AI careers",
            Intent.CONTACT: "Truefox AI contact options",
            Intent.DEMO: "Truefox AI demonstrations",
        }
        if intent.intent in subjects:
            return subjects[intent.intent]
    return None
