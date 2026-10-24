"""Safely regenerate existing SQLite chunk vectors without replacing records."""

import argparse
import asyncio
import json
import math
import numbers
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from app.config import Settings, get_settings
from app.services.embeddings import EmbeddingService

PROVENANCE_TABLE = "embedding_metadata"
BATCH_SIZE = 32
MIN_COMPATIBLE_COSINE = 0.999


def _open_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=15)


def _check_backup(database: Path, backup: Path) -> None:
    if database.resolve() == backup.resolve() or not backup.is_file():
        raise ValueError("A separate, existing SQLite backup is required")
    with closing(_open_readonly(backup)) as connection:
        integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError("Backup SQLite integrity check failed")
        backup_docs = connection.execute("SELECT id FROM documents ORDER BY id").fetchall()
        backup_chunks = connection.execute("SELECT id, document_id, content FROM chunks ORDER BY id").fetchall()
    with closing(_open_readonly(database)) as connection:
        current_docs = connection.execute("SELECT id FROM documents ORDER BY id").fetchall()
        current_chunks = connection.execute("SELECT id, document_id, content FROM chunks ORDER BY id").fetchall()
    if backup_docs != current_docs or backup_chunks != current_chunks:
        raise ValueError("Backup does not match the current documents and chunk content")


def _validate_vectors(vectors: list[list[float]], *, expected: int, dimensions: int) -> None:
    if len(vectors) != expected:
        raise ValueError(f"Embedding provider returned {len(vectors)} vectors; expected {expected}")
    for index, vector in enumerate(vectors):
        if len(vector) != dimensions:
            raise ValueError(f"Embedding vector {index} has an unexpected dimension")
        if any(isinstance(value, bool) or not isinstance(value, numbers.Real) or not math.isfinite(value) for value in vector):
            raise ValueError(f"Embedding vector {index} contains an invalid value")
        if not any(value != 0 for value in vector):
            raise ValueError(f"Embedding vector {index} is zero")


def _validate_provider(settings: Settings, embedder: EmbeddingService) -> None:
    parsed = urlparse(settings.openrouter_base_url)
    if parsed.scheme != "https" or parsed.hostname != "openrouter.ai":
        raise ValueError("Migration requires the verified OpenRouter HTTPS endpoint")
    if not settings.openrouter_api_key or settings.mock_llm:
        raise ValueError("Migration requires a configured live provider and mock mode disabled")
    if not settings.embedding_model or settings.embedding_dimensions < 1:
        raise ValueError("Embedding model and dimensions must be configured")
    if getattr(embedder, "provider", None) != "openrouter":
        raise ValueError("Migration refuses non-OpenRouter embeddings")


def _chunks(path: Path) -> list[tuple[str, str]]:
    with closing(_open_readonly(path)) as connection:
        return [tuple(row) for row in connection.execute("SELECT id, content FROM chunks ORDER BY id")]


def _write_migration(
    database: Path,
    original_chunks: list[tuple[str, str]],
    vectors: list[list[float]],
    *,
    provider: str,
    model: str,
    dimensions: int,
) -> None:
    connection = sqlite3.connect(database, timeout=30)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        current = [tuple(row) for row in connection.execute("SELECT id, content FROM chunks ORDER BY id")]
        if current != original_chunks:
            raise ValueError("Chunk IDs or content changed during embedding generation")
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS {PROVENANCE_TABLE} ("
            "id INTEGER PRIMARY KEY CHECK (id = 1), provider TEXT NOT NULL, model TEXT NOT NULL, "
            "dimensions INTEGER NOT NULL, vector_count INTEGER NOT NULL, updated_at TEXT NOT NULL)"
        )
        for (chunk_id, _), vector in zip(original_chunks, vectors, strict=True):
            cursor = connection.execute("UPDATE chunks SET embedding=? WHERE id=?", (json.dumps(vector), chunk_id))
            if cursor.rowcount != 1:
                raise ValueError("A chunk changed during migration")
        connection.execute(
            f"INSERT INTO {PROVENANCE_TABLE}(id,provider,model,dimensions,vector_count,updated_at) "
            "VALUES(1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET provider=excluded.provider, "
            "model=excluded.model, dimensions=excluded.dimensions, vector_count=excluded.vector_count, "
            "updated_at=excluded.updated_at",
            (provider, model, dimensions, len(vectors), datetime.now(UTC).isoformat()),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


async def run_migration(
    database: Path,
    *,
    apply: bool = False,
    backup: Path | None = None,
    settings: Settings | None = None,
    embedder: EmbeddingService | None = None,
) -> int:
    settings = settings or get_settings()
    embedder = embedder or EmbeddingService()
    _validate_provider(settings, embedder)
    chunks = _chunks(database)
    if not chunks:
        raise ValueError("No chunks found; refusing an empty migration")
    if apply:
        if backup is None:
            raise ValueError("--apply requires --backup pointing to a verified SQLite backup")
        _check_backup(database, backup)

    vectors: list[list[float]] = []
    contents = [content for _, content in chunks]
    for offset in range(0, len(contents), BATCH_SIZE):
        batch = contents[offset:offset + BATCH_SIZE]
        generated = await embedder.embed_many(batch)
        _validate_vectors(generated, expected=len(batch), dimensions=settings.embedding_dimensions)
        vectors.extend(generated)
    _validate_vectors(vectors, expected=len(chunks), dimensions=settings.embedding_dimensions)
    if getattr(embedder, "last_model", settings.embedding_model) != settings.embedding_model:
        raise ValueError("Embedding provider model does not match configured model")

    if apply:
        _write_migration(
            database, chunks, vectors, provider="openrouter", model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )
        print(f"Applied embeddings to {len(chunks)} existing chunks; document and chunk records were preserved.")
    else:
        print(f"Dry run valid: {len(chunks)} chunks; provider=openrouter model={settings.embedding_model} dimensions={settings.embedding_dimensions}. Database unchanged.")
    return len(chunks)


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


async def verify_database(
    database: Path,
    *,
    settings: Settings | None = None,
    embedder: EmbeddingService | None = None,
) -> tuple[int, float]:
    settings = settings or get_settings()
    embedder = embedder or EmbeddingService()
    _validate_provider(settings, embedder)
    with closing(_open_readonly(database)) as connection:
        provenance = connection.execute(
            f"SELECT provider,model,dimensions,vector_count FROM {PROVENANCE_TABLE} WHERE id=1"
        ).fetchone()
        stored = connection.execute("SELECT id,content,embedding FROM chunks ORDER BY id").fetchall()
    if not provenance or tuple(provenance) != ("openrouter", settings.embedding_model, settings.embedding_dimensions, len(stored)):
        raise ValueError("Stored embedding provenance does not match configured provider/model/dimensions")
    stored_vectors = [json.loads(row[2]) for row in stored]
    _validate_vectors(stored_vectors, expected=len(stored), dimensions=settings.embedding_dimensions)
    fresh: list[list[float]] = []
    for offset in range(0, len(stored), BATCH_SIZE):
        batch = [row[1] for row in stored[offset:offset + BATCH_SIZE]]
        generated = await embedder.embed_many(batch)
        _validate_vectors(generated, expected=len(batch), dimensions=settings.embedding_dimensions)
        fresh.extend(generated)
    if getattr(embedder, "last_model", settings.embedding_model) != settings.embedding_model:
        raise ValueError("Embedding provider model does not match configured model")
    scores = [_cosine(saved, current) for saved, current in zip(stored_vectors, fresh, strict=True)]
    minimum = min(scores, default=0.0)
    if not scores or minimum < MIN_COMPATIBLE_COSINE:
        raise ValueError(f"Stored embeddings failed compatibility check; minimum cosine={minimum:.6f}")
    print(f"Embedding verification passed: vectors={len(scores)} minimum_cosine={minimum:.6f} model={settings.embedding_model}.")
    return len(scores), minimum


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Atomically update existing chunk embeddings")
    mode.add_argument("--rollback", action="store_true", help="Restore only chunk embeddings from --backup")
    mode.add_argument("--verify", action="store_true", help="Compare stored vectors with freshly generated provider vectors")
    parser.add_argument("--database", type=Path, default=get_settings().database_file)
    parser.add_argument("--backup", type=Path, help="Verified SQLite backup; required with --apply or --rollback")
    return parser.parse_args()


def main() -> None:
    args = _args()
    try:
        if args.rollback:
            if args.backup is None:
                raise ValueError("--rollback requires --backup")
            rollback_embeddings(args.database, args.backup)
            return
        if args.verify:
            asyncio.run(verify_database(args.database))
            return
        asyncio.run(run_migration(args.database, apply=args.apply, backup=args.backup))
    except Exception as error:  # noqa: BLE001 - CLI converts any migration failure to a concise abort.
        # Controlled exception text only; provider errors and message content are not printed.
        print(f"Migration aborted: {error}")
        raise SystemExit(1) from None


def rollback_embeddings(database: Path, backup: Path) -> None:
    _check_backup(database, backup)
    with closing(_open_readonly(backup)) as source:
        saved = source.execute("SELECT id, embedding FROM chunks ORDER BY id").fetchall()
        old_provenance = source.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (PROVENANCE_TABLE,),
        ).fetchone()
        provenance = source.execute(f"SELECT * FROM {PROVENANCE_TABLE} WHERE id=1").fetchone() if old_provenance else None
    connection = sqlite3.connect(database, timeout=30)
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = [tuple(row) for row in connection.execute("SELECT id, content FROM chunks ORDER BY id")]
        if current != _chunks(backup):
            raise ValueError("Backup chunk IDs/content differ from the current database")
        for chunk_id, embedding in saved:
            cursor = connection.execute("UPDATE chunks SET embedding=? WHERE id=?", (embedding, chunk_id))
            if cursor.rowcount != 1:
                raise ValueError("Could not restore a saved embedding")
        if provenance is None:
            connection.execute(f"DROP TABLE IF EXISTS {PROVENANCE_TABLE}")
        else:
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {PROVENANCE_TABLE} (id INTEGER PRIMARY KEY CHECK (id = 1), "
                "provider TEXT NOT NULL, model TEXT NOT NULL, dimensions INTEGER NOT NULL, "
                "vector_count INTEGER NOT NULL, updated_at TEXT NOT NULL)"
            )
            connection.execute(f"DELETE FROM {PROVENANCE_TABLE}")
            connection.execute(f"INSERT INTO {PROVENANCE_TABLE} VALUES(?,?,?,?,?,?)", tuple(provenance))
        connection.commit()
        print(f"Restored embeddings for {len(saved)} existing chunks; other records were preserved.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
