"""Waechter fuer das Prognose-Archiv (Vorgabe vom 12.08.2026).

Gemessen am 12.08.2026 ueber alle 87 Tage seit Aufzeichnungsbeginn (18.05.):
neun Tage fehlten ganz, einer war abgeschnitten (28 von 494 Startplaetzen),
29 Tage trugen keine Regionsebene. Kein einziger dieser Ausfaelle hat sich
gemeldet — aufgefallen sind sie erst beim Nachzaehlen, Wochen spaeter.

Ein verlorener Archivtag ist NICHT rekonstruierbar. Die Prognose von damals
gibt es nirgends mehr: die Live-Datei rollt taeglich weiter, und Open-Meteo
liefert rueckwirkend keine Ensembles (CLAUDE.md, Daten-Wegweiser). Genau
deshalb meldet der Waechter sofort, statt auf den naechsten Blick ins Archiv
zu warten.

Die neun fehlenden Tage hatten alle dieselbe Ursache: ein Neustart kurz nach
dem Termin des Morgenlaufs, den der damalige Planer danach nicht mehr ansah.
Das Gegenstueck dazu ist der Nachlauf in `scheduler.py` (_nachlauf); hier
steht nur die Frage "liegt der Tag brauchbar im Archiv" und die Meldung
darueber.

Versandweg wie beim Frontenalarm: `email_service.send_email` an
`config.OPS_ALERT_EMAIL` (scripts/fronten_alarm.py).

Run:
  python scripts/snapshot_wache.py                # heutigen Tag pruefen
  python scripts/snapshot_wache.py 2026-06-23     # bestimmten Tag pruefen
  python scripts/snapshot_wache.py --luecken      # ganzes Archiv durchzaehlen
  python scripts/snapshot_wache.py --testmail     # Versandweg pruefen (ohne Zustand)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ARCHIVE_DIR = ROOT / "data" / "weather_archive"
# Bewusst mit Punkt und ausserhalb von weather_archive: die Auswertungen dort
# lesen das Verzeichnis per glob("*.json") ein, eine Zustandsdatei mittendrin
# wuerde als Archivtag mitgezaehlt.
ZUSTAND_DATEI = ROOT / "data" / ".snapshot_wache.json"

# Unter diesem Anteil der Referenz gilt der Tag als abgeschnitten. Der 23.06.2026
# hatte 28 von 494 Startplaetzen (6 %), weil die Wetterdatei beim Lauf erst halb
# geschrieben war. Referenz ist der juengste aeltere Archivtag statt einer festen
# Zahl: der Bestand waechst (487 -> 488 -> 494), eine feste Zahl waere seit Mai
# schon zweimal falsch gewesen.
MINDESTANTEIL = 0.9
REFERENZ_TAGE = 14

MAENGEL = {
    "fehlt": "Kein Snapshot fuer diesen Tag",
    "unlesbar": "Snapshot vorhanden, aber nicht lesbar",
    "abgeschnitten": "Snapshot enthaelt zu wenige Startplaetze",
    "keine_regionen": "Regionsebene fehlt vollstaendig",
    "keine_spot_bewertung": "Keine Spot-Bewertungen",
    "keine_regions_bewertung": "Keine Regions-Bewertungen",
}

# Was der Mangel praktisch bedeutet — steht so in der Mail, damit die Meldung
# ohne Nachschlagen entscheidbar ist.
FOLGEN = {
    "fehlt": "Der Tag ist als Prognose-Beleg verloren.",
    "unlesbar": "Der Tag ist als Prognose-Beleg verloren.",
    "abgeschnitten": "Nur ein Bruchteil der Startplaetze ist belegt.",
    "keine_regionen": "Region-Ebene rueckwirkend nicht validierbar "
                      "(so gingen im Juli 2026 29 Tage verloren).",
    "keine_spot_bewertung": "Spot-Ebene rueckwirkend nicht validierbar.",
    "keine_regions_bewertung": "Regionsurteile fehlen, Wetterwerte sind da.",
    "fehlerhafte_bewertungen": "Diese Spots/Regionen stehen heute grau in der "
                               "App, auch der Reparaturdurchgang hat sie nicht "
                               "retten koennen.",
    "region_rot_spot_gruen": "Die App zeigt den Spot ohne Warnhinweise, seine "
                             "Region mit schweren — die KI blieb auch nach der "
                             "Rueckfrage bei gruen.",
}

# Hinweise sind keine Maengel: der Tag ist brauchbar, Briefing und Nachversand
# laufen normal. Gemeldet wird trotzdem — einzelne gescheiterte Bewertungen
# liefen bis 10/2026 still durch (20.10.: 14 von 31 Regionen grau, Waechter
# meldete "in Ordnung", weil ein Fehler-Eintrag als "bewertet" zaehlte).
HINWEISE = {
    "fehlerhafte_bewertungen": "Einzelne Bewertungen sind gescheitert",
    # Seit 25.10.2026 fragt die Analyse die KI in diesem Fall nach; was danach
    # noch gruen ist, steht hier (02.08.–25.10.: 111 Faelle ohne Rueckfrage).
    "region_rot_spot_gruen": "Spots ohne Warnhinweise in einer Region mit schweren",
}


# ---------------------------------------------------------------------------
# Pruefung
# ---------------------------------------------------------------------------

def _lies(pfad: Path) -> Optional[dict]:
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except Exception:
        return None


def _referenz_spots(tag: str, archive_dir: Path) -> Optional[int]:
    """Startplatz-Zahl des juengsten aelteren Archivtags (max. REFERENZ_TAGE zurueck)."""
    try:
        d = date.fromisoformat(tag)
    except ValueError:
        return None
    for zurueck in range(1, REFERENZ_TAGE + 1):
        pfad = archive_dir / f"{(d - timedelta(days=zurueck)).isoformat()}.json"
        if not pfad.exists():
            continue
        daten = _lies(pfad)
        if daten and daten.get("spots"):
            return len(daten["spots"])
    return None


def _gescheitert(eintrag: dict) -> bool:
    a = eintrag.get("analysis")
    return isinstance(a, dict) and "error" in (a.get("safety_status"), a.get("status"))


def _status(eintrag: dict) -> Optional[str]:
    a = eintrag.get("analysis")
    return a.get("safety_status") if isinstance(a, dict) else None


def _region_rot_spot_gruen(spots: dict, regionen: dict) -> List[str]:
    """Spots, die gruen stehen, waehrend die Region, unter der die App sie
    zeigt (analyse_region), schwere Warnhinweise hat. Am Ergebnis gemessen,
    nicht an der Ursache (fehlender Kontext, KI ignoriert Regel, …)."""
    rot = {r.get("region_name") for r in regionen.values() if _status(r) == "not_safe"}
    return sorted(
        f"{name} ({s.get('analyse_region')})" for name, s in spots.items()
        if _status(s) == "safe" and s.get("analyse_region") in rot
    )


def befund(tag: Optional[str] = None, archive_dir: Optional[Path] = None) -> dict:
    """Prueft einen Archivtag. Gibt Zahlen UND die Mangelliste zurueck.

    Absichtlich ohne Seiteneffekt: dieselbe Funktion bedient den Scheduler,
    die CLI und die Tests.
    """
    archive_dir = Path(archive_dir or ARCHIVE_DIR)
    tag = tag or date.today().isoformat()
    b: Dict = {"tag": tag, "spots": 0, "regionen": 0, "spots_bewertet": 0,
               "regionen_bewertet": 0, "spots_fehler": 0, "regionen_fehler": 0,
               "referenz_spots": None, "schema": 0, "maengel": [], "hinweise": [],
               "region_rot_spot_gruen": []}

    pfad = archive_dir / f"{tag}.json"
    if not pfad.exists():
        b["maengel"].append("fehlt")
        return b

    daten = _lies(pfad)
    if daten is None:
        b["maengel"].append("unlesbar")
        return b

    meta = daten.get("_meta") or {}
    spots = daten.get("spots") or {}
    regionen = daten.get("regions") or {}
    b["schema"] = meta.get("schema_version") or 1
    b["spots"] = len(spots)
    b["regionen"] = len(regionen)
    # _meta zuerst, aber nicht blind: aeltere Snapshots (schema 1) fuehren die
    # Zaehler noch nicht, dort wird gezaehlt.
    b["spots_bewertet"] = meta.get("spots_with_analysis")
    if b["spots_bewertet"] is None:
        b["spots_bewertet"] = sum(1 for s in spots.values() if s.get("analysis"))
    b["regionen_bewertet"] = meta.get("regions_with_analysis")
    if b["regionen_bewertet"] is None:
        b["regionen_bewertet"] = sum(1 for r in regionen.values() if r.get("analysis"))
    b["referenz_spots"] = _referenz_spots(tag, archive_dir)

    ref = b["referenz_spots"]
    if b["spots"] == 0 or (ref and b["spots"] < ref * MINDESTANTEIL):
        b["maengel"].append("abgeschnitten")
    if not b["regionen"]:
        b["maengel"].append("keine_regionen")
    if not b["spots_bewertet"]:
        b["maengel"].append("keine_spot_bewertung")
    elif not b["regionen_bewertet"] and b["regionen"] and b["schema"] >= 2:
        # Nur ab schema 2 ein Mangel: die Regionsurteile kamen erst mit dieser
        # Fassung in den Snapshot. Vorher trugen ALLE Tage null Regionsurteile —
        # als Mangel gewertet waere die halbe Historie rot, und ein Waechter,
        # bei dem alles rot ist, meldet nichts mehr (Lehre aus fronten_alarm.py).
        b["maengel"].append("keine_regions_bewertung")

    # Gescheiterte Bewertungen stehen als Eintrag mit Status "error" im
    # Snapshot und zaehlen oben als "bewertet" — darum separat zaehlen.
    b["spots_fehler"] = sum(1 for s in spots.values() if _gescheitert(s))
    b["regionen_fehler"] = sum(1 for r in regionen.values() if _gescheitert(r))
    if b["spots_fehler"] or b["regionen_fehler"]:
        b["hinweise"].append("fehlerhafte_bewertungen")
    b["region_rot_spot_gruen"] = _region_rot_spot_gruen(spots, regionen)
    if b["region_rot_spot_gruen"]:
        b["hinweise"].append("region_rot_spot_gruen")
    return b


def brauchbar(tag: Optional[str] = None, archive_dir: Optional[Path] = None) -> bool:
    """True, wenn der Tag vollstaendig im Archiv liegt. Kurzform fuer den Scheduler."""
    return not befund(tag, archive_dir)["maengel"]


def luecken(archive_dir: Optional[Path] = None) -> List[dict]:
    """Zaehlt das ganze Archiv durch: fehlende Tage plus unvollstaendige.

    Das ist das Werkzeug, mit dem der Befund vom 12.08.2026 entstanden ist.
    Es bleibt hier, damit die Zahl jederzeit nachpruefbar ist statt in einem
    Protokoll zu stehen (CLAUDE.md: Zahlen aus Logs sind kein Beleg).
    """
    archive_dir = Path(archive_dir or ARCHIVE_DIR)
    tage = sorted(p.stem for p in archive_dir.glob("*.json")
                  if len(p.stem) == 10 and p.stem[4] == "-")
    if not tage:
        return []
    ergebnis: List[dict] = []
    tag = date.fromisoformat(tage[0])
    ende = date.fromisoformat(tage[-1])
    while tag <= ende:
        b = befund(tag.isoformat(), archive_dir)
        if b["maengel"]:
            ergebnis.append(b)
        tag += timedelta(days=1)
    return ergebnis


# ---------------------------------------------------------------------------
# Zustand (Wiederholungssperre der Meldungen)
# ---------------------------------------------------------------------------

def _lade_zustand() -> dict:
    try:
        return json.loads(ZUSTAND_DATEI.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _speichere_zustand(z: dict) -> None:
    ZUSTAND_DATEI.parent.mkdir(parents=True, exist_ok=True)
    ZUSTAND_DATEI.write_text(json.dumps(z, indent=1, ensure_ascii=False),
                             encoding="utf-8")


# ---------------------------------------------------------------------------
# Meldung
# ---------------------------------------------------------------------------

def _zaehlung(b: dict) -> str:
    ref = b["referenz_spots"]
    fehler_s = f", {b['spots_fehler']} gescheitert" if b.get("spots_fehler") else ""
    fehler_r = f", {b['regionen_fehler']} gescheitert" if b.get("regionen_fehler") else ""
    return (
        f"Gezaehlt:  {b['spots']} Startplaetze "
        f"({b['spots_bewertet']} bewertet{fehler_s})"
        + (f", Referenz Vortag {ref}\n" if ref else "\n") +
        f"           {b['regionen']} Regionen "
        f"({b['regionen_bewertet']} bewertet{fehler_r})\n"
        f"Geprueft:  {datetime.now().isoformat(timespec='seconds')}\n\n"
    )


def _text_rot_gruen(b: dict) -> str:
    liste = b.get("region_rot_spot_gruen") or []
    return (
        f"- {HINWEISE['region_rot_spot_gruen']} ({len(liste)})\n"
        f"    {FOLGEN['region_rot_spot_gruen']}\n"
        + "".join(f"    {s}\n" for s in liste) +
        "Ursache im Log:  journalctl -u wingcast.service | grep REGION-UNTERGRENZE\n\n"
    )


def _text_hinweise(b: dict) -> tuple:
    """Tag ist brauchbar, aber einzelne Bewertungen fehlen (Status "error")
    und/oder Spots stehen gruen in einer roten Region."""
    hinweise = b.get("hinweise") or []
    if "fehlerhafte_bewertungen" not in hinweise:
        n = len(b.get("region_rot_spot_gruen") or [])
        betreff = f"[Wingcast] {b['tag']}: {n} Spots gruen in roter Region"
        text = (
            f"Der Archivtag {b['tag']} ist brauchbar, aber Spot und Region "
            f"widersprechen sich.\n\n"
            + _text_rot_gruen(b) + _zaehlung(b) +
            "Hoechstens eine Meldung pro Archivtag.\n"
        )
        return betreff, text
    betreff = (f"[Wingcast] {b['tag']}: {b.get('regionen_fehler', 0)} Regionen / "
               f"{b.get('spots_fehler', 0)} Spots ohne Bewertung")
    text = (
        f"Der Archivtag {b['tag']} ist brauchbar, aber nicht vollstaendig bewertet.\n\n"
        f"- {HINWEISE['fehlerhafte_bewertungen']}\n"
        f"    {FOLGEN['fehlerhafte_bewertungen']}\n\n"
        + (_text_rot_gruen(b) if "region_rot_spot_gruen" in hinweise else "")
        + _zaehlung(b) +
        "Der Analyse-Lauf rechnet gescheiterte Bewertungen in bis zu drei\n"
        "Runden nach (Pausen 30/90/180 s). Was danach noch fehlt, steht hier.\n"
        "Ursache im Log:  journalctl -u wingcast.service | grep REPARATUR\n"
        "Von Hand:        Admin -> Analyse fuer Regionen bzw. Spots neu starten,\n"
        "                 danach python scripts/snapshot_weather.py " + b["tag"] + "\n"
        "\nHoechstens eine Meldung pro Archivtag.\n"
    )
    return betreff, text


def _text(b: dict, nachgeholt: Optional[bool] = None) -> tuple:
    maengel = b.get("maengel") or []
    hinweise = b.get("hinweise") or []
    if not maengel:
        return _text_hinweise(b)
    kopf = MAENGEL.get(maengel[0], "Snapshot unvollstaendig")
    betreff = f"[Wingcast] Prognose-Archiv {b['tag']}: {kopf}"

    zeilen = [f"- {MAENGEL.get(m, m)}\n    {FOLGEN.get(m, '')}" for m in maengel]
    zeilen += [f"- {HINWEISE.get(h, h)}\n    {FOLGEN.get(h, '')}" for h in hinweise]
    text = (
        f"Der Archivtag {b['tag']} ist nicht in Ordnung.\n\n"
        + "\n".join(zeilen) + "\n\n"
        + _zaehlung(b)
    )
    if nachgeholt is True:
        text += "Der Lauf wurde automatisch nachgeholt, der Tag ist gerettet.\n\n"
    elif nachgeholt is False:
        text += ("Nachholen war nicht mehr sinnvoll (nach der Mittagsgrenze) oder\n"
                 "ist gescheitert. Der Tag laesst sich nicht rekonstruieren: die\n"
                 "Prognose von heute Morgen existiert nirgends mehr.\n\n")
    text += ("Haeufigste Ursache: der Dienst lief zum Termin des Morgenlaufs nicht\n"
             "(Neustart, Deploy, Ubuntu-Update), und der Nachlauf konnte den Tag\n"
             "nicht mehr retten.\n\n"
             "Nachpruefen:  python scripts/snapshot_wache.py --luecken\n"
             "Von Hand:     python scripts/snapshot_weather.py " + b["tag"] + "\n"
             "\nHoechstens eine Meldung pro Archivtag.\n")
    return betreff, text


def _sende(betreff: str, text: str, versand: bool = True) -> None:
    print(f"  WACHE-MAIL: {betreff}")
    if not versand:
        print("  (Versand abgeschaltet — nur Anzeige)")
        return
    try:
        import config
        # Auf einem Entwicklungsrechner fehlen Archiv und Abo-Datenbank; der
        # Befund waere dort immer "Tag verloren". Ein Alarm, der oft grundlos
        # kommt, wird ignoriert — und dann sieht man den echten Ausfall auch
        # nicht mehr. Zum Testen des Versandwegs: OPS_ALERT_FORCE=1.
        erlaubt, grund = config.ops_produktion()
        if not erlaubt:
            print(f"  (kein Versand — {grund}; OPS_ALERT_FORCE=1 erzwingt ihn)")
            return
        import email_service
        betreff = config.ops_betreff(betreff)
        html = "<pre>" + text.replace("<", "&lt;").replace(">", "&gt;") + "</pre>"
        ok = email_service.send_email(config.OPS_ALERT_EMAIL, betreff, html, text)
        print(f"  -> {config.OPS_ALERT_EMAIL}: "
              f"{'gesendet' if ok else 'NICHT gesendet (siehe Log)'}")
    except Exception as e:
        # Wie beim Frontenalarm: eine gescheiterte Meldung darf den Lauf nie
        # mitnehmen. Das Archiv ist wichtiger als die Nachricht darueber.
        print(f"  WACHE-VERSAND FEHLGESCHLAGEN: {e}")


def melde(b: dict, nachgeholt: Optional[bool] = None, versand: bool = True) -> str:
    """Meldet den Befund per Mail — hoechstens einmal je Archivtag und Mangelbild.

    Ein Wiederholungsschutz ist noetig, weil der Waechter bei jedem Neustart
    laeuft. Ein taeglich gleicher Alarm wird ignoriert, dann ist er wertlos
    (Lehre aus scripts/fronten_alarm.py).
    """
    befunde = b["maengel"] + b.get("hinweise", [])
    if not befunde:
        return "kein Mangel"
    z = _lade_zustand()
    if z.get("gemeldet_tag") == b["tag"] and z.get("gemeldet_maengel") == befunde:
        return f"schon gemeldet ({b['tag']})"
    betreff, text = _text(b, nachgeholt)
    _sende(betreff, text, versand)
    z.update({"gemeldet_tag": b["tag"], "gemeldet_maengel": befunde,
              "gemeldet_am": datetime.now().isoformat(timespec="seconds")})
    _speichere_zustand(z)
    return f"gemeldet ({', '.join(befunde)})"


def _briefing_lage(briefings_heute: Optional[int],
                   nachversand: Optional[dict] = None) -> str:
    """Formuliert, was mit dem Briefing-Versand ist — gemessen, nicht geraten.

    Ein fehlender Snapshot heisst NICHT automatisch, dass der Versand
    ausgefallen ist: Versand und Snapshot sind zwei Schritte desselben Laufs.
    Faellt nur der Snapshot-Schritt aus, sind die Mails laengst beim Kunden.
    Faellt der ganze Lauf aus (Neustart nach 06:00), fehlt beides. Welcher
    Fall vorliegt, verraet die Abo-Datenbank (subscriber.count_sent_today).

    `briefings_heute` ist der Stand VOR dem Nachversand, `nachversand` das
    Ergebnis von scheduler._nachversand_falls_rechtzeitig ({'sent': n} oder
    {'grund': ...}) — sonst laese sich nicht mehr unterscheiden, ob die Mails
    aus dem Morgenlauf kamen oder aus der Reparatur.
    """
    if briefings_heute is None or briefings_heute < 0:
        return ("Briefing-Versand:  nicht feststellbar (Abo-Datenbank nicht "
                "erreichbar).\n")
    if briefings_heute == 0:
        kopf = ("Briefing-Versand:  KEINE Mail aus dem Morgenlauf — es ist also\n"
                "                   nicht nur der Snapshot ausgefallen, sondern\n"
                "                   der ganze Lauf.\n")
        return kopf + _nachversand_lage(nachversand)
    return (f"Briefing-Versand:  in Ordnung, {briefings_heute} Abo(s) haben heute\n"
            f"                   ihre Mail bekommen. Betroffen ist NUR das Archiv,\n"
            f"                   der Kunde hat nichts gemerkt.\n")


def _nachversand_lage(nachversand: Optional[dict]) -> str:
    """Zeile(n) zum Nachversand — sagt, was passiert ist, nicht was Politik ist."""
    if nachversand is None:
        return ("Nachversand:       nicht versucht.\n")
    sent = nachversand.get("sent", 0)
    if sent:
        zeit = nachversand.get("zeit")
        wann = f" um {zeit}" if zeit else ""
        zusatz = ""
        if nachversand.get("failed"):
            zusatz = (f"\n                   {nachversand['failed']} Mail(s) "
                      f"scheiterten trotzdem — Log pruefen.")
        return (f"Nachversand:       {sent} Abo(s){wann} nachversendet (nur solche\n"
                f"                   ohne heutige Mail, Doppelversand ausgeschlossen)."
                f"{zusatz}\n")
    grund = nachversand.get("grund")
    if grund:
        return f"Nachversand:       unterblieben — {grund}.\n"
    return ("Nachversand:       kein Abo offen — es war nichts nachzusenden.\n")


def melde_nachlauf(vorher: dict, nachher: dict, briefings_heute: Optional[int] = None,
                   versand: bool = True, nachversand: Optional[dict] = None) -> str:
    """Meldet, dass ein ausgefallener Morgenlauf nachgeholt wurde (einmal je Tag).

    Diese Meldung kommt AUCH, wenn das Nachholen geklappt hat — absichtlich:
    dass ein Lauf ueberhaupt ausgefallen ist, gehoert gesehen, sonst faellt
    ein schleichendes Problem (z.B. jeder Deploy am Morgen) nie auf.
    """
    tag = vorher["tag"]
    z = _lade_zustand()
    if z.get("nachlauf_gemeldet_tag") == tag:
        return f"Nachlauf schon gemeldet ({tag})"

    erfolg = not nachher.get("maengel")
    betreff = (f"[Wingcast] Archivtag {tag} war unvollstaendig — "
               f"{'nachgeholt' if erfolg else 'NICHT gerettet'}")
    text = (
        f"Der Archivtag {vorher['tag']} wurde um "
        f"{datetime.now().strftime('%H:%M')} nachgeholt.\n\n"
        f"Vorgefunden:  {', '.join(MAENGEL.get(m, m) for m in vorher['maengel'])}\n"
        f"Danach:       "
        + (f"{nachher.get('spots', 0)} Startplaetze "
           f"({nachher.get('spots_bewertet', 0)} bewertet), "
           f"{nachher.get('regionen', 0)} Regionen "
           f"({nachher.get('regionen_bewertet', 0)} bewertet)\n"
           if erfolg else
           f"weiterhin {', '.join(nachher.get('maengel', ['unbekannt']))}\n")
        + _briefing_lage(briefings_heute, nachversand) +
        f"\nUrsache pruefen: gab es am {datetime.now().strftime('%d.%m.')} um den\n"
        f"Termin des Morgenlaufs einen Deploy oder Neustart? Der Planer holt\n"
        f"einen verpassten oder abgebrochenen Lauf einmal je Tag nach.\n"
        f"Auch ohne Zutun moeglich: das automatische Ubuntu-Update laeuft\n"
        f"taeglich zwischen 06:00 und 07:00 und startet bei manchen Paketen\n"
        f"(z.B. libpam) alle Dienste neu — so geschehen am 29.08.2026 um 06:03.\n"
        f"Pruefen mit: grep \"^{vorher['tag']} 06:\" /var/log/dpkg.log\n"
    )
    _sende(betreff, text, versand)
    z["nachlauf_gemeldet_tag"] = tag
    z["nachlauf_gemeldet_am"] = datetime.now().isoformat(timespec="seconds")
    _speichere_zustand(z)
    return f"Nachlauf gemeldet ({'ok' if erfolg else 'gescheitert'})"


def pruefe_und_melde(tag: Optional[str] = None, nachgeholt: Optional[bool] = None,
                     versand: bool = True) -> dict:
    """Einstieg fuer den Scheduler: pruefen, bei Mangel melden, Befund zurueck."""
    b = befund(tag)
    if b["maengel"] or b["hinweise"]:
        b["meldung"] = melde(b, nachgeholt=nachgeholt, versand=versand)
    return b


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("tag", nargs="?", help="YYYY-MM-DD (Default: heute)")
    p.add_argument("--luecken", action="store_true",
                   help="Ganzes Archiv durchzaehlen (fehlende + unvollstaendige Tage)")
    p.add_argument("--melden", action="store_true",
                   help="Bei Mangel auch die Mail senden (Default: nur anzeigen)")
    p.add_argument("--testmail", action="store_true",
                   help="Probemeldung senden, Zustand bleibt unberuehrt")
    args = p.parse_args(argv)

    if args.testmail:
        import config
        probe = {"tag": date.today().isoformat(), "spots": 28, "regionen": 0,
                 "spots_bewertet": 0, "regionen_bewertet": 0, "referenz_spots": 494,
                 "maengel": ["abgeschnitten", "keine_regionen", "keine_spot_bewertung"]}
        betreff, text = _text(probe, nachgeholt=True)
        # Der Hinweis MUSS in den Text, nicht nur in den Betreff: Mail-Clients
        # und Weiterleitungen zeigen oft nur den Rumpf, und wer eine
        # Alarmmeldung liest, liest die Zahlen — nicht die Betreffzeile.
        # Am 12.08.2026 hat genau das einen Fehlalarm ausgeloest.
        text = (f"*** PROBEMELDUNG — KEIN ECHTER BEFUND ***\n"
                f"Test des Versandwegs (scripts/snapshot_wache.py --testmail).\n"
                f"Die Zahlen unten sind erfunden. Der echte Stand steht in\n"
                f"    python scripts/snapshot_wache.py\n"
                f"{'=' * 62}\n\n") + text
        print(f"Empfaenger: {config.OPS_ALERT_EMAIL}\n")
        print(text)
        _sende("[PROBE] " + betreff, text)
        return 0

    if args.luecken:
        offen = luecken()
        if not offen:
            print("Archiv lueckenlos und vollstaendig.")
            return 0
        print(f"{len(offen)} Tag(e) mit Befund:\n")
        for b in offen:
            kurz = ", ".join(b["maengel"])
            print(f"  {b['tag']}  {kurz:<55} "
                  f"spots={b['spots']} bew={b['spots_bewertet']} "
                  f"reg={b['regionen']} bew={b['regionen_bewertet']}")
        fehlend = sum(1 for b in offen if "fehlt" in b["maengel"])
        print(f"\n{fehlend} Tag(e) fehlen ganz, "
              f"{len(offen) - fehlend} sind unvollstaendig.")
        return 1

    b = befund(args.tag)
    if not b["maengel"] and not b["hinweise"]:
        print(f"{b['tag']}: in Ordnung ({b['spots']} Startplaetze, "
              f"{b['spots_bewertet']} bewertet, {b['regionen']} Regionen, "
              f"{b['regionen_bewertet']} bewertet).")
        return 0
    print(f"{b['tag']}: {', '.join(b['maengel'] + b['hinweise'])}")
    for m in b["maengel"]:
        print(f"  - {MAENGEL.get(m, m)}: {FOLGEN.get(m, '')}")
    for h in b["hinweise"]:
        if h == "region_rot_spot_gruen":
            print(f"  - {HINWEISE[h]}: {', '.join(b['region_rot_spot_gruen'])}")
            continue
        print(f"  - {HINWEISE.get(h, h)}: {b['regionen_fehler']} Regionen, "
              f"{b['spots_fehler']} Spots gescheitert")
    if args.melden:
        print(melde(b))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
