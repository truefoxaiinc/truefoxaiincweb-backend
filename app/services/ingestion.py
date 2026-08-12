import hashlib
import io
import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pypdf import PdfReader

from app.services.chunking import chunk_text
from app.services.embeddings import EmbeddingService
from app.services.repository import save_document


def extract_text(content: bytes, mime_type: str, filename: str) -> str:
    if mime_type == "application/pdf" or filename.lower().endswith(".pdf"):
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
    if mime_type.startswith("text/") or Path(filename).suffix.lower() in {".txt", ".md", ".csv", ".html"}:
        return content.decode("utf-8", errors="replace")
    raise ValueError("Unsupported file type. Upload PDF, TXT, Markdown, CSV, or HTML.")


async def ingest_text(*, title: str, source: str, text: str, mime_type: str = "text/plain", metadata: dict[str, str] | None = None) -> dict[str, object]:
    cleaned = text.strip()
    if len(cleaned) < 20:
        raise ValueError("Document text is too short.")
    document_metadata = _infer_metadata(title, source) | (metadata or {})
    parts = chunk_text(cleaned, metadata=document_metadata | {"source": source.strip()})
    embeddings = await EmbeddingService().embed_many([part.content for part in parts])
    checksum = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
    chunks = [(part.content, embedding, part.metadata) for part, embedding in zip(parts, embeddings, strict=True)]
    return save_document(title=title.strip(), source=source.strip(), mime_type=mime_type, checksum=checksum, metadata=document_metadata, chunks=chunks)


def _infer_metadata(title: str, source: str) -> dict[str, str]:
    label = f"{title} {source}".lower()
    if "attention minder" in label:
        return {"document_type": "product", "category": "products", "entity_name": "Attention Minder"}
    mappings = {
        "career": ("career", "careers"), "job": ("career", "careers"),
        "contact": ("contact", "contact"), "demo": ("demo", "contact"),
        "product": ("product", "products"), "service": ("service", "services"),
    }
    for keyword, (document_type, category) in mappings.items():
        if keyword in label:
            return {"document_type": document_type, "category": category}
    return {"document_type": "company", "category": "company"}


async def ingest_file(*, filename: str, content: bytes, mime_type: str) -> dict[str, object]:
    if len(content) > 10 * 1024 * 1024:
        raise ValueError("File exceeds the 10 MB limit.")
    text = extract_text(content, mime_type, filename)
    return await ingest_text(title=Path(filename).stem, source=f"upload:{Path(filename).name}", text=text, mime_type=mime_type)


def _assert_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public HTTP(S) URLs are supported.")
    for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM):
        address = ipaddress.ip_address(item[4][0])
        if not address.is_global:
            raise ValueError("Private or local network URLs are not allowed.")


async def ingest_url(*, url: str, title: str | None = None) -> dict[str, object]:
    _assert_public_url(url)
    async with httpx.AsyncClient(follow_redirects=False, timeout=15) as client:
        response = await client.get(url, headers={"User-Agent": "TruefoxKnowledgeBot/1.0"})
        response.raise_for_status()
        if len(response.content) > 5 * 1024 * 1024:
            raise ValueError("Remote document exceeds the 5 MB limit.")
        text = extract_text(response.content, response.headers.get("content-type", "text/plain").split(";")[0], url)
    return await ingest_text(title=title or url, source=url, text=text, mime_type=response.headers.get("content-type", "text/plain"))
