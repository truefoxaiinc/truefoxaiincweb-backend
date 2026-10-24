from app.services.ingestion import ingest_text
from app.services.intent import Intent
from app.services.query_resolver import resolve_query


async def seed_conversation_knowledge():
    documents = [
        ("Services", "/services", "Truefox AI services include AI development and software engineering.", "service", "AI Development"),
        ("Attention Minder", "/attention-minder", "Attention Minder is a product for attention practice. It uses real-time camera analysis and does not retain camera frames.", "product", "Attention Minder"),
        ("Careers", "/careers", "Truefox AI career applications use the careers page form.", "career", "Truefox AI Careers"),
    ]
    for title, source, text, document_type, entity in documents:
        await ingest_text(title=title, source=source, text=text, metadata={"document_type": document_type, "category": f"{document_type}s", "entity_name": entity})


async def test_follow_up_conversation_keeps_attention_minder_subject(clean_database):
    await seed_conversation_knowledge()
    conversation_id = None
    capability_token = None
    expected = [
        ("What services do you provide?", "/services"),
        ("Products?", "/attention-minder"),
        ("Attention Minder?", "/attention-minder"),
        ("How does it work?", "/attention-minder"),
        ("What are its features?", "/attention-minder"),
    ]
    for query, source in expected:
        response = clean_database.post(
            "/api/v1/chat",
            json={"message": query, "conversation_id": conversation_id},
            headers={"X-Conversation-Capability": capability_token} if capability_token else {},
        )
        assert response.status_code == 200
        payload = response.json()
        conversation_id = payload["conversation_id"]
        if payload["capability_token"]:
            capability_token = payload["capability_token"]
        assert payload["citations"], query
        assert payload["citations"][0]["source"] == source


async def test_unknown_company_claims_do_not_receive_random_context(clean_database):
    await seed_conversation_knowledge()
    for query in ("Who are your clients?", "Which certifications do you have?"):
        payload = clean_database.post("/api/v1/chat", json={"message": query}).json()
        assert payload["citations"] == []
        assert "verified" in payload["answer"].lower()


async def test_project_discovery_keeps_original_user_messages_and_citations(clean_database):
    await ingest_text(
        title="Web Development", source="/web-development",
        text="Truefox AI provides website and web application development, including AI-enabled web experiences.",
        metadata={"document_type": "service", "category": "services", "entity_name": "Web Development"},
    )
    conversation_id = None
    capability = None
    for message in ("I want an AI-enabled website", "AI-enabled web app", "How can you help?", "Yes"):
        response = clean_database.post(
            "/api/v1/chat", json={"message": message, "conversation_id": conversation_id},
            headers={"X-Conversation-Capability": capability} if capability else {},
        )
        assert response.status_code == 200
        body = response.json()
        conversation_id = body["conversation_id"]
        capability = body["capability_token"] or capability
        assert body["citations"]
    saved = clean_database.get(
        f"/api/v1/conversations/{conversation_id}", headers={"X-Conversation-Capability": capability},
    ).json()
    assert [item["content"] for item in saved if item["role"] == "user"] == [
        "I want an AI-enabled website", "AI-enabled web app", "How can you help?", "Yes",
    ]


def test_short_option_selection_uses_prior_website_goal():
    history = [
        {"role": "user", "content": "I want to develop a website."},
        {"role": "assistant", "content": "Would you like a marketing website, customer portal, or AI-enabled web app?"},
    ]
    resolved = resolve_query("AI-enabled web app", history)
    assert resolved.original == "AI-enabled web app"
    assert resolved.used_context is True
    assert resolved.entity == "Web Development"
    assert resolved.intent == Intent.SERVICE_DETAIL
    assert "I want to develop a website" in resolved.retrieval_query
    assert "AI-enabled web app" in resolved.retrieval_query


def test_chatbot_follow_up_after_assistant_question_uses_same_subject():
    history = [
        {"role": "user", "content": "I want to develop a website."},
        {"role": "assistant", "content": "Would you like an AI-enabled web app? We can discuss chatbot features."},
        {"role": "user", "content": "AI-enabled web app"},
        {"role": "assistant", "content": "What AI features are you interested in?"},
    ]
    resolved = resolve_query("Yes, I need a chatbot", history)
    assert resolved.used_context is True
    assert resolved.entity == "Web Development"
    assert "Yes, I need a chatbot" in resolved.retrieval_query
