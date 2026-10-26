from app.services.intent import Intent, classify_intent, detect_entity
from app.services.query_resolver import resolve_query
from app.services.llm import SYSTEM_PROMPT


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


import pytest
from types import SimpleNamespace

from app.services.llm import LLMService


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
