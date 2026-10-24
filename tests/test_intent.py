import pytest

from app.services.intent import Intent, classify_intent
from app.services.query_resolver import resolve_query
from app.services.website_sync import classify_path


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
        ("I need to make a website for my company", Intent.SERVICE_DETAIL, "Web Development"),
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


def test_confirmation_uses_assistant_proposed_subject():
    history = [{"role": "assistant", "content": "Would you like workflow examples for our AI Agents?"}]
    result = resolve_query("Yes please", history)
    assert result.used_context is True
    assert result.retrieval_query == "Yes please about AI Agents"


@pytest.mark.parametrize("ack", ["yes", "okay", "sure", "continue"])
def test_contextual_acknowledgment_uses_recent_project(ack):
    history = [
        {"role": "user", "content": "I want an AI-enabled website"},
        {"role": "assistant", "content": "What should the AI feature help your customers do?"},
    ]
    result = resolve_query(ack, history)
    assert result.used_context
    assert result.entity == "Web Development"
    assert "AI-enabled website" in result.retrieval_query


def test_how_can_you_help_stays_on_current_project():
    history = [{"role": "user", "content": "AI-enabled web app"}]
    result = resolve_query("How can you help?", history)
    assert result.used_context
    assert result.entity == "Web Development"
    assert "Web Development" in result.retrieval_query


def test_topic_switch_does_not_inherit_previous_project():
    history = [{"role": "user", "content": "I need an AI-enabled web app"}]
    result = resolve_query("How do I apply for a job?", history)
    assert result.intent == Intent.CAREERS
    assert not result.used_context
    assert "Web Development" not in result.retrieval_query


@pytest.mark.parametrize(
    ("assistant_message", "follow_up", "subject"),
    [
        ("Would you like examples of workflows for our Workflow Agents or Agentic Automation?", "Yes please", "Agentic Automation"),
        ("Would you like examples of workflows for Agentic Automation?", "I like to see example of workflow.", "Agentic Automation"),
    ],
)
def test_workflow_follow_up_uses_subject_from_assistant(assistant_message, follow_up, subject):
    result = resolve_query(follow_up, [{"role": "assistant", "content": assistant_message}])
    assert result.used_context is True
    assert result.entity == subject
    assert result.retrieval_query.endswith(f"about {subject}")


@pytest.mark.parametrize("query", ["sales agent", "have a discussion", "talk to someone", "schedule a call", "book a meeting", "contact the team"])
def test_sales_discussion_language_is_contact_intent(query):
    assert classify_intent(query).intent == Intent.CONTACT


@pytest.mark.parametrize("path", ["/agentic-automation", "/private-ai-assistants", "/iot-edge-ai"])
def test_root_level_capability_pages_are_synced_as_services(path):
    assert classify_path(path) == ("service", "services")
