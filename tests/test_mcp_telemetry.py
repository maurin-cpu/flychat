"""Nutzungs-Telemetrie des MCP-Servers: ein Event je Tool-Aufruf, pseudonyme Client-Kennung."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from mcp_server.server import build_http_app, build_server
from mcp_server.telemetry import client_fingerprint, client_kind
from tests.test_mcp_store import write_export

HDR = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


@pytest.fixture
def harness(tmp_path):
    write_export(str(tmp_path))
    events: list[tuple[str, str, dict]] = []
    server = build_server(str(tmp_path), telemetry_sink=lambda did, ev, props: events.append((did, ev, props)))
    app = build_http_app(server, allowed_hosts=["testserver"], rate_per_min=100)
    with TestClient(app) as c:
        yield c, events


def _call(c, tool, args=None, **extra_headers):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args or {}}}
    return c.post("/mcp", json=body, headers={**HDR, **extra_headers})


def test_tool_call_emits_one_event_with_tool_and_pseudonymous_client(harness):
    c, events = harness
    r = _call(c, "data_status", **{"x-forwarded-for": "203.0.113.7, 10.0.0.1", "user-agent": "Claude-User/1.0"})
    assert r.status_code == 200
    assert len(events) == 1
    did, ev, props = events[0]
    assert ev == "mcp_tool_called"
    assert props["tool"] == "data_status"
    assert props["ok"] is True
    assert props["client_kind"] == "claude_ai"
    assert props["app"] == "mcp" and props["$process_person_profile"] is False
    assert props["duration_ms"] >= 0
    # Kennung ist ein Hash — IP erscheint nirgends im Event
    assert did.startswith("mcp:") and len(did) == 4 + 16
    assert "203.0.113.7" not in did and "203.0.113.7" not in str(props)


def test_same_client_same_id_other_client_other_id(harness):
    c, events = harness
    a = {"x-forwarded-for": "203.0.113.7", "user-agent": "Claude-User/1.0"}
    _call(c, "data_status", **a)
    _call(c, "list_regions", **a)
    _call(c, "data_status", **{"x-forwarded-for": "198.51.100.9", "user-agent": "Claude-User/1.0"})
    ids = [e[0] for e in events]
    assert ids[0] == ids[1] != ids[2]
    assert [e[2]["tool"] for e in events] == ["data_status", "list_regions", "data_status"]


def test_tools_list_is_not_tracked(harness):
    c, events = harness
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=HDR)
    assert r.status_code == 200
    assert events == []


def test_unknown_tool_is_tracked_as_not_ok(harness):
    c, events = harness
    _call(c, "gibt_es_nicht")
    assert len(events) == 1
    assert events[0][2]["tool"] == "gibt_es_nicht"
    assert events[0][2]["ok"] is False


def test_initialize_is_tracked_with_client_info(harness):
    c, events = harness
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "claude-ai", "version": "1.2"}}}
    r = c.post("/mcp", json=body, headers=HDR)
    assert r.status_code == 200
    assert len(events) == 1
    did, ev, props = events[0]
    assert ev == "mcp_initialize"
    assert props["client_name"] == "claude-ai" and props["client_version"] == "1.2"
    assert props["client_kind"] == "claude_ai"


def test_sink_failure_never_breaks_the_tool(tmp_path):
    write_export(str(tmp_path))

    def boom(*_):
        raise RuntimeError("posthog down")
    server = build_server(str(tmp_path), telemetry_sink=boom)
    app = build_http_app(server, allowed_hosts=["testserver"], rate_per_min=100)
    with TestClient(app) as c:
        r = _call(c, "data_status")
    assert r.status_code == 200
    assert "Prognose-Stand" in r.text


def test_telemetry_can_be_disabled(tmp_path):
    write_export(str(tmp_path))
    server = build_server(str(tmp_path), telemetry_sink=False)
    assert not any(type(m).__name__ == "TelemetryMiddleware" for m in server.middleware)


def test_fingerprint_and_kind_helpers():
    a = client_fingerprint("1.2.3.4", "UA", "salt")
    assert a == client_fingerprint("1.2.3.4", "UA", "salt")
    assert a != client_fingerprint("1.2.3.4", "UA", "other-salt")
    assert a != client_fingerprint("1.2.3.5", "UA", "salt")
    assert client_kind("python-httpx/0.28", "") == "other"
    assert client_kind("", "") == "unknown"
    assert client_kind("node", "Claude Code") == "claude_code"
    assert client_kind("Mozilla/5.0 Cursor/1.0", "") == "cursor"
