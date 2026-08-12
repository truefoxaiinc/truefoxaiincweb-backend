import pytest

from app.services.intent import Intent, classify_intent
from app.services.query_resolver import resolve_query


@pytest.mark.parametrize(
    ("query", "intent", "entity"),
    [
        ("Hi", Intent.SMALL_TALK, None),
        ("Hello", Intent.SMALL_TALK, None),
        ("What is Truefox AI?", Intent.COMPANY_OVERVIEW, None),
        ("What services do you provide?", Intent.SERVICES, None),
        ("Products?", Intent.PRODUCTS, None),
        ("Tell me about your products", Intent.PRODUCTS, None),
        ("What is Attention Minder?", Intent.PRODUCT_DETAIL, "Attention Minder"),
        ("What about Attention Minder?", Intent.PRODUCT_DETAIL, "Attention Minder"),
        ("Careers?", Intent.CAREERS, None),
        ("How can I apply?", Intent.CAREERS, None),
        ("Contact details", Intent.CONTACT, None),
        ("Book a demo", Intent.DEMO, None),
    ],
)
def test_intent_matrix(query, intent, entity):
    result = classify_intent(query)
    assert result.intent == intent
    assert result.entity == entity


def test_follow_up_uses_only_recent_subject():
    history = [
        {"role": "user", "content": "What services do you provide?"},
        {"role": "assistant", "content": "Service answer"},
        {"role": "user", "content": "Attention Minder?"},
        {"role": "assistant", "content": "Product answer"},
    ]
    result = resolve_query("How does it work?", history)
    assert result.used_context is True
    assert result.entity == "Attention Minder"
    assert result.retrieval_query == "How does it work about Attention Minder"
    assert "services" not in result.retrieval_query.lower()


def test_standalone_query_does_not_leak_history():
    history = [{"role": "user", "content": "What services do you provide?"}]
    result = resolve_query("Products?", history)
    assert result.retrieval_query == "Products?"
    assert result.used_context is False
