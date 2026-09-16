"""Reine Funktionen ueber Screening-Zeilen (eine Zeile = ein Spot an einem Tag).

Kein Engine-Import, keine I/O — damit offline testbar. Die Zeilen entstehen in
export.py aus den deterministischen Caches der Engine (_ctx_gust_cache,
_ctx_tq_cache, _ctx_foehn_cache) plus Stundenreihen aus den Rohdaten.

Wichtig fuer Claude: search_spots meldet immer, wie viele Zeilen geprueft und
warum welche ausgeschlossen wurden — Claude darf nie aus einer stillen
Teilmenge schliessen.
"""
from __future__ import annotations

from collections import Counter, OrderedDict

# Reihenfolge = Reihenfolge in der Ausschluss-Zusammenfassung.
EXCLUSION_REASONS = OrderedDict([
    ("no_window", "kein sauberes Startfenster (Windrichtung passt nicht oder harte Warnungen)"),
    ("gusts", "Boeen-DANGER am Boden oder in der Hoehe"),
    ("aloft_wind", "Hoehenwind-DANGER in der Flugschicht"),
    ("thunderstorm", "Gewitter im Startfenster"),
    ("rain", "Regen im Startfenster"),
    ("foehn", "Foehn-Level danger fuer diesen Startplatz"),
    ("cloud_below_takeoff", "Wolkenbasis auf/unter Startplatzhoehe"),
    # optionale Pilotenfilter
    ("max_gust", "Boeen ueber dem gewaehlten Maximum"),
    ("min_thermal", "zu wenig Thermikstunden / zu schwaches Steigen"),
    ("region", "nicht in den gewaehlten Regionen"),
    ("date", "nicht an den gewaehlten Tagen"),
    ("near", "ausserhalb des gewaehlten Umkreises"),
])

DEFAULT_SORT = "window"
SORT_KEYS = {
    # laengstes Fenster zuerst, dann wenig harte Warnungen, dann Thermik
    "window": lambda r: (-r["longest_clean_h"], r["hard_warn_h"], -r["prod_h"], -(r["peak_climb"] or 0)),
    "thermal": lambda r: (-r["prod_h"], -(r["peak_climb"] or 0), -r["longest_clean_h"]),
    "calm": lambda r: ((r["gust_max"] or 0), r["hard_warn_h"], -r["longest_clean_h"]),
    "name": lambda r: (r["spot"], r["date"]),
}


def default_filters(thresholds: dict) -> dict:
    """Standardfilter aus dem config-Snapshot des Exports (meta.thresholds)."""
    return {
        "min_clean_h": int(thresholds.get("CLEAN_WINDOW_MIN_HOURS", 2)),
        "allow_gust_danger": False,
        "allow_aloft_danger": False,
        "allow_thunder": False,
        "allow_rain_h": 0,
        "allow_foehn_danger": False,
        # Standard AUS: eine Stratus-Stunde am Morgen wuerde sonst den ganzen Tag
        # streichen (17.09.: 286 von 494). Stunden mit Basis unter Start sind
        # ohnehin keine sauberen Fensterstunden (OVERCAST-DANGER ist hartes Tag);
        # die Zeile zeigt den Wert als "!! BASIS<START Nh".
        "allow_cloud_below_takeoff": True,
        # Pilotenfilter (aus)
        "max_gust": None,
        "min_thermal_h": None,
        "min_peak_climb": None,
        "regions": None,
        "dates": None,
        "near": None,  # {"lat":..,"lon":..,"km":..}
    }


def reasons_for_row(row: dict, f: dict) -> list[str]:
    """Alle zutreffenden Ausschlussgruende einer Zeile (Mehrfachnennung)."""
    reasons: list[str] = []
    if row["longest_clean_h"] < f["min_clean_h"]:
        reasons.append("no_window")
    if not f["allow_gust_danger"] and (row["gust_danger_h"] + row["aloft_gust_danger_h"]) > 0:
        reasons.append("gusts")
    if not f["allow_aloft_danger"] and row["aloft_danger_h"] > 0:
        reasons.append("aloft_wind")
    if not f["allow_thunder"] and row["thunder_win_h"] > 0:
        reasons.append("thunderstorm")
    if row["rain_win_h"] > (f["allow_rain_h"] or 0):
        reasons.append("rain")
    if not f["allow_foehn_danger"] and row["foehn_level"] == "danger":
        reasons.append("foehn")
    if not f["allow_cloud_below_takeoff"] and row["cloud_below_to_h"] > 0:
        reasons.append("cloud_below_takeoff")
    if f.get("max_gust") is not None and (row["gust_max"] or 0) > f["max_gust"]:
        reasons.append("max_gust")
    if f.get("min_thermal_h") is not None and row["thermal_h"] < f["min_thermal_h"]:
        reasons.append("min_thermal")
    if f.get("min_peak_climb") is not None and (row["peak_climb"] or 0) < f["min_peak_climb"]:
        reasons.append("min_thermal")
    if f.get("regions") and row["region_id"] not in f["regions"] and row["region"] not in f["regions"]:
        reasons.append("region")
    if f.get("dates") and row["date"] not in f["dates"]:
        reasons.append("date")
    near = f.get("near")
    if near:
        if haversine_km(near["lat"], near["lon"], row["lat"], row["lon"]) > near["km"]:
            reasons.append("near")
    return reasons


SCOPE_REASONS = ("region", "date", "near")


def apply_filters(rows: list[dict], f: dict) -> tuple[list[dict], dict]:
    """Teilt Zeilen in behalten/ausgeschlossen. Liefert (kept, summary).

    Bereichsfilter (Tage, Regionen, Umkreis) grenzen nur ein und zaehlen nicht
    als Ausschluss — sonst liest Claude "near 1161 ausgeschlossen" als Warnung.

    summary = {
      "total": n, "out_of_scope": n, "checked": n, "excluded": n, "kept": n,
      "by_reason": Counter (Mehrfachnennung moeglich),
      "no_window_split": {"wind_sector": n, "hard_warnings": n},
    }
    """
    kept: list[dict] = []
    by_reason: Counter = Counter()
    split = Counter()
    excluded = out_of_scope = 0
    for r in rows:
        reasons = reasons_for_row(r, f)
        if any(x in SCOPE_REASONS for x in reasons):
            out_of_scope += 1
            continue
        if reasons:
            excluded += 1
            by_reason.update(reasons)
            if "no_window" in reasons:
                split["wind_sector" if r["wind_ok_h"] == 0 else "hard_warnings"] += 1
        else:
            kept.append(r)
    return kept, {
        "total": len(rows),
        "out_of_scope": out_of_scope,
        "checked": len(rows) - out_of_scope,
        "excluded": excluded,
        "kept": len(kept),
        "by_reason": by_reason,
        "no_window_split": dict(split),
    }


def rank(rows: list[dict], sort: str = DEFAULT_SORT) -> list[dict]:
    key = SORT_KEYS.get(sort or DEFAULT_SORT, SORT_KEYS[DEFAULT_SORT])
    return sorted(rows, key=key)


def overview_counts(rows: list[dict], f: dict) -> dict:
    """{(region, date): {"pass": n, "total": n, "thunder_pct": max}} fuer die Uebersicht."""
    out: dict = {}
    for r in rows:
        k = (r["region"], r["date"])
        cell = out.setdefault(k, {"pass": 0, "total": 0, "thunder_pct": None})
        cell["total"] += 1
        if not reasons_for_row(r, f):
            cell["pass"] += 1
        tp = r.get("region_thunder_pct")
        if tp is not None:
            cell["thunder_pct"] = tp if cell["thunder_pct"] is None else max(cell["thunder_pct"], tp)
    return out


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    import math
    if None in (lat1, lon1, lat2, lon2):
        return float("inf")
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def windows_from_hours(hour_strs: list[str]) -> str:
    """['10:00','11:00','13:00'] -> '10-12,13-14' (Ende exklusiv = Stundenzahl)."""
    if not hour_strs:
        return "-"
    try:
        hours = sorted(set(int(h.split(":")[0]) for h in hour_strs))
    except (ValueError, IndexError):
        return "-"
    runs = []
    start = prev = hours[0]
    for h in hours[1:]:
        if h == prev + 1:
            prev = h
            continue
        runs.append((start, prev))
        start = prev = h
    runs.append((start, prev))
    return ",".join(f"{s:02d}-{e + 1:02d}" for s, e in runs)
