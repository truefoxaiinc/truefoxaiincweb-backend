import re
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
    # Short selections ("AI-enabled web app") often contain a recognizable
    # service entity, so intent classification alone cannot tell that they
    # continue the prior turn. Preserve the latest user goal and assistant
    # prompt as retrieval hints without changing the message saved to history.
    contextual = detected.intent == Intent.FOLLOW_UP or _is_short_continuation(message) or _is_contextual_question(message)
    if not contextual or not history:
        return ResolvedQuery(message, _expand_web_development(message, detected.entity), detected.intent, detected.entity, False)
    subject = detected.entity or _recent_subject(history)
    if not subject:
        if detected.intent != Intent.FOLLOW_UP:
            return ResolvedQuery(message, message, detected.intent, detected.entity, False)
        return ResolvedQuery(message, message, Intent.UNKNOWN, None, False)
    cleaned_message = message.rstrip().rstrip("?.!")
    prior_goal = next((
        item.get("content", "") for item in reversed(history)
        if item.get("role") == "user" and item.get("content", "").strip()
        and not _is_acknowledgment(item.get("content", ""))
    ), "")
    if subject == "Web Development":
        rewritten = f"{subject}. Visitor's request: {prior_goal}. Follow-up: {cleaned_message}"
    else:
        rewritten = f"{cleaned_message} about {subject}"
    resolved = classify_intent(rewritten)
    intent = detected.intent if detected.intent not in {Intent.UNKNOWN, Intent.FOLLOW_UP} else resolved.intent
    if intent in {Intent.UNKNOWN, Intent.FOLLOW_UP}:
        intent = Intent.SERVICE_DETAIL if subject == "Web Development" else Intent.UNKNOWN
    return ResolvedQuery(message, _expand_web_development(rewritten, subject), intent, subject, True)


def _is_short_continuation(message: str) -> bool:
    query = message.strip().lower()
    words = query.split()
    if not 0 < len(words) <= 8:
        return False
    return bool(
        detect_entity(query)
        or query.startswith(("yes", "sure", "okay", "ok", "continue", "go on", "i need", "i want", "we need", "we want"))
        or query in {"a chatbot", "chatbot", "for my business", "for our business"}
    )


def _is_acknowledgment(message: str) -> bool:
    return bool(re.fullmatch(r"\s*(?:yes(?: please)?|okay|ok|sure|continue|go on|please do)[?.! ]*", message, re.IGNORECASE))


def _is_contextual_question(message: str) -> bool:
    return bool(re.fullmatch(r"\s*(?:how can (?:you|truefox ai) help(?: me| us)?|tell me more|what technologies do you use)[?.! ]*", message, re.IGNORECASE))


def _expand_web_development(query: str, entity: str | None) -> str:
    if entity != "Web Development":
        return query
    # Canonical service terminology compensates for short phrasing and common
    # spelling mistakes while keeping the visitor's original text in history.
    cleaned = re.sub(r"\banabled\b", "enabled", query, flags=re.IGNORECASE)
    return f"Web Development website web application {cleaned}"


def _recent_subject(history: list[dict[str, str]]) -> str | None:
    recent = history[-8:]
    for item in reversed(recent):
        if item.get("role") != "user":
            continue
        entity = detect_entity(item.get("content", ""))
        if entity:
            return entity
    for item in reversed(recent):
        if item.get("role") != "user":
            continue
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
    # Assistant replies can mention several unrelated offerings; use them only
    # when the visitor has not supplied a subject.
    for item in reversed(recent):
        if item.get("role") != "assistant":
            continue
        entity = detect_entity(item.get("content", ""))
        if entity:
            return entity
    return None
