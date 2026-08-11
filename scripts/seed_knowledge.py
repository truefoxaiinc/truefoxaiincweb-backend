import asyncio
from pathlib import Path

from app.database import migrate
from app.services.ingestion import ingest_text


async def main() -> None:
    migrate()
    root = Path(__file__).resolve().parents[1] / "knowledge"
    for path in root.glob("*.md"):
        document = await ingest_text(title=path.stem.replace("-", " ").title(), source=f"knowledge/{path.name}", text=path.read_text(encoding="utf-8"), mime_type="text/markdown")
        print(f"Indexed {document['title']} ({document['chunk_count']} chunks)")


if __name__ == "__main__":
    asyncio.run(main())
