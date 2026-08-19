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
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fronten_alarm import Alarm                                    # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ARCHIV = ROOT / "data" / "dwd_fronten_archiv"
OUT_DIR = ROOT / "data" / "_experiment_fronten"
EXTRAKT = ROOT / "scripts" / "experiment_dwd_fronten_extraktion.py"

ANALYSIS_URL = "https://opendata.dwd.de/weather/charts/analysis/"
FORECAST_URL = "https://opendata.dwd.de/weather/charts/forecasts/icon/global/na/"
TEXT_URL = "https://opendata.dwd.de/weather/text_forecasts/txt/"

LATEST_DWDC = (ANALYSIS_URL + "Z__C_EDZW_LATEST_tka01%2Cana_bwkman_dwdc_O_"
               "000000_000000_LATEST_WV12.png")

# Ausfall-Alarm des Laufs. In main() gesetzt; ausserhalb eines Laufs (Import,
# --nur rohkarten) bleibt er None und alle Meldungen laufen ins Leere.
_alarm: Alarm | None = None


def _melde(fall: str, was: str, url: str = "") -> None:
    if _alarm is not None:
        _alarm.stoerung(fall, was, url)


def _pruefe_zeichnung(features: list, was: str, url: str = "") -> None:
    """Null Abschnitte auf der GESAMTEN Karte = Zeichenweise geaendert.

    Ganzkartig, nicht auf unser Gebiet bezogen: "keine Front ueber den Alpen"
    ist bei Hochdruck der Normalfall und darf nie alarmieren. Der Ausschnitt
    reicht von Groenland bis Nordafrika — dort war ueber elf Karten (27.07.)
    nie null, sondern 13 bis 19 Abschnitte.
    """
    if not features:
        _melde("zeichnung_weg", f"{was}: 0 Abschnitte auf der gesamten Karte",
               url)


def _listing(url: str) -> list[str]:
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return re.findall(r'href="([^"]+)"', r.text)


def archive_rohkarten() -> list[str]:
    """NUR die PNG-Rohkarten holen, nichts ableiten, nichts versionieren.

    Arbeitsteilung zwischen den beiden geplanten Laeufen:

      Cloud-Routine  holt alles ausser den PNGs und committet es. Sie hat
                     keinen bleibenden Datentraeger, dafuer laeuft sie
                     zuverlaessig.
      Lokal          holt NUR die PNGs. Die sind zu gross fuer Git und werden
                     nur gebraucht, falls die Bilderkennung spaeter verbessert
                     wird und alte Karten neu ausgewertet werden sollen.

    Ohne diese Trennung erzeugen beide Laeufe dieselben versionierten Dateien,
    und jeder git pull kollidiert mit den lokalen Doppeln.
    """
    got = []
    d = ARCHIV / "analyse"
    d.mkdir(parents=True, exist_ok=True)
    stamps = re.findall(r"ana_bwkman_dwdc_O_000000_000000_(\d{12})_",
                        "\n".join(_listing(ANALYSIS_URL)))
    if stamps:
        png = d / f"dwdc_{max(stamps)}.png"
        if not png.exists():
            r = requests.get(LATEST_DWDC, timeout=120)
            r.raise_for_status()
            png.write_bytes(r.content)
            got.append(f"rohkarte analyse {max(stamps)}")

    d = ARCHIV / "vorhersage"
    d.mkdir(parents=True, exist_ok=True)
    for n in _listing(FORECAST_URL):
        if "ico_tkb_na" not in n or "LATEST_WV12" in n:
            continue
        m = re.search(r"_N_(\d{6})_\d{6}_(\d{12})_", n)
        if not m:
            continue
        png = d / f"tkb_{m.group(2)}_{int(m.group(1))}.png"
        if png.exists():
            continue
        r = requests.get(FORECAST_URL + n, timeout=120)
        if r.ok:
            png.write_bytes(r.content)
            got.append(f"rohkarte tkb {m.group(2)} +{int(m.group(1)):03d}")
    return got


def _extract(args: list[str]) -> bool:
    """Bestehende Extraktion als Subprozess — eine Kette, kein Code-Doppel."""
    p = subprocess.run([sys.executable, str(EXTRAKT)] + args,
                       capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        zeilen = (p.stdout + p.stderr).strip().splitlines()
        letzte = zeilen[-1] if zeilen else f"rc={p.returncode} ohne Ausgabe"
        print(f"    EXTRAKTION FEHLGESCHLAGEN ({' '.join(args)}):\n    {letzte}")
        # Der Abbruchgrund steht nur im Text des Subprozesses. Nur die letzte
        # Zeile weitergeben: im Gesamtprotokoll steht bei --alle-steps die
        # Erfolgszeile "Legenden-Invariante: ..." gelungener Steps, deren Wort
        # LEGENDE jeden anderen Fehler als Layoutfall etikettieren wuerde.
        if _alarm is not None:
            _alarm.aus_meldung(letzte, f"Extraktion {' '.join(args)}")
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
        _melde("quelle_weg", "Analyse-Listing ohne datierte dwdc-Namen — "
                             "Pfad oder Namensschema geaendert", ANALYSIS_URL)
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
    _pruefe_zeichnung(data["features"], f"Analyse {stamp}", LATEST_DWDC)
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
            _pruefe_zeichnung(
                json.loads(src.read_text(encoding="utf-8"))["features"],
                f"Vorhersage {src.stem}", FORECAST_URL)
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


def _stempeln(gj: Path, lauf: str | None, vorlauf_h: int, gueltig: str) -> None:
    """Traegt Lauf, Vorlaufzeit und Gueltigkeit in ein GeoJSON nach.

    Beim Weg ueber `--png` kennt die Extraktion diese Angaben nicht
    (`fetch_chart` liefert dort lauf/vorlauf_h/gueltig als None) — die
    Zeitachse braucht die Gueltigkeit aber als Stuetzpunkt. Im Dateinamen
    steht sie, also wird sie hier nachgetragen.
    """
    data = json.loads(gj.read_text(encoding="utf-8"))
    data["properties"]["lauf"] = lauf
    data["properties"]["vorlauf_h"] = vorlauf_h
    data["properties"]["gueltig"] = gueltig
    for f in data["features"]:
        f["properties"]["gueltig"] = gueltig
    gj.write_text(json.dumps(data, indent=1), encoding="utf-8")


def archive_nachziehen() -> list[str]:
    """Fehlende GeoJSON aus schon archivierten Rohkarten nachziehen.

    Der Fall, fuer den es das gibt, ist am 28.-30.07.2026 eingetreten: die
    Rohkarten wurden eingesammelt, die Ableitung fiel aus (der Cloud-Lauf kam
    durch einen Proxy nicht mehr an den DWD, die lokale Aufgabe holte
    weiterhin PNGs). Ueber das DWD-Listing ist da nichts mehr zu retten — die
    Laeufe sind dort nach rund zwei Tagen weg —, die Karte liegt aber auf der
    Platte.

    Laeuft im Volllauf mit: fehlt nichts, kostet es zwei Verzeichnisvergleiche.
    """
    got = []
    for png in sorted((ARCHIV / "vorhersage").glob("tkb_*.png")):
        m = re.match(r"tkb_(\d{12})_(\d+)\.png$", png.name)
        if not m:
            continue
        run, step = m.group(1), int(m.group(2))
        gj = ARCHIV / "vorhersage" / f"dwd_fronten_{run}_{step:03d}.geojson"
        if gj.exists():
            continue
        if not _extract(["--profil", "vorhersage", "--png", str(png),
                         "--out", str(gj)]):
            continue
        t0 = datetime.strptime(run, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
        _stempeln(gj, run, step, (t0 + timedelta(hours=step)).isoformat())
        _pruefe_zeichnung(json.loads(gj.read_text(encoding="utf-8"))["features"],
                          f"Nachzug Vorhersage {run}+{step}")
        got.append(f"nachgezogen vorhersage {run}+{step:03d}")

    for png in sorted((ARCHIV / "analyse").glob("dwdc_*.png")):
        m = re.match(r"dwdc_(\d{12})\.png$", png.name)
        if not m:
            continue
        gj = ARCHIV / "analyse" / f"dwdc_{m.group(1)}.geojson"
        if gj.exists():
            continue
        if not _extract(["--profil", "analyse", "--png", str(png),
                         "--out", str(gj)]):
            continue
        gueltig = datetime.strptime(m.group(1), "%Y%m%d%H%M").replace(
            tzinfo=timezone.utc).isoformat()
        _stempeln(gj, None, 0, gueltig)
        _pruefe_zeichnung(json.loads(gj.read_text(encoding="utf-8"))["features"],
                          f"Nachzug Analyse {m.group(1)}")
        got.append(f"nachgezogen analyse {m.group(1)}")
    return got


def lauf_fingerprint(run: str) -> str:
    """Inhalts-Fingerabdruck der Vorhersagekarten eines Laufs.

    Nicht ueber Dateinamen oder Zeitstempel — nur der Inhalt entscheidet, ob
    eine neue Aussage ueberhaupt anders ausfallen kann.
    """
    h = hashlib.sha256()
    karten = sorted((ARCHIV / "vorhersage").glob(f"dwd_fronten_{run}_*.geojson"))
    for p in karten:
        h.update(p.name.encode("utf-8"))
        h.update(p.read_bytes())
    # Ohne Karten kein Fingerabdruck — leer heisst "unbekannt" und blockiert
    # den Schnappschuss nie.
    return h.hexdigest()[:16] if karten else ""


def letzter_fingerprint(run: str) -> str:
    """Fingerabdruck des juengsten Schnappschusses dieses Laufs, falls er
    einen traegt. Aeltere Schnappschuesse ohne Feld gelten als unbekannt."""
    schnapp = sorted((ARCHIV / "aussagen").glob(f"passagen_{run}_stand_*.json"))
    for p in reversed(schnapp):
        try:
            fp = json.loads(p.read_text(encoding="utf-8")).get("quelle_fingerprint")
        except (OSError, ValueError):
            continue
        if fp:
            return fp
    return ""


def archive_aussagen() -> list[str]:
    """Unsere abgeleiteten Aussagen je Lauf festhalten.

    Eine Momentaufnahme pro Lauf und Kalendertag, aber nur wenn sich die
    Eingangskarten seit der letzten geaendert haben. Bestehende werden NICHT
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
        fp = lauf_fingerprint(run)
        if fp and fp == letzter_fingerprint(run):
            # Gleiche Eingangskarten wie beim letzten Schnappschuss dieses
            # Laufs -> es gaebe Zeichen fuer Zeichen dasselbe Ergebnis. Ein
            # neuer Schnappschuss waere kein Lauf-Jitter, sondern eine
            # Wiederholung derselben Messung, und die Validierung fuehrt jede
            # Wiederholung als eigene Beobachtung.
            continue
        p = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "experiment_fronten_zeitachse.py"),
             "--lauf", run[:10], "--json", str(tgt)],
            capture_output=True, text=True, timeout=900)
        if p.returncode == 0 and tgt.exists():
            snap = json.loads(tgt.read_text(encoding="utf-8"))
            snap["quelle_fingerprint"] = fp
            tgt.write_text(json.dumps(snap, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            got.append(f"aussagen Lauf {run} ({len(snap['aussagen'])} Aussagen)")
        else:
            print(f"    AUSSAGEN FEHLGESCHLAGEN (Lauf {run}): "
                  f"{(p.stdout + p.stderr).strip().splitlines()[-1:]}")
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nur", choices=("analyse", "vorhersage", "text",
                                      "aussagen", "rohkarten", "nachziehen"),
                    help="nur einen Teil einsammeln. 'rohkarten' = nur die "
                         "PNGs, nichts Abgeleitetes (lokaler Lauf, siehe "
                         "archive_rohkarten)")
    ap.add_argument("--ohne-alarm", action="store_true",
                    help="Ausfall-Alarm nicht versenden (nur anzeigen)")
    args = ap.parse_args()

    # Der Alarm haengt am ableitenden Lauf, nicht am reinen Rohkarten-Lauf:
    # sonst melden Cloud und lokaler Rechner denselben Ausfall zweimal.
    global _alarm
    if args.nur != "rohkarten":
        _alarm = Alarm(versand=not args.ohne_alarm)

    # Reihenfolge zaehlt: die Aussagen brauchen Analyse UND Vorhersagekarten,
    # und der Nachzug muss vor ihnen laufen, damit eine gerettete Karte noch
    # in die Aussagen desselben Laufs eingeht.
    steps = {"analyse": archive_analyse, "vorhersage": archive_vorhersage,
             "nachziehen": archive_nachziehen,
             "text": archive_text, "aussagen": archive_aussagen,
             "rohkarten": archive_rohkarten}
    if args.nur:
        steps = {args.nur: steps[args.nur]}
    else:
        steps.pop("rohkarten")            # im Vollauf durch die Extraktion abgedeckt

    new = []
    for name, fn in steps.items():
        try:
            new.extend(fn())
        except Exception as e:
            print(f"  {name}: FEHLER {e}")
            # Netzfehler, HTTP-Fehler, unlesbares PNG — alles derselbe Fall:
            # die Quelle liefert nicht mehr wie erwartet.
            _melde("quelle_weg", f"Schritt '{name}': {type(e).__name__} {e}")
    if new:
        print(f"{len(new)} neu archiviert:")
        for n in new:
            print(f"  + {n}")
    else:
        print("Nichts Neues — Archiv ist aktuell.")
    if args.nur == "rohkarten":
        print("(nur Rohkarten — nichts abgeleitet, nichts versioniert)")
    elif not args.nur or args.nur == "aussagen":
        # Eintragen und beurteilen haengen am selben Lauf: so wird jede Front
        # von selbst zum Testfall, ohne dass jemand daran denken muss.
        for skript in ("build_fronten_observations.py", "validate_fronten.py"):
            p = subprocess.run([sys.executable, str(ROOT / "scripts" / skript)],
                               capture_output=True, text=True, timeout=900)
            print((p.stdout or p.stderr).strip())

    def _n(sub, pat="*"):
        return len(list((ARCHIV / sub).glob(pat))) if (ARCHIV / sub).exists() else 0
    print(f"Bestand: {len(list(ARCHIV.rglob('*.geojson')))} GeoJSON, "
          f"{len(list(ARCHIV.rglob('*.png')))} PNG, {_n('text')} Bulletins, "
          f"{_n('aussagen', '*.json')} Aussage-Schnappschuesse "
          f"in {ARCHIV.relative_to(ROOT)}")

    if _alarm is not None:
        print(f"Ausfall-Alarm: {_alarm.abschluss()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
