"""
Rendert die Briefing-Vorschau (v3) mit aktuellen Spot-/Region-Analysen und
einem Mock-Subscriber (10 Regionen) nach data/preview/briefing_preview.html.
Das ist die einzige Vorschau - daran wird gearbeitet.

Nutzung:
    python scripts/preview_briefing_email.py

Optional mit anderer Region-Auswahl:
    python scripts/preview_briefing_email.py --regions tafeljura,mittelland_ost

Tipp: Der Pfad am Ende kann direkt im Browser geoeffnet werden.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shlex
import subprocess
import sys
import webbrowser
from datetime import date
from pathlib import Path

# Projekt-Root zum sys.path (damit Imports aus flychat/ funktionieren)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Default-Mock-Subscriber: 10 Regionen quer durch CH
DEFAULT_REGIONS = [
    "tafeljura",
    "jura_zentral",
    "mittelland_ost",
    "zentrales_mittelland",
    "berner_alpen",
    "freiburger_voralpen",
    "waadtlaender_alpen",
    "bodenseeraum",
    "glarner_alpen",
    "oberwallis_goms",
]


SERVER = "deploy@178.105.39.152"
SERVER_DIR = "/home/deploy/flychat"
_SNAPSHOT_JS = ROOT / "scripts" / "synoptik_snapshot.js"
_SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]


def _snapshot_app_map(base_url: str, day_idx: int, png_path: Path,
                      iso_date: str = "") -> tuple[Path | None, str]:
    """Die Synoptik-Karte aus der App statt eines Nachbaus: Playwright auf dem
    Server oeffnet eine Seite mit der Karte und fotografiert #bfSynoptic
    (scripts/synoptik_snapshot.js, per stdin uebergeben — laeuft also auch,
    solange das Skript noch nicht deployt ist). Lokal gibt es kein Playwright.

    Reihenfolge der Kandidaten:
      1. /synoptik/karte?day=N — die schlanke Kartenseite (Festland-Ausschnitt,
         Hoehenwind-Pfeile). Gibt es erst NACH dem Deploy dieser Route.
      2. /briefing?day=N — die Karte in der Briefing-Seite. Ist deployt, also
         der Grund, dass die Vorschau ueberhaupt ein Bild bekommt.
    Rueckgabe: (PNG oder None, Stand-Text der Karte)."""
    urls = [f"{base_url.rstrip('/')}/synoptik/karte?day={day_idx}",
            f"{base_url.rstrip('/')}/briefing?day={day_idx}"]
    remote = f"/tmp/wingcast_synoptik_{os.getpid()}.png"
    errors = []
    try:
        for url in urls:
            with _SNAPSHOT_JS.open("rb") as js:
                r = subprocess.run(
                    ["ssh", *_SSH_OPTS, SERVER,
                     f"cd {SERVER_DIR} && node - {shlex.quote(url)} {remote} 960 "
                     f"{shlex.quote(iso_date)}"],
                    stdin=js, capture_output=True, timeout=180, check=False)
            if r.returncode == 0:
                break
            errors.append(f"{url}: {r.stderr.decode(errors='replace').strip()[-200:]}")
        else:
            print("WARN: Karten-Screenshot fehlgeschlagen:\n  "
                  + "\n  ".join(errors), file=sys.stderr)
            return None, ""
        if url != urls[0]:
            print(f"     (Karte aus {url} — /synoptik/karte ist noch nicht deployt)",
                  file=sys.stderr)
        png_path.unlink(missing_ok=True)
        # scp mit relativem Ziel: Git-scp liest "C:\..." sonst als Hostname "C"
        subprocess.run(["scp", *_SSH_OPTS, f"{SERVER}:{remote}", png_path.name],
                       cwd=png_path.parent, capture_output=True, timeout=60, check=False)
        subprocess.run(["ssh", *_SSH_OPTS, SERVER, f"rm -f {remote}"],
                       capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"WARN: Karten-Screenshot fehlgeschlagen: {e}", file=sys.stderr)
        return None, ""
    stand = ""
    try:
        stand = json.loads(r.stdout.decode().strip().splitlines()[-1]).get("stand", "")
    except (IndexError, ValueError):
        pass
    ok = png_path.exists() and png_path.stat().st_size > 0
    return (png_path if ok else None), stand


def _snapshot_local_map(base_url: str, day_idx: int, png_path: Path,
                        iso_date: str = "") -> tuple[Path | None, str]:
    """Dieselbe Karte, aber aus einer LOKAL laufenden App fotografiert — node
    mit playwright-core gegen das installierte Chrome. Damit braucht die
    Vorschau keinen Deploy, um die aktuelle Karte zu zeigen."""
    url = f"{base_url.rstrip('/')}/synoptik/karte?day={day_idx}"
    png_path.unlink(missing_ok=True)
    try:
        r = subprocess.run(
            ["node", str(_SNAPSHOT_JS), url, str(png_path), "960", iso_date],
            cwd=str(ROOT), capture_output=True, timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"WARN: lokaler Karten-Screenshot fehlgeschlagen: {e}", file=sys.stderr)
        return None, ""
    if r.returncode != 0:
        print("WARN: lokaler Karten-Screenshot fehlgeschlagen:" + chr(10) + "  "
              + r.stderr.decode(errors="replace").strip()[-400:], file=sys.stderr)
        return None, ""
    stand = ""
    try:
        stand = json.loads(r.stdout.decode().strip().splitlines()[-1]).get("stand", "")
    except (IndexError, ValueError):
        pass
    ok = png_path.exists() and png_path.stat().st_size > 0
    return (png_path if ok else None), stand


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--regions", default=",".join(DEFAULT_REGIONS),
                    help="Comma-separated region_ids fuer den Mock-Subscriber")
    ap.add_argument("--email", default="preview@example.com",
                    help="Mock-Email-Adresse")
    ap.add_argument("--no-open", action="store_true",
                    help="Datei nicht im Browser oeffnen")
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "preview"),
                    help="Zielordner fuer briefing_preview.html "
                         "(Default: data/preview/ im Projekt)")
    ap.add_argument("--tag", default="",
                    help="Auf welchen Tag sich 'Wie ist heute?' bezieht: "
                         "YYYY-MM-DD oder Index 0..n. Default: heute. Nuetzlich, "
                         "weil ein Tag ohne Einschaetzungssaetze im Cache nichts "
                         "ueber das Layout aussagt.")
    ap.add_argument("--lokal-karte", default="",
                    help="Karten-Screenshot LOKAL statt auf dem Server: Basis-URL "
                         "einer laufenden lokalen App, z.B. http://localhost:5001 . "
                         "Braucht node + playwright-core (Chrome-Kanal). Noetig, "
                         "solange /synoptik/karte nicht deployt ist.")
    ap.add_argument("--synoptik", default="",
                    help="JSON aus scripts/preview_synoptik_zonen.py: dessen "
                         "llm_overview_neu ersetzt den Wetterlage-Text aus dem "
                         "Cache — neuen Skill testen, ohne Prod-Cache zu schreiben.")
    args = ap.parse_args()

    # Admin-Overlay anwenden, BEVOR irgendwas config liest. Ohne das rendert die
    # Preview mit den Code-Defaults (LANG=de, FORECAST_DAYS=5) statt mit dem, was
    # produktiv gilt (data/config_overrides.json) - und laedt dann die falschen,
    # meist veralteten Analyse-Caches. Gleicher Ablauf wie cost_testing/analyze_once.py.
    import config_overrides
    config_overrides.init()

    # Briefing-Daten frisch aus Cache + Synoptik bauen (kein LLM-Call noetig)
    from chat_engine import WingcastEngine
    engine = WingcastEngine()
    briefing_data = engine.build_briefing_data()
    if not briefing_data.get("days"):
        print("FEHLER: keine Spot-/Region-Analysen verfuegbar", file=sys.stderr)
        return 2
    if args.synoptik:
        import json
        syn_json = json.loads(Path(args.synoptik).read_text(encoding="utf-8"))
        neu = syn_json.get("llm_overview_neu")
        if neu and briefing_data.get("wetterlage"):
            briefing_data["wetterlage"]["llm_overview"] = neu
            # frisch gerechnete Felder, die der gecachte Kontext noch nicht hat
            if syn_json.get("aloft_regional"):
                briefing_data["wetterlage"]["aloft_regional"] = syn_json["aloft_regional"]
            print(f"[--synoptik] Wetterlage-Text aus {args.synoptik}")
        else:
            print(f"WARN: --synoptik {args.synoptik} ohne llm_overview_neu - nehme Cache",
                  file=sys.stderr)

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
    from email_service import mail_context
    from email_service import build_briefing_context
    from flask import render_template

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    page_path = out_dir / "briefing_preview.html"        # die einzige Vorschau

    # Fokus-Tag aufloesen: Datum direkt, Index ueber die Tagesliste.
    dates = [d.get("date", "") for d in briefing_data.get("days", [])]
    focus_date = ""
    if args.tag:
        if args.tag.isdigit() and int(args.tag) < len(dates):
            focus_date = dates[int(args.tag)]
        elif args.tag in dates:
            focus_date = args.tag
        else:
            print(f"WARN: --tag {args.tag} nicht im Fenster "
                  f"({', '.join(dates)}) - nehme heute", file=sys.stderr)

    # Genau eine Fassung: die Vorschau-Seite.
    from scripts.briefing_v3_context import build_v3_context

    with mail_context(flask_app):
        # Spot-Gruppen fuer JEDE Abo-Region, nicht nur die besten drei: der
        # v2-Regionenblock listet alle Regionen, und Cards ohne Spot-Chips
        # sehen aus wie ein Fehler, obwohl es nur die Kappung von
        # build_briefing_context ist.
        ctx = build_briefing_context(
            subscriber, briefing_data,
            top_n_regions_per_day=max(3, len(subscriber["regions"])),
        )
        # v3 = die Design-Seite nach docs/plaene/PLAN_briefing_mail_v3.md
        ctx = build_v3_context(ctx, briefing_data, subscriber, focus_date=focus_date)
        # Synoptik-Karte 1:1 aus der App (Screenshot, kein Nachbau). Die App
        # waehlt den Tag per Index ab heute (?day=N), nicht per Datum.
        import config
        map_png, map_stand = None, ""
        day_idx = (date.fromisoformat(ctx["v3_focus_date"]) - date.today()).days
        if 0 <= day_idx < int(config.FORECAST_DAYS):
            if args.lokal_karte:
                map_png, map_stand = _snapshot_local_map(
                    args.lokal_karte, day_idx, out_dir / "synoptik_karte.png",
                    ctx["v3_focus_date"])
            else:
                map_png, map_stand = _snapshot_app_map(
                    config.BASE_URL, day_idx, out_dir / "synoptik_karte.png",
                    ctx["v3_focus_date"])
        else:
            print(f"WARN: Fokus-Tag {ctx['v3_focus_date']} liegt nicht im App-Fenster "
                  f"(heute + {config.FORECAST_DAYS} Tage) - keine Karte", file=sys.stderr)
        if map_png:
            ctx["v3_map_img"] = "data:image/png;base64," + base64.b64encode(
                map_png.read_bytes()).decode("ascii")
        page_html = render_template("preview/briefing_preview_page.html", **ctx)

    page_path.write_text(page_html, encoding="utf-8")

    # Stats
    flyable_days = [d for d in ctx['days']
                    if d['tier'] not in ('none', 'unknown') and d['region_groups']]
    cov = ctx.get('coverage') or {}
    unbewertet = [d['label']['short'] for d in ctx['days'] if d['tier'] == 'unknown']
    print("[OK] briefing_context gebaut:")
    print(f"     - Tage:            {len(ctx['days'])} ({len(flyable_days)} fliegbar)")
    print(f"     - Region-Matrix:   {len(ctx['region_matrix'])} Regionen")
    print(f"     - Verdict:         {ctx['verdict']['headline'] if ctx['verdict'] else '(keiner)'}")
    print(f"     - Betreff:         {ctx['v3_subject']}")
    hero = ctx.get('v3_hero')
    print(f"     - Hero-Region:     {hero['region_name'] + ' ' + str(hero['rating']) + '/5 ' + hero['status'] if hero else '(keine)'}")
    print(f"     - Fokus-Tag:       {ctx['v3_focus_date']}"
          f"{'' if ctx['v3_focus_is_today'] else '  (nicht heute)'}")
    for d in ctx['v3_strip']:
        groups = " · ".join(f"{g['range']} {g['status']} {g['n']}".strip() for g in d['groups'])
        print(f"       {d['name']:<6} {d['status']:<10} {groups}"
              f"  CH {d['ch']['hi_safe']}/{d['ch']['total']} 4-5 sicher  {d['pressure']}  {d['notable']}")
    ch = ctx['v3_chain']
    print(f"     - Lage:            {ch['lage']['label']} ({len(ch['lage']['centers'])} Zentren) — {ch['situation'][:90]}")
    print(f"     - Fronten:         {' | '.join(ch['fronts']['lines'])[:140]}")
    print(f"     - Foehn/Bise:      {ch['foehn']['foehn']} {ch['foehn']['bise']}")
    print(f"     - Hoehenwind:      {ch['wind']['arrow']} {ch['wind']['sector']} {ch['wind']['speed']} -> {ch['wind']['ground']} am Boden")
    print(f"     - Karte (App):     {map_png if map_png else '(keine - siehe WARN)'}"
          f"{'  Stand ' + map_stand if map_stand else ''}")
    w = ctx['v3_warnings']
    print(f"     - Warnungen CH:    "
          + (" · ".join(f"{'+' if c['active'] else '-'}{c['label']}" for c in w['checks']) or '(keine Daten)')
          + f"  ({sum(1 for i in w['entries'] if i['ki_text'])}/{len(w['entries'])} mit KI-Satz)")
    cov2 = ctx['v3_coverage']
    print(f"     - Regionen:        {cov2['regions']} "
          f"({cov2['with_recommendation']} mit Einschaetzung, "
          f"{cov2['with_window']} mit Fenster)")
    if cov2['regions'] and not cov2['with_recommendation']:
        print("     ! Kein einziger Einschaetzungssatz an diesem Tag — "
              "die Region-Cards zeigen den Leerzustand. Anderen Tag: --tag <YYYY-MM-DD>")
    print(f"     - Datenlage:       {cov.get('state', '?')} "
          f"({cov.get('cells_rated', 0)}/{cov.get('cells', 0)} Zellen bewertet)")
    if unbewertet:
        print(f"     - ohne Bewertung:  {', '.join(unbewertet)}")
    if cov.get('missing_regions'):
        print(f"     - Regionen ohne Bewertung: {', '.join(cov['missing_regions'])}")
    if cov.get('state') == 'leer':
        print("     ! Diese Mail wuerde NICHT versendet — keine einzige Bewertung.")
    if ctx.get('stale_notice'):
        print(f"     ! {ctx['stale_notice']}")
    print()
    print(f"[OK] SEITE:    {page_path}")

    if not args.no_open:
        url = page_path.as_uri()
        print(f"[OPEN] {url}")
        try:
            webbrowser.open(url)
        except Exception as e:
            print(f"WARN: konnte Browser nicht oeffnen: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
