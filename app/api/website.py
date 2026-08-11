import hmac
import re
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.admin_auth import create_token, require_session
from app.config import get_settings
from app.security import enforce_chat_rate_limit
from app.services.cms import create, read_all, remove, update

router = APIRouter(prefix="/api/v1", tags=["website"])
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class Login(BaseModel):
    username: str = Field(max_length=180)
    password: str = Field(max_length=500)


class CmsMutation(BaseModel):
    collection: Literal["leads", "applications", "jobs", "posts", "records"]
    item: dict[str, Any] = Field(default_factory=dict)
    id: str = ""


class PublicForm(BaseModel):
    model_config = {"extra": "allow"}
    name: str = ""
    email: str = ""
    website: str = ""
    consent: bool = False


@router.post("/admin/login")
def login(body: Login) -> dict[str, str]:
    settings = get_settings()
    if not settings.admin_password or not hmac.compare_digest(body.username, settings.admin_username) or not hmac.compare_digest(body.password, settings.admin_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"access_token": create_token(body.username), "token_type": "bearer"}


@router.get("/admin/data")
def admin_data(_: str = Depends(require_session)) -> dict[str, list[dict[str, Any]]]: return read_all()


@router.post("/admin/data", status_code=201)
def admin_create(body: CmsMutation, actor: str = Depends(require_session)) -> dict[str, Any]: return {"item": create(body.collection, body.item, actor)}


@router.patch("/admin/data")
def admin_update(body: CmsMutation, actor: str = Depends(require_session)) -> dict[str, Any]:
    item = update(body.collection, body.id, body.item, actor)
    if not item: raise HTTPException(status_code=404, detail="Not found")
    return {"item": item}


@router.delete("/admin/data")
def admin_delete(body: CmsMutation, actor: str = Depends(require_session)) -> dict[str, bool]:
    if not remove(body.collection, body.id, actor): raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


@router.get("/content")
def public_content() -> dict[str, list[dict[str, Any]]]: return read_all(public=True)


@router.post("/leads", status_code=201, dependencies=[Depends(enforce_chat_rate_limit)])
async def submit_lead(body: PublicForm, request: Request) -> dict[str, Any]:
    data = body.model_dump() | body.model_extra
    if data.get("website"): return {"ok": True}
    name, email, message = str(data.get("name", "")).strip(), str(data.get("email", "")).strip().lower(), str(data.get("message", "")).strip()
    if len(name) < 2 or not EMAIL.match(email) or len(message) < 15 or not body.consent: raise HTTPException(status_code=422, detail="Invalid form data")
    item = create("leads", {**data, "name": name, "email": email, "message": message, "status": "new", "notes": ""}, request.client.host if request.client else "public")
    webhook = get_settings().leads_webhook_url
    if webhook:
        try:
            async with httpx.AsyncClient(timeout=8) as client: await client.post(webhook, json=data)
        except httpx.HTTPError: pass
    return {"ok": True, "reference": item["id"]}


@router.post("/applications", status_code=201, dependencies=[Depends(enforce_chat_rate_limit)])
def submit_application(body: PublicForm, request: Request) -> dict[str, Any]:
    data = body.model_dump() | body.model_extra
    if data.get("website"): return {"ok": True}
    jobs = read_all(public=True)["jobs"]
    job = next((item for item in jobs if item["id"] == data.get("jobId")), None)
    cover = str(data.get("coverLetter", "")).strip()
    if len(body.name.strip()) < 2 or not EMAIL.match(body.email.strip()) or not job or len(cover) < 20 or not body.consent: raise HTTPException(status_code=422, detail="Invalid application")
    item = create("applications", {**data, "jobTitle": job["title"], "status": "new", "notes": ""}, request.client.host if request.client else "public")
    return {"ok": True, "reference": item["id"]}
