#!/usr/bin/env python3
"""
Föhn-Indikatoren für Gleitschirmflieger.

Berechnet Föhn-Warnstufen basierend auf:
- Druckgradient (Delta-P) Nord vs. Süd der Alpen
- Höhenwind am Alpenhauptkamm (700 hPa ≈ 3000 m)
- Lokale Luftfeuchtigkeit (Föhnluft ist trocken)
- Böigkeit (starke Differenz Wind/Böen = turbulent)

Verwendet MeteoSwiss ICON für die Schweiz (hochauflösend).
"""

import requests
from datetime import datetime
from typing import Optional

import config

# ============================================================================
# FÖHN-REFERENZSTATIONEN
# ============================================================================
# Südföhn: Hoher Druck im Süden (Lugano), tiefer Druck im Norden (Zürich)
# Delta-P = P_süd - P_nord > 0 → Südföhn-Gefahr

FOEHN_STATIONS = {
    "nord": {
        "name": "Zürich",
        "lat": 47.37,
        "lon": 8.55,
        "role": "Nordseite (Lee)",
    },
    "sued": {
        "name": "Lugano",
        "lat": 46.0,
        "lon": 8.96,
        "role": "Südseite (Luv)",
    },
}

# Südföhn: Wind am Kamm aus S/SW (135°–225°)
SUEDFOEHN_DIR_START = 135
SUEDFOEHN_DIR_END = 225

# Schwellenwerte (Gemini-Empfehlung)
THRESHOLD_DELTA_P_CAUTION = 4   # hPa – Vorsicht
THRESHOLD_DELTA_P_DANGER = 8    # hPa – Flugverbot-Empfehlung
THRESHOLD_CREST_WIND_CAUTION = 54   # km/h (15 m/s) – starkes Warnsignal
THRESHOLD_CREST_WIND_DANGER = 180   # km/h (50 m/s) – Flugverbot
THRESHOLD_HUMIDITY_LOW = 40     # % – Föhn „durchgebrochen“
THRESHOLD_GUST_RATIO = 1.5      # Böen/Wind > 1.5 = böig/turbulent


def _potential_temperature(temp_kelvin: float, pressure_hpa: float, p0: float = 1000.0) -> float:
    """Potenzielle Temperatur θ = T * (P0/P)^0.2854"""
    if pressure_hpa <= 0:
        return 0.0
    return temp_kelvin * (p0 / pressure_hpa) ** 0.2854


def fetch_foehn_data(forecast_days: int = 2) -> Optional[dict]:
    """
    Holt Föhn-relevante Daten von Open-Meteo (MeteoSwiss ICON).

    Multi-Point-Abfrage: Nord (Zürich) + Süd (Lugano).
    """
    lats = [FOEHN_STATIONS["nord"]["lat"], FOEHN_STATIONS["sued"]["lat"]]
    lons = [FOEHN_STATIONS["nord"]["lon"], FOEHN_STATIONS["sued"]["lon"]]

    params = config.with_api_key({
        "latitude": ",".join(str(x) for x in lats),
        "longitude": ",".join(str(x) for x in lons),
        "hourly": (
            "pressure_msl,relative_humidity_2m,wind_speed_10m,wind_gusts_10m,"
            "wind_speed_700hPa,wind_direction_700hPa,surface_pressure,temperature_2m"
        ),
        "forecast_days": forecast_days,
        "timezone": config.TIMEZONE,
    })

    try:
        resp = requests.get(config.API_URL, params=params, timeout=config.API_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        # Multi-Point liefert Liste
        if isinstance(data, dict):
            data = [data]

        if len(data) < 2:
            return None

        return {"nord": data[0], "sued": data[1]}
    except Exception as e:
        return None


def evaluate_foehn(
    nord: dict,
    sued: dict,
    time_index: Optional[int] = None,
    kritischer_foehn: str = "Süd",
) -> dict:
    """
    Bewertet Föhn-Gefahr für einen Zeitpunkt.
    kritischer_foehn: "Süd", "Nord" oder "Beide"
    """
    h_nord = nord.get("hourly", {})
    h_sued = sued.get("hourly", {})

    times = h_nord.get("time", [])
    if not times:
        return _empty_result("Keine Zeitreihe")

    if time_index is None:
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%dT%H:00")
        try:
            time_index = times.index(now_str)
        except ValueError:
            time_index = 0

    if time_index >= len(times):
        time_index = 0

    def get(arr, i):
        if arr is None or not isinstance(arr, list) or i >= len(arr):
            return None
        return arr[i]

    p_nord = get(h_nord.get("pressure_msl"), time_index)
    p_sued = get(h_sued.get("pressure_msl"), time_index)
    rh_nord = get(h_nord.get("relative_humidity_2m"), time_index)
    wind_10 = get(h_nord.get("wind_speed_10m"), time_index)
    gusts_10 = get(h_nord.get("wind_gusts_10m"), time_index)
    wind_700 = get(h_nord.get("wind_speed_700hPa"), time_index)
    dir_700 = get(h_nord.get("wind_direction_700hPa"), time_index)

    delta_p_sued = None
    delta_p_nord = None
    if p_sued is not None and p_nord is not None:
        delta_p_sued = round(p_sued - p_nord, 1) # Positiv = Südföhn
        delta_p_nord = round(p_nord - p_sued, 1) # Positiv = Nordföhn

    crest_wind = wind_700
    crest_dir = dir_700 if dir_700 is not None else 0

    gust_ratio = None
    if wind_10 is not None and wind_10 > 0 and gusts_10 is not None:
        gust_ratio = round(gusts_10 / wind_10, 1)

    indicators = []
    level = "none"
    
    krit_foehn = kritischer_foehn
    
    is_suedfoehn_active = delta_p_sued is not None and delta_p_sued > 0
    is_nordfoehn_active = delta_p_nord is not None and delta_p_nord > 0
    
    # 1. Druckgradient
    if is_suedfoehn_active:
        indicators.append(f"Delta-P (Südföhn): {delta_p_sued} hPa")
        if delta_p_sued >= THRESHOLD_DELTA_P_CAUTION:
            msg = f"Südföhn Delta-P >= {THRESHOLD_DELTA_P_CAUTION} hPa"
            if krit_foehn in ['Süd', 'Beide']:
                if delta_p_sued >= THRESHOLD_DELTA_P_DANGER:
                    level = "danger"
                    indicators.append(f"{msg} -> Flugverbot-Empfehlung")
                else:
                    if level != "danger": level = "caution"
                    indicators.append(f"{msg} -> Vorsicht")
            else:
                indicators.append(f"{msg} (für diesen Startplatz nicht kritisch)")
                
    elif is_nordfoehn_active:
        indicators.append(f"Delta-P (Nordföhn): {delta_p_nord} hPa")
        if delta_p_nord >= THRESHOLD_DELTA_P_CAUTION:
            msg = f"Nordföhn Delta-P >= {THRESHOLD_DELTA_P_CAUTION} hPa"
            if krit_foehn in ['Nord', 'Beide']:
                if delta_p_nord >= THRESHOLD_DELTA_P_DANGER:
                    level = "danger"
                    indicators.append(f"{msg} -> Flugverbot-Empfehlung")
                else:
                    if level != "danger": level = "caution"
                    indicators.append(f"{msg} -> Vorsicht")
            else:
                indicators.append(f"{msg} (für diesen Startplatz nicht kritisch)")

    # 2. Höhenwind am Kamm
    if crest_wind is not None:
        indicators.append(f"Höhenwind 700 hPa: {round(crest_wind)} km/h aus {round(crest_dir or 0)}°")
        
        is_sued_dir = SUEDFOEHN_DIR_START <= crest_dir <= SUEDFOEHN_DIR_END
        # Nordföhn Richtung: Nord bis Ost (ca 315° bis 45°)
        is_nord_dir = crest_dir >= 315 or crest_dir <= 45
        
        if is_sued_dir and crest_wind >= THRESHOLD_CREST_WIND_CAUTION:
            msg = "Starker Wind am Kamm aus S/SW"
            if krit_foehn in ['Süd', 'Beide']:
                if crest_wind >= THRESHOLD_CREST_WIND_DANGER:
                    level = "danger"
                    indicators.append(f"{msg} (Flugverbot)")
                else:
                    if level != "danger": level = "caution"
                    indicators.append(msg)
            else:
                indicators.append(f"{msg} (Schwachwind-Thermik gestört, aber kein Föhn-Risiko)")
                
        elif is_nord_dir and crest_wind >= THRESHOLD_CREST_WIND_CAUTION:
            msg = "Starker Wind am Kamm aus N/NE"
            if krit_foehn in ['Nord', 'Beide']:
                if crest_wind >= THRESHOLD_CREST_WIND_DANGER:
                    level = "danger"
                    indicators.append(f"{msg} (Flugverbot)")
                else:
                    if level != "danger": level = "caution"
                    indicators.append(msg)
            else:
                indicators.append(f"{msg} (Biseströmung, nicht föhnkritisch)")

    # 3. Luftfeuchtigkeit (trocken = Föhn durchgebrochen)
    if rh_nord is not None:
        indicators.append(f"Luftfeuchtigkeit (Nord): {round(rh_nord)}%")
        if rh_nord < THRESHOLD_HUMIDITY_LOW and level != "none":
            indicators.append("Trockene Föhnluft im Tal")

    # 4. Böigkeit
    if gust_ratio is not None and gust_ratio > THRESHOLD_GUST_RATIO:
        indicators.append(f"Böigkeit: {gust_ratio:.1f}× (turbulent)")
        if level == "caution":
            indicators.append("Starke Böen → zusätzliche Vorsicht")

    if level == "none" and ((delta_p_sued and delta_p_sued > 0) or (delta_p_nord and delta_p_nord > 0)):
        dir_str = "Süd" if is_suedfoehn_active else "Nord"
        indicators.append(f"Kein Föhn-Alarm, aber {dir_str}-Druckgradient vorhanden.")

    label = {"none": "Kein Föhn", "caution": "Föhn-Vorsicht", "danger": "Föhn-Gefahr"}[level]
    message = _build_message(level, delta_p_sued if is_suedfoehn_active else delta_p_nord, crest_wind, crest_dir, rh_nord)

    foehn_direction = "Süd" if is_suedfoehn_active else ("Nord" if is_nordfoehn_active else "none")

    return {
        "level": level,
        "label": label,
        "message": message,
        "foehn_direction": foehn_direction,
        # Für Abwärtskompatibilität liefern wir den Delta-P der aktuell aktiven Strömung zurück
        "delta_p_hpa": delta_p_sued if is_suedfoehn_active else delta_p_nord,
        "crest_wind_kmh": round(crest_wind, 0) if crest_wind is not None else None,
        "crest_dir_deg": round(crest_dir, 0) if crest_dir is not None else None,
        "humidity_nord": round(rh_nord, 0) if rh_nord is not None else None,
        "gust_ratio": gust_ratio,
        "indicators": indicators,
        "timestamp": times[time_index] if time_index < len(times) else "",
        "stations": FOEHN_STATIONS,
    }


def _build_message(
    level: str,
    delta_p: Optional[float],
    crest_wind: Optional[float],
    crest_dir: Optional[float],
    humidity: Optional[float],
) -> str:
    if level == "none":
        return "Keine Föhn-Warnung. Föhn ist für Gleitschirmflieger extrem gefährlich – bei Unsicherheit nicht starten."
    if level == "caution":
        return "Föhn-Vorsicht: ΔP oder Höhenwind erhöht. An exponierten Stellen vorsichtig sein. Föhn kann unvorhersehbar durchgreifen."
    return "Föhn-Gefahr: Flugverbot-Empfehlung. Starker Druckgradient oder Wind am Kamm. Föhn ist turbulent und tückisch."


def _empty_result(reason: str) -> dict:
    return {
        "level": "none",
        "label": "Keine Daten",
        "message": reason,
        "delta_p_hpa": None,
        "crest_wind_kmh": None,
        "crest_dir_deg": None,
        "humidity_nord": None,
        "gust_ratio": None,
        "indicators": [],
        "timestamp": "",
        "stations": FOEHN_STATIONS,
    }


def build_foehn_llm_context(nord: dict, sued: dict) -> str:
    """
    Aufbereiteter Föhn-Zusatztext für den LLM-Kontext:
    Referenzstationen, Schwellen, pro Flugstunde ΔP (Süd/Nord), 700 hPa, Label, ggf. Böigkeit.
    """
    from datetime import datetime as dt
    from datetime import timedelta as td

    h_nord = nord.get("hourly", {})
    h_sued = sued.get("hourly", {})
    times = h_nord.get("time", [])
    if not times:
        return ""

    today = dt.now().date()
    last_date = today + td(days=config.FORECAST_DAYS - 1)

    lines = [
        "═══ FÖHN — ZEITREIHE & GRADIENTEN (KI) ═══",
        f"Stationen: Nord = {FOEHN_STATIONS['nord']['name']} ({FOEHN_STATIONS['nord']['role']}), "
        f"Süd = {FOEHN_STATIONS['sued']['name']} ({FOEHN_STATIONS['sued']['role']})",
        "Definition: ΔP_Süd = P(Lugano) − P(Zürich) [hPa], positiv → Tendenz Südföhn | "
        "ΔP_Nord = P(Zürich) − P(Lugano) [hPa], positiv → Tendenz Nordföhn (mathematisch Gegenteil).",
        "Pro Stunde (nur Flugstunden, lokale Zeit; Spalte „…-Tendenz“ = welche Lage laut Gradient überwiegt):",
    ]

    pm_n = h_nord.get("pressure_msl")
    pm_s = h_sued.get("pressure_msl")
    if not isinstance(pm_n, list) or not isinstance(pm_s, list):
        lines.append("(Keine Druckzeitreihe in den Daten.)")
        return "\n".join(lines)

    count = 0
    for i, t in enumerate(times):
        try:
            d = dt.fromisoformat(t.replace("Z", "+00:00"))
        except Exception:
            continue
        if d.date() < today or d.date() > last_date:
            continue
        if not (config.FLIGHT_HOURS_START <= d.hour < config.FLIGHT_HOURS_END):
            continue
        if i >= len(pm_n) or i >= len(pm_s):
            continue

        p_zrh = pm_n[i]
        p_lug = pm_s[i]
        if p_zrh is None or p_lug is None:
            continue

        dp_sued = round(p_lug - p_zrh, 1)
        dp_nord = round(p_zrh - p_lug, 1)

        if dp_sued >= 0.5:
            lage = "Südföhn-Tendenz"
        elif dp_nord >= 0.5:
            lage = "Nordföhn-Tendenz"
        else:
            lage = "Gradient schwach"

        ev = evaluate_foehn(nord, sued, time_index=i, kritischer_foehn="Beide")
        crest = ev.get("crest_wind_kmh")
        cdir = ev.get("crest_dir_deg")
        ts = t.replace("T", " ")[:16]
        label = ev.get("label", "?")
        gust_r = ev.get("gust_ratio")
        gust_str = f" | Bö/Wind={gust_r:.1f}×" if gust_r is not None else ""

        lines.append(
            f"  {ts} | ΔP_Süd={dp_sued:+.1f} ΔP_Nord={dp_nord:+.1f} hPa | "
            f"700hPa {crest} km/h/{cdir}° | {lage} | {label}{gust_str}"
        )
        count += 1
        if count >= 200:
            break

    if count == 0:
        lines.append("(Keine Flugstunden im Vorhersagefenster.)")

    return "\n".join(lines)


def get_foehn_for_dashboard(forecast_days: int = 2) -> dict:
    """
    Liefert Föhn-Evaluation für die nächsten Flugstunden (heute + morgen).

    Gibt pro Tag die erste Bewertung im Flugstunden-Fenster zurück,
    plus die „schlimmste“ Stufe des Tages.
    """
    raw = fetch_foehn_data(forecast_days)
    if not raw:
        return {"success": False, "error": "Föhn-Daten konnten nicht geladen werden", "foehn": None}

    nord = raw["nord"]
    sued = raw["sued"]
    times = nord.get("hourly", {}).get("time", [])

    if not times:
        return {"success": True, "foehn": _empty_result("Keine Zeitreihe"), "hourly": []}

    from datetime import datetime as dt

    results_by_hour = []
    worst_level = "none"
    level_order = {"none": 0, "caution": 1, "danger": 2}

    for i, t in enumerate(times):
        try:
            d = dt.fromisoformat(t.replace("Z", "+00:00"))
            if d.hour < config.FLIGHT_HOURS_START or d.hour >= config.FLIGHT_HOURS_END:
                continue
        except Exception:
            continue

        ev = evaluate_foehn(nord, sued, time_index=i)
        results_by_hour.append({
            "time": t,
            "hour": d.hour,
            "level": ev["level"],
            "label": ev["label"],
            "delta_p_hpa": ev["delta_p_hpa"],
            "crest_wind_kmh": ev["crest_wind_kmh"],
        })

        if level_order.get(ev["level"], 0) > level_order.get(worst_level, 0):
            worst_level = ev["level"]

    # Repräsentative Bewertung: erste Flugstunde heute oder schlimmste
    first_today = next((r for r in results_by_hour if r["time"].startswith(
        dt.now().strftime("%Y-%m-%d"))), None)
    first_result = first_today or (results_by_hour[0] if results_by_hour else None)

    if first_result:
        ev = evaluate_foehn(nord, sued, time_index=times.index(first_result["time"]))
    else:
        ev = evaluate_foehn(nord, sued, time_index=0)

    ev["worst_level_today"] = worst_level
    ev["hourly"] = results_by_hour[:24]  # max 24 Einträge

    return {"success": True, "foehn": ev, "hourly": results_by_hour}


if __name__ == "__main__":
    r = get_foehn_for_dashboard()
    if r["success"]:
        f = r["foehn"]
        print(f"Foehn: {f['label']} ({f['level']})")
        print(f"  Delta-P: {f['delta_p_hpa']} hPa")
        print(f"  Hoehenwind 700hPa: {f['crest_wind_kmh']} km/h aus {f['crest_dir_deg']} deg")
        print(f"  Luftfeuchtigkeit: {f['humidity_nord']}%")
        for ind in f.get("indicators", []):
            print(f"  - {ind}")
    else:
        print("Fehler:", r.get("error"))
