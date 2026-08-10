"""Konvektion — ALLES zu Gewitter und Ueberentwicklung in EINER Datei.

Entscheid User 03.08.2026: eine Domaene, eine Datei. Drei Abschnitte:

  1. REGELN            is_ensemble_storm_hour()  -> harter Blitz
                       thunder_anchor_ok()       -> Anker (Regen-Pflicht)
                       probability_level()       -> Text-Warnstufe
                       is_overdev_hour()         -> hohler Blitz (Ueberentwicklung)
  2. ENSEMBLE-ABRUF    ICON-CH2-EPS, 21 Member (Gewitterwahrscheinlichkeit)
  3. WOLKENTOP-ABRUF   ICON-EU (Ueberentwicklungs-Potenzial)

Die Regeln sind die EINE Quelle der Wahrheit fuer Meteogramm (web.py),
KI-Analyse (engine/weather_context.py) und Validierung — Symbol, Text und
Messung koennen nicht auseinanderlaufen. Herleitung und Backtest-Zahlen:
docs/GEWITTER.md par.0c/0d.
"""
from __future__ import annotations

import re
import time

import requests

import config



# ==========================================================================
# 1. REGELN — die Entscheidungen (eine Quelle der Wahrheit)
# ==========================================================================

def _num(v):
    return v if isinstance(v, (int, float)) else None


def is_overdev_hour(cloud_top_entry, data, therm=None, storm=False):
    """Zeigt diese Stunde Ueberentwicklungs-Potenzial?

    cloud_top_entry: {"cold_share_pct": .., "top_min_c": ..} aus
                     _regions[rid]["cloud_top"][zeitstempel] (None = kein Top)
    data:            deterministische Stundenwerte (cloud_cover, cape,
                     lifted_index) — DIESELBEN Werte, die das Meteogramm zeigt
    therm:           Thermik der Stunde (max_height, lcl) — Spot-Median der
                     Region; fehlt sie, entscheidet der Rest (fail-open,
                     die Stufe ist Zusatzinfo, kein Gate)
    storm:           True = harte Blitz-Stunde -> immer False
    """
    if storm:
        return False
    if not isinstance(cloud_top_entry, dict):
        return False
    share = _num(cloud_top_entry.get("cold_share_pct"))
    if share is None or share < config.OVERDEV_TOP_SHARE_PCT:
        return False
    if not isinstance(data, dict):
        return False

    # Konsistenz-Regel (User 03.08.): nie "wolkenlos" anzeigen und daneben
    # Ueberentwicklung behaupten. Massstab ist die angezeigte Bewoelkung.
    cloud = _num(data.get("cloud_cover"))
    if cloud is None or cloud < config.OVERDEV_CLOUD_MIN_PCT:
        return False

    cape = _num(data.get("cape"))
    li = _num(data.get("lifted_index"))
    unstable = ((cape is not None and cape >= config.THUNDER_ANCHOR_CAPE_JKG)
                or (li is not None and li <= config.THUNDER_ANCHOR_LI))
    if not unstable:
        return False

    # Blauthermik-Veto: AKTIVE Thermik (climb > 0), die die Wolkenbasis klar
    # nicht erreicht -> es waechst keine Quellwolke aus der Grenzschicht
    # (User-Kriterium: nur Wolken-Gefahr zaehlt). Bewusst NUR bei aktiver
    # Thermik: Stunden ohne Thermik (Abend, Morgen) haben zwar keine
    # Blauthermik, aber sehr wohl moegliche Front-/Abendkonvektion — die
    # Abend-Gewitter waren der grosse blinde Fleck des Testtags 02.08.
    if isinstance(therm, dict):
        climb = _num(therm.get("climb_rate"))
        max_h = _num(therm.get("max_height"))
        lcl = _num(therm.get("lcl"))
        if (climb is not None and climb > 0
                and max_h is not None and lcl is not None
                and max_h + config.OVERDEV_THERMIK_MARGIN_M < lcl):
            return False
    return True


def onset_hour(hours):
    """Erste Ueberentwicklungs-Stunde ("HH:MM"-Liste) — fuer das Wording
    "Quellwolken koennen ab ~14 Uhr hochschiessen"."""
    return min(hours) if hours else None


# --------------------------------------------------------------------------
# Gewitter-Regeln (aus convection.py hierher gezogen, 03.08.2026)
# --------------------------------------------------------------------------


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
    113 (Leventina / Blenio 16.07., det. Lauf voellig trocken). Zahlen:
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


# ==========================================================================
# 2. ENSEMBLE-ABRUF — ICON-CH2-EPS, 21 Member
# ==========================================================================

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


# ==========================================================================
# 3. WOLKENTOP-ABRUF — ICON-EU (Ueberentwicklung)
# ==========================================================================

# Wolkentop-Abruf fuer die Ueberentwicklungs-Stufe (ICON-EU).
# 
# WARUM ICON-EU
# -------------
# `convective_cloud_top` liefert nur ICON-EU verlaesslich: MeteoSchweiz
# ICON-CH1/CH2 kennen das Feld gar nicht, ICON-D2 laesst es fast immer leer
# (2-km-Modell rechnet Konvektion teils explizit, das Konvektionsschema
# schweigt). Gemessen am 03.08.2026 (Saison-Backtest, docs/GEWITTER.md par.0c):
# der EU-Top erkannte 96 % der Gewittertage — als harter Alarm viel zu laut,
# als weiche Ueberentwicklungs-Vorwarnung mit Flaechen-Quorum + Anker
# brauchbar (2 von 3 Konvektionstagen, ~3-4 h Vorlauf).
# 
# MODELL-MIX, BEWUSST
# -------------------
# Das ist eine Zutat aus einem ANDEREN Modell als dem angezeigten CH1/CH2 —
# ein Indizien-Voting, keine Physik-Kette (Entscheid 03.08.). Darum wird der
# Top nie stundenscharf mit CH1-Feldern ver-UND-et, sondern nur als
# Flaechen-Anteil je Stunde gefuehrt; die Konsistenz mit der Anzeige stellt
# convection.is_overdev_hour ueber die ANGEZEIGTE Bewoelkung her. Der Abgleich
# gegen die Messung (validation/gewitter/) entscheidet empirisch, ob der Mix
# traegt — die Ein-Modell-Alternative (Wolkentiefe selbst aus dem
# CH1/CH2-Profil) bleibt als Challenger im Plan.
# 
# Wolkentop-Temperatur: Abstand zum Gefrierniveau x 6,5 K/km — bewusst grob,
# es geht um die Stufe (harmlos / hochgeschossen), nicht ums Grad.

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 90
CHUNK = 40          # Punkte pro Aufruf (2 Variablen -> moderates Gewicht)
DELAY = 0.6
RETRY_MAX = 3
RETRY_WAIT = 15

LAPSE_K_PER_M = 0.0065


def top_temp_c(top_m, freezing_m):
    """Wolkentop-Temperatur aus Tophoehe + Gefrierniveau. None = kein Top."""
    if not isinstance(top_m, (int, float)) or top_m <= 0:
        return None
    if not isinstance(freezing_m, (int, float)):
        return None
    if top_m <= freezing_m:
        return 5.0          # Top unterhalb der Nullgrad-Grenze -> "warm"
    return -(top_m - freezing_m) * LAPSE_K_PER_M


def _get_with_retry(params, label=""):
    last = None
    for attempt in range(RETRY_MAX + 1):
        resp = requests.get(FORECAST_URL, params=config.with_api_key(params),
                            timeout=TIMEOUT)
        if resp.status_code == 429 and attempt < RETRY_MAX:
            wait = RETRY_WAIT * (2 ** attempt)
            print(f"  [RATE-LIMIT] Wolkentop {label} — warte {wait}s ...")
            time.sleep(wait)
            last = resp
            continue
        resp.raise_for_status()
        return resp
    if last is not None:
        last.raise_for_status()
    raise requests.RequestException(f"Wolkentop nicht erreichbar: {label}")


def fetch_cloud_tops(points: list, days: int = None) -> list:
    """ICON-EU convective_cloud_top + freezing_level_height je Punkt."""
    days = config.FORECAST_DAYS_CH2 if days is None else days
    out = []
    n_chunks = (len(points) + CHUNK - 1) // CHUNK
    for ci, start in enumerate(range(0, len(points), CHUNK)):
        chunk = points[start:start + CHUNK]
        params = {
            "latitude": ",".join(f"{p[0]:.4f}" for p in chunk),
            "longitude": ",".join(f"{p[1]:.4f}" for p in chunk),
            "models": "icon_eu",
            "hourly": "convective_cloud_top,freezing_level_height",
            "forecast_days": days,
            "timezone": config.TIMEZONE,
        }
        resp = _get_with_retry(params, label=f"{start}-{start + len(chunk)}")
        data = resp.json()
        out.extend(data if isinstance(data, list) else [data])
        if ci < n_chunks - 1:
            time.sleep(DELAY)
    return out


def compute_region_cloud_tops(region_points: dict, days: int = None) -> dict:
    """Je Region und Stunde: Anteil der Referenzpunkte mit kaltem Wolkentop.

    region_points: {region_id: [[lat, lon], ...]}
    Rueckgabe: {region_id: {"YYYY-MM-DDTHH:MM": {"cold_share_pct": 86,
                                                  "top_min_c": -32.5}}}
    Nur Stunden mit mindestens einem kalten Punkt werden gefuehrt — alles
    andere waere ein Woerterbuch voller Nullen (Sommer: fast immer 0).
    Faellt der Abruf aus, gibt es {} — der Wetterlauf laeuft ohne
    Ueberentwicklungs-Stufe weiter, sie ist reine Zusatzinfo.
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
        raw = fetch_cloud_tops(order, days=days)
    except (requests.RequestException, ValueError) as exc:
        print(f"  [WARN] Wolkentop nicht abrufbar: {exc}")
        return {}

    out = {}
    for rid, pts in region_points.items():
        hourlies = []
        for p in pts:
            i = index.get((round(p[0], 4), round(p[1], 4)))
            if i is not None and i < len(raw):
                h = raw[i].get("hourly")
                if h and h.get("time"):
                    hourlies.append(h)
        if not hourlies:
            continue
        times = hourlies[0]["time"]
        per_hour = {}
        for j, t in enumerate(times):
            temps = []
            for h in hourlies:
                tops = h.get("convective_cloud_top") or []
                frz = h.get("freezing_level_height") or []
                if j < len(tops) and j < len(frz):
                    tt = top_temp_c(tops[j], frz[j])
                    if tt is not None:
                        temps.append(tt)
            if not temps:
                continue
            cold = [tt for tt in temps if tt <= config.OVERDEV_TOP_TEMP_C]
            if not cold:
                continue
            per_hour[t] = {
                "cold_share_pct": round(100.0 * len(cold) / len(hourlies)),
                "top_min_c": round(min(temps), 1),
            }
        if per_hour:
            out[rid] = per_hour
    return out
