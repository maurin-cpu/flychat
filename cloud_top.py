"""Wolkentop-Abruf fuer die Ueberentwicklungs-Stufe (ICON-EU).

WARUM ICON-EU
-------------
`convective_cloud_top` liefert nur ICON-EU verlaesslich: MeteoSchweiz
ICON-CH1/CH2 kennen das Feld gar nicht, ICON-D2 laesst es fast immer leer
(2-km-Modell rechnet Konvektion teils explizit, das Konvektionsschema
schweigt). Gemessen am 03.08.2026 (Saison-Backtest, docs/GEWITTER.md par.0c):
der EU-Top erkannte 96 % der Gewittertage — als harter Alarm viel zu laut,
als weiche Ueberentwicklungs-Vorwarnung mit Flaechen-Quorum + Anker
brauchbar (2 von 3 Konvektionstagen, ~3-4 h Vorlauf).

MODELL-MIX, BEWUSST
-------------------
Das ist eine Zutat aus einem ANDEREN Modell als dem angezeigten CH1/CH2 —
ein Indizien-Voting, keine Physik-Kette (Entscheid 03.08.). Darum wird der
Top nie stundenscharf mit CH1-Feldern ver-UND-et, sondern nur als
Flaechen-Anteil je Stunde gefuehrt; die Konsistenz mit der Anzeige stellt
overdev.is_overdev_hour ueber die ANGEZEIGTE Bewoelkung her. Der Abgleich
gegen die Messung (validation/gewitter/) entscheidet empirisch, ob der Mix
traegt — die Ein-Modell-Alternative (Wolkentiefe selbst aus dem
CH1/CH2-Profil) bleibt als Challenger im Plan.

Wolkentop-Temperatur: Abstand zum Gefrierniveau x 6,5 K/km — bewusst grob,
es geht um die Stufe (harmlos / hochgeschossen), nicht ums Grad.
"""
from __future__ import annotations

import time

import requests

import config

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
