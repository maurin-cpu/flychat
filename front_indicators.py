"""Frontzeichen in den eigenen Prognosedaten — für den Fronten-Block im Briefing.

Gleiche Bauart wie die Föhn-Indikatoren (foehn_indicators.evaluate_indicators):
das Briefing nennt zuerst, was die DWD-Prognosekarte zeigt, und zählt dann,
welche von vier Zeichen das Modell ab welcher Stunde zeigt. Es sagt nie "die
Front kommt" (User 16./17.10.2026), nur "Zeichen in den Daten".

Zeichen je Fronttyp (DHV-Unterlagen: Kaltfront = rasche Abkühlung, Winddrehung,
Schauer; Warmfront = Aufzug/Abschattung, Erwärmung, Dauerregen):
  kalt      : DWD-Karte, kälter auf 1500 m, Winddrehung in der Höhe, Regen
  warm      : DWD-Karte, Bewölkung verdichtet sich, wärmer auf 1500 m, Dauerregen
  okklusion : DWD-Karte, Bewölkung verdichtet sich, Luftmasse ändert sich, Regen

Jedes Modellzeichen ist eine ÄNDERUNG über 6 h (nicht ein Zustand — sonst schlägt
"Bewölkung" an jedem bewölkten Tag ab Mitternacht an). Eine Zone zeigt ein
Zeichen ab der ersten Stunde, in der es mindestens KARTE-unabhängig SHARE der
Startplätze der Zone trifft. Grenzen VORLÄUFIG — Prüfung gegen SwissMetNet steht aus.
"""

import csv
from datetime import datetime, timedelta
from typing import Optional

import config

SHARE = 0.30            # Anteil Startplätze einer Zone
T_CHANGE_K = 2.0        # Temperatur 850 hPa in 6 h
TURN_DEG = 60           # Winddrehung 700 hPa in 6 h ...
TURN_MIN_KMH = 15       # ... bei mindestens so viel Wind
RAIN_MMH = 0.5          # Regenstunde
RAIN_CONT_H = 3         # Dauerregen: so viele Regenstunden in Folge
CLOUD_PCT = 80          # Bewölkung (mittel/hoch) erreicht ...
CLOUD_RISE = 30         # ... und hat in 6 h so stark zugenommen
LOOKBACK_H = 6
CARRY_MAX_H = 1         # Zeichen ab 00/01 Uhr = läuft seit dem Vorabend (Rest vom Vortag)

SETS = {"kalt": ("dwd", "kaelter", "dreh", "regen"),
        "warm": ("dwd", "wolken", "waermer", "dauerregen"),
        "okklusion": ("dwd", "wolken", "luft", "regen")}
MODEL_SIGNS = ("kaelter", "waermer", "luft", "dreh", "regen", "dauerregen", "wolken")


def _zone_of_region_name() -> dict:
    out = {}
    with open(config.PROJECT_ROOT / "data" / "regionen.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("zone"):
                out[(r.get("region_name") or "").strip()] = r["zone"]
                out[r["id"]] = r["zone"]
    return out


def _num(v):
    return float(v) if isinstance(v, (int, float)) else None


def _dirdiff(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def _series(spot: dict, day: str) -> list:
    """Stundenwerte von LOOKBACK_H vor Tagesbeginn bis Tagesende."""
    start = datetime.fromisoformat(day) - timedelta(hours=LOOKBACK_H)
    hd_all = spot.get("hourly_data") or {}
    pl_all = spot.get("pressure_level_data") or {}
    out = []
    for h in range(24 + LOOKBACK_H):
        t = (start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:00")
        hd, pl = hd_all.get(t) or {}, pl_all.get(t) or {}
        cl = None
        if hd:
            cl = max(_num(hd.get("cloud_cover_mid")) or 0, _num(hd.get("cloud_cover_high")) or 0)
        out.append({"p": _num(hd.get("precipitation")), "t": _num(pl.get("temperature_850hPa")),
                    "d": _num(pl.get("wind_direction_700hPa")), "v": _num(pl.get("wind_speed_700hPa")),
                    "c": cl})
    return out


def _zone_signs(rows: list) -> dict:
    """{zeichen: erste Stunde (0-23)} einer Zone aus den Stundenreihen ihrer Startplätze."""
    first = {}
    L = LOOKBACK_H
    for h in range(24):
        i = h + L
        c = dict.fromkeys(("kaelter", "waermer", "dreh", "regen", "dauerregen", "wolken"), 0)
        n = 0
        for r in rows:
            cur, old = r[i], r[i - L]
            if cur["t"] is None:
                continue
            n += 1
            if old["t"] is not None:
                if cur["t"] - old["t"] <= -T_CHANGE_K:
                    c["kaelter"] += 1
                elif cur["t"] - old["t"] >= T_CHANGE_K:
                    c["waermer"] += 1
            if (cur["d"] is not None and old["d"] is not None and (cur["v"] or 0) >= TURN_MIN_KMH
                    and _dirdiff(cur["d"], old["d"]) >= TURN_DEG):
                c["dreh"] += 1
            if (cur["p"] or 0) >= RAIN_MMH:
                c["regen"] += 1
            if all((x["p"] or 0) >= RAIN_MMH for x in r[i - RAIN_CONT_H + 1:i + 1]):
                c["dauerregen"] += 1
            if (cur["c"] is not None and old["c"] is not None and cur["c"] >= CLOUD_PCT
                    and cur["c"] - old["c"] >= CLOUD_RISE):
                c["wolken"] += 1
        for k, cnt in c.items():
            if n and cnt / n >= SHARE and k not in first:
                first[k] = h
    if "kaelter" in first or "waermer" in first:
        first["luft"] = min(first.get("kaelter", 99), first.get("waermer", 99))
    return first


def detect_front_signs(weather_cache: dict, forecast_dates: list,
                       spot_region: Optional[dict] = None) -> Optional[dict]:
    """{"per_day": [{"date", "zones": {zone: {zeichen: stunde}}}]} aus wetterdaten.json.
    spot_region: {Spotname: analyse_region} (synoptic_context.build_spot_region_map)."""
    if not weather_cache or not forecast_dates:
        return None
    if spot_region is None:
        from engine.synoptic_context import build_spot_region_map
        spot_region = build_spot_region_map()
    zone_of = _zone_of_region_name()
    by_zone: dict = {}
    for name, spot in weather_cache.items():
        if name.startswith("_") or not isinstance(spot, dict):
            continue
        z = zone_of.get(spot_region.get(name, ""))
        if z:
            by_zone.setdefault(z, []).append(spot)
    if not by_zone:
        return None
    per_day = []
    for day in forecast_dates:
        zones = {z: _zone_signs([_series(s, day) for s in spots]) for z, spots in by_zone.items()}
        per_day.append({"date": day, "zones": zones})
    return {"per_day": per_day, "share": SHARE, "lookback_h": LOOKBACK_H}


def evaluate_front_signs(zones: dict, dwd: Optional[dict]) -> dict:
    """Zählung eines Tages. zones: {zone: {zeichen: stunde}} (detect_front_signs);
    dwd: {"typ", "zone_hours": {zone: stunde}} oder None (keine Front auf der Karte).

    Returns {"typ", "keys", "first": {zeichen: stunde|None}, "carried": [..],
             "counted": [..], "n_on", "from_hour" (erstes gezähltes Modellzeichen),
             "dwd_zone_hours"}."""
    if dwd and dwd.get("typ"):
        typ = dwd["typ"] if dwd["typ"] in SETS else "okklusion"
    else:
        kalt = sum(1 for f in (zones or {}).values() if "kaelter" in f)
        warm = sum(1 for f in (zones or {}).values() if "waermer" in f)
        typ = "kalt" if kalt >= warm else "warm"
    keys = SETS[typ]
    first = {}
    for k in keys:
        if k == "dwd":
            first[k] = 0 if dwd else None
        else:
            first[k] = min((f[k] for f in (zones or {}).values() if k in f), default=None)
    carried = [k for k in keys if k != "dwd" and first[k] is not None and first[k] <= CARRY_MAX_H]
    counted = [k for k in keys if first[k] is not None and k not in carried]
    model = [k for k in counted if k != "dwd"]
    return {"typ": typ, "keys": list(keys), "first": first, "carried": carried,
            "counted": counted, "n_on": len(counted),
            "from_hour": min((first[k] for k in model), default=None),
            "dwd_zone_hours": dict((dwd or {}).get("zone_hours") or {})}
