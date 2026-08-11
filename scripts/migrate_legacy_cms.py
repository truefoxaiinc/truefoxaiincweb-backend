import argparse
import json
from pathlib import Path

from app.database import migrate
from app.services.cms import COLLECTIONS, create, read_all


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the legacy Next.js CMS JSON into FastAPI storage.")
    parser.add_argument("path", nargs="?", default="../data/cms.json")
    args = parser.parse_args()
    source = Path(args.path).resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    migrate()
    existing = read_all()
    imported = 0
    for collection in COLLECTIONS:
        known = {item["id"] for item in existing[collection]}
        for item in payload.get(collection, []):
            if item.get("id") not in known:
                create(collection, item, "legacy-import")
                imported += 1
    print(f"Imported {imported} records from {source}")


if __name__ == "__main__":
    main()
