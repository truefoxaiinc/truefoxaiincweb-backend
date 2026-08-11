from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.schemas import DocumentResponse, TextIngestRequest, UrlIngestRequest, WebsiteSyncRequest
from app.security import require_admin
from app.services.ingestion import ingest_file, ingest_text, ingest_url
from app.services.repository import delete_document, list_documents
from app.services.website_sync import sync_website

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"], dependencies=[Depends(require_admin)])


@router.get("", response_model=list[DocumentResponse])
def documents() -> list[dict[str, object]]:
    return list_documents()


@router.post("/text", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def add_text(request: TextIngestRequest) -> dict[str, object]:
    try:
        return await ingest_text(title=request.title, source=request.source, text=request.text, metadata=request.metadata)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload(file: Annotated[UploadFile, File()]) -> dict[str, object]:
    try:
        return await ingest_file(filename=file.filename or "document.txt", content=await file.read(), mime_type=file.content_type or "application/octet-stream")
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/url", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def add_url(request: UrlIngestRequest) -> dict[str, object]:
    try:
        return await ingest_url(url=str(request.url), title=request.title)
    except (ValueError, httpx.HTTPError, OSError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/sync-website", response_model=list[DocumentResponse])
async def synchronize_website(request: WebsiteSyncRequest) -> list[dict[str, object]]:
    try:
        return await sync_website(str(request.base_url) if request.base_url else None)
    except (ValueError, httpx.HTTPError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_document(document_id: str) -> None:
    if not delete_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
