"""Archiviert die DWD-Frontenkarten samt extrahierter GeoJSON. (§6 Schritt 3)

Warum: DWD Open Data haelt die Karten nur rund zwei Tage vor. Jeder nicht
archivierte Tag verliert den naechsten Frontdurchgang als Testfall — und die
gesamte Validierung (§1h: Vorhersage gegen spaetere Handanalyse, Lauf-Jitter,
Bulletin-Abgleich) braucht genau diese Historie.

Was pro Lauf eingesammelt wird (idempotent — Vorhandenes wird uebersprungen):

  analyse/     farbige LATEST-Handanalyse (dwdc) als PNG + GeoJSON.
               Die Gueltigkeitszeit steht nicht in der LATEST-Datei, sondern
               wird aus den datierten Zwillingsnamen im Verzeichnislisting
               abgeleitet. Die datierten Karten selbst sind SCHWARZ-WEISS
               (gemessen 27.07.: null Frontfarben-Pixel) und damit nutzlos —
               deshalb muss dieses Skript regelmaessig laufen, um alle
               12-h-Analysen zu erwischen.
  vorhersage/  alle datierten tkb-Karten (+36...+108) als PNG + GeoJSON,
               ueber die bestehende Extraktion (experiment_dwd_fronten_
               extraktion.py als Subprozess, kein Code-Doppel).
  text/        SXDL31-Kurzfrist-Bulletins (Klartext des DWD-Meteorologen,
               fuer den semantischen Abgleich in §1h).
  aussagen/    UNSERE ABGELEITETEN AUSSAGEN je Lauf ("Kaltfront quert Zone X
               am Mittwochvormittag") als JSON. Die Linien allein genuegen
               fuer den spaeteren Abgleich NICHT — verglichen wird spaeter,
               was wir gesagt haben, gegen das, was eingetreten ist. Eine
               Momentaufnahme je Lauf und Kalendertag: so bleibt nachvoll-
               ziehbar, wie sich die Aussage mit kuerzerer Vorlaufzeit
               veraendert hat (Lauf-Jitter, §1h).

Ablage: data/dwd_fronten_archiv/ (gitignored — Rohdaten, kein Arbeitsergebnis).

Run:  python scripts/archive_dwd_fronten.py
      python scripts/archive_dwd_fronten.py --nur analyse
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ARCHIV = ROOT / "data" / "dwd_fronten_archiv"
OUT_DIR = ROOT / "data" / "_experiment_fronten"
EXTRAKT = ROOT / "scripts" / "experiment_dwd_fronten_extraktion.py"

ANALYSIS_URL = "https://opendata.dwd.de/weather/charts/analysis/"
FORECAST_URL = "https://opendata.dwd.de/weather/charts/forecasts/icon/global/na/"
TEXT_URL = "https://opendata.dwd.de/weather/text_forecasts/txt/"

LATEST_DWDC = (ANALYSIS_URL + "Z__C_EDZW_LATEST_tka01%2Cana_bwkman_dwdc_O_"
               "000000_000000_LATEST_WV12.png")


def _listing(url: str) -> list[str]:
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return re.findall(r'href="([^"]+)"', r.text)


def _extract(args: list[str]) -> bool:
    """Bestehende Extraktion als Subprozess — eine Kette, kein Code-Doppel."""
    p = subprocess.run([sys.executable, str(EXTRAKT)] + args,
                       capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        print(f"    EXTRAKTION FEHLGESCHLAGEN ({' '.join(args)}):\n"
              f"    {(p.stdout + p.stderr).strip().splitlines()[-1]}")
    return p.returncode == 0


def archive_analyse() -> list[str]:
    """Farbige LATEST-Analyse holen; Gueltigkeit aus den datierten Namen."""
    d = ARCHIV / "analyse"
    d.mkdir(parents=True, exist_ok=True)
    stamps = re.findall(r"ana_bwkman_dwdc_O_000000_000000_(\d{12})_",
                        "\n".join(_listing(ANALYSIS_URL)))
    if not stamps:
        print("  ANALYSE: keine datierten dwdc-Namen im Listing — "
              "Gueltigkeit nicht bestimmbar, Karte wird NICHT abgelegt.")
        return []
    stamp = max(stamps)
    png, gj = d / f"dwdc_{stamp}.png", d / f"dwdc_{stamp}.geojson"
    if gj.exists():
        return []
    r = requests.get(LATEST_DWDC, timeout=120)
    r.raise_for_status()
    png.write_bytes(r.content)
    if not _extract(["--png", str(png), "--out", str(gj)]):
        return []
    # Gueltigkeit nachtragen — die Zeitachse braucht sie als Stuetzpunkt.
    data = json.loads(gj.read_text(encoding="utf-8"))
    gueltig = datetime.strptime(stamp, "%Y%m%d%H%M").replace(
        tzinfo=timezone.utc).isoformat()
    data["properties"]["gueltig"] = gueltig
    data["properties"]["vorlauf_h"] = 0
    for f in data["features"]:
        f["properties"]["gueltig"] = gueltig
    gj.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return [f"analyse {stamp}"]


def archive_vorhersage() -> list[str]:
    """Alle datierten tkb-Laeufe extrahieren und einsammeln."""
    d = ARCHIV / "vorhersage"
    d.mkdir(parents=True, exist_ok=True)
    got = []
    names = [n for n in _listing(FORECAST_URL)
             if "ico_tkb_na" in n and "LATEST_WV12" not in n]
    runs = sorted({m.group(2) for n in names
                   if (m := re.search(r"_N_(\d{6})_\d{6}_(\d{12})_", n))})
    for run in runs:
        if all((d / f"dwd_fronten_{run}_{s:03d}.geojson").exists()
               for s in (36, 48, 60, 84, 108)):
            continue                      # Lauf vollstaendig archiviert
        if not _extract(["--profil", "vorhersage", "--lauf", run[:10],
                         "--alle-steps"]):
            continue
        for src in OUT_DIR.glob(f"dwd_fronten_{run}_*.geojson"):
            (d / src.name).write_bytes(src.read_bytes())
        for src in OUT_DIR.glob(f"tkb_{run}_*.png"):
            (d / src.name).write_bytes(src.read_bytes())
        got.append(f"vorhersage Lauf {run}")
    return got


def archive_text() -> list[str]:
    """SXDL31-Bulletins (Kurzfrist-Klartext) einsammeln."""
    d = ARCHIV / "text"
    d.mkdir(parents=True, exist_ok=True)
    got = []
    for name in _listing(TEXT_URL):
        if "SXDL31" not in name.upper():
            continue
        tgt = d / name
        if tgt.exists():
            continue
        r = requests.get(TEXT_URL + name, timeout=60)
        if r.ok:
            tgt.write_bytes(r.content)
            got.append(f"text {name}")
    return got


def archive_aussagen() -> list[str]:
    """Unsere abgeleiteten Aussagen je Lauf festhalten.

    Eine Momentaufnahme pro Lauf und Kalendertag. Bestehende werden NICHT
    ueberschrieben — sonst ginge verloren, was wir gestern gesagt haben, und
    genau das ist der Vergleichsgegenstand.
    """
    d = ARCHIV / "aussagen"
    d.mkdir(parents=True, exist_ok=True)
    heute = datetime.now(timezone.utc).strftime("%Y%m%d")
    got = []
    runs = sorted({m.group(1) for p in (ARCHIV / "vorhersage").glob("dwd_fronten_*.geojson")
                   if (m := re.match(r"dwd_fronten_(\d{12})_", p.name))})
    for run in runs:
        tgt = d / f"passagen_{run}_stand_{heute}.json"
        if tgt.exists():
            continue
        p = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "experiment_fronten_zeitachse.py"),
             "--lauf", run[:10], "--json", str(tgt)],
            capture_output=True, text=True, timeout=900)
        if p.returncode == 0 and tgt.exists():
            n = len(json.loads(tgt.read_text(encoding="utf-8"))["aussagen"])
            got.append(f"aussagen Lauf {run} ({n} Aussagen)")
        else:
            print(f"    AUSSAGEN FEHLGESCHLAGEN (Lauf {run}): "
                  f"{(p.stdout + p.stderr).strip().splitlines()[-1:]}")
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nur", choices=("analyse", "vorhersage", "text", "aussagen"),
                    help="nur einen Teil einsammeln")
    args = ap.parse_args()

    # Reihenfolge zaehlt: die Aussagen brauchen Analyse UND Vorhersagekarten.
    steps = {"analyse": archive_analyse, "vorhersage": archive_vorhersage,
             "text": archive_text, "aussagen": archive_aussagen}
    if args.nur:
        steps = {args.nur: steps[args.nur]}

    new = []
    for name, fn in steps.items():
        try:
            new.extend(fn())
        except Exception as e:
            print(f"  {name}: FEHLER {e}")
    if new:
        print(f"{len(new)} neu archiviert:")
        for n in new:
            print(f"  + {n}")
    else:
        print("Nichts Neues — Archiv ist aktuell.")
    if not args.nur or args.nur == "aussagen":
        p = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_fronten_observations.py")],
            capture_output=True, text=True, timeout=300)
        print((p.stdout or p.stderr).strip())

    def _n(sub, pat="*"):
        return len(list((ARCHIV / sub).glob(pat))) if (ARCHIV / sub).exists() else 0
    print(f"Bestand: {len(list(ARCHIV.rglob('*.geojson')))} GeoJSON, "
          f"{len(list(ARCHIV.rglob('*.png')))} PNG, {_n('text')} Bulletins, "
          f"{_n('aussagen', '*.json')} Aussage-Schnappschuesse "
          f"in {ARCHIV.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
