import json
import re
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from citation_grounded_rag.__main__ import WEB_ACTIONS, execute
from citation_grounded_rag.web import make_server


def test_browser_ingests_and_searches_over_http(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WEB_TOKEN", "local-test-access-token")
    db = str(tmp_path / "knowledge.sqlite3")
    server = make_server(
        "Citation Grounded RAG",
        WEB_ACTIONS,
        lambda action, values: execute(action, values, db),
        port=0,
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/") as response:
            page = response.read().decode()
        assert "Citation Grounded RAG" in page
        csrf = re.search(r'const csrf="([^"]+)"', page).group(1)

        def post(action, values):
            request = Request(
                base + "/api",
                data=json.dumps({"action": action, "values": values}).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-CSRF-Token": csrf,
                    "X-Access-Token": "local-test-access-token",
                },
                method="POST",
            )
            with urlopen(request) as response:
                return json.load(response)["result"]

        assert post(
            "ingest-text", {"source": "policy", "text": "Refunds in 30 days"}
        ) == {"chunks": 1}
        assert post("search", {"query": "Refunds"})[0]["source"] == "policy"
        unauthorized = Request(
            base + "/api",
            data=json.dumps({"action": "sources", "values": {}}).encode(),
            headers={"Content-Type": "application/json", "X-CSRF-Token": csrf},
            method="POST",
        )
        with pytest.raises(HTTPError) as error:
            urlopen(unauthorized)
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_remote_binding_requires_access_token(monkeypatch):
    monkeypatch.delenv("AGENT_WEB_TOKEN", raising=False)
    with pytest.raises(ValueError, match="AGENT_WEB_TOKEN"):
        make_server("test", {"noop": []}, lambda *_: None, host="0.0.0.0", port=0)
    monkeypatch.setenv("AGENT_WEB_TOKEN", "replace-with-a-long-random-token")
    with pytest.raises(ValueError, match="non-example"):
        make_server("test", {"noop": []}, lambda *_: None, host="0.0.0.0", port=0)
