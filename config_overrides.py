"""
Runtime-Overlay fuer config.py.

Speichert editierbare Config-Werte in data/config_overrides.json und wendet sie
beim App-Start sowie bei jedem Save via setattr(config, k, v) direkt auf das
config-Modul an. Da alle Aufrufer config.X (nicht `from config import X`)
verwenden, greifen Aenderungen sofort — Neustart nur fuer tiefgreifende
Struktur-Aenderungen noetig.

Secrets (API-Keys, SMTP, Passwoerter, DB-Tokens) sind NICHT im Schema
enthalten und koennen ueber dieses UI nicht gelesen oder gesetzt werden.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)

OVERRIDE_PATH: Path = config.DATA_DIR / "config_overrides.json"


# ---------------------------------------------------------------------------
# SCHEMA — welche Keys sind editierbar, in welcher Gruppe, mit Hilfetext.
# ---------------------------------------------------------------------------
# type:    "int" | "float" | "bool" | "str" | "choice" | "weekdays"
# choices: nur fuer "choice" — Liste erlaubter Werte
# min/max: optional fuer Zahlen (clientseitige Validierung)
# step:    optional fuer Zahlen
# unit:    optional — wird in UI hinter Input angezeigt
# help:    kurze Erklaerung (Tooltip + Muted-Subline)
# ---------------------------------------------------------------------------

SCHEMA: dict[str, dict[str, list[dict]]] = {
    "meteo": {
        "Wind-Schwellen (Hoehenwind)": [
            {"key": "ALOFT_DANGER_KMH", "type": "int", "min": 0, "max": 100, "unit": "km/h",
             "help": "Hoehenwind im Flugbereich ab dem die Stunde als gefaehrlich (ALOFT-DANGER) gewertet wird. Wird auch in Skill-Texten verwendet."},
            {"key": "ALOFT_WARN_KMH", "type": "int", "min": 0, "max": 100, "unit": "km/h",
             "help": "Hoehenwind ab dem ALOFT-WARN vergeben wird (kraeftig, aber noch nicht gefaehrlich)."},
            {"key": "ALOFT_DANGER_CONDITIONAL_HOURS", "type": "int", "min": 0, "max": 12, "unit": "h",
             "help": "Anzahl Stunden mit ALOFT-DANGER, ab der der Tag von 'safe' auf 'conditional' herabgestuft wird."},
            {"key": "ALOFT_DANGER_NOTSAFE_HOURS", "type": "int", "min": 0, "max": 12, "unit": "h",
             "help": "Anzahl Stunden mit ALOFT-DANGER, ab der der Tag hart auf 'not_safe' gesetzt wird."},
            {"key": "WIND_DIRECTION_TOLERANCE_PCT", "type": "float", "min": 0.0, "max": 1.0, "step": 0.05,
             "help": "Erlaubte Windrichtungs-Abweichung vom Startplatz-Sektor, als Anteil der Sektorbreite (0.10 = 10%)."},
        ],
        "Wind-Schwellen (Bodenwind, Regionen)": [
            {"key": "WIND_STRONG_KMH", "type": "int", "min": 0, "max": 100, "unit": "km/h",
             "help": "Grundwind ab dem [WIND-STRONG] vergeben wird — Region unfliegbar. Skill-Texte nutzen diesen Wert."},
            {"key": "WIND_MODERATE_KMH", "type": "int", "min": 0, "max": 100, "unit": "km/h",
             "help": "Grundwind ab dem [WIND-MODERATE] vergeben wird (sportlich, noch fliegbar). Darunter: WIND-CALM."},
        ],
        "Boeen-Schwellen (Bodenboeen, Spots)": [
            {"key": "GUST_WARN_KMH", "type": "int", "min": 0, "max": 100, "unit": "km/h",
             "help": "Boeen ab dem [GUST-WARN] vergeben wird (sportlich, nicht unfliegbar)."},
            {"key": "GUST_DANGER_KMH", "type": "int", "min": 0, "max": 100, "unit": "km/h",
             "help": "Boeen ab dem [GUST-DANGER] vergeben wird — Stunde unfliegbar."},
            {"key": "GUST_SPREAD_KMH", "type": "int", "min": 0, "max": 50, "unit": "km/h",
             "help": "Mindest-Exzess (gusts - wind) als zusaetzlicher Trigger fuer [GUST-WARN]."},
            {"key": "GUST_WARN_ABSOLUTE_KMH", "type": "int", "min": 0, "max": 100, "unit": "km/h",
             "help": "Absolute Boeen-Schwelle (ohne Spread-Check) fuer [GUST-WARN]."},
        ],
        "Turbulenz-Schwellen (Hoehenboeen T(z), Spots)": [
            {"key": "ALOFT_GUST_WARN_KMH", "type": "int", "min": 0, "max": 100, "unit": "km/h",
             "help": "Turbulenzrisiko T(z) im Flugbereich ab dem [ALOFT-GUST-WARN] vergeben wird."},
            {"key": "ALOFT_GUST_DANGER_KMH", "type": "int", "min": 0, "max": 100, "unit": "km/h",
             "help": "Turbulenzrisiko T(z) ab dem [ALOFT-GUST-DANGER] vergeben wird — extreme Klapper-Gefahr."},
        ],
        "CAPE-Schwellen (Konvektion)": [
            {"key": "CAPE_WARN_JKG", "type": "int", "min": 0, "max": 5000, "unit": "J/kg",
             "help": "CAPE ab dem [CAPE-WARN] vergeben wird — Potenzial fuer Ueberentwicklung vorhanden."},
            {"key": "CAPE_DANGER_JKG", "type": "int", "min": 0, "max": 5000, "unit": "J/kg",
             "help": "CAPE ab dem [CAPE-DANGER] vergeben wird — extrem instabil, Stunde unfliegbar."},
        ],
        "Flyability-Schwellen": [
            {"key": "PRODUCTIVE_CLIMB_MIN", "type": "float", "min": 0.0, "max": 3.0, "step": 0.1, "unit": "m/s",
             "help": "Mindest-Steigrate, ab der eine Stunde als 'produktiv' zaehlt."},
            {"key": "PRODUCTIVE_LOW_CLOUD_MAX", "type": "int", "min": 0, "max": 100, "unit": "%",
             "help": "Max. tiefe Wolken (<3000m) fuer produktive Stunde. Darueber werfen Cu direkten Schatten."},
            {"key": "PRODUCTIVE_MID_CLOUD_MAX", "type": "int", "min": 0, "max": 100, "unit": "%",
             "help": "Max. mittlere Wolken (3000-6000m) fuer produktive Stunde. Altostratus ab ~90% = praktisch tot."},
            {"key": "PRODUCTIVE_HOURS_FOR_GREEN", "type": "int", "min": 1, "max": 12, "unit": "h",
             "help": "Mindest-Anzahl produktive Stunden fuer gray->green Upgrade (Flyability-Tier)."},
            {"key": "PRODUCTIVE_HOURS_DOWNGRADE", "type": "int", "min": 0, "max": 12, "unit": "h",
             "help": "Unter dieser Anzahl produktiver Stunden wird green/violet -> gray herabgestuft."},
            {"key": "PRODUCTIVE_BAND_DEPTH_MIN", "type": "int", "min": 0, "max": 2000, "unit": "m",
             "help": "Mindest-Banddicke (thermal_top - elevation). Unter dieser Tiefe kein nutzbares Hoehenband."},
        ],
        "Violett-Kriterien (XC-Tag)": [
            {"key": "VIOLET_PEAK_MIN", "type": "float", "min": 0.0, "max": 5.0, "step": 0.1, "unit": "m/s",
             "help": "Mindest-Peak-Climb fuer Violett-Kandidat (XC-Tag)."},
            {"key": "VIOLET_HOURS_MIN", "type": "int", "min": 1, "max": 12, "unit": "h",
             "help": "Mindest-Anzahl produktive Stunden fuer Violett."},
            {"key": "VIOLET_ROUGH_MAX", "type": "int", "min": 0, "max": 100, "unit": "%",
             "help": "Max. ROUGH-UNUSABLE-Anteil fuer Violett (saubere Thermik-Anforderung)."},
            {"key": "VIOLET_UNUSABLE_MAX", "type": "int", "min": 0, "max": 100, "unit": "%",
             "help": "Max. Gesamt-UNUSABLE-Anteil fuer Violett."},
            {"key": "VIOLET_CLOUD_LOW_MAX", "type": "int", "min": 0, "max": 100, "unit": "%",
             "help": "Max. Durchschnitt tiefe Wolken ueber Thermikstunden fuer Violett."},
            {"key": "VIOLET_CLOUD_MID_MAX", "type": "int", "min": 0, "max": 100, "unit": "%",
             "help": "Max. Durchschnitt mittlere Wolken ueber Thermikstunden fuer Violett."},
        ],
        "Thermik-Qualitaet": [
            {"key": "THERMAL_QUALITY_MIN_CLIMB", "type": "float", "min": 0.0, "max": 2.0, "step": 0.05, "unit": "m/s",
             "help": "Minimum climb_rate fuer Tag-Aktivierung — unter diesem Wert keine Thermik-Qualitaets-Warnung."},
            {"key": "CONVECTIVE_GUST_BETA", "type": "float", "min": 0.0, "max": 4.0, "step": 0.1,
             "help": "Konvektive Boeen-Korrektur (Panofsky 1977 + COSMO). 1.8 = Default. Hoeher = mehr Boeen-Anteil als 'Thermik-Konvektion' abgezogen."},
            {"key": "GF_DANGER_MIN_MECHANICAL_MS", "type": "float", "min": 0.0, "max": 10.0, "step": 0.5, "unit": "m/s",
             "help": "Unter diesem mech. Exzess wird bei GF>=danger FRAGMENTED statt UNUSABLE vergeben."},
        ],
        "Flugstunden-Fenster": [
            {"key": "FLIGHT_HOURS_START", "type": "int", "min": 0, "max": 23, "unit": "h",
             "help": "Start-Stunde fuer Flyability-Auswertung (z.B. 10 = 10:00)."},
            {"key": "FLIGHT_HOURS_END", "type": "int", "min": 0, "max": 23, "unit": "h",
             "help": "End-Stunde (exklusiv) fuer Flyability-Auswertung (z.B. 17 = bis 16:59)."},
        ],
        "Bias-Korrektur (Stationsdaten)": [
            {"key": "BIAS_CORRECTION_ENABLED", "type": "bool",
             "help": "Ob die Bias-Korrektur ueberhaupt auf wind_gusts_10m angewendet wird (Spots + Regionen)."},
            {"key": "MULTI_MODEL_GUST_MERGE", "type": "bool",
             "help": "wind_gusts_10m = max(D2, CH1, CH2). Deaktiviert = nur WIND_MODEL verwenden."},
            {"key": "BIAS_LOOKBACK_DAYS", "type": "int", "min": 1, "max": 60, "unit": "d",
             "help": "Zeitfenster fuer Bias-Berechnung. Laenger = stabiler, aber reagiert traeger auf Modell-Updates."},
            {"key": "BIAS_ALPHA", "type": "float", "min": 0.5, "max": 1.0, "step": 0.05,
             "help": "Exponentieller Gewichtungsfaktor. Hoeher = juengere Paare staerker gewichten."},
            {"key": "BIAS_MIN_PAIRS", "type": "int", "min": 1, "max": 30,
             "help": "Mindestanzahl Forecast/Station-Paare bevor Bias angewendet wird."},
            {"key": "BIAS_MAX_CORRECTION", "type": "int", "min": 1, "max": 40, "unit": "km/h",
             "help": "Maximale absolute Bias-Korrektur (Sicherheitslimit)."},
            {"key": "BIAS_ELEV_DECAY_HG", "type": "int", "min": 100, "max": 1000, "unit": "m",
             "help": "Skalenhoehe fuer exponentiellen Decay Station->Spot (Brasseur 2001)."},
            {"key": "STATION_SEARCH_RADIUS_KM", "type": "int", "min": 1, "max": 100, "unit": "km",
             "help": "Suchradius fuer winds.mobi-Stationen um einen Spot."},
            {"key": "STATION_MAX_ELEV_DIFF_M", "type": "int", "min": 50, "max": 1500, "unit": "m",
             "help": "Max. Hoehendifferenz zwischen Station und Spot. Kleiner = weniger Expositions-Verfaelschung."},
            {"key": "STATION_MAX_PER_SPOT", "type": "int", "min": 1, "max": 10,
             "help": "Maximale Anzahl Stationen pro Spot."},
        ],
    },
    "technisch": {
        "Darstellung": [
            {"key": "SHOW_REFERENCE_POINTS", "type": "bool",
             "help": "Zeigt Linien vom Startplatz zu den regionalen Thermik-Referenzpunkten beim Hover auf der Karte."},
        ],
        "Forecast": [
            {"key": "FORECAST_DAYS", "type": "int", "min": 1, "max": 7, "unit": "d",
             "help": "Anzahl Vorhersage-Tage. Open-Meteo max 7. Mehr Tage = mehr API-Weight."},
            {"key": "API_TIMEOUT", "type": "int", "min": 5, "max": 120, "unit": "s",
             "help": "HTTP-Timeout fuer Open-Meteo Requests."},
        ],
        "Briefing-Scheduler": [
            {"key": "DAILY_RUN_TIME", "type": "time",
             "composed_from": ["DAILY_RUN_HOUR", "DAILY_RUN_MINUTE"],
             "help": "Exakte Uhrzeit (HH:MM) an der der taegliche Refresh + Briefing-Versand startet."},
            {"key": "DAILY_RUN_WEEKDAYS", "type": "weekdays",
             "help": "Wochentage, an denen der Daily-Run laeuft. 0=Mo, 6=So."},
        ],
        "LLM-Analyse": [
            {"key": "LLM_ANALYSIS_MODE", "type": "choice", "choices": ["parallel", "batch"],
             "help": "parallel = schnell (viele gleichzeitige Calls). batch = guenstig (OpenAI Batch API, 50% billiger, 5-30 Min)."},
            {"key": "LLM_MAX_WORKERS", "type": "int", "min": 1, "max": 100,
             "help": "Anzahl paralleler LLM-Calls im parallel-Modus. Hoeher = schneller, aber mehr Quota-Verbrauch."},
            {"key": "LLM_BATCH_POLL_INTERVAL", "type": "int", "min": 5, "max": 300, "unit": "s",
             "help": "Poll-Intervall fuer Batch-Status im batch-Modus."},
        ],
    },
}


# ---------------------------------------------------------------------------
# Load / Save / Apply
# ---------------------------------------------------------------------------

def _flat_keys() -> dict[str, dict]:
    """Flacht SCHEMA auf: {key -> field_spec} inkl. section/group zur Lookup."""
    out: dict[str, dict] = {}
    for section, groups in SCHEMA.items():
        for group, fields in groups.items():
            for f in fields:
                out[f["key"]] = {**f, "_section": section, "_group": group}
    return out


def get_overrides() -> dict[str, Any]:
    """Liest aktuelles Overlay aus data/config_overrides.json. Leer bei fehlender Datei."""
    if not OVERRIDE_PATH.exists():
        return {}
    try:
        with open(OVERRIDE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("config_overrides.json konnte nicht gelesen werden: %s", e)
        return {}


def _coerce(value: Any, field: dict) -> Any:
    """Konvertiert Form-String in Ziel-Typ. ValueError bei ungueltigen Werten.

    Fuer type='time' wird die Rueckgabe ein Tupel (hour, minute). Die Aufloesung
    auf die zugrundeliegenden Config-Keys (DAILY_RUN_HOUR, DAILY_RUN_MINUTE)
    erfolgt in apply_overrides() und save_overrides().
    """
    t = field["type"]
    if t == "bool":
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("1", "true", "on", "yes")
    if t == "int":
        return int(value)
    if t == "float":
        return float(value)
    if t == "str":
        return str(value).strip()
    if t == "choice":
        sval = str(value).strip()
        if sval not in field["choices"]:
            raise ValueError(f"Ungueltiger Wert fuer {field['key']}: {sval}")
        return sval
    if t == "weekdays":
        # Erwartet Liste von ints (0-6) oder comma-separated String
        if isinstance(value, (list, set, tuple)):
            items = list(value)
        else:
            items = [x.strip() for x in str(value).split(",") if x.strip() != ""]
        return set(int(x) for x in items if 0 <= int(x) <= 6)
    if t == "time":
        # Erwartet "HH:MM" String; Rueckgabe (hour, minute) Tupel
        sval = str(value).strip()
        if ":" not in sval:
            raise ValueError(f"Ungueltiges Zeitformat fuer {field['key']}: {sval!r} (erwartet HH:MM)")
        h_str, m_str = sval.split(":", 1)
        h, m = int(h_str), int(m_str)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError(f"Zeit ausserhalb 00:00-23:59: {sval!r}")
        return (h, m)
    raise ValueError(f"Unbekannter Typ: {t}")


def apply_overrides(overrides: dict[str, Any] | None = None) -> list[str]:
    """Setzt Overlay-Werte auf das config-Modul. Gibt Liste angewandter Keys zurueck.

    Fuer virtuelle composed-Keys (z.B. DAILY_RUN_TIME) werden die
    zugrundeliegenden Keys (DAILY_RUN_HOUR, DAILY_RUN_MINUTE) gesetzt.
    """
    if overrides is None:
        overrides = get_overrides()
    schema = _flat_keys()
    applied: list[str] = []
    for k, v in overrides.items():
        if k not in schema:
            logger.warning("Override-Key '%s' nicht im Schema — ignoriert.", k)
            continue
        field = schema[k]
        try:
            coerced = _coerce(v, field)
        except (TypeError, ValueError) as e:
            logger.warning("Override '%s' konnte nicht konvertiert werden: %s", k, e)
            continue

        # Virtuelles time-Feld: Tupel (h, m) -> zwei Config-Attribute setzen
        if field["type"] == "time" and "composed_from" in field:
            sub_keys = field["composed_from"]
            if len(sub_keys) != 2 or not isinstance(coerced, tuple) or len(coerced) != 2:
                logger.warning("Ungueltige time-Konfiguration fuer %s", k)
                continue
            setattr(config, sub_keys[0], coerced[0])
            setattr(config, sub_keys[1], coerced[1])
            applied.append(k)
            continue

        setattr(config, k, coerced)
        applied.append(k)
    if applied:
        logger.info("Config-Overrides angewandt: %s", ", ".join(applied))
    return applied


def save_overrides(new_values: dict[str, Any]) -> list[str]:
    """Validiert + speichert Overlay + wendet direkt an. Gibt Liste der Aenderungen zurueck.

    new_values: Roh-Werte aus dem Form-POST (Strings, Listen etc.).
    Schluessel, die NICHT im Schema sind, werden ignoriert (Sicherheit).
    """
    schema = _flat_keys()
    current = get_overrides()
    cleaned: dict[str, Any] = {}
    changed: list[str] = []

    for k, field in schema.items():
        if k not in new_values:
            # Nicht im Form → unveraendert uebernehmen falls bereits im Overlay
            if k in current:
                cleaned[k] = current[k]
            continue

        try:
            coerced = _coerce(new_values[k], field)
        except (TypeError, ValueError) as e:
            logger.warning("save_overrides: Wert fuer %s ignoriert: %s", k, e)
            continue

        # Virtuelles time-Feld: Vergleich mit aktuellem (HOUR, MINUTE) aus config
        if field["type"] == "time" and "composed_from" in field:
            sub_keys = field["composed_from"]
            coerced_for_json: Any = f"{coerced[0]:02d}:{coerced[1]:02d}"
            # Default aus _ORIGINAL_DEFAULTS (pre-overlay state)
            def_h = _ORIGINAL_DEFAULTS.get(sub_keys[0], getattr(config, sub_keys[0], 0))
            def_m = _ORIGINAL_DEFAULTS.get(sub_keys[1], getattr(config, sub_keys[1], 0))
            default_for_compare = f"{def_h:02d}:{def_m:02d}"
        elif field["type"] == "weekdays":
            coerced_for_json = sorted(coerced)
            default_val = _ORIGINAL_DEFAULTS.get(k, getattr(config, k, None))
            default_for_compare = sorted(default_val) if default_val else []
        else:
            coerced_for_json = coerced
            default_for_compare = _ORIGINAL_DEFAULTS.get(k, getattr(config, k, None))

        # Nur speichern wenn abweichend vom Default
        if coerced_for_json == default_for_compare:
            if k in current:
                changed.append(k)  # Entfernt aus Overlay
            continue

        cleaned[k] = coerced_for_json
        if current.get(k) != coerced_for_json:
            changed.append(k)

    # Atomar schreiben
    config.atomic_write_json(OVERRIDE_PATH, cleaned)

    # Sofort anwenden — da alle Aufrufer config.X nutzen, greifen Aenderungen live.
    apply_overrides(cleaned)

    # Defaults fuer entfernte Keys wiederherstellen (Reset auf Default-Wert)
    # Das passiert automatisch, wenn der Key aus dem Overlay faellt — der
    # urspruengliche Wert ist noch im config-Modul, da setattr nicht rueckgaengig
    # gemacht wurde. Wir restaurieren explizit aus den gespeicherten Defaults.
    for k in list(current.keys()):
        if k not in cleaned and k in schema:
            # Reset auf Code-Default. Wir haben den Originalwert nicht mehr, da
            # setattr frueher ueberschrieben hat → reimport des Defaults aus Code:
            _restore_default(k)

    return changed


_ORIGINAL_DEFAULTS: dict[str, Any] = {}


def snapshot_defaults() -> None:
    """Snapshottet Code-Defaults VOR dem ersten apply_overrides.
    Muss EINMAL beim App-Start aufgerufen werden, noch vor apply_overrides().

    Fuer virtuelle composed-Keys werden die zugrundeliegenden Keys
    gesnapshotet (DAILY_RUN_HOUR/MINUTE, nicht DAILY_RUN_TIME).
    """
    schema = _flat_keys()
    for k, field in schema.items():
        if "composed_from" in field:
            for sub in field["composed_from"]:
                if hasattr(config, sub):
                    _ORIGINAL_DEFAULTS[sub] = getattr(config, sub)
        elif hasattr(config, k):
            _ORIGINAL_DEFAULTS[k] = getattr(config, k)


def _restore_default(key: str) -> None:
    schema = _flat_keys()
    field = schema.get(key)
    # Virtuelle composed-Keys: restaurieren die zugrundeliegenden Keys
    if field and "composed_from" in field:
        for sub in field["composed_from"]:
            if sub in _ORIGINAL_DEFAULTS:
                setattr(config, sub, _ORIGINAL_DEFAULTS[sub])
        logger.info("Config-Override '%s' (composed) auf Default zurueckgesetzt.", key)
        return
    if key in _ORIGINAL_DEFAULTS:
        setattr(config, key, _ORIGINAL_DEFAULTS[key])
        logger.info("Config-Override '%s' auf Default zurueckgesetzt.", key)


def current_values() -> dict[str, Any]:
    """Aktuell geltende Werte (Overlay ueber Defaults gemergt).
    Fuer UI-Befuellung. Virtuelle Keys werden aus ihren Sub-Keys komponiert."""
    out: dict[str, Any] = {}
    schema = _flat_keys()
    for k, field in schema.items():
        if field["type"] == "time" and "composed_from" in field:
            sub_keys = field["composed_from"]
            h = getattr(config, sub_keys[0], 0)
            m = getattr(config, sub_keys[1], 0)
            out[k] = f"{int(h):02d}:{int(m):02d}"
            continue
        val = getattr(config, k, None)
        if field["type"] == "weekdays" and isinstance(val, (set, frozenset)):
            val = sorted(val)
        out[k] = val
    return out


def default_values() -> dict[str, Any]:
    """Code-Defaults (was gilt ohne Overlay). Fuer UI-Hint 'Default: X'."""
    out: dict[str, Any] = {}
    schema = _flat_keys()
    for k, field in schema.items():
        if field["type"] == "time" and "composed_from" in field:
            sub_keys = field["composed_from"]
            h = _ORIGINAL_DEFAULTS.get(sub_keys[0], 0)
            m = _ORIGINAL_DEFAULTS.get(sub_keys[1], 0)
            out[k] = f"{int(h):02d}:{int(m):02d}"
            continue
        v = _ORIGINAL_DEFAULTS.get(k)
        if isinstance(v, (set, frozenset)):
            out[k] = sorted(v)
        else:
            out[k] = v
    return out


def init() -> None:
    """Einmal beim App-Start: Defaults sichern + Overlay anwenden."""
    snapshot_defaults()
    apply_overrides()
