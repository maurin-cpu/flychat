"""Fronten aus den DWD-Karten als Linien herausziehen — Analyse und Vorhersage.

Hintergrund: die eigene Berechnung ist ausserhalb der Alpen gut, ueber den
Alpen nachweislich unbrauchbar (PLAN_fronten_darstellung.md §1d). Die
DWD-Karten sind ueberall richtig, liegen aber nur als PNG vor. Dieses
Skript prueft, ob sich daraus Vektordaten gewinnen lassen.

Warum das entgegen der urspruenglichen Annahme geht: die Karten kodieren
Fronten in REINEN FARBEN, und sonst ist auf der Kartenflaeche nichts farbig
(gemessen: null gruen-dominante Pixel). Isobaren, Stationsmeldungen, Kuesten
und Beschriftung sind durchweg Grau. Die Trennung ist damit trivial statt
unmoeglich.

ZWEI KARTENPROFILE (--profil):

  analyse      Handanalyse der Ist-Lage, 4379 x 3269 px, 2.39 km/px.
               Kalt / Warm / Okklusion. Kein Orange auf dieser Karte
               (gemessen: null Pixel).
  vorhersage   ICON-Vorhersagekarte `ico_tkb_na`, 1280 x 910 px, 5.71 km/px.
               Zusaetzlich ORANGE TROGACHSEN — aber nur an manchen Terminen
               (gemessen 27.07.2026: auf 3 von 10 Karten). Vorlaufzeiten
               +36/+48/+60/+84/+108 h aus dem 00-UTC-Lauf; es gibt kein
               +12/+24. Fuer ein 06:00-Briefing heisst das: fuer HEUTE die
               +036 des GESTRIGEN Laufs nehmen.

Kette:
  1. Karte holen (LATEST oder ein bestimmter Lauf + Vorlauf)
  2. Farbmasken -> Kalt / Warm / Okklusion (/ Trog)
  3. Skelett der Linie, Symbol-Auswuechse (Dreiecke, Halbkreise) abschneiden
  4. Pixel -> lat/lon ueber die je Profil kalibrierte Polarstereographie
  5. GeoJSON

Die Kalibrierungen wurden einmalig gegen eine Referenz-Landmaske gefittet
(Hoehen-API, dieselbe wie im Frontexperiment): 98.2 % Uebereinstimmung der
Land-See-Maske bei der Analyse, 98.66 % bei der Vorhersage. Das Kartenlayout
ist fix, deshalb gelten sie fuer jede Karte — muessen aber ueberwacht werden
(siehe `check_projection`; faellt der Wert unter die Profilschwelle, bricht
das Skript ab, statt falsche Linien zu liefern).

Die Laengenschwellen stehen GEOGRAFISCH in km, nicht in Pixeln: die beiden
Karten haben um den Faktor 2.4 verschiedene Massstaebe, in Pixeln gesetzte
Schwellen wuerden auf der groeberen Karte viel zu wenig wegfiltern.

Lizenz der Quelle: GeoNutzV. Nutzung frei MIT Quellenangabe
("© Deutscher Wetterdienst"), bei Veraenderung zusaetzlich ein
Aenderungshinweis — eine Vektorisierung ist eine Veraenderung.

Run:
  python scripts/experiment_dwd_fronten_extraktion.py
  python scripts/experiment_dwd_fronten_extraktion.py --profil vorhersage --step 36
  python scripts/experiment_dwd_fronten_extraktion.py --profil vorhersage \
         --lauf 2026072600 --alle-steps --overlay
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "data" / "_experiment_fronten"

CHART_URL = ("https://opendata.dwd.de/weather/charts/analysis/"
             "Z__C_EDZW_LATEST_tka01%2Cana_bwkman_dwdc_O_000000_000000_"
             "LATEST_WV12.png")

FORECAST_DIR = ("https://opendata.dwd.de/weather/charts/forecasts/"
                "icon/global/na/")
FORECAST_LATEST = (FORECAST_DIR + "Z__C_EDZW_LATEST_nwv01%2Cico_tkb_na_N_"
                   "{step:06d}_000000_LATEST_WV12.png")
FORECAST_STEPS = (36, 48, 60, 84, 108)


# ============================================================================
# Kartenprofile
# ============================================================================

def _land_sea_analyse(rgb) -> np.ndarray:
    """0 = See, 1 = Land, -1 = unklar (Isobaren, Text, Fronten)."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    sea = (abs(r - 133) < 14) & (abs(g - 146) < 14) & (abs(b - 163) < 14)
    grey = (abs(r - g) < 12) & (abs(g - b) < 12)
    return np.where(sea, 0, np.where(grey & (r >= 165), 1, -1)).astype(np.int8)


def _land_sea_tkb(rgb) -> np.ndarray:
    """Vorhersagekarte: Land exakt (222,222,222), See reines Weiss.

    Sauberer trennbar als bei der Analysekarte — dort ist die See eingefaerbt
    und das Grau der Landflaeche teilt sich den Bereich mit Beschriftung.
    """
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    grey = (abs(r - g) < 8) & (abs(g - b) < 8)
    land = grey & (abs(r - 222) < 8)
    sea = grey & (r > 246)
    return np.where(sea, 0, np.where(land, 1, -1)).astype(np.int8)


FRONT_COLORS = {           # exakt so im PNG, kein Antialiasing-Rand noetig
    "kalt":      lambda r, g, b: (b > 180) & (r < 90) & (g < 90),
    "warm":      lambda r, g, b: (r > 180) & (g < 90) & (b < 90),
    "okklusion": lambda r, g, b: (r > 200) & (b > 200) & (g > 90) & (g < 190),
}

# Trogachse/Konvergenzlinie, nur auf der Vorhersagekarte. Zwei reine Toene
# (255,191,114) hell und (191,114,0) dunkel — der DWD zeichnet die Linie
# zweifarbig. Kein Frontsymbol, sondern Querstriche.
TROG_COLOR = {
    "trog": lambda r, g, b: (r > 150) & (g > 60) & (g < 200) & (b < 120)
                            & ((r - b) > 90) & ((g - b) > 20),
}

PROFILES = {
    # Einmalig kalibrierte Polarstereographie (Nordpol ausserhalb bzw. im Bild).
    #   rho = S * tan(45 - lat/2);  alpha = THETA - lon
    #   x = X0 + rho*cos(alpha);    y = Y0 + rho*sin(alpha)
    # THETA ~ 100 Grad heisst: Zentralmeridian 10 Ost zeigt senkrecht nach unten.
    "analyse": {
        "proj": {"x0": 2960.8, "y0": 339.7, "s": 4625.0, "theta_deg": 100.0},
        "land_sea": _land_sea_analyse,
        "guard_min": 0.93,           # gemessen 98.2 %
        "colors": dict(FRONT_COLORS),
        "ignore": [],                # Kartenflaeche fuellt das Bild
        "quelle": "Deutscher Wetterdienst, Bodenanalyse (bwkman)",
    },
    "vorhersage": {
        "proj": {"x0": 814.1, "y0": -181.2, "s": 1934.0, "theta_deg": 100.12},
        "land_sea": _land_sea_tkb,
        "guard_min": 0.93,           # gemessen 98.66 %
        "colors": {**FRONT_COLORS, **TROG_COLOR},
        # Legendenkasten, senkrechter Beschriftungsstreifen, DWD-Logo. Der
        # Legendentext ist orange — ohne diese Sperre waere er eine Trogachse.
        "ignore": [(810, 910, 0, 270), (520, 790, 0, 40), (790, 910, 1150, 1280)],
        # Invariante zur Sperrzone (§1h Befund 5): die orange Legendenfarbe muss
        # INNERHALB der Sperrzone liegen. Schwellen = halbe gemessene Untergrenze
        # ueber zehn Karten vom 26./27.07. (Kasten 619-651 Px, Streifen 65-71 Px).
        "groesse": (910, 1280),
        "legende": [((810, 910, 0, 270), 300), ((520, 790, 0, 40), 30)],
        "quelle": "Deutscher Wetterdienst, ICON-Vorhersagekarte (tkb)",
    },
}

# Aktives Profil; wird in main() gesetzt, damit die Projektionsfunktionen
# unveraendert bleiben koennen.
PROJ = dict(PROFILES["analyse"]["proj"])
_ACTIVE = "analyse"

# Schwellen GEOGRAFISCH, nicht in Pixeln — siehe Modul-Docstring. Die Werte
# sind die auf der Analysekarte kalibrierten Pixelschwellen (70/120/60 px bei
# 2.39 km/px), einmal in km umgerechnet.
MIN_BRANCH_KM = 167.0      # kuerzere Skelettaeste = Frontsymbol, kein Linienteil
MIN_LINE_KM = 287.0        # kuerzere Reste sind Bildrauschen
MIN_SEG_KM = 143.0         # kuerzerer Typwechsel = Symbol, nicht Front
CLASSIFY_RADIUS_KM = 21.5  # Umkreis fuer die Farbzuordnung je Linienpunkt
CLOSING_KM = 12.0          # Lueckenschluss vor der Skelettierung


# ============================================================================
# Projektion
# ============================================================================

def lonlat_to_px(lat, lon):
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    rho = PROJ["s"] * np.tan(np.radians(45.0 - lat / 2.0))
    al = np.radians(PROJ["theta_deg"]) - np.radians(lon)
    return PROJ["x0"] + rho * np.cos(al), PROJ["y0"] + rho * np.sin(al)


def px_to_lonlat(x, y):
    dx = np.asarray(x, float) - PROJ["x0"]
    dy = np.asarray(y, float) - PROJ["y0"]
    rho = np.hypot(dx, dy)
    lat = 90.0 - 2.0 * np.degrees(np.arctan(rho / PROJ["s"]))
    lon = PROJ["theta_deg"] - np.degrees(np.arctan2(dy, dx))
    return (lon + 180.0) % 360.0 - 180.0, lat


def km_per_px(lat: float = 47.0) -> float:
    """Massstab des aktiven Profils an einer Breite — abgeleitet statt gesetzt.

    Die Polarstereographie ist nicht flaechentreu; der Wert waechst polwaerts.
    47 Grad ist die Breite unseres Gebiets, und die Schwellen betreffen
    Linienlaengen dort, nicht am Pol.
    """
    x1, y1 = lonlat_to_px(lat, 0.0)
    x2, y2 = lonlat_to_px(lat, 1.0)
    d_px = float(np.hypot(float(x2) - float(x1), float(y2) - float(y1)))
    return (111.32 * np.cos(np.radians(lat))) / d_px


def _px(km: float, minimum: int = 1) -> int:
    """Geografische Schwelle -> Pixelschwelle des aktiven Profils."""
    return max(minimum, int(round(km / km_per_px())))


def _ignore_mask(shape) -> np.ndarray:
    """True = auswertbare Kartenflaeche. Blendet Legende, Beschriftungsstreifen
    und Logo aus — der Legendentext der Vorhersagekarte ist orange und waere
    sonst eine Trogachse."""
    m = np.ones(shape[:2], bool)
    for y0, y1, x0, x1 in PROFILES[_ACTIVE]["ignore"]:
        m[y0:y1, x0:x1] = False
    return m


def check_projection(rgb) -> float:
    """Waechter gegen ein stilles Brechen: stimmt die Land-See-Maske der Karte
    noch mit der Referenz ueberein? Aendert der DWD Layout oder Projektion,
    faellt dieser Wert ab, statt dass falsche Linien ausgeliefert werden."""
    ref = OUT_DIR / "ref_landmask.npz"
    if not ref.exists():
        return float("nan")
    z = np.load(ref)
    la, lo = np.meshgrid(z["lats"], z["lons"], indexing="ij")
    land_ref = (z["elev"] > 1).ravel()
    x, y = lonlat_to_px(la.ravel(), lo.ravel())
    xi, yi = np.rint(x).astype(int), np.rint(y).astype(int)
    h, w = rgb.shape[:2]
    ok = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
    keep = _ignore_mask(rgb.shape)
    cls = PROFILES[_ACTIVE]["land_sea"](rgb)[yi[ok], xi[ok]]
    cls = np.where(keep[yi[ok], xi[ok]], cls, -1)
    v = cls >= 0
    return float((cls[v] == land_ref[ok][v]).mean()) if v.sum() else float("nan")


def check_sperrzone(rgb) -> list[str]:
    """Blindstelle des Projektions-Waechters schliessen (§1h Befund 5).

    Der Legendentext der Vorhersagekarte ist orange — dieselbe Farbe wie die
    Trogachse. Er liegt in der Sperrzone und wird deshalb nicht ausgewertet.
    Verschiebt der DWD den Legendenkasten, bleibt die Land-See-Maske perfekt,
    der Projektions-Waechter merkt also NICHTS — aber der orange Text steht
    ploetzlich auf der Kartenflaeche und wird als Trogachse extrahiert.

    Die Invariante dreht die Pruefung um: nicht "ist die Karte richtig", sondern
    "liegt die erwartete Legendenfarbe noch dort, wo wir sie wegblenden". Ist
    der Kasten leer, ist die Legende woanders — und damit im Auswertebereich.

    Rueckgabe: Liste der Verstoesse, leer = in Ordnung.
    """
    p = PROFILES[_ACTIVE]
    erwartet = p.get("legende") or []
    if not erwartet:
        return []
    fehler = []
    soll = p.get("groesse")
    if soll and rgb.shape[:2] != tuple(soll):
        # Die Sperrzonen sind Pixelkoordinaten; bei anderer Bildgroesse zeigen
        # sie ins Leere und jede weitere Zaehlung waere sinnlos.
        return [f"LEGENDE: Kartengroesse {rgb.shape[1]}x{rgb.shape[0]} statt "
                f"{soll[1]}x{soll[0]} — Sperrzonen passen nicht mehr"]
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    orange = TROG_COLOR["trog"](r, g, b)
    for (y0, y1, x0, x1), minimum in erwartet:
        n = int(orange[y0:y1, x0:x1].sum())
        if n < minimum:
            fehler.append(f"LEGENDE: nur {n} orange Pixel in der Sperrzone "
                          f"({y0}:{y1},{x0}:{x1}), erwartet >= {minimum} — "
                          f"Legende verschoben, der Text landet sonst als "
                          f"Trogachse in der Auswertung")
    return fehler


# ============================================================================
# Skelett (Zhang-Suen) und Linienverfolgung
# ============================================================================

def thin(mask: np.ndarray) -> np.ndarray:
    """Zhang-Suen: haelt die Linie auf einem Pixel Breite zusammenhaengend."""
    img = np.pad(mask.astype(np.uint8), 1)
    while True:
        removed = False
        for step in (0, 1):
            p = [np.roll(np.roll(img, dy, 0), dx, 1) for dy, dx in
                 ((-1, 0), (-1, 1), (0, 1), (1, 1),
                  (1, 0), (1, -1), (0, -1), (-1, -1))]
            n = sum(int_ for int_ in p)
            seq = p + [p[0]]
            trans = sum(((seq[i] == 0) & (seq[i + 1] == 1)).astype(np.uint8)
                        for i in range(8))
            if step == 0:
                cond = ((p[0] * p[2] * p[4] == 0) & (p[2] * p[4] * p[6] == 0))
            else:
                cond = ((p[0] * p[2] * p[6] == 0) & (p[0] * p[4] * p[6] == 0))
            drop = (img == 1) & (n >= 2) & (n <= 6) & (trans == 1) & cond
            if drop.any():
                img[drop] = 0
                removed = True
        if not removed:
            break
    return img[1:-1, 1:-1].astype(bool)


_NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def _neighbours(pts: set):
    return {p: [(p[0] + dy, p[1] + dx) for dy, dx in _NB
                if (p[0] + dy, p[1] + dx) in pts] for p in pts}


def _bfs(start, nb, pts):
    """Breitensuche im Skelettgraphen: Entfernungen und Vorgaenger."""
    dist, parent, queue = {start: 0}, {start: None}, [start]
    while queue:
        nxt = []
        for p in queue:
            for q in nb[p]:
                if q not in dist:
                    dist[q] = dist[p] + 1
                    parent[q] = p
                    nxt.append(q)
        queue = nxt
    far = max(dist, key=dist.get)
    return far, dist, parent


def spines(pts: set, min_line: int):
    """Laengsachsen einer Skelettkomponente, laengste zuerst.

    Robuster als Astbeschnitt: Zhang-Suen hinterlaesst Treppenartefakte, an
    denen ein einfacher Graphlauf staendig abbricht (gemessen: 2563 Knoten vom
    Grad 3, 1352 vom Grad 4). Die doppelte Breitensuche laeuft da hindurch —
    sie sucht schlicht die zwei am weitesten auseinander liegenden Punkte und
    nimmt den Weg dazwischen. Die Symbol-Auswuechse sind kuerzere Seitenwege
    und fallen damit von selbst heraus.

    Danach wird die gefundene Achse entfernt und der Rest erneut geprueft —
    so ueberlebt am Okklusionspunkt auch der dritte Arm, statt verloren zu
    gehen.
    """
    out, todo = [], [set(pts)]
    while todo:
        comp = todo.pop()
        if len(comp) < min_line:
            continue
        nb = _neighbours(comp)
        seed = next(iter(comp))
        a, _, _ = _bfs(seed, nb, comp)
        b, _, parent = _bfs(a, nb, comp)
        path, cur = [], b
        while cur is not None:
            path.append(cur)
            cur = parent[cur]
        if len(path) < min_line:
            continue
        out.append(np.array(path))
        rest = comp - set(path)
        if rest:                       # Reststuecke als eigene Komponenten
            seen = set()
            for p in rest:
                if p in seen:
                    continue
                stack, grp = [p], set()
                while stack:
                    q = stack.pop()
                    if q in grp:
                        continue
                    grp.add(q)
                    stack.extend(n for n in _NB_of(q) if n in rest and n not in grp)
                seen |= grp
                todo.append(grp)
    return sorted(out, key=len, reverse=True)


def _NB_of(p):
    return [(p[0] + dy, p[1] + dx) for dy, dx in _NB]


def trace_lines(skel: np.ndarray, min_branch=None, min_line=None):
    """Skelett -> Polylinien ueber die Laengsachse je Komponente."""
    min_branch = _px(MIN_BRANCH_KM) if min_branch is None else min_branch
    min_line = _px(MIN_LINE_KM) if min_line is None else min_line
    from scipy.ndimage import label as _label
    lab, n = _label(skel, np.ones((3, 3)))
    lines = []
    for k in range(1, n + 1):
        pts = set(map(tuple, np.argwhere(lab == k)))
        if len(pts) < min_line:
            continue
        lines.extend(spines(pts, min_line))
    return sorted(lines, key=len, reverse=True)


def _trace_lines_old(skel, min_branch=70, min_line=120):
    """Erste Fassung (Astbeschnitt) — zerschnitt die Linien an jedem Symbol.

    Bleibt als Beleg stehen, warum die Laengsachse noetig war. Die Pixelwerte
    sind die der Analysekarte; die Funktion wird nicht mehr aufgerufen.
    """
    pts = set(map(tuple, np.argwhere(skel)))
    for _ in range(6):                      # mehrfach, Aeste koennen gestaffelt sein
        nb = _neighbours(pts)
        drop = set()
        for e in [p for p, q in nb.items() if len(q) == 1]:
            path, prev, cur, at_junction = [e], None, e, False
            while len(path) <= min_branch:
                cand = [q for q in nb[cur] if q != prev]
                if len(cand) != 1:
                    break
                nxt = cand[0]
                if len(nb[nxt]) > 2:
                    at_junction = True      # Kreuzung NICHT mitloeschen, sonst
                    break                   # zerschneidet jedes Symbol die Linie
                prev, cur = cur, nxt
                path.append(cur)
            if at_junction and len(path) <= min_branch:
                drop.update(path)
        if not drop:
            break
        pts -= drop

    nb = _neighbours(pts)
    lines, visited = [], set()

    def walk(start):
        path, prev, cur = [start], None, start
        while True:
            cand = [q for q in nb[cur] if q != prev and q not in visited]
            if len(cand) != 1:
                break
            prev, cur = cur, cand[0]
            path.append(cur)
        return path

    for s in [p for p, q in nb.items() if len(q) == 1]:
        if s in visited:
            continue
        path = walk(s)
        visited.update(path)
        if len(path) >= min_line:
            lines.append(np.array(path))
    for s in sorted(pts - visited):         # geschlossene Ringe ohne Endpunkt
        if s in visited:
            continue
        path = walk(s)
        visited.update(path)
        if len(path) >= min_line:
            lines.append(np.array(path))
    return lines


# ============================================================================
# Hauptlauf
# ============================================================================

def classify(line_px, masks, radius=None):
    """Fronttyp je Linienpunkt aus der Originalfarbe in der Umgebung.

    Wichtig fuer stationaere Fronten: die zeichnet der DWD als EINE Linie mit
    abwechselnd roten und blauen Abschnitten. Deshalb wird nicht die ganze
    Linie eingefaerbt, sondern jeder Punkt einzeln bestimmt.
    """
    radius = _px(CLASSIFY_RADIUS_KM, minimum=3) if radius is None else radius
    out = []
    h, w = next(iter(masks.values())).shape
    for j, i in line_px:
        best, bn = "unbekannt", 0
        for name, m in masks.items():
            n = m[max(0, j - radius):j + radius + 1,
                  max(0, i - radius):i + radius + 1].sum()
            if n > bn:
                best, bn = name, n
        out.append(best)
    return out


def _smooth_types(types, win=15):
    """Mehrheitsfilter gegen Ausreisser: an einem Symbol dominiert kurzzeitig
    die Symbolfarbe, das ist kein Typwechsel."""
    out = []
    for k in range(len(types)):
        w = types[max(0, k - win):k + win + 1]
        out.append(max(set(w), key=w.count))
    return out


def _type_runs(types, min_len):
    """Zusammenhaengende Abschnitte gleichen Typs; zu kurze werden dem
    Nachbarabschnitt zugeschlagen statt als eigene Front ausgegeben."""
    runs, start = [], 0
    for k in range(1, len(types) + 1):
        if k == len(types) or types[k] != types[start]:
            runs.append([start, k, types[start]])
            start = k
    merged = []
    for a, b, t in runs:
        if merged and (b - a) < min_len:
            merged[-1][1] = b
        elif merged and merged[-1][2] == t:
            merged[-1][1] = b
        else:
            merged.append([a, b, t])
    return [(a, b, t) for a, b, t in merged if (b - a) >= min_len]


def _seg_km(seg) -> float:
    lon, lat = px_to_lonlat(seg[:, 1], seg[:, 0])
    p1, p2 = np.radians(lat[:-1]), np.radians(lat[1:])
    dl = np.radians(lon[1:] - lon[:-1])
    d = np.sin(p1) * np.sin(p2) + np.cos(p1) * np.cos(p2) * np.cos(dl)
    return float(6371.0 * np.arccos(np.clip(d, -1, 1)).sum())


def forecast_url(step: int, lauf: str | None) -> tuple[str, str]:
    """URL der Vorhersagekarte. `lauf` = None/'latest' oder 'YYYYMMDDHH'.

    Der Dateiname traegt einen Erzeugungszeitstempel, der nicht vorhersagbar
    ist — deshalb wird fuer einen bestimmten Lauf das Verzeichnis gelistet
    statt die URL zusammengebaut.
    """
    if not lauf or lauf.lower() == "latest":
        return FORECAST_LATEST.format(step=step), "LATEST"
    run12 = lauf if len(lauf) == 12 else lauf + "00"
    html = requests.get(FORECAST_DIR, timeout=60).text
    pat = re.compile(r'href="([^"]*ico_tkb_na_N_%06d_\d{6}_%s_WV12\.png)"'
                     % (step, run12))
    m = pat.search(html)
    if not m:
        raise SystemExit(f"Keine tkb-Karte fuer Lauf {run12} +{step:03d} h. "
                         f"Der DWD haelt nur rund zwei Tage vor.")
    return FORECAST_DIR + m.group(1), run12


def fetch_chart(profil: str, step: int, lauf: str | None, png: str | None):
    """Karte holen (oder lokale Datei nehmen) und beschreiben."""
    from PIL import Image
    if png:
        return Image.open(png).convert("RGB"), {"quelle_url": png, "lauf": None,
                                                "vorlauf_h": None, "gueltig": None}
    if profil == "analyse":
        url, cache, meta = CHART_URL, OUT_DIR / "dwd_latest.png", {
            "quelle_url": CHART_URL, "lauf": "LATEST",
            "vorlauf_h": 0, "gueltig": None}
    else:
        url, run12 = forecast_url(step, lauf)
        gueltig = None
        if run12 != "LATEST":
            t0 = datetime.strptime(run12, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
            gueltig = (t0 + timedelta(hours=step)).isoformat()
        cache = OUT_DIR / f"tkb_{run12}_{step}.png"
        meta = {"quelle_url": url, "lauf": run12, "vorlauf_h": step,
                "gueltig": gueltig}
    # Datierte Karten sind unveraenderlich und werden zwischengespeichert.
    # LATEST wechselt — die muss jedes Mal neu geholt werden.
    if meta["lauf"] in (None, "LATEST") or not cache.exists():
        r = requests.get(url, timeout=90)
        r.raise_for_status()
        cache.write_bytes(r.content)
    return Image.open(cache).convert("RGB"), meta


def write_overlay(img, feats, path: Path) -> None:
    """Kontrollbild: extrahierte Linien in Gruen ueber die Karte.

    Gruen, weil auf beiden Karten gemessen null gruen-dominante Pixel liegen —
    was im Kontrollbild gruen ist, kommt sicher von uns.
    """
    a = np.array(img).astype(np.uint8).copy()
    h, w = a.shape[:2]
    for f in feats:
        for lon, lat in f["geometry"]["coordinates"]:
            x, y = lonlat_to_px(lat, lon)
            xi, yi = int(round(float(x))), int(round(float(y)))
            if 0 <= xi < w and 0 <= yi < h:
                a[max(0, yi - 2):yi + 3, max(0, xi - 2):xi + 3] = (0, 200, 0)
    from PIL import Image
    Image.fromarray(a).save(path)


def extract(img, meta: dict, simplify_km: float, verbose: bool = True) -> list:
    """Eine Karte -> Liste von GeoJSON-Features."""
    rgb = np.array(img).astype(int)
    if verbose:
        print(f"Karte {img.size[0]} x {img.size[1]}, "
              f"{km_per_px():.2f} km/px bei 47N")

    agree = check_projection(rgb)
    if verbose:
        print(f"Projektions-Waechter: Land-See-Uebereinstimmung {agree*100:.1f} %"
              if agree == agree else
              "Projektions-Waechter: keine Referenz vorhanden")
    guard = PROFILES[_ACTIVE]["guard_min"]
    if agree == agree and agree < guard:
        raise SystemExit(f"  ABBRUCH: Layout passt nicht mehr zur Kalibrierung "
                         f"({agree*100:.1f} % < {guard*100:.0f} %).")
    verstoesse = check_sperrzone(rgb)
    if verstoesse:
        # Abbruch statt Weitermachen: der Fehler erzeugt keine fehlende, sondern
        # eine ERFUNDENE Front — teurer als eine leere Ebene.
        raise SystemExit("  ABBRUCH: " + " | ".join(verstoesse))
    if verbose and PROFILES[_ACTIVE].get("legende"):
        print("Legenden-Invariante: Sperrzone traegt die Legendenfarbe")

    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    keep = _ignore_mask(rgb.shape)
    masks = {k: f(r, g, b) & keep for k, f in PROFILES[_ACTIVE]["colors"].items()}
    if verbose:
        for k, m in masks.items():
            print(f"  {k:<10} {int(m.sum()):>7} Pixel")

    union = np.zeros(r.shape, bool)
    for m in masks.values():
        union |= m
    if not union.any():
        if verbose:
            print("  keine Frontfarben auf der Karte")
        return []
    from scipy.ndimage import binary_closing
    c = _px(CLOSING_KM, minimum=3)
    union = binary_closing(union, np.ones((c, c)))

    ys, xs = np.where(union)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    if verbose:
        print(f"Skelettierung im Ausschnitt {x1-x0} x {y1-y0} ...")
    skel = np.zeros(r.shape, bool)
    skel[y0:y1, x0:x1] = thin(union[y0:y1, x0:x1])
    lines = trace_lines(skel)
    if verbose:
        print(f"  {int(skel.sum())} Skelettpunkte, {len(lines)} Linien")

    try:
        from shapely.geometry import LineString
    except ImportError:
        LineString = None

    feats = []
    for ln in lines:
        types = _smooth_types(classify(ln, masks))
        # Nach Typ zerlegen: eine gezeichnete Linie wechselt unterwegs zwischen
        # kalt und warm (so zeichnet der DWD Stationaerfronten und die Kette
        # Warmfront-Okklusion-Kaltfront). Ein Mehrheitstyp pro Linie waere
        # genau die Information, auf die es ankommt, weggemittelt.
        for a_, b_, typ in _type_runs(types, min_len=_px(MIN_SEG_KM)):
            seg = ln[a_:b_]
            lon, lat = px_to_lonlat(seg[:, 1], seg[:, 0])
            coords = list(zip(np.round(lon, 4), np.round(lat, 4)))
            if LineString is not None and simplify_km > 0 and len(coords) > 2:
                coords = list(LineString(coords).simplify(simplify_km / 111.0).coords)
            if len(coords) < 2:
                continue
            feats.append({
                "type": "Feature",
                "geometry": {"type": "LineString",
                             "coordinates": [[float(p), float(q)] for p, q in coords]},
                "properties": {
                    "typ": typ,
                    "laenge_km": round(float(_seg_km(seg)), 1),
                    "punkte": len(coords),
                    "quelle": PROFILES[_ACTIVE]["quelle"],
                    "hinweis": "aus der DWD-Karte vektorisiert (veraendert)",
                    **{k: v for k, v in meta.items() if v is not None},
                }})
    return feats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profil", choices=sorted(PROFILES), default="analyse")
    ap.add_argument("--png", help="lokale Karte statt Download")
    ap.add_argument("--lauf", help="Modelllauf YYYYMMDDHH (nur Vorhersage), "
                                   "Vorgabe: LATEST")
    ap.add_argument("--step", type=int, default=36,
                    help=f"Vorlaufzeit in Stunden {FORECAST_STEPS}")
    ap.add_argument("--alle-steps", action="store_true",
                    help="alle Vorlaufzeiten des Laufs nacheinander")
    ap.add_argument("--out", help="Zieldatei (Vorgabe: nach Profil und Lauf)")
    ap.add_argument("--overlay", action="store_true",
                    help="Kontrollbild mit den extrahierten Linien schreiben")
    ap.add_argument("--simplify-km", type=float, default=15.0)
    args = ap.parse_args()

    global PROJ, _ACTIVE
    _ACTIVE = args.profil
    PROJ = dict(PROFILES[_ACTIVE]["proj"])
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    steps = list(FORECAST_STEPS) if (args.alle_steps and args.profil == "vorhersage") \
        else [args.step]
    rc, summary = 0, []

    for step in steps:
        try:
            img, meta = fetch_chart(args.profil, step, args.lauf, args.png)
        except SystemExit as e:
            if len(steps) == 1:
                raise
            # Der DWD publiziert die spaeten Steps (+084/+108) einige Minuten
            # nach den fruehen. Ein fehlender Step ist darum kein Ketten-
            # ausfall: ueberspringen, der naechste Archivlauf zieht ihn nach.
            print(f"\n=== {args.profil} {args.lauf} +{step:03d} h ===")
            print(f"  uebersprungen: {e}")
            continue
        tag = (f"{args.profil} {meta.get('lauf')} +{step:03d} h"
               if args.profil == "vorhersage" else f"{args.profil} LATEST")
        print(f"\n=== {tag} ===")
        if meta.get("gueltig"):
            print(f"gueltig fuer {meta['gueltig']}")
        feats = extract(img, meta, args.simplify_km)

        if args.out and len(steps) == 1:
            out = Path(args.out)
        elif args.profil == "vorhersage":
            out = OUT_DIR / f"dwd_fronten_{meta.get('lauf')}_{step:03d}.geojson"
        else:
            out = OUT_DIR / "dwd_fronten.geojson"
        gj = {"type": "FeatureCollection", "features": feats,
              "properties": {"lizenz": "GeoNutzV", "profil": args.profil,
                             **{k: v for k, v in meta.items() if v is not None},
                             "copyright": "© Deutscher Wetterdienst, "
                                          "vektorisiert und damit veraendert"}}
        out.write_text(json.dumps(gj, indent=1), encoding="utf-8")
        print(f"{len(feats)} Abschnitte -> {out.name}")
        for f in sorted(feats, key=lambda f: -f["properties"]["laenge_km"]):
            c, pr = f["geometry"]["coordinates"], f["properties"]
            print(f"  {pr['typ']:<10} {pr['laenge_km']:>7.0f} km  "
                  f"{c[0][0]:7.2f},{c[0][1]:6.2f}  bis {c[-1][0]:7.2f},{c[-1][1]:6.2f}")
        if args.overlay:
            ov = out.with_name(out.stem + "_overlay.png")
            write_overlay(img, feats, ov)
            print(f"  Kontrollbild -> {ov.name}")
        summary.append((tag, len(feats),
                        sum(f["properties"]["laenge_km"] for f in feats)))

    if len(summary) > 1:
        print("\nUebersicht:")
        for tag, n, km in summary:
            print(f"  {tag:<32} {n:>3} Abschnitte  {km:>7.0f} km")
    if not summary:
        # Erst wenn KEIN Step eine Karte hatte, ist die Quelle wirklich weg.
        print(f"Keine einzige tkb-Karte fuer Lauf {args.lauf} gefunden.")
        return 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
