"""
Analyse-Kette des Morgenbriefings — gemeinsame Quelle fuer Mail und App.

Aufbau, Prinzip und Pillen-Regeln: docs/BRIEFING.md. Kurz: das Briefing folgt
der Analyse-Kette des Piloten (Lage -> Fronten -> Foehn -> Hoehenwind ->
Labilitaet -> Thermik -> Sonne -> Modelle), stellt je Block die Erwartung aus
der Synoptik gegen die eigenen Prognosedaten und spricht ein Urteil (Pille +
Satz). Jede Block-Funktion rechnet fuer EINEN Tag: Signatur `(wetterlage, date)`.

Zwei Einstiege:
- `build_v3_context(ctx, briefing_data, subscriber, focus_date)` — das Mail
  (email_service._render_briefing_v3) und die Vorschau
  (scripts/preview_briefing_email.py): Woche + Kette + Warnungen + Regionen
  fuer den Fokus-Tag (Versand: heute).
- `build_chain_all_days(wetterlage, dates)` — die App (/api/briefing): Kette
  + Warnungen fuer jeden Prognosetag, die Tages-Tabs schalten um.

Sprache: config.LANG (global), Labels _L2/_L3 unten, Saetze entstehen hier.
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
import statistics
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import config
import i18n
from email_service import _rating_for_spot, _tier_label, _format_window

ROOT = Path(__file__).resolve().parent.parent

# ----------------------------------------------------------------------
# Basis-Labels (frueher briefing_v2_context._L) — _L3 unten ergaenzt/ueberschreibt
# ----------------------------------------------------------------------
_L2 = {
    "de": {
        "q1":            "Welche Tage sind gut?",
        "q2":            "Wie ist heute?",
        "synoptik":      "Synoptik heute",
        "regions":       "Deine Regionen heute",
        "warnings":      "Warnungen",
        "flyable":       "fliegbar",
        # Betreff in der Sprache der Kacheln — kein Urteil, der Pilot entscheidet
        "subj_safe":     "{days} ohne Warnhinweise",
        "subj_caution":  "{days} mit Warnhinweisen",
        "subj_not_safe": "Warnhinweise an allen Tagen",
        "subj_severe":   "{days} mit schweren Warnhinweisen",
        "subj_all_safe":   "An allen Tagen ohne Warnhinweise",
        "subj_all_caution": "Warnhinweise an allen Tagen",
        "subj_all_severe": "Schwere Warnhinweise an allen Tagen",
        "conditional":   "fliegbar mit Warnhinweisen",
        "nothing":       "Nichts gelistet",
        "today":         "Heute",
        "in_your_regions": "In deinen Regionen",
        "no_good_day":   "Kein guter Tag in deinen Regionen",
        "no_rating":     "keine Bewertung",
        "and":           "und",
        "pressure":      "Bodendruck",
        "flow":          "Hoehenwind 700 hPa",
        "t850":          "T850",
        "precip":        "Niederschlag",
        "convection":    "Konvektion",
        "confidence":    "Vertrauen",
        "north":         "Alpennord",
        "south":         "Alpensued",
        "thunder":       "Gewitter",
        "overdev":       "Ueberentwicklung",
        "none_today":    "keine",
        "no_window":     "kein Fenster",
        "peak":          "Spitze",
        "spots":         "Spots",
        "q1_long":       "Wann kann ich diese Woche fliegen?",
        "q2_long":       "Heute im Detail",
        "q2_day":        "Im Detail",            # App: anderer Tag als heute gewaehlt
        "question":      "Sektion",
        "days_ahead":    "Die Tage voraus",
        "lead_title":    "Wie sich die Lage umstellt",
        "no_recommendation": "Kein Einschaetzungssatz im Cache",
        "no_regions":    "Fuer diesen Tag liegt keine Regions-Bewertung vor",
        "cta":           "Alle Details in der App ansehen",
        "disclaimer":    "Wingcast unterstuetzt deine Entscheidung — "
                         "geflogen wird nach deinem Urteil am Startplatz.",
        "legend_code":   "rechnet Zahlen, Farben, Fenster",
        "legend_ki":     "erklaert sie in Worten",
        "inbox_sender":  "WINGCAST BRIEFING",
        "wet":           "der Spots nass",
    },
    "en": {
        "q1":            "Which days are good?",
        "q2":            "How is today?",
        "synoptik":      "Synoptics today",
        "regions":       "Your regions today",
        "warnings":      "Warnings",
        "flyable":       "flyable",
        "subj_safe":     "{days} without alerts",
        "subj_caution":  "{days} with alerts",
        "subj_not_safe": "Alerts every day",
        "subj_severe":   "{days} with severe alerts",
        "subj_all_safe":   "No alerts on any day",
        "subj_all_caution": "Alerts on all days",
        "subj_all_severe": "Severe alerts on all days",
        "conditional":   "flyable with alerts",
        "nothing":       "Nothing listed",
        "today":         "Today",
        "in_your_regions": "In your regions",
        "no_good_day":   "No good day in your regions",
        "no_rating":     "no rating",
        "and":           "and",
        "pressure":      "Surface pressure",
        "flow":          "Upper wind 700 hPa",
        "t850":          "T850",
        "precip":        "Precipitation",
        "convection":    "Convection",
        "confidence":    "Confidence",
        "north":         "North of Alps",
        "south":         "South of Alps",
        "thunder":       "Thunderstorms",
        "overdev":       "Overdevelopment",
        "none_today":    "none",
        "no_window":     "no window",
        "peak":          "peak",
        "spots":         "Spots",
        "q1_long":       "When can I fly this week?",
        "q2_long":       "Today in detail",
        "q2_day":        "In detail",            # app: a day other than today selected
        "question":      "Section",
        "days_ahead":    "The days ahead",
        "lead_title":    "How the situation shifts",
        "no_recommendation": "No assessment sentence in the cache",
        "no_regions":    "No region assessment available for this day",
        "cta":           "See all details in the app",
        "disclaimer":    "Wingcast supports your decision — you fly on your own "
                         "judgement at the launch site.",
        "legend_code":   "computes numbers, colours, windows",
        "legend_ki":     "puts them into words",
        "inbox_sender":  "WINGCAST BRIEFING",
        "wet":           "of spots wet",
    },
}

# Sektor-Namen aus config.SYNOPTIC_FLOW_SECTORS sind deutsch. Fuer die Mail
# reicht die Kompass-Kurzform — die ist in beiden Sprachen lesbar.
_SECTOR_ABBR = {
    "Nord": "N", "Nordost": "NE", "Ost": "E", "Suedost": "SE",
    "Sued": "S", "Suedwest": "SW", "West": "W", "Nordwest": "NW",
}
_STRENGTH = {
    "de": {"schwach": "schwach", "maessig": "maessig", "kraeftig": "kraeftig",
           "stuermisch": "stuermisch"},
    "en": {"schwach": "light", "maessig": "moderate", "kraeftig": "strong",
           "stuermisch": "stormy"},
}
# Muss ALLE Werte kennen, die engine/synoptic_context.py:decide_pressure_influence()
# erzeugen kann (Z. 695-735): Hochdruck, starker Tiefdruck, Tiefdruck, neutral,
# unbekannt, Uebergangslage. Fehlt einer, reicht der Fallback unten den deutschen
# Rohwert still ins EN-UI durch.
_REGIME = {
    "de": {"hoch": "Hoch", "hochdruck": "Hochdruck", "tief": "Tief", "tiefdruck": "Tiefdruck",
           "starker tiefdruck": "Starker Tiefdruck", "neutral": "Neutral",
           "uebergangslage": "Uebergangslage", "unbekannt": "Unbekannt"},
    "en": {"hoch": "High", "hochdruck": "High pressure", "tief": "Low", "tiefdruck": "Low pressure",
           "starker tiefdruck": "Strong low pressure", "neutral": "Neutral",
           "uebergangslage": "Transitional", "unbekannt": "Unknown"},
}
_CONFIDENCE = {
    "de": {"high": "hoch", "medium": "mittel", "low": "gering"},
    "en": {"high": "high", "medium": "medium", "low": "low"},
}
_CENTER_TYPE = {
    "de": {"Hoch": "Hoch", "Tief": "Tief"},
    "en": {"Hoch": "High", "Tief": "Low"},
}

# Rating-Palette v3.2 "Royal Premium" — die Werte stammen 1:1 aus
# docs/RATING_FARBKONZEPT.md (Single Source of Truth, Touchpoint-Liste dort in
# §3). Nicht hier abaendern: das Farbkonzept ist die Quelle, diese Tabelle nur
# eine weitere Kopie davon. Sky (1-2) -> Lime (3) -> Green-500 (4) -> Violet (5).
_TINT_SAFE = {
    1: {"fill": "#e0f2fe", "border": "#38bdf8", "text": "#075985"},
    2: {"fill": "#bae6fd", "border": "#0ea5e9", "text": "#075985"},
    3: {"fill": "#BEF264", "border": "#65a30d", "text": "#3f6212"},
    4: {"fill": "#22c55e", "border": "#15803d", "text": "#ffffff"},
    5: {"fill": "#a78bfa", "border": "#6d28d9", "text": "#ffffff"},
}
_TINT_COND = {
    1: {"fill": "#fef08a", "border": "#ca8a04", "text": "#713f12"},
    2: {"fill": "#facc15", "border": "#a16207", "text": "#713f12"},
    3: {"fill": "#f97316", "border": "#9a3412", "text": "#ffffff"},
    4: {"fill": "#c2410c", "border": "#7c2d12", "text": "#ffffff"},
    5: {"fill": "#7c2d12", "border": "#431407", "text": "#ffffff"},
}
_TINT_NOT_SAFE = {"fill": "#ef4444", "border": "#991b1b", "text": "#ffffff"}
_TINT_NO_DATA = {"fill": "#9ca3af", "border": "#6b7280", "text": "#1f2937"}


def _rating_tint(band: str, rating: int) -> dict:
    """Farbton fuer eine Band/Rating-Kombination nach RATING_FARBKONZEPT v3.2."""
    r = max(1, min(5, int(rating or 0))) if rating else 0
    if band == "red":
        return _TINT_NOT_SAFE
    if band == "green" and r:
        return _TINT_SAFE[r]
    if band == "amber" and r:
        return _TINT_COND[r]
    return _TINT_NO_DATA


# Windpfeil zeigt, wohin die Luft laeuft. dir_deg ist meteorologisch (woher),
# deshalb +180 Grad. Aus 270 Grad (Westwind) wird "->" = nach Osten.
_ARROWS = ["↑", "↗", "→", "↘",
           "↓", "↙", "←", "↖"]


def _wind_arrow(dir_deg) -> str:
    try:
        deg = (float(dir_deg) + 180.0) % 360.0
    except (TypeError, ValueError):
        return ""
    return _ARROWS[int((deg + 22.5) % 360 // 45)]


# Tages-Glyph im Streifen. Die Farbe traegt das Urteil, das Zeichen nur die
# Grobform — und 'unknown' muss sichtbar anders aussehen als 'none', sonst
# liest sich eine Datenluecke als Urteil.
_DAY_GLYPH = {
    "violet": "☀", "green": "☀", "conditional": "◐",
    "gray": "◐", "none": "✕", "not_safe": "✕", "unknown": "?",
}

# "13:00-17:00" — nur so etwas darf als Fenster-Pill erscheinen. Der Cache
# liefert im gleichen Feld auch ganze Saetze ("No thermal window exists ...")
# und den String "none"; beides ist keine Uhrzeit und gehoert nicht in die Pill.
_WINDOW_RE = re.compile(r"^\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}$")


def _lang() -> str:
    return "en" if i18n.get_current_lang() == "en" else "de"


def _join_days(names: list[str]) -> str:
    """['Heute','Fr','Sa'] -> 'Heute, Fr und Sa'."""
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} {_lbl('and')} {names[-1]}"


def _day_name(day: dict) -> str:
    return _lbl("today") if day.get("is_today") else day["label"].get("short", "")


def _clean_window(raw: str) -> str:
    """Gibt nur echte Uhrzeit-Fenster zurueck, sonst ''."""
    w = _format_window(raw or "")
    if not w or w.lower() in ("none", "kein", "-"):
        return ""
    return w if _WINDOW_RE.match(w) else ""


def _first_sentences(text: str, max_chars: int = 240) -> str:
    """Kuerzt die LLM-Einschaetzung auf ganze Saetze.

    Passt kein ganzer Satz in max_chars, zaehlt der erste Satz trotzdem ganz
    (bis zur harten Grenze 2x max_chars) — lieber etwas laenger als
    "...a weak peak of 1.3 m/s ma..." (Vorschau 16.09.2026). Erst darueber wird
    an der letzten Wortgrenze gekuerzt, nie mitten im Wort.
    """
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    cut = t[:max_chars]
    dot = cut.rfind(". ")
    if dot > 60:
        return cut[:dot + 1]
    first = re.search(r"^.+?[.!?](?=\s|$)", t)
    if first and len(first.group(0)) <= 2 * max_chars:
        return first.group(0)
    hard = t[:2 * max_chars]
    space = hard.rfind(" ")
    return (hard[:space] if space > 0 else hard).rstrip(" ,;:") + "…"


def _per_day_index(block, dates: list[str]) -> dict:
    """per_day-Liste eines Synoptik-Blocks auf {date: entry} abbilden."""
    if not isinstance(block, dict):
        return {}
    pd = block.get("per_day")
    if not isinstance(pd, list):
        return {}
    out = {}
    for i, item in enumerate(pd):
        if isinstance(item, dict) and item.get("date"):
            out[item["date"]] = item
        elif i < len(dates):
            # t850_trend.per_day ist eine reine Zahlenliste ohne Datum
            out[dates[i]] = item
    return out


def _strip_synoptik(wetterlage: dict, dates: list[str]) -> dict:
    """Pro Datum eine Kurzzeile: Druckregime + msl, T850, Foehn."""
    lang = _lang()
    flow = _per_day_index(wetterlage.get("flow_overhead"), dates)
    press = _per_day_index(wetterlage.get("pressure_influence"), dates)
    t850 = _per_day_index(wetterlage.get("t850_trend"), dates)
    foehn = _per_day_index(wetterlage.get("foehn"), dates)

    out = {}
    for d in dates:
        f = flow.get(d) or {}
        sector = _SECTOR_ABBR.get(f.get("sector", ""), f.get("sector", ""))
        strength = _STRENGTH[lang].get(f.get("strength", ""), f.get("strength", ""))
        speed = f.get("speed_kmh")
        speed_txt = f"{round(float(speed))} km/h" if speed else ""
        wind = ""
        if sector:
            wind = f"{sector} {strength}".strip()
            if speed_txt:
                wind += f" · {speed_txt}"

        p = press.get(d) or {}
        regime = _REGIME[lang].get((p.get("regime") or "").lower(), (p.get("regime") or "").title())
        msl = p.get("msl_hpa")
        pressure = f"{regime} {round(float(msl))} hPa" if msl else regime

        temp = t850.get(d)
        t_txt = t_val = ""
        if isinstance(temp, (int, float)):
            t_val = f"{temp:.1f}°"
            t_txt = f"T850 {t_val}"

        flags = []
        fo = foehn.get(d) or {}
        if fo.get("nord_active"):
            flags.append("Foehn N")
        if fo.get("sued_active"):
            flags.append("Foehn S")

        out[d] = {
            "wind": wind,
            "wind_arrow": _wind_arrow(f.get("dir_deg")),
            "wind_sector": sector,
            "wind_strength": strength,
            "wind_speed": speed_txt,
            "wind_deg": (f"{round(float(f['dir_deg']))}°"
                         if f.get("dir_deg") is not None else ""),
            "wind_hot": f.get("strength") in ("kraeftig", "stuermisch"),
            "pressure": pressure,
            "pressure_regime": regime,
            "pressure_msl": (f"{float(msl):.1f} hPa" if msl else ""),
            "t850": t_txt,
            "t850_value": t_val,
            "flags": flags,
        }
    return out


def _wind_class(kmh: float) -> str:
    """Staerkeklasse wie decide_flow_overhead (schwach <15, maessig <30,
    kraeftig <50, sonst stuermisch)."""
    return ("schwach" if kmh < 15 else "maessig" if kmh < 30
            else "kraeftig" if kmh < 50 else "stuermisch")


def _wind_range_block(wetterlage: dict, date: str, strip: dict) -> dict:
    """Spanne der Regionsspitzen (700 hPa) und ein Fazit: deckt sich der Wind
    in den Prognosedaten mit der Stroemungsstaerke der Synoptik? Leer, wenn
    der Kontext keine Regionsspitzen traegt (aeltere Caches)."""
    day = _per_day_index((wetterlage or {}).get("aloft_regional"), [date]).get(date) or {}
    hi, lo = day.get("max_kmh"), day.get("min_kmh")
    if not hi or not day.get("region"):
        return {}
    lo = lo if isinstance(lo, (int, float)) else hi
    hour = int(day.get("hour") or 12)
    when = _lbl("hour_morning" if hour < 10 else "hour_midday" if hour < 14
                else "hour_afternoon" if hour < 18 else "hour_evening")
    flow = _per_day_index((wetterlage or {}).get("flow_overhead"), [date]).get(date) or {}
    syn_cls = flow.get("strength") or _wind_class(float(flow.get("speed_kmh") or 0))
    data_cls = _wind_class(float(hi))
    order = ["schwach", "maessig", "kraeftig", "stuermisch"]
    abbr = _SECTOR_ABBR.get(flow.get("sector", ""), "")
    sector = _lbl("lg_sector_" + abbr) if abbr else ""
    args = dict(models=_model_words(), strength=_lbl("wstr_" + syn_cls), sector=sector, lo=int(lo), hi=int(hi),
                Strength=_capitalize(_lbl("wstr_" + syn_cls)),
                region=day["region"], when=when, cls=_lbl("wcls_" + data_cls))
    if order.index(data_cls) > order.index(syn_cls):
        fazit, verdict = _lbl("wind_fazit_stronger").format(**args), "stronger"
    elif order.index(data_cls) < order.index(syn_cls):
        fazit, verdict = _lbl("wind_fazit_weaker").format(**args), "weaker"
    else:
        fazit, verdict = _lbl("wind_fazit_match").format(**args), "match"
    return {
        "verdict": verdict, "peak_region": day["region"], "peak_hour": f"{hour:02d}",
        "range": _lbl("wind_range").format(lo=int(lo), hi=int(hi)),
        "range_note": _lbl("wind_range_note").format(region=day["region"], hour=f"{hour:02d}"),
        "ground_range": _lbl("wind_ground_range").format(lo=int(round(lo * 2 / 3)), hi=int(round(hi * 2 / 3))),
        "fazit": fazit,
    }


def _aloft_regional_text(wetterlage: dict, date: str) -> str:
    """"Regional bis 45 km/h (Berner Alpen), staerkste Stunde 14 Uhr" — nur,
    wenn der Kontext das Feld hat (aeltere Caches: leer)."""
    day = _per_day_index((wetterlage or {}).get("aloft_regional"), [date]).get(date) or {}
    if not day.get("max_kmh") or not day.get("region"):
        return ""
    return _lbl("wind_regional").format(kmh=day["max_kmh"], region=day["region"],
                                        hour=f"{int(day.get('hour') or 0):02d}")


def _center_name(label: str) -> str:
    """Druckzentrum in Mailsprache; unbekannter Name bleibt stehen."""
    if not label:
        return ""
    out = _lbl("ctr_" + label)
    return label if out == "ctr_" + label else out


def _synoptik_today(wetterlage: dict, dates: list[str], today: str):
    if not wetterlage or not today:
        return None
    lang = _lang()
    # Label DIESES Tages, nicht des 3-Tage-Fensters (Tages-Sektion = nur der Tag)
    from engine.synoptic_context import decide_lage_label_for_day
    lage_raw = decide_lage_label_for_day(wetterlage, today).get("value", "")
    if lage_raw == "unbestimmt":
        lage_raw = ""
    # Der Kontext schreibt das Label deutsch — fuer die Mail uebersetzen
    lage = _lbl("lage_" + lage_raw) if lage_raw else ""
    if lage == "lage_" + lage_raw:
        lage = lage_raw

    centers = []
    for entry in wetterlage.get("pressure_centers_per_day") or []:
        if entry.get("date") != today:
            continue
        for c in entry.get("centers") or []:
            centers.append({
                "type": _CENTER_TYPE[lang].get(c.get("type", ""), c.get("type", "")),
                # Namen kommen deutsch aus config.EUROPE_PRESSURE_GRID
                "region": _center_name(c.get("region_label", "")),
                "msl": round(float(c.get("msl_hpa") or 0)),
                "is_high": c.get("type") == "Hoch",
            })

    strip = _strip_synoptik(wetterlage, dates).get(today, {})

    press_block = wetterlage.get("pressure_influence") or {}
    trend = press_block.get("trend", "")
    slope = press_block.get("slope_hpa_per_day")

    precip = None
    for entry in (wetterlage.get("precip_pattern") or {}).get("per_day") or []:
        if entry.get("date") != today:
            continue
        precip = {
            "north": entry.get("alpennord") or {},
            "south": entry.get("alpensued") or {},
        }

    thunder, overdev = [], []
    for entry in (wetterlage.get("konvektion") or {}).get("per_day") or []:
        if entry.get("date") != today:
            continue
        for _zone, val in (entry.get("zones") or {}).items():
            for name, _hours in val.get("gewitter") or []:
                if name not in thunder:
                    thunder.append(name)
            for name, _hours in val.get("ueberentwicklung") or []:
                if name not in overdev:
                    overdev.append(name)

    conf = ""
    for entry in wetterlage.get("confidence_per_day") or []:
        if entry.get("date") == today:
            conf = _CONFIDENCE[lang].get(entry.get("level", ""), entry.get("level", ""))

    t850_note = ""
    change = (wetterlage.get("t850_trend") or {}).get("change")
    if isinstance(change, dict) and change.get("delta_k") is not None:
        try:
            delta = float(change["delta_k"])
            word = ("kuehler" if lang == "de" else "cooler") if delta < 0 else \
                   ("waermer" if lang == "de" else "warmer")
            t850_note = f"{abs(delta):.1f} K {word}"
        except (TypeError, ValueError):
            t850_note = ""

    press_note = trend or ""
    if slope:
        try:
            press_note = f"{press_note} {float(slope):+.1f} hPa/d".strip()
        except (TypeError, ValueError):
            pass

    return {
        "lage": lage,
        "centers": centers,
        "pressure": strip.get("pressure", ""),
        "pressure_msl": strip.get("pressure_msl", ""),
        "pressure_regime": strip.get("pressure_regime", ""),
        "pressure_note": press_note,
        "pressure_trend": trend,
        "pressure_slope": slope,
        "flow": strip.get("wind", ""),
        "flow_speed": strip.get("wind_speed", ""),
        "flow_arrow": strip.get("wind_arrow", ""),
        "flow_note": " · ".join(x for x in (strip.get("wind_sector", ""),
                                            strip.get("wind_deg", ""),
                                            strip.get("wind_strength", "")) if x),
        "flow_hot": strip.get("wind_hot", False),
        "t850": strip.get("t850_value", ""),
        "t850_note": t850_note,
        "flags": strip.get("flags", []),
        "precip": precip,
        "thunder": thunder[:4],
        "overdev": overdev[:4],
        "confidence": conf,
        "confidence_level": next((e.get("level", "") for e in
                                  wetterlage.get("confidence_per_day") or []
                                  if e.get("date") == today), ""),
    }


def _day_verdict(raw_day: dict, region_ids) -> dict:
    """Einstufung des TAGES aus den Abo-Regionen (Entscheid 16.09.2026).

    Frueher: bester einzelner Startplatz — ein guter Spot hob den ganzen Tag,
    und die Zahl passte nicht zur Regionsliste darunter (Do 2/5 ueber drei
    Regionen mit 3). Jetzt zaehlt, wie der Tag in den Regionen insgesamt ist
    (Entscheid 12.10.2026: keine Mehrheits-Schwellen mehr — eine einzige
    Region mit Warnhinweisen darf nicht hinter "No alerts" verschwinden):
      not_safe     — mindestens eine Region mit schweren Warnhinweisen
      green        — alle bewerteten Regionen ohne Warnhinweise
      conditional  — sonst
      unknown      — keine Region mit Bewertung
    rating = Mittelwert der Regions-Bewertungen, kaufmaennisch gerundet.
    """
    by_id = {r.get("region_id"): r for r in (raw_day or {}).get("top_regions") or []}
    rated = []
    for rid in region_ids:
        r = by_id.get(rid) or {}
        band = r.get("safety_band")
        rating = int(r.get("experience_rating") or 0)
        if band in ("green", "amber", "red") and rating > 0:
            rated.append((band, rating))
    if not rated:
        return {"tier": "unknown", "rating": 0, "n": 0}
    n = len(rated)
    if any(b == "red" for b, _ in rated):
        tier = "not_safe"
    elif all(b == "green" for b, _ in rated):
        tier = "green"
    else:
        tier = "conditional"
    mean = sum(r for _, r in rated) / n
    return {"tier": tier, "rating": int(mean + 0.5), "n": n}


def _tier_band(tier: str) -> str:
    """Tages-Tier auf ein Safety-Band abbilden, damit der Streifen dieselbe
    Rating-Palette benutzt wie Region-Cards, Karte und Web-Ansicht."""
    if tier in ("violet", "green"):
        return "green"
    if tier in ("conditional", "gray"):
        return "amber"
    if tier in ("none", "not_safe"):
        return "red"
    return "no_data"
try:
    _TZ = ZoneInfo("Europe/Zurich")
except Exception:
    # Windows-Dev-PC ohne tzdata: die lokale Zone des Rechners ist hier ohnehin
    # die Schweizer — auf dem Server greift ZoneInfo.
    _TZ = datetime.now().astimezone().tzinfo

# ----------------------------------------------------------------------
# Labels (Ergaenzung zu v2) — beim Uebernehmen nach i18n.py
# ----------------------------------------------------------------------
_L3 = {
    "de": {
        "no_warning":   "keine Warnung",
        "spots_word":   "Spots",
        "regions_word": "Regionen",
        "ch_context":   "CH",
        "of":           "von",
        "step_lage":    "Lage",
        "step_front":   "Fronten",
        "step_foehn":   "Föhn",
        "step_wind":    "Höhenwind",
        "step_stab":    "Labilität",
        "step_thermik": "Thermik / Basis",
        "step_sonne":   "Sonne / Bewölkung",
        "step_modelle": "Modelle",
        # Status-Pille je Kettenglied (kurz, max 3 Woerter)
        "st_front_signs": "Zeichen sichtbar", "st_front_weaksigns": "schwache Zeichen", "st_front_nosigns": "keine Zeichen", "st_front_airmass": "Luftmassenwechsel", "st_front_none": "keine Front angezeigt", "st_front_rear": "Rückseite",
        "st_foehn_on": "Föhn angezeigt", "st_foehn_gusty": "einzelne Böen", "st_foehn_off": "keine Föhn-Anzeichen",
        "st_wind_stronger": "regional stärker", "st_wind_match": "regional wie im Mittel", "st_wind_weaker": "regional schwächer",
        "st_stab_thunder": "Gewitter angezeigt", "st_stab_labile": "teils Labilität angezeigt", "st_stab_stable": "stabile Luft angezeigt",
        "st_th_good": "gutes Steigen", "st_th_mod": "mässiges Steigen", "st_th_weak": "schwaches Steigen",
        "st_sun_match": "wie erwartet", "st_sun_partial": "teils anders", "st_sun_contra": "anders als erwartet",
        "st_md_agree": "Modelle einig", "st_md_partial": "meist einig", "st_md_uncertain": "Modelle uneinig",
        "fx_dwd": "DWD", "fx_signature": "Zeichen", "fx_sig_deutlich": "deutlich", "fx_sig_schwach": "schwach", "fx_sig_no": "keine",
        "fx_dp": "Druckunterschied Alpen", "fx_gust": "Böe", "fx_tal": "Föhntäler", "fx_tal_na": "n. prüfbar", "fx_t850": "T850", "fx_thunder_none": "keine Gewitter",
        "fx_ground": "am Boden ≈", "fx_peak": "Spitze",
        "md_head_0":     "Fazit: Gute Übereinstimmung der Modelle.",
        "md_head_1":     "Fazit: Ein offener Punkt.",
        "md_head_n":     "Fazit: {n} offene Punkte.",
        "md_warn":       "{what}: {zones} {window} sehen die Modelle {spread}{nomaj}; {agreewin}.",
        "md_warn_allday": "{what}: {zones} sehen die Modelle den ganzen Tag {spread}{nomaj}.",
        "md_spread":     "alles von {lo} bis {hi}",
        "md_nomaj":      ", keine Mehrheit",
        "md_info":       "{what} {window} ist weitgehend einig, nur {models} sieht {more}.",
        "md_info_plain": "{what} {window} ist nur knapp einig.",
        "md_least":      "{what} ist am wenigsten sicher ({pct} %), die Abweichungen bleiben aber lokal.",
        "md_more":       "mehr", "md_less": "weniger",
        "md_aw_morning":   "am Vormittag sind sie einig",
        "md_aw_midday":    "über Mittag sind sie einig",
        "md_aw_afternoon": "am Nachmittag sind sie einig",
        "md_aw_from_midday":  "ab Mittag sind sie einig",
        "md_aw_until_midday": "bis Mittag sind sie einig",
        "md_aw_split":     "am Vormittag und am Nachmittag sind sie einig",
        "md_aw_none":      "uneinig über den ganzen Tag",
        "md_grp":        "{label}: {models}",
        "md_line":       "{what} · {groups}",
        "md_win_morning": "am Vormittag", "md_win_midday": "über Mittag", "md_win_afternoon": "am Nachmittag",
        "md_var_rain": "Niederschlag", "md_var_dir": "Windrichtung", "md_var_speed": "Wind",
        "md_var_gust": "Böen", "md_var_cloud": "Bewölkung", "md_var_cloud_low": "tiefe Wolken",
        "md_lab_rain_0": "trocken", "md_lab_rain_1": "Niederschlag",
        "md_lab_gust_0": "unter 15 km/h", "md_lab_gust_1": "15–25 km/h", "md_lab_gust_2": "25–40 km/h",
        "md_lab_gust_3": "40–60 km/h", "md_lab_gust_4": "60–80 km/h", "md_lab_gust_5": "über 80 km/h",
        "md_lab_speed_0": "unter 10 km/h", "md_lab_speed_1": "10–20 km/h", "md_lab_speed_2": "20–30 km/h",
        "md_lab_speed_3": "30–45 km/h", "md_lab_speed_4": "45–60 km/h", "md_lab_speed_5": "60–80 km/h",
        "md_lab_speed_6": "über 80 km/h",
        "md_lab_cloud_0": "0–20 %", "md_lab_cloud_1": "20–40 %", "md_lab_cloud_2": "40–60 %",
        "md_lab_cloud_3": "60–80 %", "md_lab_cloud_4": "80–100 %",
        "md_lab_dir_0": "N", "md_lab_dir_1": "NO", "md_lab_dir_2": "O", "md_lab_dir_3": "SO",
        "md_lab_dir_4": "S", "md_lab_dir_5": "SW", "md_lab_dir_6": "W", "md_lab_dir_7": "NW",
        "md_word_rain_0": "trocken", "md_word_rain_1": "Niederschlag",
        "md_word_gust_0": "ruhig", "md_word_gust_1": "fliegbar", "md_word_gust_2": "stark",
        "md_word_gust_3": "verblasen", "md_word_gust_4": "Sturm", "md_word_gust_5": "schwerer Sturm",
        "md_word_speed_0": "Flaute", "md_word_speed_1": "schwachem Wind", "md_word_speed_2": "mässigem Wind",
        "md_word_speed_3": "frischem Wind", "md_word_speed_4": "starkem Wind", "md_word_speed_5": "Sturm",
        "md_word_speed_6": "Orkan",
        "md_word_cloud_0": "wolkenlos", "md_word_cloud_1": "aufgelockert", "md_word_cloud_2": "halb bedeckt",
        "md_word_cloud_3": "stark bewölkt", "md_word_cloud_4": "bedeckt",
        "md_word_dir_0": "Nord", "md_word_dir_1": "Nordost", "md_word_dir_2": "Ost", "md_word_dir_3": "Südost",
        "md_word_dir_4": "Süd", "md_word_dir_5": "Südwest", "md_word_dir_6": "West", "md_word_dir_7": "Nordwest",
        "su_exp_high":  "{Press}: viel Sonne zu erwarten",
        "su_exp_low":   "{Press}: viel Bewölkung zu erwarten",
        "su_exp_flat":  "Übergangslage: wechselnde Bewölkung zu erwarten",
        "su_air_south": ", die feuchte {sector}luft bringt aber Wolken in den Süden",
        "su_air_north": ", die {sector}luft bringt aber Wolken an den Alpennordhang",
        "su_data":      " — {models} zeigt {zones}{best}.",
        "su_match":     ". {models} bestätigt die Zweiteilung: {zones}{best}.",
        "su_match_all": ". {models} bestätigt das landesweit: {zones}{best}.",
        "su_partial":   ". {models} zeigt das nur teilweise: {zones}{best} — {miss}.",
        "su_contra":    ". {models} widerspricht: {zones}{best} — {miss}.",
        "su_miss_north_cloudy": "mehr Wolken im Norden, als die Lage erwarten lässt",
        "su_miss_north_sunny":  "die Wolken am Alpennordhang bleiben aus",
        "su_miss_south_cloudy": "mehr Wolken im Süden, als die Lage erwarten lässt",
        "su_miss_south_sunny":  "die feuchte Luft zeigt sich im Süden nicht",
        "su_zone":      "{where} {word}{cloud}",
        "su_group":     "{zones} {word}{cloud}",
        "su_word_sunny": "meist sonnig", "su_word_mixed": "teils sonnig", "su_word_overcast": "meist bedeckt",
        "su_low":       " mit tiefen Wolken (unter 2 km)",
        "su_high":      " unter mittelhohen und hohen Wolken (über 2 km)",
        "su_best":      "; am sonnigsten {zone}",
        "su_both":      "im ganzen Land {word}",
        "su_north":     "im Norden", "su_south": "im Süden",
        "su_lbl_sun":   "Sonne 10–16 Uhr", "su_lbl_low": "Wolken unter 2 km", "su_lbl_high": "Wolken über 2 km",
        "th_exp_high":  "{Press}: Absinken und eine gedeckelte Basis zu erwarten",
        "th_exp_low":   "{Press}: hohe Basis, aber Überentwicklung zu erwarten",
        "th_exp_flat":  "Übergangslage: keine klare Schichtung zu erwarten",
        "th_press_hoch": "Hochdruck", "th_press_up": "Steigender Druck",
        "th_press_tief": "Tiefdruck", "th_press_down": "Fallender Druck",
        "th_t850_warm": ", die warme Höhenluft bremst das Steigen",
        "th_t850_cold": ", die kalte Höhenluft fördert kräftiges Steigen",
        "th_data":      " — {models} zeigt {base}, {climb}{start}{sun}.",
        "th_match":     ". {models} bestätigt die gedeckelte Basis: {base}, {climb}{start}{sun}.",
        "th_match_high": ". {models} bestätigt die hohe Basis: {base}, {climb}{start}{sun}.",
        "th_contra_higher": ". {models} zeigt das nicht: {base}, {climb}{start}{sun} — die Basis liegt höher, als die Lage erwarten lässt.",
        "th_contra_lower":  ". {models} zeigt das nicht: {base}, {climb}{start}{sun} — die Basis bleibt tiefer, als die Lage erwarten lässt.",
        "th_base_range": "Basis {lo_zone} am tiefsten, {hi_zone} am höchsten",
        "th_base_one":  "Basis überall ähnlich",
        "th_lbl_base":  "Basis", "th_lbl_climb": "Steigen", "th_lbl_from": "ab", "th_unit_h": " Uhr",
        "th_base_none": "keine Basisangabe",
        "th_climb":     "Steigen {grade}",
        "th_grade_weak": "schwach", "th_grade_mod": "mässig", "th_grade_good": "gut", "th_grade_strong": "kräftig",
        "th_start":     ", Thermik ab {h} Uhr",
        "th_sun_split": "; {sunny} sonnig, {cloudy} bedeckt",
        "th_sun_all":   "; verbreitet sonnig",
        "th_cloud_all": "; verbreitet tiefe Bewölkung",
        "th_north":     "Norden", "th_south": "Süden",
        "ground_est":   "am Boden zu erwarten",
        "rule_23":      "⅔-Regel",
        "front_none":   "Daten zeigen keine Front im Vorhersagefenster (DWD).",
        # Fazit — Prognosedaten, nie eine finale Aussage
        # Stroemungsrichtung (Hoehenwind-Block, Wochenkacheln)
        "lg_sector_N":     "Nord", "lg_sector_NE": "Nordost", "lg_sector_E": "Ost", "lg_sector_SE": "Südost",
        "lg_sector_S":     "Süd", "lg_sector_SW": "Südwest", "lg_sector_W": "West", "lg_sector_NW": "Nordwest",
        # Lage wie Foehn (User 26.10.2026): gleicher Aufbau — Pille "n von 4", vier
        # Chips (Luftdruck zuerst, erfuellte hervorgehoben), Satz "zeigt … auf",
        # "Auch die Daten zeigen Zeichen dafür", "Nicht in den Daten", "Dagegen"
        # Labels als Woerter (User 31.10.2026): Zahlen stehen im Text darunter
        "li_k_drucklage":  "Drucklage", "li_v_neither": "weder Hoch noch Tief",
        "li_k_tend3":      "{subj} nächste 3 Tage", "li_k_tagesgang": "{subj} heute 6–22 Uhr",
        "li_subj_none":    "Druck",
        "li_w_aufbau":     "baut sich auf", "li_w_abklingen": "klingt ab", "li_w_gleich": "etwa gleich",
        "li_w_verst":      "verstärkt sich", "li_w_abbau": "baut ab",
        "li_w_steigt":     "steigt", "li_w_faellt": "fällt",
        "li_side_hoch":    "Hochdruck", "li_side_tief": "Tiefdruck",
        "li_k_p_hoch":     "Luftdruck ≥{thr} hPa", "li_k_p_tief": "Luftdruck ≤{thr} hPa",
        "li_k_trend":      "Tendenz 3 Tage",
        "li_v_trend":      "{v} hPa/Tag",
        "li_k_day":        "Druckverlauf 6–22 Uhr",
        "li_v_mixed":      "uneinheitlich",
        "li_k_c_hoch":     "Hoch ≤{km} km", "li_k_c_tief": "Tief ≤{km} km",
        "li_v_none":       "keines",
        # Satz 1: Zustand und Entwicklung des Drucks ueber der Schweiz (User 26.10.2026)
        # Text (User 26.10.2026): Was liegt ueber der Schweiz, wie entwickelt sich der
        # Druck ueber den Flugtag, Ausblick ueber die drei Tage — kein "Zeichen dafür"
        "li_p_on":         "In {m} liegt über der Schweiz {side} ({hpa}).",
        "li_p_off":        "In {m} liegt über der Schweiz weder Hoch- noch Tiefdruck ({hpa}).",
        "li_dday_verst":   " Über den Tag (6–22 Uhr) verstärkt sich der {side} ({v} hPa).",
        "li_dday_abbau":   " Über den Tag (6–22 Uhr) baut sich der {side} ab ({v} hPa).",
        "li_day_up":       " Über den Tag (6–22 Uhr) steigt der Druck um {v} hPa.",
        "li_day_down":     " Über den Tag (6–22 Uhr) fällt der Druck um {v} hPa.",
        "li_day_flat":     " Über den Tag (6–22 Uhr) bleibt der Druck etwa gleich ({v} hPa).",
        "li_day_mixed":    " Über den Tag (6–22 Uhr) verläuft der Druck uneinheitlich{wie}.",
        "li_day_ns":       ": Norden {a}, Süden {b}",
        "li_day_one":      ": {zone} {a}, übrige Zonen {b}",
        "li_jump":         " Am stärksten ändert er sich zwischen {von} und {bis} Uhr: {v} hPa in 3 Stunden ({zone}).",
        "li_dev":          " Über die drei Prognosetage {was} ({v} hPa pro Tag).",
        "li_was_hoch_up":  "baut sich der Hochdruck auf", "li_was_hoch_down": "klingt der Hochdruck ab",
        "li_was_tief_down": "baut sich der Tiefdruck auf", "li_was_tief_up": "klingt der Tiefdruck ab",
        "li_was_on_flat":  "bleibt der {side} etwa gleich",
        "li_was_off_up":   "steigt der Druck", "li_was_off_down": "fällt der Druck",
        "li_was_off_flat": "bleibt der Druck etwa gleich",
        "lg_rain_fading":  " und im Tagesverlauf abklingend",
        "lg_rain_south_growing": "meist trocken, auf der Alpensüdseite Schauer und am Nachmittag zunehmend",
        "lg_rain_for_now": "vorerst ",
        "lg_rain_growing": " und am Nachmittag zunehmend",
        "lg_rain_dry":     "trocken",
        "lg_rain_mostly_dry": "meist trocken",
        "lg_rain_south_only": "meist trocken, Schauer nur auf der Alpensüdseite",
        "lg_rain_north_only": "meist trocken, Regen nur auf der Alpennordseite",
        "lg_rain_partly":  "teils Regen",
        "lg_rain_wide":    "verbreitet Regen",
        "lg_wind_calm":    "Wind ruhig",
        "lg_wind_partly":  "teils windig",
        "lg_wind_wide":    "verbreitet windig",
        "lg_wind_strong":  "verbreitet stark windig",
        "lg_wind_aloft":   " vom Höhenwind",
        "lg_wind_less_south": ", auf der Alpensüdseite weniger",
        "lg_wind_less_north": ", auf der Alpennordseite weniger",
        "from_morning":    "ab dem Morgen", "from_midday": "ab Mittag",
        "from_afternoon":  "ab dem Nachmittag", "from_evening": "ab dem Abend",
        "wc_windig":       "windig", "wc_verblasen": "verblasen", "wc_ruhig": "ruhig",
        "wc_stark_eingeschraenkt": "stark eingeschränkt",
        # Foehn: Anspruch der Synoptik gegen die Prognosedaten
        "fb_foehn_yes":     "Daten deuten auf {Side}föhn hin: Druckgefälle {dp} hPa über die Alpen. {models} zeigt ihn auch — am Lee-Prognosepunkt {station} Böen bis {gust} km/h{windows}.",
        "fb_foehn_aloft":   "Daten deuten auf {Side}föhn hin: Druckgefälle {dp} hPa über die Alpen, doch am Lee-Prognosepunkt {station} zeigt {models} kaum Böen (bis {gust} km/h) — in der Höhe können die Daten trotzdem auf Föhn hindeuten.",
        "fb_foehn_no":      "Daten zeigen keine Föhn-Anzeichen: das Druckgefälle über die Alpen bleibt mit {dp} hPa unter der Schwelle von 4 hPa.{strong}",
        "fb_foehn_no_nodp": "Daten zeigen keine Föhn-Anzeichen: kein nennenswertes Druckgefälle über die Alpen.{strong}",
        # Bestaetigung am Talboden: Foehn-Talpunkte (data/foehn_talpunkte.geojson)
        "fb_foehn_tal_yes": "Daten deuten auf {Side}föhn hin: Druckgefälle {dp} hPa über die Alpen. {model} zeigt den Föhn auch am Boden in {taeler} — Wind {w1}–{w2} km/h aus {dir}, Böen bis {g} km/h ({gtal}){when}.",
        "fb_foehn_tal_no":  "Anzeichen für {Side}föhn: Druckgefälle {dp} hPa über die Alpen. {tal_wind} In der Höhe können die Daten trotzdem auf Föhn hindeuten, Startplätze auf 1500–2000 m können betroffen sein.",
        "fb_tal_weak": "In den {n} Föhntälern zeigt {model} Wind bis {w} km/h, Böen bis {g} km/h ({gtal}) — die Windstärke deutet am Talboden nicht auf Föhn hin.",
        "fb_tal_strong": "In den {n} Föhntälern zeigt {model} Wind bis {w} km/h, Böen bis {g} km/h ({gtal}) — der Wind zeigt aber nicht das typische Föhnmuster (Richtung, trockene Luft).",
        "fb_tal_nonum": "Der Wind an den {n} Föhn-Talpunkten ({model}) deutet am Talboden nicht auf Föhn hin.",
        "fb_foehn_tal_na":  " Bestätigung durch Talwind nicht prüfbar (keine Talpunkt-Daten).",
        "fb_tal_more":      " u. a.",
        # Foehn-Block nach Talmerkmalen (User 14.10.2026, Blog wetterkunde/foehn):
        # beide Seiten jeden Tag, Richtung + Wind + trockene Luft, Druck nur als Zahl.
        "fv_side_sued":     "Täler Nordseite",
        "fv_side_nord":     "Täler Südseite",
        "fv_full":          "{side}: trockener Wind aus Föhnrichtung in {n} von {t} Tälern — {taeler}; Böen bis {g} km/h.",
        "fv_dirdry":        "{side}: trockener Wind aus Föhnrichtung in {n} von {t} Tälern — {taeler}; Wind noch schwach, Böen bis {g} km/h.",
        "fv_none":          "{side}: kein trockener Wind aus Föhnrichtung in den {t} Tälern, Talwind bis {w} km/h.",
        "fv_both_none":     "Täler: kein trockener Wind aus Föhnrichtung in den {t} Tälern, Talwind bis {w} km/h.",
        "fv_aloft":         "In der Höhe: Böen bis {g} km/h aus {dir} ({spot}, {alt} m).",
        "fv_none_short":    "{side}: kein trockener Wind aus Föhnrichtung in den {t} Tälern, Talwind bis {w} km/h.",
        "fv_dp":            "Druckunterschied über die Alpen: {dp} hPa.",
        "fv_dp_high":       "Druckunterschied über die Alpen: {dp} hPa — in dieser Grösse ist Föhn in den grossen Föhntälern häufig.",
        "fv_na":            "Föhntäler: keine Taldaten verfügbar.",
        "fvs_full":         "Trockener Wind aus Föhnrichtung: {n} von {t} Tälern",
        "fvs_dirdry":       "Trockener Wind aus Föhnrichtung: {n} von {t} Tälern",
        "fvs_aloft":        "Wind in der Höhe {g} km/h",
        "fvs_dp":           "Druckunterschied {dp} hPa",
        "fvs_none":         "Trockener Wind aus Föhnrichtung: 0 von {t} Tälern",
        "fx_rh":            "Tiefste Talfeuchte",
        "fx_gust_aloft":    "Böe in der Höhe",
        "fv_side_na":       "{side}: keine Taldaten — nicht prüfbar.",
        "fv_name_dir":      "{tal} aus {dir}",
        "fv_dir_N": "N", "fv_dir_NE": "NO", "fv_dir_E": "O", "fv_dir_SE": "SO",
        "fv_dir_S": "S", "fv_dir_SW": "SW", "fv_dir_W": "W", "fv_dir_NW": "NW",
        # Einordnung: feste Saetze, was ein Datenmuster ueblicherweise bedeutet,
        # immer mit Grenze (User 14.10.2026; Grundlage Blog wetterkunde/foehn).
        "fvr_quiet":   "Einordnung: Die Föhn-Indikatoren in den Tälern zeigen kein Föhnsignal. Das ist eine Modellprognose: Seichter Föhn wird von Modellen oft nicht erfasst, und inneralpin (Wallis, Domleschg, Davos) setzt Föhn auch bei kleinem Druckunterschied ein. Am Flugtag die Live-Werte an Tal- und Gipfelstationen prüfen.",
        "fvr_pool":    "Einordnung: In solchen Daten kann der Föhn über den ruhigen Tälern wehen, über einem Kaltluftsee. Auf Starthöhe kann es stark wehen, während das Tal ruhig ist, und der Föhn kann bis zum Boden durchbrechen.",
        "fvr_dirdry":  "Einordnung: Die Luft zeigt Föhn-Eigenschaften, der Modellwind ist aber schwach. Die Modelle zeigen Föhnwind meist zu schwach — Föhn am Talboden ist deshalb nicht auszuschliessen.",
        "fvr_full":    "Einordnung: In diesen Tälern zeigt die Prognose trockenen Wind aus der Föhnrichtung — die Merkmale, an denen MeteoSchweiz Föhn am Talboden erkennt. Die Modelle zeigen Föhnwind meist zu schwach, und Nachbartäler können um Stunden versetzt sein.",
        "fvr_dp_high": "Einordnung: Bei so grossem Druckunterschied tritt in den grossen Föhntälern häufig Föhn auf, auch wenn die Taldaten noch ruhig sind.",
        "fvr_guide":   "So liest du Föhn-Daten",
        "fvr_legend":  "So wird gezählt: Ein Tal zählt, wenn die Prognose ({model}) dort mindestens {h} Stunden zwischen {h0} und {h1} Uhr Wind aus der Föhnrichtung dieses Tals zeigt, mit Wind ab {w} km/h oder Böen ab {g} km/h und höchstens {rh} % Luftfeuchte. Die Föhnrichtung je Tal stammt aus Messungen von MeteoSchweiz ({m} von {n} Tälern, die übrigen: Halbkreis).",
        # Vier Foehn-Indikatoren (15.10.2026): Labels oben, Datentext darunter
        "fi_pill":       "Föhn-Indikatoren: {n} von 4",
        "fi_k_dp":       "Druckdiff.",
        "fi_v_dp":       "{dp} hPa ({side} höher)",
        "fi_hi_sued":    "Süden", "fi_hi_nord": "Norden",
        "fi_k_map":      "Regionen mit {dirw} ≥{kmh} km/h",
        "fi_v_map":      "{n} von {t}",
        "fi_k_luv_sued": "Südseite Höhe", "fi_k_luv_nord": "Nordseite Höhe",
        "fi_v_cooler":   "{k} °C kühler", "fi_v_warmer": "{k} °C wärmer", "fi_v_equal": "gleich warm",
        "fi_k_val":      "Täler mit trockenem {dirw} ≥{kmh} km/h",
        "fi_v_val":      "{n} von {t}",
        "fi_tal_multi":  "{n} von {t} Föhntälern zeigen trockenen Wind aus Föhnrichtung, am stärksten {name} (Böen bis {g} km/h)",
        "fi_tal_one":    "{name} zeigt trockenen Wind aus Föhnrichtung (Böen bis {g} km/h)",
        "fi_map_on":     "{n} von {t} Alpenregionen haben starken {dirw}, vor allem {names}",
        "fi_dp_on":      "der Druck ist im {side} {dp} hPa höher",
        "fi_luv_on":     "{side} ist in der Höhe {k} °C kühler",
        # nicht erfuellt: Nominalgruppen nach dem Doppelpunkt, ohne Wertung (nie "nur"/"klein"/"schwach")
        "fi_x_tal":      "kein Föhntal mit trockenem Wind aus Föhnrichtung",
        "fi_x_map":      "starker {dirw} in {n} von {t} Regionen ({names})",
        "fi_x_map_none": "keine Alpenregion mit starkem Wind aus Föhnrichtung",
        "fi_x_dp":       "ein Druckunterschied von {dp} hPa",
        "fi_x_luv":      "{side} in der Höhe {k} °C kühler",
        "fi_x_luv_warm": "{side} in der Höhe {k} °C wärmer",
        "fi_x_luv_eq":   "in der Höhe beide Seiten gleich warm",
        "fi_dirw_sued":  "Südwind", "fi_dirw_nord": "Nordwind",
        "fi_luv_sued":   "die Südseite", "fi_luv_nord": "die Nordseite",
        "fi_all":        "Alle vier Indikatoren sind erfüllt: ",
        "fi_none":       "Keiner der vier Indikatoren ist erfüllt: ",
        "fi_rest_1":     "Der vierte Indikator ist nicht erfüllt: ",
        "fi_rest_2":     "Die übrigen zwei Indikatoren sind nicht erfüllt: ",
        "fi_rest_3":     "Die übrigen drei Indikatoren sind nicht erfüllt: ",
        "fi_and":        " und ",
        # Deutungstext (15.10.2026): erklaert, was die Labels zusammen bedeuten — Zahlen stehen oben
        "fd_p_on":       "In {m} zeigt der Druckunterschied{ab} auf {foehn}.",
        "fd_p_off":      "In {m} zeigt der Druckunterschied nicht auf Föhn.",
        "fd_s_also":     " Auch die Daten zeigen{ab} Zeichen dafür: {seq}.",
        "fd_s_still":    " Trotzdem zeigen die Daten{ab} Zeichen von {foehn}: {seq}.",
        "fd_s_other":    " Die Daten zeigen aber{ab} Zeichen von {foehn}: {seq}.",
        "fd_s_none":     " Auch die übrigen Föhnzeichen zeigen die Daten nicht.",
        "fd_signs":      " {m} zeigt{ab} Zeichen von {foehn}: {seq}.",
        "fd_seq_later":  ",{ab} {item}",
        "fd_absent":     " Nicht in den Daten: {liste}.",
        "fd_i_map_wo":   " (vor allem {names})",
        "fd_i_val_wo":   " (am stärksten {name})",
        "fd_i_val_1":    "trockener Wind aus Föhnrichtung in {name}",
        "fd_against":    " Dagegen: {liste}.",
        "fd_ag_map":     "{dirw} in den Regionen",
        "fd_ag_tp":      "wärmere {luv}seite in der Höhe",
        "fd_ag_val":     "trockener Föhnwind in Tälern der Gegenseite",
        "fd_m_tp":       "kühlere {luv}seite in der Höhe",
        "fd_m_map":      "Wind aus Föhnrichtung in den Regionen", "fd_m_val": "trockener Wind aus Föhnrichtung in den Tälern",
        "fd_foehn_sued": "Südföhn", "fd_foehn_nord": "Nordföhn",
        "fd_luv_sued":   "Süd", "fd_luv_nord": "Nord",
        "fd_r_inner":    " Inneralpiner Föhn setzt oft ohne sie ein.",
        "fd_r_weak":     " Modelle zeigen Föhnwind meist zu schwach.",
        "fd_r_none":     " Föhn bleibt trotzdem möglich: Modelle übersehen oft Föhn, der nur flach über die Pässe kommt oder auf einzelne Täler beschränkt ist. Am Flugtag die Live-Werte an Tal- und Gipfelstationen prüfen.",
        "fd_ab":         " ab etwa {t}", "fd_ab_start": " bereits um {t}",
        "fd_model_x":    "den Daten",
        # Fronten-Block nach Zeichen (17.10.2026): DWD-Karte ohne Uhrzeit, dann die
        # Modellzeichen mit Tageszeit; jedes Label kommt im Text vor
        "fz_pill":        "Frontzeichen: {n} von 4", "fz_pill_from": " · ab ~{t}",
        "fz_k_dwd":       "DWD-Karte", "fz_k_kaelter": "Kälter auf 1500 m", "fz_k_waermer": "Wärmer auf 1500 m",
        "fz_k_luft":      "Luftmasse 1500 m ändert sich", "fz_k_dreh": "Winddrehung in der Höhe",
        "fz_k_regen":     "Regen", "fz_k_dauerregen": "Dauerregen", "fz_k_wolken": "Bewölkung verdichtet sich",
        "fz_typ_kalt":    "Kaltfront", "fz_typ_warm": "Warmfront", "fz_typ_okklusion": "Okklusion",
        "fz_dwd_yes":     "DWD-Prognosekarte: {typ}.",
        "fz_dwd_no":      "DWD-Prognosekarte: keine Front prognostiziert.",
        "fz_pill_none":   "DWD-Karte: keine Front",
        "fz_match":       " {models} zeigt Zeichen ab etwa {t}{move}: {det}.",
        "fz_nomatch":     " {models} zeigt keines der passenden Zeichen.",
        "fz_absent":      " Nicht in den Daten: {liste}.",
        "fz_carried":     " Vom Vortag noch in den Daten: {liste}.",
        "fz_x_kaelter":   "kältere Luft auf 1500 m", "fz_x_waermer": "wärmere Luft auf 1500 m",
        "fz_x_luft":      "eine andere Luftmasse auf 1500 m", "fz_x_dreh": "eine Winddrehung in der Höhe",
        "fz_x_regen":     "Regen", "fz_x_dauerregen": "Dauerregen", "fz_x_wolken": "dichtere Bewölkung",
        "fz_dp_0": "in der Nacht", "fz_dp_1": "am frühen Morgen", "fz_dp_2": "am Vormittag",
        "fz_dp_3": "um die Mittagszeit", "fz_dp_4": "am Nachmittag", "fz_dp_5": "am Abend", "fz_dp_6": "in der Nacht",
        "fz_move":        ", von {a} nach {b} fortschreitend",
        "fz_dir_N": "Norden", "fz_dir_S": "Süden", "fz_dir_W": "Westen", "fz_dir_E": "Osten",
        "fz_carried_v":   " (Vortag)", "fz_time": "{h} Uhr",
        "fi_close_none":  "Modellprognose — seichter Föhn wird oft nicht erfasst.",
        "fi_close_inner": "Inneralpiner Föhn setzt oft ohne die übrigen Zeichen ein.",
        "fi_close_weak":  "Modelle zeigen Föhnwind in den Tälern meist zu schwach.",
        "fi_guide":      "So zählen wir",
        "fb_dir_sued":      "Süd", "fb_dir_nord": "Nord",
        "fb_strong_none":   " {models} zeigt auch keine Böen ab {g} km/h an den Startplätzen.",
        "fb_strong_some":   " {models} zeigt trotzdem starke Winde an einzelnen Startplätzen: Böen bis {gust} km/h aus {dir} ({spot}, {alt} m, {when}){cmp} — die Daten zeigen Höhenwind, ohne Föhn-Anzeichen.",
        "fb_models":        "; die Modelle sind uneinig, CH2 sieht nur {ch2} km/h",
        "fb_station_nord":  "Zürich", "fb_station_sued": "Lugano",
        "fb_side_nord":     "Nord", "fb_side_sued": "Süd",
        "fb_win_from":      ", ab {when}",
        # Labilitaet: Erwartung aus der Synoptik gegen CAPE / Gewitter / Ueberentwicklung
        "lb_expect":        "{air}{press}",
        "lb_air_humid":     "Feuchte {sector}luft: Labilität zu erwarten",
        "lb_air_cool":      "Kühle {sector}luft: Schauer und Labilität am Nordhang zu erwarten",
        "lb_air_neutral":   "{Sector}strömung: keine ausgeprägt labile Luft",
        "lb_press_cap":     ", der {regime} deckelt sie aber",
        "lb_press_up":      ", der steigende Druck deckelt sie aber zunehmend",
        "lb_press_low":     ", der Tiefdruck begünstigt sie",
        "lb_press_none":    "",
        "lb_regime_hoch":   "Hochdruck",
        "lb_data":          " — {models} zeigt {what}.",
        "lb_match":         ". {models} bestätigt die Labilität: {what}.",
        "lb_match_stable":  ". {models} bestätigt die stabile Schichtung: {what}.",
        "lb_partial":       ". {models} zeigt das nur teilweise: {what} — der Deckel hält am Alpennordhang nicht.",
        "lb_contra_stable": ". {models} zeigt das nicht: {what} — die Luft ist stabiler, als die Lage vermuten lässt.",
        "lb_contra_labile": ". {models} widerspricht: {what} — labiler, als die Lage vermuten lässt.",
        "lb_stable":        "überall stabile Luft, keine Gewitter",
        "lb_labile_only":   "nur {zones}, ohne Gewitter{overdev}{north}",
        "lb_labile_wide":   "{zones}, ohne Gewitter{overdev}",
        "lb_thunder":       "Gewitter {zones}{overdev}{north}",
        "lb_thunder_at":    "{zone} ab {hour} Uhr",
        "lb_overdev":       ", Überentwicklung {zones}",
        "lb_od_in":         ", Überentwicklung ab {hour} Uhr",
        "lb_zone_grade":    "{zone} ({grade}{od})",
        "lb_od_zone":       "Überentwicklung {zone} ab {hour} Uhr",
        "lb_north_capped":  "; am Alpennordhang bleibt die Luft gedeckelt",
        "lb_grade_light":   "leicht labil", "lb_grade_mod": "labil", "lb_grade_strong": "stark labil",
        "lb_in":            "im ", "lb_in_plural": "in ",
        "front_today_in":     "{Day}: Die {typ} {art} {zone} voraussichtlich {when}{unsicher}{prov}.",
        "front_fazit_none_more": "Danach zeigen die Daten im 3-Tage-Fenster keine weitere Front.",
        # Frontzeichen (seit 09.10.2026): DWD nennt die Front, die eigene
        # Prognose beschreibt ihre Zeichen — kein Urteil "zieht durch/loest sich auf"
        "front_z_deutlich":   "{Day}: In der DWD-Prognose wird {when} eine {typ} über {zone_dat} angegeben. {models} zeigt dazu deutliche Zeichen: {zeichen}.",
        "front_z_schwach":    "{Day}: In der DWD-Prognose wird {when} eine {typ} über {zone_dat} angegeben. {models} zeigt dazu nur schwache Zeichen: {zeichen}.",
        "front_z_keine":      "{Day}: In der DWD-Prognose wird {when} eine {typ} über {zone_dat} angegeben. {models} zeigt dazu keine Zeichen.",
        "front_z_ohne_dwd":   "{Day}: In der DWD-Prognose ist keine Front über der Schweiz angegeben. {models} zeigt über {zone_dat} aber deutliche Zeichen eines Luftmassenwechsels: {zeichen}.",
        "ez_druck_deutlich":  "kräftiger Druckanstieg ({val} hPa in 12 h)",
        "ez_druck_schwach":   "Druckanstieg ({val} hPa in 12 h)",
        "ez_druckfall_deutlich": "kräftiger Druckfall ({val} hPa in 12 h)",
        "ez_druckfall_schwach": "Druckfall ({val} hPa in 12 h)",
        "front_z_gegen":      " Stattdessen: {gegen}.",
        "ez_kalt_deutlich":   "deutlich kältere Luft auf 1500 m ({val} °C gegenüber dem Vortag)",
        "ez_kalt_schwach":    "etwas kältere Luft auf 1500 m ({val} °C gegenüber dem Vortag)",
        "ez_warm_deutlich":   "deutlich wärmere Luft auf 1500 m ({val} °C gegenüber dem Vortag)",
        "ez_warm_schwach":    "etwas wärmere Luft auf 1500 m ({val} °C gegenüber dem Vortag)",
        "ez_regen_deutlich":  "Regen ({val} mm)",
        "ez_regen_schwach":   "etwas Regen ({val} mm)",
        "ez_drehung":         "Höhenwind dreht auf {sector}",
        "front_generic":      "Front",
        "sectors":            "Nord,Nordost,Ost,Südost,Süd,Südwest,West,Nordwest",
        "front_prev_run":     " (Lauf von gestern; heute früh {dist} km {dir})",
        "front_fazit_in_more": "Gemäss Prognosedaten dürfte eine weitere {typ} {zone} {day} {when} {art}{unsicher}.",
        "front_today_none":   "{Day}: Daten zeigen keine Front.",
        "front_passed":       "{When}: Die {typ} ist über {zone} gezogen (DWD-Analyse) — {day} auf der Rückseite.",
        "yesterday":          "gestern",
        "front_fazit_in":     "Gemäss Prognosedaten dürfte die {typ} {zone} {day} {when} {art}{unsicher}.",
        "front_fazit_later":  "Gemäss Prognosedaten erreicht die {typ} die Schweiz frühestens {day} — nach dem 3-Tage-Fenster.",
        "front_fazit_stays":  "Gemäss Prognosedaten bleibt die {typ} ({dist} km {dir}) im 3-Tage-Fenster fern der Schweiz.",
        "front_fazit_none":   "Gemäss Prognosedaten erreicht im 3-Tage-Fenster keine Front die Schweiz.",
        "front_unsicher":     " — unsicher, nur ein Randkontakt",
        "front_far":    "{typ} {dist} km {dir} — ausserhalb der Reichweite heute.",
        "front_near":   "{typ} {dist} km {dir}.",
        "front_pass":   "{typ} {art} {zone} {when}.",
        "kalt":         "Kaltfront",
        "warm":         "Warmfront",
        "okklusion":    "Okklusion",
        "quert":        "quert",
        "streift":      "streift",
        "morning":      "am Vormittag",
        "midday":       "um die Mittagszeit",
        "afternoon":    "im Laufe des Nachmittags",
        "evening":      "am Abend",
        "night":        "in der Nacht",
        "showers_from": "Schauer ab {h} Uhr",
        "showers_onset": "Schauerbeginn",
        "simultaneous": "überall gleichzeitig",
        "foehn_none":   "Daten zeigen keine Föhn-Anzeichen.",
        "foehn_line":   "Daten deuten auf {side}föhn hin ({level}), {h} h.",
        "north":        "Nord",
        "south":        "Süd",
        "level_caution": "mässig",
        "level_danger": "stark",
        "thunder_window": "im Flugfenster 10–18 Uhr",
        "thunder_caveat": "Fehlalarmrate hoch — vor Ort prüfen.",
        "no_convection": "keine Gewitter, keine Überentwicklung",
        "climb":        "Steigen",
        "height":       "Arbeitshöhe",
        "hours":        "produktive Stunden",
        "spots_link":   "Spots ansehen",
        "map_title":    "Synoptik",
        "map_caption":  "Bodendruck {model} · {ts} · Fronten: DWD {kind} {valid}",
        "map_analysis": "Bodenanalyse",
        "map_forecast": "Vorhersage +{h} h",
        "legend_cold":  "Kaltfront",
        "legend_warm":  "Warmfront",
        "legend_occl":  "Okklusion",
        "legend_flow":  "Höhenströmung 700 hPa",
        "w_foehn":      "Daten deuten auf {side}föhn hin ({level}) an {days} ({h}).",
        "w_storm":      "Höhenwind bis {kmh} km/h ({days}) — am Boden ≈ {ground} km/h zu erwarten.",
        "w_thunder":    "Daten zeigen Gewitterzellen im Flugfenster: {zones} ({days}). Fehlalarmrate bei 5 % Grundrate hoch — vor Ort prüfen.",
        "w_overdev":    "Daten deuten auf mögliche Überentwicklung hin: {zones} ({days}). Weiche Vorwarnung, kein Alarm.",
        "w_shear":      "Daten zeigen Windscherung an {days} — die Thermik dürfte zerrissen werden, Details je Region.",
        "w_gusts":      "Böen-Hinweise aus den Spot-Analysen an {days} — der Höhenwind selbst bleibt schwach ({kmh} km/h auf 700 hPa). Details je Region.",
        "w_thunder_spots": "Gewitter-Hinweise in den Spot-Analysen an {days} — die Synoptik zeigt an diesen Tagen keine Zellen im Flugfenster. Vor Ort prüfen.",
        "w_overdev_spots": "Überentwicklung in den Spot-Analysen an {days} erwähnt — die Synoptik zeigt keine Zonen. Weiche Vorwarnung.",
        "trend_aufbauend": "aufbauend", "trend_fallend": "fallend", "trend_stabil": "stabil",
        "trend_abschwaechend": "abschwächend",
        # Druckzeile: 3-Tage-Steigung, Tagestendenz (bereinigt), 3-h-Sprung
        "pt_3d": "3 Tage:", "pt_day": "tagsüber {val} hPa", "pt_mixed": "tagsüber uneinheitlich",
        "pt_ns": " — Norden {a}, Süden {b}", "pt_one": " — nur {zone} {dir}",
        "pt_up": "steigend", "pt_down": "fallend",
        "pt_jump": "Sprung {val} hPa in 3 h, {von}–{bis} Uhr ({zone})",
        "w_generic":    "{label} an {days}.",
        "sev_stop":     "Schwerer Warnhinweis",
        "sev_warn":     "Warnhinweis",
        "alps_north":   "Alpennordseite",
        "alps_south":   "Alpensüdseite",
        "warnings_ch":  "Warnhinweise · Gesamtlage Schweiz",
        "hz_off":       "Nicht angezeigt",
        # schmale Kacheln (alle Warnhinweise immer in einer Zeile, auch Handy/Mail)
        "hzs_RAIN": "Regen", "hzs_THUNDER": "Gewitter", "hzs_FOEHN": "Föhn", "hzs_WIND": "Wind",
        "sevs_stop": "Schwer", "sevs_warn": "Hinweis",
        "src_line":     "Prognosedaten: {surface} (Boden), {pl} (Höhe) — MeteoSchweiz/DWD via Open-Meteo · Grosswetterlage: ECMWF IFS · Fronten: DWD",
        "hz_RAIN": "Regen", "hz_THUNDER": "Gewitter", "hz_FOEHN": "Föhn",
        "hz_WIND": "Starker Wind",
        "hz_none":      "Daten zeigen schweizweit keine Gefahr.",
        "lage_Westlage": "Westlage", "lage_Suedwestlage": "S\u00fcdwestlage",
        "lage_Nordwestlage": "Nordwestlage", "lage_Nordlage": "Nordlage",
        "lage_Nordostlage": "Nordostlage", "lage_Ostlage": "Ostlage",
        "lage_Suedostlage": "S\u00fcdostlage", "lage_Suedlage": "S\u00fcdlage",
        "wind_regional": "Regional bis {kmh} km/h ({region}), st\u00e4rkste Stunde {hour} Uhr",
        "ctr_Island": "Island",
        "ctr_Schottland": "Schottland",
        "ctr_Atlantik vor Irland": "Atlantik vor Irland",
        "ctr_England": "England",
        "ctr_Frankreich": "Frankreich",
        "ctr_Spanien": "Spanien",
        "ctr_Nordskandinavien": "Nordskandinavien",
        "ctr_Suedskandinavien": "Südskandinavien",
        "ctr_Mitteleuropa": "Mitteleuropa",
        "ctr_Norditalien": "Norditalien",
        "ctr_Westliches Mittelmeer": "Westliches Mittelmeer",
        "ctr_Adria": "Adria",
        "ctr_Osteuropa": "Osteuropa",
        "ctr_Schwarzes Meer": "Schwarzes Meer",
        "ctr_Azoren": "Azoren",
        "sum_none":     "Keine grösseren Wettergefahren.",
        "sum_one":      "{hz} erschwert das Fliegen.",
        "sum_many":     "{hz} erschweren das Fliegen.",
        "sum_RAIN": "Regen", "sum_THUNDER": "Gewitter", "sum_FOEHN": "Föhn",
        "sum_WIND": "starker Wind",
        "wind_meaning": "Mittelwert über alle Schweizer Spots, 12 Uhr",
        "wind_range":   "{lo}–{hi} km/h je Region",
        "wind_range_note": "Spanne der Regionsspitzen auf 700 hPa, am stärksten {region} {hour} Uhr",
        "wind_ground_range": "≈ {lo}–{hi} km/h am Boden zu erwarten (⅔-Regel)",
        "wind_fazit_match": "{Strength} {sector}strömung: so das Schweizer Mittel ({models}), und die Regionen bleiben in dieser Klasse — {lo} bis {hi} km/h, am stärksten {region} am {when}.",
        "wind_fazit_stronger": "{Strength} {sector}strömung: so das Schweizer Mittel ({models}) — regional ist es eine Klasse stärker, bis {hi} km/h {region} am {when}, also {cls}. Das Mittel verharmlost.",
        "wind_fazit_weaker": "{Strength} {sector}strömung: so das Schweizer Mittel ({models}) — selbst die stärkste Region bleibt darunter, höchstens {hi} km/h ({region}).",
        "wcls_schwach": "schwach", "wcls_maessig": "mässig", "wcls_kraeftig": "kräftig", "wcls_stuermisch": "stürmisch",
        "wstr_schwach": "schwache", "wstr_maessig": "mässige", "wstr_kraeftig": "kräftige", "wstr_stuermisch": "stürmische",
        "hour_morning": "Morgen", "hour_midday": "Mittag", "hour_afternoon": "Nachmittag", "hour_evening": "Abend",
        "chip_rain_widespread": "Flächiger Regen angezeigt",
        "chip_rain_scattered":  "Regen in Teilen der Region angezeigt",
        "chip_rain_isolated":   "Einzelne Schauer angezeigt",
        "chip_rain":            "Regen angezeigt",
        "chip_aloft_warn":  "Höhenwind über {kmh} km/h",
        "chip_aloft_stop":  "Starker Höhenwind über {kmh} km/h",
        "chip_ground_warn": "Bodenwind über {kmh} km/h",
        "chip_ground_stop": "Starker Bodenwind über {kmh} km/h",
        "chip_foehn_moderate": "Föhn angezeigt (mässig)",
        "chip_foehn_strong":   "Föhn angezeigt (stark)",
        "chip_thunder":        "Gewitter angezeigt",
        "chip_thunder_risk":   "Gewitterrisiko {pct} %",
        "chip_clouds":         "Wolken bis auf Starthöhe angezeigt",
        "lage_Hochdrucklage": "Hochdrucklage", "lage_Tiefdrucklage": "Tiefdrucklage",
        "lage_Nordfoehnlage": "Nordföhnlage", "lage_Suedfoehnlage": "Südföhnlage",
        "lage_Foehnlage (wechselnd)": "Föhnlage (wechselnd)",
        "lage_Bisenlage": "Bisenlage", "lage_Genua-Tief": "Genua-Tief",
        "lage_Uebergangslage": "Übergangslage", "lage_unbestimmt": "unbestimmt",
        "zb_alpennordhang_west": "Alpennordhang West",
        "zb_alpennordhang_ost":  "Alpennordhang Ost",
        "zones_all":    "landesweit",
        "zones_except": "überall ausser {zone}",
        "zone_in_alpennordhang": "am Alpennordhang",
        "zone_in_wallis": "im Wallis",
        "zone_in_tessin": "im Tessin",
        "zone_in_graubuenden_engadin": "in Graubünden",
        "airspace_note": "Luftraum (DABS), Startplatz und Windsack prüft der Pilot vor Ort — das kann keine Prognose.",
        "days_ahead":   "Die Tage voraus",
        "week_hint":    "Oben je Tag: Mittelwert deiner Regionen (1–5). Keine Warnhinweise nur, wenn keine deiner Regionen Warnhinweise hat; schwere Warnhinweise, sobald eine Region schwere hat; sonst Warnhinweise. Darunter jede Region mit ihrer eigenen Bewertung.",
        "regions_word": "Deine Regionen",
        "situation_ch":  "Gesamtlage Schweiz",
        "wl_rain": "Regen", "wl_dry": "trocken", "wl_high": "Hochdruck", "wl_low": "Tiefdruck",
        "wl_windy": "kräftiger Höhenwind", "wl_calm": "ruhig", "wl_foehn_n": "Nordföhn angezeigt", "wl_foehn_s": "Südföhn angezeigt",
    },
    "en": {
        "no_warning":   "no warning",
        "spots_word":   "spots",
        "regions_word": "regions",
        "ch_context":   "CH",
        "of":           "of",
        "step_lage":    "Situation",
        "step_front":   "Fronts",
        "step_foehn":   "Foehn",
        "step_wind":    "Upper wind",
        "step_stab":    "Stability",
        "step_thermik": "Thermals / cloud base",
        "step_sonne":   "Sun / cloud",
        "step_modelle": "Models",
        # status pill per chain step (short, max 3 words)
        "st_front_signs": "signs visible", "st_front_weaksigns": "weak signs", "st_front_nosigns": "no signs", "st_front_airmass": "air-mass change", "st_front_none": "no front indicated", "st_front_rear": "rear side",
        "st_foehn_on": "foehn indicated", "st_foehn_gusty": "isolated gusts", "st_foehn_off": "no foehn signs",
        "st_wind_stronger": "regionally stronger", "st_wind_match": "regionally as average", "st_wind_weaker": "regionally weaker",
        "st_stab_thunder": "thunderstorms indicated", "st_stab_labile": "instability indicated in parts", "st_stab_stable": "stable air indicated",
        "st_th_good": "good climbs", "st_th_mod": "moderate climbs", "st_th_weak": "weak climbs",
        "st_sun_match": "as expected", "st_sun_partial": "partly different", "st_sun_contra": "different than expected",
        "st_md_agree": "models agree", "st_md_partial": "mostly agree", "st_md_uncertain": "models disagree",
        "fx_dwd": "DWD", "fx_signature": "signs", "fx_sig_deutlich": "clear", "fx_sig_schwach": "weak", "fx_sig_no": "none",
        "fx_dp": "Pressure diff. Alps", "fx_gust": "gust", "fx_tal": "foehn valleys", "fx_tal_na": "n/a", "fx_t850": "T850", "fx_thunder_none": "no thunderstorms",
        "fx_ground": "ground ≈", "fx_peak": "peak",
        "md_head_0":     "Verdict: Good agreement between the models.",
        "md_head_1":     "Verdict: One open point.",
        "md_head_n":     "Verdict: {n} open points.",
        "md_warn":       "{what}: {zones} {window} the models see {spread}{nomaj}; {agreewin}.",
        "md_warn_allday": "{what}: {zones} the models see {spread} all day{nomaj}.",
        "md_spread":     "anything from {lo} to {hi}",
        "md_nomaj":      ", no majority",
        "md_info":       "{what} {window} is largely agreed, only {models} sees {more}.",
        "md_info_plain": "{what} {window} is only just agreed.",
        "md_least":      "{what} is the least certain ({pct} %), but the deviations stay local.",
        "md_more":       "more", "md_less": "less",
        "md_aw_morning":   "in the morning they agree",
        "md_aw_midday":    "around midday they agree",
        "md_aw_afternoon": "in the afternoon they agree",
        "md_aw_from_midday":  "from midday on they agree",
        "md_aw_until_midday": "until midday they agree",
        "md_aw_split":     "in the morning and in the afternoon they agree",
        "md_aw_none":      "they disagree all day",
        "md_grp":        "{label}: {models}",
        "md_line":       "{what} · {groups}",
        "md_win_morning": "in the morning", "md_win_midday": "around midday", "md_win_afternoon": "in the afternoon",
        "md_var_rain": "precipitation", "md_var_dir": "wind direction", "md_var_speed": "wind",
        "md_var_gust": "gusts", "md_var_cloud": "cloud", "md_var_cloud_low": "low cloud",
        "md_lab_rain_0": "dry", "md_lab_rain_1": "precipitation",
        "md_lab_gust_0": "under 15 km/h", "md_lab_gust_1": "15–25 km/h", "md_lab_gust_2": "25–40 km/h",
        "md_lab_gust_3": "40–60 km/h", "md_lab_gust_4": "60–80 km/h", "md_lab_gust_5": "over 80 km/h",
        "md_lab_speed_0": "under 10 km/h", "md_lab_speed_1": "10–20 km/h", "md_lab_speed_2": "20–30 km/h",
        "md_lab_speed_3": "30–45 km/h", "md_lab_speed_4": "45–60 km/h", "md_lab_speed_5": "60–80 km/h",
        "md_lab_speed_6": "over 80 km/h",
        "md_lab_cloud_0": "0–20 %", "md_lab_cloud_1": "20–40 %", "md_lab_cloud_2": "40–60 %",
        "md_lab_cloud_3": "60–80 %", "md_lab_cloud_4": "80–100 %",
        "md_lab_dir_0": "N", "md_lab_dir_1": "NE", "md_lab_dir_2": "E", "md_lab_dir_3": "SE",
        "md_lab_dir_4": "S", "md_lab_dir_5": "SW", "md_lab_dir_6": "W", "md_lab_dir_7": "NW",
        "md_word_rain_0": "dry", "md_word_rain_1": "precipitation",
        "md_word_gust_0": "calm", "md_word_gust_1": "flyable", "md_word_gust_2": "strong",
        "md_word_gust_3": "blown out", "md_word_gust_4": "storm", "md_word_gust_5": "severe storm",
        "md_word_speed_0": "calm", "md_word_speed_1": "light wind", "md_word_speed_2": "moderate wind",
        "md_word_speed_3": "fresh wind", "md_word_speed_4": "strong wind", "md_word_speed_5": "storm",
        "md_word_speed_6": "hurricane force",
        "md_word_cloud_0": "clear", "md_word_cloud_1": "broken cloud", "md_word_cloud_2": "half overcast",
        "md_word_cloud_3": "mostly cloudy", "md_word_cloud_4": "overcast",
        "md_word_dir_0": "north", "md_word_dir_1": "north-east", "md_word_dir_2": "east", "md_word_dir_3": "south-east",
        "md_word_dir_4": "south", "md_word_dir_5": "south-west", "md_word_dir_6": "west", "md_word_dir_7": "north-west",
        "su_exp_high":  "{Press}: plenty of sunshine expected",
        "su_exp_low":   "{Press}: a lot of cloud expected",
        "su_exp_flat":  "Transitional situation: changeable cloud expected",
        "su_air_south": ", but the humid {sector} air brings cloud to the south",
        "su_air_north": ", but the {sector} air brings cloud to the Northern Alps",
        "su_data":      " — {models} shows {zones}{best}.",
        "su_match":     ". {models} confirms the split: {zones}{best}.",
        "su_match_all": ". {models} confirms it nationwide: {zones}{best}.",
        "su_partial":   ". {models} only partly shows this: {zones}{best} — {miss}.",
        "su_contra":    ". {models} contradicts it: {zones}{best} — {miss}.",
        "su_miss_north_cloudy": "more cloud in the north than the situation suggests",
        "su_miss_north_sunny":  "the cloud on the Northern Alps fails to appear",
        "su_miss_south_cloudy": "more cloud in the south than the situation suggests",
        "su_miss_south_sunny":  "the humid air does not show in the south",
        "su_zone":      "{where} {word}{cloud}",
        "su_word_sunny": "mostly sunny", "su_word_mixed": "partly sunny", "su_word_overcast": "mostly overcast",
        "su_group":     "{zones} {word}{cloud}",
        "su_low":       " with low-level cloud (below 2 km)",
        "su_high":      " under mid- and high-level cloud (above 2 km)",
        "su_best":      "; sunniest in {zone}",
        "su_both":      "{word} nationwide",
        "su_north":     "in the north", "su_south": "in the south",
        "su_lbl_sun":   "Sun 10–16h", "su_lbl_low": "cloud below 2 km", "su_lbl_high": "cloud above 2 km",
        "th_exp_high":  "{Press}: subsidence and a capped cloud base expected",
        "th_exp_low":   "{Press}: high base but overdevelopment expected",
        "th_exp_flat":  "Transitional situation: no clear stratification expected",
        "th_press_hoch": "High pressure", "th_press_up": "Rising pressure",
        "th_press_tief": "Low pressure", "th_press_down": "Falling pressure",
        "th_t850_warm": ", the warm air aloft brakes the climb",
        "th_t850_cold": ", the cold air aloft favours strong climbs",
        "th_data":      " — {models} shows {base}, {climb}{start}{sun}.",
        "th_match":     ". {models} confirms the capped base: {base}, {climb}{start}{sun}.",
        "th_match_high": ". {models} confirms the high base: {base}, {climb}{start}{sun}.",
        "th_contra_higher": ". {models} does not show this: {base}, {climb}{start}{sun} — the cloud base is higher than the situation suggests.",
        "th_contra_lower":  ". {models} does not show this: {base}, {climb}{start}{sun} — the cloud base stays lower than the situation suggests.",
        "th_base_range": "cloud base lowest {lo_zone}, highest {hi_zone}",
        "th_base_one":  "cloud base similar everywhere",
        "th_lbl_base":  "Base", "th_lbl_climb": "Climb", "th_lbl_from": "from", "th_unit_h": "h",
        "th_base_none": "no base available",
        "th_climb":     "climbs {grade}",
        "th_grade_weak": "weak", "th_grade_mod": "moderate", "th_grade_good": "good", "th_grade_strong": "strong",
        "th_start":     ", thermals from {h}h",
        "th_sun_split": "; {sunny} sunny, {cloudy} overcast",
        "th_sun_all":   "; widely sunny",
        "th_cloud_all": "; widespread low cloud",
        "th_north":     "north", "th_south": "south",
        "ground_est":   "expected at ground level",
        "rule_23":      "⅔ rule",
        "front_none":   "Data show no front within the forecast window (DWD).",
        # verdict — forecast data, never a final statement
        # flow direction (upper-wind block, week tiles)
        "lg_sector_N":     "northerly", "lg_sector_NE": "north-easterly", "lg_sector_E": "easterly",
        "lg_sector_SE":    "south-easterly", "lg_sector_S": "southerly", "lg_sector_SW": "south-westerly",
        "lg_sector_W":     "westerly", "lg_sector_NW": "north-westerly",
        # situation like foehn (User 26.10.2026): same layout — pill "n of 4", four
        # chips (pressure first, met ones highlighted), "points to", "also show",
        # "Not in the data", "Against it"
        "li_k_drucklage":  "Pressure situation", "li_v_neither": "neither high nor low",
        "li_k_tend3":      "{subj} next 3 days", "li_k_tagesgang": "{subj} today 6–22h",
        "li_subj_none":    "Pressure",
        "li_w_aufbau":     "builds up", "li_w_abklingen": "weakens", "li_w_gleich": "about the same",
        "li_w_verst":      "strengthens", "li_w_abbau": "weakens",
        "li_w_steigt":     "rises", "li_w_faellt": "falls",
        "li_side_hoch":    "High pressure", "li_side_tief": "Low pressure",
        "li_k_p_hoch":     "Pressure ≥{thr} hPa", "li_k_p_tief": "Pressure ≤{thr} hPa",
        "li_k_trend":      "Trend 3 days",
        "li_v_trend":      "{v} hPa/day",
        "li_k_day":        "Pressure 06–22h",
        "li_v_mixed":      "mixed",
        "li_k_c_hoch":     "High ≤{km} km", "li_k_c_tief": "Low ≤{km} km",
        "li_v_none":       "none",
        # sentence 1: state and development of pressure over Switzerland (User 26.10.2026)
        # text (User 26.10.2026): what lies over Switzerland, how pressure develops over
        # the flying day, outlook over the three days — no "signs of it"
        "li_p_on":         "In {m}, Switzerland is under {side_l} ({hpa}).",
        "li_p_off":        "In {m}, Switzerland is under neither high nor low pressure ({hpa}).",
        "li_dday_verst":   " Over the day (06:00–22:00) {side_l} strengthens ({v} hPa).",
        "li_dday_abbau":   " Over the day (06:00–22:00) {side_l} weakens ({v} hPa).",
        "li_day_up":       " Over the day (06:00–22:00) pressure rises by {v} hPa.",
        "li_day_down":     " Over the day (06:00–22:00) pressure falls by {v} hPa.",
        "li_day_flat":     " Over the day (06:00–22:00) pressure stays about the same ({v} hPa).",
        "li_day_mixed":    " Over the day (06:00–22:00) pressure is mixed{wie}.",
        "li_day_ns":       ": north {a}, south {b}",
        "li_day_one":      ": {zone} {a}, other zones {b}",
        "li_jump":         " The strongest change is between {von}:00 and {bis}:00: {v} hPa in 3 hours ({zone}).",
        "li_dev":          " Over the three forecast days {was} ({v} hPa per day).",
        "li_was_hoch_up":  "high pressure builds up", "li_was_hoch_down": "high pressure weakens",
        "li_was_tief_down": "low pressure builds up", "li_was_tief_up": "low pressure weakens",
        "li_was_on_flat":  "{side_l} stays about the same",
        "li_was_off_up":   "pressure rises", "li_was_off_down": "pressure falls",
        "li_was_off_flat": "pressure stays about the same",
        "lg_rain_fading":  " and fading during the day",
        "lg_rain_south_growing": "mostly dry, showers on the south side of the Alps increasing in the afternoon",
        "lg_rain_for_now": "for now ",
        "lg_rain_growing": " and increasing in the afternoon",
        "lg_rain_dry":     "dry",
        "lg_rain_mostly_dry": "mostly dry",
        "lg_rain_south_only": "mostly dry, showers only on the south side of the Alps",
        "lg_rain_north_only": "mostly dry, rain only on the north side of the Alps",
        "lg_rain_partly":  "some rain",
        "lg_rain_wide":    "widespread rain",
        "lg_wind_calm":    "wind calm",
        "lg_wind_partly":  "partly windy",
        "lg_wind_wide":    "widely windy",
        "lg_wind_strong":  "widely strong wind",
        "lg_wind_aloft":   " from the upper wind",
        "lg_wind_less_south": ", less on the south side of the Alps",
        "lg_wind_less_north": ", less on the north side of the Alps",
        "from_morning":    "from the morning", "from_midday": "from midday",
        "from_afternoon":  "from the afternoon", "from_evening": "from the evening",
        "wc_windig":       "windy", "wc_verblasen": "blown out", "wc_ruhig": "calm",
        "wc_stark_eingeschraenkt": "severely restricted",
        # foehn: synoptic claim against the forecast data
        "fb_foehn_yes":     "Data indicate {Side} foehn: pressure difference of {dp} hPa across the Alps. {models} shows it too — gusts up to {gust} km/h at the lee forecast point {station}{windows}.",
        "fb_foehn_aloft":   "Data indicate {Side} foehn: pressure difference of {dp} hPa across the Alps, but at the lee forecast point {station} {models} shows hardly any gusts (up to {gust} km/h) — aloft the data can still point to foehn.",
        "fb_foehn_no":      "Data show no signs of foehn: the pressure difference across the Alps stays below the 4 hPa threshold at {dp} hPa.{strong}",
        "fb_foehn_no_nodp": "Data show no signs of foehn: no notable pressure difference across the Alps.{strong}",
        "fb_foehn_tal_yes": "Data indicate {Side} foehn: pressure difference of {dp} hPa across the Alps. {model} shows the foehn on the ground too in {taeler} — wind {w1}–{w2} km/h from the {dir}, gusts up to {g} km/h ({gtal}){when}.",
        "fb_foehn_tal_no":  "Signs of {side} foehn: pressure difference of {dp} hPa across the Alps. {tal_wind} Aloft the data can still point to foehn; launch sites at 1500–2000 m can be affected.",
        "fb_tal_weak": "In the {n} foehn valleys {model} shows wind up to {w} km/h, gusts up to {g} km/h ({gtal}) — the wind strength does not point to foehn on the valley floor.",
        "fb_tal_strong": "In the {n} foehn valleys {model} shows wind up to {w} km/h, gusts up to {g} km/h ({gtal}) — but the wind does not show the typical foehn pattern (direction, dry air).",
        "fb_tal_nonum": "The wind at the {n} foehn valley points ({model}) does not point to foehn on the valley floor.",
        "fb_foehn_tal_na":  " Confirmation by valley wind not verifiable (no valley-point data).",
        "fb_tal_more":      " and others",
        "fv_side_sued":     "North side valleys",
        "fv_side_nord":     "South side valleys",
        "fv_full":          "{side}: dry wind from the foehn direction in {n} of {t} valleys — {taeler}; gusts up to {g} km/h.",
        "fv_dirdry":        "{side}: dry wind from the foehn direction in {n} of {t} valleys — {taeler}; wind still weak, gusts up to {g} km/h.",
        "fv_none":          "{side}: no dry wind from the foehn direction in the {t} valleys, valley wind up to {w} km/h.",
        "fv_both_none":     "Valleys: no dry wind from the foehn direction in the {t} valleys, valley wind up to {w} km/h.",
        "fv_aloft":         "Aloft: gusts up to {g} km/h from the {dir} ({spot}, {alt} m).",
        "fv_none_short":    "{side}: no dry wind from the foehn direction in the {t} valleys, valley wind up to {w} km/h.",
        "fv_dp":            "Pressure difference across the Alps: {dp} hPa.",
        "fv_dp_high":       "Pressure difference across the Alps: {dp} hPa — at this level foehn is frequent in the large foehn valleys.",
        "fv_na":            "Foehn valleys: no valley data available.",
        "fvs_full":         "Dry wind from foehn direction: {n} of {t} valleys",
        "fvs_dirdry":       "Dry wind from foehn direction: {n} of {t} valleys",
        "fvs_aloft":        "Wind aloft {g} km/h",
        "fvs_dp":           "Pressure difference {dp} hPa",
        "fvs_none":         "Dry wind from foehn direction: 0 of {t} valleys",
        "fx_rh":            "Lowest valley humidity",
        "fx_gust_aloft":    "Gust aloft",
        "fv_side_na":       "{side}: no valley data — not verifiable.",
        "fv_name_dir":      "{tal} from {dir}",
        "fv_dir_N": "N", "fv_dir_NE": "NE", "fv_dir_E": "E", "fv_dir_SE": "SE",
        "fv_dir_S": "S", "fv_dir_SW": "SW", "fv_dir_W": "W", "fv_dir_NW": "NW",
        "fvr_quiet":   "Context: the foehn indicators in the valleys show no foehn signal. This is a model forecast: shallow foehn is often not captured by models, and in inner-Alpine valleys (Valais, Domleschg, Davos) foehn sets in even with a small pressure difference. On the day, check live readings at valley and summit stations.",
        "fvr_pool":    "Context: in data like these, foehn can blow above the calm valleys, over a cold-air pool. At launch height it can be strong while the valley is calm, and the foehn can break through to the ground.",
        "fvr_dirdry":  "Context: the air shows foehn characteristics, but the model wind is weak. Models usually show foehn wind too weak — foehn at the valley floor cannot be ruled out.",
        "fvr_full":    "Context: in these valleys the forecast shows dry wind from the foehn direction — the features MeteoSwiss uses to identify foehn at the valley floor. Models usually show foehn wind too weak, and neighbouring valleys can be hours apart.",
        "fvr_dp_high": "Context: with a pressure difference this large, foehn is frequent in the large foehn valleys, even while the valley data are still calm.",
        "fvr_guide":   "How to read foehn data",
        "fvr_legend":  "How valleys are counted: a valley counts when the forecast ({model}) shows wind from that valley's foehn direction for at least {h} hours between {h0}:00 and {h1}:00, with wind from {w} km/h or gusts from {g} km/h and humidity of at most {rh} %. The foehn direction of each valley comes from MeteoSwiss measurements ({m} of {n} valleys; the rest: half-circle).",
        "fi_pill":       "Foehn indicators: {n} of 4",
        "fi_k_dp":       "Pressure diff.",
        "fi_v_dp":       "{dp} hPa ({side} higher)",
        "fi_hi_sued":    "south", "fi_hi_nord": "north",
        "fi_k_map":      "Regions with {dirw} ≥{kmh} km/h",
        "fi_v_map":      "{n} of {t}",
        "fi_k_luv_sued": "South side aloft", "fi_k_luv_nord": "North side aloft",
        "fi_v_cooler":   "{k} °C cooler", "fi_v_warmer": "{k} °C warmer", "fi_v_equal": "equally warm",
        "fi_k_val":      "Valleys with dry {dirw} ≥{kmh} km/h",
        "fi_v_val":      "{n} of {t}",
        "fi_tal_multi":  "{n} of {t} foehn valleys show dry wind from the foehn direction, strongest {name} (gusts up to {g} km/h)",
        "fi_tal_one":    "{name} shows dry wind from the foehn direction (gusts up to {g} km/h)",
        "fi_map_on":     "{n} of {t} Alpine regions have strong {dirw}, mainly {names}",
        "fi_dp_on":      "pressure is {dp} hPa higher in the {side}",
        "fi_luv_on":     "{side} is {k} °C cooler aloft",
        "fi_x_tal":      "no foehn valley with dry wind from the foehn direction",
        "fi_x_map":      "strong {dirw} in {n} of {t} regions ({names})",
        "fi_x_map_none": "no Alpine region with strong wind from a foehn direction",
        "fi_x_dp":       "a pressure difference of {dp} hPa",
        "fi_x_luv":      "{side} {k} °C cooler aloft",
        "fi_x_luv_warm": "{side} {k} °C warmer aloft",
        "fi_x_luv_eq":   "equal temperatures aloft on both sides",
        "fi_dirw_sued":  "south wind", "fi_dirw_nord": "north wind",
        "fi_luv_sued":   "the south side", "fi_luv_nord": "the north side",
        "fi_all":        "All four indicators are met: ",
        "fi_none":       "None of the four indicators is met: ",
        "fi_rest_1":     "The fourth indicator is not met: ",
        "fi_rest_2":     "The other two indicators are not met: ",
        "fi_rest_3":     "The other three indicators are not met: ",
        "fi_and":        " and ",
        "fd_p_on":       "In {m}, the pressure difference points to {foehn}{ab}.",
        "fd_p_off":      "In {m}, the pressure difference does not point to foehn.",
        "fd_s_also":     " The data also show signs of it{ab}: {seq}.",
        "fd_s_still":    " Still, the data show signs of {foehn}{ab}: {seq}.",
        "fd_s_other":    " The data, however, show signs of {foehn}{ab}: {seq}.",
        "fd_s_none":     " The data show none of the other foehn signs either.",
        "fd_signs":      " {m} show{ab} signs of {foehn}: {seq}.",
        "fd_seq_later":  ",{ab} {item}",
        "fd_absent":     " Not in the data: {liste}.",
        "fd_i_map_wo":   " (mainly {names})",
        "fd_i_val_wo":   " (strongest {name})",
        "fd_i_val_1":    "dry wind from the foehn direction in {name}",
        "fd_against":    " Against it: {liste}.",
        "fd_ag_map":     "{dirw} in the regions",
        "fd_ag_tp":      "a warmer {luv} side aloft",
        "fd_ag_val":     "dry foehn wind in valleys on the other side",
        "fd_m_tp":       "a cooler {luv} side aloft",
        "fd_m_map":      "wind from the foehn direction in the regions", "fd_m_val": "dry wind from the foehn direction in the valleys",
        "fd_foehn_sued": "south foehn", "fd_foehn_nord": "north foehn",
        "fd_luv_sued":   "south", "fd_luv_nord": "north",
        "fd_r_inner":    " Inner-Alpine foehn often sets in without them.",
        "fd_r_weak":     " Models usually show foehn wind too weak.",
        "fd_r_none":     " Foehn is still possible: models often miss foehn that only spills shallowly over the passes or stays in single valleys. On the day, check live readings at valley and summit stations.",
        "fd_ab":         " from about {t}", "fd_ab_start": " already at {t}",
        "fd_model_x":    "the data",
        "fz_pill":        "Front signs: {n} of 4", "fz_pill_from": " · from ~{t}",
        "fz_k_dwd":       "DWD map", "fz_k_kaelter": "Colder at 1500 m", "fz_k_waermer": "Warmer at 1500 m",
        "fz_k_luft":      "Air mass change at 1500 m", "fz_k_dreh": "Wind shift aloft",
        "fz_k_regen":     "Rain", "fz_k_dauerregen": "Continuous rain", "fz_k_wolken": "Cloud thickening",
        "fz_typ_kalt":    "cold front", "fz_typ_warm": "warm front", "fz_typ_okklusion": "occlusion",
        "fz_dwd_yes":     "DWD forecast map: {typ}.",
        "fz_dwd_no":      "DWD forecast map: no front forecast.",
        "fz_pill_none":   "DWD map: no front",
        "fz_match":       " {models} show signs from about {t}{move}: {det}.",
        "fz_nomatch":     " {models} show none of the matching signs.",
        "fz_absent":      " Not in the data: {liste}.",
        "fz_carried":     " Carried over from the day before: {liste}.",
        "fz_x_kaelter":   "colder air at 1500 m", "fz_x_waermer": "warmer air at 1500 m",
        "fz_x_luft":      "an air mass change at 1500 m", "fz_x_dreh": "a wind shift aloft",
        "fz_x_regen":     "rain", "fz_x_dauerregen": "continuous rain", "fz_x_wolken": "cloud thickening",
        "fz_dp_0": "overnight", "fz_dp_1": "in the early morning", "fz_dp_2": "in the morning",
        "fz_dp_3": "around midday", "fz_dp_4": "in the afternoon", "fz_dp_5": "in the evening", "fz_dp_6": "at night",
        "fz_move":        ", spreading from {a} to {b}",
        "fz_dir_N": "north", "fz_dir_S": "south", "fz_dir_W": "west", "fz_dir_E": "east",
        "fz_carried_v":   " (day before)", "fz_time": "{h}:00",
        "fi_close_none":  "Model forecast — shallow foehn is often missed.",
        "fi_close_inner": "Inner-Alpine foehn often sets in without the other signs.",
        "fi_close_weak":  "Models usually show foehn wind in the valleys too weak.",
        "fi_guide":      "How we count",
        "fb_dir_sued":      "south", "fb_dir_nord": "north",
        "fb_strong_none":   " {models} also shows no gusts from {g} km/h at the launch sites.",
        "fb_strong_some":   " {models} nevertheless shows strong winds at individual launch sites: gusts up to {gust} km/h from the {dir} ({spot}, {alt} m, {when}){cmp} — the data show upper wind, without signs of foehn.",
        "fb_models":        "; the models disagree, CH2 sees only {ch2} km/h",
        "fb_station_nord":  "Zurich", "fb_station_sued": "Lugano",
        "fb_side_nord":     "North", "fb_side_sued": "South",
        "fb_win_from":      ", from the {when}",
        # stability: expectation from the synoptic picture against CAPE / thunderstorms / overdevelopment
        "lb_expect":        "{air}{press}",
        "lb_air_humid":     "Humid {sector} air: instability expected",
        "lb_air_cool":      "Cool {sector} air: showers and instability on the north side expected",
        "lb_air_neutral":   "{Sector} flow: no distinctly unstable air",
        "lb_press_cap":     ", but the {regime} caps it",
        "lb_press_up":      ", but rising pressure increasingly caps it",
        "lb_press_low":     ", and low pressure favours it",
        "lb_press_none":    "",
        "lb_regime_hoch":   "high pressure",
        "lb_data":          " — {models} shows {what}.",
        "lb_match":         ". {models} confirms instability: {what}.",
        "lb_match_stable":  ". {models} confirms the stable stratification: {what}.",
        "lb_partial":       ". {models} only partly shows this: {what} — the cap does not hold on the Northern Alps.",
        "lb_contra_stable": ". {models} does not show this: {what} — the air is more stable than the situation suggests.",
        "lb_contra_labile": ". {models} contradicts it: {what} — more unstable than the situation suggests.",
        "lb_stable":        "stable air everywhere, no thunderstorms",
        "lb_labile_only":   "only {zones}, no thunderstorms{overdev}{north}",
        "lb_labile_wide":   "{zones}, no thunderstorms{overdev}",
        "lb_thunder":       "thunderstorms {zones}{overdev}{north}",
        "lb_thunder_at":    "{zone} from {hour}h",
        "lb_overdev":       ", overdevelopment {zones}",
        "lb_od_in":         ", overdevelopment from {hour}h",
        "lb_zone_grade":    "{zone} ({grade}{od})",
        "lb_od_zone":       "overdevelopment {zone} from {hour}h",
        "lb_north_capped":  "; on the Northern Alps the air stays capped",
        "lb_grade_light":   "slightly unstable", "lb_grade_mod": "unstable", "lb_grade_strong": "strongly unstable",
        "lb_in":            "in ", "lb_in_plural": "in ",
        "front_today_in":     "{Day}: the {typ} is expected to {art_inf} {zone} {when}{unsicher}{prov}.",
        "front_fazit_none_more": "After that, data indicate no further front within the 3-day window.",
        "front_z_deutlich":   "{Day}: the DWD forecast indicates a {typ} over {zone} {when}. {models} shows clear signs of it: {zeichen}.",
        "front_z_schwach":    "{Day}: the DWD forecast indicates a {typ} over {zone} {when}. {models} shows only weak signs of it: {zeichen}.",
        "front_z_keine":      "{Day}: the DWD forecast indicates a {typ} over {zone} {when}. {models} shows no signs of it.",
        "front_z_ohne_dwd":   "{Day}: the DWD forecast indicates no front over Switzerland. {models} nevertheless shows clear signs of an air-mass change over {zone}: {zeichen}.",
        "ez_druck_deutlich":  "a strong pressure rise ({val} hPa in 12 h)",
        "ez_druck_schwach":   "a pressure rise ({val} hPa in 12 h)",
        "ez_druckfall_deutlich": "a strong pressure fall ({val} hPa in 12 h)",
        "ez_druckfall_schwach": "a pressure fall ({val} hPa in 12 h)",
        "front_z_gegen":      " Instead: {gegen}.",
        "ez_kalt_deutlich":   "markedly colder air at 1500 m ({val} °C vs. the day before)",
        "ez_kalt_schwach":    "slightly colder air at 1500 m ({val} °C vs. the day before)",
        "ez_warm_deutlich":   "markedly warmer air at 1500 m ({val} °C vs. the day before)",
        "ez_warm_schwach":    "slightly warmer air at 1500 m ({val} °C vs. the day before)",
        "ez_regen_deutlich":  "rain ({val} mm)",
        "ez_regen_schwach":   "some rain ({val} mm)",
        "ez_drehung":         "upper wind veering to the {sector}",
        "front_generic":      "front",
        "sectors":            "north,north-east,east,south-east,south,south-west,west,north-west",
        "front_prev_run":     " (yesterday's run; this morning {dist} km to the {dir})",
        "front_fazit_in_more": "Forecast data suggest a further {typ} {art} {zone} {day} {when}{unsicher}.",
        "front_today_none":   "{Day}: data indicate no front.",
        "front_passed":       "{When}: the {typ} passed over {zone} (DWD analysis) — {day} on its rear side.",
        "yesterday":          "yesterday",
        "front_fazit_in":     "Forecast data suggest the {typ} {art} {zone} {day} {when}{unsicher}.",
        "front_fazit_later":  "Forecast data suggest the {typ} reaches Switzerland {day} at the earliest — beyond the 3-day window.",
        "front_fazit_stays":  "Forecast data suggest the {typ} ({dist} km to the {dir}) stays clear of Switzerland within the 3-day window.",
        "front_fazit_none":   "Forecast data suggest no front reaches Switzerland within the 3-day window.",
        "front_unsicher":     " — uncertain, edge contact only",
        "front_far":    "{typ} {dist} km to the {dir} — out of reach today.",
        "front_near":   "{typ} {dist} km to the {dir}.",
        "front_pass":   "{typ} {art} {zone} {when}.",
        "kalt":         "Cold front",
        "warm":         "Warm front",
        "okklusion":    "Occlusion",
        "quert":        "crosses",
        "streift":      "brushes",
        "morning":      "in the morning",
        "midday":       "around midday",
        "afternoon":    "during the afternoon",
        "evening":      "in the evening",
        "night":        "overnight",
        "showers_from": "showers from {h}h",
        "showers_onset": "shower onset",
        "simultaneous": "everywhere at once",
        "foehn_none":   "Data show no signs of foehn.",
        "foehn_line":   "Data indicate {side} foehn ({level}), {h} h.",
        "north":        "North",
        "south":        "South",
        "level_caution": "moderate",
        "level_danger": "strong",
        "thunder_window": "in the flying window 10–18h",
        "thunder_caveat": "High false-alarm rate — verify on site.",
        "no_convection": "no thunderstorms, no overdevelopment",
        "climb":        "climb",
        "height":       "working height",
        "hours":        "productive hours",
        "spots_link":   "View spots",
        "map_title":    "Synoptics",
        "map_caption":  "Surface pressure {model} · {ts} · fronts: DWD {kind} {valid}",
        "map_analysis": "surface analysis",
        "map_forecast": "forecast +{h} h",
        "legend_cold":  "cold front",
        "legend_warm":  "warm front",
        "legend_occl":  "occlusion",
        "legend_flow":  "upper flow 700 hPa",
        "w_foehn":      "Data indicate {side} foehn ({level}) on {days} ({h}).",
        "w_storm":      "Upper wind up to {kmh} km/h ({days}) — expect ≈ {ground} km/h at ground level.",
        "w_thunder":    "Data indicate thunderstorm cells in the flying window: {zones} ({days}). High false-alarm rate at a 5 % base rate — verify on site.",
        "w_overdev":    "Data indicate possible overdevelopment: {zones} ({days}). Soft early warning, not an alarm.",
        "w_shear":      "Data indicate wind shear on {days} — thermals likely torn apart, see regions.",
        "w_gusts":      "Gust warnings from the spot analyses on {days} — the upper wind itself stays light ({kmh} km/h at 700 hPa). See regions.",
        "w_thunder_spots": "Thunderstorm hints in the spot analyses on {days} — the synoptics show no cells in the flying window on those days. Verify on site.",
        "w_overdev_spots": "Overdevelopment mentioned in the spot analyses on {days} — the synoptics show no zones. Soft early warning.",
        "trend_aufbauend": "building", "trend_fallend": "falling", "trend_stabil": "steady",
        "trend_abschwaechend": "weakening",
        "pt_3d": "3 days:", "pt_day": "daytime {val} hPa", "pt_mixed": "daytime mixed",
        "pt_ns": " — north {a}, south {b}", "pt_one": " — only {zone} {dir}",
        "pt_up": "rising", "pt_down": "falling",
        "pt_jump": "jump of {val} hPa in 3 h, {von}–{bis} h ({zone})",
        "w_generic":    "{label} on {days}.",
        "sev_stop":     "Severe alert",
        "sev_warn":     "Alert",
        "alps_north":   "northern Alps",
        "alps_south":   "southern Alps",
        "warnings_ch":  "Alerts · Switzerland overall",
        "hz_off":       "Not indicated",
        # narrow tiles (all alerts always in one row, also on phones/in the mail)
        "hzs_RAIN": "Rain", "hzs_THUNDER": "Thunder", "hzs_FOEHN": "Foehn", "hzs_WIND": "Wind",
        "sevs_stop": "Severe", "sevs_warn": "Alert",
        "src_line":     "Forecast data: {surface} (surface), {pl} (upper levels) — MeteoSwiss/DWD via Open-Meteo · Synoptic pattern: ECMWF IFS · Fronts: DWD",
        "hz_RAIN": "Rain", "hz_THUNDER": "Thunderstorms", "hz_FOEHN": "Foehn",
        "hz_WIND": "Strong wind",
        "hz_none":      "Data show no hazards across Switzerland.",
        "lage_Westlage": "Westerly flow", "lage_Suedwestlage": "South-westerly flow",
        "lage_Nordwestlage": "North-westerly flow", "lage_Nordlage": "Northerly flow",
        "lage_Nordostlage": "North-easterly flow", "lage_Ostlage": "Easterly flow",
        "lage_Suedostlage": "South-easterly flow", "lage_Suedlage": "Southerly flow",
        "wind_regional": "Regionally up to {kmh} km/h ({region}), strongest hour {hour}:00",
        "ctr_Island": "Iceland",
        "ctr_Schottland": "Scotland",
        "ctr_Atlantik vor Irland": "Atlantic off Ireland",
        "ctr_England": "England",
        "ctr_Frankreich": "France",
        "ctr_Spanien": "Spain",
        "ctr_Nordskandinavien": "northern Scandinavia",
        "ctr_Suedskandinavien": "southern Scandinavia",
        "ctr_Mitteleuropa": "Central Europe",
        "ctr_Norditalien": "northern Italy",
        "ctr_Westliches Mittelmeer": "western Mediterranean",
        "ctr_Adria": "Adriatic",
        "ctr_Osteuropa": "Eastern Europe",
        "ctr_Schwarzes Meer": "Black Sea",
        "ctr_Azoren": "Azores",
        "sum_none":     "No major weather hazards.",
        "sum_one":      "{hz} makes flying difficult.",
        "sum_many":     "{hz} make flying difficult.",
        "sum_RAIN": "rain", "sum_THUNDER": "thunderstorms", "sum_FOEHN": "foehn",
        "sum_WIND": "strong wind",
        "wind_meaning": "Average across all Swiss spots, 12:00",
        "wind_range":   "{lo}–{hi} km/h across regions",
        "wind_range_note": "range of regional peaks at 700 hPa, strongest {region} {hour}h",
        "wind_ground_range": "≈ {lo}–{hi} km/h expected at ground level (⅔ rule)",
        "wind_fazit_match": "{Strength} {sector} flow: that is the Swiss average ({models}), and the regions stay in that class — {lo} to {hi} km/h, strongest {region} in the {when}.",
        "wind_fazit_stronger": "{Strength} {sector} flow: that is the Swiss average ({models}) — regionally it is one class stronger, up to {hi} km/h {region} in the {when}, i.e. {cls}. The average understates it.",
        "wind_fazit_weaker": "{Strength} {sector} flow: that is the Swiss average ({models}) — even the strongest region stays below that, at most {hi} km/h ({region}).",
        "wcls_schwach": "light", "wcls_maessig": "moderate", "wcls_kraeftig": "strong", "wcls_stuermisch": "stormy",
        "wstr_schwach": "light", "wstr_maessig": "moderate", "wstr_kraeftig": "strong", "wstr_stuermisch": "stormy",
        "hour_morning": "morning", "hour_midday": "midday", "hour_afternoon": "afternoon", "hour_evening": "evening",
        "chip_rain_widespread": "Widespread rain indicated",
        "chip_rain_scattered":  "Rain indicated in parts of the region",
        "chip_rain_isolated":   "Isolated showers indicated",
        "chip_rain":            "Rain indicated",
        "chip_aloft_warn":  "Upper wind above {kmh} km/h",
        "chip_aloft_stop":  "Strong upper wind above {kmh} km/h",
        "chip_ground_warn": "Ground wind above {kmh} km/h",
        "chip_ground_stop": "Strong ground wind above {kmh} km/h",
        "chip_foehn_moderate": "Foehn indicated (moderate)",
        "chip_foehn_strong":   "Foehn indicated (strong)",
        "chip_thunder":        "Thunderstorms indicated",
        "chip_thunder_risk":   "Thunderstorm risk {pct}%",
        "chip_clouds":         "Cloud down to launch height indicated",
        "lage_Hochdrucklage": "High pressure", "lage_Tiefdrucklage": "Low pressure",
        "lage_Nordfoehnlage": "North foehn", "lage_Suedfoehnlage": "South foehn",
        "lage_Foehnlage (wechselnd)": "Foehn (changing side)",
        "lage_Bisenlage": "Bise", "lage_Genua-Tief": "Genoa low",
        "lage_Uebergangslage": "Transitional", "lage_unbestimmt": "undetermined",
        "zb_alpennordhang_west": "northern Alps west",
        "zb_alpennordhang_ost":  "northern Alps east",
        "zones_all":    "countrywide",
        "zones_except": "everywhere except {zone}",
        "zone_in_alpennordhang": "in the northern Alps",
        "zone_in_wallis": "in Valais",
        "zone_in_tessin": "in Ticino",
        "zone_in_graubuenden_engadin": "in the Grisons",
        "airspace_note": "Airspace (DABS), launch site and windsock are checked by the pilot on site — no forecast can do that.",
        "days_ahead":   "The days ahead",
        "week_hint":    "Top of each day: average of your regions (1–5). No alerts only when none of your regions has any; severe alerts as soon as one region has severe ones; otherwise alerts. Below, each region with its own rating.",
        "regions_word": "Your regions",
        "situation_ch":  "Overall situation Switzerland",
        "wl_rain": "rain", "wl_dry": "dry", "wl_high": "high pressure", "wl_low": "low pressure",
        "wl_windy": "strong upper wind", "wl_calm": "calm", "wl_foehn_n": "north foehn indicated", "wl_foehn_s": "south foehn indicated",
    },
}


def _lbl(key: str) -> str:
    lang = _lang()
    # .get() statt "or": ein absichtlich leeres Label (z.B. lb_press_none)
    # ist falsy und wuerde sonst als Schluessel im Text landen.
    val = _L3[lang].get(key)
    if val is None:
        val = _L2[lang].get(key)
    return key if val is None else val


def _labels() -> dict:
    lang = _lang()
    return {**_L2[lang], **_L3[lang]}


# ----------------------------------------------------------------------
# Gruppen: Rating 4-5 / 1-3 x Status der App (User 14.09.: kein eigenes
# Wording, kein neues Rating — nur Rating 1-5 und Sicher/Vorsicht/Nicht sicher)
# ----------------------------------------------------------------------
HIGH_RATING = 4

_CLASS_ORDER = ("hi_safe", "hi_cond", "lo_safe", "lo_cond", "not_safe", "no_data")
# Klasse -> (Rating-Spanne, Status-Key der App in i18n "tier.*")
_CLASS_META = {
    "hi_safe":  ("4–5", "green"),
    "hi_cond":  ("4–5", "conditional"),
    "lo_safe":  ("1–3", "green"),
    "lo_cond":  ("1–3", "conditional"),
    "not_safe": ("", "not_safe"),
    "no_data":  ("", "unknown"),
}
_STATUS_COLOR = {"green": "#15803d", "conditional": "#b45309",
                 "not_safe": "#b91c1c", "unknown": "#64748b"}
_CLASS_TINT = {
    "hi_safe":  _rating_tint("green", 4),
    "hi_cond":  _rating_tint("amber", 4),
    "lo_safe":  _rating_tint("green", 2),
    "lo_cond":  _rating_tint("amber", 2),
    "not_safe": _rating_tint("red", 0),
    "no_data":  _TINT_NO_DATA,
}


def _classify(band: str, rating: int) -> str:
    if band == "red":
        return "not_safe"
    if band not in ("green", "amber") or rating <= 0:
        return "no_data"
    hi = rating >= HIGH_RATING
    if band == "green":
        return "hi_safe" if hi else "lo_safe"
    return "hi_cond" if hi else "lo_cond"


def _status_key(band: str) -> str:
    return {"green": "green", "amber": "conditional", "red": "not_safe"}.get(band, "unknown")


def _status(tier_key: str) -> str:
    """Status-Wort genau wie in der App (i18n tier.*)."""
    return i18n.t(f"tier.{tier_key}")


def _class_label(cls: str) -> str:
    rng, tier_key = _CLASS_META[cls]
    return f"{rng} · {_status(tier_key)}" if rng else _status(tier_key)


def _spot_class(spot: dict) -> str:
    return _classify(spot.get("safety_band") or "no_data", _rating_for_spot(spot))


def _region_class(entry: dict) -> str:
    return _classify(entry.get("safety_band") or "no_data",
                     int(entry.get("experience_rating") or 0))


def _counts(items, classifier) -> dict:
    c = {k: 0 for k in _CLASS_ORDER}
    for it in items:
        c[classifier(it)] += 1
    c["total"] = sum(c[k] for k in _CLASS_ORDER)
    c["segments"] = [
        {"cls": k, "n": c[k], "pct": (100.0 * c[k] / c["total"]) if c["total"] else 0.0,
         "fill": _CLASS_TINT[k]["fill"], "label": _class_label(k)}
        for k in _CLASS_ORDER if c[k]
    ]
    return c


def _counts_text(c: dict) -> str:
    parts = [f"{c[k]} {_class_label(k)}" for k in _CLASS_ORDER if c.get(k)]
    return " · ".join(parts)


def _abbr(name: str) -> str:
    words = [w for w in re.split(r"[\s/\-–]+", name) if w and w[0].isalpha()]
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(w[0] for w in words[:3]).upper()


# ----------------------------------------------------------------------
# Regionen
# ----------------------------------------------------------------------

def _spots_of_region(day: dict, rid: str) -> list:
    return [s for s in (day.get("top_spots") or []) if s.get("region_id") == rid]


def _region_thermals(spots: list) -> dict:
    climbs, heights, hours = [], [], []
    for s in spots:
        ri = ((s.get("analysis_full") or {}).get("_rating_inputs")) or {}
        if isinstance(ri.get("sustained_peak_mps"), (int, float)):
            climbs.append(float(ri["sustained_peak_mps"]))
        if isinstance(ri.get("working_height_agl_m"), (int, float)):
            heights.append(float(ri["working_height_agl_m"]))
        if isinstance(ri.get("productive_thermal_h"), (int, float)):
            hours.append(float(ri["productive_thermal_h"]))

    def q75(v):
        if not v:
            return None
        v = sorted(v)
        return v[min(len(v) - 1, int(round(0.75 * (len(v) - 1))))]

    return {
        "climb": f"{statistics.median(climbs):.1f} m/s" if climbs else "",
        # P75 — laut Topout-Stichprobe nahezu bias-frei, Median unterschaetzt
        "height": f"{round(q75(heights) / 50) * 50:.0f} m" if heights else "",
        "hours": f"{statistics.median(hours):.0f} h" if hours else "",
    }


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


# Chip-Werte, wie das Backend sie schreibt (engine/decision_engine.py
# build_region_topic_tags, via i18n "tag.val.*") — beide Sprachen, weil der
# Cache in der Sprache des Analyse-Laufs vorliegt.
_RAIN_CLASS = {"widespread": "widespread", "flaechig": "widespread",
               "scattered": "scattered", "verstreut": "scattered",
               "isolated": "isolated", "vereinzelt": "isolated"}


def _chip_text(tag: dict) -> str:
    """Warn-Chip in Klartext. "Clouds Base 1400m ≤ region ref 1500m" versteht
    kein Pilot; "Wolken bis auf Starthoehe" sofort. Unbekanntes Thema: wie
    bisher Label + Wert."""
    topic, sev = tag.get("topic", ""), tag.get("severity", "")
    value = str(tag.get("value", "") or "")
    if topic == "RAIN":
        cls = _RAIN_CLASS.get(value.strip().lower())
        return _lbl("chip_rain_" + cls) if cls else _lbl("chip_rain")
    if topic in ("WIND_ALOFT", "WIND_GROUND"):
        kmh = config.WIND_DANGER_KMH if sev == "stop" else config.WIND_WARN_KMH
        kind = "aloft" if topic == "WIND_ALOFT" else "ground"
        return _lbl(f"chip_{kind}_{'stop' if sev == 'stop' else 'warn'}").format(kmh=kmh)
    if topic == "FOEHN":
        return _lbl("chip_foehn_strong" if sev == "stop" else "chip_foehn_moderate")
    if topic == "THUNDERSTORM":
        m = re.search(r"(\d+)\s*%", value)
        return (_lbl("chip_thunder_risk").format(pct=m.group(1)) if m
                else _lbl("chip_thunder"))
    if topic == "CLOUDS":
        return _lbl("chip_clouds")
    return f"{tag.get('label', '')} {value}".strip()


def _region_cards(day: dict, day_idx: int, subscriber_regions: list, base: str) -> list:
    by_id = {r.get("region_id"): r for r in (day.get("top_regions") or [])}
    cards = []
    for rid in subscriber_regions:
        r = by_id.get(rid)
        spots = _spots_of_region(day, rid)
        if not r and not spots:
            continue
        r = r or {}
        band = r.get("safety_band") or "no_data"
        rating = int(r.get("experience_rating") or 0)
        tint = _rating_tint(band, rating)
        counts = _counts(spots, _spot_class)
        window = _clean_window(r.get("best_window", ""))
        rec = (r.get("recommendation") or "").strip()
        # Warn-Labels der App: nur stop/warn — diese Stufen setzt allein das
        # Backend (engine/decision_engine.py build_region_topic_tags). stop zuerst.
        tags = sorted(
            ({"topic": tg.get("topic", ""), "severity": tg.get("severity"),
              "label": tg.get("label", ""), "value": tg.get("value", ""),
              "time": tg.get("time", ""), "text": _chip_text(tg)}
             for tg in (r.get("tags") or []) if tg.get("severity") in ("stop", "warn")),
            key=lambda t: t["severity"] != "stop")
        cards.append({
            "region_id": rid,
            "region_name": r.get("region_name") or (spots[0].get("region_name") if spots else rid),
            "band": band, "rating": rating,
            "rating_display": str(rating) if rating > 0 else "",
            "cls": _region_class(r) if r else "no_data",
            "status": _status(_status_key(band)),
            "fill": tint["fill"], "border": tint["border"], "text": tint["text"],
            "window": window, "has_window": bool(window),
            "counts": counts, "counts_text": _counts_text(counts),
            "thermals": _region_thermals(spots),
            "recommendation": rec, "has_recommendation": bool(rec),
            # ein knapper Satz je Region — "Our assessment:"-Praefix weg, erster Satz
            "short": _capitalize(_first_sentences(
                re.sub(r"^(Our assessment|Unsere Einschätzung):\s*", "", rec), 150)),
            "tags": tags,
            "url": f"{base}/briefing?regions={rid}&day={day_idx}",
        })
    # Nicht sicher / ohne Bewertung ans Ende, sonst Rating absteigend, bei
    # gleichem Rating Sicher vor Vorsicht
    cards.sort(key=lambda c: (c["band"] == "red", c["cls"] == "no_data", -c["rating"],
                              c["band"] != "green", c["region_name"]))
    return cards


def _hero(cards: list) -> dict | None:
    """Staerkste Abo-Region — auch an einem mauen Tag: dann traegt sie eben
    ihre Zaehlung ohne Top-Spots. Nur ganz ohne Bewertung gibt es keinen Hero."""
    if not cards:
        return None
    best = cards[0]
    if best["cls"] == "no_data" and best["counts"]["total"] == 0:
        return None
    return best


def _headline(hero: dict | None, focus_label: dict) -> str:
    """Kopfzeile ohne Spot-Namen: Region + Rating + Status der App."""
    if not hero:
        return _tier_label("unknown")
    rating = f"{hero['rating']}/5" if hero["rating"] else ""
    return f"{hero['region_name']} {rating} — {hero['status']}".replace("  ", " ")


# ----------------------------------------------------------------------
# Woche
# ----------------------------------------------------------------------

def _region_split(day: dict, region_ids) -> dict:
    by_id = {r.get("region_id"): r for r in (day.get("top_regions") or [])}
    entries = [by_id.get(rid) or {} for rid in region_ids]
    return _counts(entries, _region_class)


def _day_summaries(wetterlage: dict, dates: list) -> dict:
    """Ein Satz je Tag, der die Gefahren schweizweit zusammenfasst.

    Bewusst KEIN Urteil ("kein nutzbares Fenster", "Top-Tag") — ob geflogen
    wird, entscheidet der Pilot. Frueher stand hier der flight_hint der Zone
    Alpennordhang, der als Urteil fuer die ganze Schweiz gelesen wurde
    (16.09.2026: "No usable window" neben einer Region mit Fenster 13-15 Uhr).
    Quelle sind die Gefahren-Schalter des Codes, dieselben wie in den Warnungen.
    """
    from engine.synoptic_llm import HAZARD_TOPICS
    out = {}
    for date in dates:
        day = _hazard_day(wetterlage, date) if wetterlage else None
        if not day:
            continue
        # Dieselben Datenworte wie Block 1 (Lage): "Meist trocken, Schauer nur im
        # Sueden, verbreitet windig …" — national und ohne Urteil. Das fruehere
        # "Regen und starker Wind erschweren das Fliegen" stand unter Regionen,
        # fuer die es nicht galt (Freitag 18.09.2026: Nordseite trocken).
        words = _lage_data_words(wetterlage, date)
        if words:
            out[date] = words
            continue
        active = [t for t in HAZARD_TOPICS if (day["checks"].get(t) or {}).get("active")]
        if not active:
            out[date] = _lbl("sum_none")
            continue
        names = [_lbl("sum_" + t) for t in active]
        # "Gewitter"/"thunderstorms" sind Plural — auch allein
        plural = len(active) > 1 or active == ["THUNDER"]
        out[date] = _capitalize(_lbl("sum_many" if plural else "sum_one")
                                .format(hz=_join_days(names)))
    return out


def _notable(strip_entry: dict, wetterlage: dict, date: str) -> str:
    """Das eine Auffaellige je Tag: Foehn vor Schauerbeginn vor nichts."""
    if strip_entry.get("flags"):
        return " · ".join(strip_entry["flags"])
    zb = _per_day_index(wetterlage.get("zugbahn"), [date]).get(date) or {}
    hours = [v for v in (zb.get("onset_hour_by_group") or {}).values()
             if isinstance(v, (int, float))]
    if hours:
        return _lbl("showers_from").format(h=f"{int(min(hours)):02d}")
    return ""


# ----------------------------------------------------------------------
# Kette fuer den Fokus-Tag
# ----------------------------------------------------------------------

_ZONE_LABELS = getattr(config, "SYNOPTIC_ZONE_LABELS", {})


def _zone_name(zone_id: str) -> str:
    lab = _ZONE_LABELS.get(zone_id) or {}
    return lab.get(_lang()) or lab.get("de") or zone_id


def _when(utc_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00")).astimezone(_TZ)
    except (TypeError, ValueError):
        return ""
    h = dt.hour
    if 5 <= h < 10:
        return _lbl("morning")
    if 10 <= h < 14:
        return _lbl("midday")
    if 14 <= h < 18:
        return _lbl("afternoon")
    if 18 <= h < 22:
        return _lbl("evening")
    return _lbl("night")


def _front_type(typ: str) -> str:
    return _lbl(typ) if typ in ("kalt", "warm", "okklusion") else (typ or "Front").title()


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    p = math.pi / 180
    a = (0.5 - math.cos((lat2 - lat1) * p) / 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2)
    return 12742 * math.asin(math.sqrt(a))


def _bearing_word(lat, lon, ref=(46.8, 8.2)) -> str:
    dlat, dlon = lat - ref[0], (lon - ref[1]) * math.cos(ref[0] * math.pi / 180)
    ang = (math.degrees(math.atan2(dlon, dlat)) + 360) % 360
    names_de = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    words = {"de": {"N": "nördlich", "NE": "nordöstlich", "E": "östlich", "SE": "südöstlich",
                    "S": "südlich", "SW": "südwestlich", "W": "westlich", "NW": "nordwestlich"},
             "en": {"N": "north", "NE": "north-east", "E": "east", "SE": "south-east",
                    "S": "south", "SW": "south-west", "W": "west", "NW": "north-west"}}
    return words[_lang()][names_de[int((ang + 22.5) % 360 // 45)]]


def _front_lines(fronts: dict | None, passagen: dict | None, date: str) -> list:
    lines = []
    # 1) DWD-Durchgangsaussagen je Zone fuer den Fokus-Tag
    for a in (passagen or {}).get("aussagen") or []:
        med = a.get("durchgang_median_utc") or ""
        try:
            local_day = datetime.fromisoformat(med.replace("Z", "+00:00")).astimezone(_TZ).date().isoformat()
        except (TypeError, ValueError):
            continue
        if local_day != date:
            continue
        lines.append(_lbl("front_pass").format(
            typ=_front_type(a.get("typ", "")),
            art=_lbl(a.get("art", "quert")) if a.get("art") in ("quert", "streift") else (a.get("art") or ""),
            zone=_zone_name(a.get("zone", "")),
            when=_when(a.get("fenster_von_utc") or med),
        ))
    # Keine Distanz-Zeilen ("Warmfront 230 km suedoestlich") mehr: der Pilot
    # sieht die Fronten auf der Karte, und ob eine kommt, sagt das Fazit
    # (_front_fazit). Ohne Durchgang am Fokus-Tag bleibt die Liste leer.
    return lines


def _lage_regime(wl: dict, date: str) -> tuple[str, str]:
    """(regime hoch|tief|neutral, Tendenz up|down|flat) fuer den Tag."""
    press = _per_day_index(wl.get("pressure_influence"), [date]).get(date) or {}
    regime = (press.get("regime") or "neutral").replace("druck", "")
    regime = regime if regime in ("hoch", "tief") else "neutral"
    slope = (wl.get("pressure_influence") or {}).get("slope_hpa_per_day")
    tkey = ("up" if isinstance(slope, (int, float)) and slope >= 2
            else "down" if isinstance(slope, (int, float)) and slope <= -2 else "flat")
    return regime, tkey


def _lage_effects(wl: dict, date: str, regime: str, tkey: str) -> dict:
    """Wetterfolge fuer die ganze Schweiz aus den Nord/Sued-Aggregaten, in
    Worten: {rain, rain_trend, wind} — inkl. Logik-Abgleich mit der
    Druck-Tendenz. Fuer die Wochenkacheln."""
    pp = _per_day_index(wl.get("precip_pattern"), [date]).get(date) or {}
    wp = _per_day_index(wl.get("wind_pattern"), [date]).get(date) or {}

    def _wavg(field, key):
        tot, acc = 0, 0.0
        for side in ("alpennord", "alpensued"):
            v = field.get(side) or {}
            n = v.get("n_spots") or 0
            if n and isinstance(v.get(key), (int, float)):
                tot += n
                acc += n * v[key]
        return (acc / tot) if tot else None

    wet = _wavg(pp, "wet_share")
    wet_n = ((pp.get("alpennord") or {}).get("wet_share"))
    wet_s = ((pp.get("alpensued") or {}).get("wet_share"))
    if wet is None:
        rain = _lbl("lg_rain_mostly_dry")
    elif wet < 0.05:
        rain = _lbl("lg_rain_dry")
    elif wet < 0.15 and wet_s is not None and wet_s >= 0.2 and (wet_n or 0) < 0.1:
        rain = _lbl("lg_rain_south_only")
    elif wet < 0.15 and wet_n is not None and wet_n >= 0.2 and (wet_s or 0) < 0.1:
        rain = _lbl("lg_rain_north_only")
    elif wet < 0.15:
        rain = _lbl("lg_rain_mostly_dry")
    elif wet < 0.4:
        rain = _lbl("lg_rain_partly")
    else:
        rain = _lbl("lg_rain_wide")

    pz = ((_per_day_index(wl.get("precip_zones"), [date]).get(date) or {}).get("zones") or {})

    def _win(name):
        tot, acc = 0, 0.0
        for z in pz.values():
            w = ((z or {}).get("windows") or {}).get(name) or {}
            n = w.get("n_spots") or 0
            if n and isinstance(w.get("wet_share"), (int, float)):
                tot += n
                acc += n * w["wet_share"]
        return (acc / tot) if tot else None

    early, late = _win("morning"), _win("afternoon")
    rain_trend = ""
    if early is not None and late is not None and wet is not None and wet >= 0.05:
        if early >= 0.1 and late <= early * 0.5:
            rain_trend = _lbl("lg_rain_fading")
        elif late >= 0.1 and late >= early * 2:
            rain_trend = _lbl("lg_rain_growing")

    warn = _wavg(wp, "share_wind_warn")
    crit = _wavg(wp, "share_wind_crit")
    warn_n = ((wp.get("alpennord") or {}).get("share_wind_warn"))
    warn_s = ((wp.get("alpensued") or {}).get("share_wind_warn"))
    if warn is None or warn < 0.3:
        wind = _lbl("lg_wind_calm")
    elif (crit or 0) >= 0.3:
        wind = _lbl("lg_wind_strong")
    elif warn < 0.6:
        wind = _lbl("lg_wind_partly")
    else:
        wind = _lbl("lg_wind_wide")
    if warn is not None and warn >= 0.3:
        drivers = {(wp.get(side) or {}).get("wind_driver") for side in ("alpennord", "alpensued")}
        if drivers == {"hoehenwind"}:
            wind += _lbl("lg_wind_aloft")
        if warn_n is not None and warn_s is not None:
            if warn_n - warn_s >= 0.25:
                wind += _lbl("lg_wind_less_south")
            elif warn_s - warn_n >= 0.25:
                wind += _lbl("lg_wind_less_north")
    # Logik-Abgleich: "beruhigt sich" darf nicht neben "Schauer nehmen zu" stehen.
    # Steigt der Druck, aber der Regen nimmt zu, wird die Beruhigung eingegrenzt
    # (nur Norden) oder vertagt; ist es unbestaendig, aber trocken, gilt "vorerst".
    calming = tkey == "up" or (regime == "hoch" and tkey == "flat")
    if calming and rain_trend == _lbl("lg_rain_growing") and rain == _lbl("lg_rain_south_only"):
        rain, rain_trend = _lbl("lg_rain_south_growing"), ""
    unsettled = tkey == "down" or (regime == "tief" and tkey == "flat")
    if unsettled and rain in (_lbl("lg_rain_dry"), _lbl("lg_rain_mostly_dry"))             and rain_trend != _lbl("lg_rain_growing"):
        rain = _lbl("lg_rain_for_now") + rain
    return {"rain": rain, "rain_trend": rain_trend, "wind": wind}


# Lage-Zeichen (User 26.10.2026): nur der Druck — Wind und Regen stehen in
# anderen Bloecken. Druckzentren zaehlen nur in der Naehe der Schweiz
_LI_CENTER_KM = 1000
_LI_CH = (46.8, 8.2)


def _lage_indicators(wl: dict, date: str):
    """(Status, Pille, Chips, Satz) des Lage-Blocks — gleicher Aufbau wie der
    Foehn-Block (User 26.10.2026), damit der Leser ihn gleich liest: vier
    Indikatoren fuer Hoch- bzw. Tiefdruck, nur aus dem Druck (Wind und Regen
    haben eigene Bloecke): Luftdruck ueber der Schweiz, Tendenz ueber 3 Tage,
    Verlauf 06-22 h, Druckzentrum in der Naehe. Die Seite (Hoch/Tief) gibt der
    Luftdruck vor; dazwischen die Seite mit mehr Zeichen. Pille immer grau:
    Hoch ist nicht "gut", Tief nicht "schlecht"."""
    press = _per_day_index(wl.get("pressure_influence"), [date]).get(date) or {}
    msl = press.get("msl_hpa")
    if not isinstance(msl, (int, float)):
        return "", "", [], ""

    def num(x):
        return isinstance(x, (int, float))

    regime = (press.get("regime") or "").lower().replace("druck", "")
    slope = (wl.get("pressure_influence") or {}).get("slope_hpa_per_day")
    thr_s = config.SYNOPTIC_PRESSURE_TREND_THRESHOLD_HPA
    fs = wl.get("frontsignatur") or {}
    tag = (next((d for d in fs.get("per_day") or [] if d.get("date") == date), None) or {}).get("druck_tag") or {}
    t = tag.get("tendenz_hpa") if tag.get("einig") else None
    thr_t = config.SYNOPTIC_DRUCK_TENDENZ_HPA
    near = {}                                   # naechstes Hoch / Tief im Umkreis
    for d in wl.get("pressure_centers_per_day") or []:
        if d.get("date") != date:
            continue
        for c in d.get("centers") or []:
            typ = {"Hoch": "hoch", "Tief": "tief"}.get(c.get("type"))
            if typ and num(c.get("lat")) and num(c.get("lon")):
                km = _haversine_km(_LI_CH[0], _LI_CH[1], c["lat"], c["lon"])
                if km <= _LI_CENTER_KM and (typ not in near or km < near[typ][0]):
                    near[typ] = (km, c)
    # je Seite: welche Indikatoren erfuellt sind
    hits = {
        "hoch": {"p": msl >= config.SYNOPTIC_HOCH_HPA, "trend": num(slope) and slope >= thr_s,
                 "day": num(t) and t >= thr_t},
        "tief": {"p": msl <= config.SYNOPTIC_TIEF_HPA, "trend": num(slope) and slope <= -thr_s,
                 "day": num(t) and t <= -thr_t},
    }
    if regime in ("hoch", "tief"):
        side = regime
    else:
        nh, nt = sum(hits["hoch"].values()), sum(hits["tief"].values())
        side = "hoch" if nh > nt or (nh == nt and (slope or 0) >= 0) else "tief"
    on = hits[side]
    thr_p = config.SYNOPTIC_HOCH_HPA if side == "hoch" else config.SYNOPTIC_TIEF_HPA
    def _word(delta, pos_side_word, neg_side_word, ok_word):
        """Hoch: Anstieg = aufbauen; Tief: Abfall = aufbauen (Tief vertieft sich)."""
        if delta is None or abs(delta) < 1e-9:
            return _lbl("li_w_gleich")
        rising = delta > 0
        if side == "hoch" or side == "tief":
            building = rising if side == "hoch" else not rising
            return _lbl(ok_word[0] if building else ok_word[1])
        return _lbl(pos_side_word if rising else neg_side_word)

    trend_d = slope if num(slope) and abs(slope) >= thr_s else (0 if num(slope) else None)
    day_d = t if num(t) and abs(t) >= thr_t else (0 if num(t) else None)
    # Label nennt, WAS sich aendert (User 31.10.2026: "Trend 3 days: stays the same"
    # war unklar) — "Hochdruck naechste 3 Tage: etwa gleich"
    subj = _lbl("li_side_" + side) if on["p"] else _lbl("li_subj_none")
    # Keine Zaehlung mehr (User 31.10.2026): die Pille sagt, was ueber der Schweiz
    # liegt; die Chips beschreiben Tagesverlauf und Tendenz, ohne orange Markierung
    facts = [
        {"k": _lbl("li_k_tagesgang").format(subj=subj), "on": False,
         "v": (_word(day_d, "li_w_steigt", "li_w_faellt", ("li_w_verst", "li_w_abbau"))
               if num(t) else _lbl("li_v_mixed") if tag else "—")},
        {"k": _lbl("li_k_tend3").format(subj=subj), "on": False,
         "v": _word(trend_d, "li_w_steigt", "li_w_faellt", ("li_w_aufbau", "li_w_abklingen"))
              if num(slope) else "—"},
    ]
    side_w = _lbl("li_side_" + side)
    pill = side_w if on["p"] else _capitalize(_lbl("li_v_neither"))
    fmt = {"m": _model_words(), "side": side_w, "side_l": side_w.lower()}
    # 1 Was liegt ueber der Schweiz?
    out = _lbl("li_p_on" if on["p"] else "li_p_off").format(hpa=f"{float(msl):.1f} hPa", **fmt)
    # 2 Wie entwickelt sich der Druck ueber den Flugtag (06-22 h)?
    if num(t):
        way = "up" if t >= thr_t else "down" if t <= -thr_t else "flat"
        if on["p"] and way != "flat":
            # gleiche Woerter wie das Label "Tagesverlauf" (User 31.10.2026)
            building = (way == "up") == (side == "hoch")
            out += _lbl("li_dday_verst" if building else "li_dday_abbau").format(v=f"{t:+.1f}", **fmt)
        else:
            out += _lbl("li_day_" + way).format(v=(f"{abs(t):.1f}" if way != "flat" else f"{t:+.1f}"))
    elif tag:
        m = tag.get("muster") or {}
        wie = ""
        if m.get("art") == "nord_sued":
            wie = _lbl("li_day_ns").format(a=_lbl("pt_" + m["nord"]), b=_lbl("pt_" + m["sued"]))
        elif m.get("art") == "einzel":
            rest = "down" if m["richtung"] == "up" else "up"
            wie = _lbl("li_day_one").format(zone=_zone_name(m["zone"]), a=_lbl("pt_" + m["richtung"]),
                                            b=_lbl("pt_" + rest))
        out += _lbl("li_day_mixed").format(wie=wie)
    # kein Satz zum staerksten 3-h-Sprung mehr (User 31.10.2026: braucht es nicht)
    # 3 Ausblick ueber die drei Prognosetage
    if num(slope):
        way = "up" if slope >= thr_s else "down" if slope <= -thr_s else "flat"
        key = ((f"li_was_{side}_{way}" if way != "flat" else "li_was_on_flat") if on["p"]
               else f"li_was_off_{way}")
        out += _lbl("li_dev").format(was=_lbl(key).format(**fmt), v=f"{slope:+.1f}")
    # Pille sichtbar wie die anderen (User 31.10.2026): "info" (blau) — Hoch ist nicht
    # "gut" (gruen), Tief nicht "schlecht" (orange); grau war auf Weiss kaum zu sehen
    return "info", pill, facts, out


def _lage_data_words(wl: dict | None, date: str) -> str:
    """Nur die Wetterfolge als Satz — der Tages-Hinweis der Wochenkacheln.
    Leer, wenn der Kontext keine Aggregate traegt."""
    wl = wl or {}
    if not (_per_day_index(wl.get("precip_pattern"), [date]).get(date)
            or _per_day_index(wl.get("wind_pattern"), [date]).get(date)):
        return ""
    regime, tkey = _lage_regime(wl, date)
    e = _lage_effects(wl, date, regime, tkey)
    return _capitalize(f"{e['rain']}{e['rain_trend']}, {e['wind']}.")


def _lage_fazit(wetterlage: dict | None, date: str) -> str:
    return _lage_block(wetterlage, date)["fazit"]


def _lage_block(wetterlage: dict | None, date: str) -> dict:
    """Die Lage fuer die ganze Schweiz (seit 26.10.2026): liegt Hoch- oder
    Tiefdruck ueber der Schweiz, und woran sieht man das im Druck
    (_lage_indicators)? Nur Druck — Wind und Regen haben eigene Bloecke. Ohne
    Deutung ("beruhigt sich") und ohne Urteil "Daten passen/widersprechen"."""
    wl = wetterlage or {}
    if not wl:
        return {"fazit": ""}
    kind, pill, facts, txt = _lage_indicators(wl, date)
    out = {"fazit": txt}
    if kind:
        out.update(status=kind, status_label=pill, facts=facts)
    return out


def _sector_word(deg) -> str:
    names = _lbl("sectors").split(",")
    return names[int(((float(deg) + 22.5) // 45) % 8)]


_STUFE_RANG = {"deutlich": 2, "schwach": 1, None: 0}


def _front_zeichen(wetterlage: dict | None, date: str, zone: str = "") -> tuple[str, dict]:
    """(Zone, Frontzeichen) des Tages aus wetterlage['frontsignatur'] — fuer
    die genannte Zone, sonst die Zone mit den staerksten Zeichen. ("", {}),
    wenn der Kontext das Feld nicht hat."""
    fs = (wetterlage or {}).get("frontsignatur") or {}
    day = next((d for d in fs.get("per_day") or [] if d.get("date") == date), None)
    zones = {z: v for z, v in ((day or {}).get("zones") or {}).items() if isinstance(v, dict)}
    if zone:
        return (zone, zones[zone]) if zone in zones else ("", {})
    if not zones:
        return "", {}
    z = max(zones, key=lambda k: (_STUFE_RANG.get(zones[k].get("stufe"), 0),
                                  abs((zones[k].get("t850") or {}).get("k") or 0),
                                  (zones[k].get("druck") or {}).get("hpa") or 0))
    return z, zones[z]


def _kaltluft_ohne_dwd(zeichen: dict) -> bool:
    """Deutlich kaeltere Luft plus Druckanstieg: ein Luftmassenwechsel, der
    auch ohne DWD-Front ins Briefing gehoert."""
    t = zeichen.get("t850") or {}
    return (t.get("richtung") == "kalt" and t.get("stufe") == "deutlich"
            and bool((zeichen.get("druck") or {}).get("stufe")))


def _zeichen_text(zeichen: dict, key: str) -> str:
    """Ein Zeichen in Worten mit Zahl. key: druck, druck_fall, kalt, warm,
    regen, drehung (kalt/warm = T850 in dieser Richtung)."""
    if key in ("kalt", "warm"):
        z = zeichen.get("t850") or {}
        return _lbl(f"ez_{key}_{z['stufe']}").format(val=f"{z['k']:+.1f}")
    z = zeichen.get(key) or {}
    if key == "druck":
        return _lbl(f"ez_druck_{z['stufe']}").format(val=f"{z['hpa']:+.1f}")
    if key == "druck_fall":
        return _lbl(f"ez_druckfall_{z['stufe']}").format(val=f"{z['hpa']:+.1f}")
    if key == "regen":
        return _lbl(f"ez_regen_{z['stufe']}").format(val=f"{z['mm']:.0f}" if z["mm"] >= 2 else f"{z['mm']:.1f}")
    return _lbl("ez_drehung").format(sector=_sector_word(z["nach"]))


def _zeichen_stufe(zeichen: dict, key: str) -> str | None:
    if key in ("kalt", "warm"):
        t = zeichen.get("t850") or {}
        return t.get("stufe") if t.get("richtung") == key else None
    return (zeichen.get(key) or {}).get("stufe")


def _zeichen_words(zeichen: dict, typ: str = "kalt") -> tuple[str | None, str, str]:
    """(Stufe, Zeichen in Worten, Gegenzeichen) fuer einen Fronttyp — nur
    die Zeichen, die zu diesem Typ passen (Warmfront: Druckfall, waermere
    Luft, Regen; Kaltfront: Druckanstieg, kaeltere Luft, Regen, Drehung),
    deutliche zuerst. Gegenzeichen: deutlich die andere Luftmasse als der Typ
    erwarten laesst (DWD-Warmfront, aber deutlich kaeltere Luft) — die
    gehoert in den Satz, sonst verschweigt er den eigentlichen Wechsel."""
    from engine.synoptic_context import front_zeichen_passend
    stufe, keys = front_zeichen_passend(zeichen, typ)
    items = sorted(((-_STUFE_RANG[_zeichen_stufe(zeichen, k)], i, _zeichen_text(zeichen, k))
                    for i, k in enumerate(keys)))
    gegen = ""
    t = zeichen.get("t850") or {}
    erwartet = {"kalt": "kalt", "trog": "kalt", "warm": "warm"}.get(typ)
    if erwartet and t.get("stufe") == "deutlich" and t.get("richtung") != erwartet:
        gegen = _zeichen_text(zeichen, t["richtung"])
    return stufe, ", ".join(x for _, _, x in items), gegen


def _druck_tag_words(wetterlage: dict | None, date: str) -> tuple[str, str, bool]:
    """(Tagestendenz-Text, Sprung-Text, Sprung hervorheben) fuer die Druckzeile
    aus frontsignatur.per_day[date].druck_tag — Worte vom Code, nicht von der
    KI. Einig: eine Zahl. Uneinig: 'uneinheitlich' plus das Muster in ein
    paar Woertern, wenn es eines gibt."""
    fs = (wetterlage or {}).get("frontsignatur") or {}
    day = next((d for d in fs.get("per_day") or [] if d.get("date") == date), None)
    tag = (day or {}).get("druck_tag") or {}
    if not tag:
        return "", "", False
    if tag.get("einig"):
        t = tag.get("tendenz_hpa")
        day_txt = _lbl("pt_day").format(val=f"{t:+.1f}") if t is not None else ""
    else:
        day_txt = _lbl("pt_mixed")
        m = tag.get("muster") or {}
        if m.get("art") == "nord_sued":
            day_txt += _lbl("pt_ns").format(a=_lbl("pt_" + m["nord"]), b=_lbl("pt_" + m["sued"]))
        elif m.get("art") == "einzel":
            day_txt += _lbl("pt_one").format(zone=_zone_name(m["zone"]),
                                             dir=_lbl("pt_" + m["richtung"]))
    sp = tag.get("sprung") or {}
    jump_txt = ""
    if sp.get("hpa") is not None:
        h = int((sp.get("hour") or "00:00")[:2])
        jump_txt = _lbl("pt_jump").format(val=f"{sp['hpa']:+.1f}", von=f"{h:02d}",
                                          bis=f"{h + 3:02d}", zone=_zone_name(sp.get("zone", "")))
    return day_txt, jump_txt, bool(tag.get("sprung_hot"))


def _nearest_front(fronts: dict | None, typ: str):
    """(Distanz km, Punkt [lon, lat]) der naechsten Front dieses Typs auf der
    Karte, oder None."""
    best = None
    for f in (fronts or {}).get("features") or []:
        if (f.get("properties") or {}).get("typ") != typ:
            continue
        for c in (f.get("geometry") or {}).get("coordinates") or []:
            d = _haversine_km(46.8, 8.2, c[1], c[0])
            if best is None or d < best[0]:
                best = (d, c)
    return best


def _front_day_word(iso_day: str, dates: list) -> str:
    """'heute' / 'morgen' / 'am So' relativ zum ersten Tag des Fensters."""
    lang = _lang()
    try:
        d = date.fromisoformat(iso_day)
    except ValueError:
        return iso_day
    today = date.fromisoformat(dates[0]) if dates else datetime.now().date()
    off = (d - today).days
    if off == 0:
        return "heute" if lang == "de" else "today"
    if off == 1:
        return "morgen" if lang == "de" else "tomorrow"
    short = {"de": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
             "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}[lang][d.weekday()]
    return ("am " if lang == "de" else "on ") + short


# Zone mit Artikel im Akkusativ (DE) bzw. Artikel wo ueblich (EN) — fuer
# "streift den Alpennordhang" / "brushes the Northern Alps"
_ZONE_ARTICLE = {"de": {"alpennordhang": "den ", "wallis": "das ", "tessin": "das "},
                 "en": {"alpennordhang": "the "}}
_ZONE_ARTICLE_DAT = {"de": {"alpennordhang": "dem ", "wallis": "dem ", "tessin": "dem "},
                     "en": {"alpennordhang": "the "}}


def _zone_dat(zone_id: str) -> str:
    return _ZONE_ARTICLE_DAT[_lang()].get(zone_id, "") + _zone_name(zone_id)


def _zone_object(zone_id: str) -> str:
    return _ZONE_ARTICLE[_lang()].get(zone_id, "") + _zone_name(zone_id)


def _front_fazit(fronts: dict | None, passagen: dict | None, dates: list,
                 focus: str = "", wetterlage: dict | None = None) -> str:
    return _front_block(fronts, passagen, dates, focus, wetterlage)["fazit"]


def _front_block(fronts: dict | None, passagen: dict | None, dates: list,
                 focus: str = "", wetterlage: dict | None = None) -> dict:
    """Kurzes Fazit: kommt eine Front — laut DWD-Frontenprognose (passagen_*.json,
    Durchgang je Zone aus den +36…+108-h-Karten). Immer als Prognose formuliert.

    Satz 1 gilt IMMER dem Fokus-Tag ("Heute wird keine Front erwartet." oder
    "Heute duerfte die Kaltfront …"). Satz 2 ist der Ausblick: fruehester
    Durchgang im 3-Tage-Fenster > Durchgang danach > naechste Front auf der
    Analysekarte bleibt fern > gar keine Front."""
    if not dates:
        return {"fazit": "", "rear": False, "dwd": False, "dwd_typ": "",
                "zeichen": None, "ohne_dwd": False}
    focus = focus if focus in dates else dates[0]
    window_end = date.fromisoformat(dates[-1])
    hits = []
    for a in (passagen or {}).get("aussagen") or []:
        med = a.get("durchgang_median_utc") or ""
        try:
            local = datetime.fromisoformat(med.replace("Z", "+00:00")).astimezone(_TZ)
        except (TypeError, ValueError):
            continue
        hits.append((local, a))
    hits.sort(key=lambda h: h[0])

    def _typ(a):
        t = _front_type(a.get("typ", ""))
        return t.lower() if _lang() == "en" else t

    def _art(a, infinitive=False):
        art = a.get("art") if a.get("art") in ("quert", "streift") else "quert"
        if _lang() == "en" and infinitive:
            return {"quert": "cross", "streift": "brush"}[art]
        return _lbl(art)

    day_word = _front_day_word(focus, dates)
    day_cap = day_word[0].upper() + day_word[1:]

    # 0) durchgezogene Front (DWD-Analyse, letzte 36 h vor dem Fokus-Tag)
    passed = ""
    focus_start = datetime.fromisoformat(focus).replace(tzinfo=_TZ)
    for e in (passagen or {}).get("vergangen") or []:
        try:
            med = datetime.fromisoformat(e["median_utc"]).astimezone(_TZ)
        except (KeyError, ValueError):
            continue
        if med >= focus_start or (focus_start - med).total_seconds() > 36 * 3600:
            continue
        when_day = (_lbl("yesterday") if (focus_start.date() - med.date()).days == 1
                    else _front_day_word(med.date().isoformat(), dates))
        when = when_day[0].upper() + when_day[1:] + " " + _when(e["median_utc"])
        passed = _lbl("front_passed").format(
            When=when, typ=_typ(e), zone=_zone_object(e.get("zone", "")), day=day_word)
        break

    # Der neueste Lauf sieht die naechsten 36 h nicht (Vorhersagekarten ab
    # +36 h). Eine Aussage fuer den Fokus-Tag stammt deshalb oft aus dem
    # Vortageslauf — die gilt nur, wenn die Karte des Tages die Front noch
    # zeigt (gleicher Typ, hoechstens 600 km entfernt). Sonst ist sie
    # aufgeloest oder schon durch, und der Satz waere erfunden.
    latest_run = max((a.get("lauf") or "" for _, a in hits), default="")
    today_hits = []
    for l, a in hits:
        if l.date().isoformat() != focus:
            continue
        prov = ""
        if (a.get("lauf") or "") != latest_run:
            near = _nearest_front(fronts, a.get("typ", ""))
            if not near or near[0] > 600:
                continue                      # Karte kennt die Front nicht mehr
            prov = _lbl("front_prev_run").format(dist=int(round(near[0] / 10) * 10),
                                                 dir=_bearing_word(near[1][1], near[1][0]))
        today_hits.append((l, a, prov))
    today_typ = ""
    # Die DWD-Prognose nennt die Front, die eigene Prognose beschreibt ihre
    # Zeichen (Druckanstieg, kaeltere/waermere Luft auf 1500 m, Regen,
    # Hoehenwind-Drehung) — ohne Urteil. Bis 09.10.2026 stand hier ein Ja/Nein
    # ("zieht durch" / "duerfte sich aufloesen"), das an keinem Fronttag
    # angeschlagen hat; die Kaltfront vom 08.10. hiess deshalb "loest sich auf".
    stufe = None
    ohne_dwd = False
    if today_hits:
        # Nennt der DWD mehrere Zonen, gilt der Satz der Zone mit den
        # staerksten Zeichen (01.10.2026: Wallis zuerst mit schwachen
        # Zeichen, am Alpennordhang waren sie deutlich); bei Gleichstand
        # der frueheste Durchgang.
        rank = [_STUFE_RANG.get(_zeichen_words(_front_zeichen(wetterlage, focus, h[1].get("zone", ""))[1],
                                               h[1].get("typ", ""))[0], 0) for h in today_hits]
        local, a, prov = today_hits[rank.index(max(rank))]
        today_typ = a.get("typ", "")
        z, zeichen = _front_zeichen(wetterlage, focus, a.get("zone", ""))
        if zeichen:
            stufe, words, gegen = _zeichen_words(zeichen, today_typ)
            key = {"deutlich": "front_z_deutlich", "schwach": "front_z_schwach"}.get(stufe, "front_z_keine")
            first = _lbl(key).format(models=_model_words(),
                typ=_typ(a), day=day_word, Day=day_cap, zone=_zone_object(a.get("zone", "")),
                zone_dat=_zone_dat(a.get("zone", "")),
                when=_when(a.get("fenster_von_utc") or a.get("durchgang_median_utc") or ""),
                zeichen=words)
            if gegen:
                first += _lbl("front_z_gegen").format(gegen=gegen)
            first = first[0].upper() + first[1:]
        else:
            unsicher = bool(a.get("randwert")) or (a.get("anteil") or 0) < 0.1
            first = _lbl("front_today_in").format(
                Day=day_cap, typ=_typ(a), zone=_zone_object(a.get("zone", "")),
                when=_when(a.get("fenster_von_utc") or a.get("durchgang_median_utc") or ""),
                art=_art(a), art_inf=_art(a, infinitive=True),
                unsicher=_lbl("front_unsicher") if unsicher else "", prov=prov)
    else:
        z, zeichen = _front_zeichen(wetterlage, focus)
        if zeichen and _kaltluft_ohne_dwd(zeichen):
            ohne_dwd = True
            stufe, words, _ = _zeichen_words(zeichen, "kalt")
            first = _lbl("front_z_ohne_dwd").format(models=_model_words(), day=day_word, Day=day_cap,
                zone=_zone_object(z), zone_dat=_zone_dat(z), zeichen=words)
        else:
            first = _lbl("front_today_none").format(Day=day_cap)
    if passed:
        first = passed + " " + first
    # Nur der Tag zaehlt. Ob am Sonntag eine Front kommt, steht im Briefing
    # des Sonntags — kein Ausblick, keine "weitere Front".
    # rear = Ist-Durchgang in den 36 h vor dem Tag (DWD-Analyse) -> Pille "Rueckseite"
    # dwd  = die DWD-Prognose nennt fuer DIESEN Tag eine Front (dieselbe Quelle
    #        wie der Satz: passagen_*.json, inkl. Karten-Gegenprobe fuer aeltere
    #        Laeufe). Frueher las die Pille stattdessen wetterlage.fronten.
    #        durchgaenge — eine zweite Quelle mit eigener Tageszuordnung, die
    #        "keine Front" neben einen Satz mit Front stellen konnte (19.09.2026).
    # zeichen  = Stufe der Frontzeichen in der eigenen Prognose (Pille)
    # ohne_dwd = keine DWD-Front, aber deutlich kaeltere Luft + Druckanstieg
    # dwd_zone_hours: Stunde je Zone (Lokalzeit) der DWD-Fronten des Tages — nur fuer
    # die Zugrichtung im neuen Block (die Uhrzeit selbst wird nie genannt, 17.10.2026)
    zone_hours = {}
    for l, a, _ in today_hits:
        if not today_typ or a.get("typ") == today_typ:
            zone_hours.setdefault(a.get("zone", ""), l.hour)
    return {"fazit": first, "rear": bool(passed),
            "dwd": bool(today_hits), "dwd_typ": today_typ or "",
            "dwd_zone_hours": zone_hours,
            "zeichen": stufe, "ohne_dwd": ohne_dwd}


def _zugbahn_text(wetterlage: dict, date: str) -> str:
    zb = _per_day_index(wetterlage.get("zugbahn"), [date]).get(date) or {}
    # None = Gruppe bleibt trocken — nur die nassen Gruppen tragen eine Zeit
    onset = {k: v for k, v in (zb.get("onset_hour_by_group") or {}).items()
             if isinstance(v, (int, float))}
    if not onset:
        return ""
    mv = zb.get("movement") or {}
    if all(v == "gleichzeitig" for v in mv.values()) and len(set(onset.values())) <= 1:
        return _lbl("showers_from").format(h=f"{int(min(onset.values())):02d}") + " — " + _lbl("simultaneous")
    def name(group):
        # West/Ost-Teil des Alpennordhangs hat eigene Labels, sonst Zonenname
        own = _lbl("zb_" + group)
        return own if own != "zb_" + group else _zone_name(group)
    parts = [f"{name(k)} {int(v):02d}h" for k, v in sorted(onset.items(), key=lambda kv: kv[1])]
    return _lbl("showers_onset") + ": " + " → ".join(parts)


def _thermik_fazit(wetterlage: dict, date: str) -> str:
    """Block 6: was die Synoptik fuer Thermik und Basis erwarten laesst (Druck,
    T850) und was die Prognosedaten je Zone zeigen (Basis, Steigen, Beginn,
    Sonne/tiefe Wolken). Leer ohne thermik_zonen."""
    wl = wetterlage or {}
    tz = ((_per_day_index(wl.get("thermik_zonen"), [date]).get(date) or {}).get("zones") or {})
    zones = {z: v for z, v in tz.items() if v}
    if not zones:
        return ""
    lang = _lang()
    regime, tkey = _lage_regime(wl, date)
    if regime == "hoch" or tkey == "up":
        press = _lbl("th_press_hoch" if regime == "hoch" else "th_press_up")
        expect = _lbl("th_exp_high").format(Press=press)
    elif regime == "tief" or tkey == "down":
        press = _lbl("th_press_tief" if regime == "tief" else "th_press_down")
        expect = _lbl("th_exp_low").format(Press=press)
    else:
        expect = _lbl("th_exp_flat")
    t850 = _per_day_index(wl.get("t850_trend"), [date]).get(date)
    if isinstance(t850, (int, float)):
        if t850 >= 14:
            expect += _lbl("th_t850_warm")
        elif t850 <= 4:
            expect += _lbl("th_t850_cold")
    # Basis: Spanne ueber die Zonen
    bases = {z: v["base_m"] for z, v in zones.items() if isinstance(v.get("base_m"), (int, float))}
    if len(bases) >= 2 and max(bases.values()) - min(bases.values()) >= 300:
        lo_z = min(bases, key=bases.get)
        hi_z = max(bases, key=bases.get)
        def _zin(z):
            if lang != "de":
                return "in " + _ZONE_ARTICLE_DAT["en"].get(z, "") + _zone_name(z)
            return ("am " if z == "alpennordhang" else ("im " if _ZONE_ARTICLE_DAT["de"].get(z) else "in ")) + _zone_name(z)
        base = _lbl("th_base_range").format(lo_zone=_zin(lo_z), hi_zone=_zin(hi_z))
    elif bases:
        base = _lbl("th_base_one")
    else:
        base = _lbl("th_base_none")
    # Steigen: Median der Zonen-Spitzen
    climbs = [v["climb_ms"] for v in zones.values() if isinstance(v.get("climb_ms"), (int, float))]
    c = statistics.median(climbs) if climbs else 0
    grade = ("strong" if c >= 3 else "good" if c >= 2 else "mod" if c >= 1 else "weak")
    climb = _lbl("th_climb").format(grade=_lbl("th_grade_" + grade))
    start = ""   # Thermikbeginn bewusst weggelassen (User 18.09.2026: brauchen wir nicht)
    # Sonne / tiefe Wolken: Norden (Alpennordhang) gegen Sueden (Tessin)
    def cloudy(z):
        v = zones.get(z) or {}
        lc = v.get("low_cloud_pct")
        return None if lc is None else lc >= 60
    joiner = " und " if lang == "de" else " and "
    sunny = [_zone_name(z) for z in config.SYNOPTIC_ZONES if cloudy(z) is False]
    cloud = [_zone_name(z) for z in config.SYNOPTIC_ZONES if cloudy(z) is True]

    def _names(ns):
        return (", ".join(ns[:-1]) + joiner + ns[-1]) if len(ns) > 1 else "".join(ns)

    if sunny and cloud:
        sun = _lbl("th_sun_split").format(sunny=_names(sunny), cloudy=_names(cloud))
    elif cloud:
        sun = _lbl("th_cloud_all")
    elif sunny:
        sun = _lbl("th_sun_all")
    else:
        sun = ""
    # Urteil: Hoch/steigend erwartet gedeckelte Basis, Tief/fallend eine hohe —
    # gemessen am Median der Zonen-Basen (Schwelle 2800 m)
    med_base = statistics.median(bases.values()) if bases else None
    if med_base is None or not (regime in ("hoch", "tief") or tkey in ("up", "down")):
        key = "th_data"
    elif regime == "hoch" or tkey == "up":
        key = "th_match" if med_base < 2800 else "th_contra_higher"
    else:
        key = "th_match_high" if med_base >= 2800 else "th_contra_lower"
    return expect + _lbl(key).format(models=_model_words(), base=base, climb=climb, start=start, sun=sun)


MD_PARAMS = ("rain", "dir", "speed", "gust", "cloud", "cloud_low")   # Reihenfolge = Piloten-Relevanz


def _mc_consensus(zones: dict, param: str) -> dict | None:
    """Konsens einer Groesse als Prozent: Anteil der beurteilten
    (Region, Tagesfenster)-Paare ueber alle Zonen, in denen die Region einig
    ist. Die Bewertung selbst faellt im Engine (Region = Median ihrer
    Referenzpunkte je Modell); hier wird nur gezaehlt. Dazu die Stelle mit dem
    groessten Streit (Zone + Fenster), die Zonen ueber der Schwelle und die
    Fenster, in denen keine betroffene Zone uneinig ist."""
    total = agree = 0
    worst = None            # (share, zone, window)
    dis_zones, dis_wins = [], set()
    for z, zv in zones.items():
        pv = (zv.get("params") or {}).get(param)
        if not pv:
            continue
        if pv.get("disagree"):
            dis_zones.append(z)
        for w, info in (pv.get("windows") or {}).items():
            n = int(info.get("n_regions") or 0)
            if not n:
                continue
            total += n
            agree += n - len(info.get("regions") or [])
            if info.get("disagree"):
                dis_wins.add(w)
            share = float(info.get("share") or 0.0)
            if worst is None or share > worst[0]:
                worst = (share, z, w)
    if not total or worst is None:
        return None
    pct = round(100 * agree / total)
    level = "ok" if pct >= 90 else ("info" if pct >= 67 else "warn")
    return {"pct": pct, "level": level, "zone": worst[1], "window": worst[2],
            "zones": dis_zones, "agree_windows": [w for w in _MD_WINDOWS if w not in dis_wins]}


_MD_WINDOWS = ("morning", "midday", "afternoon")   # Reihenfolge des Tages


def _md_agree_window_key(agree_wins: list) -> str:
    """Welche Tagesfenster sind einig? Als Satzteil, nicht als Liste."""
    got = [w for w in _MD_WINDOWS if w in set(agree_wins)]
    if not got:
        return "none"
    if got == ["midday", "afternoon"]:
        return "from_midday"
    if got == ["morning", "midday"]:
        return "until_midday"
    if got == ["morning", "afternoon"]:
        return "split"
    if len(got) == 1:
        return got[0]
    return "none"


def _modelle_block(wetterlage: dict, date: str) -> dict:
    """Block 8: sind sich die Modelle einig? Datenformat v2
    (engine.synoptic_context.modell_vergleich_aus_punkten).

    Drei Ebenen, alle kurz (26.09.2026 umgebaut; der Fliesstext mit drei
    Saetzen zu je fuenf Modellgruppen war unlesbar, und ✓/✗ war zu binaer):
    **Konsens in Prozent** je Groesse fuer die Pillen, **Fazit** nur ueber die
    nicht-gruenen Groessen (orange: ganzer Satz mit Zonen, Tagesfenster,
    Spanne und der Angabe, wann die Modelle wieder einig sind; blau: ein
    Halbsatz; gruen: nichts), und **eine Modell-Zeile je oranger Groesse**.
    Ort sind immer die Zonen, nie einzelne Regionen — die Regionsebene ist
    die Messebene, nicht die Erzaehlebene."""
    wl = wetterlage or {}
    mv = wl.get("modell_vergleich") or {}
    if mv.get("version") != 2:
        return {}
    day = _per_day_index(mv, [date]).get(date) or {}
    zones = {z: v for z, v in (day.get("zones") or {}).items() if v and v.get("params")}
    if not zones:
        return {}
    names = mv.get("models") or {}
    joiner = " und " if _lang() == "de" else " and "

    def big(t):
        return t[:1].upper() + t[1:] if t else t

    def short(m):
        return names.get(m, m).replace("ICON-", "")

    def groups_of(param, z, win):
        info = zones[z]["params"][param]["windows"][win]
        out: dict[int, list[str]] = {}
        for m, mv_ in (info.get("models") or {}).items():
            out.setdefault(int(mv_["cls"]), []).append(short(m))
        return out

    def models_line(param, groups):
        kind = "cloud" if param == "cloud_low" else param
        return " · ".join(_lbl("md_grp").format(label=_lbl(f"md_lab_{kind}_{c}"),
                                               models=", ".join(groups[c]))
                          for c in sorted(groups))

    cons = {p: _mc_consensus(zones, p) for p in MD_PARAMS}
    cons = {p: c for p, c in cons.items() if c}
    if not cons:
        return {}
    warn = [p for p in MD_PARAMS if cons.get(p, {}).get("level") == "warn"]
    info_ = [p for p in MD_PARAMS if cons.get(p, {}).get("level") == "info"]

    sentences, lines = [], []
    for param in warn:
        c = cons[param]
        kind = "cloud" if param == "cloud_low" else param
        groups = groups_of(param, c["zone"], c["window"])
        lo, hi = min(groups), max(groups)
        spread = _lbl("md_spread").format(lo=_lbl(f"md_word_{kind}_{lo}"),
                                          hi=_lbl(f"md_word_{kind}_{hi}"))
        nomaj = "" if any(len(v) >= 3 for v in groups.values()) else _lbl("md_nomaj")
        # Kein einiges Fenster: dann kein Fenster nennen — "am Vormittag" und
        # "den ganzen Tag uneinig" im selben Satz widersprechen sich.
        awin = _md_agree_window_key(c["agree_windows"])
        sentences.append(_lbl("md_warn_allday" if awin == "none" else "md_warn").format(
            what=big(_lbl("md_var_" + param)),
            zones=_zones_text(c["zones"] or [c["zone"]], where=True),
            window=_lbl("md_win_" + c["window"]), spread=spread, nomaj=nomaj,
            agreewin=_lbl("md_aw_" + awin)))
        what, grp = big(_lbl("md_var_" + param)), models_line(param, groups)
        lines.append({"what": what, "groups": grp,
                      "text": _lbl("md_line").format(what=what, groups=grp)})
    # Blau: ein Halbsatz, und nur fuer die unsicherste — sonst waechst das
    # Fazit wieder zu, wogegen der Umbau gemacht wurde.
    weakest = min(info_, key=lambda p: cons[p]["pct"]) if info_ else None
    if weakest and warn:
        c = cons[weakest]
        groups = groups_of(weakest, c["zone"], c["window"])
        odd = [cl for cl, ms in groups.items() if len(ms) == 1]
        rest = [cl for cl, ms in groups.items() if len(ms) > 1]
        if len(odd) == 1 and rest and weakest != "dir":
            sentences.append(_lbl("md_info").format(
                what=big(_lbl("md_var_" + weakest)), window=_lbl("md_win_" + c["window"]),
                models=", ".join(groups[odd[0]]),
                more=_lbl("md_more" if odd[0] > max(rest) else "md_less")))
        else:
            sentences.append(_lbl("md_info_plain").format(
                what=big(_lbl("md_var_" + weakest)), window=_lbl("md_win_" + c["window"])))
    elif weakest:
        sentences.append(_lbl("md_least").format(what=big(_lbl("md_var_" + weakest)),
                                                 pct=cons[weakest]["pct"]))
    head = _lbl("md_head_0") if not warn else (
        _lbl("md_head_1") if len(warn) == 1 else _lbl("md_head_n").format(n=len(warn)))
    verdict = "uncertain" if warn else ("partial" if info_ else "agree")
    return {"fazit": " ".join([head] + sentences), "lines": lines, "num": {},
            "verdict": verdict,
            "consensus": [{"k": _lbl("md_var_" + p), "v": f"{cons[p]['pct']} %",
                           "level": cons[p]["level"]} for p in MD_PARAMS if p in cons],
            "agree": [p for p in MD_PARAMS if p in cons and cons[p]["level"] == "ok"],
            "open": warn}


def _sonne_fazit(wetterlage: dict, date: str) -> str:
    return _sonne_block(wetterlage, date)["fazit"]


def _sonne_block(wetterlage: dict, date: str) -> dict:
    """Block 7: was die Synoptik an Sonne/Bewoelkung erwarten laesst (Druck,
    Luftmasse) und was die Prognosedaten je Landesteil zeigen (Sonnenanteil,
    tiefe vs. hohe Wolken). Leer ohne thermik_zonen. Liefert Satz und Urteil
    (match / partial / contra) zusammen — die Pille in _decorate_chain liest
    das Urteil aus dem Block, kein Modul-Zustand (mehrere Tage je Aufruf, Flask)."""
    wl = wetterlage or {}
    tz = ((_per_day_index(wl.get("thermik_zonen"), [date]).get(date) or {}).get("zones") or {})
    zones = {z: v for z, v in tz.items() if v and v.get("sun_share") is not None}
    if not zones:
        return {"fazit": "", "verdict": "match"}
    regime, tkey = _lage_regime(wl, date)
    if regime == "hoch" or tkey == "up":
        expect = _lbl("su_exp_high").format(Press=_lbl("th_press_hoch" if regime == "hoch" else "th_press_up"))
    elif regime == "tief" or tkey == "down":
        expect = _lbl("su_exp_low").format(Press=_lbl("th_press_tief" if regime == "tief" else "th_press_down"))
    else:
        expect = _lbl("su_exp_flat")
    flow = _per_day_index(wl.get("flow_overhead"), [date]).get(date) or {}
    abbr = _SECTOR_ABBR.get(flow.get("sector", ""), "")
    sector = _lbl("lg_sector_" + abbr) if abbr else ""
    if abbr in ("S", "SW", "SE"):
        expect += _lbl("su_air_south").format(sector=sector)
    elif abbr in ("N", "NW"):
        expect += _lbl("su_air_north").format(sector=sector)

    def word(v):
        s = v.get("sun_share") or 0
        w = _lbl("su_word_sunny" if s >= 0.6 else "su_word_mixed" if s >= 0.3 else "su_word_overcast")
        if s < 0.6:
            if (v.get("low_cloud_pct") or 0) >= 60:
                w += _lbl("su_low")
            elif (v.get("mid_high_pct") or 0) >= 60:
                w += _lbl("su_high")
        return w

    # Norden = Alpennordhang, Sueden = Tessin; die anderen Zonen ueber "am sonnigsten"
    # Zonen nach Sonnenklasse gruppieren und beim Namen nennen — "Norden/Sueden"
    # waere unpraezise (gemeint waeren nur Alpennordhang und Tessin)
    joiner = " und " if _lang() == "de" else " and "
    groups: dict[str, list[str]] = {}
    for z in config.SYNOPTIC_ZONES:
        if z in zones:
            groups.setdefault(word(zones[z]), []).append(_zone_name(z))
    parts = []
    for w_, names in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        names_txt = (", ".join(names[:-1]) + joiner + names[-1]) if len(names) > 1 else names[0]
        if len(names) == len(zones):
            parts.append(_lbl("su_both").format(word=w_))
        else:
            parts.append(_lbl("su_group").format(zones=names_txt, word=w_, cloud=""))
    wn = word(zones["alpennordhang"]) if "alpennordhang" in zones else None
    ws = word(zones["tessin"]) if "tessin" in zones else None
    best = ""

    # Abgleich: was die Lage je Landesteil erwarten laesst gegen die Daten.
    # Erwartung: Hoch/steigend -> Sonne, Tief/fallend -> Wolken; die Luftmasse
    # legt Wolken auf eine Seite (Suedwest -> Sueden, Nordwest -> Nordhang).
    high = regime == "hoch" or tkey == "up"
    low = regime == "tief" or tkey == "down"
    exp_n = "cloudy" if abbr in ("N", "NW") or low else ("sunny" if high else None)
    exp_s = "cloudy" if abbr in ("S", "SW", "SE") or low else ("sunny" if high else None)

    def obs(z):
        v = zones.get(z)
        if not v:
            return None
        sh = v.get("sun_share") or 0
        return "sunny" if sh >= 0.6 else "mixed" if sh >= 0.3 else "overcast"

    def fits(exp, ob):
        if exp is None or ob is None:
            return None
        return ob != "overcast" if exp == "sunny" else ob != "sunny"

    o_n, o_s = obs("alpennordhang"), obs("tessin")
    checks = [(fits(exp_n, o_n), "north", exp_n, o_n), (fits(exp_s, o_s), "south", exp_s, o_s)]
    misses = [(side, o) for ok, side, e, o in checks if ok is False]
    judged = [ok for ok, *_ in checks if ok is not None]
    zones_txt = ", ".join(parts)
    if not judged:
        return {"fazit": expect + _lbl("su_data").format(models=_model_words(), zones=zones_txt, best=best), "verdict": "match"}
    if not misses:
        key = "su_match_all" if (wn and ws and wn == ws) else "su_match"
        return {"fazit": expect + _lbl(key).format(models=_model_words(), zones=zones_txt, best=best), "verdict": "match"}
    miss_txt = (", " if _lang() == "de" else ", ").join(_lbl(f"su_miss_{side}_{'cloudy' if o == 'overcast' else 'sunny'}") for side, o in misses)
    key = "su_contra" if len(misses) == len(judged) else "su_partial"
    return {"fazit": expect + _lbl(key).format(models=_model_words(), zones=zones_txt, best=best, miss=miss_txt),
            "verdict": "contra" if key == "su_contra" else "partial"}


def _sonne_numbers(wetterlage: dict, date: str) -> dict:
    wl = wetterlage or {}
    tz = ((_per_day_index(wl.get("thermik_zonen"), [date]).get(date) or {}).get("zones") or {})
    zones = {z: v for z, v in tz.items() if v and v.get("sun_share") is not None}
    if not zones:
        return {}
    return {
        "lbl_sun": _lbl("su_lbl_sun"), "lbl_low": _lbl("su_lbl_low"), "lbl_high": _lbl("su_lbl_high"),
        "zones": [{"name": _zone_name(z),
                   "sun": f"{int(round(100 * (v.get('sun_share') or 0)))} %",
                   "low": (f"{int(v['low_cloud_pct'])} %" if isinstance(v.get("low_cloud_pct"), (int, float)) else "—"),
                   "high": (f"{int(v['mid_high_pct'])} %" if isinstance(v.get("mid_high_pct"), (int, float)) else "—")}
                  for z, v in zones.items()],
    }


def _thermik_numbers(wetterlage: dict, date: str) -> dict:
    """Die Zahlen zum Thermik-Block, sauber formatiert und getrennt vom
    Fliesstext: Basis-Spanne, Steig-Spanne, Beginn, dazu je Zone ein Chip."""
    wl = wetterlage or {}
    tz = ((_per_day_index(wl.get("thermik_zonen"), [date]).get(date) or {}).get("zones") or {})
    zones = {z: v for z, v in tz.items() if v}
    if not zones:
        return {}
    bases = [v["base_m"] for v in zones.values() if isinstance(v.get("base_m"), (int, float))]
    climbs = [v["climb_ms"] for v in zones.values() if isinstance(v.get("climb_ms"), (int, float))]
    starts = [v["start_hour"] for v in zones.values() if isinstance(v.get("start_hour"), int)]
    def rng(vals, fmt):
        if not vals:
            return "—"
        lo, hi = min(vals), max(vals)
        return fmt(lo) if lo == hi else f"{fmt(lo)}–{fmt(hi)}"
    return {
        "base": rng(bases, lambda v: f"{int(v)}") + " m",
        "climb": rng(climbs, lambda v: f"{v:.1f}") + " m/s",
        "start": (f"{min(starts):02d}" + _lbl("th_unit_h")) if starts else "",
        "zones": [{"name": _zone_name(z),
                   "base": (f"{int(v['base_m'])} m" if isinstance(v.get("base_m"), (int, float)) else "—"),
                   "climb": (f"{v['climb_ms']:.1f} m/s" if isinstance(v.get("climb_ms"), (int, float)) else "—")}
                  for z, v in zones.items()],
        "lbl_base": _lbl("th_lbl_base"), "lbl_climb": _lbl("th_lbl_climb"), "lbl_from": _lbl("th_lbl_from"),
    }


def _konv_by_zone(wetterlage: dict, date: str) -> dict:
    """Gewitter/Ueberentwicklung je ZONE (nicht je Region): erste Stunde.
    'Locarnese / Bellinzonese' neben 'Tessin' zu nennen, ist doppelt."""
    kv = ((_per_day_index((wetterlage or {}).get("konvektion"), [date]).get(date) or {}).get("zones") or {})
    out = {}
    for z, v in kv.items():
        th = [str(h)[:2] for _n, h in (v or {}).get("gewitter") or []]
        od = [str(h)[:2] for _n, h in (v or {}).get("ueberentwicklung") or []]
        out[z] = {"thunder_hour": min(th) if th else None, "overdev_hour": min(od) if od else None}
    return out


def _labilitaet_fazit(wetterlage: dict, date: str) -> str:
    return _labilitaet_block(wetterlage, date)["fazit"]


def _labilitaet_block(wetterlage: dict, date: str) -> dict:
    """Block 5: was die Synoptik an Labilitaet erwarten laesst (Luftmasse,
    Druck) und was die Prognosedaten zeigen (CAPE je Zone in Worten, Gewitter
    mit Beginn, Ueberentwicklung). Leer ohne Zonen-Felder. `labile` = CAPE-
    Klasse in mindestens einer Zone ohne Modell-Gewitter (Pille "teils labil")."""
    wl = wetterlage or {}
    pz = ((_per_day_index(wl.get("precip_zones"), [date]).get(date) or {}).get("zones") or {})
    kv = ((_per_day_index(wl.get("konvektion"), [date]).get(date) or {}).get("zones") or {})
    if not pz and not kv:
        return {"fazit": "", "labile": False}
    lang = _lang()
    joiner = " und " if lang == "de" else " and "
    # --- Erwartung ---
    flow = _per_day_index(wl.get("flow_overhead"), [date]).get(date) or {}
    abbr = _SECTOR_ABBR.get(flow.get("sector", ""), "")
    sector = _lbl("lg_sector_" + abbr) if abbr else ""
    if abbr in ("S", "SW", "SE"):
        air = _lbl("lb_air_humid").format(sector=sector)
    elif abbr in ("N", "NW"):
        air = _lbl("lb_air_cool").format(sector=sector)
    else:
        air = _lbl("lb_air_neutral").format(sector=sector, Sector=_capitalize(sector))
    regime, tkey = _lage_regime(wl, date)
    if regime == "hoch":
        press = _lbl("lb_press_cap").format(regime=_lbl("lb_regime_hoch"))
    elif tkey == "up":
        press = _lbl("lb_press_up")
    elif regime == "tief" or tkey == "down":
        press = _lbl("lb_press_low")
    else:
        press = _lbl("lb_press_none")
    expect = _lbl("lb_expect").format(air=air, press=press)
    # --- Daten ---
    def grade(cape):
        return ("strong" if cape >= 1000 else "mod" if cape >= 400 else "light" if cape >= 150 else None)
    labile = {z: grade(((pz.get(z) or {}).get("day") or {}).get("max_cape") or 0) for z in config.SYNOPTIC_ZONES}
    labile = {z: g for z, g in labile.items() if g}
    konv = _konv_by_zone(wl, date)
    zone_prep = (lambda z: (("am " if z == "alpennordhang" else ("im " if _ZONE_ARTICLE_DAT["de"].get(z) else "in ")) + _zone_name(z))
                 if lang == "de" else ("in " + _ZONE_ARTICLE_DAT["en"].get(z, "") + _zone_name(z)))
    thunder = [_lbl("lb_thunder_at").format(zone=zone_prep(z), hour=konv[z]["thunder_hour"])
               for z in config.SYNOPTIC_ZONES if konv.get(z, {}).get("thunder_hour")]
    # Ueberentwicklung: bei labilen Zonen in die Klammer, sonst als eigener Zusatz
    od_extra = [_lbl("lb_od_zone").format(zone=zone_prep(z), hour=konv[z]["overdev_hour"])
                for z in config.SYNOPTIC_ZONES
                if konv.get(z, {}).get("overdev_hour") and z not in labile and not konv[z].get("thunder_hour")]
    ov = (", " + ", ".join(od_extra)) if od_extra else ""
    north_capped = ("alpennordhang" not in labile and (regime == "hoch" or tkey == "up")
                    and (labile or thunder))
    north = _lbl("lb_north_capped") if north_capped else ""
    # Urteil: Erwartung (labil? gedeckelt?) gegen Daten (labil irgendwo? Norden?)
    # feuchte Suedluft UND kuehle Nord(west)luft lassen Labilitaet erwarten (Sueden bzw. Nordhang)
    expect_labile = abbr in ("S", "SW", "SE", "N", "NW") or regime == "tief" or tkey == "down"
    expect_cap = regime == "hoch" or tkey == "up"
    obs_labile = bool(thunder or labile)
    obs_north = "alpennordhang" in labile or any("Alpennordhang" in t for t in thunder)
    if expect_labile != obs_labile:
        verdict = "contra_labile" if obs_labile else "contra_stable"
    elif expect_cap and obs_north:
        verdict = "partial"
    else:
        verdict = "match" if obs_labile else "match_stable"
    if thunder:
        what = _lbl("lb_thunder").format(zones=joiner.join(thunder[:3]), overdev=ov, north=north)
    elif labile:
        top = max(labile.values(), key=lambda g: ["light", "mod", "strong"].index(g))
        def _zl(z):
            od = konv.get(z, {}).get("overdev_hour")
            return _lbl("lb_zone_grade").format(zone=zone_prep(z), grade=_lbl("lb_grade_" + labile[z]),
                                                od=_lbl("lb_od_in").format(hour=od) if od else "")
        zones = joiner.join(_zl(z) for z in labile)
        key = "lb_labile_only" if len(labile) < len(config.SYNOPTIC_ZONES) else "lb_labile_wide"
        what = _lbl(key).format(zones=zones, grade=_lbl("lb_grade_" + top), overdev=ov, north=north)
    else:
        what = _lbl("lb_stable") + (ov if ov else "")
    return {"fazit": expect + _lbl("lb_" + verdict).format(models=_model_words(), what=what),
            "labile": bool(labile) and not thunder}


# Startplatz-Boee, ab der aeltere Caches "starken Wind" nennen; im Text als Zahl
_STRONG_GUST_KMH = 40


def _foehn_fazit(wetterlage: dict, date: str) -> str:
    """Block 3: was die Synoptik zum Foehn sagt (Druckgefaelle) und ob die
    Prognosedaten es zeigen (Talpunkte bzw. Lee-Boeen). Bise bewusst nicht
    (User 12.10.2026: "Bise ist egal, wichtig ist nur Nord-/Suedfoehn").
    Leer, wenn der Kontext die Abgleich-Felder nicht hat."""
    fo = _per_day_index(wetterlage.get("foehn"), [date]).get(date) or {}
    claim, lee = fo.get("claim") or {}, fo.get("lee") or {}
    sw = _per_day_index(wetterlage.get("starkwind_punkte"), [date]).get(date) or {}
    # Vier Indikatoren (15.10.2026) vor allem anderen; aeltere Caches unten
    if isinstance(fo.get("indikatoren"), dict):
        return _foehn_indicator_text(fo["indikatoren"])
    if not claim and not sw:
        return ""
    # Neuer Block (14.10.2026): Talmerkmale beider Seiten, Druck nur als Zahl.
    # Aeltere Caches ohne `taeler` fallen auf den bisherigen Abgleich zurueck.
    if isinstance(fo.get("taeler"), dict):
        return _foehn_valley_fazit(fo, sw)
    parts = []

    # --- Foehn: Anspruch (Druckgefaelle) gegen den Wind an den Foehn-Talpunkten
    # (foehn.per_day[].tal, synoptic_context.foehn_tal_for_day) — die einzigen
    # Punkte, von denen wir wissen, dass sie im Foehntal liegen. Startplaetze
    # gelten nicht als Foehntal. Ohne Talreihe: alter Abgleich an der
    # Lee-Station + "nicht pruefbar", nie ein falsches "nicht bestaetigt".
    side = "sued" if fo.get("sued_active") else "nord" if fo.get("nord_active") else None
    tal = fo.get("tal")
    if side and tal:
        parts.append(_foehn_tal_sentence(fo, side, tal))
    elif side:
        dp = claim.get(f"delta_p_{side}_max_hpa")
        gust = lee.get("gust_nord_max_kmh" if side == "sued" else "gust_sued_max_kmh") or 0
        station = _lbl("fb_station_nord" if side == "sued" else "fb_station_sued")
        wins = fo.get(f"{side}_windows") or {}
        first = next((w for w in ("morning", "midday", "afternoon", "evening")
                      if (wins.get(w) or {}).get("hours")), None)
        windows = _lbl("fb_win_from").format(when=_lbl("hour_" + first)) if first else ""
        key = "fb_foehn_yes" if gust >= 30 else "fb_foehn_aloft"
        parts.append(_lbl(key).format(models=_model_words(), Side=_lbl("fb_side_" + side), station=station,
                                      dp=(f"{dp:.0f}" if isinstance(dp, (int, float)) else "–"),
                                      gust=int(gust), windows=windows) + _lbl("fb_foehn_tal_na"))
    else:
        dps = [v for v in (claim.get("delta_p_sued_max_hpa"), claim.get("delta_p_nord_max_hpa"))
               if isinstance(v, (int, float))]
        # Starke Winde absolut, an einzelnen Prognosepunkten — mit Richtung,
        # Hoehe, Stunde und Modell-Uneinigkeit; bewusst ohne "Foehntal"
        strong = ""
        g = sw.get("max_gust_kmh") or 0
        if sw and g >= _STRONG_GUST_KMH:
            hour = int(sw.get("hour") or 12)
            when = _lbl("hour_morning" if hour < 10 else "hour_midday" if hour < 14
                        else "hour_afternoon" if hour < 18 else "hour_evening")
            # Kein Modellvergleich in diesem Block (CH1/CH2-Differenz bleibt im
            # Feld, wird hier aber nicht genannt)
            cmp = ""
            alt = sw.get("elevation_m")
            strong = _lbl("fb_strong_some").format(
                gust=int(g), dir=(_sector_word(sw["dir_deg"]) if sw.get("dir_deg") is not None else "–"),
                spot=sw.get("spot", ""), alt=(int(alt) if isinstance(alt, (int, float)) else "–"),
                when=when, cmp=cmp, models=_model_words())
        elif sw:
            strong = _lbl("fb_strong_none").format(models=_model_words(), g=_STRONG_GUST_KMH)
        if dps:
            parts.append(_lbl("fb_foehn_no").format(dp=f"{max(dps):.0f}", strong=strong))
        else:
            parts.append(_lbl("fb_foehn_no_nodp").format(strong=strong))
    return " ".join(parts)


# Foehnrichtung des Hoehenwinds (User-Regel 14.10.2026): Suedfoehn SO–SW,
# Nordfoehn NW–NO. Bestaetigt durch die Messung am Guetsch 2026 (Kamm, 2283 m):
# Suedfoehn zu 90 % aus 130–170°, Nordfoehn aus 315–30°, Westwind 0–1 %.
# Ost-/Westwind in der Hoehe wird nur als Wind genannt, ohne Foehn-Bezug.
_ALOFT_FOEHN_SECTOR = {"nord": (315, 45), "sued": (135, 225)}


def _aloft_foehn_side(sw: dict):
    """Seite, deren Foehnrichtung der staerkste Startplatzwind hat (oder None)."""
    from foehn_indicators import dir_in_sector
    d = sw.get("dir_deg")
    if not isinstance(d, (int, float)):
        return None
    for side, (lo, hi) in _ALOFT_FOEHN_SECTOR.items():
        if dir_in_sector(d, lo, hi):
            return side
    return None


def _dir_abbr(deg) -> str:
    """Windrichtung als Kurzzeichen in der aktiven Sprache (N, NO/NE, O/E, ...)."""
    if not isinstance(deg, (int, float)):
        return ""
    keys = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    k = keys[int(((deg % 360) + 22.5) // 45) % 8]
    return _lbl("fv_dir_" + k)


def _valley_names_with_dir(tal: dict, key: str) -> str:
    """'Reusstal aus SO, Haslital aus O u. a.' — die Richtung zeigt, dass der Wind
    dem Tal folgt (Leventina: Foehn aus W). Nach Boeenspitze sortiert."""
    from foehn_talpunkte import tal_kurzname
    rows = [t for t in tal.get("taeler") or [] if t.get(key)]
    rows.sort(key=lambda t: -(t.get("gust_max_kmh") or t.get("all_gust_max_kmh") or 0))
    out, seen = [], set()
    for t in rows:
        name = tal_kurzname(t.get("tal", ""))
        if not name or name in seen:
            continue
        seen.add(name)
        d = _dir_abbr(t.get("foehn_dir_deg"))
        out.append(_lbl("fv_name_dir").format(tal=name, dir=d) if d else name)
    return ", ".join(out[:3]) + (_lbl("fb_tal_more") if len(out) > 3 else "")


def _valley_side_sentence(side: str, tal: dict) -> str:
    """Ein Satz je Foehnseite aus den Talmerkmalen — nur Messgroessen, kein Urteil."""
    from foehn_talpunkte import tal_kurzname
    lbl_side = _lbl("fv_side_" + side)
    total = tal.get("n_total", 0)
    if tal.get("n_dir_dry"):
        # EINE Grenze (User 14.10.2026): Foehnrichtung + Boeen ab 22/Wind ab 16 km/h
        # + Feuchte bis 68 %, >= 2 h — im MeteoSchweiz-Bereich (Duerr 2008: Boeen
        # 14-33 km/h je Station), Modellfehler eingerechnet; 15 km/h getestet:
        # gleiche Treffer, doppelt so viele Fehlalarme.
        counted = [e for e in tal.get("taeler") or [] if e.get("dir_dry")]
        g = max((e.get("all_gust_max_kmh") or 0) for e in counted) if counted else "–"
        return _lbl("fv_full").format(side=lbl_side, n=tal["n_dir_dry"], t=total,
                                      taeler=_valley_names_with_dir(tal, "dir_dry"), g=g)
    return _lbl("fv_none").format(side=lbl_side, t=total, w=tal.get("all_wind_max_kmh", "–"),
                                  wmin=_tal_wmin(), g=tal.get("all_gust_max_kmh", "–"),
                                  gtal=tal_kurzname(tal.get("all_gust_tal", "")),
                                  rh=tal.get("rh_min_pct", "–"))


def _spot_kurz(name: str) -> str:
    """'Carì, Lago di Pro da Lèi' -> 'Carì' (Text kurz halten)."""
    return (name or "").split(",")[0].strip()


def _tal_wmin() -> int:
    from foehn_indicators import TAL_WIND_WEAK_KMH
    return TAL_WIND_WEAK_KMH


def _valley_quiet(tal) -> bool:
    return bool(tal) and not tal.get("n_bestaetigt") and not tal.get("n_dir_dry")


def _foehn_valley_fazit(fo: dict, sw: dict) -> str:
    """Block 3 (ab 14.10.2026): was die Foehntaeler beider Seiten zeigen
    (Richtung, Wind, Feuchte), der staerkste Wind in der Hoehe und der
    Druckunterschied als Zahl. Nie "Foehn" oder "kein Foehn" als Tatsache,
    keine Druckschwelle als Urteil (Blog wetterkunde/foehn)."""
    from foehn_talpunkte import tal_kurzname
    taeler = fo.get("taeler") or {}
    sued, nord = taeler.get("sued"), taeler.get("nord")
    sides = [(s, t) for s, t in (("sued", sued), ("nord", nord)) if t]
    missing = [s for s, t in (("sued", sued), ("nord", nord)) if not t]
    parts = []
    if not sides:
        parts.append(_lbl("fv_na"))
    elif all(_valley_quiet(t) for _, t in sides) and len(sides) == 2:
        # Beide Seiten ruhig: ein Satz mit den Landeswerten
        tot = sum(t.get("n_total", 0) for _, t in sides)
        top = max(sides, key=lambda st: st[1].get("all_gust_max_kmh") or 0)[1]
        rh = min((t.get("rh_min_pct") for _, t in sides if t.get("rh_min_pct") is not None), default="–")
        parts.append(_lbl("fv_both_none").format(
            t=tot, wmin=_tal_wmin(), w=max(t.get("all_wind_max_kmh") or 0 for _, t in sides),
            g=top.get("all_gust_max_kmh", "–"), gtal=tal_kurzname(top.get("all_gust_tal", "")), rh=rh))
    else:
        active = any(not _valley_quiet(t) for _, t in sides)
        for side, t in sides:
            if active and _valley_quiet(t):
                parts.append(_lbl("fv_none_short").format(side=_lbl("fv_side_" + side),
                                                          t=t.get("n_total", 0),
                                                          w=t.get("all_wind_max_kmh", "–")))
            else:
                parts.append(_valley_side_sentence(side, t))
    if sides:
        # Fehlt eine Seite (Talpunkte ohne Daten): offen sagen, nie weglassen
        parts.extend(_lbl("fv_side_na").format(side=_lbl("fv_side_" + s)) for s in missing)
    g = sw.get("max_gust_kmh") or 0
    if sw and g >= 40:
        hour = int(sw.get("hour") or 12)
        when = _lbl("hour_morning" if hour < 10 else "hour_midday" if hour < 14
                    else "hour_afternoon" if hour < 18 else "hour_evening")
        alt = sw.get("elevation_m")
        line = _lbl("fv_aloft").format(
            g=int(g), dir=(_sector_word(sw["dir_deg"]) if sw.get("dir_deg") is not None else "–"),
            spot=_spot_kurz(sw.get("spot", "")), alt=(int(alt) if isinstance(alt, (int, float)) else "–"),
            when=when)
        parts.append(line)
    claim = fo.get("claim") or {}
    dps = [v for v in (claim.get("delta_p_sued_max_hpa"), claim.get("delta_p_nord_max_hpa"))
           if isinstance(v, (int, float))]
    return " ".join(parts)


def _foehn_valley_reading(fo: dict, sw: dict) -> str:
    """Einordnung zum Foehn-Block: EIN fester Satz je Datenlage, was das Muster
    ueblicherweise bedeutet — mit Grenze, nie ein Urteil ueber den Tag.
    Reihenfolge = Gewicht: Talmuster > Foehn ueber Kaltluftsee > Richtung+trocken
    > grosser Druckunterschied > ruhig. Ohne Taldaten: leer."""
    taeler = fo.get("taeler") or {}
    sides = [t for t in (taeler.get("sued"), taeler.get("nord")) if t]
    if not sides:
        return ""
    if any(t.get("n_dir_dry") for t in sides):
        return _lbl("fvr_full")
    g = sw.get("max_gust_kmh") or 0
    aside = _aloft_foehn_side(sw) if g >= 40 else None
    if aside and _valley_quiet(taeler.get(aside)):
        return _lbl("fvr_pool")
    claim = fo.get("claim") or {}
    dps = [v for v in (claim.get("delta_p_sued_max_hpa"), claim.get("delta_p_nord_max_hpa"))
           if isinstance(v, (int, float))]
    if dps and max(dps) >= 8:
        return _lbl("fvr_dp_high")
    return _lbl("fvr_quiet")


def _foehn_reading(wetterlage: dict, date: str) -> str:
    fo = _per_day_index(wetterlage.get("foehn"), [date]).get(date) or {}
    if isinstance(fo.get("indikatoren"), dict) or not isinstance(fo.get("taeler"), dict):
        return ""
    sw = _per_day_index(wetterlage.get("starkwind_punkte"), [date]).get(date) or {}
    return _foehn_valley_reading(fo, sw)


def _foehn_legend(fo: dict) -> str:
    """Legende zum Foehn-Block: wann ein Tal mitgezaehlt wird — Zahlen aus den
    Konstanten (eine Quelle mit der Regel), nie von Hand nachgetragen."""
    from foehn_indicators import TAL_MIN_HOURS, TAL_WIND_WEAK_KMH, TAL_GUST_WEAK_KMH, TAL_RH_WEAK
    taeler = fo.get("taeler") or {}
    sides = [t for t in (taeler.get("sued"), taeler.get("nord")) if t]
    if not sides:
        return ""
    model = _model_short(next((t.get("model") for t in sides if t.get("model")), ""))
    from foehn_talpunkte import load_talpunkte
    gemessen = sum(1 for p in load_talpunkte() if p.get("sektor"))
    return _lbl("fvr_legend").format(model=model, h=TAL_MIN_HOURS, h0=config.FLIGHT_HOURS_START,
                                     h1=config.FLIGHT_HOURS_END, w=TAL_WIND_WEAK_KMH, g=TAL_GUST_WEAK_KMH,
                                     rh=TAL_RH_WEAK, n=sum(t.get("n_total", 0) for t in sides), m=gemessen)


def _foehn_legend_for(wetterlage: dict, date: str) -> str:
    fo = _per_day_index(wetterlage.get("foehn"), [date]).get(date) or {}
    if isinstance(fo.get("indikatoren"), dict):
        return ""          # Zaehlregel steht auf der Erklaerseite (/foehn)
    return _foehn_legend(fo) if isinstance(fo.get("taeler"), dict) else ""


def _foehn_guide_url() -> str:
    """Blog-Artikel 'Foehn' als Lesehilfe in der Sprache des Briefings
    (Webseite: Deutsch ohne Praefix, andere Sprachen unter /<lang>/)."""
    import i18n
    lang = i18n.get_current_lang()
    prefix = "" if lang == "de" else f"/{lang}"
    return config.MARKETING_URL.rstrip("/") + prefix + "/wetterkunde/foehn"


def _foehn_valley_status(fo: dict, sw: dict):
    """Pille + Kennzahlen zum neuen Block — dieselben Zahlen wie der Satz."""
    taeler = fo.get("taeler") or {}
    sides = [t for t in (taeler.get("sued"), taeler.get("nord")) if t]
    tot = sum(t.get("n_total", 0) for t in sides)
    full = sum(t.get("n_bestaetigt", 0) for t in sides)
    dirdry = sum(t.get("n_dir_dry", 0) for t in sides)
    claim = fo.get("claim") or {}
    dps = [v for v in (claim.get("delta_p_sued_max_hpa"), claim.get("delta_p_nord_max_hpa"))
           if isinstance(v, (int, float))]
    dp = max(dps) if dps else None
    g = sw.get("max_gust_kmh") or 0
    aside = _aloft_foehn_side(sw) if g >= 40 else None
    if dirdry:
        kind, label = "warn", _lbl("fvs_full").format(n=dirdry, t=tot)
    elif aside and _valley_quiet(taeler.get(aside)):
        kind, label = "info", _lbl("fvs_aloft").format(g=int(g))
    elif dp is not None and dp >= 8:
        kind, label = "info", _lbl("fvs_dp").format(dp=f"{dp:.0f}")
    else:
        # Neutral statt "ok"/gruen: Gruen wirkt wie eine Entwarnung (Recherche
        # 14.10.2026, SHV: Schweigen/Entwarnung bei seichtem Foehn = Unfallmuster)
        kind, label = "neutral", _lbl("fvs_none").format(t=tot)
    rh = min((t.get("rh_min_pct") for t in sides if t.get("rh_min_pct") is not None), default=None)
    facts = [{"k": _lbl("fx_dp"), "v": (f"{dp:.0f} hPa" if dp is not None else "—")}]
    if rh is not None:
        facts.append({"k": _lbl("fx_rh"), "v": f"{rh} %"})
    if g >= 40:
        facts.append({"k": _lbl("fx_gust_aloft"), "v": f"{int(g)} km/h {_dir_abbr(sw.get('dir_deg'))}".strip()})
    return kind, label, facts


def _fi_join(parts: list) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + _lbl("fi_and") + parts[-1]


def _fi_cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _fi_models(*inds) -> str:
    """Anzeigenamen der Modelle hinter den Indikatoren ("ICON-D2", "ICON-CH2"), in
    Reihenfolge, ohne Doppel; ohne Angabe (aeltere Caches) "den Daten"."""
    from engine.synoptic_context import MODEL_COMPARE_MODELS as names
    out = []
    for x in inds:
        m = (x or {}).get("model")
        for mid in (m if isinstance(m, list) else [m] if m else []):
            nm = names.get(mid, mid)
            if nm not in out:
                out.append(nm)
    return "/".join(out) if out else _lbl("fd_model_x")


def _fi_ab(*hours) -> str:
    """' ab etwa 10 Uhr' / ' from about 10:00' — fruehestes Zeichen, sonst leer."""
    hs = [h for h in hours if h is not None]
    if not hs:
        return ""
    # Vor dem Flugfenster schauen die Indikatoren nicht hin: erste Flugstunde = "bereits"
    key = "fd_ab_start" if min(hs) <= config.FLIGHT_HOURS_START else "fd_ab"
    return _lbl(key).format(t=_fz_time(min(hs)))


def _foehn_indicator_text(ind: dict) -> str:
    """Block 3 (ab 15.10.2026): Deutung unter den vier Indikator-Labels.

    Ein Satz, Modell und Uhrzeit nur einmal (User 24.10.2026): "ICON-CH1/ICON-D2 show a
    pressure difference pointing to north foehn already at 06:00, together with a cooler
    north side aloft, and from about 07:00 in the wind: …, from about 09:00 also …".
    Eine spätere Uhrzeit nur, wenn ein Zeichen erst später dazukommt. Zeichen beim Namen
    der Labels, Zahlen nur in den Labels. Modelle zusammen wie bei den Fronten (Boden
    ICON-CH, Höhentemperatur ICON-D2). Kein Mechanismus, keine Wertungswoerter."""
    from foehn_talpunkte import tal_kurzname
    va, wk, dp, tp = (ind.get(k) or None for k in ("valleys", "wind_map", "pressure", "luv_cooler"))
    obj = {"dp": dp, "tp": tp, "map": wk, "val": va}
    on = {k: bool(x and x.get("on")) for k, x in obj.items()}
    against = {k: bool(x and x.get("against")) for k, x in obj.items()}
    # Foehnseite des Tages aus evaluate_indicators (Mehrheit der Zeichen);
    # Zeichen der Gegenseite stehen als "Dagegen:" im Text, nie als Treffer
    side = ind.get("side") or (dp or {}).get("high_side") or "sued"
    luv = _lbl("fd_luv_" + side)
    foehn = _lbl("fd_foehn_" + side)
    # Bodenmodelle zuerst, dann das Höhenmodell — wie "ICON-CH1/ICON-D2" bei den Fronten
    models = _fi_models(dp, wk, va, tp)

    def hour(k):
        return (obj[k] or {}).get("from_hour")

    def folge(items, start=None):
        """'A, ab etwa 09 Uhr auch B und C' — Uhrzeit nur, wenn ein Zeichen später kommt.
        items: [(Stunde, Text)] nach Uhrzeit; start: Uhrzeit, die schon genannt ist."""
        out, prev = "", start
        for i, (h, txt) in enumerate(items):
            if i == 0:          # die Uhrzeit des ersten Zeichens steht im Satzkopf
                out, prev = txt, (h if h is not None else prev)
            elif h is None or prev is None or h <= prev:
                out += _lbl("fi_and") + txt
            else:
                out += _lbl("fd_seq_later").format(ab=_fi_ab(h), item=txt)
                prev = h
        return out

    def ab_wenn_spaeter(h, schon):
        return "" if h is None or (schon is not None and h <= schon) else _fi_ab(h)

    # Zeichen im Wind (Windkarte, Täler), nach Uhrzeit
    wind = []
    if on["map"]:
        names = _fi_join(list(wk.get("regions") or [])[:2])
        wind.append((hour("map"), _lbl("fd_m_map") + (_lbl("fd_i_map_wo").format(names=names) if names else "")))
    if on["val"]:
        top = tal_kurzname(((va.get("top") or {}).get("tal")) or "")
        wind.append((hour("val"), _lbl("fd_m_val") + (_lbl("fd_i_val_wo").format(name=top) if top else "")
                     if va["n"] > 1 else _lbl("fd_i_val_1").format(name=top)))
    wind.sort(key=lambda x: 99 if x[0] is None else x[0])
    tp_item = (hour("tp"), _lbl("fd_m_tp").format(luv=luv)) if on["tp"] else None

    # 1 Übergeordnetes Bild zuerst (wie die DWD-Karte bei den Fronten): der Druckunterschied
    out, h_dp = "", hour("dp")
    if dp:
        out = (_lbl("fd_p_on").format(m=models, foehn=_lbl("fd_foehn_" + dp["high_side"]), ab=_fi_ab(h_dp))
               if (on["dp"] or against["dp"]) else _lbl("fd_p_off").format(m=models))
    if not any(on.values()):
        return (out + _lbl("fd_s_none") + _fi_against(ind, luv) + _lbl("fd_r_none")).strip()

    # 2 Zeigen die Daten Föhnzeichen? Nach Uhrzeit; eine Uhrzeit nur, wenn später als der Druck
    items = sorted(([tp_item] if tp_item else []) + wind, key=lambda x: 99 if x[0] is None else x[0])
    schon = h_dp if (on["dp"] or against["dp"]) else None
    if items:
        key = ("fd_s_also" if on["dp"] else "fd_s_other" if against["dp"] else "fd_s_still" if dp else "fd_signs")
        out += _lbl(key).format(m=models, foehn=foehn, ab=ab_wenn_spaeter(items[0][0], schon),
                                seq=folge(items, start=schon))

    # Was fehlt (wie die Frontzeichen: "Not in the data")
    missing = [_lbl("fd_m_" + k).format(luv=luv) for k in ("tp", "map", "val") if not on[k] and not against[k]]
    if missing:
        out += _lbl("fd_absent").format(liste=_fi_join(missing))
    out += _fi_against(ind, luv)
    local = on["val"] and not (on["dp"] or on["tp"] or on["map"])
    out += _lbl("fd_r_inner") if local else "" if on["val"] else _lbl("fd_r_weak")
    return out.strip()


def _fi_against(ind: dict, luv: str) -> str:
    """' Against it: …' — Zeichen der Gegenseite (der Druck steht schon in Satz 1)."""
    va, wk, tp = ind.get("valleys"), ind.get("wind_map"), ind.get("luv_cooler")
    ag = []
    if wk and wk.get("against"):
        ag.append(_lbl("fd_ag_map").format(dirw=_lbl("fi_dirw_" + wk["side"])))
    if tp and tp.get("against"):
        ag.append(_lbl("fd_ag_tp").format(luv=luv))
    if va and va.get("against"):
        ag.append(_lbl("fd_ag_val"))
    return _lbl("fd_against").format(liste=_fi_join(ag)) if ag else ""


def _foehn_indicator_status(ind: dict):
    """Pille + vier Labels (on = Indikator erfuellt). Taeler oder >= 3 Indikatoren:
    warn; 1-2 ohne Taeler: info; 0: neutral (nie gruen = keine Entwarnung).
    Wind-Labels mit der Mittelwind-Grenze (User 25.10.2026: "Regions with north wind
    ≥30 km/h"); die Böen-Grenzen stehen auf /foehn."""
    import foehn_indicators as fi
    n = ind.get("n_on", 0)
    va = ind.get("valleys") or {}
    kind = "warn" if (va.get("on") or n >= 3) else "info" if n else "neutral"
    dp, wk, tp = ind.get("pressure"), ind.get("wind_map"), ind.get("luv_cooler")
    # Richtung im Label wie die Luv-Seite (User 24.10.2026): "Regions with north wind";
    # die Windkarte nennt ihre eigene Seite nur, wenn sie Regionen zaehlt (auch dagegen) —
    # bei 0 Regionen waehlt sie Sued, das Label folgt dann der Foehnseite des Tages
    side = ind.get("side") or "sued"
    dirw = {s: _lbl("fi_dirw_" + s) for s in ("sued", "nord")}
    wk = wk or None
    map_side = wk["side"] if wk and (wk.get("on") or wk.get("against")) else side
    ps = ((wk or {}).get("per_side") or {}).get(map_side)
    map_nt = ({"n": ps["n"], "t": ps["total"]} if ps else
              {"n": (wk or {}).get("n", 0), "t": (wk or {}).get("total", 0)})   # aeltere Caches
    facts = [{"k": _lbl("fi_k_dp"), "on": bool(dp and dp["on"]),
              "v": (_lbl("fi_v_dp").format(dp=f"{dp['hpa']:.0f}", side=_lbl("fi_hi_" + dp["high_side"]))
                    if dp else "—")},
             {"k": _lbl("fi_k_map").format(dirw=dirw[map_side], kmh=fi.KARTE_WIND_KMH), "on": bool(wk and wk["on"]),
              "v": (_lbl("fi_v_map").format(**map_nt) if wk else "—")}]
    if tp:
        k = tp["cooler_k"]
        v = (_lbl("fi_v_equal") if abs(k) < 0.5 else
             _lbl("fi_v_cooler").format(k=f"{k:.1f}") if k > 0 else _lbl("fi_v_warmer").format(k=f"{-k:.1f}"))
        facts.append({"k": _lbl("fi_k_luv_" + tp["side"]), "v": v, "on": tp["on"]})
    else:
        facts.append({"k": _lbl("fi_k_luv_" + side), "v": "—", "on": False})
    facts.append({"k": _lbl("fi_k_val").format(dirw=dirw[side], kmh=fi.TAL_WIND_WEAK_KMH), "on": bool(va.get("on")),
                  "v": (_lbl("fi_v_val").format(n=va.get("n", 0), t=va.get("total", 0)) if va else "—")})
    # Kurze Labels ohne Uhrzeit (User 24.10.2026): die Uhrzeiten stehen im Text,
    # die Grenzen auf der Erklaerseite /foehn; nur die Pille nennt das frueheste Zeichen
    pill = _lbl("fi_pill").format(n=n)
    if n and ind.get("from_hour") is not None:
        pill += _lbl("fz_pill_from").format(t=_fz_time(ind["from_hour"]))
    return kind, pill, facts


def _foehn_indicators_for(wetterlage: dict, date: str):
    fo = _per_day_index(wetterlage.get("foehn"), [date]).get(date) or {}
    ind = fo.get("indikatoren")
    return ind if isinstance(ind, dict) else None


def _foehn_explain_url() -> str:
    """Erklaerseite 'So zaehlen wir' (App, /foehn) in der Sprache des Briefings."""
    import i18n
    lang = i18n.get_current_lang()
    return config.BASE_URL.rstrip("/") + "/foehn" + ("" if lang == "de" else f"?lang={lang}")


def _foehn_facts_legacy(chain: dict, fo: dict, sw: dict, dps: list) -> None:
    """Kennzahlen des alten Foehn-Blocks (Caches ohne `taeler`)."""
    chain["foehn"]["facts"] = [
        {"k": _lbl("fx_dp"), "v": (f"{max(dps):.0f} hPa" if dps else "—")},
        {"k": _lbl("fx_gust"), "v": (f"{int(sw['max_gust_kmh'])} km/h" if sw.get("max_gust_kmh") else "—")},
    ]
    if fo.get("sued_active") or fo.get("nord_active"):
        # Foehnlage: Talwerte statt Starkwind-Boe (andere Groesse, jede Richtung) —
        # eine Zahl, eine Quelle mit Satz und Warnbox
        tal = fo.get("tal")
        facts = chain["foehn"]["facts"][:1]
        if tal:
            facts.append({"k": _lbl("fx_tal"), "v": f"{tal.get('n_bestaetigt', 0)}/{tal.get('n_total', 0)}"})
            if tal.get("n_bestaetigt"):
                facts.append({"k": _lbl("fx_gust"), "v": f"{tal['gust_max_kmh']} km/h"})
        else:
            facts.append({"k": _lbl("fx_tal"), "v": _lbl("fx_tal_na")})
        chain["foehn"]["facts"] = facts


def _model_short(model_id) -> str:
    """Anzeigename; seit 24.10.2026 auch Listen (ICON-CH1, dann ICON-CH2) -> "ICON-CH1/ICON-CH2"."""
    from engine.synoptic_context import MODEL_COMPARE_MODELS as names
    if isinstance(model_id, list):
        return "/".join(names.get(m, m) for m in model_id) or "ICON"
    return names.get(model_id, model_id or "ICON")


def _tal_when(hour) -> str:
    """', ab Mittag' aus der ersten Foehnstunde (gleiche Fenster wie die Synoptik)."""
    for wname, lo, hi in config.SYNOPTIC_DAY_WINDOWS:
        if isinstance(hour, int) and lo <= hour < hi:
            return ", " + _lbl("from_" + wname)
    return ""


def _foehn_tal_sentence(fo: dict, side: str, tal: dict) -> str:
    """Block-3-Satz aus den Talwerten — dieselben Zahlen wie Chips und Warnbox."""
    from foehn_talpunkte import tal_kurzname, tal_namen
    dp = (fo.get("claim") or {}).get(f"delta_p_{side}_max_hpa")
    dp_txt = f"{dp:.0f}" if isinstance(dp, (int, float)) else "–"
    model = _model_short(tal.get("model"))
    if tal.get("n_bestaetigt"):
        names = tal_namen(tal)
        taeler = ", ".join(names[:3]) + (_lbl("fb_tal_more") if len(names) > 3 else "")
        return _lbl("fb_foehn_tal_yes").format(
            Side=_lbl("fb_side_" + side), dp=dp_txt, model=model, taeler=taeler,
            w1=tal["wind_min_kmh"], w2=tal["wind_max_kmh"], dir=_lbl("fb_dir_" + side),
            g=tal["gust_max_kmh"], gtal=tal_kurzname(tal.get("gust_tal", "")),
            when=_tal_when(tal.get("first_hour")))
    return _lbl("fb_foehn_tal_no").format(Side=_lbl("fb_side_" + side), side=_lbl("fb_dir_" + side), dp=dp_txt,
                                          tal_wind=_tal_wind_text(tal))


def _tal_wind_text(tal: dict) -> str:
    """Talwind ohne Foehnstunden: Hoechstwind/-boe in den Foehntaelern und was
    die Windstaerke sagt — nie "kein Foehn" (User 12.10.2026). Derselbe Satz in
    Block 3 und Warnbox (eine Zahl, eine Quelle). Aeltere Daten ohne die
    Hoechstwerte: Satz ohne Zahl."""
    from foehn_talpunkte import tal_kurzname
    args = dict(n=tal.get("n_total", 0), model=_model_short(tal.get("model")))
    if tal.get("all_gust_max_kmh") is None:
        return _lbl("fb_tal_nonum").format(**args)
    return _lbl("fb_tal_weak" if tal.get("all_weak") else "fb_tal_strong").format(
        w=tal["all_wind_max_kmh"], g=tal["all_gust_max_kmh"],
        gtal=tal_kurzname(tal.get("all_gust_tal", "")), **args)


def _foehn_text(wetterlage: dict, date: str) -> str:
    fo = _per_day_index(wetterlage.get("foehn"), [date]).get(date) or {}
    parts = []
    for side, key in (("north", "nord"), ("south", "sued")):
        if fo.get(f"{key}_active"):
            peak = fo.get(f"peak_{key}", "")
            level = _lbl("level_danger") if peak == "danger" else _lbl("level_caution")
            parts.append(_lbl("foehn_line").format(side=_lbl(side), level=level,
                                                   h=fo.get(f"{key}_hours", 0)))
    return " ".join(parts) if parts else _lbl("foehn_none")


def _ground_estimate(speed_txt: str) -> str:
    m = re.match(r"(\d+)", speed_txt or "")
    if not m:
        return ""
    return f"{int(round(int(m.group(1)) * 2 / 3 / 5) * 5)} km/h"


def _week_line(wetterlage: dict, days: list) -> str:
    """Ein kompakter Satz ueber alle Tage, aus den Daten gebaut:
    'Heute Regen, Nordfoehn · Do trocken, ruhig · Fr Hochdruck, trocken.'"""
    dates = [d.get("date", "") for d in days]
    press = _per_day_index(wetterlage.get("pressure_influence"), dates)
    flow = _per_day_index(wetterlage.get("flow_overhead"), dates)
    foehn = _per_day_index(wetterlage.get("foehn"), dates)
    precip = _per_day_index(wetterlage.get("precip_pattern"), dates)
    parts = []
    for d in days:
        date = d.get("date", "")
        words = []
        pr = precip.get(date) or {}
        wet = max(float((pr.get("alpennord") or {}).get("wet_share") or 0),
                  float((pr.get("alpensued") or {}).get("wet_share") or 0))
        if wet >= 0.5:
            words.append(_lbl("wl_rain"))
        regime = ((press.get(date) or {}).get("regime") or "").lower()
        if regime.startswith("hoch"):
            words.append(_lbl("wl_high"))
        elif regime.startswith("tief"):
            words.append(_lbl("wl_low"))
        if wet < 0.5 and not regime.startswith("hoch"):
            words.append(_lbl("wl_dry"))
        fo = foehn.get(date) or {}
        tv = fo.get("taeler") or {}
        if fo.get("nord_active") or (tv.get("nord") or {}).get("n_dir_dry"):
            words.append(_lbl("wl_foehn_n"))
        if fo.get("sued_active") or (tv.get("sued") or {}).get("n_dir_dry"):
            words.append(_lbl("wl_foehn_s"))
        strength = (flow.get(date) or {}).get("strength", "")
        if strength in ("kraeftig", "stuermisch"):
            words.append(_lbl("wl_windy"))
        elif not fo.get("nord_active") and not fo.get("sued_active") and wet < 0.5:
            words.append(_lbl("wl_calm"))
        parts.append(f"{_day_name(d)} {', '.join(words[:3])}")
    return " · ".join(parts) + "." if parts else ""


def _chain(wetterlage: dict, dates: list, date: str, fronts, passagen) -> dict:
    chain = _chain_raw(wetterlage, dates, date, fronts, passagen)
    _decorate_chain(chain, wetterlage, date)
    return chain


# --- Fronten-Block nach Zeichen (17.10.2026) ---------------------------------
# Mittelpunkte der vier Zonen fuer die Zugrichtung (nur aus der DWD-Frontlinie;
# die Richtung aus den Modellzeichen ist ungeprueft und bleibt aus)
_FZ_ZONE_POS = {"tessin": (46.2, 8.9), "alpennordhang": (46.9, 8.2), "wallis": (46.2, 7.5),
                "graubuenden_engadin": (46.7, 9.8)}
_FZ_DAYPART = (5, 8, 11, 14, 18, 22, 24)


def _fz_time(h: int) -> str:
    return _lbl("fz_time").format(h=f"{int(h):02d}")


def _fz_daypart(h: int) -> str:
    return _lbl("fz_dp_" + str(next(i for i, lim in enumerate(_FZ_DAYPART) if h < lim)))


def _fz_direction(zone_hours: dict) -> str:
    """', spreading from north to south' aus den Zonen-Stunden der DWD-Frontlinie;
    leer bei weniger als 2 Zonen oder weniger als 2 h Abstand."""
    hours = {z: h for z, h in (zone_hours or {}).items() if z in _FZ_ZONE_POS}
    if len(hours) < 2:
        return ""
    t0, t1 = min(hours.values()), max(hours.values())
    if t1 - t0 < 2:
        return ""
    early = [_FZ_ZONE_POS[z] for z, h in hours.items() if h - t0 < 2]
    late = [_FZ_ZONE_POS[z] for z, h in hours.items() if t1 - h < 2]
    la1, lo1 = sum(p[0] for p in early) / len(early), sum(p[1] for p in early) / len(early)
    la2, lo2 = sum(p[0] for p in late) / len(late), sum(p[1] for p in late) / len(late)
    dy, dx = la2 - la1, (lo2 - lo1) * 0.69
    if abs(dy) >= abs(dx):
        a, b = ("S", "N") if dy > 0 else ("N", "S")
    else:
        a, b = ("W", "E") if dx > 0 else ("E", "W")
    return _lbl("fz_move").format(a=_lbl("fz_dir_" + a), b=_lbl("fz_dir_" + b))


def _front_signs_zones(wetterlage: dict, date: str):
    fz = (wetterlage or {}).get("front_zeichen") or {}
    day = next((d for d in fz.get("per_day") or [] if d.get("date") == date), None)
    return (day or {}).get("zones") if day else None


def _front_signs_block(fb: dict, zones: dict):
    """(Status, Pille, Chips, Text) des Fronten-Blocks: zuerst was die DWD-Karte zeigt
    (ohne Uhrzeit), dann die Modellzeichen mit Tageszeit. Jedes Label kommt im Text
    vor; nie "die Front kommt" (User 16./17.10.2026)."""
    from front_indicators import evaluate_front_signs
    # Ohne Front auf der DWD-Karte nur dieser Satz — einzelne Modellzeichen sind dann
    # keine Frontzeichen (User 19.10.2026). Grau statt gruen: keine Entwarnung.
    if not fb.get("dwd"):
        return "neutral", _lbl("fz_pill_none"), [], _lbl("fz_dwd_no")
    dwd = {"typ": fb.get("dwd_typ"), "zone_hours": fb.get("dwd_zone_hours")}
    ev = evaluate_front_signs(zones, dwd)
    typ, keys, first = ev["typ"], ev["keys"], ev["first"]
    carried, counted = set(ev["carried"]), set(ev["counted"])
    typ_w = _lbl("fz_typ_" + typ)
    n = ev["n_on"]
    pill = _lbl("fz_pill").format(n=n)
    if ev["from_hour"] is not None:
        pill += _lbl("fz_pill_from").format(t=_fz_time(ev["from_hour"]))
    facts = []
    for k in keys:
        if k == "dwd":
            v = typ_w[:1].upper() + typ_w[1:]
        elif first[k] is None:
            v = "—"
        else:
            v = "~" + _fz_time(first[k]) + (_lbl("fz_carried_v") if k in carried else "")
        facts.append({"k": _lbl("fz_k_" + k), "v": v, "on": k in counted})
    kind = "warn" if n >= 3 else "info" if n else "neutral"

    def names(ks):
        return _fi_join([_lbl("fz_x_" + k) for k in ks])

    model = [k for k in keys if k != "dwd"]
    shown = sorted((k for k in model if k in counted), key=lambda k: first[k])
    groups = []                     # gleiche Tageszeit zusammenfassen
    for k in shown:
        dp = _fz_daypart(first[k])
        if groups and groups[-1][0] == dp:
            groups[-1][1].append(k)
        else:
            groups.append((dp, [k]))
    det = [(f"{dp} {names(ks)}" if _lang() == "de" else f"{names(ks)} {dp}") for dp, ks in groups]
    det_txt = _fi_join(det)
    models = _model_words()
    move = _fz_direction(ev["dwd_zone_hours"])
    t = _fz_time(first[shown[0]]) if shown else ""
    txt = _lbl("fz_dwd_yes").format(typ=typ_w)
    txt += (_lbl("fz_match").format(models=models, t=t, move=move, det=det_txt) if shown
            else _lbl("fz_nomatch").format(models=models))
    absent = [k for k in model if first[k] is None]
    if absent:
        txt += _lbl("fz_absent").format(liste=names(absent))
    if carried:
        txt += _lbl("fz_carried").format(liste=names([k for k in model if k in carried]))
    return kind, pill, facts, txt


def _decorate_chain(chain: dict, wetterlage: dict, date: str) -> None:
    """Status-Pille (ok / info / warn + Kurzlabel) und Fakten-Chips je Block —
    die visuelle Schicht ueber den Saetzen. Alles aus Feldern, die die Bloecke
    schon tragen; kein neuer Datenzugriff."""
    wl = wetterlage or {}

    def st(block, kind, label_key):
        chain[block]["status"] = kind
        chain[block]["status_label"] = _lbl(label_key)

    # Lage: Status, Pille und Chips setzt schon _lage_block (vier Indikatoren)
    # Fronten
    passed = bool(chain["fronts"].get("rear"))
    dwd_typ = chain["fronts"].get("dwd_typ") or ""
    zst = chain["fronts"].get("zeichen")
    if chain["fronts"].get("dwd"):
        st("fronts", *{"deutlich": ("warn", "st_front_signs"),
                       "schwach": ("info", "st_front_weaksigns")}.get(zst, ("info", "st_front_nosigns")))
    elif chain["fronts"].get("ohne_dwd"):
        st("fronts", "warn", "st_front_airmass")
    elif passed:
        st("fronts", "info", "st_front_rear")
    else:
        st("fronts", "ok", "st_front_none")
    fo = _per_day_index(wl.get("foehn"), [date]).get(date) or {}
    sw = _per_day_index(wl.get("starkwind_punkte"), [date]).get(date) or {}
    chain["fronts"]["facts"] = [
        {"k": _lbl("fx_dwd"), "v": (_front_type(dwd_typ) if dwd_typ else "—")},
        {"k": _lbl("fx_signature"), "v": _lbl("fx_sig_" + zst) if zst else _lbl("fx_sig_no")},
    ]
    # Neuer Fronten-Block nach Zeichen (17.10.2026); aeltere Caches ohne
    # `front_zeichen` behalten Satz, Pille und Chips von oben
    fz_zones = _front_signs_zones(wl, date)
    if fz_zones is not None:
        kind, pill, facts, txt = _front_signs_block(chain["fronts"], fz_zones)
        chain["fronts"].update(status=kind, status_label=pill, facts=facts, fazit=txt)
    # Foehn — vier Indikatoren (15.10.2026), sonst Talmerkmale (14.10.2026)
    if isinstance(fo.get("indikatoren"), dict):
        kind, label, facts = _foehn_indicator_status(fo["indikatoren"])
        chain["foehn"]["status"] = kind
        chain["foehn"]["status_label"] = label
    elif isinstance(fo.get("taeler"), dict):
        kind, label, facts = _foehn_valley_status(fo, sw)
        chain["foehn"]["status"] = kind
        chain["foehn"]["status_label"] = label
    elif fo.get("sued_active") or fo.get("nord_active"):
        st("foehn", "warn", "st_foehn_on")
    elif (sw.get("max_gust_kmh") or 0) >= _STRONG_GUST_KMH:
        st("foehn", "info", "st_foehn_gusty")
    else:
        st("foehn", "ok", "st_foehn_off")
    claim = fo.get("claim") or {}
    dps = [v for v in (claim.get("delta_p_sued_max_hpa"), claim.get("delta_p_nord_max_hpa")) if isinstance(v, (int, float))]
    if isinstance(fo.get("indikatoren"), dict) or isinstance(fo.get("taeler"), dict):
        chain["foehn"]["facts"] = facts
    else:
        _foehn_facts_legacy(chain, fo, sw, dps)
    # Hoehenwind
    w = chain["wind"]
    st("wind", {"stronger": "warn", "weaker": "info"}.get(w.get("verdict"), "ok"), "st_wind_" + (w.get("verdict") or "match"))
    w["facts"] = [f for f in [
        {"k": "700 hPa", "v": f"{w.get('arrow', '')} {w.get('sector', '')} {w.get('range') or w.get('speed') or ''}".strip()},
        {"k": _lbl("fx_ground"), "v": (lambda m: m.group(0) if m else "")(
            re.search(r"\d+(?:–\d+)? km/h", w.get("ground_range", "")))},
        {"k": _lbl("fx_peak"), "v": f"{w.get('peak_region', '')} {w.get('peak_hour', '')}h".strip()} if w.get("peak_region") else None,
    ] if f and f["v"]]
    # Labilitaet
    s_ = chain["stability"]
    if s_.get("thunder"):
        st("stability", "warn", "st_stab_thunder")
    elif s_.get("labile"):
        st("stability", "info", "st_stab_labile")
    else:
        st("stability", "ok", "st_stab_stable")
    s_["facts"] = [f for f in [
        {"k": _lbl("fx_t850"), "v": s_.get("t850", "")} if s_.get("t850") else None,
        {"k": _lbl("thunder"), "v": ", ".join(f"{_zone_name(z)} {v['thunder_hour']}h" for z, v in _konv_by_zone(wl, date).items() if v.get("thunder_hour"))}
        if any(v.get("thunder_hour") for v in _konv_by_zone(wl, date).values()) else {"k": "", "v": _lbl("fx_thunder_none")},
        {"k": _lbl("overdev"), "v": ", ".join(f"{_zone_name(z)} {v['overdev_hour']}h" for z, v in _konv_by_zone(wl, date).items() if v.get("overdev_hour"))}
        if any(v.get("overdev_hour") for v in _konv_by_zone(wl, date).values()) else None,
    ] if f]
    # Thermik
    th = chain.get("thermik") or {}
    if th.get("num"):
        climbs = [float(z["climb"].split()[0]) for z in th["num"].get("zones", []) if z.get("climb", "—") != "—"]
        c = statistics.median(climbs) if climbs else 0
        st("thermik", "ok" if c >= 2 else "info" if c >= 1 else "warn", "st_th_good" if c >= 2 else "st_th_mod" if c >= 1 else "st_th_weak")
    # Sonne
    so = chain.get("sonne") or {}
    if so.get("fazit"):
        v = so.get("verdict") or "match"
        st("sonne", {"match": "ok", "partial": "info"}.get(v, "warn"), "st_sun_" + v)
    # Modelle
    md = chain.get("modelle") or {}
    if md.get("fazit"):
        v = md.get("verdict", "agree")
        st("modelle", {"agree": "ok", "partial": "info"}.get(v, "warn"), "st_md_" + v)
        md["facts"] = md.get("consensus") or []
    return None


def _chain_raw(wetterlage: dict, dates: list, date: str, fronts, passagen) -> dict:
    syn = _synoptik_today(wetterlage, dates, date) or {}
    strip = _strip_synoptik(wetterlage, dates).get(date, {})
    note = syn.get("pressure_note", "")
    for de in ("abschwaechend", "aufbauend", "fallend", "stabil"):
        note = note.replace(de, _lbl(f"trend_{de}"))
    if note:
        note = f"{_lbl('pt_3d')} {note}"          # die Steigung gilt fuer 3 Tage, nicht fuer heute
    day_txt, jump_txt, jump_hot = _druck_tag_words(wetterlage, date)
    if day_txt:
        note = f"{note} · {day_txt}" if note else day_txt
    return {
        "lage": {
            **_lage_block(wetterlage, date),
            "label": syn.get("lage", ""),
            "centers": syn.get("centers", []),
            "pressure": syn.get("pressure_msl", ""),
            "pressure_note": note,
            "pressure_jump": jump_txt,
            "pressure_jump_hot": jump_hot,
            "regime": syn.get("pressure_regime", ""),
        },
        "day_hint": _day_summaries(wetterlage, dates).get(date, ""),
        "fronts": {**_front_block(fronts, passagen, dates, date, wetterlage),
                   "lines": _front_lines(fronts, passagen, date),
                   "zugbahn": _zugbahn_text(wetterlage, date)},
        "foehn": {"foehn": _foehn_text(wetterlage, date),
                  "fazit": _foehn_fazit(wetterlage, date),
                  "reading": _foehn_reading(wetterlage, date),
                  "legend": _foehn_legend_for(wetterlage, date),
                  "guide": ({"label": _lbl("fi_guide"), "url": _foehn_explain_url()}
                            if _foehn_indicators_for(wetterlage, date)
                            else {"label": _lbl("fvr_guide"), "url": _foehn_guide_url()}),
                  "flags": strip.get("flags", [])},
        "wind": {
            "arrow": strip.get("wind_arrow", ""), "speed": strip.get("wind_speed", ""),
            "sector": strip.get("wind_sector", ""), "strength": strip.get("wind_strength", ""),
            "deg": strip.get("wind_deg", ""), "hot": strip.get("wind_hot", False),
            "ground": _ground_estimate(strip.get("wind_speed", "")),
            # was der Wert IST: Vektor-Mittel ueber alle Spots, 12 Uhr —
            # gegenlaeufige Winde heben sich auf, regional ist es oft mehr
            "meaning": _lbl("wind_meaning"),
            # Spitze auf Regionsebene — ohne sie wirkt das Mittel harmlos
            "regional": _aloft_regional_text(wetterlage, date),
            # Spanne der Regionsspitzen + Fazit gegen die Synoptik (ersetzt das Mittel)
            **_wind_range_block(wetterlage, date, strip),
        },
        "thermik": {"fazit": _thermik_fazit(wetterlage, date), "num": _thermik_numbers(wetterlage, date)},
        "sonne": {**_sonne_block(wetterlage, date), "num": _sonne_numbers(wetterlage, date)},
        "modelle": _modelle_block(wetterlage, date),
        "stability": {
            **_labilitaet_block(wetterlage, date),
            "t850": syn.get("t850", ""), "t850_note": syn.get("t850_note", ""),
            "thunder": syn.get("thunder", []), "overdev": syn.get("overdev", []),
            "confidence": syn.get("confidence", ""),
            "confidence_level": syn.get("confidence_level", ""),
        },
    }


# ----------------------------------------------------------------------
# Warnungen mit Satz
# ----------------------------------------------------------------------

def _hazard_day(wetterlage: dict, date: str) -> dict | None:
    """Gefahren-Schalter des Tages, frisch aus dem Strukturfeld gerechnet."""
    from engine.synoptic_llm import hazard_checks
    for h in hazard_checks(wetterlage):
        if h["date"] == date:
            return h
    return None


def _zone_in(zone_id: str) -> str:
    """Zone als Ortsangabe im Satz: "im Tessin", "am Alpennordhang"."""
    return _lbl("zone_in_" + zone_id) or _zone_name(zone_id)


def _zones_text(zone_ids: list, where: bool = False) -> str:
    """Betroffene Zonen als Raum, nicht als Liste.

    Wetterberichte zaehlen keine Gebiete auf, sie fassen zusammen: alle vier
    Zonen sind "landesweit", drei von vier sind "ueberall ausser im Tessin".
    Erst darunter werden Namen genannt. `where=True` liefert die Ortsangabe
    fuer den Satz ("am Alpennordhang und im Tessin").
    """
    ids = [z for z in config.SYNOPTIC_ZONES if z in set(zone_ids or [])]
    if not ids:
        return ""
    if len(ids) == len(config.SYNOPTIC_ZONES):
        return _lbl("zones_all")
    if len(ids) == len(config.SYNOPTIC_ZONES) - 1:
        missing = [z for z in config.SYNOPTIC_ZONES if z not in ids][0]
        return _lbl("zones_except").format(zone=_zone_in(missing))
    return _join_days([(_zone_in(z) if where else _zone_name(z)) for z in ids])


def _ch_warnings(wetterlage: dict, date: str) -> dict:
    """Warnungen als Gesamtlage Schweiz — nur noch als Uebersicht: welche der
    vier Gefahren die Daten heute schalten (vom Code). Kein Satz mehr: Erklaert
    wird jede Gefahr in ihrem Block der Kette (Regen in Block 1, Foehn, Wind,
    Gewitter in der Labilitaet) — der Warnsatz wiederholte das nur (User
    25.10.2026). Die Regionen folgen erst danach mit ihren Warn-Chips.

    `entries` = die aktiven Gefahren, schwere zuerst; die oeffentliche Webseite
    (gleitcast_webpage/lib/briefing.ts) liest daraus Label und Stufe."""
    from engine.synoptic_llm import HAZARD_TOPICS
    day = _hazard_day(wetterlage, date) if wetterlage else None
    if not day:
        return {"checks": [], "entries": [], "any": False}
    checks = []
    for topic in HAZARD_TOPICS:
        c = day["checks"].get(topic) or {}
        checks.append({"topic": topic, "label": _lbl("hz_" + topic),
                       "active": bool(c.get("active")), "level": c.get("level", "warn"),
                       "sev_label": _lbl("sev_" + c.get("level", "warn"))})
    # "entries", nicht "items": Jinja loest w.items auf die dict-Methode auf.
    # `block` = der Block der Kette, der die Gefahr erklaert (App springt hin).
    entries = sorted(({"topic": c["topic"], "label": c["label"], "severity": c["level"],
                       "sev_label": c["sev_label"], "short": _lbl("hzs_" + c["topic"]),
                       "sev_short": _lbl("sevs_" + c["level"]),
                       "block": _HAZARD_BLOCK[c["topic"]][0],
                       "block_label": _lbl(_HAZARD_BLOCK[c["topic"]][1])}
                      for c in checks if c["active"]),
                     key=lambda e: e["severity"] != "stop")
    return {"checks": checks, "entries": entries, "any": bool(entries),
            "off": [c["label"] for c in checks if not c["active"]]}


# Welcher Block der Kette erklaert welche Gefahr: (Block-Schluessel, Titel-Label)
_HAZARD_BLOCK = {"RAIN": ("lage", "step_lage"), "THUNDER": ("stability", "step_stab"),
                 "FOEHN": ("foehn", "step_foehn"), "WIND": ("wind", "step_wind")}


# ----------------------------------------------------------------------
# Karte
# ----------------------------------------------------------------------

def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _map_payload(focus_date: str, dates: list) -> dict | None:
    grid = _load_json(ROOT / "data" / "synoptic_grid.json")
    if not grid or not grid.get("timesteps"):
        return None
    # 06:00 — der Stand, mit dem der Pilot morgens plant (Morgenbriefing)
    ts = focus_date + "T06:00"
    if ts not in grid["timesteps"]:
        same = [t for t in grid["timesteps"] if t.startswith(focus_date)]
        ts = same[len(same) // 2] if same else grid["timesteps"][0]
    slim = {
        "generated_at": grid.get("generated_at"), "model": grid.get("model"),
        "attribution": grid.get("attribution"), "timezone": grid.get("timezone"),
        "meta": grid["meta"], "timesteps": [ts],
        "values": {ts: grid["values"][ts]},
        "winds": {ts: grid["winds"][ts]} if grid.get("winds", {}).get(ts) else {},
        "elevations": grid.get("elevations"),
        "centers": {ts: grid.get("centers", {}).get(ts, [])},
    }

    # Fronten: dieselbe Auswahl wie die Karte der App (engine/fronten.py) zum
    # selben Zeitpunkt (Fokustag 12:00, wie synoptic-embed.js) — sonst beschreibt
    # der Fronten-Text andere Fronten als das Kartenbild im Briefing. Keine
    # Frontkarte in der Naehe: keine Fronten statt einer von einem anderen Tag.
    from engine.fronten import select_for_timestep
    sel = select_for_timestep(f"{focus_date}T12:00")
    fronts, kind = None, ""
    if sel:
        fronts = sel["geojson"]
        kind = (_lbl("map_analysis") if sel["kind"] == "analyse"
                else _lbl("map_forecast").format(h=sel["lead_h"]))

    valid = ""
    if fronts:
        v = (fronts.get("properties") or {}).get("gueltig", "")
        try:
            valid = datetime.fromisoformat(v).astimezone(_TZ).strftime("%d.%m. %H:%M")
        except (TypeError, ValueError):
            valid = v
    caption = _lbl("map_caption").format(
        model=(grid.get("model") or "").upper().replace("_", " "),
        ts=ts.replace("T", " "), kind=kind, valid=valid)
    return {"grid": slim, "fronts": fronts or {"type": "FeatureCollection", "features": []},
            "ts": ts, "caption": caption, "kind": kind, "valid": valid,
            "n_fronts": len((fronts or {}).get("features") or [])}


def _load_passagen() -> dict | None:
    """Prognose-Durchgaenge (letzte Laeufe uebereinandergelegt, siehe
    engine.synoptic_context.merge_passagen_runs) plus die tatsaechlichen
    Durchgaenge der letzten 36 h aus der DWD-Analyse."""
    from engine.synoptic_context import merge_passagen_runs, load_ist_durchgaenge
    aussagen, datei = merge_passagen_runs()
    if datei is None:
        return None
    return {"aussagen": aussagen, "vergangen": load_ist_durchgaenge(), "datei": datei}


# ----------------------------------------------------------------------
# Einstieg
# ----------------------------------------------------------------------

# Labels, die die App zum Rendern der Kette braucht (Blocktitel, Warnungen);
# Pillen-Woerter und Chip-Keys stehen schon fertig in den Bloecken.
_APP_LABEL_KEYS = ("step_lage", "step_front", "step_foehn", "step_wind", "step_stab",
                   "step_thermik", "step_sonne", "step_modelle", "thunder_caveat",
                   "warnings_ch", "hz_none", "hz_off",
                   "question", "q1_long", "q2_long", "q2_day")


def build_chain_all_days(wetterlage: dict | None, dates: list[str],
                         days: list[dict] | None = None) -> dict:
    """Analyse-Kette + Warnungen Schweiz fuer JEDEN Tag im Fenster — fuer die
    App (/api/briefing), die per Tages-Tab umschaltet. Dieselben Funktionen
    wie das Mail (`_chain`, `_ch_warnings`), also fuer "heute" 1:1 dasselbe
    Ergebnis. Fronten je Tag aus dem DWD-Archiv wie die Karte der App
    (engine.fronten.select_for_timestep, 12:00 des Tages) — ohne das
    Druckraster zu laden, das braucht nur das Kartenbild.

    `days` (briefing_data["days"]) liefert zusaetzlich je Tag die Kachel
    (`tile`) wie im Wochenstreifen des Mails: Einstufung des Tages ueber
    ALLE bewerteten Regionen (die App kennt keine Abo-Regionen), Note, Druck,
    Hoehenwind — fuer die Tages-Tabs.

    Tage ohne Synoptik-Daten (aelterer Cache) stehen mit `chain: None` drin —
    die App zeigt dann eine ehrliche Leerzeile statt eines geratenen Blocks."""
    from engine.fronten import select_for_timestep
    wl = wetterlage or {}
    dates = [d for d in (dates or []) if d]
    wl_dates = set(wl.get("forecast_dates") or [])
    passagen = _load_passagen()
    strip = _strip_synoptik(wl, dates) if wl else {}
    raw_days = {d.get("date", ""): d for d in (days or []) if isinstance(d, dict)}
    all_region_ids = sorted({r.get("region_id") for d in raw_days.values()
                             for r in (d.get("top_regions") or []) if r.get("region_id")})
    by_date: dict[str, dict] = {}
    for d in dates:
        tile = _day_tile(raw_days.get(d) or {}, all_region_ids, strip.get(d) or {})
        if wl_dates and d not in wl_dates:
            by_date[d] = {"chain": None, "warnings": None, "fronts_kind": "", "tile": tile}
            continue
        sel = _select_fronts_safe(select_for_timestep, f"{d}T12:00")
        fronts = sel["geojson"] if sel else None
        kind = ""
        if sel:
            kind = (_lbl("map_analysis") if sel["kind"] == "analyse"
                    else _lbl("map_forecast").format(h=sel["lead_h"]))
        by_date[d] = {
            "chain": _chain(wl, dates, d, fronts, passagen),
            "warnings": _ch_warnings(wl, d),
            "fronts_kind": kind,
            "tile": tile,
        }
    labels = _labels()
    return {
        "dates": dates,
        "lang": _lang(),
        "generated_at": wl.get("generated_at", ""),
        "labels": {k: labels.get(k, "") for k in _APP_LABEL_KEYS},
        "source": _source_line(),
        "by_date": by_date,
    }


def _day_tile(raw_day: dict, region_ids, strip_entry: dict) -> dict:
    """Tageskachel wie im Mail-Wochenstreifen (Sektion 1), fuer die Tabs der
    App: Einstufung + Note (_day_verdict), Druck und Hoehenwind (Synoptik)."""
    v = _day_verdict(raw_day, region_ids)
    tier = v["tier"]
    msl = strip_entry.get("pressure_msl") or ""
    m = re.search(r"[\d.]+", msl)
    return {
        "tier": tier,
        "band": _tier_band(tier),
        "status": _tier_label(tier) if v["n"] else "",
        "rating": v["rating"],
        "n": v["n"],
        "pressure_hpa": (f"{round(float(m.group(0)))} hPa" if m else ""),
        "wind_arrow": strip_entry.get("wind_arrow", ""),
        # Gradzahl (woher, meteorologisch) fuer einen gedrehten Pfeil in der App
        "wind_dir_deg": (lambda m: int(m.group(0)) if m else None)(re.match(r"\d+", strip_entry.get("wind_deg") or "")),
        "wind_sector": strip_entry.get("wind_sector", ""),
        "wind_strength": strip_entry.get("wind_strength", ""),
        "wind_hot": bool(strip_entry.get("wind_hot")),
    }


def _model_names() -> tuple[str, str]:
    """(Boden, Hoehe): Anzeigenamen der Modelle, aus denen die Frontsignatur
    und die Zonen-Kennzahlen kommen — Bodendruck/Regen vom Surface-Modell,
    700-hPa-Wind/T850 vom Druckflaechen-Modell (config, docs/WETTERMODELLE.md).
    Nie "unsere Prognose": die Daten sind ICON, nicht Wingcast."""
    from engine.synoptic_context import MODEL_COMPARE_MODELS as names
    surface = names.get(config.SURFACE_PRIMARY_MODEL, config.SURFACE_PRIMARY_MODEL)
    pl = names.get(config.PRESSURE_LEVEL_PRIMARY_MODEL, config.PRESSURE_LEVEL_PRIMARY_MODEL)
    return surface, pl


def _model_words() -> str:
    surface, pl = _model_names()
    return surface if surface == pl else f"{surface}/{pl}"


def _source_line() -> str:
    surface, pl = _model_names()
    return _lbl("src_line").format(surface=surface, pl=pl)


def _select_fronts_safe(fn, ts: str):
    """Frontkarte darf die Kette nie reissen: fehlendes Archiv -> keine Fronten."""
    try:
        return fn(ts)
    except Exception:  # noqa: BLE001 — Archiv fehlt/defekt: Kette ohne Fronten
        return None


def _subject_line(days: list, verdicts: dict) -> str:
    """Betreff + Kopf-Pille: ALLE Tage, nach Stufe gruppiert, mit denselben
    Worten wie die Tageskacheln — "Mo mit Warnhinweisen · Heute, Di mit
    schweren Warnhinweisen". Frueher nannte die Pille nur die Tage der besten
    vorhandenen Stufe ("Mon with alerts", 25.10.2026) und las sich, als haette
    nur Montag Warnhinweise. Haben alle bewerteten Tage dieselbe Stufe, steht
    die Kurzform ("Schwere Warnhinweise an allen Tagen"). Nie ein Superlativ,
    nie "fliegbar": ob geflogen wird, entscheidet der Pilot."""
    groups = {"green": [], "conditional": [], "not_safe": []}
    for d in days:
        tier = (verdicts.get(d.get("date")) or {}).get("tier")
        if tier in groups:
            groups[tier].append(d)
    present = [t for t in ("green", "conditional", "not_safe") if groups[t]]
    if not present:
        return _lbl("subj_not_safe")
    rated = sum(len(groups[t]) for t in present)
    if len(present) == 1 and rated == len(days):
        return _lbl({"green": "subj_all_safe", "conditional": "subj_all_caution",
                     "not_safe": "subj_all_severe"}[present[0]])
    key = {"green": "subj_safe", "conditional": "subj_caution", "not_safe": "subj_severe"}
    return " · ".join(_capitalize(_lbl(key[t]).format(days=_join_days([_day_name(d) for d in groups[t]])))
                      for t in present)


def build_v3_context(ctx: dict, briefing_data: dict, subscriber: dict,
                     focus_date: str = "", top_n_regions_per_day: int = 0) -> dict:
    days = ctx.get("days") or []
    dates = [d.get("date", "") for d in days]
    raw_days = {d.get("date", ""): d for d in briefing_data.get("days", []) or []}
    wetterlage = briefing_data.get("wetterlage") or {}
    abo = [r for r in (subscriber.get("regions") or [])]
    all_region_ids = sorted({r.get("region_id") for d in raw_days.values()
                             for r in (d.get("top_regions") or []) if r.get("region_id")})
    base = config.BASE_URL.rstrip("/")

    today_iso = datetime.now().date().isoformat()
    focus_iso = focus_date if focus_date in dates else (today_iso if today_iso in dates else (dates[0] if dates else today_iso))
    focus_idx = dates.index(focus_iso) if focus_iso in dates else 0
    focus_raw = raw_days.get(focus_iso) or {}
    focus_ctx = next((d for d in days if d.get("date") == focus_iso), {})

    # ---- Woche -----------------------------------------------------------
    syn = _strip_synoptik(wetterlage, dates)
    hints = _day_summaries(wetterlage, dates)
    region_name_by_id = {}
    for d in raw_days.values():
        for r in d.get("top_regions") or []:
            region_name_by_id[r.get("region_id")] = r.get("region_name", r.get("region_id"))

    strip = []
    verdicts = {}
    for d in days:
        date_str = d.get("date", "")
        raw = raw_days.get(date_str) or {}
        # Der Tag selbst, aus den Abo-Regionen — nicht der beste Startplatz
        verdict = _day_verdict(raw, abo)
        verdicts[date_str] = verdict
        tier = verdict["tier"]
        rating = verdict["rating"]
        tint = _rating_tint(_tier_band(tier), rating)
        by_id = {r.get("region_id"): r for r in (raw.get("top_regions") or [])}
        # Eine Zeile je Abo-Region: voller Name + Rating in der App-Farbe,
        # gruppiert nach Rating 4-5 / 1-3 x Sicher/Vorsicht, Nicht sicher separat.
        segments = []
        for rid in abo:
            entry = by_id.get(rid) or {}
            cls = _region_class(entry)
            # eigener Name: "rating" ist oben das Tages-Rating der Karte
            r_rating = int(entry.get("experience_rating") or 0)
            r_tint = _rating_tint(entry.get("safety_band") or "no_data", r_rating)
            segments.append({"rid": rid, "cls": cls, "label": _class_label(cls),
                             "fill": r_tint["fill"], "border": r_tint["border"], "text": r_tint["text"],
                             "rating": r_rating, "rating_display": str(r_rating) if r_rating else "",
                             "name": region_name_by_id.get(rid, rid)})
        segments.sort(key=lambda x: (_CLASS_ORDER.index(x["cls"]), -x["rating"], x["name"]))
        groups = []
        for cls in _CLASS_ORDER:
            items = [x for x in segments if x["cls"] == cls]
            if items:
                rng, tier_key = _CLASS_META[cls]
                groups.append({"cls": cls, "range": rng, "status": _status(tier_key),
                               "color": _STATUS_COLOR[tier_key], "n": len(items), "items": items})
        mine = _region_split(raw, abo)
        ch = _region_split(raw, all_region_ids)
        s = syn.get(date_str, {})
        strip.append({
            "date": date_str, "name": _day_name(d), "label": d.get("label", {}),
            "is_today": d.get("is_today", False), "is_focus": date_str == focus_iso,
            "url": d.get("strip_url", ""),
            "tier": tier, "status": _tier_label(tier), "glyph": _DAY_GLYPH.get(tier, "?"),
            "rating_display": str(rating) if rating else "",
            "fill": tint["fill"], "border": tint["border"], "text": tint["text"],
            "is_good": tier == "green",
            "segments": segments, "groups": groups, "mine": mine, "ch": ch,
            "pressure": s.get("pressure", ""),
            "wind_arrow": s.get("wind_arrow", ""), "wind_sector": s.get("wind_sector", ""),
            "wind_strength": s.get("wind_strength", ""), "wind_hot": s.get("wind_hot", False),
            "notable": _notable(s, wetterlage, date_str),
            "hint": hints.get(date_str, ""),
        })

    subject = _subject_line(days, verdicts)

    # ---- Tag -------------------------------------------------------------
    passagen = _load_passagen()
    map_payload = _map_payload(focus_iso, dates)
    fronts = map_payload["fronts"] if map_payload else None
    chain = _chain(wetterlage, dates, focus_iso, fronts, passagen)
    cards = _region_cards(focus_raw, focus_idx, abo, base)
    hero = _hero(cards)
    warnings = _ch_warnings(wetterlage, focus_iso)

    out = dict(ctx)
    out.update({
        "v3_subject": subject,
        "v3_strip": strip,
        "v3_abo_count": len(abo),
        "v3_ch_count": len(all_region_ids),
        "v3_hero": hero,
        "v3_headline": _headline(hero, focus_ctx.get("label", {})),
        "v3_week_line": _week_line(wetterlage, days),
        "v3_focus_date": focus_iso,
        "v3_focus_is_today": focus_iso == today_iso,
        "v3_focus_label": focus_ctx.get("label", {}),
        "v3_chain": chain,
        "v3_warnings": warnings,
        "v3_regions": cards,
        "v3_map": map_payload,
        "v3_coverage": {
            "regions": len(cards),
            "with_recommendation": sum(1 for c in cards if c["has_recommendation"]),
            "with_window": sum(1 for c in cards if c["has_window"]),
        },
        "v3_labels": _labels(),
        "v3_lang": _lang(),
    })
    return out
