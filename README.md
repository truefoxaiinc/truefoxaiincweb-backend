# Truefox AI private RAG backend

Independent FastAPI service for the website chatbot. It provides document ingestion, chunking, embeddings, cosine retrieval, cited LLM answers, persistent conversations, SSE streaming, API-key-protected knowledge administration, rate limiting, health checks, tests, and Docker support.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
python -m scripts.seed_knowledge --reset
python -m scripts.sync_website --base-url http://localhost:3000
python -m scripts.migrate_legacy_cms ../data/cms.json
uvicorn app.main:app --reload --port 8000
```

Set `OPENAI_API_KEY` in `.env`. Without it, local deterministic embeddings remain available for development, while company-specific chat requests return a safe provider-unavailable message instead of exposing raw knowledge. Set a strong random `ADMIN_API_KEY` before exposing the service.

The frontend proxies requests through `/api/chat`, using `AI_BACKEND_URL` on the Next.js server. API docs are available at `http://127.0.0.1:8000/docs` in non-production environments.

## Knowledge management

Send `X-Admin-Key` with all `/api/v1/knowledge` requests. Supported sources are manual text, PDF/TXT/Markdown/CSV/HTML upload, and public HTTP(S) URLs. URL ingestion rejects private/local addresses and redirects to reduce SSRF risk.

Run `python -m scripts.sync_website` after approved website content changes. In production, `POST /api/v1/knowledge/sync-website` refreshes the full configured company site and is protected by `X-Admin-Key`.

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/knowledge/text -H "X-Admin-Key: your-key" -H "Content-Type: application/json" -d '{"title":"FAQ","source":"/faq","text":"Approved company information..."}'
```

## Verification

```powershell
pytest
ruff check app tests scripts
```

## Retrieval debugging

Development code can call `await app.services.retrieval.debug_retrieve("What is Attention Minder?", intent=Intent.PRODUCT_DETAIL, entity="Attention Minder")` to inspect semantic, lexical, title, entity, intent, penalty, final score, and acceptance reason. This is intentionally not exposed as a public production route.
