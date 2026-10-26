from types import SimpleNamespace

import pytest

from app.services.intent import Intent, classify_intent
from app.services.llm import SYSTEM_PROMPT, LLMService
from app.services.query_resolver import resolve_query


def test_cctv_and_camera_requests_map_to_security():
    for message in ("I want a security system", "Camera based intelligent security system", "CCTV surveillance", "video analytics"):
        classified = classify_intent(message)
        assert classified.intent == Intent.SERVICE_DETAIL
        assert classified.entity == "AI Smart Security"


def test_security_short_followup_preserves_visitor_goal():
    history = [
        {"role": "user", "content": "I want to know about security systems"},
        {"role": "assistant", "content": "What kind of location are you securing?"},
    ]
    resolved = resolve_query("Camera based intelligent security system", history)
    assert resolved.entity == "AI Smart Security"
    assert resolved.intent == Intent.SERVICE_DETAIL
    assert "security systems" in resolved.retrieval_query


def test_sales_prompt_preserves_grounding_and_transparency():
    assert "not a human employee" in SYSTEM_PROMPT
    assert "Company-specific claims must be supported" in SYSTEM_PROMPT
    assert "at most ONE relevant next question" in SYSTEM_PROMPT


class RecordingResponses:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text="Could you tell me which cameras are already installed?")


@pytest.mark.asyncio
async def test_missing_rag_context_still_allows_grounded_discovery():
    service = LLMService()
    responses = RecordingResponses()
    service.client = SimpleNamespace(responses=responses)
    answer = await service.answer(
        "Camera based intelligent security system",
        [{"role": "user", "content": "I want to know about security systems"}],
        [], intent=Intent.SERVICE_DETAIL, entity="AI Smart Security",
    )
    assert "which cameras" in answer
    assert len(responses.calls) == 1
    assert "No relevant company facts were retrieved" in responses.calls[0]["input"][-1]["content"]

@pytest.mark.parametrize(
    ("question", "entity"),
    [
        ("We need facial recognition attendance", "Biometric Intelligence"),
        ("Build a private knowledge assistant", "Private AI Assistants"),
        ("Can you do agentic automation?", "Agentic Automation"),
        ("Connect IoT sensors with edge processing", "IoT & Edge AI"),
        ("We need predictive analytics", "Custom AI & ML"),
        ("Please build a mobile app", "Web & Mobile Products"),
        ("Can you create a proof of concept?", "R&D & Product Validation"),
        ("AI-powered CCTV security for a restaurant", "AI Smart Security"),
    ],
)
def test_primary_service_intents(question, entity):
    result = classify_intent(question)
    assert result.intent == Intent.SERVICE_DETAIL
    assert result.entity == entity


def test_all_services_question_does_not_select_one_entity():
    result = classify_intent("What other services do you offer?")
    assert result.intent == Intent.SERVICES


def test_greeting_with_requirement_is_not_discarded():
    question = "Hi, I need AI-powered CCTV for my restaurant."
    result = classify_intent(question)
    assert result.intent == Intent.SERVICE_DETAIL
    assert LLMService.deterministic_reply(question, result.intent, result.entity) is None


def test_no_unverified_pricing_guardrail():
    assert "numerical illustrative pricing" in SYSTEM_PROMPT
