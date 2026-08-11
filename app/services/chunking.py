import re


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ").replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, target_chars: int = 1800, overlap_chars: int = 250) -> list[str]:
    cleaned = normalize_text(text)
    if not cleaned:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > target_chars:
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        else:
            sentences = [paragraph]
        for sentence in sentences:
            candidate = f"{current}\n\n{sentence}".strip()
            if current and len(candidate) > target_chars:
                chunks.append(current)
                current = f"{current[-overlap_chars:]} {sentence}".strip()
            else:
                current = candidate
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if len(chunk) >= 30]
