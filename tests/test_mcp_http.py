"""HTTP-Betrieb des MCP-Servers: Health, Rate-Limit, Host-Pruefung; Scheduler-Hook."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from mcp_server.server import build_http_app, build_server
from tests.test_mcp_store import write_export


@pytest.fixture
def client(tmp_path):
    write_export(str(tmp_path))
    server = build_server(str(tmp_path))
    app = build_http_app(server, allowed_hosts=["app.wingcast.ch", "testserver"], rate_per_min=3)
    # Context-Manager: startet den Lifespan (Session-Manager des MCP-Transports)
    with TestClient(app) as c:
        yield c


def test_healthz_reports_build(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert "build=build-20260917-0600" in r.text


def test_rate_limit_per_ip(client):
    hdr = {"x-forwarded-for": "203.0.113.5"}
    codes = [client.post("/mcp", json={}, headers=hdr).status_code for _ in range(4)]
    assert codes[3] == 429
    assert all(c != 429 for c in codes[:3])
    # andere IP hat eigenes Budget
    assert client.post("/mcp", json={}, headers={"x-forwarded-for": "203.0.113.6"}).status_code != 429
    # healthz ist vom Limit ausgenommen
    assert client.get("/healthz", headers=hdr).status_code == 200


def test_unknown_host_rejected(tmp_path):
    write_export(str(tmp_path))
    app = build_http_app(build_server(str(tmp_path)), allowed_hosts=["app.wingcast.ch"], rate_per_min=100)
    with TestClient(app, base_url="http://evil.example") as c:
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                   headers={"accept": "application/json, text/event-stream", "content-type": "application/json"})
    assert r.status_code in (421, 400, 403)


def test_scheduler_hook_is_failure_tolerant(monkeypatch):
    import scheduler
    import mcp_server.export as ex

    calls = []
    monkeypatch.setattr(ex, "build_export", lambda engine, out_root=None: calls.append(engine) or "build-x")
    assert scheduler._run_mcp_export("ENGINE") is True
    assert calls == ["ENGINE"]

    def boom(engine, out_root=None):
        raise RuntimeError("kaputt")
    monkeypatch.setattr(ex, "build_export", boom)
    assert scheduler._run_mcp_export("ENGINE") is False
