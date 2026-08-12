from app.services.ingestion import ingest_text


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
    expected = [
        ("What services do you provide?", "/services"),
        ("Products?", "/attention-minder"),
        ("Attention Minder?", "/attention-minder"),
        ("How does it work?", "/attention-minder"),
        ("What are its features?", "/attention-minder"),
    ]
    for query, source in expected:
        response = clean_database.post("/api/v1/chat", json={"message": query, "conversation_id": conversation_id})
        assert response.status_code == 200
        payload = response.json()
        conversation_id = payload["conversation_id"]
        assert payload["citations"], query
        assert payload["citations"][0]["source"] == source


async def test_unknown_company_claims_do_not_receive_random_context(clean_database):
    await seed_conversation_knowledge()
    for query in ("Who are your clients?", "Which certifications do you have?"):
        payload = clean_database.post("/api/v1/chat", json={"message": query}).json()
        assert payload["citations"] == []
        assert "verified" in payload["answer"].lower()
