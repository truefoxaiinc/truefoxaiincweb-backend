import json
from contextlib import closing
from uuid import uuid4

from app.database import connect, decode_json, transaction, utcnow


def save_document(*, title: str, source: str, mime_type: str, checksum: str, metadata: dict[str, str], chunks: list[tuple[str, list[float]]]) -> dict[str, object]:
    document_id = str(uuid4())
    now = utcnow()
    with transaction() as connection:
        existing = connection.execute("SELECT id FROM documents WHERE checksum = ?", (checksum,)).fetchone()
        if existing:
            connection.execute("DELETE FROM documents WHERE id = ?", (existing["id"],))
        connection.execute(
            "INSERT INTO documents(id,title,source,mime_type,checksum,metadata,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (document_id, title, source, mime_type, checksum, json.dumps(metadata), now, now),
        )
        for position, (content, embedding) in enumerate(chunks):
            connection.execute(
                "INSERT INTO chunks(id,document_id,position,content,embedding,token_estimate,created_at) VALUES(?,?,?,?,?,?,?)",
                (str(uuid4()), document_id, position, content, json.dumps(embedding), max(1, len(content) // 4), now),
            )
    return {"id": document_id, "title": title, "source": source, "mime_type": mime_type, "chunk_count": len(chunks), "created_at": now}


def list_documents() -> list[dict[str, object]]:
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT d.id,d.title,d.source,d.mime_type,d.created_at,COUNT(c.id) chunk_count FROM documents d LEFT JOIN chunks c ON c.document_id=d.id GROUP BY d.id ORDER BY d.created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def delete_document(document_id: str) -> bool:
    with transaction() as connection:
        result = connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    return result.rowcount > 0


def all_chunks() -> list[dict[str, object]]:
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT c.id,c.document_id,c.content,c.embedding,d.title,d.source FROM chunks c JOIN documents d ON d.id=c.document_id"
        ).fetchall()
    return [{**dict(row), "embedding": decode_json(row["embedding"], [])} for row in rows]


def ensure_conversation(conversation_id: str | None) -> str:
    identifier = conversation_id or str(uuid4())
    now = utcnow()
    with transaction() as connection:
        connection.execute("INSERT OR IGNORE INTO conversations(id,created_at,updated_at) VALUES(?,?,?)", (identifier, now, now))
        connection.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, identifier))
    return identifier


def save_message(conversation_id: str, role: str, content: str, citations: list[dict[str, object]] | None = None) -> str:
    identifier = str(uuid4())
    with transaction() as connection:
        connection.execute(
            "INSERT INTO messages(id,conversation_id,role,content,citations,created_at) VALUES(?,?,?,?,?,?)",
            (identifier, conversation_id, role, content, json.dumps(citations or []), utcnow()),
        )
    return identifier


def recent_messages(conversation_id: str, limit: int = 8) -> list[dict[str, str]]:
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT role,content FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT ?", (conversation_id, limit)
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def conversation_messages(conversation_id: str) -> list[dict[str, object]]:
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT id,role,content,citations,created_at FROM messages WHERE conversation_id=? ORDER BY created_at", (conversation_id,)
        ).fetchall()
    return [{**dict(row), "citations": decode_json(row["citations"], [])} for row in rows]
