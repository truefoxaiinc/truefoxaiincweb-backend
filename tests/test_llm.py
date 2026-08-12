import pytest

from app.services.intent import Intent
from app.services.llm import LLMService


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
