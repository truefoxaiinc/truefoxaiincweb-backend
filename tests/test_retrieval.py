import pytest

from app.services.ingestion import ingest_text
from app.services.intent import Intent
from app.services.retrieval import debug_retrieve, retrieve


async def add(title, source, text, document_type, entity):
    return await ingest_text(
        title=title,
        source=source,
        text=text,
        metadata={"document_type": document_type, "category": f"{document_type}s", "entity_name": entity},
    )


@pytest.mark.asyncio
async def test_attention_minder_beats_unrelated_documents(clean_database):
    await add("Attention Minder", "/attention-minder", "Attention Minder supports focus habits. It uses live camera analysis for attention shifts and screen engagement. Camera frames are not retained.", "product", "Attention Minder")
    await add("Careers", "/careers", "Apply for engineering careers using the online application form.", "career", "Truefox AI Careers")
    await add("Company", "/about", "Truefox AI is an artificial intelligence company.", "company", "Truefox AI")
    matches, citations = await retrieve("What is Attention Minder?", intent=Intent.PRODUCT_DETAIL, entity="Attention Minder")
    assert matches
    assert all(item["metadata"]["entity_name"] == "Attention Minder" for item in matches)
    assert [item.source for item in citations] == ["/attention-minder"]


@pytest.mark.asyncio
async def test_products_services_and_careers_stay_in_category(clean_database):
    await add("Attention Minder", "/attention-minder", "Attention Minder is a focus and attention-support application.", "product", "Attention Minder")
    await add("AI Development", "/services", "Truefox AI develops grounded assistants and computer vision systems.", "service", "AI Development")
    await add("Careers", "/careers", "Current jobs and application instructions are on the careers page.", "career", "Truefox AI Careers")
    cases = [("Products?", Intent.PRODUCTS, "product"), ("Services?", Intent.SERVICES, "service"), ("Careers?", Intent.CAREERS, "career")]
    for query, intent, expected_type in cases:
        matches, _ = await retrieve(query, intent=intent)
        assert matches, query
        assert matches[0]["metadata"]["document_type"] == expected_type


@pytest.mark.asyncio
async def test_generic_words_do_not_force_unrelated_match(clean_database):
    await add("Careers", "/careers", "Apply for a software engineering role.", "career", "Truefox AI Careers")
    matches, citations = await retrieve("Which certifications do you have?", intent=Intent.UNKNOWN)
    assert matches == []
    assert citations == []


@pytest.mark.asyncio
async def test_debug_retrieve_has_explainable_scores(clean_database):
    await add("Attention Minder", "/attention-minder", "Attention Minder provides attention monitoring.", "product", "Attention Minder")
    result = await debug_retrieve("Attention Minder", intent=Intent.PRODUCT_DETAIL, entity="Attention Minder")
    candidate = result["candidates"][0]
    assert {"semantic", "lexical", "title_match", "entity_match", "intent_boost", "final", "accepted", "reason"} <= candidate.keys()
