#!/usr/bin/env python3
"""
backtest_foehn.py — Unsere Föhnwarnung gegen den amtlichen Föhnindex.

Wahrheit:  MeteoSchweiz-Föhnindex wcc006s0 (0 kein Föhn, 1 Föhnmischluft,
           2 Föhn), Zehnminutenwerte UTC, reduziert abgelegt in
           validation/foehn/messwerte/<ABK>_foehnindex_2024-.csv
Prognose:  foehn_indicators.evaluate_foehn (Produktiv-Logik, unverändert)
           auf Open-Meteo historical-forecast-api (best_match = dieselbe
           Modellwahl wie fetch_foehn_data, das keinen models-Parameter setzt),
           Zürich/Lugano stündlich UTC, validation/foehn/modell/*.json

Vergleich stündlich im Flugfenster (config.FLIGHT_HOURS lokal):
  Wahrheit Stunde = Föhn, wenn >= 3 von 6 Zehnminutenwerten Index 2
  (Mischluft analog, wird getrennt gezählt).
  Warnung = level in {caution, danger} bei kritischer_foehn der Region.

Ausgabe: validation/foehn/AUTO_REPORT.md + scoreboard.json
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from foehn_indicators import evaluate_foehn, THRESHOLD_DELTA_P_CAUTION  # noqa: E402

VDIR = ROOT / "validation" / "foehn"
TZ = ZoneInfo(config.TIMEZONE)

# Station -> (Name, Wingcast-Region, Föhnrichtung der Station)
STATIONS = {
    "ALT": ("Altdorf", "Zentralschweizer Alpen", "Süd"),
    "ENG": ("Engelberg", "Zentralschweizer Alpen", "Süd"),
    "CHU": ("Chur", "Rheintal", "Süd"),
    "RAG": ("Bad Ragaz", "Rheintal", "Süd"),
    "VAD": ("Vaduz", "Rheintal", "Süd"),
    "GLA": ("Glarus", "Glarner Alpen", "Süd"),
    "ELM": ("Elm", "Glarner Alpen", "Süd"),
    "MER": ("Meiringen", "Berner Alpen", "Süd"),
    "AND": ("Andeer", "Mittelbünden", "Süd"),
    "DAV": ("Davos", "Prättigau - Davos", "Süd"),
    "VIS": ("Visp", "Oberwallis / Goms", "Süd"),
    "SIO": ("Sion", "Unterwallis", "Süd"),
    "EVI": ("Evionnaz", "Waadtländer Alpen", "Süd"),
    "PIO": ("Piotta", "Leventina / Blenio", "Nord"),
    "COM": ("Acquarossa", "Leventina / Blenio", "Nord"),
    "MAG": ("Magadino", "Locarnese / Bellinzonese", "Nord"),
}


def load_model() -> tuple[dict, dict]:
    nord = json.loads((VDIR / "modell" / "nord_zuerich_best_match_2024-2026.json").read_text())
    sued = json.loads((VDIR / "modell" / "sued_lugano_best_match_2024-2026.json").read_text())
    return nord, sued


def model_levels(nord: dict, sued: dict) -> dict[str, dict]:
    """{'YYYY-MM-DDTHH' (UTC): {'Süd': level, 'Nord': level, 'dp_s': .., 'dp_n': .., 'crest': .., 'cdir': ..}}"""
    times = nord["hourly"]["time"]
    out = {}
    for i, t in enumerate(times):
        ev_s = evaluate_foehn(nord, sued, time_index=i, kritischer_foehn="Süd")
        ev_n = evaluate_foehn(nord, sued, time_index=i, kritischer_foehn="Nord")
        p_n = nord["hourly"]["pressure_msl"][i]
        p_s = sued["hourly"]["pressure_msl"][i]
        dp = None if (p_n is None or p_s is None) else round(p_s - p_n, 1)
        out[t[:13]] = {
            "Süd": ev_s["level"], "Nord": ev_n["level"],
            "dp": dp,                       # positiv = Südföhn-Gradient
            "crest": ev_s["crest_wind_kmh"], "cdir": ev_s["crest_dir_deg"],
        }
    return out


def load_truth(abbr: str) -> dict[str, tuple[int, int, int]]:
    """{'YYYY-MM-DDTHH' (UTC): (n_foehn, n_misch, n_total)} aus Zehnminutenwerten."""
    path = VDIR / "messwerte" / f"{abbr}_foehnindex_2024-.csv"
    if not path.exists():
        return {}
    acc: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            ts = row["reference_timestamp"]  # dd.mm.yyyy HH:MM UTC
            try:
                d = datetime.strptime(ts, "%d.%m.%Y %H:%M")
            except ValueError:
                continue
            key = d.strftime("%Y-%m-%dT%H")
            v = row.get("wcc006s0", "")
            if v == "":
                continue
            a = acc[key]
            a[2] += 1
            if v == "2":
                a[0] += 1
            elif v == "1":
                a[1] += 1
    return {k: tuple(v) for k, v in acc.items()}


def in_flight_window(key_utc: str) -> bool:
    d = datetime.strptime(key_utc, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc).astimezone(TZ)
    return config.FLIGHT_HOURS_START <= d.hour < config.FLIGHT_HOURS_END


def score_station(abbr: str, truth: dict, model: dict) -> dict:
    name, region, side = STATIONS[abbr]
    c = Counter()
    dp_foehn, dp_none = [], []
    days_truth, days_warn = set(), set()
    for key, (nf, nm, nt) in truth.items():
        if nt < 4 or key not in model or not in_flight_window(key):
            continue
        m = model[key]
        is_foehn = nf >= 3
        is_misch = (not is_foehn) and (nf + nm) >= 3
        warned = m[side] in ("caution", "danger")
        day = key[:10]
        dp = m["dp"] if side == "Süd" else (None if m["dp"] is None else -m["dp"])
        if is_foehn:
            c["foehn_h"] += 1
            days_truth.add(day)
            c["hit" if warned else "miss"] += 1
            if dp is not None:
                dp_foehn.append(dp)
        elif is_misch:
            c["misch_h"] += 1
            c["misch_warned" if warned else "misch_unwarned"] += 1
        else:
            c["none_h"] += 1
            c["false_alarm" if warned else "correct_neg"] += 1
            if dp is not None:
                dp_none.append(dp)
        if warned:
            days_warn.add(day)
        c["hours"] += 1

    def pct(a, b):
        return None if not b else round(100.0 * a / b, 1)

    dp_foehn.sort()
    dp_none.sort()

    def q(xs, p):
        return None if not xs else xs[min(len(xs) - 1, int(p * len(xs)))]

    # Wie viele Föhnstunden liegen UNTER der heutigen Schwelle?
    below4 = sum(1 for x in dp_foehn if x < THRESHOLD_DELTA_P_CAUTION)
    below2 = sum(1 for x in dp_foehn if x < 2)
    # Tagesebene: Föhntag = >=1 Föhnstunde im Flugfenster
    day_hit = len(days_truth & days_warn)
    day_fa = len(days_warn - days_truth)
    return {
        "station": abbr, "name": name, "region": region, "side": side,
        "hours_evaluated": c["hours"],
        "foehn_hours": c["foehn_h"], "misch_hours": c["misch_h"],
        "pod_pct": pct(c["hit"], c["foehn_h"]),
        "miss_hours": c["miss"],
        "false_alarm_hours": c["false_alarm"],
        "far_pct": pct(c["false_alarm"], c["false_alarm"] + c["hit"]),
        "misch_warned_pct": pct(c["misch_warned"], c["misch_h"]),
        "foehn_days": len(days_truth), "warn_days": len(days_warn),
        "day_pod_pct": pct(day_hit, len(days_truth)),
        "day_far_pct": pct(day_fa, len(days_warn)),
        "dp_foehn_p10": q(dp_foehn, 0.10), "dp_foehn_p50": q(dp_foehn, 0.50),
        "dp_foehn_p90": q(dp_foehn, 0.90),
        "dp_none_p50": q(dp_none, 0.50), "dp_none_p90": q(dp_none, 0.90),
        "dp_none_p99": q(dp_none, 0.99),
        "foehn_hours_dp_below_4_pct": pct(below4, len(dp_foehn)),
        "foehn_hours_dp_below_2_pct": pct(below2, len(dp_foehn)),
    }


def threshold_sweep(abbr: str, truth: dict, model: dict) -> list[dict]:
    """POD/FAR für Δp-Schwellen 1..10 hPa (nur Δp, ohne Kammwind) — Kalibrierhilfe."""
    side = STATIONS[abbr][2]
    rows = []
    pairs = []
    for key, (nf, nm, nt) in truth.items():
        if nt < 4 or key not in model or not in_flight_window(key):
            continue
        dp = model[key]["dp"]
        if dp is None:
            continue
        if side == "Nord":
            dp = -dp
        pairs.append((dp, nf >= 3, (nf + nm) >= 3 and nf < 3))
    for thr in range(1, 11):
        hit = sum(1 for dp, f, _ in pairs if f and dp >= thr)
        miss = sum(1 for dp, f, _ in pairs if f and dp < thr)
        fa = sum(1 for dp, f, m in pairs if not f and not m and dp >= thr)
        rows.append({"thr": thr, "pod_pct": round(100 * hit / max(1, hit + miss), 1),
                     "far_pct": round(100 * fa / max(1, fa + hit), 1), "fa_hours": fa})
    return rows


def main() -> None:
    nord, sued = load_model()
    model = model_levels(nord, sued)
    t0, t1 = min(model), max(model)
    results, sweeps = [], {}
    for abbr in STATIONS:
        truth = load_truth(abbr)
        if not truth:
            print(f"[WARN] keine Messwerte für {abbr}")
            continue
        results.append(score_station(abbr, truth, model))
        sweeps[abbr] = threshold_sweep(abbr, truth, model)

    (VDIR / "scoreboard.json").write_text(json.dumps(
        {"period_utc": [t0, t1], "stations": results, "dp_sweep": sweeps},
        ensure_ascii=False, indent=1), encoding="utf-8")

    L = []
    L.append("# Föhn-Backtest — AUTO_REPORT (maschinell erzeugt, nicht editieren)\n")
    L.append(f"Zeitraum {t0} … {t1} UTC · Flugfenster {config.FLIGHT_HOURS_START}–{config.FLIGHT_HOURS_END} Uhr lokal · "
             f"Prognose = `evaluate_foehn` (Produktivlogik) auf Open-Meteo historical-forecast best_match · "
             f"Wahrheit = MeteoSchweiz-Föhnindex (Stunde = Föhn bei ≥3/6 Zehnminutenwerten Index 2)\n")
    L.append("## Stundenebene\n")
    L.append("| Station | Region | Ri | Föhn-h | Treffer % | verpasst h | Fehlalarm h | FAR % | Mischluft-h (gewarnt %) |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in results:
        L.append(f"| {r['name']} ({r['station']}) | {r['region']} | {r['side']} | {r['foehn_hours']} | "
                 f"{r['pod_pct']} | {r['miss_hours']} | {r['false_alarm_hours']} | {r['far_pct']} | "
                 f"{r['misch_hours']} ({r['misch_warned_pct']}) |")
    L.append("\n## Tagesebene (Föhntag = ≥1 Föhnstunde im Flugfenster)\n")
    L.append("| Station | Föhntage | Warntage | Treffer % | Fehlalarm-Tage % |")
    L.append("|---|---|---|---|---|")
    for r in results:
        L.append(f"| {r['name']} | {r['foehn_days']} | {r['warn_days']} | {r['day_pod_pct']} | {r['day_far_pct']} |")
    L.append("\n## Δp Lugano−Zürich während Föhn vs. ohne Föhn (hPa, Nordföhn-Stationen mit Vorzeichen gedreht)\n")
    L.append("| Station | Föhn P10 / P50 / P90 | kein Föhn P50 / P90 / P99 | Föhn-h mit Δp < 4 | Föhn-h mit Δp < 2 |")
    L.append("|---|---|---|---|---|")
    for r in results:
        L.append(f"| {r['name']} | {r['dp_foehn_p10']} / {r['dp_foehn_p50']} / {r['dp_foehn_p90']} | "
                 f"{r['dp_none_p50']} / {r['dp_none_p90']} / {r['dp_none_p99']} | "
                 f"{r['foehn_hours_dp_below_4_pct']} % | {r['foehn_hours_dp_below_2_pct']} % |")
    L.append("\n## Δp-Schwellen-Sweep (nur Δp, ohne Kammwind): Treffer % / FAR %\n")
    L.append("| Station | " + " | ".join(f"≥{t}" for t in range(1, 11)) + " |")
    L.append("|---|" + "---|" * 10)
    for abbr, rows in sweeps.items():
        L.append(f"| {STATIONS[abbr][0]} | " + " | ".join(f"{x['pod_pct']}/{x['far_pct']}" for x in rows) + " |")
    (VDIR / "AUTO_REPORT.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
