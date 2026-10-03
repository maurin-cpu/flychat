"""Nutzungs-Telemetrie des MCP-Servers: ein PostHog-Event pro Tool-Aufruf.

Haengt als Context-Middleware des MCP-SDK vor jedem eingehenden JSON-RPC-
Aufruf und sieht so Methode, Tool-Name, HTTP-Header und Ergebnis, ohne dass
die zwoelf Tools etwas davon wissen. Gemeldet werden `initialize` (Start einer
Client-Verbindung) und `tools/call`; `tools/list` & Co. sind Rauschen.

Wer ist ein "User"? Der Server kennt keine Konten (offen, nur Rate-Limit).
distinct_id ist deshalb ein gesalzener Hash aus Client-IP + User-Agent —
pseudonym, nicht rueckrechenbar, aber stabil genug, um Clients zu zaehlen.
Grenze: Anfragen ueber den claude.ai-Connector kommen alle von Anthropic-
Servern und fallen auf wenige Fingerabdruecke zusammen → die Zahl ist eine
UNTERGRENZE. Echte Nutzerzahlen gaebe es erst mit einem Token pro Nutzer.

Tracking darf nie stoeren: jeder Fehler hier wird geschluckt, der Versand
laeuft im Hintergrund-Thread (mail_tracking.posthog_capture).
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any, Callable, Mapping, Optional

logger = logging.getLogger(__name__)

Sink = Callable[[str, str, dict], None]  # (distinct_id, event, properties)

EVENT_TOOL = "mcp_tool_called"
EVENT_INIT = "mcp_initialize"
UA_MAX = 120

# grobe Client-Klasse aus User-Agent / clientInfo.name — zum Gruppieren im
# Dashboard; der rohe (gekuerzte) User-Agent geht zur Nachschaerfung mit.
_KINDS = (
    ("claude-code", "claude_code"), ("claude code", "claude_code"),
    ("claude-desktop", "claude_desktop"), ("claude desktop", "claude_desktop"),
    ("claude-user", "claude_ai"), ("claude.ai", "claude_ai"), ("claude-ai", "claude_ai"), ("anthropic", "claude_ai"),
    ("chatgpt", "chatgpt"), ("openai", "chatgpt"),
    ("cursor", "cursor"), ("windsurf", "windsurf"), ("vscode", "vscode"), ("copilot", "copilot"),
    ("mcp-inspector", "inspector"), ("inspector", "inspector"),
    ("claude", "claude_other"),   # Fallback: irgendein Claude-Client, Spezialfaelle stehen oben
)


def client_kind(user_agent: str, client_name: str = "") -> str:
    hay = f"{client_name} {user_agent}".lower()
    for needle, kind in _KINDS:
        if needle in hay:
            return kind
    return "other" if hay.strip() else "unknown"


def client_fingerprint(ip: str, user_agent: str, salt: str) -> str:
    """Pseudonyme distinct_id: gesalzener Hash, nur die ersten 16 Hex-Zeichen."""
    raw = f"{salt}|{(ip or '').strip()}|{(user_agent or '').strip()}".encode("utf-8")
    return "mcp:" + hashlib.sha256(raw).hexdigest()[:16]


def _posthog_sink(distinct_id: str, event: str, properties: dict) -> None:
    # Lazy: zieht config/.env erst beim ersten Event; ohne POSTHOG_KEY no-op.
    from mail_tracking import posthog_capture
    posthog_capture(distinct_id, event, properties)


def _salt() -> str:
    # Eigener Salt, damit die Hashes nicht mit anderen Projekt-Salts kollidieren.
    return os.environ.get("MCP_CLIENT_SALT", "") or "wingcast-mcp"


class TelemetryMiddleware:
    """ServerMiddleware des MCP-SDK: `(ctx, call_next) -> result`."""

    def __init__(self, sink: Optional[Sink] = None, salt: Optional[str] = None):
        self.sink: Sink = sink or _posthog_sink
        self.salt = salt if salt is not None else _salt()

    async def __call__(self, ctx, call_next):
        t0 = time.monotonic()
        ok = True
        try:
            result = await call_next(ctx)
        except Exception:
            ok = False
            self._record(ctx, ok=False, duration_ms=(time.monotonic() - t0) * 1000)
            raise
        if ctx.method == "tools/call":
            ok = not _is_error(result)
        self._record(ctx, ok=ok, duration_ms=(time.monotonic() - t0) * 1000)
        return result

    # --------------------------------------------------------------
    def _record(self, ctx, *, ok: bool, duration_ms: float) -> None:
        try:
            method = getattr(ctx, "method", "")
            if method == "tools/call":
                event = EVENT_TOOL
            elif method == "initialize":
                event = EVENT_INIT
            else:
                return
            headers = _headers(ctx)
            ip = (headers.get("x-forwarded-for") or _client_host(ctx) or "").split(",")[0].strip()
            ua = (headers.get("user-agent") or "").strip()
            name, version = _client_info(ctx, method)
            props: dict[str, Any] = {
                "app": "mcp",
                "$lib": "wingcast-mcp",
                "$process_person_profile": False,   # anonyme Events, kein Personen-Profil
                "method": method,
                "ok": ok,
                "duration_ms": round(duration_ms, 1),
                "client_kind": client_kind(ua, name),
                "user_agent": ua[:UA_MAX],
                "protocol_version": getattr(ctx, "protocol_version", None),
            }
            if name:
                props["client_name"] = name
                props["client_version"] = version
            if method == "tools/call":
                params = ctx.params or {}
                props["tool"] = params.get("name") if isinstance(params, Mapping) else None
            did = client_fingerprint(ip, ua, self.salt)
            logger.info("mcp %s tool=%s ok=%s client=%s %s %.0fms", method, props.get("tool", "-"),
                        ok, props["client_kind"], did, duration_ms)
            self.sink(did, event, props)
        except Exception as e:  # noqa: BLE001 — Tracking darf nie stoeren
            logger.warning("mcp telemetry failed: %s", e)


def _headers(ctx) -> Mapping[str, str]:
    req = getattr(ctx, "request", None)
    h = getattr(req, "headers", None)
    return h if h is not None else {}


def _client_host(ctx) -> str:
    client = getattr(getattr(ctx, "request", None), "client", None)
    return getattr(client, "host", "") or ""


def _client_info(ctx, method: str) -> tuple[str, str]:
    """clientInfo (Name/Version des MCP-Clients): bei `initialize` aus den
    Rohparametern, sonst — falls die Session es kennt — aus client_params."""
    try:
        if method == "initialize" and isinstance(ctx.params, Mapping):
            ci = ctx.params.get("clientInfo") or {}
            return str(ci.get("name") or ""), str(ci.get("version") or "")
        cp = getattr(getattr(ctx, "session", None), "client_params", None)
        ci = getattr(cp, "client_info", None) or getattr(cp, "clientInfo", None)
        if ci is not None:
            return str(getattr(ci, "name", "") or ""), str(getattr(ci, "version", "") or "")
    except Exception:  # noqa: BLE001
        pass
    return "", ""


def _is_error(result) -> bool:
    if isinstance(result, Mapping):
        return result.get("isError") is True
    return getattr(result, "is_error", False) is True
