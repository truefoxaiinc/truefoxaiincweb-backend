import json
import re
from contextlib import closing
from typing import Any, Literal
from uuid import uuid4

from app.database import connect, transaction, utcnow

Collection = Literal["leads", "applications", "jobs", "posts", "records"]
COLLECTIONS: tuple[Collection, ...] = ("leads", "applications", "jobs", "posts", "records")


def clean(value: Any, maximum: int = 10_000) -> str:
    return str(value or "").strip().replace("<", "").replace(">", "")[:maximum]


def normalize(collection: Collection, source: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = {**(current or {}), **source}
    now = utcnow()
    common = {"id": clean(merged.get("id"), 100) or str(uuid4()), "createdAt": clean(merged.get("createdAt"), 50) or now, "updatedAt": now}
    fields: dict[Collection, tuple[tuple[str, int], ...]] = {
        "leads": (("status",20),("intent",30),("name",120),("email",180),("company",180),("phone",80),("interest",140),("timing",80),("message",5000),("notes",10000)),
        "applications": (("status",20),("jobId",100),("jobTitle",180),("name",120),("email",180),("phone",80),("location",180),("experience",80),("resumeUrl",1000),("coverLetter",10000),("notes",10000)),
        "jobs": (("status",20),("title",180),("department",120),("location",180),("employmentType",80),("summary",1000),("description",10000),("requirements",10000)),
        "posts": (("status",20),("title",220),("slug",180),("category",100),("excerpt",1000),("content",50000),("author",120),("publishedAt",50),("readTime",50)),
        "records": (("status",20),("group",100),("label",180),("value",10000),("description",1000)),
    }
    item = {**common, **{name: clean(merged.get(name), size) for name, size in fields[collection]}}
    defaults = {"leads":"new", "applications":"new", "jobs":"draft", "posts":"draft", "records":"published"}
    item["status"] = item["status"] or defaults[collection]
    if collection in {"jobs", "records"}:
        try: item["sortOrder"] = int(merged.get("sortOrder") or 0)
        except (TypeError, ValueError): item["sortOrder"] = 0
    if collection == "posts": item["slug"] = re.sub(r"(^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", item["slug"].lower()))
    return item


def read_all(public: bool = False) -> dict[str, list[dict[str, Any]]]:
    result = {name: [] for name in COLLECTIONS}
    query = "SELECT collection,payload FROM cms_items"
    params: tuple[Any, ...] = ()
    if public: query += " WHERE collection IN ('jobs','posts','records') AND status='published'"
    query += " ORDER BY updated_at DESC"
    with closing(connect()) as connection:
        for row in connection.execute(query, params).fetchall(): result[row["collection"]].append(json.loads(row["payload"]))
    return result


def create(collection: Collection, source: dict[str, Any], actor: str = "system") -> dict[str, Any]:
    item = normalize(collection, source)
    with transaction() as connection:
        connection.execute("INSERT INTO cms_items(collection,id,status,payload,created_at,updated_at) VALUES(?,?,?,?,?,?)", (collection,item["id"],item["status"],json.dumps(item),item["createdAt"],item["updatedAt"]))
        connection.execute("INSERT INTO audit_log(action,collection,item_id,actor,occurred_at) VALUES('create',?,?,?,?)", (collection,item["id"],actor,item["updatedAt"]))
    return item


def update(collection: Collection, identifier: str, source: dict[str, Any], actor: str) -> dict[str, Any] | None:
    with transaction() as connection:
        row = connection.execute("SELECT payload FROM cms_items WHERE collection=? AND id=?", (collection,identifier)).fetchone()
        if not row: return None
        item = normalize(collection, {**source, "id": identifier}, json.loads(row["payload"]))
        connection.execute("UPDATE cms_items SET status=?,payload=?,updated_at=? WHERE collection=? AND id=?", (item["status"],json.dumps(item),item["updatedAt"],collection,identifier))
        connection.execute("INSERT INTO audit_log(action,collection,item_id,actor,occurred_at) VALUES('update',?,?,?,?)", (collection,identifier,actor,item["updatedAt"]))
    return item


def remove(collection: Collection, identifier: str, actor: str) -> bool:
    with transaction() as connection:
        result = connection.execute("DELETE FROM cms_items WHERE collection=? AND id=?", (collection,identifier))
        if result.rowcount: connection.execute("INSERT INTO audit_log(action,collection,item_id,actor,occurred_at) VALUES('delete',?,?,?,?)", (collection,identifier,actor,utcnow()))
    return result.rowcount > 0
