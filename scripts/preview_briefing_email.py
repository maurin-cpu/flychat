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
    ap.add_argument("--briefing-json", default="data/weekly_briefing.json",
                    help="Pfad zu briefing_data JSON")
    ap.add_argument("--email", default="preview@example.com",
                    help="Mock-Email-Adresse")
    ap.add_argument("--no-open", action="store_true",
                    help="Datei nicht im Browser oeffnen")
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "preview"),
                    help="Zielordner fuer briefing_preview.html/.txt "
                         "(Default: data/preview/ im Projekt)")
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

    # Liste aller Template-Varianten (v1 = Standard, v2-v5 = Alternativen)
    variants = [
        ("v1_baseline",  "email/briefing.html",                    "V1 — Baseline (aktuell live)"),
        ("v2_editorial", "email/variants/v2_editorial.html",       "V2 — Editorial / Magazine"),
        ("v3_minimal",   "email/variants/v3_minimal.html",         "V3 — Minimalist / Mono"),
        ("v4_bold",      "email/variants/v4_bold.html",            "V4 — Bold Color Blocks"),
        ("v5_dense",     "email/variants/v5_dense.html",           "V5 — Data Dashboard / Dense"),
        ("v6_timeline",  "email/variants/v6_timeline.html",        "V6 — Timeline / Vertical Flow"),
        ("v7_pastel",    "email/variants/v7_pastel.html",          "V7 — Soft Pastel / Friendly"),
        ("v8_brutalist", "email/variants/v8_brutalist.html",       "V8 — Brutalist / Mono"),
        ("v9_newspaper", "email/variants/v9_newspaper.html",       "V9 — Newspaper / Multi-Column"),
        ("v10_sport",    "email/variants/v10_sport.html",          "V10 — Sport / Fitness Stats"),
    ]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rendered = []
    with flask_app.app_context(), flask_app.test_request_context():
        ctx = build_briefing_context(subscriber, briefing_data)
        # TXT nur fuer baseline (Plain-Text-Variante ist nicht designspezifisch)
        text = render_template("email/briefing.txt", **ctx)
        (out_dir / "briefing_preview.txt").write_text(text, encoding="utf-8")

        for slug, tpl, label in variants:
            try:
                html = render_template(tpl, **ctx)
                path = out_dir / f"briefing_{slug}.html"
                path.write_text(html, encoding="utf-8")
                rendered.append((slug, label, path))
            except Exception as e:
                print(f"[WARN] {tpl} failed: {e}")

    # Stats
    flyable_days = [d for d in ctx['days'] if d['tier'] != 'none' and d['region_groups']]
    print("[OK] briefing_context gebaut:")
    print(f"     - Tage:            {len(ctx['days'])} ({len(flyable_days)} fliegbar)")
    print(f"     - Region-Matrix:   {len(ctx['region_matrix'])} Regionen")
    print(f"     - Verdict:         {ctx['verdict']['headline'] if ctx['verdict'] else '(keiner)'}")
    print()

    # Index-Seite mit Links zu allen Varianten
    index_html = _build_index_page(rendered, ctx)
    index_path = out_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")

    for slug, label, path in rendered:
        print(f"[OK] {label}")
        print(f"     {path}")
    print()
    print(f"[INDEX] {index_path}")

    if not args.no_open:
        url = index_path.as_uri()
        print(f"[OPEN] {url}")
        try:
            webbrowser.open(url)
        except Exception as e:
            print(f"WARN: konnte Browser nicht oeffnen: {e}")

    return 0


def _build_index_page(rendered: list[tuple], ctx: dict) -> str:
    """Render eine simple Index-Seite mit iframe-Previews aller Varianten nebeneinander."""
    cards = []
    for slug, label, path in rendered:
        cards.append(f"""
        <article class="card">
          <header>
            <h2>{label}</h2>
            <a href="{path.name}" target="_blank">In neuem Tab oeffnen &rarr;</a>
          </header>
          <iframe src="{path.name}" loading="lazy"></iframe>
        </article>
        """)
    cards_html = "\n".join(cards)

    verdict_line = ctx['verdict']['headline'] if ctx['verdict'] else '(keiner)'
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Briefing-Mail Varianten</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,'Inter',sans-serif; background:#0f172a; color:#f1f5f9; padding:24px; }}
  h1 {{ font-size:22px; margin:0 0 4px; font-weight:700; letter-spacing:-0.01em; }}
  .meta {{ color:#94a3b8; font-size:13px; margin-bottom:20px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(420px, 1fr)); gap:18px; }}
  article.card {{ background:#1e293b; border:1px solid #334155; border-radius:10px; overflow:hidden; }}
  article.card header {{ padding:12px 16px; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #334155; }}
  article.card h2 {{ font-size:14px; margin:0; font-weight:600; }}
  article.card a {{ font-size:12px; color:#60a5fa; text-decoration:none; }}
  article.card a:hover {{ text-decoration:underline; }}
  iframe {{ width:100%; height:1200px; border:0; background:#fff; display:block; }}
</style>
</head>
<body>
<h1>Briefing-Mail &mdash; 5 Design-Varianten</h1>
<div class="meta">Verdict: {verdict_line} &middot; {len(ctx['days'])} Tage &middot; {len(ctx['region_matrix'])} Regionen</div>
<div class="grid">
{cards_html}
</div>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
