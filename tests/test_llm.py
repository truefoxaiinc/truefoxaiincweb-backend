from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError

from app.services.intent import Intent
from app.services.llm import LLMService


class FakeResponses:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(output_text=outcome)


class FakeClient:
    def __init__(self, outcomes):
        self.responses = FakeResponses(outcomes)


@pytest.mark.asyncio
async def test_provider_unavailable_never_dumps_raw_context():
    service = LLMService()
    service.client = None
    raw = "# Attention Minder\nSecret-looking raw markdown chunk with many implementation details."
    answer = await service.answer("What is Attention Minder?", [], [raw], intent=Intent.PRODUCT_DETAIL, entity="Attention Minder")
    assert "temporarily unable" in answer
    assert "raw markdown" not in answer
    assert "Here's the short version" not in answer


@pytest.mark.asyncio
async def test_deterministic_small_talk_works_without_provider():
    service = LLMService()
    service.client = None
    answer = await service.answer("Hello", [], [], intent=Intent.SMALL_TALK, entity=None)
    assert answer == "Hi! How can I help you with Truefox AI today?"


@pytest.mark.asyncio
async def test_successful_provider_answer_is_returned_with_grounding():
    service = LLMService()
    service.client = FakeClient(["Truefox AI builds verified web applications."])
    answer = await service.answer(
        "I need a website for my company", [], ["# Web Development\nTruefox AI builds web applications."],
        intent=Intent.UNKNOWN, entity=None,
    )
    assert answer == "Truefox AI builds verified web applications."
    sent = service.client.responses.calls[0]["input"][0]["content"]
    assert "APPROVED CONTEXT" in sent
    assert "Web Development" in sent


@pytest.mark.asyncio
async def test_timeout_is_retried_once_then_succeeds():
    timeout = APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    service = LLMService()
    service.client = FakeClient([timeout, "Recovered answer"])
    answer = await service.answer("Services?", [], ["Verified service context"], intent=Intent.SERVICES, entity=None)
    assert answer == "Recovered answer"
    assert len(service.client.responses.calls) == 2


@pytest.mark.asyncio
async def test_repeated_timeout_returns_safe_fallback():
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    service = LLMService()
    service.client = FakeClient([APITimeoutError(request=request), APITimeoutError(request=request)])
    answer = await service.answer("Products?", [], ["Verified product context"], intent=Intent.PRODUCTS, entity=None)
    assert "temporarily unable" in answer
    assert len(service.client.responses.calls) == 2
