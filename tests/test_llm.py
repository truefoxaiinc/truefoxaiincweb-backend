from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError, RateLimitError

from app.services.embeddings import EmbeddingProviderError, EmbeddingService
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
        return outcome


class FakeClient:
    def __init__(self, outcomes):
        self.responses = FakeResponses(outcomes)


class FakeEmbeddings:
    def __init__(self, error):
        self.error = error

    async def create(self, **kwargs):
        raise self.error


def rate_limit_error():
    body = {
        "error": {
            "message": "customer request text and sk-test-sensitive-key",
            "type": "insufficient_quota",
            "code": "insufficient_quota",
        }
    }
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/responses", headers={"Authorization": "Bearer sk-test-sensitive-key"})
    response = httpx.Response(429, request=request, json=body)
    return RateLimitError("provider error", response=response, body=body)


def response(text, **kwargs):
    values = {"output_text": text, "id": "resp_test", "status": "completed", "output": [], "usage": None, "incomplete_details": None}
    values.update(kwargs)
    return SimpleNamespace(**values)


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
async def test_sales_request_without_context_receives_a_useful_contact_reply():
    service = LLMService()
    service.client = None
    answer = await service.answer(
        "I am from Ontario and need a sales agent. Can we have a discussion?",
        [], [], intent=Intent.CONTACT, entity=None,
    )
    assert "start a conversation" in answer.lower()
    assert "temporarily unable" not in answer


@pytest.mark.asyncio
async def test_successful_provider_answer_is_returned_with_grounding():
    service = LLMService()
    service.client = FakeClient([response("Truefox AI builds verified web applications.")])
    answer = await service.answer(
        "I need a website for my company", [], ["# Web Development\nTruefox AI builds web applications."],
        intent=Intent.UNKNOWN, entity=None,
    )
    assert answer == "Truefox AI builds verified web applications."
    sent = service.client.responses.calls[0]["input"][0]["content"]
    assert "APPROVED CONTEXT" in sent
    assert "Web Development" in sent
    assert service.client.responses.calls[0]["max_output_tokens"] == 2048
    assert service.client.responses.calls[0]["reasoning"] == {"effort": "low"}


@pytest.mark.asyncio
async def test_empty_output_logs_safe_response_diagnostics(caplog):
    service = LLMService()
    service.client = FakeClient([response(None, status="incomplete", incomplete_details=SimpleNamespace(reason="max_output_tokens"), output=[SimpleNamespace(type="reasoning")], usage=SimpleNamespace(input_tokens=10, output_tokens=2, total_tokens=12, output_tokens_details=SimpleNamespace(reasoning_tokens=2)))])
    answer = await service.answer("Services?", [{"role": "user", "content": "private history"}], ["private context"], intent=Intent.SERVICES, entity=None, conversation_id="conv-test")
    assert "temporarily unable" in answer
    assert "incomplete_reason=max_output_tokens" in caplog.text
    assert "private history" not in caplog.text
    assert "private context" not in caplog.text


@pytest.mark.asyncio
async def test_timeout_is_retried_once_then_succeeds():
    timeout = APITimeoutError(request=httpx.Request("POST", "https://openrouter.ai/api/v1/responses"))
    service = LLMService()
    service.client = FakeClient([timeout, response("Recovered answer")])
    answer = await service.answer("Services?", [], ["Verified service context"], intent=Intent.SERVICES, entity=None)
    assert answer == "Recovered answer"
    assert len(service.client.responses.calls) == 2


@pytest.mark.asyncio
async def test_repeated_timeout_returns_safe_fallback():
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/responses")
    service = LLMService()
    service.client = FakeClient([APITimeoutError(request=request), APITimeoutError(request=request)])
    answer = await service.answer("Products?", [], ["Verified product context"], intent=Intent.PRODUCTS, entity=None)
    assert "temporarily unable" in answer
    assert len(service.client.responses.calls) == 2


@pytest.mark.asyncio
async def test_rate_limit_logs_safe_provider_code_without_sensitive_details(caplog):
    first_error, final_error = rate_limit_error(), rate_limit_error()
    service = LLMService()
    service.client = FakeClient([first_error, final_error])
    await service.answer(
        "customer request text", [], ["private customer context"],
        intent=Intent.UNKNOWN, entity=None, conversation_id="conversation-private",
    )

    embedding_service = EmbeddingService()
    embedding_service.client = SimpleNamespace(embeddings=FakeEmbeddings(rate_limit_error()))
    with pytest.raises(EmbeddingProviderError):
        await embedding_service.embed_many(["private customer text"])

    assert "error_code=insufficient_quota" in caplog.text
    assert "sk-test-sensitive-key" not in caplog.text
    assert "customer request text" not in caplog.text
    assert "private customer context" not in caplog.text
    assert "private customer text" not in caplog.text
