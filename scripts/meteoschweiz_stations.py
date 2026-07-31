"""MeteoSchweiz-Stationsmessungen (OGD-SMN) — Wahrheitsquelle fuer Validierung.

WARUM STATIONEN UND NICHT MODELLDATEN
-------------------------------------
Eine Auswertung im Juli 2026 nutzte die Open-Meteo-Archive-API ohne
`models`-Parameter. Die liefert ECMWF IFS statt des Schweizer Modells — der
Vergleich mass also ein fremdes Modell gegen unsere Anzeige und erzeugte einen
Scheinbefund, der sich bei der Gegenprobe umkehrte. Gegen Messungen kann das
nicht passieren. Darum: Vorhersagen IMMER gegen Stationsmessungen pruefen.

DATENQUELLE (frei, ohne Schluessel)
-----------------------------------
  Stationsliste
    https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/ogd-smn_meta_stations.csv
  Stundenwerte je Station (<abbr> kleingeschrieben)
    https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/<abbr>/ogd-smn_<abbr>_h_recent.csv

  Encoding latin-1, Trennzeichen ";".
  rre150h0 = Niederschlag Stundensumme in mm
  tre200h0 = Lufttemperatur 2 m in Grad C

ZEITACHSE — DIE FEHLERQUELLE
----------------------------
`reference_timestamp` ist UTC und bezeichnet das ENDE der Stunde, also die
Stunde DAVOR. Um den Stundenbeginn zu erhalten: 1 Stunde abziehen. Danach von
UTC in die lokale Zeit der Vorhersage umrechnen.

Die Ausrichtung ist nicht zu glauben, sondern zu pruefen: check_alignment()
verschiebt die Messreihe gegen die Modelltemperatur um -3..+3 Stunden. Die
kleinste mittlere Abweichung MUSS bei Verschiebung 0 liegen. Tut sie das nicht,
ist die Zuordnung falsch und jede darauf gebaute Trefferquote wertlos.
"""

from __future__ import annotations

import csv
import io
import os
import sys
import time
from datetime import datetime, timedelta

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

META_URL = "https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/ogd-smn_meta_stations.csv"
HOURLY_URL = ("https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/"
              "{abbr}/ogd-smn_{abbr}_h_recent.csv")

CACHE_DIR = os.path.join(ROOT, "data", "_meteoschweiz_cache")
CACHE_MAX_AGE_S = 6 * 3600

PRECIP_COL = "rre150h0"
TEMP_COL = "tre200h0"

EARTH_R_KM = 6371.0


def _cache_path(name):
    return os.path.join(CACHE_DIR, name)


def _fetch_text(url, cache_name, max_age=CACHE_MAX_AGE_S):
    """Holt eine CSV-Datei, mit lokalem Zwischenspeicher (latin-1)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(cache_name)
    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < max_age:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    text = resp.content.decode("latin-1")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text


def load_stations():
    """-> {abbr: {"name", "lat", "lon", "elevation_m"}} (nur mit Koordinaten)."""
    text = _fetch_text(META_URL, "meta_stations.csv", max_age=7 * 24 * 3600)
    out = {}
    for row in csv.DictReader(io.StringIO(text), delimiter=";"):
        try:
            lat = float(row["station_coordinates_wgs84_lat"])
            lon = float(row["station_coordinates_wgs84_lon"])
        except (TypeError, ValueError, KeyError):
            continue
        try:
            elev = float(row.get("station_height_masl") or "nan")
        except ValueError:
            elev = None
        out[row["station_abbr"]] = {
            "name": row.get("station_name", ""),
            "lat": lat,
            "lon": lon,
            "elevation_m": elev,
        }
    return out


def load_hourly(abbr, utc_offset_h=2):
    """Stundenwerte einer Station -> {"YYYY-MM-DDTHH": {"precip_mm", "temp_c"}}.

    Der Schluessel ist der STUNDENBEGINN in LOKALER Zeit — also so, wie unsere
    Vorhersage die Stunde benennt. Zwei Korrekturen stecken darin:
      1. reference_timestamp bezeichnet das Ende der Stunde -> 1 h abziehen
      2. reference_timestamp ist UTC -> utc_offset_h addieren (Sommer: +2)
    """
    try:
        text = _fetch_text(HOURLY_URL.format(abbr=abbr.lower()),
                           f"h_{abbr.lower()}.csv")
    except requests.RequestException:
        return {}

    out = {}
    for row in csv.DictReader(io.StringIO(text), delimiter=";"):
        raw = (row.get("reference_timestamp") or "").strip()
        if not raw:
            continue
        try:
            ts = datetime.strptime(raw, "%d.%m.%Y %H:%M")
        except ValueError:
            continue
        start = ts - timedelta(hours=1) + timedelta(hours=utc_offset_h)

        def _num(col):
            v = (row.get(col) or "").strip()
            if v in ("", "-"):
                return None
            try:
                return float(v)
            except ValueError:
                return None

        out[start.strftime("%Y-%m-%dT%H")] = {
            "precip_mm": _num(PRECIP_COL),
            "temp_c": _num(TEMP_COL),
        }
    return out


def haversine_km(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, asin, sqrt
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (sin(dlat / 2) ** 2
         + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2)
    return 2 * EARTH_R_KM * asin(sqrt(a))


def check_alignment(pairs, max_shift=3):
    """Beweist die ZEITZUORDNUNG ueber den Tagesgang der Temperatur.

    pairs: [(station_stunden_dict, modell_temp_dict)] — beide {"YYYY-MM-DDTHH": wert}.
    Verschiebt die Messreihe um -max_shift..+max_shift Stunden und gibt je
    Verschiebung die mittlere absolute Abweichung zurueck.

    WICHTIG: Je Paar wird der MITTLERE Versatz abgezogen. Station und
    Modellpunkt liegen fast nie auf derselben Hoehe; der daraus folgende
    konstante Temperaturunterschied (leicht 5-6 K zwischen Talstation und
    alpinem Referenzpunkt) sagt nichts ueber die Zeitachse aus und wuerde die
    Pruefung nur verrauschen. Uebrig bleibt der Tagesgang — und genau der
    verschiebt sich, wenn die Stunden falsch zugeordnet sind.

    -> (best_shift, {shift: mean_abs_residual})
    Ist best_shift != 0, stimmt die Zuordnung NICHT.
    """
    errors = {}
    for shift in range(-max_shift, max_shift + 1):
        residuals = []
        for obs, model in pairs:
            diffs = []
            for key, rec in obs.items():
                t_obs = rec.get("temp_c")
                if t_obs is None:
                    continue
                try:
                    dt = datetime.strptime(key, "%Y-%m-%dT%H") + timedelta(hours=shift)
                except ValueError:
                    continue
                t_mod = model.get(dt.strftime("%Y-%m-%dT%H"))
                if t_mod is None:
                    continue
                diffs.append(t_obs - t_mod)
            if len(diffs) < 24:  # zu kurz fuer einen belastbaren Mittelwert
                continue
            bias = sum(diffs) / len(diffs)
            residuals.extend(abs(d - bias) for d in diffs)
        if residuals:
            errors[shift] = sum(residuals) / len(residuals)
    if not errors:
        return None, {}
    best = min(errors, key=errors.get)
    return best, errors


def assign_stations_to_regions(stations, spots, max_km=12.0):
    """Ordnet jede Station der Region ihres naechsten Fluggebiets zu (<= max_km).

    Bewusst ueber das naechste Fluggebiet und NICHT ueber die Distanz zum
    Regionsmittelpunkt: Regionen sind langgezogene Polygone, ein Distanzmass
    zum Zentrum ordnet Randstationen regelmaessig falsch zu.
    """
    out = {}
    for abbr, st in stations.items():
        best = None
        for sp in spots:
            lat, lon = sp.get("latitude"), sp.get("longitude")
            region = sp.get("analyse_region")
            if lat is None or lon is None or not region:
                continue
            d = haversine_km(st["lat"], st["lon"], lat, lon)
            if best is None or d < best[0]:
                best = (d, region, sp.get("name"))
        if best and best[0] <= max_km:
            out[abbr] = {"region": best[1], "distance_km": round(best[0], 2),
                         "nearest_spot": best[2]}
    return out
