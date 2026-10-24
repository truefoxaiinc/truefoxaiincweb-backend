import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from openai import RateLimitError

from app.config import get_settings
from app.database import migrate
from app.services.embeddings import EmbeddingProviderError, EmbeddingService, local_embedding
from app.services.repository import create_conversation, save_document, save_message
from scripts.migrate_embeddings import rollback_embeddings, run_migration, verify_database


class FakeProvider:
    provider = "openrouter"

    def __init__(self, model: str, *, fail: bool = False, wrong_dimensions: bool = False):
        self.last_model = model
        self.fail = fail
        self.wrong_dimensions = wrong_dimensions

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise EmbeddingProviderError("provider failure")
        dimensions = 511 if self.wrong_dimensions else 512
        return [local_embedding(text, dimensions) for text in texts]


class FailingEmbeddingClient:
    async def create(self, **_kwargs):
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/embeddings")
        response = httpx.Response(429, request=request, json={"error": {"code": "rate_limit"}})
        raise RateLimitError("provider unavailable", response=response, body={"error": {"code": "rate_limit"}})


class ReturningEmbeddingClient:
    def __init__(self, model: str, vector: list[float]):
        self.model = model
        self.vector = vector

    async def create(self, *, input, **_kwargs):
        data = [SimpleNamespace(index=index, embedding=self.vector) for index, _ in enumerate(input)]
        return SimpleNamespace(model=self.model, data=data)


def _seed_database(path: Path, monkeypatch) -> tuple[list[tuple], list[tuple]]:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", path)
    migrate()
    content = "# Web Development\n\nTruefox AI provides website and web application development services."
    embedding = local_embedding(content, 512)
    save_document(
        title="Web Development", source="/services", mime_type="text/markdown", checksum="test-checksum",
        metadata={"document_type": "service"}, chunks=[(content, embedding, {"heading": "Web Development"})],
    )
    conversation_id, _ = create_conversation(24)
    save_message(conversation_id, "user", "I need a website")
    save_message(conversation_id, "assistant", "Verified answer", [{"title": "Web Development"}])
    return _snapshot(path)


def _snapshot(path: Path) -> tuple[list[tuple], list[tuple]]:
    with sqlite3.connect(path) as connection:
        documents = connection.execute("SELECT id,title,source,checksum,metadata FROM documents ORDER BY id").fetchall()
        chunks = connection.execute("SELECT id,document_id,content,metadata,embedding FROM chunks ORDER BY id").fetchall()
        conversations = connection.execute("SELECT id,capability_hash FROM conversations ORDER BY id").fetchall()
        messages = connection.execute("SELECT id,conversation_id,role,content,citations FROM messages ORDER BY id").fetchall()
    return documents + conversations + messages, chunks


def _backup(database: Path, backup_path: Path) -> None:
    with sqlite3.connect(database) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)


def _provider_settings(monkeypatch, database: Path):
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", database)
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key-not-logged")
    monkeypatch.setattr(settings, "openrouter_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "embedding_model", "openai/text-embedding-3-small")
    monkeypatch.setattr(settings, "embedding_dimensions", 512)
    monkeypatch.setattr(settings, "mock_llm", False)
    return settings


@pytest.mark.asyncio
async def test_embedding_provider_failure_raises_without_local_fallback(monkeypatch, caplog):
    settings = get_settings()
    monkeypatch.setattr(settings, "openrouter_api_key", "sk-secret-test")
    monkeypatch.setattr(settings, "openrouter_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "mock_llm", False)
    monkeypatch.setattr(settings, "app_env", "development")
    service = EmbeddingService()
    service.client.embeddings = SimpleNamespace(create=FailingEmbeddingClient().create)

    with pytest.raises(EmbeddingProviderError):
        await service.embed_many(["private query text"])

    assert "fallback=local" not in caplog.text
    assert "sk-secret-test" not in caplog.text
    assert "private query text" not in caplog.text


@pytest.mark.asyncio
async def test_embedding_service_checks_provider_model_dimensions_and_count(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "embedding_dimensions", 512)
    monkeypatch.setattr(settings, "embedding_model", "openai/text-embedding-3-small")
    monkeypatch.setattr(settings, "mock_llm", False)
    monkeypatch.setattr(settings, "app_env", "development")
    service = EmbeddingService()
    vector = [1.0] + [0.0] * 511
    service.client.embeddings = ReturningEmbeddingClient(settings.embedding_model, vector)
    assert len(await service.embed_many(["one", "two"])) == 2

    service.client.embeddings = ReturningEmbeddingClient("different/model", vector)
    with pytest.raises(EmbeddingProviderError, match="unexpected model"):
        await service.embed_many(["one"])

    service.client.embeddings = ReturningEmbeddingClient(settings.embedding_model, [1.0])
    with pytest.raises(EmbeddingProviderError, match="unexpected dimension"):
        await service.embed_many(["one"])


@pytest.mark.asyncio
async def test_local_hash_embeddings_are_limited_to_explicit_nonproduction_mock(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    monkeypatch.setattr(settings, "mock_llm", True)
    monkeypatch.setattr(settings, "app_env", "development")
    service = EmbeddingService()
    assert service.provider == "local"
    assert len(await service.embed_one("test")) == settings.embedding_dimensions

    monkeypatch.setattr(settings, "app_env", "production")
    service = EmbeddingService()
    assert service.provider == "openrouter"
    with pytest.raises(EmbeddingProviderError):
        await service.embed_one("test")


@pytest.mark.asyncio
async def test_embedding_failure_does_not_write_ingested_document(tmp_path, monkeypatch):
    from app.services import ingestion

    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", tmp_path / "rag.sqlite3")
    migrate()

    class FailedService:
        async def embed_many(self, _texts):
            raise EmbeddingProviderError("provider unavailable")

    monkeypatch.setattr(ingestion, "EmbeddingService", FailedService)
    with pytest.raises(EmbeddingProviderError):
        await ingestion.ingest_text(title="Web Development", source="/services", text="Verified website development services content.")
    with closing(sqlite3.connect(get_settings().database_file)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_dry_run_does_not_modify_database(tmp_path, monkeypatch):
    database = tmp_path / "rag.sqlite3"
    before = _seed_database(database, monkeypatch)
    settings = _provider_settings(monkeypatch, database)

    await run_migration(database, settings=settings, embedder=FakeProvider(settings.embedding_model))

    assert _snapshot(database) == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='embedding_metadata'").fetchone() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", [FakeProvider("openai/text-embedding-3-small", fail=True), FakeProvider("openai/text-embedding-3-small", wrong_dimensions=True)])
async def test_failed_apply_leaves_all_embeddings_unchanged(tmp_path, monkeypatch, provider):
    database = tmp_path / "rag.sqlite3"
    before = _seed_database(database, monkeypatch)
    backup = tmp_path / "rag-backup.sqlite3"
    _backup(database, backup)
    settings = _provider_settings(monkeypatch, database)

    with pytest.raises((EmbeddingProviderError, ValueError)):
        await run_migration(database, apply=True, backup=backup, settings=settings, embedder=provider)

    assert _snapshot(database) == before


@pytest.mark.asyncio
async def test_apply_preserves_records_and_stores_compatible_vectors(tmp_path, monkeypatch):
    database = tmp_path / "rag.sqlite3"
    before = _seed_database(database, monkeypatch)
    backup = tmp_path / "rag-backup.sqlite3"
    _backup(database, backup)
    settings = _provider_settings(monkeypatch, database)
    provider = FakeProvider(settings.embedding_model)

    await run_migration(database, apply=True, backup=backup, settings=settings, embedder=provider)

    after = _snapshot(database)
    assert [row[:-1] for row in after[1]] == [row[:-1] for row in before[1]]
    assert after[0] == before[0]
    stored = json.loads(after[1][0][-1])
    fresh = (await provider.embed_many([after[1][0][2]]))[0]
    cosine = sum(left * right for left, right in zip(stored, fresh, strict=True))
    assert cosine == pytest.approx(1.0)
    with sqlite3.connect(database) as connection:
        provenance = connection.execute("SELECT provider,model,dimensions,vector_count FROM embedding_metadata WHERE id=1").fetchone()
    assert provenance == ("openrouter", settings.embedding_model, 512, 1)
    count, minimum = await verify_database(database, settings=settings, embedder=provider)
    assert count == 1
    assert minimum == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_rollback_restores_only_vectors_and_preserves_new_messages(tmp_path, monkeypatch):
    database = tmp_path / "rag.sqlite3"
    _seed_database(database, monkeypatch)
    backup = tmp_path / "rag-backup.sqlite3"
    _backup(database, backup)
    settings = _provider_settings(monkeypatch, database)
    await run_migration(database, apply=True, backup=backup, settings=settings, embedder=FakeProvider(settings.embedding_model))
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO messages(id,conversation_id,role,content,citations,created_at) "
            "SELECT 'new-message',id,'user','message after backup','[]','2026-01-01T00:00:00+00:00' FROM conversations LIMIT 1"
        )
        connection.commit()

    rollback_embeddings(database, backup)

    after = _snapshot(database)
    assert after[1] == _snapshot(backup)[1]
    assert any(row[0] == "new-message" for row in after[0])


@pytest.mark.asyncio
async def test_apply_requires_backup_matching_current_chunks(tmp_path, monkeypatch):
    database = tmp_path / "rag.sqlite3"
    _seed_database(database, monkeypatch)
    backup = tmp_path / "rag-backup.sqlite3"
    _backup(database, backup)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE chunks SET content='changed while backup was stale'")
    settings = _provider_settings(monkeypatch, database)

    with pytest.raises(ValueError, match="does not match"):
        await run_migration(database, apply=True, backup=backup, settings=settings, embedder=FakeProvider(settings.embedding_model))
