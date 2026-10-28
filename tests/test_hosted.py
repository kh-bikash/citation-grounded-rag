"""Hosted RAG boundaries, independent of a live database or model."""

from __future__ import annotations

from fastapi.testclient import TestClient

import app as hosted_app
from citation_grounded_rag import hosted
from citation_grounded_rag.engine import Passage


def test_authenticated_action_and_origin(monkeypatch):
    def auth(method, path, *, token="", body=None):
        if path == "user" and token == "access":
            return {"id": "user-1", "email": "user@example.com"}
        if path == "token?grant_type=password":
            return {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 3600,
            }
        raise AssertionError((method, path))

    monkeypatch.setattr(hosted_app, "_auth_request", auth)
    monkeypatch.setattr(
        hosted_app,
        "run_action",
        lambda action, values, token: {"action": action, "token": token},
    )
    client = TestClient(hosted_app.app, base_url="https://rag.example.com")
    payload = {"action": "sources", "values": {}}
    assert (
        client.post(
            "/api/action", json=payload, headers={"Origin": "https://rag.example.com"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login",
            json={"email": "user@example.com", "password": "password123"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    response = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "password123"},
        headers={"Origin": "https://rag.example.com"},
    )
    assert response.status_code == 200
    assert client.post(
        "/api/action", json=payload, headers={"Origin": "https://rag.example.com"}
    ).json() == {"result": {"action": "sources", "token": "access"}}


def test_hosted_chunks_and_grounding(monkeypatch):
    assert hosted._chunks("x" * 2100) and len(hosted._chunks("x" * 2100)) == 3
    calls = []
    monkeypatch.setattr(
        hosted,
        "_rpc",
        lambda name, values, token: calls.append((name, values, token)) or 2,
    )
    assert hosted.run_action(
        "ingest-text", {"source": "notes", "text": "a" * 1100}, "user-token"
    ) == {"chunks": 2}
    assert calls[0][0] == "rag_replace_source" and calls[0][2] == "user-token"
    passage = Passage(1, "notes", "Only supported fact", 0.8)

    class FakeLLM:
        def complete(self, messages):
            return '{"answer":"Unsupported", "evidence":[{"id":1,"quote":"invented"}],"confidence":0.99}'

    monkeypatch.setattr(hosted.OpenAICompatibleLLM, "from_env", lambda: FakeLLM())
    answer = hosted._answer("Question", [passage])
    assert not answer.grounded and answer.citations == ()
