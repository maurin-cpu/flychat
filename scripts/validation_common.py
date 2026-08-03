# -*- coding: utf-8 -*-
"""Gemeinsame Bausteine aller Validierungs-Domänen (validation/README.md).

Enthält, was sich zwischen den Domänen wirklich teilt:
  1. SwissMetNet-Zugriff (MeteoSchweiz OGD) + Station→Region-Zuordnung
  2. die Gewitter-/Schauer-Signatur auf Stundenwerten
  3. das einheitliche Urteils-Schema (treffer | verpasst | fehlalarm | still)

Bewusst NICHT hier: die Wahrheits-Beschaffung anderer Domänen (XContest =
Mensch, Fronten = DWD-Handanalyse) — gemeinsam ist der Takt, nicht der
Richter.
"""
from __future__ import annotations

import csv
import datetime
import io
import json
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent

SMN_BASE = "https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn"
_UA = {"User-Agent": "wingcast-validation/1.0"}
_TAIL_BYTES = 600_000          # HTTP-Range vom Dateiende — deckt mehrere Wochen Stundenwerte
_TZ = ZoneInfo("Europe/Zurich")

REGION_GEOJSON = ROOT / "data" / "regionen_polygone_mapped.geojson"

# --- Mess-Signaturen (Zehnminutenwerte, 30-Minuten-Fenster) ---------------
# Gewitter: konvektiver Guss MIT Kaltluft-/Böenausfluss im selben 30-min-
# Fenster. Kein Blitzbeweis — die nächstbeste messbare Näherung (Grenzen:
# validation/gewitter/README.md). Schauer: Beleg für hochgewachsene Wolken.
#
# BEWUSST Zehnminutenwerte statt Stundenwerte: die Stunden-Aggregation
# verwässert die Signatur — die beiden realen Gewitter vom 02.08. (Altdorf
# 21:50: +21 km/h in 30 min, Interlaken 20:00: 3,6 mm/30 min) fielen auf
# Stundenbasis beide unter die Schwellen (Böensprung +14, Regen unter 4 mm/h).
STORM_RAIN_MM30 = 3.0        # mm in 30 Minuten
STORM_GUST_JUMP_KMH = 15.0   # Böensprung gegen 30 min davor
STORM_TEMP_DROP_K = -2.0     # Temperatursturz gegen 30 min davor
SHOWER_RAIN_MM30 = 1.5

# AUSFLUSS-Signatur (03.08.2026): konvektive Kaltluft OHNE Regen an der
# Station — Böensprung + Temperatursturz + Druckanstieg. Markiert den blinden
# Fleck der Gewitter-Signatur (Regenkern verfehlt die Station, Böenfront
# kommt trotzdem an) — bewusst KEIN Gewitter-Beweis: exakt dieses Muster
# erzeugte die trockene Böenfront vom 30.07. an 45 Stationen ohne ein
# einziges Gewitter. Wird nur GESPEICHERT (messwerte/urteile), nie angezeigt
# und aendert kein Urteil. Schwellen = die an 139 Stationen validierte
# Dichtestroemungs-Signatur der Böenfront-Analyse vom 30.07.
OUTFLOW_GUST_JUMP_KMH = 15.0
OUTFLOW_TEMP_DROP_K = -1.0
OUTFLOW_PRES_RISE_HPA = 0.2

VERDICTS = ("treffer", "verpasst", "fehlalarm", "still")


def _fetch(url: str, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={**_UA, **(headers or {})})
    return urllib.request.urlopen(req, timeout=120).read()


def _point_in_poly(lat: float, lon: float, rings) -> bool:
    """Ray-Casting gegen den Aussenring eines Polygons ([lon, lat]-Paare)."""
    x, y = lon, lat
    inside = False
    ring = rings[0]
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def load_region_polygons() -> list[tuple[str, list]]:
    """[(Regionsname, [Polygon-Ringe, ...]), ...] aus dem Referenz-GeoJSON."""
    gj = json.loads(REGION_GEOJSON.read_text(encoding="utf-8"))
    out = []
    for f in gj["features"]:
        p = f["properties"]
        name = p.get("region") or p.get("name") or p.get("id")
        g = f["geometry"]
        out.append((name, [g["coordinates"]] if g["type"] == "Polygon"
                    else g["coordinates"]))
    return out


def smn_stations_by_region() -> list[dict]:
    """Alle SwissMetNet-Stationen mit Regionszuordnung (ohne Region: weggelassen)."""
    meta = list(csv.DictReader(
        io.StringIO(_fetch(f"{SMN_BASE}/ogd-smn_meta_stations.csv")
                    .decode("cp1252", "replace")), delimiter=";"))
    polys = load_region_polygons()
    out = []
    for r in meta:
        try:
            lat = float(r["station_coordinates_wgs84_lat"])
            lon = float(r["station_coordinates_wgs84_lon"])
        except (ValueError, KeyError):
            continue
        for name, multip in polys:
            if any(_point_in_poly(lat, lon, rings) for rings in multip):
                out.append({"abbr": r["station_abbr"].lower(),
                            "name": r["station_name"],
                            "elev": float(r.get("station_height_masl") or 0),
                            "region": name})
                break
    return out


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def smn_station_day(abbr: str, day: datetime.date) -> dict[str, list] | None:
    """Zehnminutenwerte einer Station fuer einen LOKALEN Kalendertag.

    Rueckgabe {"HH:MM": [regen_mm, boee_kmh, temp_c, sonne_min]} oder None,
    wenn die Station fuer den Tag nichts liefert. Quelle ist die t_recent-
    Datei (laufendes Jahr, UTC) — geholt wird nur das Dateiende.
    """
    url = f"{SMN_BASE}/{abbr}/ogd-smn_{abbr}_t_recent.csv"
    try:
        head = _fetch(url, {"Range": "bytes=0-3000"}).decode("utf-8", "replace")
        header = head.split("\n")[0].strip().split(";")
        tail = _fetch(url, {"Range": f"bytes=-{_TAIL_BYTES}"}).decode("utf-8", "replace")
    except Exception:
        return None
    rows = [dict(zip(header, ln.strip().split(";")))
            for ln in tail.split("\n")[1:]
            if ln.count(";") == len(header) - 1]
    out: dict[str, list] = {}
    for r in rows:
        ts = r.get("reference_timestamp", "")
        if len(ts) < 16:
            continue
        try:
            dt_utc = datetime.datetime(int(ts[6:10]), int(ts[3:5]), int(ts[0:2]),
                                       int(ts[11:13]), int(ts[14:16]),
                                       tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
        loc = dt_utc.astimezone(_TZ)
        if loc.date() != day:
            continue
        gust = _num(r.get("fkl010z1"))
        out[f"{loc.hour:02d}:{loc.minute:02d}"] = [
            _num(r.get("rre150z0")),
            gust * 3.6 if gust is not None else None,
            _num(r.get("tre200s0")),
            _num(r.get("sre000z0")),
            _num(r.get("prestas0"))]
    return out or None


def region_events(werte_by_station: dict[str, dict], stations_meta: dict[str, dict]) -> dict:
    """Ereignisse je Region aus den Zehnminutenwerten eines Tages.

    werte_by_station: {abbr: {"HH:MM": [regen, boee, temp, sonne]}}
    Signatur auf gleitenden 30-Minuten-Fenstern (3 Schritte). Ein Ereignis je
    Station: der staerkste Treffer. Rueckgabe je Region: gewitter/schauer-
    Ereignislisten (Zeit = Fensterende, lokal) + Sonnenanteil 12-18 Uhr.
    """
    regionen: dict[str, dict] = {}
    for abbr, werte in werte_by_station.items():
        meta = stations_meta.get(abbr)
        if not meta:
            continue
        reg = regionen.setdefault(meta["region"], {
            "gewitter": [], "schauer": [], "ausfluss": [], "_sonne": []})
        times = sorted(werte)
        best_storm = best_shower = best_outflow = None
        for i in range(3, len(times)):
            win = [werte[t] for t in times[i - 2:i + 1]]
            rain30 = sum(v[0] for v in win if v[0] is not None)
            a, b = werte[times[i - 3]], werte[times[i]]
            jump = (b[1] - a[1]) if None not in (a[1], b[1]) else None
            dtemp = (b[2] - a[2]) if None not in (a[2], b[2]) else None
            dpres = ((b[4] - a[4]) if len(a) > 4 and len(b) > 4
                     and None not in (a[4], b[4]) else None)
            if rain30 >= STORM_RAIN_MM30 and (
                    (jump is not None and jump >= STORM_GUST_JUMP_KMH)
                    or (dtemp is not None and dtemp <= STORM_TEMP_DROP_K)):
                cand = [times[i], abbr, round(rain30, 1),
                        round(jump) if jump is not None else None,
                        round(dtemp, 1) if dtemp is not None else None]
                if best_storm is None or cand[2] > best_storm[2]:
                    best_storm = cand
            elif rain30 >= SHOWER_RAIN_MM30:
                cand = [times[i], abbr, round(rain30, 1)]
                if best_shower is None or cand[2] > best_shower[2]:
                    best_shower = cand
            elif (jump is not None and jump >= OUTFLOW_GUST_JUMP_KMH
                    and dtemp is not None and dtemp <= OUTFLOW_TEMP_DROP_K
                    and dpres is not None and dpres >= OUTFLOW_PRES_RISE_HPA):
                cand = [times[i], abbr, round(jump),
                        round(dtemp, 1), round(dpres, 1)]
                if best_outflow is None or cand[2] > best_outflow[2]:
                    best_outflow = cand
        if best_storm:
            reg["gewitter"].append(best_storm)
        elif best_shower:
            reg["schauer"].append(best_shower)
        elif best_outflow:
            reg["ausfluss"].append(best_outflow)
        sonne = [v[3] for t, v in werte.items()
                 if "12:00" <= t < "18:00" and v[3] is not None]
        if sonne:
            reg["_sonne"].append(round(100.0 * sum(sonne) / (len(sonne) * 10)))
    for reg in regionen.values():
        vals = sorted(reg.pop("_sonne"))
        reg["sonne_1218_pct"] = vals[len(vals) // 2] if vals else None
    return regionen


def judge(angezeigt: list, gemessen: list) -> tuple[str, float | None]:
    """Das gemeinsame Urteil: (urteil, zeitversatz_h).

    angezeigt/gemessen: Stundenlisten (int oder 'HH:MM'). Zeitversatz nur bei
    Treffern: erste Warnstunde minus erste Ereignisstunde (negativ = zu frueh).
    """
    def _hours(xs):
        return sorted(int(str(x)[:2]) for x in xs)
    w, t = _hours(angezeigt), _hours(gemessen)
    if w and t:
        return "treffer", float(w[0] - t[0])
    if t:
        return "verpasst", None
    if w:
        return "fehlalarm", None
    return "still", None
