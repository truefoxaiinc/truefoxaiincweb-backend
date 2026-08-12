def test_health(clean_database):
    response = clean_database.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_admin_auth_and_rag_chat(clean_database):
    unauthorized = clean_database.get("/api/v1/knowledge")
    assert unauthorized.status_code == 401

    created = clean_database.post(
        "/api/v1/knowledge/text",
        headers={"X-Admin-Key": "test-admin-key"},
        json={"title": "Careers", "source": "/careers", "text": "Truefox career applications are submitted through the careers page application form."},
    )
    assert created.status_code == 201
    assert created.json()["chunk_count"] == 1

    answer = clean_database.post("/api/v1/chat", json={"message": "How do I apply for a career?"})
    assert answer.status_code == 200
    payload = answer.json()
    assert payload["conversation_id"]
    assert payload["citations"][0]["source"] == "/careers"

    history = clean_database.get(f"/api/v1/conversations/{payload['conversation_id']}")
    assert history.status_code == 200
    assert [item["role"] for item in history.json()] == ["user", "assistant"]


def test_upload_rejects_unsupported_type(clean_database):
    response = clean_database.post(
        "/api/v1/knowledge/upload",
        headers={"X-Admin-Key": "test-admin-key"},
        files={"file": ("image.png", b"not an image", "image/png")},
    )
    assert response.status_code == 422


def test_admin_crud_public_content_and_application(clean_database):
    login = clean_database.post("/api/v1/admin/login", json={"username": "admin@example.com", "password": "test-password"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = clean_database.post(
        "/api/v1/admin/data",
        headers=headers,
        json={"collection": "jobs", "item": {"id": "python-engineer", "status": "published", "title": "Python Engineer", "department": "AI", "location": "India", "summary": "Build FastAPI services."}},
    )
    assert created.status_code == 201
    assert clean_database.get("/api/v1/content").json()["jobs"][0]["title"] == "Python Engineer"

    application = clean_database.post(
        "/api/v1/applications",
        json={"jobId": "python-engineer", "name": "Test Candidate", "email": "candidate@example.com", "coverLetter": "I have substantial Python and FastAPI experience.", "consent": True},
    )
    assert application.status_code == 201
    data = clean_database.get("/api/v1/admin/data", headers=headers).json()
    assert data["applications"][0]["jobTitle"] == "Python Engineer"

    deleted = clean_database.request("DELETE", "/api/v1/admin/data", headers=headers, json={"collection": "jobs", "id": "python-engineer"})
    assert deleted.status_code == 200


def test_public_lead_validation_and_storage(clean_database):
    invalid = clean_database.post("/api/v1/leads", json={"name": "A", "email": "bad", "message": "short", "consent": False})
    assert invalid.status_code == 422
    valid = clean_database.post("/api/v1/leads", json={"name": "Ada Lovelace", "email": "ada@example.com", "message": "We need a private AI assistant for our support team.", "consent": True, "intent": "demo"})
    assert valid.status_code == 201
    assert valid.json()["reference"]


def test_website_parser_indexes_only_main_content():
    from app.services.website_sync import MainTextParser

    parser = MainTextParser()
    parser.feed("<html><head><title>Services | Truefox AI</title><script>secret()</script></head><body><nav>Repeated navigation</nav><main><h1>AI Services</h1><p>Computer vision and private AI assistants.</p></main><footer>Repeated footer</footer></body></html>")
    title, content = parser.result()
    assert title == "Services | Truefox AI"
    assert "AI Services" in content
    assert "private AI assistants" in content
    assert "Repeated navigation" not in content
    assert "Repeated footer" not in content
    assert "secret" not in content


def test_cors_allows_apex_www_and_admin_headers(clean_database):
    for origin in ("https://truefoxaiinc.com", "https://www.truefoxaiinc.com"):
        response = clean_database.options(
            "/api/v1/admin/login",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,authorization",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert "authorization" in response.headers["access-control-allow-headers"].lower()
