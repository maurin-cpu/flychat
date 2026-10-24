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

import math
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

# Südföhn: Wind am Kamm aus S/SW (135°–225°) — Kern-Sektor für den Kammwind-Trigger
SUEDFOEHN_DIR_START = 135
SUEDFOEHN_DIR_END = 225
# Südhalbkreis (Ost über Süd nach West) — Pflichtbedingung für den Δp-Trigger
SUEDFOEHN_HALFCIRCLE_START = 90
SUEDFOEHN_HALFCIRCLE_END = 270

# Schwellenwerte (Gemini-Empfehlung)
THRESHOLD_DELTA_P_CAUTION = 4   # hPa – Vorsicht
THRESHOLD_DELTA_P_DANGER = 8    # hPa – Flugverbot-Empfehlung
THRESHOLD_CREST_WIND_CAUTION = 54   # km/h (15 m/s) – starkes Warnsignal
THRESHOLD_CREST_WIND_DANGER = 180   # km/h (50 m/s) – Flugverbot
THRESHOLD_HUMIDITY_LOW = 40     # % – Föhn „durchgebrochen“
THRESHOLD_GUST_RATIO = 1.5      # Böen/Wind > 1.5 = böig/turbulent

# Bestätigung der Föhnlage durch Wind an den Föhn-Talpunkten
# (data/foehn_talpunkte.geojson). Ergänzung, kein Ersatz für Δp/Kammwind —
# nur das Briefing nutzt sie (docs/FOEHN.md). Eine Flugstunde ist Föhnstunde,
# wenn der Wind aus dem Föhnsektor des Tals kommt, stark genug ist (Mittelwind
# ODER Böe) und die Luft trocken ist. Ein Tal gilt ab TAL_MIN_HOURS als bestätigt.
TAL_WIND_MIN_KMH = 20
TAL_GUST_MIN_KMH = 30
TAL_RH_MAX = 60
TAL_MIN_HOURS = 2
# "Richtung + trockene Luft": die Modelle zeigen Foehnwind zu schwach (Blog
# wetterkunde/foehn, Fall 26.-28.08.2026: Mittelwind 3-4, Boeen knapp 8 km/h
# unter der Messung). Schwelle minus dieser Fehler — ohne Mindestwind zaehlte
# jede schwache, trockene Talbrise im 180°-Sektor (Vorschau 14.10.2026: bis
# 16 von 23 Taelern bei 10 km/h, auf beiden Seiten zugleich).
TAL_WIND_WEAK_KMH = TAL_WIND_MIN_KMH - 4
TAL_GUST_WEAK_KMH = TAL_GUST_MIN_KMH - 8
# Feuchte genauso: Modelle zeigen Foehnluft ~8 Prozentpunkte zu feucht (Blog,
# Fall 26.-28.08.). Validierung 07.10.2026 Davos: Richtung SW + Boeen 30 km/h, Feuchte
# 59-62 % -> mit 60 % verpasst, Foehnindex zeigte 5 Foehnstunden.
TAL_RH_WEAK = TAL_RH_MAX + 8
# Föhnsektor je foehn_typ (Grad, im Uhrzeigersinn von lo nach hi; Nord über 0°)
TAL_SEKTOR = {
    "Süd": (SUEDFOEHN_HALFCIRCLE_START, SUEDFOEHN_HALFCIRCLE_END),   # 90–270
    "Süd(-ost)": (45, 225),     # Wallis: Föhn aus E/SE (Visp, Sion)
    "Nord": (270, 90),
}

# ============================================================================
# VIER FÖHN-INDIKATOREN fürs Briefing (Blog wetterkunde/foehn, User 15.10.2026)
# ============================================================================
# Das Briefing zählt, wie viele der vier Planungszeichen aus dem Blog die Daten
# zeigen — nie ein Urteil "Föhn"/"kein Föhn". Grenzen:
# 1 Druck: Δp Lugano–Zürich ab 4 hPa (Blog: ab 4 hPa Föhn möglich).
# 2 Windkarte (wie der Pilot die Windkarte liest, User 15.10.2026): Raster aus
#   ICON-CH1/CH2-Prognosepunkten (~8 km) über die Alpenregionen. Ein Punkt ist "rot",
#   wenn er mind. 2 h Mittelwind ab 30 oder Böen ab 50 km/h aus der Föhnrichtung
#   zeigt; eine Region zählt ab einem Viertel roter Punkte. Föhnrichtung je Region
#   aus regionen.csv `kritischer_foehn` (Süd/Nord/Beide); Mittelland und Jura
#   zählen nicht (Kaltfront-Nordwind im Jura 17.10.2026 ist kein Föhn).
#   Test 15.10.2026: Föhntag 27.08. 17 % der Punkte rot aus S, sonst <= 1 %.
#   Statt Kammpunkten: 5 Pässe zeigten am 15.10. bei NW-Strömung "3 von 5".
#   VORLÄUFIGE Grenzen — Abgleich gegen den Föhnindex 2026 steht aus.
KARTE_PASS_SECTOR = {"sued": (135, 225), "nord": (315, 45)}
KARTE_WIND_KMH = 30
KARTE_GUST_KMH = 50
KARTE_REGION_SHARE = 0.25
KARTE_MIN_REGIONS = 3
# Welche Regionen je Föhnrichtung zählen, steht in regionen.csv `kritischer_foehn`
# (Süd / Nord / Beide) — dieselbe Quelle wie die Regionsbewertung. "Beide" zählt für
# beide Richtungen (User 24.10.2026: "alle Regionen, die vom Föhn betroffen sind");
# Regionen nur mit Süd zählen keinen Nordwind und umgekehrt.


def karte_min_regions(total: int) -> int:
    """Regionen, ab denen das Zeichen zählt: KARTE_MIN_REGIONS, bei wenigen Lee-Regionen
    die Hälfte (Nordföhn: 2 von 3)."""
    return max(1, min(KARTE_MIN_REGIONS, math.ceil(total / 2)))
KARTE_TERRAIN = ("voralpen", "alpen", "hochalpin")
KARTE_STEP_LAT, KARTE_STEP_LON = 0.07, 0.1
# 3 Luv-Seite auf ~2000 m (800 hPa) kühler ab 2 °C (SHV: 1–2 °C = Föhnzeichen;
#   obere Grenze, weil 1.5 °C an ruhigen Tagen vorkommt, 16.10.2026).
LUV_COOLER_MIN_K = 2.0
# 4 Föhn-Talpunkte: mindestens ein Tal mit trockenem Wind aus Föhnrichtung
#   (evaluate_talpunkt dir_dry).
DP_INDICATOR_HPA = THRESHOLD_DELTA_P_CAUTION


# Modelle der Föhn-Indikatoren (User 24.10.2026: wie die Spot-Daten und die Fronten
# "ICON-CH1/ICON-D2"): Bodenwerte aus MeteoSwiss ICON — CH1, nach dessen ~33 h CH2.
# Höhenwerte (…hPa) liefert ICON-CH bei Open-Meteo nicht (nachgemessen 24.10.) —
# dafür ICON-D2, nach dessen 48 h ICON-EU. Druckunterschied CH1 vs. D2 Juli–Okt.:
# Median +0.2 hPa, 4-hPa-Zeichen an 58 statt 52 von 115 Tagen (alle 4.1–4.3 hPa).
FOEHN_SURFACE_MODELS = (config.SURFACE_PRIMARY_MODEL, config.SURFACE_SECONDARY_MODEL)
FOEHN_PL_MODELS = (config.PRESSURE_LEVEL_PRIMARY_MODEL, config.PRESSURE_LEVEL_FALLBACK_MODEL)


def _models_for(key: str) -> tuple:
    return FOEHN_PL_MODELS if "hPa" in key else FOEHN_SURFACE_MODELS


def _merge_models(point: dict) -> dict:
    """Je Stunde der erste Wert in Vorrang-Reihenfolge (_models_for); Schluessel ohne
    Modell-Suffix wie bei einer Ein-Modell-Abfrage. Dazu je Stunde das Modell:
    `model` (Bodenwerte) und `model_pl` (Höhenwerte, falls abgefragt)."""
    h = point.get("hourly") or {}
    times = h.get("time") or []
    alle = FOEHN_SURFACE_MODELS + FOEHN_PL_MODELS
    out, mods = {"time": times}, {}
    for key in {k.rsplit("_" + m, 1)[0] for k in h for m in alle if k.endswith("_" + m)}:
        vals, ms = [None] * len(times), [None] * len(times)
        for m in _models_for(key):
            arr = h.get(f"{key}_{m}") or []
            for i, v in enumerate(arr[:len(times)]):
                if vals[i] is None and v is not None:
                    vals[i], ms[i] = v, m
        out[key], mods[key] = vals, ms
    boden = [k for k in ("pressure_msl", "wind_speed_10m") if k in mods]
    out["model"] = mods[boden[0]] if boden else [None] * len(times)
    hoehe = sorted(k for k in mods if "hPa" in k)
    if hoehe:
        out["model_pl"] = mods["temperature_800hPa" if "temperature_800hPa" in mods else hoehe[0]]
    return {**point, "hourly": out}


def models_in(series: list, indices: list) -> list:
    """Modelle einer Stundenreihe (`hourly["model"]`) in den Stunden `indices`, in
    Vorrang-Reihenfolge — fuer die Modellnamen im Briefing."""
    alle = FOEHN_SURFACE_MODELS + FOEHN_PL_MODELS
    found = {series[i] for i in indices if i < len(series) and series[i]}
    return sorted(found, key=lambda m: alle.index(m) if m in alle else 9)


def fetch_foehn_data(forecast_days: int = 2) -> Optional[dict]:
    """
    Holt Föhn-relevante Daten von Open-Meteo (MeteoSwiss ICON).

    Multi-Point-Abfrage: Nord (Zürich) + Süd (Lugano).
    Quelle fest: Bodenwerte ICON-CH1/CH2, Höhenwerte ICON-D2/EU (FOEHN_SURFACE_MODELS,
    FOEHN_PL_MODELS); `hourly["model"]`/`["model_pl"]` nennen je Stunde das Modell.
    """
    lats = [FOEHN_STATIONS["nord"]["lat"], FOEHN_STATIONS["sued"]["lat"]]
    lons = [FOEHN_STATIONS["nord"]["lon"], FOEHN_STATIONS["sued"]["lon"]]

    params = config.with_api_key({
        "latitude": ",".join(str(x) for x in lats),
        "longitude": ",".join(str(x) for x in lons),
        "hourly": (
            "pressure_msl,relative_humidity_2m,wind_speed_10m,wind_gusts_10m,"
            "wind_speed_700hPa,wind_direction_700hPa,surface_pressure,temperature_2m,"
            "temperature_800hPa"
        ),
        "models": ",".join(FOEHN_SURFACE_MODELS + FOEHN_PL_MODELS),
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

        return {"nord": _merge_models(data[0]), "sued": _merge_models(data[1])}
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
    
    # Südföhn braucht eine Strömung, die die Alpen von Süden her überquert:
    # 700-hPa-Wind im Südhalbkreis (Ost über Süd nach West, 90–270°; Jansing
    # et al. 2022). Backtest 2024–26 gegen den MeteoSchweiz-Föhnindex
    # (validation/foehn/PATTERNS.md, P-2): 62 % der Fehlalarme in Altdorf
    # hatten Δp ≥ 4 bei Höhenwind AUSSERHALB dieses Halbkreises — Westlagen mit
    # Druckgefälle, kein Föhn. Fehlt die Richtung, bleibt die alte Regel.
    crest_south_half = dir_700 is None or (SUEDFOEHN_HALFCIRCLE_START <= dir_700 <= SUEDFOEHN_HALFCIRCLE_END)

    # 1. Druckgradient
    if is_suedfoehn_active:
        indicators.append(f"Delta-P (Südföhn): {delta_p_sued} hPa")
        if delta_p_sued >= THRESHOLD_DELTA_P_CAUTION and not crest_south_half:
            indicators.append(
                f"Südföhn Delta-P >= {THRESHOLD_DELTA_P_CAUTION} hPa, aber Höhenwind aus "
                f"{round(dir_700)}° ohne Südkomponente -> keine Föhnlage")
        elif delta_p_sued >= THRESHOLD_DELTA_P_CAUTION:
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


# ============================================================================
# FÖHN-TALPUNKTE: Bestätigung der Föhnlage durch Wind am Talboden
# ============================================================================

def dir_in_sector(deg: float, lo: float, hi: float) -> bool:
    """True, wenn `deg` im Sektor lo→hi (im Uhrzeigersinn) liegt; lo > hi = über 0°."""
    deg = deg % 360
    return lo <= deg <= hi if lo <= hi else (deg >= lo or deg <= hi)


def tal_side(foehn_typ: str) -> str:
    """'nord' für Nordföhn-Täler (Tessin), sonst 'sued'."""
    return "nord" if (foehn_typ or "").startswith("Nord") else "sued"


def evaluate_talpunkt(hourly: dict, indices: list, foehn_typ: str, sektor=None) -> dict:
    """Föhnstunden eines Talpunkts in den Stunden `indices` (Flugfenster eines Tages).

    hourly: Listen `wind_speed_10m`, `wind_gusts_10m`, `wind_direction_10m`,
    `relative_humidity_2m` (km/h, Grad, %). Föhnstunde = Richtung im Sektor des
    Tals ∧ (Mittelwind ≥ TAL_WIND_MIN_KMH ∨ Böe ≥ TAL_GUST_MIN_KMH) ∧ Feuchte ≤
    TAL_RH_MAX. Die Werte (Spanne Mittelwind, Böenspitze) stammen nur aus den
    Föhnstunden. has_data=False, wenn keine Stunde vollständige Werte hat —
    dann zählt der Punkt nicht mit (nie als "kein Föhn" werten).

    sektor: gemessene Föhnrichtung DIESES Tals [lo, hi] (foehn_talpunkte.geojson,
    14.10.2026: Station ∪ Modell an Föhntagen). Ohne: Halbkreis je foehn_typ.
    """
    if sektor and len(sektor) == 2:
        lo, hi = float(sektor[0]), float(sektor[1])
    else:
        lo, hi = TAL_SEKTOR.get(foehn_typ, TAL_SEKTOR["Süd"])

    def _at(key, i):
        arr = hourly.get(key) or []
        v = arr[i] if i < len(arr) else None
        return float(v) if isinstance(v, (int, float)) else None

    winds, gusts, hours = [], [], []
    all_w, all_g, all_rh = [], [], []
    dir_dry_hours, first_dir_dry = 0, None
    foehn_dirs = []        # Richtungen der Merkmal-Stunden (fuer "Leventina aus W")
    has_data = False
    for i in indices:
        w, g = _at("wind_speed_10m", i), _at("wind_gusts_10m", i)
        d, rh = _at("wind_direction_10m", i), _at("relative_humidity_2m", i)
        if w is None or g is None or d is None or rh is None:
            continue
        has_data = True
        all_w.append(w)
        all_g.append(g)
        all_rh.append(rh)
        in_dir, dry = dir_in_sector(d, lo, hi), rh <= TAL_RH_MAX
        dry_weak = rh <= TAL_RH_WEAK
        # Richtung + trockene Luft, ohne Windstaerke: erkannte im Foehnfall
        # 26.-28.08.2026 84-85 % der Foehnstunden, weil die Modelle den
        # Foehnwind zu schwach zeigen (Blog wetterkunde/foehn, Abschnitt Prognose)
        if in_dir and dry_weak and (w >= TAL_WIND_WEAK_KMH or g >= TAL_GUST_WEAK_KMH):
            if not dir_dry_hours:
                first_dir_dry = i
            dir_dry_hours += 1
            foehn_dirs.append(d)
        if in_dir and (w >= TAL_WIND_MIN_KMH or g >= TAL_GUST_MIN_KMH) and dry:
            winds.append(w)
            gusts.append(g)
            hours.append(i)
    out = {"has_data": has_data, "hours": len(hours),
           "bestaetigt": has_data and len(hours) >= TAL_MIN_HOURS,
           "dir_dry_hours": dir_dry_hours,
           "dir_dry": has_data and dir_dry_hours >= TAL_MIN_HOURS}
    if out["dir_dry"]:
        out["first_dir_dry_index"] = first_dir_dry
    if has_data:
        # Hoechstwerte ueber ALLE Flugstunden, jede Richtung — damit das Briefing
        # auch ohne Foehnstunden die Windstaerke im Tal nennen kann (12.10.2026)
        out.update(all_wind_max_kmh=round(max(all_w)), all_gust_max_kmh=round(max(all_g)),
                   rh_min_pct=round(min(all_rh)))
    if out["bestaetigt"]:
        out.update(wind_min_kmh=round(min(winds)), wind_max_kmh=round(max(winds)),
                   gust_max_kmh=round(max(gusts)), first_index=min(hours))
    if foehn_dirs:
        # Vektormittel der Richtung (nicht arithmetisch: 350° und 10° -> 0°)
        sx = sum(math.sin(math.radians(x)) for x in foehn_dirs)
        cx = sum(math.cos(math.radians(x)) for x in foehn_dirs)
        out["foehn_dir_deg"] = round(math.degrees(math.atan2(sx, cx)) % 360)
    return out


def summarize_taeler(results: list) -> dict:
    """Landesweite Zusammenfassung aus evaluate_talpunkt-Ergebnissen (je Eintrag
    zusätzlich `id`, `tal`, `wind_min/max`, …). Spanne/Spitze über ALLE
    bestätigten Täler — so liegt jede Talzeile innerhalb der Landeswerte."""
    checked = [r for r in results if r.get("has_data")]
    best = [r for r in checked if r.get("bestaetigt")]
    dir_dry = [r for r in checked if r.get("dir_dry")]
    out = {"n_total": len(checked), "n_bestaetigt": len(best),
           # Richtung + trockene Luft (auch ohne starken Wind), inkl. der bestaetigten
           "n_dir_dry": len(dir_dry), "dir_dry_taeler": [r.get("tal", "") for r in dir_dry]}
    with_rh = [r for r in checked if r.get("rh_min_pct") is not None]
    if with_rh:
        low = min(with_rh, key=lambda r: r["rh_min_pct"])
        out.update(rh_min_pct=low["rh_min_pct"], rh_min_tal=low.get("tal", ""))
    # Windstaerke in allen Taelern (jede Richtung) — fuer den Satz ohne Foehnstunden
    with_all = [r for r in checked if r.get("all_gust_max_kmh") is not None]
    if with_all:
        top = max(with_all, key=lambda r: r["all_gust_max_kmh"])
        out.update(all_wind_max_kmh=max(r["all_wind_max_kmh"] for r in with_all),
                   all_gust_max_kmh=top["all_gust_max_kmh"], all_gust_tal=top.get("tal", ""),
                   all_weak=(max(r["all_wind_max_kmh"] for r in with_all) < TAL_WIND_MIN_KMH
                             and top["all_gust_max_kmh"] < TAL_GUST_MIN_KMH))
    if best:
        top = max(best, key=lambda r: r["gust_max_kmh"])
        out.update(wind_min_kmh=min(r["wind_min_kmh"] for r in best),
                   wind_max_kmh=max(r["wind_max_kmh"] for r in best),
                   gust_max_kmh=top["gust_max_kmh"], gust_tal=top["tal"],
                   first_hour=min(r["first_hour"] for r in best))
    return out


_KARTE_PUNKTE: list = []


def karte_punkte() -> list:
    """Rasterpunkte der Windkarte: {lat, lon, region_id, region, sides} — nur Regionen
    der Alpen (KARTE_TERRAIN); `sides` = Föhnrichtungen der Region (kritischer_foehn:
    Süd, Nord oder Beide).
    Punkt-in-Polygon gegen regionen_polygone_mapped.geojson. Einmal je Prozess."""
    if _KARTE_PUNKTE:
        return _KARTE_PUNKTE
    import csv
    import json as _json
    from shapely.geometry import Point, shape
    base = config.FOEHN_TALPUNKTE_PATH.parent
    meta = {}
    with open(base / "regionen.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("terrain_type") not in KARTE_TERRAIN:
                continue
            kf = (r.get("kritischer_foehn") or "").strip()
            sides = {"Süd": ("sued",), "Nord": ("nord",), "Beide": ("sued", "nord")}.get(kf, ())
            meta[r["id"]] = {"region": r.get("region_name", r["id"]), "sides": sides}
    with open(base / "regionen_polygone_mapped.geojson", encoding="utf-8") as f:
        polys = [(ft["properties"]["id"], shape(ft["geometry"]))
                 for ft in _json.load(f)["features"] if ft["properties"].get("id") in meta]
    lat = 45.85
    while lat <= 47.75:
        lon = 6.0
        while lon <= 10.5:
            rid = next((i for i, g in polys if g.contains(Point(lon, lat))), None)
            if rid:
                _KARTE_PUNKTE.append({"lat": round(lat, 2), "lon": round(lon, 2),
                                      "region_id": rid, **meta[rid]})
            lon += KARTE_STEP_LON
        lat += KARTE_STEP_LAT
    return _KARTE_PUNKTE


def fetch_wind_karte(forecast_days: int = 2) -> Optional[dict]:
    """Stundenwind an allen Rasterpunkten (ICON-CH1, dann ICON-CH2, 10 m), Blöcke zu
    150 Punkten. {"model": [je Stunde], "time", "punkte": [{..karte_punkte..,
    "hourly": {...}}]}; None bei Fehler."""
    pts = karte_punkte()
    if not pts:
        return None
    out, times, model = [], None, None
    for i in range(0, len(pts), 150):
        chunk = pts[i:i + 150]
        params = config.with_api_key({
            "latitude": ",".join(str(p["lat"]) for p in chunk),
            "longitude": ",".join(str(p["lon"]) for p in chunk),
            "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
            "models": ",".join(FOEHN_SURFACE_MODELS),
            "forecast_days": forecast_days, "timezone": config.TIMEZONE, "wind_speed_unit": "kmh",
        })
        try:
            resp = requests.get(config.API_URL, params=params, timeout=config.API_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return None
        data = data if isinstance(data, list) else [data]
        if len(data) != len(chunk):
            return None
        for p, d in zip(chunk, data):
            h = _merge_models(d)["hourly"]
            times, model = times or h.get("time"), model or h.get("model")
            out.append({**p, "hourly": {k: h.get(k) or [] for k in
                                        ("wind_speed_10m", "wind_direction_10m", "wind_gusts_10m")}})
    return {"model": model or [], "time": times or [], "punkte": out}


def _num(arr, i):
    v = arr[i] if isinstance(arr, list) and i < len(arr) else None
    return float(v) if isinstance(v, (int, float)) else None


def _side_of(deg) -> Optional[str]:
    if deg is None:
        return None
    for side, (lo, hi) in KARTE_PASS_SECTOR.items():
        if dir_in_sector(deg, lo, hi):
            return side
    return None


def evaluate_wind_karte(karte: Optional[dict], date: str) -> Optional[dict]:
    """Indikator 2: in wie vielen vom Föhn betroffenen Regionen ist die Windkarte "rot"
    aus der Föhnrichtung? Erfüllt ab karte_min_regions je Seite; zählt die Seite, die erfüllt ist
    (sonst die mit dem grösseren Anteil roter Regionen)."""
    if not karte or not karte.get("punkte"):
        return None
    times = karte.get("time") or []
    idx = [i for i, t in enumerate(times)
           if t.startswith(date) and config.FLIGHT_HOURS_START <= int(t[11:13]) < config.FLIGHT_HOURS_END]
    if not idx:
        return None
    per = {}
    for p in karte["punkte"]:
        h = p.get("hourly") or {}
        r = per.setdefault(p["region_id"], {"n": 0, "sued": 0, "nord": 0,
                                           "region": p.get("region", ""), "sides": p.get("sides") or ()})
        r["n"] += 1
        hits = {"sued": 0, "nord": 0}
        first = {"sued": None, "nord": None}
        for i in idx:
            w, d, g = (_num(h.get("wind_speed_10m"), i), _num(h.get("wind_direction_10m"), i),
                       _num(h.get("wind_gusts_10m"), i))
            if w is None or d is None:
                continue
            side = _side_of(d)
            if side and (w >= KARTE_WIND_KMH or (g or 0) >= KARTE_GUST_KMH):
                hits[side] += 1
                if first[side] is None:
                    first[side] = int(times[i][11:13])
        for side in hits:
            if hits[side] >= TAL_MIN_HOURS:
                r[side] += 1
                r.setdefault("first_" + side, []).append(first[side])
    res = {}
    for side in ("sued", "nord"):
        regs = [r for r in per.values() if side in r["sides"]]
        red = sorted([r for r in regs if r["n"] and r[side] / r["n"] >= KARTE_REGION_SHARE],
                     key=lambda r: -r[side] / r["n"])
        # Ab wann: eine Region ist "rot", sobald ein Viertel ihrer Punkte Wind zeigt;
        # der Indikator, sobald genug Regionen dieser Seite rot sind
        need = karte_min_regions(len(regs))
        since = sorted(sorted(r["first_" + side])[math.ceil(KARTE_REGION_SHARE * r["n"]) - 1] for r in red)
        res[side] = {"n": len(red), "total": len(regs), "regions": [r["region"] for r in red], "need": need,
                     "on": bool(regs) and len(red) >= need,
                     "from_hour": since[need - 1] if len(since) >= need else None}

    def anteil(sd):
        return res[sd]["n"] / res[sd]["total"] if res[sd]["total"] else 0

    side = max(("sued", "nord"), key=lambda sd: (res[sd]["on"], anteil(sd), sd == "sued"))
    best = res[side]
    on = best["on"]
    m = karte.get("model")
    return {"on": on, "side": side, "n": best["n"], "total": best["total"], "regions": best["regions"][:3],
            "from_hour": best["from_hour"] if on else None,
            # beide Seiten fuers Label der Tages-Foehnseite ("Regions with north wind 0 of 11")
            "per_side": {sd: {"n": res[sd]["n"], "total": res[sd]["total"]} for sd in ("sued", "nord")},
            "model": models_in(m, idx) if isinstance(m, list) else m}


def evaluate_indicators(nord_hourly: dict, sued_hourly: dict, indices: list,
                        karte: Optional[dict], date: str, taeler: dict) -> dict:
    """Die vier Föhn-Indikatoren eines Tages (Flugfenster `indices` der Zürich/Lugano-Reihe).

    nord/sued_hourly: Zürich/Lugano (pressure_msl, temperature_800hPa).
    karte: fetch_wind_karte (eigene Zeitachse). taeler: {"sued": …, "nord": …}
    (synoptic_context.foehn_tal_for_day). Jeder Indikator {"on": bool, …} oder None,
    wenn Daten fehlen (zählt dann nicht; das Briefing zeigt "—")."""
    times = nord_hourly.get("time") or []

    def _hour(i):
        return int(times[i][11:13]) if i < len(times) else None

    # Modelle der Stationsreihe im Flugfenster: Druck vom Boden-, Temperatur vom
    # Höhenmodell (fetch_foehn_data)
    dp_model = models_in(nord_hourly.get("model") or [], indices)
    tp_model = models_in(nord_hourly.get("model_pl") or nord_hourly.get("model") or [], indices)

    # 1 Druck: grösster Unterschied in eine Richtung über das Flugfenster
    dps, dpn, dp_i = [], [], []
    for i in indices:
        pn, ps = _num(nord_hourly.get("pressure_msl"), i), _num(sued_hourly.get("pressure_msl"), i)
        if pn is not None and ps is not None:
            dps.append(ps - pn)
            dpn.append(pn - ps)
            dp_i.append(i)
    dp = None
    if dps:
        s_max, n_max = max(dps), max(dpn)
        val = round(max(s_max, n_max), 1)
        hs = "sued" if s_max >= n_max else "nord"
        series = dps if hs == "sued" else dpn
        dp = {"on": val >= DP_INDICATOR_HPA, "hpa": val, "high_side": hs, "model": dp_model,
              "from_hour": next((_hour(i) for i, v in zip(dp_i, series) if v >= DP_INDICATOR_HPA), None)}

    # 2 Windkarte
    wk = evaluate_wind_karte(karte, date)

    # 3 Temperatur 800 hPa: Mittel Lugano − Zürich; welche Seite ist kühler?
    dts, dt_i = [], []
    for i in indices:
        tn, ts = (_num(nord_hourly.get("temperature_800hPa"), i),
                  _num(sued_hourly.get("temperature_800hPa"), i))
        if tn is not None and ts is not None:
            dts.append(ts - tn)
            dt_i.append(i)
    dt_mean = sum(dts) / len(dts) if dts else None
    t_side = None if dt_mean is None else ("sued" if dt_mean < 0 else "nord")
    t_on = dt_mean is not None and abs(dt_mean) >= LUV_COOLER_MIN_K

    # 4 Täler je Föhnseite
    rows = {"sued": [], "nord": []}
    total, totals = 0, {"sued": 0, "nord": 0}
    for s, t in (taeler or {}).items():
        if not t:
            continue
        total += t.get("n_total", 0)
        if s in totals:
            totals[s] = t.get("n_total", 0)
        for e in t.get("taeler") or []:
            if e.get("dir_dry") and s in rows:
                rows[s].append({"tal": e.get("tal", ""), "side": s,
                                "gust_kmh": e.get("all_gust_max_kmh") or 0,
                                "from_hour": e.get("first_dir_dry_hour")})

    # Föhnseite des Tages: Seite mit den meisten erfüllten Zeichen. Zeichen der
    # Gegenseite zählen NICHT mit, sondern stehen als "dagegen" im Text
    # (18.10.2026: Windkarte Süd + Davos, aber Druck und Kälte im Norden —
    # zusammengezählt wären es falsche "3 von 4" gewesen).
    votes = {s: 0 for s in ("sued", "nord")}
    for on, s in ((bool(dp and dp["on"]), (dp or {}).get("high_side")),
                  (bool(wk and wk["on"]), (wk or {}).get("side")),
                  (t_on, t_side), (bool(rows["sued"]), "sued"), (bool(rows["nord"]), "nord")):
        if on and s in votes:
            votes[s] += 1
    if votes["sued"] != votes["nord"]:
        side = max(votes, key=votes.get)
    else:   # Gleichstand: der Wind entscheidet, dann der Druck
        side = ((wk or {}).get("side") if (wk or {}).get("on") else None) \
            or ((dp or {}).get("high_side") if (dp or {}).get("on") else None) \
            or (max(rows, key=lambda s: len(rows[s])) if rows["sued"] or rows["nord"] else None) \
            or t_side or (dp or {}).get("high_side") or "sued"

    if dp:
        same = dp["high_side"] == side
        dp["against"], dp["on"] = dp["on"] and not same, dp["on"] and same
    if wk:
        same = wk["side"] == side
        wk["against"], wk["on"] = wk["on"] and not same, wk["on"] and same
    tp = None
    if dt_mean is not None:
        cool = round(-dt_mean if side == "sued" else dt_mean, 1)   # > 0: Föhnseite kühler
        tp = {"on": t_on and t_side == side, "against": t_on and t_side != side,
              "cooler_k": cool, "side": side, "model": tp_model, "from_hour": None}
        if tp["on"]:   # erste Stunde, in der die Föhnseite um die Grenze kühler ist
            sign = -1 if side == "sued" else 1
            tp["from_hour"] = next((_hour(i) for i, v in zip(dt_i, dts) if sign * v >= LUV_COOLER_MIN_K), None)
    va = None
    if total:
        mine = sorted(rows[side], key=lambda e: -e["gust_kmh"])
        other = "nord" if side == "sued" else "sued"
        hours = [e["from_hour"] for e in mine if e.get("from_hour") is not None]
        # "of N" = Täler, in denen Föhn dieser Seite vorkommt (Label "Valleys with dry north wind")
        va = {"on": bool(mine), "n": len(mine), "total": totals[side] or total, "top": mine[0] if mine else None,
              "against": bool(rows[other]) and not mine, "n_other": len(rows[other]),
              "from_hour": min(hours) if hours else None,
              "model": next((t.get("model") for t in (taeler or {}).values() if t and t.get("model")), None)}

    ind = {"side": side, "pressure": dp, "wind_map": wk, "luv_cooler": tp, "valleys": va}
    ind["n_on"] = sum(1 for k in ("pressure", "wind_map", "luv_cooler", "valleys")
                      if (ind[k] or {}).get("on"))
    # Ab wann zeigen die Daten das erste erfüllte Zeichen (wie "Front signs · from ~HH:00")
    ind["from_hour"] = min((ind[k]["from_hour"] for k in ("pressure", "wind_map", "luv_cooler", "valleys")
                            if (ind[k] or {}).get("on") and ind[k].get("from_hour") is not None), default=None)
    return ind
