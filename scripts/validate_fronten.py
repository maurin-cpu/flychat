"""Auto-Validierung der Frontenvorhersage (Plan §6 Schritt 5, Konzept §1h).

Der Schiedsrichter ist im Haus: die HANDANALYSE. Sie erscheint alle 12 h, ist
von Meteorologen nach Messungen gezeichnet, und wir extrahieren sie ohnehin
schon. Damit wird jede Front der naechsten Wochen von selbst zum Testfall —
der Qualitaetsnachweis liegt vor, bevor die Kartenebene live geht.

Verglichen wird NICHT Linie gegen Linie, sondern WAS WIR GESAGT HABEN gegen
WAS EINGETRETEN IST:

  1. Vorhersage gegen spaetere Handanalyse
     Aus der Kette der Handanalysen wird mit demselben Verfahren wie bei der
     Vorhersage (Vorzeichenwechsel der Laengsprojektion, Querabstands-Gate) der
     TATSAECHLICHE Durchgang je Zone bestimmt. Die Differenz zur Ansage ist
     `delta_h`; ihr VORZEICHEN ueber viele Faelle ist die eigentliche Frage —
     eine systematische Schieflage waere korrigierbar, Rauschen nicht.

  2. Gegenlauf: verpasste Fronten
     Die Trefferquote aus unseren eigenen Zeilen ist einseitig — sie sagt nur,
     wie oft eine BEHAUPTUNG stimmte, nie wie oft wir eine Front uebersehen
     haben. Deshalb laeuft die Pruefung auch andersherum: jedes Zonenereignis
     der Ist-Kette, zu dem es keine Ansage gibt, wird als `verpasst` eingetragen
     — aber nur, wenn ein Aussage-Schnappschuss den Zeitpunkt ueberhaupt
     abgedeckt hat. Was vor dem Archivbeginn lag, ist keine verpasste Front,
     sondern eine Zeit ohne Betrieb.

  3. Lauf-Jitter
     Dieselbe Zielzeit, an mehreren Tagen neu beurteilt. Springt die Aussage
     zwischen den Laeufen, ist sie unreif zum Anzeigen — unabhaengig davon, ob
     sie am Ende zufaellig stimmt. Das ist die einzige Pruefung, die SOFORT
     Ergebnisse liefert, weil sie keine Ist-Lage braucht.

WAS DAS VERFAHREN NICHT KANN

Die Ist-Kette hat 12 h Stuetzweite — sie ist selbst unscharf. Die Toleranz fuer
"getroffen" ist deshalb die halbe Stuetzweite der Vorhersage PLUS die halbe der
Analyse; alles andere waere eine Genauigkeit, die der Schiedsrichter nicht hat.
Und: leere Verifikations-Spalten heissen NICHT GEPRUEFT, nicht "kein Befund".
Zeilen ohne ausreichende Analyse-Abdeckung bleiben bewusst leer.

Run:
  python scripts/validate_fronten.py              # urteilen, CSV + Bericht schreiben
  python scripts/validate_fronten.py --probelauf  # nur anzeigen, nichts schreiben
  python scripts/validate_fronten.py --selftest   # Urteilslogik pruefen
"""
import argparse
import csv
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from experiment_fronten_zeitachse import (          # noqa: E402
    EVENT_GAP_H, MIN_ZONE_SHARE, TYP_LABEL,
    cluster_events, load_zones, passages_for_point,
)

ARCHIV = ROOT / "data" / "dwd_fronten_archiv"
VALID = ROOT / "fronten_validation"
OBS = VALID / "observations.csv"
BERICHT = VALID / "AUTO_REPORT.md"

# Zeitlicher Suchradius um eine Ansage. Jenseits davon ist es nicht mehr
# dasselbe Ereignis, sondern die naechste Front — dieselbe Grenze, die auch die
# Ereignis-Trennung in der Zeitachse zieht (dort EVENT_GAP_H = 12 h), hier
# verdoppelt, damit ein grob verschobener Treffer noch als "zu frueh/zu spaet"
# und nicht faelschlich als "keine Front" gilt.
SUCH_H = 2 * EVENT_GAP_H

# Groesste Luecke, ueber die zwischen zwei Handanalysen noch interpoliert wird.
# Der Regelabstand ist 12 h (00/12 UTC). Faellt ein Termin aus, sind es 24 h —
# noch vertretbar. Alles darueber ist keine Kette mehr, sondern zwei.
MAX_ANA_LUECKE_H = 24.0

FRONTWOERTER = re.compile(
    r"(kaltfront|warmfront|okklusion|front|trog|konvergenz)", re.I)


# ============================================================================
# Ist-Lage aus der Kette der Handanalysen
# ============================================================================

def lade_analysen() -> list[dict]:
    """Alle archivierten Handanalysen, nach Gueltigkeit sortiert."""
    out = []
    for p in sorted((ARCHIV / "analyse").glob("dwdc_*.geojson")):
        d = json.loads(p.read_text(encoding="utf-8"))
        g = d["properties"].get("gueltig")
        if not g:
            continue
        out.append({"gueltig": datetime.fromisoformat(g),
                    "features": d["features"], "datei": p.name})
    return sorted(out, key=lambda k: k["gueltig"])


def ketten(analysen: list[dict]) -> list[list[dict]]:
    """Zusammenhaengende Abschnitte — ueber eine Archivluecke wird nicht gerechnet."""
    if not analysen:
        return []
    out, cur = [], [analysen[0]]
    for a in analysen[1:]:
        if (a["gueltig"] - cur[-1]["gueltig"]) > timedelta(hours=MAX_ANA_LUECKE_H):
            out.append(cur)
            cur = []
        cur.append(a)
    out.append(cur)
    return [k for k in out if len(k) >= 2]


def abdeckung(analysen: list[dict]) -> list[tuple[datetime, datetime]]:
    """Zeitraeume, ueber die ein Urteil ueberhaupt moeglich ist."""
    return [(k[0]["gueltig"], k[-1]["gueltig"]) for k in ketten(analysen)]


def _abgedeckt(spanne: list[tuple[datetime, datetime]],
               von: datetime, bis: datetime) -> bool:
    return any(a <= von and bis <= b for a, b in spanne)


def ist_ereignisse(analysen: list[dict], zones: dict) -> dict:
    """Tatsaechliche Durchgaenge je (Zone, Typ) aus der Ist-Kette.

    Dasselbe Verfahren wie bei der Vorhersage — anderer Eingang. Das ist
    Absicht: ein Schiedsrichter mit eigener Methodik wuerde Methoden- und
    Datenfehler vermischen. Hier bleibt genau ein Unterschied uebrig, naemlich
    Vorhersage gegen Ist.
    """
    out: dict[tuple[str, str], list[dict]] = {}
    for kette in ketten(analysen):
        zeiten = [k["gueltig"] for k in kette]
        for zone, pts in sorted(zones.items()):
            lat0 = float(np.mean([p[0] for p in pts]))
            for typ in sorted(TYP_LABEL):
                rows = []
                for la, lo in pts:
                    rows.extend(passages_for_point(la, lo, kette, typ, lat0))
                for grp in cluster_events(rows):
                    ts = np.array(sorted(r[0].timestamp() for r in grp))
                    med = datetime.fromtimestamp(float(np.median(ts)), timezone.utc)
                    davor = [t for t in zeiten if t <= med]
                    danach = [t for t in zeiten if t >= med]
                    out.setdefault((zone, typ), []).append({
                        "median": med,
                        "von": datetime.fromtimestamp(
                            float(np.percentile(ts, 10)), timezone.utc),
                        "bis": datetime.fromtimestamp(
                            float(np.percentile(ts, 90)), timezone.utc),
                        "spots": len(grp), "spots_zone": len(pts),
                        "anteil": round(len(grp) / len(pts), 3),
                        "art": ("quert" if len(grp) / len(pts) >= MIN_ZONE_SHARE
                                else "streift"),
                        "seitlich_km": round(float(np.median([r[2] for r in grp])), 1),
                        "stuetzweite_h": max(r[1] for r in grp),
                        "randwert": all(r[3] for r in grp),
                        "ana_von": max(davor) if davor else zeiten[0],
                        "ana_bis": min(danach) if danach else zeiten[-1],
                    })
    for v in out.values():
        v.sort(key=lambda e: e["median"])
    return out


# ============================================================================
# Bulletin — der unabhaengige semantische Gegencheck
# ============================================================================

def lade_bulletins() -> list[tuple[datetime, str, str]]:
    """(Ausgabezeit, Dateiname, Text). Der Name traegt nur TTHHMM."""
    out = []
    for p in sorted((ARCHIV / "text").glob("SXDL31_*")):
        m = re.search(r"_(\d{2})(\d{2})(\d{2})$", p.name)
        if not m:
            continue                                   # LATEST o. ae.
        try:
            txt = p.read_text(encoding="latin-1")
        except Exception:
            continue
        # Jahr und Monat stehen nur im Text ("ausgegeben am ... den 27.07.2026")
        d = re.search(r"den\s+(\d{2})\.(\d{2})\.(\d{4})", txt)
        if not d:
            continue
        tag, monat, jahr = int(d.group(1)), int(d.group(2)), int(d.group(3))
        out.append((datetime(jahr, monat, tag, int(m.group(2)),
                             tzinfo=timezone.utc), p.name, txt))
    return sorted(out)


def bulletin_zitat(bulletins, zeitpunkt: datetime, typ: str) -> str:
    """Kurzzitat aus dem letzten Bulletin VOR dem Durchgang.

    Bewusst nur ein Zitat, kein Urteil: ob der Meteorologe dasselbe meint,
    entscheidet ein Mensch. Der Automat liefert die Belegstelle, damit er nicht
    jedes Mal im Archiv suchen muss.
    """
    davor = [b for b in bulletins if b[0] <= zeitpunkt]
    if not davor:
        return ""
    zeit, name, txt = davor[-1]
    wort = {"kalt": "kaltfront", "warm": "warmfront",
            "okklusion": "okklusion", "trog": "trog"}.get(typ, "front")
    saetze = [s.strip().replace("\n", " ")
              for s in re.split(r"(?<=[.!?])\s+", txt)]
    treffer = ([s for s in saetze if re.search(wort, s, re.I)]
               or [s for s in saetze if FRONTWOERTER.search(s)])
    if not treffer:
        return f"{name[:6]} {zeit:%d.%m %H} UTC: keine Frontnennung im Text"
    s = re.sub(r"\s+", " ", treffer[0])[:280]
    return f"{name[:6]} {zeit:%d.%m %H} UTC: {s}"


# ============================================================================
# Urteil
# ============================================================================

def beurteile(zeile: dict, ereignisse: list[dict],
              spanne: list[tuple[datetime, datetime]]) -> dict | None:
    """Eine Vorhersagezeile gegen die Ist-Lage. None = noch nicht beurteilbar.

    Vorzeichen von `delta_h` wie im SCHEMA: positiv = die Front kam spaeter als
    angesagt, wir waren also ZU FRUEH.
    """
    T = datetime.fromisoformat(zeile["median_utc"])
    breite = float(zeile.get("stuetzweite_h") or 12.0)
    randwert = str(zeile.get("randwert", "")).strip() == "1"

    nah = [e for e in ereignisse
           if abs((e["median"] - T).total_seconds()) <= SUCH_H * 3600]
    if nah:
        e = min(nah, key=lambda e: abs((e["median"] - T).total_seconds()))
        delta = (e["median"] - T).total_seconds() / 3600.0
        tol = breite / 2 + e["stuetzweite_h"] / 2
        if abs(delta) <= tol:
            urteil = "getroffen"
        else:
            urteil = "zu_frueh" if delta > 0 else "zu_spaet"
        return {
            "ana_gueltig_utc": f"{e['ana_von']:%Y-%m-%dT%H:%MZ}/"
                               f"{e['ana_bis']:%Y-%m-%dT%H:%MZ}",
            "ana_front_da": 1,
            "ana_median_utc": e["median"].isoformat(timespec="minutes"),
            "delta_h": f"{delta:+.1f}",
            "verdict": urteil,
            "notes": (f"auto: Ist-Durchgang {e['median']:%d.%m %H:%M} UTC "
                      f"({e['art']}, {e['spots']}/{e['spots_zone']} Spots), "
                      f"Toleranz ±{tol:.0f} h aus {breite:.0f} h Vorhersage- "
                      f"und {e['stuetzweite_h']:.0f} h Analyse-Stuetzweite"),
        }

    # Kein Ist-Ereignis gefunden — das darf nur behauptet werden, wenn die
    # Analysen den ganzen Suchraum abdecken. Sonst ist es keine Information,
    # sondern eine Luecke.
    if not _abgedeckt(spanne, T - timedelta(hours=SUCH_H),
                      T + timedelta(hours=SUCH_H)):
        return None
    if randwert:
        # Der angesagte Zeitpunkt lag am Rand des Stuetzintervalls: der wahre
        # Durchgang kann ausserhalb des Betrachtungsfensters liegen. Aus einem
        # Nicht-Fund laesst sich dann nichts folgern.
        return {"ana_gueltig_utc": f"{T - timedelta(hours=SUCH_H):%Y-%m-%dT%H:%MZ}/"
                                   f"{T + timedelta(hours=SUCH_H):%Y-%m-%dT%H:%MZ}",
                "ana_front_da": 0, "verdict": "unklar",
                "notes": "auto: kein Ist-Durchgang gefunden, aber Randwert — "
                         "der wahre Durchgang kann ausserhalb des Fensters liegen"}
    return {"ana_gueltig_utc": f"{T - timedelta(hours=SUCH_H):%Y-%m-%dT%H:%MZ}/"
                               f"{T + timedelta(hours=SUCH_H):%Y-%m-%dT%H:%MZ}",
            "ana_front_da": 0, "verdict": "keine_front",
            "notes": f"auto: kein Ist-Durchgang im Fenster ±{SUCH_H:.0f} h"}


# ============================================================================
# Gegenlauf und Lauf-Jitter
# ============================================================================

def _schnappschuss_fenster() -> list[tuple[str, str, datetime, datetime]]:
    """(lauf, stand, von, bis) je Aussage-Schnappschuss.

    Das Fenster ist der Bereich, ueber den der Lauf ueberhaupt etwas sagen
    konnte. Ohne diese Einschraenkung wuerde jede Front vor dem Archivbeginn
    als "verpasst" gezaehlt, obwohl niemand hingeschaut hat.
    """
    out = []
    for p in sorted((VALID / "aussagen").glob("passagen_*_stand_*.json")):
        m = re.match(r"passagen_(\d{12})_stand_(\d{8})\.json", p.name)
        if not m:
            continue
        snap = json.loads(p.read_text(encoding="utf-8"))
        zeiten = [datetime.fromisoformat(s["gueltig_utc"])
                  for s in snap.get("stuetzpunkte", [])]
        if zeiten:
            out.append((m.group(1), m.group(2), min(zeiten), max(zeiten)))
    return out


def verpasste(ist: dict, rows: list[dict], fenster) -> list[dict]:
    """Zonenereignisse der Ist-Kette, zu denen wir nichts gesagt haben."""
    neu = []
    # Bereits eingetragene Fehlstellen: ohne das haengt bei jedem Lauf eine
    # weitere Zeile fuer dasselbe Ereignis an.
    bekannt = {(r.get("zone"), r.get("typ"), (r.get("ana_median_utc") or "")[:16])
               for r in rows if r.get("verdict") == "verpasst"}
    for (zone, typ), events in sorted(ist.items()):
        for e in events:
            if (zone, typ, e["median"].isoformat(timespec="minutes")[:16]) in bekannt:
                continue
            if e["art"] != "quert":
                continue          # Streifschuesse sind keine Zonenaussage
            if not any(v <= e["median"] <= b for _, _, v, b in fenster):
                continue          # kein Lauf hat diesen Zeitpunkt abgedeckt
            gesagt = any(
                r["zone"] == zone and r["typ"] == typ and r.get("median_utc")
                and abs((datetime.fromisoformat(r["median_utc"]) - e["median"])
                        .total_seconds()) <= SUCH_H * 3600
                for r in rows)
            if not gesagt:
                neu.append({"zone": zone, "typ": typ, "art": e["art"],
                            "ana_gueltig_utc": f"{e['ana_von']:%Y-%m-%dT%H:%MZ}/"
                                               f"{e['ana_bis']:%Y-%m-%dT%H:%MZ}",
                            "ana_front_da": 1,
                            "ana_median_utc": e["median"].isoformat(timespec="minutes"),
                            "spots_betroffen": e["spots"],
                            "spots_zone": e["spots_zone"], "anteil": e["anteil"],
                            "verdict": "verpasst",
                            "notes": "auto: Gegenlauf ueber die Handanalysen — "
                                     "Ist-Durchgang ohne zugehoerige Ansage"})
    return neu


def jitter(rows: list[dict], fenster) -> list[dict]:
    """Wie stabil ist dieselbe Aussage ueber mehrere Laeufe hinweg?

    Braucht keine Ist-Lage und liefert deshalb als einzige Pruefung sofort ein
    Ergebnis. Zwei Groessen: die Streuung der angesagten Zeit, und wie oft die
    Aussage in einem Lauf ganz FEHLTE, der den Zeitpunkt abgedeckt hat.
    """
    nach_gruppe: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        if not r.get("median_utc") or not r.get("lauf"):
            continue
        nach_gruppe.setdefault((r["zone"], r["typ"]), []).append(r)

    out = []
    for (zone, typ), rs in sorted(nach_gruppe.items()):
        rs.sort(key=lambda r: r["median_utc"])
        gruppe = [rs[0]]
        for r in rs[1:]:
            vor = datetime.fromisoformat(gruppe[-1]["median_utc"])
            if (datetime.fromisoformat(r["median_utc"]) - vor
                    ).total_seconds() / 3600.0 > EVENT_GAP_H:
                out.append(_jitter_zeile(zone, typ, gruppe, fenster))
                gruppe = []
            gruppe.append(r)
        out.append(_jitter_zeile(zone, typ, gruppe, fenster))
    return out


def _jitter_zeile(zone, typ, gruppe, fenster) -> dict:
    zeiten = [datetime.fromisoformat(r["median_utc"]) for r in gruppe]
    mitte = min(zeiten) + (max(zeiten) - min(zeiten)) / 2
    stände = {(r["lauf"], r["stand"]) for r in gruppe}
    abdeckend = {(lauf, stand) for lauf, stand, v, b in fenster
                 if v <= mitte <= b}
    return {
        "zone": zone, "typ": typ,
        "median_von": min(zeiten), "median_bis": max(zeiten),
        "spanne_h": (max(zeiten) - min(zeiten)).total_seconds() / 3600.0,
        "laeufe": len(stände),
        "abdeckend": len(abdeckend),
        "fehlend": sorted(abdeckend - stände),
        "arten": sorted({r["art"] for r in gruppe if r.get("art")}),
    }


# ============================================================================
# CSV und Bericht
# ============================================================================

def lies_csv() -> tuple[list[dict], list[str]]:
    if not OBS.exists():
        return [], []
    with open(OBS, encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        return list(r), list(r.fieldnames or [])


def schreibe_csv(rows: list[dict], cols: list[str]) -> None:
    rows.sort(key=lambda r: (r.get("median_utc") or r.get("ana_median_utc") or "",
                             r.get("zone", ""), r.get("typ", "")))
    with open(OBS, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def bericht(rows, ist, spanne, jit, offen, neu_beurteilt, neu_verpasst) -> str:
    def zaehle(feld):
        d: dict[str, int] = {}
        for r in rows:
            v = (r.get(feld) or "").strip()
            if v:
                d[v] = d.get(v, 0) + 1
        return d

    urteile = zaehle("verdict")
    auto = [r for r in rows if (r.get("notes") or "").startswith("auto:")]
    deltas = []
    for r in rows:
        if r.get("verdict") not in ("getroffen", "zu_frueh", "zu_spaet"):
            continue
        try:
            deltas.append(float(r["delta_h"]))
        except (TypeError, ValueError):
            pass

    L = ["# Auto-Validierung — erzeugt, nicht von Hand gepflegt",
         "",
         f"Stand {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC, erzeugt von "
         f"`scripts/validate_fronten.py`. Befunde gehoeren nach `PATTERNS.md`, "
         f"Urteile duerfen in `observations.csv` von Hand ueberschrieben werden "
         f"— dieser Bericht wird bei jedem Lauf neu geschrieben.",
         "",
         "## Bestand",
         "",
         f"- {len(rows)} Zeile(n) in `observations.csv`, davon {len(auto)} "
         f"automatisch beurteilt",
         f"- Analyse-Abdeckung: " + (", ".join(
             f"{a:%d.%m %H:%M} – {b:%d.%m %H:%M} UTC" for a, b in spanne)
             or "keine zusammenhaengende Kette (mindestens zwei Analysen noetig)"),
         f"- Ist-Ereignisse in der Analyse-Kette: "
         f"{sum(len(v) for v in ist.values())}",
         f"- neu beurteilt in diesem Lauf: {neu_beurteilt}, "
         f"neue verpasste Fronten: {neu_verpasst}",
         f"- **{offen} Zeile(n) warten auf Analysen** — leer heisst NICHT "
         f"GEPRUEFT, nicht \"kein Befund\"",
         "",
         "## Urteile",
         ""]
    if urteile:
        L += ["| Urteil | Zeilen |", "|---|---|"]
        L += [f"| `{k}` | {v} |" for k, v in sorted(urteile.items())]
    else:
        L.append("Noch kein Urteil moeglich.")
    L += ["", "## Systematik (Vorzeichen von `delta_h`)", ""]
    if deltas:
        med = float(np.median(deltas))
        richtung = ("wir sagen zu FRUEH an" if med > 0 else
                    "wir sagen zu SPAET an" if med < 0 else "kein Versatz")
        L += [f"- n = {len(deltas)}, Median {med:+.1f} h, "
              f"Spanne {min(deltas):+.1f} … {max(deltas):+.1f} h",
              f"- Lesart: {richtung} (positiv = die Front kam spaeter als "
              f"angesagt)",
              "",
              "Eine systematische Schieflage waere korrigierbar, Rauschen "
              "nicht. Ab n < 10 ist beides nicht unterscheidbar — die Zahl "
              "steht hier als Richtungshinweis, nicht als Beleg."]
    else:
        L.append("Noch keine verwertbaren Differenzen.")

    L += ["", "## Lauf-Jitter (braucht keine Ist-Lage)", ""]
    if jit:
        L += ["| Zone | Typ | angesagt fuer | Spanne | Laeufe | fehlt in |",
              "|---|---|---|---|---|---|"]
        for j in jit:
            fehlt = (", ".join(f"Stand {stand}" for _, stand in j["fehlend"])
                     if j["fehlend"] else "—")
            zeit = f"{j['median_von']:%d.%m %H:%M}"
            if j["spanne_h"]:
                zeit += f" – {j['median_bis']:%H:%M}"
            L.append(f"| {j['zone']} | {j['typ']} | {zeit} UTC | "
                     f"{j['spanne_h']:.1f} h | {j['laeufe']} | {fehlt} |")
        L += ["",
              "`fehlt in` = Laeufe, die den Zeitpunkt abgedeckt haben, aber "
              "keine Aussage dazu machten. Das ist der haertere Jitter: nicht "
              "eine verschobene Zeit, sondern eine verschwundene Front."]
    else:
        L.append("Noch keine Aussage mehrfach beurteilt.")

    verp = [r for r in rows if r.get("verdict") == "verpasst"]
    L += ["", "## Verpasste Fronten (Gegenlauf ueber die Analysen)", ""]
    if verp:
        L += [f"- {r['zone']} / {r['typ']} — Ist-Durchgang "
              f"{r['ana_median_utc']}" for r in verp]
    else:
        L.append("Keine — im abgedeckten Zeitraum gab es kein Zonenereignis "
                 "ohne zugehoerige Ansage.")
    L += ["",
          "## Die 0-Front-Regel",
          "",
          "Frontfreie Tage erzeugen keine Zeile. Jede Quote hier gilt nur fuer "
          "Tage, an denen wir etwas behauptet haben; wie oft wir eine Front "
          "uebersehen, beantwortet allein der Gegenlauf oben.",
          ""]
    return "\n".join(L)


# ============================================================================
# Selbsttest
# ============================================================================

def selftest() -> int:
    """Prueft die Urteilslogik an konstruierten Faellen.

    Ohne das laesst sich die Logik nur an echten Frontlagen pruefen — und die
    gibt es nicht auf Bestellung. Geprueft wird vor allem, dass NICHT geurteilt
    wird, wo die Grundlage fehlt.
    """
    t = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    spanne = [(t - timedelta(hours=48), t + timedelta(hours=48))]
    ok = True

    def ev(versatz_h, stuetz=12.0, art="quert"):
        return {"median": t + timedelta(hours=versatz_h), "von": t, "bis": t,
                "spots": 100, "spots_zone": 300, "anteil": 0.33, "art": art,
                "seitlich_km": 30.0, "stuetzweite_h": stuetz, "randwert": False,
                "ana_von": t, "ana_bis": t + timedelta(hours=12)}

    def zeile(stuetz=12.0, rand="0"):
        return {"median_utc": t.isoformat(), "stuetzweite_h": stuetz,
                "randwert": rand, "zone": "alpennordhang", "typ": "kalt"}

    faelle = [
        ("Treffer innerhalb der Toleranz", zeile(), [ev(5)], spanne, "getroffen"),
        ("zu frueh angesagt (Front kam spaeter)", zeile(), [ev(18)], spanne, "zu_frueh"),
        ("zu spaet angesagt (Front kam frueher)", zeile(), [ev(-18)], spanne, "zu_spaet"),
        ("Ansage ohne Ist-Front", zeile(), [], spanne, "keine_front"),
        ("Randwert ohne Ist-Front bleibt unklar", zeile(rand="1"), [], spanne, "unklar"),
        ("weit entferntes Ereignis zaehlt nicht als Treffer",
         zeile(), [ev(40)], spanne, "keine_front"),
    ]
    for i, (was, z, evs, sp, soll) in enumerate(faelle, 1):
        got = beurteile(z, evs, sp)
        ist = (got or {}).get("verdict")
        if ist != soll:
            print(f"  FEHLER {i}: {was} — erwartet {soll}, bekommen {ist}")
            ok = False
        else:
            print(f"  ok {i}  {was} -> {soll}")

    # Der wichtigste Fall: ohne Analyse-Abdeckung wird NICHT geurteilt.
    if beurteile(zeile(), [], []) is not None:
        print("  FEHLER 7: ohne Abdeckung wurde geurteilt")
        ok = False
    else:
        print("  ok 7  ohne Analyse-Abdeckung bleibt die Zeile leer")

    # Und: eine engere Analyse-Stuetzweite verschaerft die Toleranz.
    eng = beurteile(zeile(stuetz=12.0), [ev(9, stuetz=1.0)], spanne)
    if eng["verdict"] != "zu_frueh":
        print(f"  FEHLER 8: Toleranz beruecksichtigt die Analyse-Stuetzweite "
              f"nicht ({eng['verdict']})")
        ok = False
    else:
        print("  ok 8  Toleranz = halbe Vorhersage- + halbe Analyse-Stuetzweite")

    print("Selbsttest bestanden" if ok else "SELBSTTEST FEHLGESCHLAGEN")
    return 0 if ok else 1


# ============================================================================

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true",
                    help="Urteilslogik pruefen, nichts schreiben")
    ap.add_argument("--probelauf", action="store_true",
                    help="nur anzeigen, CSV und Bericht nicht schreiben")
    ap.add_argument("--neu-beurteilen", action="store_true",
                    help="auch bereits automatisch geurteilte Zeilen neu "
                         "bewerten (Zeilen mit Handnotiz bleiben unberuehrt)")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    rows, cols = lies_csv()
    if not cols:
        print(f"Keine {OBS.relative_to(ROOT)} — erst "
              f"scripts/build_fronten_observations.py laufen lassen.")
        return 2

    analysen = lade_analysen()
    spanne = abdeckung(analysen)
    print(f"{len(analysen)} Handanalyse(n), {len(ketten(analysen))} "
          f"zusammenhaengende Kette(n)")
    for a, b in spanne:
        print(f"  abgedeckt {a:%d.%m %H:%M} - {b:%d.%m %H:%M} UTC")
    if not spanne:
        print("  (mindestens zwei Analysen im Abstand von hoechstens "
              f"{MAX_ANA_LUECKE_H:.0f} h noetig — bis dahin ist nur der "
              "Lauf-Jitter auswertbar)")

    zones = load_zones()
    ist = ist_ereignisse(analysen, zones) if spanne else {}
    bulletins = lade_bulletins()

    neu = 0
    for r in rows:
        hand = (r.get("verdict") or "").strip() and not (
            r.get("notes") or "").startswith("auto:")
        if hand:
            continue                     # Handurteil hat Vorrang, immer
        if (r.get("verdict") or "").strip() and not args.neu_beurteilen:
            continue
        if not r.get("median_utc"):
            continue
        u = beurteile(r, ist.get((r["zone"], r["typ"]), []), spanne)
        if not u:
            continue
        if not r.get("bulletin"):
            u["bulletin"] = bulletin_zitat(
                bulletins, datetime.fromisoformat(r["median_utc"]), r["typ"])
        r.update(u)
        neu += 1
        versatz = f"  ({u['delta_h']} h)" if u.get("delta_h") else ""
        print(f"  {r['zone']:<22}{r['typ']:<10}{r['median_utc'][:16]}  "
              f"-> {u['verdict']}{versatz}")

    fenster = _schnappschuss_fenster()
    fehlend = verpasste(ist, rows, fenster)
    for v in fehlend:
        v["bulletin"] = bulletin_zitat(
            bulletins, datetime.fromisoformat(v["ana_median_utc"]), v["typ"])
        rows.append({**{c: "" for c in cols}, **v})
    if fehlend:
        print(f"  Gegenlauf: {len(fehlend)} verpasste Front(en)")

    jit = jitter(rows, fenster)
    offen = sum(1 for r in rows if not (r.get("verdict") or "").strip())

    text = bericht(rows, ist, spanne, jit, offen, neu, len(fehlend))
    if args.probelauf:
        print("\n(Probelauf — nichts geschrieben)\n")
        print(text)
        return 0
    schreibe_csv(rows, cols)
    BERICHT.write_text(text, encoding="utf-8")
    print(f"\n{neu} Zeile(n) neu beurteilt, {offen} warten weiter auf Analysen")
    print(f"  -> {OBS.relative_to(ROOT)}")
    print(f"  -> {BERICHT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
