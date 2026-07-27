"""Wann quert eine Front unsere Flugwetter-Zonen? (Schritt 2, §6 des Plans)

Die Linie auf der Karte ist noch keine Aussage. Verwertbar wird sie erst als
Zeitpunkt: "Die Kaltfront erreicht den Alpennordhang am Montagnachmittag."
Dieses Skript leitet das aus den extrahierten Frontlinien mehrerer
Vorlaufzeiten ab.

VERFAHREN

Fuer jeden Spot einer Zone und jede Vorlaufzeit wird der naechste Punkt auf
einer Frontlinie gesucht. Zwischen zwei aufeinanderfolgenden Vorlaufzeiten
ergibt sich daraus die Zugrichtung der Front (Bewegung des naechsten Punktes).
Projiziert man die Lage des Spots auf diese Richtung, entsteht ein
VORZEICHENBEHAFTETER Abstand: positiv = die Front steht noch bevor, negativ =
sie ist durch. Wechselt das Vorzeichen zwischen zwei Terminen, lag der
Durchgang dazwischen; der genaue Zeitpunkt wird linear interpoliert.

Der Umweg ueber die Zugrichtung ist noetig, weil ein reiner Abstand nicht
zwischen "Front zieht heran" und "Front zieht ab" unterscheiden kann.

WARUM PRO SPOT UND NICHT PRO ZONE

Der Alpennordhang ist rund 270 km breit. Eine Front mit 40 km/h braucht dafuer
etwa sieben Stunden. Ein einzelner Zeitpunkt fuer die ganze Zone waere deshalb
eine Scheingenauigkeit — ausgegeben wird ein Durchgangs-FENSTER (Median und
10-/90-Perzentil ueber die Spots der Zone).

GRENZEN, DIE DAS VERFAHREN NICHT UEBERSCHREITEN DARF

- Die Vorhersagekarten liegen 12 h auseinander (+36/+48/+60), danach 24 h
  (+60/+84/+108). Eine auf die Minute interpolierte Zeit taeuscht Genauigkeit
  vor, die die Quelle nicht hat. Die Ausgabe rundet deshalb auf Stunden und
  weist die Stuetzweite je Durchgang mit aus.
- Die lineare Interpolation unterstellt gleichfoermige Verlagerung ueber das
  ganze Intervall. Bei 12 h ist das vertretbar, bei 24 h deutlich schwaecher.
- Zwei menschliche Analysen stimmen bei der exakten Frontlage nur zu 23-30 %
  ueberein (§2b). Der Anspruch ist "Nachmittag", nicht "14:20".

Run:
  python scripts/experiment_fronten_zeitachse.py --lauf 2026072700
  python scripts/experiment_fronten_zeitachse.py --lauf 2026072600 --typ kalt
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "data" / "_experiment_fronten"

# Verlagerung, die eine Front zwischen zwei Terminen plausibel zuruecklegt.
# Darunter ist die Richtung aus dem Rauschen nicht bestimmbar, darueber ist es
# nicht mehr dieselbe Front.
MIN_SHIFT_KMH = 3.0
MAX_SHIFT_KMH = 90.0

# Seitlicher Abstand quer zur Zugrichtung. OHNE DIESE SCHWELLE MELDET DAS
# VERFAHREN DURCHGAENGE, DIE ES NICHT GIBT: der naechste Punkt einer weit
# entfernten, langen Frontlinie rutscht an ihr entlang, das Vorzeichen der
# Laengsprojektion kippt — und die Front war nie in der Naehe. Gemessen am
# Lauf 27.07.: Kaltfront durchgehend 500-1700 km entfernt, das Verfahren
# meldete trotzdem Durchgaenge fuer alle vier Zonen.
#
# Physikalisch ist die Schwelle der Abstand, den die Front im Moment des
# Durchgangs seitlich noch hat: bei reiner Verlagerung bleibt er konstant,
# waehrend die Laengskomponente durch null geht. 100 km ist die Groessen-
# ordnung einer Zone und liegt unter der Streuung zweier menschlicher
# Frontanalysen (§2b) — feiner waere Scheingenauigkeit.
MAX_LATERAL_KM = 100.0

# Zwei Durchgaenge mit groesserem zeitlichem Abstand sind zwei Fronten, nicht
# einer. Ohne diese Trennung mittelt die Auswertung ueber zwei Ereignisse.
EVENT_GAP_H = 12.0

# Anteil der Zonen-Spots, ab dem von einem Durchgang QUER durch die Zone die
# Rede sein darf. Realfall 27.07.: eine Kaltfront streifte den noerdlichsten
# Spot des Alpennordhangs (1 von 327). Das ist ein echter Befund, aber keine
# Zonenaussage — ohne diese Unterscheidung wuerde ein Streifschuss im Text zu
# "Kaltfrontdurchgang am Alpennordhang".
MIN_ZONE_SHARE = 0.10

# Liegt der interpolierte Zeitpunkt sehr nah am Rand des Stuetzintervalls, war
# die Front zum Randtermin bereits praktisch am Ort — der wahre Durchgang kann
# dann VOR dem ersten bzw. NACH dem letzten Stuetzpunkt liegen. Solche Zeiten
# sind Randwerte, keine Messwerte.
EDGE_FRAC = 0.10

TYP_LABEL = {"kalt": "Kaltfront", "warm": "Warmfront",
             "okklusion": "Okklusion", "trog": "Trogachse"}


# ============================================================================
# Geometrie (aequidistante Naeherung, bei diesen Distanzen ausreichend)
# ============================================================================

def _to_km(lat, lon, lat0):
    """lat/lon -> lokale km-Koordinaten um lat0."""
    x = np.asarray(lon, float) * 111.32 * np.cos(np.radians(lat0))
    y = np.asarray(lat, float) * 110.57
    return x, y


def nearest_on_lines(px, py, lines_km):
    """Naechster Punkt auf einer Menge von Polylinien.

    Rueckgabe: (Abstand km, qx, qy) — oder (inf, nan, nan) ohne Linien.
    """
    best_d, best_q = np.inf, (np.nan, np.nan)
    for ax, ay in lines_km:
        if len(ax) < 2:
            continue
        # Segmentweise Projektion des Punktes auf die Strecke
        x1, y1, x2, y2 = ax[:-1], ay[:-1], ax[1:], ay[1:]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        L2 = np.where(L2 == 0, 1e-9, L2)
        t = np.clip(((px - x1) * dx + (py - y1) * dy) / L2, 0.0, 1.0)
        qx, qy = x1 + t * dx, y1 + t * dy
        d = np.hypot(px - qx, py - qy)
        k = int(np.argmin(d))
        if d[k] < best_d:
            best_d, best_q = float(d[k]), (float(qx[k]), float(qy[k]))
    return best_d, best_q[0], best_q[1]


# ============================================================================
# Daten
# ============================================================================

def load_zones() -> dict:
    """{zone_id: [(lat, lon), ...]} aus den echten Spots der App."""
    from engine.synoptic_context import build_spot_zone_map
    import spots as spots_mod
    zone_of = build_spot_zone_map()
    coords = {s["name"]: (s.get("latitude"), s.get("longitude"))
              for s in spots_mod.load_spots()}
    out: dict[str, list] = {}
    for name, zone in zone_of.items():
        la, lo = coords.get(name, (None, None))
        if la is None or lo is None:
            continue
        out.setdefault(zone, []).append((float(la), float(lo)))
    return out


ARCHIV = ROOT / "data" / "dwd_fronten_archiv"


def _load_geojson(p: Path, quelle: str):
    d = json.loads(p.read_text(encoding="utf-8"))
    g = d["properties"].get("gueltig")
    if not g:
        return None
    return {"gueltig": datetime.fromisoformat(g),
            "vorlauf_h": d["properties"].get("vorlauf_h"),
            "features": d["features"], "datei": p.name, "quelle": quelle}


def load_run(lauf: str, mit_analyse: bool = True) -> list[dict]:
    """Alle Vorlaufzeiten eines Laufs plus Handanalysen als Stuetzpunkte.

    OHNE die Analysen ist die Zeitachse fuer den Briefing-Vormittag blind
    (§1h Befund 1): die frueheste Vorhersagekarte des Laufs gilt fuer 12 UTC —
    ein Durchgang zwischen Mitternacht und Mittag laege vor dem ersten
    Intervall. Die 00-UTC-Handanalyse liefert genau den fehlenden fruehen
    Stuetzpunkt; die Vorhersagekarten desselben Laufs schliessen an.
    """
    run12 = lauf if len(lauf) == 12 else lauf + "00"
    out = []
    for folder in (OUT_DIR, ARCHIV / "vorhersage"):
        for p in sorted(folder.glob(f"dwd_fronten_{run12}_*.geojson")):
            k = _load_geojson(p, "FC")
            if k and not any(x["gueltig"] == k["gueltig"] for x in out):
                out.append(k)
    if mit_analyse and out:
        first_fc = min(k["gueltig"] for k in out)
        for p in sorted((ARCHIV / "analyse").glob("dwdc_*.geojson")):
            k = _load_geojson(p, "ANA")
            if k is None:
                continue
            # Nur Analysen VOR der ersten Vorhersagekarte und hoechstens 24 h
            # zurueck — aeltere sagen ueber das Briefing-Fenster nichts mehr.
            if not (timedelta(0) < first_fc - k["gueltig"] <= timedelta(hours=24)):
                continue
            if not any(x["gueltig"] == k["gueltig"] for x in out):
                out.append(k)
    return sorted(out, key=lambda c: c["gueltig"])


def lines_by_type(features, typ, lat0) -> list:
    return [_to_km([c[1] for c in f["geometry"]["coordinates"]],
                   [c[0] for c in f["geometry"]["coordinates"]], lat0)
            for f in features if f["properties"]["typ"] == typ]


# ============================================================================
# Durchgangszeit
# ============================================================================

def passages_for_point(lat, lon, karten, typ, lat0, max_lateral=MAX_LATERAL_KM):
    """Durchgaenge an einem Punkt: [(zeit, stuetzweite_h, seitlicher_abstand)]."""
    px, py = _to_km(lat, lon, lat0)
    px, py = float(px), float(py)

    track = []
    for k in karten:
        d, qx, qy = nearest_on_lines(px, py, lines_by_type(k["features"], typ, lat0))
        track.append((k["gueltig"], d, qx, qy))

    found = []
    for (t1, d1, q1x, q1y), (t2, d2, q2x, q2y) in zip(track, track[1:]):
        if not np.isfinite(d1) or not np.isfinite(d2):
            continue
        dt_h = (t2 - t1).total_seconds() / 3600.0
        mx, my = q2x - q1x, q2y - q1y
        shift = float(np.hypot(mx, my))
        speed = shift / dt_h if dt_h else 0.0
        if not (MIN_SHIFT_KMH <= speed <= MAX_SHIFT_KMH):
            continue                      # Richtung unbestimmbar oder andere Front
        mxn, myn = mx / shift, my / shift
        # Zerlegung in laengs (s) und quer (c) zur Zugrichtung.
        # positiv = Front steht noch bevor, negativ = durch
        s1 = (px - q1x) * mxn + (py - q1y) * myn
        s2 = (px - q2x) * mxn + (py - q2y) * myn
        c1 = abs((px - q1x) * myn - (py - q1y) * mxn)
        c2 = abs((px - q2x) * myn - (py - q2y) * mxn)
        if not (s1 > 0 >= s2):
            continue
        frac = s1 / (s1 - s2) if (s1 - s2) else 0.5
        c = c1 + (c2 - c1) * frac         # seitlicher Abstand im Moment des Durchgangs
        if c > max_lateral:
            continue                      # Front zieht vorbei, nicht darueber
        rand = frac < EDGE_FRAC or frac > (1.0 - EDGE_FRAC)
        found.append((t1 + timedelta(hours=frac * dt_h), dt_h, float(c), rand))
    return found


def cluster_events(rows: list) -> list:
    """Durchgaenge nach Zeit gruppieren — zwei Fronten sind zwei Ereignisse."""
    if not rows:
        return []
    rows = sorted(rows, key=lambda r: r[0])
    groups, cur = [], [rows[0]]
    for r in rows[1:]:
        if (r[0] - cur[-1][0]).total_seconds() / 3600.0 > EVENT_GAP_H:
            groups.append(cur)
            cur = []
        cur.append(r)
    groups.append(cur)
    return groups


def _synth(lon_points, lat_points, typ="kalt"):
    return {"type": "Feature", "properties": {"typ": typ},
            "geometry": {"type": "LineString",
                         "coordinates": [[lo, la] for lo, la
                                         in zip(lon_points, lat_points)]}}


def selftest() -> int:
    """Prueft die Zeitrechnung an synthetischen Fronten.

    Ohne das laesst sich das Verfahren nur an echten Frontlagen pruefen, und
    die gibt es nicht auf Bestellung. Fall 3 haelt einen bereits aufgetretenen
    Fehler fest: ohne Querabstands-Schwelle meldete das Verfahren Durchgaenge
    fuer eine Front, die 500-1700 km entfernt blieb.
    """
    t0 = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    lat0, ok = 46.78, True
    ZH = (46.78, 7.95)

    def karten(f1, f2, dt_h=12):
        return [{"gueltig": t0, "features": [f1], "vorlauf_h": 36},
                {"gueltig": t0 + timedelta(hours=dt_h), "features": [f2],
                 "vorlauf_h": 36 + dt_h}]

    # 1. Nord-Sued-Front zieht von 5 nach 11 Grad Ost. Der Punkt bei 7.95 Ost
    #    muss nach 12 h * (7.95-5)/(11-5) = 5.9 h erreicht sein.
    k = karten(_synth([5.0, 5.0], [40.0, 55.0]), _synth([11.0, 11.0], [40.0, 55.0]))
    got = passages_for_point(*ZH, k, "kalt", lat0)
    soll = t0 + timedelta(hours=12 * (7.95 - 5.0) / (11.0 - 5.0))
    if len(got) != 1 or abs((got[0][0] - soll).total_seconds()) > 1800:
        print(f"  FEHLER 1: erwartet {soll:%H:%M}, bekommen "
              f"{[f'{g[0]:%H:%M}' for g in got]}")
        ok = False
    else:
        print(f"  ok 1  Durchgang {got[0][0]:%H:%M} UTC "
              f"(erwartet {soll:%H:%M}), quer {got[0][2]:.0f} km")

    # 2. Dieselbe Front, aber weit noerdlich vorbei: kein Durchgang.
    k = karten(_synth([5.0, 5.0], [56.0, 66.0]), _synth([11.0, 11.0], [56.0, 66.0]))
    got = passages_for_point(*ZH, k, "kalt", lat0)
    if got:
        print(f"  FEHLER 2: Vorbeizug als Durchgang gemeldet ({got})")
        ok = False
    else:
        print("  ok 2  nordlich vorbeiziehende Front wird nicht gemeldet")

    # 3. Der reale Fehlalarm: lange, schraege Front weit westlich, zieht
    #    ostwaerts, erreicht uns aber nicht. Ohne Querabstands-Schwelle kippt
    #    die Laengsprojektion und meldete faelschlich einen Durchgang.
    k = karten(_synth([-30.0, -10.0], [40.0, 60.0]),
               _synth([-24.0, -4.0], [40.0, 60.0]))
    got = passages_for_point(*ZH, k, "kalt", lat0)
    if got:
        print(f"  FEHLER 3: entfernte Front als Durchgang gemeldet ({got})")
        ok = False
    else:
        print("  ok 3  entfernte Front wird nicht gemeldet (Regression)")

    # 4. Ereignis-Trennung: zwei Fronten im Abstand von Tagen sind zwei
    #    Ereignisse, nicht ein gemitteltes.
    rows = [(t0, 12.0, 5.0, False), (t0 + timedelta(hours=2), 12.0, 5.0, False),
            (t0 + timedelta(hours=40), 12.0, 5.0, False)]
    if len(cluster_events(rows)) != 2:
        print("  FEHLER 4: Ereignis-Trennung greift nicht")
        ok = False
    else:
        print("  ok 4  zwei Fronten bleiben zwei Ereignisse")

    print("Selbsttest bestanden" if ok else "SELBSTTEST FEHLGESCHLAGEN")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true",
                    help="Zeitrechnung an synthetischen Fronten pruefen")
    ap.add_argument("--lauf", help="Modelllauf YYYYMMDDHH")
    ap.add_argument("--typ", default=None, choices=sorted(TYP_LABEL),
                    help="nur ein Fronttyp (Vorgabe: alle)")
    ap.add_argument("--tz", default=None, help="Ausgabe-Zeitzone, "
                                               "Vorgabe: config.TIMEZONE")
    ap.add_argument("--max-seitlich-km", type=float, default=MAX_LATERAL_KM,
                    help="seitlicher Hoechstabstand im Moment des Durchgangs; "
                         "hoehere Werte melden auch vorbeiziehende Fronten")
    ap.add_argument("--ohne-analyse", action="store_true",
                    help="Handanalyse nicht als Stuetzpunkt verwenden "
                         "(laesst die Morgen-Luecke bewusst offen)")
    ap.add_argument("--json", dest="json_out",
                    help="abgeleitete Aussagen als JSON ablegen — DAS ist der "
                         "spaeter vergleichbare Teil, nicht die Linien")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.lauf:
        ap.error("--lauf oder --selftest angeben")

    karten = load_run(args.lauf, mit_analyse=not args.ohne_analyse)
    if len(karten) < 2:
        print(f"Zu wenige Karten fuer Lauf {args.lauf}. Erst einsammeln:\n"
              f"  python scripts/archive_dwd_fronten.py")
        return 2

    try:
        from zoneinfo import ZoneInfo
        import config
        tz = ZoneInfo(args.tz or config.TIMEZONE)
    except Exception:
        tz = timezone.utc

    print(f"Lauf {args.lauf} — {len(karten)} Stuetzpunkte "
          f"(ANA = Handanalyse, FC = Vorhersagekarte)")
    for k in karten:
        n = len(k["features"])
        print(f"  {k.get('quelle', 'FC'):<4} +{k['vorlauf_h']:03d} h  "
              f"gueltig {k['gueltig'].astimezone(tz):%a %d.%m %H:%M %Z}"
              f"  {n:>2} Abschnitte")
    spans = [(b["gueltig"] - a["gueltig"]).total_seconds() / 3600.0
             for a, b in zip(karten, karten[1:])]
    print(f"  Stuetzweite: {'/'.join(f'{s:.0f}' for s in spans)} h — "
          f"feiner kann die Aussage nicht werden")

    zones = load_zones()
    typen = [args.typ] if args.typ else sorted(TYP_LABEL)
    aussagen = []                          # fuer --json

    print(f"\n{'Zone':<22}{'Front':<11}{'Art':<9}{'Durchgang (Median)':<22}"
          f"{'Zonenfenster 10-90 %':<26}{'Spots':>7}{'seitl.':>8}")
    print("-" * 104)
    any_hit = False
    for zone, pts in sorted(zones.items()):
        lat0 = float(np.mean([p[0] for p in pts]))
        for typ in typen:
            rows = []
            for la, lo in pts:
                rows.extend(passages_for_point(la, lo, karten, typ, lat0,
                                               args.max_seitlich_km))
            for grp in cluster_events(rows):
                any_hit = True
                ts = np.array(sorted(r[0].timestamp() for r in grp))
                med = datetime.fromtimestamp(float(np.median(ts)), tz)
                lo_t = datetime.fromtimestamp(float(np.percentile(ts, 10)), tz)
                hi_t = datetime.fromtimestamp(float(np.percentile(ts, 90)), tz)
                share = len(grp) / len(pts)
                # Streifschuss vs. Durchgang: ein einzelner Randspot ist kein
                # Zonenereignis (Realfall 27.07., 1 von 327).
                art = "quert" if share >= MIN_ZONE_SHARE else "streift"
                rand = "  ~Rand" if all(r[3] for r in grp) else ""
                fenster = (f"{lo_t:%d.%m %H:%M} - {hi_t:%H:%M}"
                           if lo_t.date() == hi_t.date() else
                           f"{lo_t:%d.%m %H:%M} - {hi_t:%d.%m %H:%M}")
                stuetz = f"±{max(r[1] for r in grp)/2:.0f} h"
                print(f"{zone:<22}{TYP_LABEL[typ]:<11}{art:<9}"
                      f"{med:%a %d.%m %H:%M} {stuetz:<7}"
                      f"{fenster:<26}{len(grp):>4}/{len(pts):<5}"
                      f"{np.median([r[2] for r in grp]):>4.0f} km{rand}")
                aussagen.append({
                    "zone": zone, "typ": typ, "art": art,
                    "durchgang_median_utc": datetime.fromtimestamp(
                        float(np.median(ts)), timezone.utc).isoformat(),
                    "fenster_von_utc": datetime.fromtimestamp(
                        float(np.percentile(ts, 10)), timezone.utc).isoformat(),
                    "fenster_bis_utc": datetime.fromtimestamp(
                        float(np.percentile(ts, 90)), timezone.utc).isoformat(),
                    "spots_betroffen": len(grp), "spots_zone": len(pts),
                    "anteil": round(share, 3),
                    "seitlich_km": round(float(np.median([r[2] for r in grp])), 1),
                    "stuetzweite_h": max(r[1] for r in grp),
                    "randwert": all(r[3] for r in grp),
                })
    if not any_hit:
        print("  (kein Frontdurchgang in diesem Zeitraum — bei stabiler "
              "Hochdrucklage der Normalfall)")
    print("\nLesehilfe:")
    print("  quert/streift  ab " f"{MIN_ZONE_SHARE:.0%}"
          " betroffener Spots gilt es als Durchgang durch die Zone,")
    print("                 darunter als Streifschuss am Rand — keine "
          "Zonenaussage.")
    print("  Median         Durchgang am mittleren betroffenen Spot; das "
          "Zonenfenster zeigt,")
    print("                 wie lange die Front fuer die Zone braucht.")
    print("  ±              halbe Stuetzweite der Quelle (Unschaerfe der "
          "Interpolation).")
    print("  seitl.         Abstand der Front quer zur Zugrichtung beim "
          "Passieren.")
    print("  ~Rand          Zeitpunkt liegt am Rand des Stuetzintervalls — der "
          "wahre Durchgang")
    print("                 kann davor bzw. danach liegen, ausserhalb des "
          "Betrachtungsfensters.")

    if args.json_out:
        # Festhalten, WAS WIR WANN GESAGT HABEN. Die Linien allein reichen fuer
        # den spaeteren Abgleich nicht — verglichen wird die Aussage.
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "lauf": args.lauf,
            "erstellt_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "mit_analyse": not args.ohne_analyse,
            "max_seitlich_km": args.max_seitlich_km,
            "stuetzpunkte": [{"quelle": k.get("quelle", "FC"),
                              "vorlauf_h": k["vorlauf_h"],
                              "gueltig_utc": k["gueltig"].isoformat(),
                              "abschnitte": len(k["features"]),
                              "datei": k["datei"]} for k in karten],
            "stuetzweiten_h": spans,
            "aussagen": aussagen,
        }, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\n{len(aussagen)} Aussage(n) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
