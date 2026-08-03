"""Ensemble-basierte Gewitterwahrscheinlichkeit (ICON-CH2-EPS, 21 Member).

WARUM
-----
Gewitter kamen bisher ausschliesslich aus EINEM deterministischen Lauf: der
Zelle musste zufaellig genau auf einem Referenzpunkt zuenden, sonst existierte
sie fuer uns nicht. Fuer Konvektion ist das die unzuverlaessigste verfuegbare
Information.

Belegfall Engelberg (46.82/8.40), Sonntag 02.08.2026, Fenster 11-20 Uhr,
gemessen am 31.07.2026:
  * ICON-CH2 deterministisch: weather_code 0 durchgehend, CAPE max 430, 0.0 mm
  * ICON-CH2-EPS: 3 von 21 Membern mit Code 95, 4 mit >= 1 mm/h,
    CAPE median 720 / max 1570
Auch ICON-D2, ICON-EU, ECMWF und GFS zuenden deterministisch keine Zelle.
MeteoSchweiz zeigte fuer diesen Tag Gewitter — das Ensemble sieht es, der
Einzellauf nicht.

WAS DAS IST — UND WAS NICHT
---------------------------
Der Member-Anteil ist eine WEICHE Warnstufe ("Gewitterwahrscheinlichkeit X %,
Schwerpunkt HH-HH"). Er ist ausdruecklich KEIN Fliegbarkeits-Gate und setzt
nie ein No-Go. Das harte Gate bleibt der deterministische weather_code
(95/96/99) wie bisher.

Die Schwellen in config.ENSEMBLE_THUNDER_* sind NICHT kalibriert. Sie sind der
im Auftrag genannte Startpunkt (20-30 % der Member) und muessen vor einem
Livegang gegen MeteoSchweiz-Stationsmessungen geprueft werden — niemals gegen
Modelldaten (siehe scripts/validate_thunder_vs_stations.py).

API-EIGENHEIT
-------------
Der Ensemble-Endpunkt laeuft NUR ohne unseren Kunden-API-Key. Mit Key
antwortet er "requires the API Professional or Enterprise plan" (HTTP 403).
Darum wird hier bewusst NICHT config.with_api_key() aufgerufen. Damit gelten
die freien Rate-Limits — die Punktzahl pro Aufruf niedrig halten.
"""

from __future__ import annotations

import re
import time

import requests

import config

ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
ENSEMBLE_TIMEOUT = 90

# Der freie Endpunkt gewichtet einen Aufruf mit Variablen x Orten — und jeder
# Member zaehlt als eigene Variable. 3 Variablen x 21 Member x 40 Orte lief
# sofort in ein 429. Darum: wenige Orte pro Call, nur weather_code als
# Standard-Variable, Pause dazwischen.
ENSEMBLE_CHUNK = 15
ENSEMBLE_DELAY = 2.0        # Sekunden zwischen Chunks
ENSEMBLE_RETRY_MAX = 3
ENSEMBLE_RETRY_WAIT = 20    # Basis-Wartezeit bei 429, verdoppelt sich

# Nur weather_code wird fuer die Wahrscheinlichkeit gebraucht. cape/precipitation
# sind Kontext und verdreifachen das Gewicht des Aufrufs — daher optional.
ENSEMBLE_VARS_DEFAULT = "weather_code"

THUNDER_CODES = (95, 96, 99)

_MEMBER_RE = re.compile(r"_member\d+$")


def member_keys(hourly: dict, var: str) -> list:
    """Alle Member-Spalten einer Variable: Kontrolllauf + member01..member20.

    Open-Meteo liefert den Kontrolllauf unter dem nackten Namen ("cape") und
    die Stoerungslaeufe als "cape_member01" ... "cape_member20".
    """
    keys = [k for k in hourly
            if k == var or (k.startswith(var + "_member") and _MEMBER_RE.search(k))]
    # Kontrolllauf zuerst, danach numerisch sortiert.
    return sorted(keys, key=lambda k: (k != var, k))


def _severest(values):
    """Schwerster Code ueber mehrere Referenzpunkte (Rangfolge aus fetch_weather)."""
    from fetch_weather import _severest_weather_code
    return _severest_weather_code(values)


def merge_points_per_member(point_hourlies: list, var: str = "weather_code") -> list:
    """Fuehrt mehrere Referenzpunkte je Member zusammen.

    point_hourlies: eine "hourly"-Struktur pro Referenzpunkt.
    Rueckgabe: eine Werteliste pro Member (Laenge = Anzahl Stunden).

    Innerhalb eines Members gehoeren alle Referenzpunkte zum SELBEN gestoerten
    Lauf — sie ueber die Region zusammenzufassen ist physikalisch konsistent.
    Ueber Member hinweg darf nicht gemischt werden; genau darum laeuft die
    Zusammenfassung je Member und nicht ueber alle Spalten.
    """
    if not point_hourlies:
        return []
    keys = member_keys(point_hourlies[0], var)
    if not keys:
        return []
    n_hours = min(len(h.get(k, [])) for h in point_hourlies for k in keys)

    merged = []
    for k in keys:
        row = []
        for i in range(n_hours):
            vals = [h[k][i] for h in point_hourlies if k in h and i < len(h[k])]
            if var == "weather_code":
                row.append(_severest(vals))
            else:
                nums = [v for v in vals if isinstance(v, (int, float))]
                row.append(max(nums) if nums else None)
        merged.append(row)
    return merged


def _is_thunder(v) -> bool:
    try:
        return v is not None and int(v) in THUNDER_CODES
    except (TypeError, ValueError):
        return False


def merge_points_thunder_count(point_hourlies: list) -> list:
    """Wie merge_points_per_member, liefert aber die ANZAHL der Referenzpunkte
    mit Gewitter-Code statt des schwersten Codes.

    Grundlage fuer den Mindestanteil (config.ENSEMBLE_THUNDER_POINT_QUORUM).
    Vorher genuegte ein einziger von 7 Punkten, damit ein Member fuer die ganze
    Region als Gewitter zaehlte — ein ODER ueber die Flaeche. In Voralpen-
    regionen, deren Punkte vom Talboden bis zum Grat reichen, schlaegt das am
    staerksten durch; dort lagen am 02.08. alle 5 Faelle, in denen nur wir
    Gewitter zeigten und XC Therm nicht.
    """
    if not point_hourlies:
        return []
    keys = member_keys(point_hourlies[0], "weather_code")
    if not keys:
        return []
    n_hours = min(len(h.get(k, [])) for h in point_hourlies for k in keys)

    merged = []
    for k in keys:
        row = []
        for i in range(n_hours):
            vals = [h[k][i] for h in point_hourlies if k in h and i < len(h[k])]
            row.append(sum(1 for v in vals if _is_thunder(v)))
        merged.append(row)
    return merged


def thunder_probability(member_codes: list, times: list, date: str,
                        hour_start: int = None, hour_end: int = None,
                        quorum: int = None) -> dict:
    """Anteil der Member mit Gewitter-Code im Flugfenster eines Tages.

    member_codes: eine Werteliste je Member (aus merge_points_per_member).
    times:        Zeitachse (Open-Meteo "time"), gleiche Laenge.
    quorum:       Ist er gesetzt, sind die Werte PUNKTZAEHLER aus
                  merge_points_thunder_count und ein Member zaehlt erst ab
                  dieser Anzahl Referenzpunkte als Gewitter. Ohne quorum
                  bleibt es beim alten Verhalten (Werte sind Wettercodes).

    Rueckgabe (probability_pct = Anteil der Member, die IRGENDWANN im Fenster
    zuenden; peak_* = zeitlicher Schwerpunkt):
        {"probability_pct", "n_members", "n_hit", "hourly_share_pct",
         "peak_start", "peak_end", "peak_share_pct", "level"}
    Bei fehlenden Daten: {"probability_pct": None, ...}.
    """
    hour_start = config.FLIGHT_HOURS_START if hour_start is None else hour_start
    hour_end = config.FLIGHT_HOURS_END if hour_end is None else hour_end

    idx = [i for i, t in enumerate(times)
           if t[:10] == date and hour_start <= int(t[11:13]) < hour_end]
    n_members = len(member_codes)
    if not idx or not n_members:
        return {"probability_pct": None, "n_members": n_members, "n_hit": 0,
                "hourly_share_pct": {}, "peak_start": None, "peak_end": None,
                "peak_share_pct": None, "level": None}

    if quorum is None:
        def _hit(v):
            return _is_thunder(v)
    else:
        def _hit(v):
            return isinstance(v, int) and v >= quorum

    n_hit = sum(1 for m in member_codes
                if any(i < len(m) and _hit(m[i]) for i in idx))
    prob = round(100.0 * n_hit / n_members)

    hourly_share = {}
    for i in idx:
        hits = sum(1 for m in member_codes if i < len(m) and _hit(m[i]))
        hourly_share[times[i][11:16]] = round(100.0 * hits / n_members)

    peak_start = peak_end = peak_share = None
    if hourly_share:
        peak_share = max(hourly_share.values())
        if peak_share > 0:
            # Schwerpunkt = kleinstes zusammenhaengendes Fenster, das alle
            # Stunden mit mindestens der halben Spitzen-Zustimmung abdeckt.
            cut = peak_share / 2.0
            hot = [h for h, s in sorted(hourly_share.items()) if s >= cut]
            peak_start, peak_end = hot[0], hot[-1]

    return {
        "probability_pct": prob,
        "n_members": n_members,
        "n_hit": n_hit,
        "hourly_share_pct": hourly_share,
        "peak_start": peak_start,
        "peak_end": peak_end,
        "peak_share_pct": peak_share,
        "level": probability_level(prob),
    }


def probability_level(prob):
    """Weiche Warnstufe. None = unterhalb der Erwaehnungsschwelle.

    UNKALIBRIERT — Startpunkt laut Auftrag (20-30 % der Member).
    """
    if prob is None:
        return None
    if prob >= config.ENSEMBLE_THUNDER_HIGH_PCT:
        return "hoch"
    if prob >= config.ENSEMBLE_THUNDER_ELEVATED_PCT:
        return "erhoeht"
    if prob >= config.ENSEMBLE_THUNDER_MENTION_PCT:
        return "moeglich"
    return None


def thunder_anchor_ok(data):
    """Plausibilitaetsanker: gibt die Stunde ein Gewitter ueberhaupt her?

    Das Ensemble kennt nur Wettercodes und wurde bis 02.08.2026 nie gegen die
    Stunde gegengelesen, in der es angezeigt wird — die Haelfte aller Blitze
    stand bei unter 50 % Bewoelkung und ohne einen Tropfen Regen (Tessin
    Zentral 04.08. 14:00 bei 2 % Bewoelkung).

    Bedingung: Instabilitaet UND Niederschlag, beides in DERSELBEN Stunde aus
    dem deterministischen Lauf. Instabilitaet heisst CAPE ODER Lifted Index —
    CAPE allein waere hoehenabhaengig und wuerde Hochalpenregionen dauerhaft
    stummschalten. Schwellen und Begruendung — auch warum CIN bewusst fehlt —
    in config.THUNDER_ANCHOR_*.

    Bewoelkung als Regen-Alternative wurde am 03.08.2026 ENTFERNT: im
    Saison-Backtest (15.05.-02.08., 2320 Regionstage gegen SwissMetNet-
    Signaturen) liess der Wolken-Zweig 61 % aller gewitterfreien Tage durch
    — im Sommer hat fast jede Region irgendwo 50 % Bewoelkung. Die
    Regen-Pflicht senkt das auf 24 % und kostet genau einen Gewittertag von
    113 (Tessin Nord 16.07., det. Lauf voellig trocken). Zahlen:
    docs/GEWITTER.md, Abschnitt "Anker verschaerft".

    Gilt nur fuer den Ensemble-Weg, nie fuer den deterministischen
    Gewittercode 95/96/99: der stammt aus demselben Lauf wie Wolken und Regen
    und ist per Konstruktion in sich stimmig.
    """
    if not isinstance(data, dict):
        return False

    def _num(key):
        v = data.get(key)
        return v if isinstance(v, (int, float)) else None

    cape = _num("cape")
    li = _num("lifted_index")
    unstable = ((cape is not None and cape >= config.THUNDER_ANCHOR_CAPE_JKG)
                or (li is not None and li <= config.THUNDER_ANCHOR_LI))
    if not unstable:
        return False
    precip = _num("precipitation")
    return precip is not None and precip >= config.THUNDER_ANCHOR_PRECIP_MM


def is_ensemble_storm_hour(share_pct, data):
    """Zeigt diese Stunde ein Ensemble-Gewitter? Die EINE gemeinsame Regel.

    Wird sowohl vom Blitz-Symbol im Meteogramm (web.format_data_for_charts)
    als auch von der Gewitter-Kachel und dem LLM-Kontext
    (engine/weather_context.py) benutzt. Vorher hatte jede Schicht ihre eigene
    Rechnung: das Symbol lief ab 02.08. auf Stundenwerten, die Kachel weiter
    auf dem Tageswert — dieselbe Region zeigte im Meteogramm keinen Blitz und
    im Text daneben eine Gewitterwarnung.

    share_pct: Anteil der Member mit Gewitter in DIESER Stunde.
    """
    if share_pct is None or share_pct < config.ENSEMBLE_THUNDER_METEOGRAM_PCT:
        return False
    return thunder_anchor_ok(data)


def _get_with_retry(params, label=""):
    """GET mit Backoff bei 429. Ohne API-Key (siehe Modul-Kopf)."""
    last = None
    for attempt in range(ENSEMBLE_RETRY_MAX + 1):
        resp = requests.get(ENSEMBLE_URL, params=params, timeout=ENSEMBLE_TIMEOUT)
        if resp.status_code == 429 and attempt < ENSEMBLE_RETRY_MAX:
            retry_after = resp.headers.get("Retry-After")
            wait = int(retry_after) + 2 if retry_after else ENSEMBLE_RETRY_WAIT * (2 ** attempt)
            print(f"  [RATE-LIMIT] Ensemble {label} — warte {wait}s "
                  f"(Versuch {attempt + 1}/{ENSEMBLE_RETRY_MAX})...")
            time.sleep(wait)
            last = resp
            continue
        resp.raise_for_status()
        return resp
    if last is not None:
        last.raise_for_status()
    raise requests.RequestException(f"Ensemble nicht erreichbar: {label}")


def fetch_ensemble(points: list, days: int = None, model: str = None,
                   variables: str = None) -> list:
    """Holt die Member-Zeitreihen fuer mehrere Punkte.

    Rueckgabe: eine Antwort je Punkt, in der Reihenfolge von `points`.
    Ohne API-Key — der Endpunkt weist unseren Kunden-Key ab (siehe Modul-Kopf).
    """
    days = config.FORECAST_DAYS_CH2 if days is None else days
    model = config.ENSEMBLE_MODEL if model is None else model
    variables = ENSEMBLE_VARS_DEFAULT if variables is None else variables

    out = []
    n_chunks = (len(points) + ENSEMBLE_CHUNK - 1) // ENSEMBLE_CHUNK
    for ci, start in enumerate(range(0, len(points), ENSEMBLE_CHUNK)):
        chunk = points[start:start + ENSEMBLE_CHUNK]
        params = {
            "latitude": ",".join(f"{p[0]:.4f}" for p in chunk),
            "longitude": ",".join(f"{p[1]:.4f}" for p in chunk),
            "models": model,
            "hourly": variables,
            "forecast_days": days,
            "timezone": config.TIMEZONE,
        }
        resp = _get_with_retry(params, label=f"{start}-{start + len(chunk)}")
        data = resp.json()
        out.extend(data if isinstance(data, list) else [data])
        if ci < n_chunks - 1:
            time.sleep(ENSEMBLE_DELAY)
    return out


def compute_region_thunder(region_points: dict, days: int = None,
                           model: str = None, variables: str = None) -> dict:
    """Gewitterwahrscheinlichkeit je Region und Tag.

    region_points: {region_id: [[lat, lon], ...]}
    Rueckgabe:     {region_id: {"YYYY-MM-DD": {...}, "_meta": {...}}}

    Faellt der Ensemble-Abruf aus, wird {} zurueckgegeben — der Aufrufer laeuft
    dann ohne Ensemble weiter. Die weiche Warnstufe darf nie dazu fuehren, dass
    der ganze Wetterlauf scheitert.
    """
    order, index = [], {}
    for pts in region_points.values():
        for p in pts:
            key = (round(p[0], 4), round(p[1], 4))
            if key not in index:
                index[key] = len(order)
                order.append(p)
    if not order:
        return {}

    try:
        raw = fetch_ensemble(order, days=days, model=model, variables=variables)
    except (requests.RequestException, ValueError) as exc:
        print(f"  [WARN] Ensemble-Gewitter nicht abrufbar: {exc}")
        return {}

    if len(raw) != len(order):
        print(f"  [WARN] Ensemble: {len(raw)} Antworten fuer {len(order)} Punkte")

    out = {}
    for rid, pts in region_points.items():
        hourlies = []
        for p in pts:
            i = index.get((round(p[0], 4), round(p[1], 4)))
            if i is not None and i < len(raw):
                h = raw[i].get("hourly")
                if h:
                    hourlies.append(h)
        if not hourlies:
            continue
        times = hourlies[0].get("time", [])
        # Punktzaehler statt schwerstem Code: ein einzelner Referenzpunkt soll
        # die ganze Region nicht mehr allein tragen (siehe
        # config.ENSEMBLE_THUNDER_POINT_QUORUM). Bei Regionen mit weniger
        # Punkten als der Mindestanteil verlangt faellt er auf 1 zurueck —
        # sonst waere die Region stumm.
        merged = merge_points_thunder_count(hourlies)
        if not merged:
            continue
        quorum = max(1, min(config.ENSEMBLE_THUNDER_POINT_QUORUM, len(hourlies)))
        days_seen = sorted({t[:10] for t in times})
        per_day = {d: thunder_probability(merged, times, d, quorum=quorum)
                   for d in days_seen}
        per_day["_meta"] = {
            "model": model or config.ENSEMBLE_MODEL,
            "n_members": len(merged),
            "n_points": len(hourlies),
            "point_quorum": quorum,
        }
        out[rid] = per_day
    return out
