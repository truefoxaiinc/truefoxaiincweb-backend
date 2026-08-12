import argparse
import asyncio
import json

from app.database import migrate
from app.services.intent import classify_intent
from app.services.retrieval import debug_retrieve


async def main(query: str) -> None:
    migrate()
    detected = classify_intent(query)
    result = await debug_retrieve(query, intent=detected.intent, entity=detected.entity)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspect RAG ranking signals for one query.")
    parser.add_argument("query")
    args = parser.parse_args()
    asyncio.run(main(args.query))
