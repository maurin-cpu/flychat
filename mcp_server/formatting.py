"""Textausgaben fuer Claude: kompakt, aber mit sichtbarem Verlauf ueber Zeit und Hoehe.

Grundsatz (User 16.09.): ein Fenster mit Einzelwerten ist zu riskant — Claude
muss sehen, wie sich Wind, Boeen, Hoehenwind und Thermik ueber den Tag und
ueber die Hoehe entwickeln. Darum drei Dichten:
  day_line()      eine Zeile pro Spot-Tag mit Min→Max und Trendpfeil (alle Spots)
  series_block()  Stundenreihen + Mini-Hoehenprofil (Region / Auswahl)
  Block/Meteogramm/Hoehenwind (Detail) formatiert server.py aus den Rohdateien.
"""
from __future__ import annotations

from datetime import datetime

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def day_label(date_str: str) -> str:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{WEEKDAYS[d.weekday()]} {d.day:02d}.{d.month:02d}."
    except ValueError:
        return date_str


def footer(store) -> str:
    m = store.meta
    models = ", ".join(f"{d[5:]}: {'/'.join(sorted(v))}" for d, v in (m.get("models_by_date") or {}).items())
    lines = [
        "",
        f"— Stand Prognose: {(m.get('last_updated') or '?')[:16]} · Export {(m.get('built_at') or '?')[:16]} · Modelle {models}",
        "— Quelle: Open-Meteo (CC BY 4.0) mit ICON-CH1/CH2 (MeteoSchweiz), ICON-D2/EU (DWD). "
        "Rohdaten + deterministische Kennzahlen, keine Bewertung der App. Entscheid liegt beim Piloten.",
    ]
    a = store.age_hours()
    if store.is_stale():
        lines.insert(1, f"!! WARNUNG: Prognose ist {a:.0f} h alt — nur noch als grobe Orientierung brauchbar.")
    return "\n".join(lines)


def _f(v, nd=0, empty="-"):
    if v is None:
        return empty
    return f"{v:.{nd}f}" if nd else f"{int(round(v))}"


def _trend(vals: list, delta_min: float) -> str:
    """Pfeil aus erstem/letztem Drittel: ↗ ↘ → (leer wenn keine Daten)."""
    xs = [v for v in vals if v is not None]
    if len(xs) < 3:
        return ""
    k = max(1, len(xs) // 3)
    a, b = sum(xs[:k]) / k, sum(xs[-k:]) / k
    if b - a >= delta_min:
        return "↗"
    if a - b >= delta_min:
        return "↘"
    return "→"


def _rng(vals: list, nd=0) -> str:
    xs = [v for v in vals if v is not None]
    if not xs:
        return "-"
    lo, hi = min(xs), max(xs)
    return _f(lo, nd) if lo == hi else f"{_f(lo, nd)}→{_f(hi, nd)}"


def _dir8(deg) -> str:
    if deg is None:
        return "-"
    return ["N", "NO", "O", "SO", "S", "SW", "W", "NW"][int(((deg + 22.5) % 360) // 45)]


def day_line_header() -> str:
    return ("Spot | Region | Höhe | Sektor | Fenster (Stunden gesamt/längstes) | Wind km/h min→max Trend | "
            "Böen max | 700hPa km/h | Höhe Start→+3000m (12h) | Regen mm (h im Fenster) | CAPE max | "
            "Föhn | Thermik: h prod / Steigen max / Top | Basis min | Bew. tief%")


def day_line(r: dict) -> str:
    s = r["series"]
    p12 = (r.get("profiles") or {}).get("12") or []
    grad = "-"
    if p12:
        grad = f"{_f(p12[0][1])}→{_f(p12[-1][1])} {_dir8(p12[-1][2])}"
    foehn = "-" if r["foehn_level"] in ("none", None, "unknown") else f"{r['foehn_level']} ΔP{_f(r['foehn_dp'], 1)} {r['foehn_dir'] or ''}".strip()
    warn = []
    if r["gust_danger_h"] or r["aloft_gust_danger_h"]:
        warn.append("GUST-DANGER")
    if r["aloft_danger_h"]:
        warn.append("ALOFT-DANGER")
    if r["thunder_win_h"]:
        warn.append("GEWITTER")
    if r["cloud_below_to_h"]:
        warn.append(f"BASIS<START {r['cloud_below_to_h']}h")
    tops = [v for v in s["top"] if v]
    base = f"{_f(r['min_base_m'])}m" if r["min_base_m"] is not None else "-"
    return (
        f"{r['spot']} | {r['region']} | {_f(r['elev'])}m | {r['sector'] or '-'} | "
        f"{r['clean_windows']} ({r['clean_h']}h/{r['longest_clean_h']}h) | "
        f"{_rng(s['wind'])} {_trend(s['wind'], 3)} | {_f(r['gust_max'])} {_trend(s['gust'], 4)} | "
        f"{_rng(s['aloft700'])} {_trend(s['aloft700'], 4)} | {grad} | "
        f"{_f(r['precip_mm'], 1)} ({r['rain_win_h']}h) | {_f(r['cape_max'])} | {foehn} | "
        f"{r['prod_h']}h / {_f(r['peak_climb'], 1)} m/s / {_f(max(tops)) + 'm' if tops else '-'} | "
        f"{base} | {_f(r['low_cloud_pct'])}%"
        + (f" | !! {' '.join(warn)}" if warn else "")
    )


def _foehn_text(r: dict) -> str:
    """'caution (ΔP 6.2 hPa, Nord)' — bzw. Hinweis, wenn ΔP hoch, aber Richtung fuer den Spot nicht kritisch."""
    lvl, dp, d = r.get("foehn_level"), r.get("foehn_dp"), r.get("foehn_dir")
    if lvl == "unknown":
        return "unbekannt (keine Zeitreihe)"
    base = f"{lvl} (ΔP {_f(dp, 1)} hPa, {d or '-'})"
    if lvl == "none" and dp is not None and dp >= 4 and d and d != "none":
        return base + f" — {d}-Föhn-Gradient vorhanden, für diesen Spot (kritisch: {r.get('foehn_crit') or '-'}) nicht relevant"
    return base


def _series_line(label: str, vals: list, nd=0, width=4) -> str:
    return f"  {label:<8}" + "".join(f"{_f(v, nd):>{width}}" for v in vals)


def series_block(r: dict, agl_steps: list[int]) -> str:
    s = r["series"]
    hours = s["hours"]
    lines = [
        f"### {r['spot']} ({r['fluggebiet']}, {r['region']}) · {day_label(r['date'])} · {_f(r['elev'])} m · "
        f"Sektor {r['sector'] or '-'} · Föhn-kritisch: {r['foehn_crit'] or '-'} · Modell {r['model'] or '?'}",
        f"  Fenster WIND-OK ohne DANGER: {r['clean_windows']} · Föhn: {_foehn_text(r)}"
        f" · Regen {_f(r['precip_mm'], 1)} mm · Gewitterstunden {r['thunder_h']} · Ensemble-Gewitter Region {_f(r['region_thunder_pct'])}%",
        "  Uhr    " + "".join(f"{h:>4}" for h in hours),
        _series_line("Wind", s["wind"]),
        "  Richt.  " + "".join(f"{_dir8(v):>4}" for v in s["dir"]),
        "  WIND-OK " + "".join(f"{'ok' if v else 'X':>4}" for v in s["wind_ok"]),
        _series_line("Böen", s["gust"]),
        _series_line("850hPa", s["aloft850"]),
        _series_line("700hPa", s["aloft700"]),
        "  700 aus " + "".join(f"{_dir8(v):>4}" for v in s["aloft700_dir"]),
        _series_line("Steigen", s["climb"], nd=1, width=5).replace("  Steigen ", "  Steig. "),
        _series_line("Top m", s["top"], width=5),
        _series_line("Basis m", s["base"], width=5),
        _series_line("tief %", s["low"]),
        _series_line("mittel%", s["mid"]),
        _series_line("Regen", s["rain"], nd=1, width=5),
        _series_line("CAPE", s["cape"], width=5),
        _series_line("Strahl.", s["sw"], width=5),
        _series_line("Temp", s["temp"], nd=1, width=5),
    ]
    prof = r.get("profiles") or {}
    if prof:
        hrs = sorted(prof.keys())
        lines.append("  Höhenwind km/h / aus / Turbulenz-Exzess   " + "".join(f"{h + ' Uhr':>18}" for h in hrs))
        for i, agl in enumerate(agl_steps):
            cells = []
            for h in hrs:
                row = next((x for x in prof[h] if x[0] == agl), None)
                cells.append(f"{_f(row[1])} {_dir8(row[2])} +{_f(row[3])}" if row else "-")
            lab = "Start" if agl == 0 else f"+{agl}m"
            lines.append(f"  {lab:<8}" + "".join(f"{c:>18}" for c in cells))
    return "\n".join(lines)


def exclusion_summary(summary: dict, reasons_map: dict) -> str:
    parts = []
    for key in reasons_map:
        n = summary["by_reason"].get(key)
        if not n:
            continue
        if key == "no_window":
            sp = summary["no_window_split"]
            parts.append(f"{key} {n} [Windrichtung passt nie {sp.get('wind_sector', 0)} / harte Warnungen {sp.get('hard_warnings', 0)}]")
        else:
            parts.append(f"{key} {n}")
    scope = f"Im Bereich: {summary['checked']} von {summary['total']} Spot-Tagen · " if summary.get("out_of_scope") else ""
    return (f"{scope}Geprüft: {summary['checked']} Spot-Tage · Ausgeschlossen: {summary['excluded']} "
            f"({'; '.join(parts) or 'keine'}; Mehrfachnennung möglich) · Übrig: {summary['kept']}")


def filters_line(f: dict) -> str:
    on = [f"min_clean_h={f['min_clean_h']}"]
    for k in ("allow_gust_danger", "allow_aloft_danger", "allow_thunder", "allow_foehn_danger", "allow_cloud_below_takeoff"):
        if f.get(k):
            on.append(f"{k}=ja")
    if f.get("allow_rain_h"):
        on.append(f"allow_rain_h={f['allow_rain_h']}")
    for k in ("max_gust", "min_thermal_h", "min_peak_climb", "regions", "dates"):
        if f.get(k):
            on.append(f"{k}={f[k]}")
    if f.get("near"):
        n = f["near"]
        on.append(f"near={n['lat']:.3f},{n['lon']:.3f} r={n['km']}km")
    return "Filter: " + ", ".join(on)
