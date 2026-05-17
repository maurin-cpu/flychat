"""
Rendert das Briefing-Mail mit aktuellen Spot-/Region-Analysen und einem
Mock-Subscriber (10 Regionen) und schreibt es als klickbare HTML-Datei
ins Temp-Verzeichnis.

Nutzung:
    python scripts/preview_briefing_email.py

Optional mit anderer Region-Auswahl:
    python scripts/preview_briefing_email.py --regions jura_ost,mittelland_ost

Tipp: Der Pfad am Ende kann direkt im Browser geoeffnet werden.
"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

# Projekt-Root zum sys.path (damit Imports aus flychat/ funktionieren)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Default-Mock-Subscriber: 10 Regionen quer durch CH
DEFAULT_REGIONS = [
    "jura_ost",
    "jura_zentral",
    "mittelland_ost",
    "zentrales_mittelland",
    "berner_voralpen",
    "schwarzsee_gantrisch",
    "waadtlaender_alpen",
    "bodenseeraum",
    "glarnerland_walensee",
    "oberwallis_goms",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--regions", default=",".join(DEFAULT_REGIONS),
                    help="Comma-separated region_ids fuer den Mock-Subscriber")
    ap.add_argument("--email", default="preview@example.com",
                    help="Mock-Email-Adresse")
    ap.add_argument("--no-open", action="store_true",
                    help="Datei nicht im Browser oeffnen")
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "preview"),
                    help="Zielordner fuer briefing_preview.html/.txt "
                         "(Default: data/preview/ im Projekt)")
    args = ap.parse_args()

    # Briefing-Daten frisch aus Cache + Synoptik bauen (kein LLM-Call noetig)
    from chat_engine import GleitcastEngine
    engine = GleitcastEngine()
    briefing_data = engine.build_briefing_data()
    if not briefing_data.get("days"):
        print("FEHLER: keine Spot-/Region-Analysen verfuegbar", file=sys.stderr)
        return 2

    subscriber = {
        "id": 999,
        "email": args.email,
        "regions": [r.strip() for r in args.regions.split(",") if r.strip()],
        "skill_level": "standard",
        "action_token": "PREVIEW-TOKEN-0000",
        "status": "active",
    }

    # Flask-App fuer render_template
    from web import app as flask_app
    from email_service import build_briefing_context
    from flask import render_template

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "briefing_preview.html"
    txt_path = out_dir / "briefing_preview.txt"

    with flask_app.app_context(), flask_app.test_request_context():
        ctx = build_briefing_context(subscriber, briefing_data)
        html = render_template("email/briefing.html", **ctx)
        text = render_template("email/briefing.txt", **ctx)

    html_path.write_text(html, encoding="utf-8")
    txt_path.write_text(text, encoding="utf-8")

    # Stats
    flyable_days = [d for d in ctx['days'] if d['tier'] != 'none' and d['region_groups']]
    print("[OK] briefing_context gebaut:")
    print(f"     - Tage:            {len(ctx['days'])} ({len(flyable_days)} fliegbar)")
    print(f"     - Region-Matrix:   {len(ctx['region_matrix'])} Regionen")
    print(f"     - Verdict:         {ctx['verdict']['headline'] if ctx['verdict'] else '(keiner)'}")
    print()
    print(f"[OK] HTML:  {html_path}")
    print(f"[OK] TEXT:  {txt_path}")

    if not args.no_open:
        url = html_path.as_uri()
        print(f"[OPEN] {url}")
        try:
            webbrowser.open(url)
        except Exception as e:
            print(f"WARN: konnte Browser nicht oeffnen: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
