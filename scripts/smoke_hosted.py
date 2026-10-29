"""Temporary two-user Supabase integration test; deletes both users afterward."""

from __future__ import annotations

import os
import secrets

import httpx


def main() -> None:
    base = os.environ["SUPABASE_URL"].rstrip("/")
    admin_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    public_key = (
        os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ["SUPABASE_ANON_KEY"]
    )
    hosted_url = os.environ.get("HOSTED_URL", "").rstrip("/")
    admin_headers = {"apikey": admin_key, "Authorization": f"Bearer {admin_key}"}
    users: list[str] = []
    with httpx.Client(timeout=15.0) as client:
        try:
            tokens = []
            for _ in range(2):
                email = f"agent-smoke-{secrets.token_hex(8)}@example.com"
                password = secrets.token_urlsafe(24)
                response = client.post(
                    f"{base}/auth/v1/admin/users",
                    headers=admin_headers,
                    json={"email": email, "password": password, "email_confirm": True},
                )
                response.raise_for_status()
                users.append(response.json()["id"])
                session = client.post(
                    f"{base}/auth/v1/token?grant_type=password",
                    headers={"apikey": public_key},
                    json={"email": email, "password": password},
                )
                session.raise_for_status()
                tokens.append(session.json()["access_token"])

            def rpc(token: str, name: str, body: dict):
                response = client.post(
                    f"{base}/rest/v1/rpc/{name}",
                    headers={"apikey": public_key, "Authorization": f"Bearer {token}"},
                    json=body,
                )
                response.raise_for_status()
                return response.json()

            source = f"smoke-{secrets.token_hex(6)}"
            assert (
                rpc(
                    tokens[0],
                    "rag_replace_source",
                    {"p_source": source, "p_chunks": ["Private launch notes"]},
                )
                == 1
            )
            assert len(rpc(tokens[0], "rag_search", {"p_query": "launch notes"})) == 1
            assert rpc(tokens[1], "rag_search", {"p_query": "launch notes"}) == []
            assert rpc(tokens[1], "rag_delete_source", {"p_source": source}) == 0
            assert rpc(tokens[0], "rag_delete_source", {"p_source": source}) == 1
            if hosted_url:
                with httpx.Client(timeout=20.0, follow_redirects=False) as web:
                    assert web.get(f"{hosted_url}/api/session").status_code == 401
                    login = web.post(
                        f"{hosted_url}/auth/login",
                        headers={"Origin": hosted_url},
                        json={"email": email, "password": password},
                    )
                    # The loop's final credentials belong to the second user.
                    login.raise_for_status()
                    assert web.get(f"{hosted_url}/api/session").status_code == 200
                    payload = {
                        "action": "ingest-text",
                        "values": {"source": source, "text": "Private hosted document"},
                    }
                    ingest = web.post(
                        f"{hosted_url}/api/action",
                        headers={"Origin": hosted_url},
                        json=payload,
                    )
                    ingest.raise_for_status()
                    assert ingest.json()["result"]["chunks"] == 1
                    search = web.post(
                        f"{hosted_url}/api/action",
                        headers={"Origin": hosted_url},
                        json={
                            "action": "search",
                            "values": {"query": "hosted document"},
                        },
                    )
                    search.raise_for_status()
                    assert len(search.json()["result"]) == 1
                    answer = web.post(
                        f"{hosted_url}/api/action",
                        headers={"Origin": hosted_url},
                        json={
                            "action": "ask",
                            "values": {"query": "What is the private hosted document?"},
                        },
                    )
                    answer.raise_for_status()
                    assert answer.json()["result"]["grounded"] is True
            print("Two-user RLS and RAG operations passed")
        finally:
            for user_id in users:
                response = client.delete(
                    f"{base}/auth/v1/admin/users/{user_id}", headers=admin_headers
                )
                response.raise_for_status()


if __name__ == "__main__":
    main()
