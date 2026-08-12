import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    content: str
    metadata: dict[str, str]


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ").replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def chunk_text(
    text: str,
    *,
    metadata: dict[str, str] | None = None,
    target_chars: int = 2200,
    max_chars: int = 3000,
) -> list[Chunk]:
    """Split markdown-like content on semantic sections without cutting sentences."""
    cleaned = normalize_text(text)
    if not cleaned:
        return []
    base = dict(metadata or {})
    title, sections = _sections(cleaned)
    entity = base.get("entity_name", title if base.get("document_type") in {"product", "service"} else "")
    chunks: list[Chunk] = []
    for heading, body in sections:
        prefix = "\n\n".join(value for value in (f"# {title}" if title else "", f"## {heading}" if heading else "") if value)
        units = [item.strip() for item in re.split(r"\n\s*\n|(?<=[.!?])\s+(?=[A-Z])", body) if item.strip()]
        current = prefix
        for unit in units:
            candidate = f"{current}\n\n{unit}".strip()
            if len(candidate) > max_chars and len(current) > len(prefix) + 40:
                chunks.append(Chunk(current, base | {"heading": heading, "entity_name": entity}))
                current = f"{prefix}\n\n{unit}".strip()
            else:
                current = candidate
            if len(current) >= target_chars:
                chunks.append(Chunk(current, base | {"heading": heading, "entity_name": entity}))
                current = prefix
        if len(current) > len(prefix) + 20:
            chunks.append(Chunk(current, base | {"heading": heading, "entity_name": entity}))
    return _merge_tiny(chunks, max_chars)


def _sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    title = ""
    heading = ""
    body: list[str] = []
    sections: list[tuple[str, str]] = []
    for line in text.splitlines():
        match = re.match(r"^(#{1,4})\s+(.+)$", line.strip())
        if match:
            if body:
                sections.append((heading, "\n".join(body).strip()))
                body = []
            if len(match.group(1)) == 1 and not title:
                title = match.group(2).strip()
            else:
                heading = match.group(2).strip()
        else:
            body.append(line)
    if body:
        sections.append((heading, "\n".join(body).strip()))
    return title, [(head, value) for head, value in sections if value]


def _merge_tiny(chunks: list[Chunk], max_chars: int) -> list[Chunk]:
    merged: list[Chunk] = []
    for chunk in chunks:
        same_heading = merged and merged[-1].metadata.get("heading") == chunk.metadata.get("heading")
        if same_heading and len(chunk.content) < 220 and len(merged[-1].content) + len(chunk.content) < max_chars:
            previous = merged.pop()
            merged.append(Chunk(f"{previous.content}\n\n{chunk.content}", previous.metadata))
        elif len(chunk.content) >= 40:
            merged.append(chunk)
    return merged
