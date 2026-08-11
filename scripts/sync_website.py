import argparse
import asyncio

from app.database import migrate
from app.services.website_sync import sync_website


async def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronize public company pages into the RAG knowledge base.")
    parser.add_argument("--base-url", default=None, help="Company site URL; localhost is allowed outside production.")
    args = parser.parse_args()
    migrate()
    documents = await sync_website(args.base_url)
    print(f"Indexed {len(documents)} company pages with {sum(int(item['chunk_count']) for item in documents)} chunks.")


if __name__ == "__main__":
    asyncio.run(main())
