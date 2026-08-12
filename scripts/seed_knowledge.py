import argparse
import asyncio
from pathlib import Path

from app.database import migrate
from app.services.ingestion import ingest_text
from app.services.repository import reset_knowledge


def parse_document(path: Path) -> tuple[str, dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    metadata: dict[str, str] = {"path": path.as_posix()}
    if text.startswith("---\n"):
        header, text = text[4:].split("\n---\n", 1)
        for line in header.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip()
    return text.strip(), metadata


async def seed(*, reset: bool = False) -> None:
    migrate()
    if reset:
        reset_knowledge()
    root = Path(__file__).resolve().parents[1] / "knowledge"
    for path in sorted(root.rglob("*.md")):
        text, metadata = parse_document(path)
        relative = path.relative_to(root).as_posix()
        document = await ingest_text(
            title=next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), path.stem.replace("-", " ").title()),
            source=metadata.get("source", f"knowledge/{relative}"),
            text=text,
            mime_type="text/markdown",
            metadata=metadata | {"path": relative},
        )
        print(f"Indexed {document['title']} ({document['chunk_count']} chunks)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Index approved Truefox AI knowledge documents.")
    parser.add_argument("--reset", action="store_true", help="Delete existing knowledge documents and chunks first.")
    args = parser.parse_args()
    asyncio.run(seed(reset=args.reset))


if __name__ == "__main__":
    main()
