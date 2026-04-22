"""
Rendert das Briefing-Mail mit realen Daten aus data/weekly_briefing.json und
einem Mock-Subscriber (10 Regionen) und schreibt es als klickbare HTML-Datei
ins Temp-Verzeichnis.

Nutzung:
    python scripts/preview_briefing_email.py

Optional mit anderer Region-Auswahl:
    python scripts/preview_briefing_email.py --regions jura_ost,mittelland_ost

Tipp: Der Pfad am Ende kann direkt im Browser geoeffnet werden.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
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
    "urner_alpen",
    "glarnerland_walensee",
    "oberwallis_goms",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--regions", default=",".join(DEFAULT_REGIONS),
                    help="Comma-separated region_ids fuer den Mock-Subscriber")
    ap.add_argument("--briefing-json", default="data/weekly_briefing.json",
                    help="Pfad zu briefing_data JSON")
    ap.add_argument("--email", default="preview@example.com",
                    help="Mock-Email-Adresse")
    ap.add_argument("--no-open", action="store_true",
                    help="Datei nicht im Browser oeffnen")
    args = ap.parse_args()

    briefing_path = ROOT / args.briefing_json
    if not briefing_path.exists():
        print(f"FEHLER: {briefing_path} nicht gefunden", file=sys.stderr)
        return 2

    with briefing_path.open("r", encoding="utf-8") as f:
        briefing_data = json.load(f)

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

    with flask_app.app_context(), flask_app.test_request_context():
        ctx = build_briefing_context(subscriber, briefing_data)
        html = render_template("email/briefing.html", **ctx)
        text = render_template("email/briefing.txt", **ctx)

    # Stats ausgeben
    print("[OK] briefing_context gebaut:")
    print(f"     - Tage:            {len(ctx['days'])}")
    print(f"     - Region-Matrix:   {len(ctx['region_matrix'])} Regionen")
    print(f"     - Top-5 Woche:     {len(ctx['top_spots_week'])} Spots")
    print(f"     - Warnings:        {len(ctx['warnings'])}")
    print(f"     - Verdict:         {ctx['verdict']['headline'] if ctx['verdict'] else '(keiner)'}")

    # HTML-Preview schreiben
    tmp_dir = Path(tempfile.gettempdir()) / "gleitcast_mail_preview"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    html_path = tmp_dir / "briefing_preview.html"
    txt_path = tmp_dir / "briefing_preview.txt"

    html_path.write_text(html, encoding="utf-8")
    txt_path.write_text(text, encoding="utf-8")

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
