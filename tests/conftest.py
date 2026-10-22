import os

os.environ["DATABASE_PATH"] = "./data/test.sqlite3"
os.environ["ADMIN_API_KEY"] = "test-admin-key"
os.environ["ADMIN_USERNAME"] = "admin@example.com"
os.environ["ADMIN_PASSWORD"] = "test-password"
os.environ["ADMIN_SESSION_SECRET"] = "test-session-secret-with-enough-entropy"
os.environ["MOCK_LLM"] = "true"
os.environ["RAG_MIN_SCORE"] = "-1"

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.security import chat_rate_limiter


@pytest.fixture(autouse=True)
def clean_database(tmp_path):
    settings = get_settings()
    settings.database_path = tmp_path / "test.sqlite3"
    chat_rate_limiter._events.clear()
    path = settings.database_file
    with TestClient(app) as client:
        yield client
    path.unlink(missing_ok=True)
