"""
Legt in PostHog das Dashboard „MCP-Server Nutzung" an (oder druckt die
Definition): Tool-Aufrufe pro Tag, verschiedene Clients pro Tag/Woche,
Aufrufe je Tool, Clients nach Art, Fehlerquote, Antwortzeit.

Datenquelle sind die Events `mcp_tool_called` / `mcp_initialize`, die der
MCP-Server je Aufruf meldet (mcp_server/telemetry.py). „Clients" = pseudonyme
distinct_id (Hash aus IP + User-Agent) — ueber den claude.ai-Connector kommen
alle Nutzer von Anthropic-Servern und fallen zusammen: Untergrenze, kein
Nutzerzaehler. Steht so auch als Text oben im Dashboard.

Braucht einen PERSOENLICHEN API-Key (PostHog → Settings → Personal API keys,
Scopes dashboard:write + insight:write) und die Projekt-ID (Zahl in der URL
https://eu.posthog.com/project/<ID>/…). Der phc_-Projekt-Key reicht nicht.

    python scripts/posthog_mcp_dashboard.py --dry-run
    POSTHOG_PERSONAL_API_KEY=phx_… POSTHOG_PROJECT_ID=12345 python scripts/posthog_mcp_dashboard.py

Idempotent: findet es ein Dashboard gleichen Namens, legt es kein zweites an.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

DASHBOARD_NAME = "MCP-Server Nutzung"
DESCRIPTION = ("Nutzung des wingcast MCP-Servers (app.wingcast.ch/mcp). Quelle: Events "
               "mcp_tool_called / mcp_initialize. 'Clients' sind pseudonyme Fingerabdruecke "
               "(IP + User-Agent); ueber den claude.ai-Connector fallen viele Nutzer auf wenige "
               "Fingerabdruecke zusammen -> UNTERGRENZE, kein exakter Nutzerzaehler.")

MCP_FILTER = {"type": "AND", "values": [{"type": "AND", "values": [
    {"key": "app", "type": "event", "value": ["mcp"], "operator": "exact"}]}]}


def trends(name, series, *, interval="day", display="ActionsLineGraph", breakdown=None, days=30, formula=None):
    q = {"kind": "TrendsQuery", "series": series, "interval": interval,
         "dateRange": {"date_from": f"-{days}d"}, "properties": MCP_FILTER,
         "trendsFilter": {"display": display}}
    if breakdown:
        q["breakdownFilter"] = {"breakdown": breakdown, "breakdown_type": "event"}
    if formula:
        q["trendsFilter"]["formula"] = formula
    return {"name": name, "query": {"kind": "InsightVizNode", "source": q}}


def ev(event="mcp_tool_called", math="total", **kw):
    e = {"kind": "EventsNode", "event": event, "math": math}
    e.update(kw)
    return e


INSIGHTS = [
    trends("Tool-Aufrufe pro Tag", [ev()]),
    trends("Verschiedene Clients pro Tag", [ev(math="dau")], display="ActionsBar"),
    trends("Verschiedene Clients pro Woche", [ev(math="weekly_active")], interval="week", days=90, display="ActionsBar"),
    trends("Aufrufe je Tool (30 Tage)", [ev()], breakdown="tool", display="ActionsBarValue"),
    trends("Clients nach Art (30 Tage)", [ev(math="dau")], breakdown="client_kind", display="ActionsPie"),
    trends("Verbindungsstarts (initialize) pro Tag", [ev(event="mcp_initialize")], breakdown="client_kind", display="ActionsBar"),
    trends("Fehlerquote % pro Tag", [ev(properties=[{"key": "ok", "type": "event", "value": ["false"], "operator": "exact"}]), ev()],
           formula="A / B * 100"),
    trends("Antwortzeit p95 ms je Tool", [ev(math="p95", math_property="duration_ms")], breakdown="tool", display="ActionsBar"),
]


class PostHog:
    def __init__(self, host, project_id, key):
        self.base = f"{host.rstrip('/')}/api/projects/{project_id}"
        self.key = key

    def _req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            sys.exit(f"PostHog {method} {path} -> HTTP {e.code}: {e.read().decode(errors='replace')[:500]}")

    def find_dashboard(self, name):
        for d in self._req("GET", "/dashboards/?limit=300").get("results", []):
            if d.get("name") == name and not d.get("deleted"):
                return d
        return None

    def create_dashboard(self, name, description):
        return self._req("POST", "/dashboards/", {"name": name, "description": description, "pinned": True})

    def create_insight(self, dashboard_id, spec):
        return self._req("POST", "/insights/", {"name": spec["name"], "query": spec["query"],
                                                 "dashboards": [dashboard_id], "saved": True})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="nur Definition drucken, nichts anlegen")
    ap.add_argument("--project-id", default=os.environ.get("POSTHOG_PROJECT_ID", ""))
    ap.add_argument("--api-key", default=os.environ.get("POSTHOG_PERSONAL_API_KEY", ""))
    ap.add_argument("--host", default=config.POSTHOG_UI_HOST, help="PostHog-UI-Host (EU-Standard aus config)")
    a = ap.parse_args()

    if a.dry_run:
        print(json.dumps({"dashboard": DASHBOARD_NAME, "description": DESCRIPTION, "insights": INSIGHTS},
                         ensure_ascii=False, indent=2))
        return 0
    if not a.api_key or not a.project_id:
        print("POSTHOG_PERSONAL_API_KEY und POSTHOG_PROJECT_ID (oder --api-key/--project-id) noetig; "
              "--dry-run zeigt die Definition ohne Zugang.")
        return 1

    ph = PostHog(a.host, a.project_id, a.api_key)
    dash = ph.find_dashboard(DASHBOARD_NAME)
    if dash:
        print(f"Dashboard existiert schon (id {dash['id']}) — nichts angelegt: {a.host}/project/{a.project_id}/dashboard/{dash['id']}")
        return 0
    dash = ph.create_dashboard(DASHBOARD_NAME, DESCRIPTION)
    for spec in INSIGHTS:
        ins = ph.create_insight(dash["id"], spec)
        print(f"  + {spec['name']} (insight {ins.get('id')})")
    print(f"Dashboard angelegt: {a.host}/project/{a.project_id}/dashboard/{dash['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
