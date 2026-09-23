"""
Analyse-Kette des Morgenbriefings — gemeinsame Quelle fuer Mail und App.

Aufbau, Prinzip und Pillen-Regeln: docs/BRIEFING.md. Kurz: das Briefing folgt
der Analyse-Kette des Piloten (Lage -> Fronten -> Foehn/Bise -> Hoehenwind ->
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
        "subj_safe":     "{days} sicher",
        "subj_caution":  "{days} mit Vorsicht",
        "subj_not_safe": "Kein sicherer Tag",
        "conditional":   "bedingt fliegbar",
        "nothing":       "Nichts fliegbar",
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
        "subj_safe":     "{days} safe",
        "subj_caution":  "{days} with caution",
        "subj_not_safe": "No safe day",
        "conditional":   "conditionally flyable",
        "nothing":       "Nothing flyable",
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
_REGIME = {
    "de": {"hoch": "Hoch", "hochdruck": "Hochdruck", "tief": "Tief", "tiefdruck": "Tiefdruck", "neutral": "Neutral"},
    "en": {"hoch": "High", "hochdruck": "High pressure", "tief": "Low", "tiefdruck": "Low pressure", "neutral": "Neutral"},
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
    """Pro Datum eine Kurzzeile: Druckregime + msl, T850, Foehn/Bise."""
    lang = _lang()
    flow = _per_day_index(wetterlage.get("flow_overhead"), dates)
    press = _per_day_index(wetterlage.get("pressure_influence"), dates)
    t850 = _per_day_index(wetterlage.get("t850_trend"), dates)
    foehn = _per_day_index(wetterlage.get("foehn"), dates)
    bise = _per_day_index(wetterlage.get("bise"), dates)

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
        bi = bise.get(d) or {}
        if bi.get("active"):
            flags.append("Bise")

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


def _day_line(wetterlage: dict, date: str) -> str:
    """Kurzer KI-Satz zur Lage dieses Tages (llm_overview.day_lines)."""
    for e in ((wetterlage or {}).get("llm_overview") or {}).get("day_lines") or []:
        if isinstance(e, dict) and e.get("date") == date:
            return (e.get("text") or "").strip()
    return ""


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
    Regionen mit 3). Jetzt zaehlt, wie der Tag in den Regionen insgesamt ist:
      not_safe     — mehr als BRIEFING_DAY_NOT_SAFE_SHARE der Regionen Not safe
      green (Safe) — mindestens BRIEFING_DAY_SAFE_SHARE der Regionen Safe
      conditional  — dazwischen
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
    red = sum(1 for b, _ in rated if b == "red")
    green = sum(1 for b, _ in rated if b == "green")
    if red > n * config.BRIEFING_DAY_NOT_SAFE_SHARE:
        tier = "not_safe"
    elif green >= n * config.BRIEFING_DAY_SAFE_SHARE:
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
        "step_foehn":   "Föhn / Bise",
        "step_wind":    "Höhenwind",
        "step_stab":    "Labilität",
        "step_thermik": "Thermik / Basis",
        "step_sonne":   "Sonne / Bewölkung",
        "step_modelle": "Modelle",
        # Status-Pille je Kettenglied (kurz, max 3 Woerter)
        "st_lage_match": "Daten passen zur Lage", "st_lage_partial": "Daten passen teilweise", "st_lage_contra": "Daten widersprechen der Lage",
        "st_front_passes": "Front zieht durch", "st_front_weak": "Front schwächt ab", "st_front_none": "keine Front", "st_front_rear": "Rückseite",
        "st_foehn_on": "Föhn aktiv", "st_foehn_gusty": "einzelne Böen", "st_foehn_off": "kein Föhn", "st_bise_on": "Bise",
        "st_wind_stronger": "regional stärker", "st_wind_match": "regional wie im Mittel", "st_wind_weaker": "regional schwächer",
        "st_stab_thunder": "Gewitter", "st_stab_labile": "teils labil", "st_stab_stable": "stabil",
        "st_th_good": "gutes Steigen", "st_th_mod": "mässiges Steigen", "st_th_weak": "schwaches Steigen",
        "st_sun_match": "wie erwartet", "st_sun_partial": "teils anders", "st_sun_contra": "anders als erwartet",
        "st_md_agree": "Modelle einig", "st_md_partial": "ein offener Punkt", "st_md_uncertain": "Modelle uneinig",
        "fx_dwd": "DWD", "fx_signature": "Signatur", "fx_sig_yes": "ja", "fx_sig_no": "keine",
        "fx_dp": "ΔP Alpen", "fx_gust": "Böe", "fx_t850": "T850", "fx_thunder_none": "keine Gewitter",
        "fx_ground": "am Boden ≈", "fx_peak": "Spitze",
        "md_agree":      "Fazit: Die Modelle sind sich bei Wind, Niederschlag und Bewölkung einig.",
        "md_partial":    "Fazit: Bei {agree} sind sich die Modelle einig, bei {q}",
        "md_uncertain":  "Fazit: Die Modelle widersprechen sich — bei {q}",
        "md_q":          "{what} {zone} nicht (Vergleichspunkt {place}): {groups}.",
        "md_grp":        "{models} {verb} {label}",
        "md_lab_wind_mid": "fliegbaren Wind", "md_lab_cloud_mid": "halb bedeckt",
        "md_what_wind":  "dem Wind", "md_what_rain": "dem Niederschlag", "md_what_cloud": "der Bewölkung",
        "md_lab_wind_hi": "windig bis verblasen", "md_lab_wind_lo": "ruhigen Wind",
        "md_lab_rain_hi": "Niederschlag", "md_lab_rain_lo": "trocken",
        "md_lab_cloud_hi": "bedeckt", "md_lab_cloud_lo": "wenig Wolken",
        "md_verb_one":   "sieht", "md_verb_many": "sehen",
        "md_var_wind":   "Wind", "md_var_rain": "Niederschlag", "md_var_cloud": "Bewölkung",
        "md_place_alpennordhang": "Interlaken", "md_place_wallis": "Sion", "md_place_tessin": "Locarno", "md_place_graubuenden_engadin": "Chur",
        "su_exp_high":  "{Press} lässt viel Sonne erwarten",
        "su_exp_low":   "{Press} lässt viel Bewölkung erwarten",
        "su_exp_flat":  "Die Übergangslage lässt wechselnde Bewölkung erwarten",
        "su_air_south": ", die feuchte {sector}luft aber Wolken im Süden",
        "su_air_north": ", die {sector}luft aber Wolken am Alpennordhang",
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
        "th_exp_high":  "{Press} lässt Absinken und eine gedeckelte Basis erwarten",
        "th_exp_low":   "{Press} lässt eine hohe Basis, aber Überentwicklung erwarten",
        "th_exp_flat":  "Die Übergangslage lässt keine klare Schichtung erwarten",
        "th_press_hoch": "Der Hochdruck", "th_press_up": "Der steigende Druck",
        "th_press_tief": "Der Tiefdruck", "th_press_down": "Der fallende Druck",
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
        "front_none":   "Keine Front im Vorhersagefenster (DWD).",
        # Fazit — Prognosedaten, nie eine finale Aussage
        # Lage in drei kurzen Saetzen: Einfluss -> Druck -> Prognosedaten
        "lg_between":      "Zwischen {a} und {b}: {strength} {sector}strömung mit {air}.",
        "lg_single":       "{a}: {strength} {sector}strömung mit {air}.",
        "lg_nocenter":     "{strength} {sector}strömung mit {air}.",
        "lg_center":       "{ctype} {name}",
        "lg_air_SW":       "feuchter Mittelmeerluft", "lg_air_S": "Südströmung, Föhnrisiko im Norden",
        "lg_air_SE":       "Südströmung, Föhnrisiko im Norden", "lg_air_W": "milder Atlantikluft",
        "lg_air_NW":       "kühler Nordwestluft", "lg_air_N": "kühler Nordluft",
        "lg_air_NE":       "trockener Kontinentalluft, Bise möglich", "lg_air_E": "trockener Kontinentalluft, Bise möglich",
        "lg_sector_N":     "Nord", "lg_sector_NE": "Nordost", "lg_sector_E": "Ost", "lg_sector_SE": "Südost",
        "lg_sector_S":     "Süd", "lg_sector_SW": "Südwest", "lg_sector_W": "West", "lg_sector_NW": "Nordwest",
        "lg_strength_schwach": "schwache", "lg_strength_maessig": "mässige",
        "lg_strength_kraeftig": "kräftige", "lg_strength_stuermisch": "stürmische",
        "lg_pressure":     "{regime} {trend} — {meaning}.",
        "lg_regime_hoch":  "Hochdruck", "lg_regime_tief": "Tiefdruck", "lg_regime_neutral": "Der Druck",
        "lg_trend_up":     "steigt", "lg_trend_down": "fällt", "lg_trend_flat": "bleibt",
        # was das fuer das Wetter heisst — Hoch: stabil und trocken, Tief: unbestaendig
        "lg_mean_hoch_up": "Hochdruckeinfluss festigt sich, stabiles und meist trockenes Wetter",
        "lg_mean_hoch_flat": "stabiles, meist trockenes Wetter",
        "lg_mean_hoch_down": "das Hoch gibt nach, das Wetter wird anfälliger",
        "lg_mean_tief_up": "das Tief zieht ab, das Wetter beruhigt sich langsam",
        "lg_mean_tief_flat": "unbeständig, Wolken und Regen",
        "lg_mean_tief_down": "Tiefdruckeinfluss verstärkt sich, unbeständig mit Regen",
        "lg_mean_neutral_up": "Hochdruckeinfluss nimmt zu, das Wetter beruhigt sich",
        "lg_mean_neutral_flat": "Übergangslage, wechselhaft",
        "lg_mean_neutral_down": "Tiefdruckeinfluss nimmt zu, das Wetter wird unbeständiger",
        # Urteil Block 1 im Satz, nicht nur in der Pille: passt die Synoptik zu den Modellwerten?
        "lg_data_match":   "{models} bestätigt das: {rain}{rain_trend}, {wind}.",
        "lg_data_partial": "{models} passt nur teilweise dazu: {rain}{rain_trend}, {wind}.",
        "lg_data_contra":  "{models} widerspricht: {rain}{rain_trend}, {wind}.",
        "lg_rain_fading":  " und im Tagesverlauf abklingend",
        "lg_mean_calm_north": "Hochdruckeinfluss nimmt zu, das Wetter beruhigt sich auf der Alpennordseite",
        "lg_rain_south_growing": "meist trocken, auf der Alpensüdseite Schauer und am Nachmittag zunehmend",
        "lg_mean_calm_not_yet": "Hochdruckeinfluss nimmt zu, kommt aber noch nicht an",
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
        # Foehn/Bise: Anspruch der Synoptik gegen die Prognosedaten
        "fb_foehn_yes":     "{Side}föhnlage: Druckgefälle {dp} hPa über die Alpen. {models} bestätigt ihn — am Lee-Prognosepunkt {station} Böen bis {gust} km/h{windows}.",
        "fb_foehn_aloft":   "{Side}föhnlage: Druckgefälle {dp} hPa über die Alpen, doch am Lee-Prognosepunkt {station} zeigt {models} kaum Böen (bis {gust} km/h) — der Föhn bleibt in der Höhe.",
        "fb_foehn_no":      "Kein Föhn: das Druckgefälle über die Alpen bleibt mit {dp} hPa unter der Schwelle von 4 hPa.{strong}",
        "fb_foehn_no_nodp": "Kein Föhn: kein nennenswertes Druckgefälle über die Alpen.{strong}",
        "fb_strong_none":   " {models} bestätigt das: keine starken Winde an den Startplätzen.",
        "fb_strong_some":   " {models} zeigt trotzdem starke Winde an einzelnen Startplätzen: Böen bis {gust} km/h aus {dir} ({spot}, {alt} m, {when}){cmp} — Höhenwind, kein Föhn.",
        "fb_models":        "; die Modelle sind uneinig, CH2 sieht nur {ch2} km/h",
        "fb_station_nord":  "Zürich", "fb_station_sued": "Lugano",
        "fb_bise_yes":      "Bise: Druckgefälle Nordost–Süd {dp} hPa und Höhenwind aus Nordost — im Mittelland zeigt {models} Nordostwind bis {kmh} km/h an {share} % der Startplätze.",
        "fb_bise_yes_noground": "Bise laut Synoptik (Druckgefälle {dp} hPa, Höhenwind Nordost), doch im Mittelland zeigt {models} kaum Nordostwind — schwach oder erst später.",
        "fb_bise_no":       "Keine Bise: {reason} — {models} bestätigt das: im Mittelland kein Nordostwind.",
        "fb_bise_no_ground": "Keine Bise laut Synoptik ({reason}), {models} zeigt im Mittelland aber lokal Nordostwind bis {kmh} km/h.",
        "fb_reason_dp":     "das Druckgefälle Nordost–Süd ist zu schwach ({dp} hPa)",
        "fb_reason_dir":    "der Höhenwind kommt aus {sector} statt Nordost",
        "fb_reason_both":   "Druckgefälle und Höhenwind passen nicht ({dp} hPa, {sector})",
        "fb_side_nord":     "Nord", "fb_side_sued": "Süd",
        "fb_win_from":      ", ab {when}",
        # Labilitaet: Erwartung aus der Synoptik gegen CAPE / Gewitter / Ueberentwicklung
        "lb_expect":        "{air}{press}",
        "lb_air_humid":     "Die feuchte {sector}luft lässt Labilität erwarten",
        "lb_air_cool":      "Die kühle {sector}luft lässt Schauer und Labilität am Nordhang erwarten",
        "lb_air_neutral":   "Die {sector}strömung bringt keine ausgeprägt labile Luft",
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
        "front_today_in":     "{Day} dürfte die {typ} {zone} {when} {art}{unsicher}{prov}.",
        "front_sig_yes":      "In der DWD-Prognose wird eine {typ} über {zone_dat} angegeben. {Day} zieht sie gegen {hour} Uhr durch — {models} bestätigt das: {belege}.",
        "front_fazit_none_more": "Danach ist im 3-Tage-Fenster keine weitere Front in Sicht.",
        "front_sig_dwd_only": "In der DWD-Prognose wird {day} {when} eine {typ} über {zone_dat} angegeben. {models} bestätigt das nicht: keine Signatur ({gegen}) — die Front dürfte sich abschwächen oder auflösen.",
        "front_sig_none":     "In der DWD-Prognose ist keine Front über der Schweiz angegeben. {Day} zieht keine durch — {models} bestätigt das: {gegen}.",
        "ev_druck":           "Druckanstieg",
        "ev_drehung":         "Winddrehung auf {sector}",
        "ev_kalt":            "Abkühlung in der Höhe",
        "ev_warm":            "Erwärmung in der Höhe",
        "ev_regen":           "Regen",
        "gv_sprung":          "Drucksprung {val} hPa in 3 h ({zone})",
        "gv_druck_flach":     "keinen Drucksprung",
        "gv_drehung":         "keine Winddrehung",
        "gv_regen":           "keinen Regen",
        "front_generic":      "Front",
        "sectors":            "Nord,Nordost,Ost,Südost,Süd,Südwest,West,Nordwest",
        "front_prev_run":     " (Lauf von gestern; heute früh {dist} km {dir})",
        "front_fazit_in_more": "Gemäss Prognosedaten dürfte eine weitere {typ} {zone} {day} {when} {art}{unsicher}.",
        "front_today_none":   "{Day} wird keine Front erwartet.",
        "front_passed":       "{When} ist die {typ} über {zone} gezogen (DWD-Analyse) — {day} auf der Rückseite.",
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
        "foehn_none":   "Kein Föhn.",
        "foehn_line":   "{side}föhn {level}, {h} h.",
        "bise_none":    "Keine Bise.",
        "bise_line":    "Bise {strength}, ΔP {dp} hPa.",
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
        "w_foehn":      "{side}föhn {level} an {days} ({h}).",
        "w_storm":      "Höhenwind bis {kmh} km/h ({days}) — am Boden ≈ {ground} km/h zu erwarten.",
        "w_thunder":    "Gewitterzellen im Flugfenster: {zones} ({days}). Fehlalarmrate bei 5 % Grundrate hoch — vor Ort prüfen.",
        "w_overdev":    "Überentwicklung möglich: {zones} ({days}). Weiche Vorwarnung, kein Alarm.",
        "w_shear":      "Windscherung an {days} — die Thermik wird zerrissen, Details je Region.",
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
        "sev_stop":     "Stopp",
        "sev_warn":     "Warnung",
        "alps_north":   "Alpennordseite",
        "alps_south":   "Alpensüdseite",
        "warnings_ch":  "Warnungen · Gesamtlage Schweiz",
        "src_line":     "Prognosedaten: {surface} (Boden), {pl} (Höhe) — MeteoSchweiz/DWD via Open-Meteo · Grosswetterlage: ECMWF IFS · Fronten: DWD",
        "hz_RAIN": "Regen", "hz_THUNDER": "Gewitter", "hz_FOEHN": "Föhn", "hz_BISE": "Bise",
        "hz_WIND": "Starker Wind",
        "hz_none":      "Keine Gefahr schweizweit.",
        # Ursache je Warnung aus der Synoptik — Warnung = Daten, Ursache = Lage
        "hz_cause_rain_south": "— die feuchte {sector}luft staut sich im Süden.",
        "hz_cause_rain_north": "— die {sector}luft staut sich am Alpennordhang.",
        "hz_cause_rain_front": "— Frontdurchgang.",
        "hz_cause_rain_flow":  "— {sector}strömung.",
        "hz_cause_wind_aloft": "— der {sector}-Höhenwind schlägt bis in die Täler durch.",
        "hz_cause_wind_gusts": "— böiger Wind.",
        "hz_cause_foehn":      "— Druckgefälle {dp} hPa über die Alpen.",
        "hz_cause_thunder":    "— feuchte, labile Luft{cap}.",
        "hz_cause_thunder_cap": ", im Norden gedeckelt",
        "hz_cause_bise":       "— Druckgefälle Nordost–Süd {dp} hPa.",
        "hz_code_rain": "Regen {zones}, {extent} und {intensity}.",
        "hz_extent_widespread": "verbreitet",
        "hz_extent_scattered": "gebietsweise",
        "hz_extent_isolated": "vereinzelt",
        "hz_rain_light": "leicht",
        "hz_rain_moderate": "mässig",
        "hz_rain_heavy": "kräftig",
        "hz_rain_severe": "kräftig, lokal mit Starkregen",
        "hz_code_thunder": "Modell-Gewitter {zones}.",
        "hz_code_foehn": "{side}föhn {level}, {h} h — Lee-Seite {zones}.",
        "hz_code_wind": "{classes}.",
        "hz_class_verblasen": "verblasen", "hz_class_stark_eingeschraenkt": "stark eingeschränkt",
        "win_morning": "Vormittag", "win_midday": "Mittag",
        "win_afternoon": "Nachmittag", "win_evening": "Abend",
        "hz_windows":   "{spans}.",
        "hz_run_single": "am {a}",
        "hz_run_open":   "ab {a}",
        "hz_run_span":   "{a} bis {b}",
        "hz_run_join":   " und wieder ",
        "hz_windows_but": "{main}, {exception}",
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
        "sum_BISE": "Bise", "sum_WIND": "starker Wind",
        "wind_meaning": "Mittelwert über alle Schweizer Spots, 12 Uhr",
        "wind_range":   "{lo}–{hi} km/h je Region",
        "wind_range_note": "Spanne der Regionsspitzen auf 700 hPa, am stärksten {region} {hour} Uhr",
        "wind_ground_range": "≈ {lo}–{hi} km/h am Boden zu erwarten (⅔-Regel)",
        "wind_fazit_match": "Das Schweizer Mittel ({models}) sagt {strength} {sector}strömung, und die Regionen bleiben in dieser Klasse: {lo} bis {hi} km/h, am stärksten {region} am {when}.",
        "wind_fazit_stronger": "Das Schweizer Mittel ({models}) sagt {strength} {sector}strömung — regional ist es eine Klasse stärker: bis {hi} km/h {region} am {when}, also {cls}. Das Mittel verharmlost.",
        "wind_fazit_weaker": "Das Schweizer Mittel ({models}) sagt {strength} {sector}strömung — selbst die stärkste Region bleibt darunter: höchstens {hi} km/h ({region}).",
        "wcls_schwach": "schwach", "wcls_maessig": "mässig", "wcls_kraeftig": "kräftig", "wcls_stuermisch": "stürmisch",
        "wstr_schwach": "schwache", "wstr_maessig": "mässige", "wstr_kraeftig": "kräftige", "wstr_stuermisch": "stürmische",
        "hour_morning": "Morgen", "hour_midday": "Mittag", "hour_afternoon": "Nachmittag", "hour_evening": "Abend",
        "chip_rain_widespread": "Flächiger Regen",
        "chip_rain_scattered":  "Regen in Teilen der Region",
        "chip_rain_isolated":   "Einzelne Schauer",
        "chip_rain":            "Regen",
        "chip_aloft_warn":  "Höhenwind über {kmh} km/h",
        "chip_aloft_stop":  "Starker Höhenwind über {kmh} km/h",
        "chip_ground_warn": "Bodenwind über {kmh} km/h",
        "chip_ground_stop": "Starker Bodenwind über {kmh} km/h",
        "chip_foehn_moderate": "Mässiger Föhn",
        "chip_foehn_strong":   "Starker Föhn",
        "chip_thunder":        "Gewitter möglich",
        "chip_thunder_risk":   "Gewitterrisiko {pct} %",
        "chip_clouds":         "Wolken bis auf Starthöhe",
        "lage_Hochdrucklage": "Hochdrucklage", "lage_Tiefdrucklage": "Tiefdrucklage",
        "lage_Nordfoehnlage": "Nordföhnlage", "lage_Suedfoehnlage": "Südföhnlage",
        "lage_Foehnlage (wechselnd)": "Föhnlage (wechselnd)",
        "lage_Bisenlage": "Bisenlage", "lage_Genua-Tief": "Genua-Tief",
        "lage_Uebergangslage": "Übergangslage", "lage_unbestimmt": "unbestimmt",
        "zb_alpennordhang_west": "Alpennordhang West",
        "zb_alpennordhang_ost":  "Alpennordhang Ost",
        "hz_windows_staggered": "Zeitlich gestaffelt: ab {a} {zones}, anderswo später.",
        "hz_shape_ganztags": "ganztägig",
        "hz_shape_ab":  "ab {a}",
        "hz_shape_bis": "bis {b}",
        "hz_shape_nur": "nur am {a}",
        "hz_shape_spanne": "von {a} bis {b}",
        "hz_shape_wechselnd": "am {a} und wieder am {b}",
        "zones_all":    "landesweit",
        "zones_except": "überall ausser {zone}",
        "zone_in_alpennordhang": "am Alpennordhang",
        "zone_in_wallis": "im Wallis",
        "zone_in_tessin": "im Tessin",
        "zone_in_graubuenden_engadin": "in Graubünden",
        "hz_course_zunehmend": "Legt im Tagesverlauf zu.",
        "hz_course_abflauend": "Flaut im Tagesverlauf ab.",
        "hz_course_gleich":    "Bleibt den Tag über gleich stark.",
        "hz_foehn_gust":       "Im Lee Böen bis {kmh} km/h.",
        "hz_tm_vorbei":     "Folgetag: vorbei.",
        "hz_tm_abklingend": "Folgetag: schwächer.",
        "hz_tm_zunehmend":  "Folgetag: stärker.",
        "hz_tm_gleich":     "Folgetag: unverändert.",
        "airspace_note": "Luftraum (DABS), Startplatz und Windsack prüft der Pilot vor Ort — das kann keine Prognose.",
        "days_ahead":   "Die Tage voraus",
        "week_hint":    "Oben je Tag: Mittelwert deiner Regionen (1–5). Sicher, wenn mindestens die Hälfte sicher ist; Nicht sicher, wenn mehr als die Hälfte nicht sicher ist; sonst Vorsicht. Darunter jede Region mit ihrer eigenen Bewertung.",
        "regions_word": "Deine Regionen",
        "situation_ch":  "Gesamtlage Schweiz",
        "wl_rain": "Regen", "wl_dry": "trocken", "wl_high": "Hochdruck", "wl_low": "Tiefdruck",
        "wl_windy": "kräftiger Höhenwind", "wl_calm": "ruhig", "wl_foehn_n": "Nordföhn", "wl_foehn_s": "Südföhn", "wl_bise": "Bise",
    },
    "en": {
        "no_warning":   "no warning",
        "spots_word":   "spots",
        "regions_word": "regions",
        "ch_context":   "CH",
        "of":           "of",
        "step_lage":    "Situation",
        "step_front":   "Fronts",
        "step_foehn":   "Foehn / Bise",
        "step_wind":    "Upper wind",
        "step_stab":    "Stability",
        "step_thermik": "Thermals / cloud base",
        "step_sonne":   "Sun / cloud",
        "step_modelle": "Models",
        # status pill per chain step (short, max 3 words)
        "st_lage_match": "data fit the pattern", "st_lage_partial": "data partly fit", "st_lage_contra": "data contradict the pattern",
        "st_front_passes": "front passes", "st_front_weak": "front weakening", "st_front_none": "no front", "st_front_rear": "rear side",
        "st_foehn_on": "foehn active", "st_foehn_gusty": "isolated gusts", "st_foehn_off": "no foehn", "st_bise_on": "Bise",
        "st_wind_stronger": "regionally stronger", "st_wind_match": "regionally as average", "st_wind_weaker": "regionally weaker",
        "st_stab_thunder": "thunderstorms", "st_stab_labile": "partly unstable", "st_stab_stable": "stable",
        "st_th_good": "good climbs", "st_th_mod": "moderate climbs", "st_th_weak": "weak climbs",
        "st_sun_match": "as expected", "st_sun_partial": "partly different", "st_sun_contra": "different than expected",
        "st_md_agree": "models agree", "st_md_partial": "one open point", "st_md_uncertain": "models disagree",
        "fx_dwd": "DWD", "fx_signature": "signature", "fx_sig_yes": "yes", "fx_sig_no": "none",
        "fx_dp": "ΔP Alps", "fx_gust": "gust", "fx_t850": "T850", "fx_thunder_none": "no thunderstorms",
        "fx_ground": "ground ≈", "fx_peak": "peak",
        "md_agree":      "Verdict: The models agree on wind, precipitation and cloud.",
        "md_partial":    "Verdict: The models agree on {agree}, but not on {q}",
        "md_uncertain":  "Verdict: The models contradict each other — on {q}",
        "md_q":          "{what} {zone} (comparison point {place}): {groups}.",
        "md_grp":        "{models} {verb} {label}",
        "md_lab_wind_mid": "flyable wind", "md_lab_cloud_mid": "half overcast",
        "md_what_wind":  "wind", "md_what_rain": "precipitation", "md_what_cloud": "cloud",
        "md_lab_wind_hi": "windy to blown out", "md_lab_wind_lo": "calm wind",
        "md_lab_rain_hi": "precipitation", "md_lab_rain_lo": "dry",
        "md_lab_cloud_hi": "overcast", "md_lab_cloud_lo": "little cloud",
        "md_verb_one":   "sees", "md_verb_many": "see",
        "md_var_wind":   "wind", "md_var_rain": "precipitation", "md_var_cloud": "cloud",
        "md_place_alpennordhang": "Interlaken", "md_place_wallis": "Sion", "md_place_tessin": "Locarno", "md_place_graubuenden_engadin": "Chur",
        "su_exp_high":  "{Press} suggests plenty of sunshine",
        "su_exp_low":   "{Press} suggests a lot of cloud",
        "su_exp_flat":  "The transitional situation suggests changeable cloud",
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
        "th_exp_high":  "{Press} suggests subsidence and a capped cloud base",
        "th_exp_low":   "{Press} suggests a high base but overdevelopment",
        "th_exp_flat":  "The transitional situation suggests no clear stratification",
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
        "front_none":   "No front within the forecast window (DWD).",
        # verdict — forecast data, never a final statement
        # situation in three short sentences: influence -> pressure -> forecast data
        "lg_between":      "Between {a} and {b}: {strength} {sector} flow with {air}.",
        "lg_single":       "{a}: {strength} {sector} flow with {air}.",
        "lg_nocenter":     "{strength} {sector} flow with {air}.",
        "lg_center":       "{ctype} {name}",
        "lg_air_SW":       "humid Mediterranean air", "lg_air_S": "a southerly flow, foehn risk in the north",
        "lg_air_SE":       "a southerly flow, foehn risk in the north", "lg_air_W": "mild Atlantic air",
        "lg_air_NW":       "cool north-westerly air", "lg_air_N": "cool northerly air",
        "lg_air_NE":       "dry continental air, Bise possible", "lg_air_E": "dry continental air, Bise possible",
        "lg_sector_N":     "northerly", "lg_sector_NE": "north-easterly", "lg_sector_E": "easterly",
        "lg_sector_SE":    "south-easterly", "lg_sector_S": "southerly", "lg_sector_SW": "south-westerly",
        "lg_sector_W":     "westerly", "lg_sector_NW": "north-westerly",
        "lg_strength_schwach": "light", "lg_strength_maessig": "moderate",
        "lg_strength_kraeftig": "strong", "lg_strength_stuermisch": "stormy",
        "lg_pressure":     "{regime} {trend} — {meaning}.",
        "lg_regime_hoch":  "High pressure", "lg_regime_tief": "Low pressure", "lg_regime_neutral": "Pressure",
        "lg_trend_up":     "rising", "lg_trend_down": "falling", "lg_trend_flat": "steady",
        # what it means for the weather — high: stable and dry, low: unsettled
        "lg_mean_hoch_up": "high-pressure influence consolidating, stable and mostly dry weather",
        "lg_mean_hoch_flat": "stable, mostly dry weather",
        "lg_mean_hoch_down": "the high is giving way, weather turning more fragile",
        "lg_mean_tief_up": "the low is moving off, weather slowly calming down",
        "lg_mean_tief_flat": "unsettled, cloud and rain",
        "lg_mean_tief_down": "low-pressure influence strengthening, unsettled with rain",
        "lg_mean_neutral_up": "high-pressure influence growing, weather calming down",
        "lg_mean_neutral_flat": "transitional, changeable",
        "lg_mean_neutral_down": "low-pressure influence growing, weather turning more unsettled",
        "lg_data_match":   "{models} confirms it: {rain}{rain_trend}, {wind}.",
        "lg_data_partial": "{models} only partly fits: {rain}{rain_trend}, {wind}.",
        "lg_data_contra":  "{models} contradicts it: {rain}{rain_trend}, {wind}.",
        "lg_rain_fading":  " and fading during the day",
        "lg_mean_calm_north": "high-pressure influence growing, weather calming down on the north side of the Alps",
        "lg_rain_south_growing": "mostly dry, showers on the south side of the Alps increasing in the afternoon",
        "lg_mean_calm_not_yet": "high-pressure influence growing but not arriving yet",
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
        # foehn/bise: synoptic claim against the forecast data
        "fb_foehn_yes":     "{Side} foehn situation: pressure difference of {dp} hPa across the Alps. {models} confirms it — gusts up to {gust} km/h at the lee forecast point {station}{windows}.",
        "fb_foehn_aloft":   "{Side} foehn situation: pressure difference of {dp} hPa across the Alps, but at the lee forecast point {station} {models} shows hardly any gusts (up to {gust} km/h) — the foehn stays aloft.",
        "fb_foehn_no":      "No foehn: the pressure difference across the Alps stays below the 4 hPa threshold at {dp} hPa.{strong}",
        "fb_foehn_no_nodp": "No foehn: no notable pressure difference across the Alps.{strong}",
        "fb_strong_none":   " {models} confirms it: no strong winds at the launch sites.",
        "fb_strong_some":   " {models} nevertheless shows strong winds at individual launch sites: gusts up to {gust} km/h from the {dir} ({spot}, {alt} m, {when}){cmp} — upper wind, not foehn.",
        "fb_models":        "; the models disagree, CH2 sees only {ch2} km/h",
        "fb_station_nord":  "Zurich", "fb_station_sued": "Lugano",
        "fb_bise_yes":      "Bise: pressure difference north-east–south of {dp} hPa and upper wind from the north-east — on the Plateau {models} shows north-easterly wind up to {kmh} km/h at {share} % of launch sites.",
        "fb_bise_yes_noground": "Bise according to the synoptic picture (pressure difference {dp} hPa, upper wind north-east), but {models} shows hardly any north-easterly wind on the Plateau — weak or later.",
        "fb_bise_no":       "No Bise: {reason} — {models} confirms it: no north-easterly wind on the Plateau.",
        "fb_bise_no_ground": "No Bise in the synoptic picture ({reason}), but {models} shows locally north-easterly wind up to {kmh} km/h on the Plateau.",
        "fb_reason_dp":     "the north-east–south pressure difference is too weak ({dp} hPa)",
        "fb_reason_dir":    "the upper wind comes from the {sector} instead of the north-east",
        "fb_reason_both":   "pressure difference and upper wind do not fit ({dp} hPa, {sector})",
        "fb_side_nord":     "North", "fb_side_sued": "South",
        "fb_win_from":      ", from the {when}",
        # stability: expectation from the synoptic picture against CAPE / thunderstorms / overdevelopment
        "lb_expect":        "{air}{press}",
        "lb_air_humid":     "The humid {sector} air suggests instability",
        "lb_air_cool":      "The cool {sector} air suggests showers and instability on the north side",
        "lb_air_neutral":   "The {sector} flow brings no distinctly unstable air",
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
        "front_today_in":     "{Day} the {typ} is expected to {art_inf} {zone} {when}{unsicher}{prov}.",
        "front_sig_yes":      "The DWD forecast indicates a {typ} over {zone}. {Day} it passes around {hour_full} — {models} confirms it: {belege}.",
        "front_fazit_none_more": "No further front is in sight within the 3-day window.",
        "front_sig_dwd_only": "The DWD forecast indicates a {typ} over {zone} {day} {when}. {models} does not confirm it: no signature ({gegen}) — the front is likely weakening or dissolving.",
        "front_sig_none":     "The DWD forecast indicates no front over Switzerland. {Day} none passes — {models} confirms it: {gegen}.",
        "ev_druck":           "a pressure rise",
        "ev_drehung":         "wind veering to the {sector}",
        "ev_kalt":            "cooling aloft",
        "ev_warm":            "warming aloft",
        "ev_regen":           "rain",
        "gv_sprung":          "pressure jump of {val} hPa in 3 h ({zone})",
        "gv_druck_flach":     "no pressure jump",
        "gv_drehung":         "no wind shift",
        "gv_regen":           "no rain",
        "front_generic":      "front",
        "sectors":            "north,north-east,east,south-east,south,south-west,west,north-west",
        "front_prev_run":     " (yesterday's run; this morning {dist} km to the {dir})",
        "front_fazit_in_more": "Forecast data suggest a further {typ} {art} {zone} {day} {when}{unsicher}.",
        "front_today_none":   "{Day} no front is expected.",
        "front_passed":       "{When} the {typ} passed over {zone} (DWD analysis) — {day} on its rear side.",
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
        "foehn_none":   "No foehn.",
        "foehn_line":   "{side} foehn {level}, {h} h.",
        "bise_none":    "No bise.",
        "bise_line":    "Bise {strength}, ΔP {dp} hPa.",
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
        "w_foehn":      "{side} foehn {level} on {days} ({h}).",
        "w_storm":      "Upper wind up to {kmh} km/h ({days}) — expect ≈ {ground} km/h at ground level.",
        "w_thunder":    "Thunderstorm cells in the flying window: {zones} ({days}). High false-alarm rate at a 5 % base rate — verify on site.",
        "w_overdev":    "Overdevelopment possible: {zones} ({days}). Soft early warning, not an alarm.",
        "w_shear":      "Wind shear on {days} — thermals get torn apart, see regions.",
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
        "sev_stop":     "stop",
        "sev_warn":     "warning",
        "alps_north":   "northern Alps",
        "alps_south":   "southern Alps",
        "warnings_ch":  "Warnings · Switzerland overall",
        "src_line":     "Forecast data: {surface} (surface), {pl} (upper levels) — MeteoSwiss/DWD via Open-Meteo · Synoptic pattern: ECMWF IFS · Fronts: DWD",
        "hz_RAIN": "Rain", "hz_THUNDER": "Thunderstorms", "hz_FOEHN": "Foehn", "hz_BISE": "Bise",
        "hz_WIND": "Strong wind",
        "hz_none":      "No hazard across Switzerland.",
        # cause per warning from the synoptic picture — warning = data, cause = situation
        "hz_cause_rain_south": "— the humid {sector} air piles up in the south.",
        "hz_cause_rain_north": "— the {sector} air piles up on the Northern Alps.",
        "hz_cause_rain_front": "— frontal passage.",
        "hz_cause_rain_flow":  "— {sector} flow.",
        "hz_cause_wind_aloft": "— the {sector} upper wind reaches down into the valleys.",
        "hz_cause_wind_gusts": "— gusty wind.",
        "hz_cause_foehn":      "— pressure difference of {dp} hPa across the Alps.",
        "hz_cause_thunder":    "— humid, unstable air{cap}.",
        "hz_cause_thunder_cap": ", capped in the north",
        "hz_cause_bise":       "— north-east–south pressure difference of {dp} hPa.",
        "hz_code_rain": "Rain {zones}, {extent} and {intensity}.",
        "hz_extent_widespread": "widespread",
        "hz_extent_scattered": "in places",
        "hz_extent_isolated": "isolated",
        "hz_rain_light": "light",
        "hz_rain_moderate": "moderate",
        "hz_rain_heavy": "heavy",
        "hz_rain_severe": "heavy, locally torrential",
        "hz_code_thunder": "Model thunderstorms {zones}.",
        "hz_code_foehn": "{side} foehn {level}, {h} h — lee side {zones}.",
        "hz_code_wind": "{classes}.",
        "hz_class_verblasen": "blown out", "hz_class_stark_eingeschraenkt": "heavily restricted",
        "win_morning": "morning", "win_midday": "midday",
        "win_afternoon": "afternoon", "win_evening": "evening",
        "hz_windows":   "{spans}.",
        "hz_run_single": "in the {a}",
        "hz_run_open":   "from the {a}",
        "hz_run_span":   "{a} to {b}",
        "hz_run_join":   " and again ",
        "hz_windows_but": "{main}, {exception}",
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
        "sum_BISE": "bise", "sum_WIND": "strong wind",
        "wind_meaning": "Average across all Swiss spots, 12:00",
        "wind_range":   "{lo}–{hi} km/h across regions",
        "wind_range_note": "range of regional peaks at 700 hPa, strongest {region} {hour}h",
        "wind_ground_range": "≈ {lo}–{hi} km/h expected at ground level (⅔ rule)",
        "wind_fazit_match": "The Swiss average ({models}) says {strength} {sector} flow, and the regions stay in that class: {lo} to {hi} km/h, strongest {region} in the {when}.",
        "wind_fazit_stronger": "The Swiss average ({models}) says {strength} {sector} flow — regionally it is one class stronger: up to {hi} km/h {region} in the {when}, i.e. {cls}. The average understates it.",
        "wind_fazit_weaker": "The Swiss average ({models}) says {strength} {sector} flow — even the strongest region stays below that: at most {hi} km/h ({region}).",
        "wcls_schwach": "light", "wcls_maessig": "moderate", "wcls_kraeftig": "strong", "wcls_stuermisch": "stormy",
        "wstr_schwach": "light", "wstr_maessig": "moderate", "wstr_kraeftig": "strong", "wstr_stuermisch": "stormy",
        "hour_morning": "morning", "hour_midday": "midday", "hour_afternoon": "afternoon", "hour_evening": "evening",
        "chip_rain_widespread": "Widespread rain",
        "chip_rain_scattered":  "Rain in parts of the region",
        "chip_rain_isolated":   "Isolated showers",
        "chip_rain":            "Rain",
        "chip_aloft_warn":  "Upper wind above {kmh} km/h",
        "chip_aloft_stop":  "Strong upper wind above {kmh} km/h",
        "chip_ground_warn": "Ground wind above {kmh} km/h",
        "chip_ground_stop": "Strong ground wind above {kmh} km/h",
        "chip_foehn_moderate": "Moderate foehn",
        "chip_foehn_strong":   "Strong foehn",
        "chip_thunder":        "Thunderstorms possible",
        "chip_thunder_risk":   "Thunderstorm risk {pct}%",
        "chip_clouds":         "Cloud down to launch height",
        "lage_Hochdrucklage": "High pressure", "lage_Tiefdrucklage": "Low pressure",
        "lage_Nordfoehnlage": "North foehn", "lage_Suedfoehnlage": "South foehn",
        "lage_Foehnlage (wechselnd)": "Foehn (changing side)",
        "lage_Bisenlage": "Bise", "lage_Genua-Tief": "Genoa low",
        "lage_Uebergangslage": "Transitional", "lage_unbestimmt": "undetermined",
        "zb_alpennordhang_west": "northern Alps west",
        "zb_alpennordhang_ost":  "northern Alps east",
        "hz_windows_staggered": "Staggered: from the {a} {zones}, later elsewhere.",
        "hz_shape_ganztags": "all day",
        "hz_shape_ab":  "from {a} onwards",
        "hz_shape_bis": "until {b}",
        "hz_shape_nur": "in the {a} only",
        "hz_shape_spanne": "from {a} to {b}",
        "hz_shape_wechselnd": "in the {a} and again in the {b}",
        "zones_all":    "countrywide",
        "zones_except": "everywhere except {zone}",
        "zone_in_alpennordhang": "in the northern Alps",
        "zone_in_wallis": "in Valais",
        "zone_in_tessin": "in Ticino",
        "zone_in_graubuenden_engadin": "in the Grisons",
        "hz_course_zunehmend": "Builds through the day.",
        "hz_course_abflauend": "Eases off through the day.",
        "hz_course_gleich":    "Stays at the same strength all day.",
        "hz_foehn_gust":       "Gusts up to {kmh} km/h in the lee.",
        "hz_tm_vorbei":     "Next day: over.",
        "hz_tm_abklingend": "Next day: weaker.",
        "hz_tm_zunehmend":  "Next day: stronger.",
        "hz_tm_gleich":     "Next day: unchanged.",
        "airspace_note": "Airspace (DABS), launch site and windsock are checked by the pilot on site — no forecast can do that.",
        "days_ahead":   "The days ahead",
        "week_hint":    "Top of each day: average of your regions (1–5). Safe when at least half are safe; Not safe when more than half are not safe; otherwise Caution. Below, each region with its own rating.",
        "regions_word": "Your regions",
        "situation_ch":  "Overall situation Switzerland",
        "wl_rain": "rain", "wl_dry": "dry", "wl_high": "high pressure", "wl_low": "low pressure",
        "wl_windy": "strong upper wind", "wl_calm": "calm", "wl_foehn_n": "north foehn", "wl_foehn_s": "south foehn", "wl_bise": "bise",
    },
}


def _lbl(key: str) -> str:
    lang = _lang()
    return _L3[lang].get(key) or _L2[lang].get(key) or key


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


def _sentences(text: str, n: int) -> str:
    """Die ersten n ganzen Saetze. Trennt nur an Satzzeichen + Leerzeichen +
    Grossbuchstabe, damit 'z. B. ' oder '1.5 m/s' nicht zerschnitten werden."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ])", (text or "").strip())
    return " ".join(p for p in parts[:n] if p)


_WEEKDAYS = (("monday", "montag"), ("tuesday", "dienstag"), ("wednesday", "mittwoch"),
             ("thursday", "donnerstag"), ("friday", "freitag"), ("saturday", "samstag"),
             ("sunday", "sonntag"))


def _situation_sentences(text: str, date: str, n: int) -> str:
    """Lage in n Saetzen fuer den Fokus-Tag. Der Wochen-Lead erzaehlt Tag fuer
    Tag ('Sunday stays dry … on Monday foehn …') — Saetze, die einen ANDEREN
    Wochentag nennen, fallen raus, sonst steht am Montag 'Sunday stays dry'."""
    try:
        own = _WEEKDAYS[datetime.fromisoformat(date).weekday()]
    except (TypeError, ValueError):
        return _sentences(text, n)
    others = [w for day in _WEEKDAYS if day != own for w in day]
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ])", (text or "").strip())
    keep = [p for p in parts if p and not any(re.search(rf"\b{w}\b", p, re.I) for w in others)]
    return " ".join(keep[:n])


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
    """Das eine Auffaellige je Tag: Foehn/Bise vor Schauerbeginn vor nichts."""
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


def _zone_sentences(wetterlage: dict, dates: list, date: str) -> list:
    out = []
    idx = dates.index(date) if date in dates else -1
    for z in ((wetterlage.get("llm_overview") or {}).get("zones")) or []:
        days = z.get("days") or []
        if 0 <= idx < len(days) and isinstance(days[idx], dict):
            text = (days[idx].get("text") or "").strip()
            # "Wednesday: ..." — den Wochentags-Praefix abschneiden
            text = re.sub(r"^[A-Za-zäöü]+:\s*", "", text)
            out.append({
                "zone": z.get("zone", ""),
                "label": z.get("label") or _zone_name(z.get("zone", "")),
                "text": _first_sentences(text, 320),
                "hint": (days[idx].get("flight_hint") or "").strip(),
            })
    return out


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
    Worten: {rain, rain_trend, wind, meaning} — inkl. Logik-Abgleich mit der
    Druck-Tendenz. Von Block 1 (Lage) und den Wochenkacheln genutzt."""
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
        rain, rain_key = _lbl("lg_rain_mostly_dry"), "mostly_dry"
    elif wet < 0.05:
        rain, rain_key = _lbl("lg_rain_dry"), "dry"
    elif wet < 0.15 and wet_s is not None and wet_s >= 0.2 and (wet_n or 0) < 0.1:
        rain, rain_key = _lbl("lg_rain_south_only"), "south_only"
    elif wet < 0.15 and wet_n is not None and wet_n >= 0.2 and (wet_s or 0) < 0.1:
        rain, rain_key = _lbl("lg_rain_north_only"), "north_only"
    elif wet < 0.15:
        rain, rain_key = _lbl("lg_rain_mostly_dry"), "mostly_dry"
    elif wet < 0.4:
        rain, rain_key = _lbl("lg_rain_partly"), "partly"
    else:
        rain, rain_key = _lbl("lg_rain_wide"), "wide"

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
    rain_trend, trend_key = "", ""
    if early is not None and late is not None and wet is not None and wet >= 0.05:
        if early >= 0.1 and late <= early * 0.5:
            rain_trend, trend_key = _lbl("lg_rain_fading"), "fading"
        elif late >= 0.1 and late >= early * 2:
            rain_trend, trend_key = _lbl("lg_rain_growing"), "growing"

    warn = _wavg(wp, "share_wind_warn")
    crit = _wavg(wp, "share_wind_crit")
    warn_n = ((wp.get("alpennord") or {}).get("share_wind_warn"))
    warn_s = ((wp.get("alpensued") or {}).get("share_wind_warn"))
    if warn is None or warn < 0.3:
        wind, wind_key = _lbl("lg_wind_calm"), "calm"
    elif (crit or 0) >= 0.3:
        wind, wind_key = _lbl("lg_wind_strong"), "strong"
    elif warn < 0.6:
        wind, wind_key = _lbl("lg_wind_partly"), "partly"
    else:
        wind, wind_key = _lbl("lg_wind_wide"), "wide"
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
    meaning = _lbl(f"lg_mean_{regime}_{tkey}")
    calming = tkey == "up" or (regime == "hoch" and tkey == "flat")
    if calming and rain_trend == _lbl("lg_rain_growing"):
        if rain == _lbl("lg_rain_south_only"):
            meaning, rain, rain_trend = _lbl("lg_mean_calm_north"), _lbl("lg_rain_south_growing"), ""
            rain_key, trend_key = "south_only", "growing"
        else:
            meaning = _lbl("lg_mean_calm_not_yet")
    unsettled = tkey == "down" or (regime == "tief" and tkey == "flat")
    if unsettled and rain in (_lbl("lg_rain_dry"), _lbl("lg_rain_mostly_dry"))             and rain_trend != _lbl("lg_rain_growing"):
        rain = _lbl("lg_rain_for_now") + rain
    # Urteil Block 1: Erwartung aus Druck/Tendenz (beruhigend / unbestaendig /
    # Uebergang) gegen die Prognosedaten (Regen- und Windmuster CH-weit).
    # Stufe 0 = trocken & ruhig, 1 = teils/einseitig, 2 = verbreitet/kraeftig.
    wet_level = {"dry": 0, "mostly_dry": 0, "south_only": 1, "north_only": 1, "partly": 1, "wide": 2}[rain_key]
    if trend_key == "growing":
        wet_level = min(2, wet_level + 1)
    wind_level = {"calm": 0, "partly": 1, "wide": 2, "strong": 2}[wind_key]
    level = max(wet_level, wind_level)
    if calming:
        verdict = ("match", "partial", "contra")[level]
    elif unsettled:
        verdict = ("contra", "partial", "match")[level]
    else:                       # Uebergangslage: wechselhaft ist erwartet
        verdict = "match" if level <= 1 else "partial"
    return {"rain": rain, "rain_trend": rain_trend, "wind": wind, "meaning": meaning,
            "verdict": verdict}


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
    """Die Lage fuer die ganze Schweiz in drei kurzen Saetzen, ohne Zahlen:
    Einfluss (Druckzentren -> Stroemung -> Luftmasse), Druck mit Tendenz und
    Bedeutung, und was die Prognosedaten daraus machen (Wind je Zone, Regen
    mit Seite und Beginn). Deterministisch — die Form, die der Skill auch von
    der KI verlangt."""
    wl = wetterlage or {}
    if not wl:
        return {"fazit": "", "verdict": ""}
    lang = _lang()
    centers = []
    for d in wl.get("pressure_centers_per_day") or []:
        if d.get("date") == date:
            for c in d.get("centers") or []:
                ctype = _CENTER_TYPE[lang].get(c.get("type"), c.get("type", ""))
                centers.append(_lbl("lg_center").format(
                    ctype=ctype, name=_center_name(c.get("region_label", ""))))
            break
    flow = _per_day_index(wl.get("flow_overhead"), [date]).get(date) or {}
    abbr = _SECTOR_ABBR.get(flow.get("sector", ""), "")
    sector = _lbl("lg_sector_" + abbr) if abbr else ""
    air = _lbl("lg_air_" + abbr) if abbr else ""
    strength = _lbl("lg_strength_" + (flow.get("strength") or "maessig"))
    if len(centers) >= 2:
        s1 = _lbl("lg_between").format(a=centers[0], b=centers[1], strength=strength, sector=sector, air=air)
    elif centers:
        s1 = _lbl("lg_single").format(a=centers[0], strength=strength, sector=sector, air=air)
    else:
        s1 = _lbl("lg_nocenter").format(strength=strength, sector=sector, air=air)
    s1 = s1[0].upper() + s1[1:]

    regime, tkey = _lage_regime(wl, date)
    s2 = _lbl("lg_pressure").format(regime=_lbl("lg_regime_" + regime), trend=_lbl("lg_trend_" + tkey),
                                    meaning=_lbl(f"lg_mean_{regime}_{tkey}"))

    e = _lage_effects(wl, date, regime, tkey)
    rain, rain_trend, wind, meaning = e["rain"], e["rain_trend"], e["wind"], e["meaning"]
    s2 = _lbl("lg_pressure").format(regime=_lbl("lg_regime_" + regime), trend=_lbl("lg_trend_" + tkey),
                                    meaning=meaning)
    # Datensatz als eigener Satz mit Modellname — nie "unsere Prognose"
    s3 = _lbl("lg_data_" + e["verdict"]).format(models=_model_words(), rain=rain, rain_trend=rain_trend, wind=wind)
    return {"fazit": " ".join((s1, s2, _capitalize(s3))), "verdict": e["verdict"]}


def _sector_word(deg) -> str:
    names = _lbl("sectors").split(",")
    return names[int(((float(deg) + 22.5) // 45) % 8)]


def _front_signature(wetterlage: dict | None, date: str) -> tuple[dict | None, dict]:
    """(beste Signatur des Tages mit 'zone', Tagesverlauf je Zone) aus
    wetterlage['frontsignatur'] — leer, wenn der Kontext das Feld nicht hat."""
    fs = (wetterlage or {}).get("frontsignatur") or {}
    day = next((d for d in fs.get("per_day") or [] if d.get("date") == date), None)
    if not day:
        return None, {}
    best = None
    for z, sig in (day.get("zones") or {}).items():
        if not sig:
            continue
        score = (sig.get("druck_hpa") or 0) + abs(sig.get("t850_k") or 0) + min(sig.get("regen_mm") or 0, 5) / 2
        if best is None or score > best[0]:
            best = (score, dict(sig, zone=z))
    return (best[1] if best else None), (day.get("verlauf") or {})


def _evidence_words(sig: dict) -> str:
    parts = [_lbl("ev_druck"), _lbl("ev_drehung").format(sector=_sector_word(sig["drehung"][1]))]
    t = sig.get("t850_k")
    if t is not None and t <= -2.0:
        parts.append(_lbl("ev_kalt"))
    elif t is not None and t >= 2.0:
        parts.append(_lbl("ev_warm"))
    if (sig.get("regen_mm") or 0) >= 1.0:
        parts.append(_lbl("ev_regen"))
    return ", ".join(parts)


def _counter_words(verlauf: dict, zone: str = "") -> str:
    """Gegenbeleg 'keine Front': was in ALLEN Zonen fehlt (oder in der
    genannten Zone, wenn die DWD-Karte dort eine Front zeichnet). Der Druck
    zaehlt als Sprung, nicht als Tagesbilanz — eine Front ist ein Knick,
    keine Steigung; und das Maximum ueber die Zonen mit Namen, weil ein
    Mittel eine Front ueber nur einer Zone wegrechnet. Bis 23.09.2026 stand
    hier die 06->22-h-Bilanz der ersten Zone im Dict — die war im September
    durch den Tagesgang fast immer "steigend" und widersprach der Kopfzeile."""
    items = ([(zone, verlauf[zone])] if zone and verlauf.get(zone)
             else [(z, v) for z, v in (verlauf or {}).items() if v])
    if not items:
        return _lbl("gv_druck_flach") + ", " + _lbl("gv_drehung")
    z_max, sprung = max(((z, v.get("sprung_max_hpa") or 0.0) for z, v in items),
                        key=lambda t: abs(t[1]))
    if abs(sprung) >= config.SYNOPTIC_DRUCK_SPRUNG_HPA:
        parts = [_lbl("gv_sprung").format(val=f"{sprung:+.1f}", zone=_zone_name(z_max))]
    else:
        parts = [_lbl("gv_druck_flach")]
    if max((v.get("max_drehung_deg") or 0) for _, v in items) < 40:
        parts.append(_lbl("gv_drehung"))
    if max((v.get("regen_mm") or 0) for _, v in items) < 1.0:
        parts.append(_lbl("gv_regen"))
    return ", ".join(parts)


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
        return {"fazit": "", "rear": False, "dwd": False, "dwd_typ": ""}
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
    # Entscheidend ist, was die EIGENEN Prognosedaten fuer den Tag zeigen
    # (Druck, Winddrehung, T850, Regen) — die DWD-Prognose gibt den Namen, die
    # eigene Prognose gibt das Urteil. Ohne Signatur zieht keine Front durch, auch
    # wenn die Karte eine zeichnet: dann schwaecht sie sich ab.
    sig, verlauf = _front_signature(wetterlage, focus)
    if sig:
        if today_hits:
            _, a, _ = today_hits[0]
            today_typ = a.get("typ", "")
            typ_txt = _typ(a)
        else:
            today_typ = sig.get("typ_hinweis") or ""
            typ_txt = (_typ({"typ": today_typ}) if today_typ else _lbl("front_generic"))
        first = _lbl("front_sig_yes").format(models=_model_words(),
            Day=day_cap, typ=typ_txt, zone=_zone_object(sig["zone"]), zone_dat=_zone_dat(sig["zone"]),
            hour=sig["hour"][:2], hour_full=sig["hour"], belege=_evidence_words(sig))
    elif today_hits:
        local, a, prov = today_hits[0]
        today_typ = a.get("typ", "")
        if verlauf:
            first = _lbl("front_sig_dwd_only").format(models=_model_words(),
                typ=_typ(a), day=day_word, zone=_zone_object(a.get("zone", "")),
                zone_dat=_zone_dat(a.get("zone", "")),
                when=_when(a.get("fenster_von_utc") or a.get("durchgang_median_utc") or ""),
                gegen=_counter_words(verlauf, a.get("zone", "")))
            first = first[0].upper() + first[1:]
        else:
            unsicher = bool(a.get("randwert")) or (a.get("anteil") or 0) < 0.1
            first = _lbl("front_today_in").format(
                Day=day_cap, typ=_typ(a), zone=_zone_object(a.get("zone", "")),
                when=_when(a.get("fenster_von_utc") or a.get("durchgang_median_utc") or ""),
                art=_art(a), art_inf=_art(a, infinitive=True),
                unsicher=_lbl("front_unsicher") if unsicher else "", prov=prov)
    elif verlauf:
        first = _lbl("front_sig_none").format(models=_model_words(), Day=day_cap, gegen=_counter_words(verlauf))
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
    return {"fazit": first, "rear": bool(passed),
            "dwd": bool(today_hits), "dwd_typ": today_typ or ""}


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


def _modelle_block(wetterlage: dict, date: str) -> dict:
    """Block 8: sind sich die Modelle einig? Fazit zuerst; bei Uneinigkeit
    ALLE Modelle mit Wert, dazu Mehrheit und Ausreisser, dann die offene
    Pilotenfrage. Der Vergleichspunkt (Interlaken, Sion, Locarno, Chur) steht
    im Satz. Keine separate Zahlenzeile — die Werte sind im Text."""
    wl = wetterlage or {}
    mv = wl.get("modell_vergleich") or {}
    day = _per_day_index(mv, [date]).get(date) or {}
    zones = {z: v for z, v in (day.get("zones") or {}).items() if v}
    if not zones:
        return {}
    names = mv.get("models") or {}
    thr = mv.get("thresholds") or {}
    excl = set(thr.get("spread_excludes") or [])
    lang = _lang()
    joiner = " und " if lang == "de" else " and "

    def zone_in(z):
        if lang == "de":
            prep = "am " if z == "alpennordhang" else ("im " if _ZONE_ARTICLE_DAT["de"].get(z) else "in ")
            return prep + _zone_name(z)
        return "in " + _ZONE_ARTICLE_DAT["en"].get(z, "") + _zone_name(z)

    def _list(models):
        """'A, B und C' statt 'A und B und C'."""
        if len(models) <= 1:
            return "".join(models)
        return ", ".join(models[:-1]) + joiner + models[-1]

    def question(kind, z, field, unit, classify):
        """Satz fuer eine Groesse: welche Modelle sehen was — Klassen statt Zahlen."""
        vals = {names.get(k, k): v[field] for k, v in zones[z]["models"].items() if v.get(field) is not None}
        groups: dict[str, list[str]] = {}
        for m, v in vals.items():
            groups.setdefault(classify(v), []).append(m)
        order = ["hi", "mid", "lo"]
        parts = []
        for cls in sorted(groups, key=lambda c: (-len(groups[c]), order.index(c))):
            ms = groups[cls]
            parts.append(_lbl("md_grp").format(models=_list(ms),
                                               verb=_lbl("md_verb_many" if len(ms) > 1 else "md_verb_one"),
                                               label=_lbl(f"md_lab_{kind}_{cls}")))
        return _lbl("md_q").format(what=_lbl("md_what_" + kind), zone=zone_in(z),
                                   place=_lbl("md_place_" + z), groups=", ".join(parts))

    questions = []
    wz = max(zones, key=lambda z: zones[z].get("gust_spread_kmh") or 0)
    if (zones[wz].get("gust_spread_kmh") or 0) >= thr.get("gust_disagree_kmh", 20):
        questions.append(("wind", question("wind", wz, "gust_kmh", " km/h",
                                           lambda v: "hi" if v >= 25 else "mid" if v >= 15 else "lo")))
    for z, v in zones.items():
        n, wet = v.get("rain_n") or 0, v.get("rain_wet_models") or 0
        if n >= 2 and 0 < wet < n:
            questions.append(("rain", question("rain", z, "rain_mm", " mm",
                                               lambda v: "hi" if v >= thr.get("wet_mm", 1.0) else "lo")))
            break
    cz = max(zones, key=lambda z: zones[z].get("cloud_spread_pct") or 0)
    if (zones[cz].get("cloud_spread_pct") or 0) >= thr.get("cloud_agree_pct", 30):
        questions.append(("cloud", question("cloud", cz, "cloud_pct", " %",
                                            lambda v: "hi" if v >= 60 else "mid" if v >= 30 else "lo")))

    open_kinds = {k for k, _ in questions}
    agree = [_lbl("md_var_" + k) for k in ("wind", "rain", "cloud") if k not in open_kinds]
    if not questions:
        text, verdict = _lbl("md_agree"), "agree"
    elif len(questions) == 1:
        text, verdict = _lbl("md_partial").format(agree=_list(agree), q=questions[0][1]), "partial"
    else:
        text, verdict = _lbl("md_uncertain").format(q=" ".join(qq[1] for qq in questions)), "uncertain"
    return {"fazit": text, "num": {}, "verdict": verdict,
            "agree": [k for k in ("wind", "rain", "cloud") if k not in open_kinds],
            "open": [k for k, _ in questions]}


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
        air = _lbl("lb_air_neutral").format(sector=sector)
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


def _foehn_bise_fazit(wetterlage: dict, date: str) -> str:
    """Block 3: was die Synoptik zu Foehn und Bise sagt (Druckgefaelle,
    Hoehenwind) und ob die Prognosedaten es zeigen (Lee-Boeen, Nordostwind
    im Mittelland). Leer, wenn der Kontext die Abgleich-Felder nicht hat."""
    fo = _per_day_index(wetterlage.get("foehn"), [date]).get(date) or {}
    claim, lee = fo.get("claim") or {}, fo.get("lee") or {}
    sw = _per_day_index(wetterlage.get("starkwind_punkte"), [date]).get(date) or {}
    bi = _per_day_index(wetterlage.get("bise"), [date]).get(date) or {}
    bb = _per_day_index(wetterlage.get("bise_boden"), [date]).get(date) or {}
    if not claim and not bb and not sw:
        return ""
    parts = []

    # --- Foehn: Anspruch (Druckgefaelle) gegen die Lee-Station — ein Punkt, von
    # dem wir wissen, dass er unten liegt (Zuerich fuer Suedfoehn, Lugano fuer
    # Nordfoehn). Startplaetze taugen dafuer nicht: welcher im Tal liegt, wissen
    # wir nicht.
    side = "sued" if fo.get("sued_active") else "nord" if fo.get("nord_active") else None
    if side:
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
                                      gust=int(gust), windows=windows))
    else:
        dps = [v for v in (claim.get("delta_p_sued_max_hpa"), claim.get("delta_p_nord_max_hpa"))
               if isinstance(v, (int, float))]
        # Starke Winde absolut, an einzelnen Prognosepunkten — mit Richtung,
        # Hoehe, Stunde und Modell-Uneinigkeit; bewusst ohne "Foehntal"
        strong = ""
        g = sw.get("max_gust_kmh") or 0
        if sw and g >= 40:
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
            strong = _lbl("fb_strong_none").format(models=_model_words())
        if dps:
            parts.append(_lbl("fb_foehn_no").format(dp=f"{max(dps):.0f}", strong=strong))
        else:
            parts.append(_lbl("fb_foehn_no_nodp").format(strong=strong))
    # --- Bise ---
    dp = bi.get("delta_p_hpa")
    ddeg = bi.get("wind_700_dir_deg")
    ne = isinstance(ddeg, (int, float)) and 30 <= ddeg <= 90
    dp_ok = isinstance(dp, (int, float)) and dp >= 4
    share, kmh = bb.get("share_ne"), bb.get("max_kmh") or 0
    ground = isinstance(share, (int, float)) and share >= 0.2
    sector = _lbl("lg_sector_" + _SECTOR_ABBR.get(bi.get("sector", ""), "")) if bi.get("sector") else (
        _sector_word(ddeg) if isinstance(ddeg, (int, float)) else "")
    dp_txt = f"{dp:+.0f}" if isinstance(dp, (int, float)) else "–"
    # Bise nur erwaehnen, wenn sie ein Thema ist: aktiv, Nordostwind am Boden,
    # oder der Hoehenwind hat eine Nord-/Ostkomponente. Bei Suedwest weiss
    # jeder Pilot, dass keine Bise kommt.
    ne_component = isinstance(ddeg, (int, float)) and (ddeg >= 330 or ddeg <= 120)
    if not (bi.get("active") or ground or ne_component):
        return " ".join(parts)
    if bi.get("active"):
        key = "fb_bise_yes" if ground else "fb_bise_yes_noground"
        parts.append(_lbl(key).format(models=_model_words(), dp=dp_txt, kmh=int(kmh),
                                      share=int(round(100 * (share or 0)))))
    else:
        if not dp_ok and not ne:
            reason = _lbl("fb_reason_both").format(dp=dp_txt, sector=sector)
        elif not dp_ok:
            reason = _lbl("fb_reason_dp").format(dp=dp_txt)
        else:
            reason = _lbl("fb_reason_dir").format(sector=sector)
        key = "fb_bise_no_ground" if ground else "fb_bise_no"
        parts.append(_lbl(key).format(models=_model_words(), reason=reason, kmh=int(kmh)))
    return " ".join(parts)


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


def _bise_text(wetterlage: dict, date: str) -> str:
    bi = _per_day_index(wetterlage.get("bise"), [date]).get(date) or {}
    if not bi.get("active"):
        return _lbl("bise_none")
    return _lbl("bise_line").format(strength=bi.get("strength") or "",
                                    dp=f"{float(bi.get('delta_p_hpa') or 0):+.1f}")


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
    bise = _per_day_index(wetterlage.get("bise"), dates)
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
        if fo.get("nord_active"):
            words.append(_lbl("wl_foehn_n"))
        if fo.get("sued_active"):
            words.append(_lbl("wl_foehn_s"))
        if (bise.get(date) or {}).get("active"):
            words.append(_lbl("wl_bise"))
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


def _decorate_chain(chain: dict, wetterlage: dict, date: str) -> None:
    """Status-Pille (ok / info / warn + Kurzlabel) und Fakten-Chips je Block —
    die visuelle Schicht ueber den Saetzen. Alles aus Feldern, die die Bloecke
    schon tragen; kein neuer Datenzugriff."""
    wl = wetterlage or {}

    def st(block, kind, label_key):
        chain[block]["status"] = kind
        chain[block]["status_label"] = _lbl(label_key)

    # Lage: Erwartung aus dem Druck gegen Regen-/Windmuster der Prognose
    lv = (chain.get("lage") or {}).get("verdict")
    if lv:
        st("lage", {"match": "ok", "partial": "info"}.get(lv, "warn"), "st_lage_" + lv)
    # Fronten
    sig, _ = _front_signature(wl, date)
    passed = bool(chain["fronts"].get("rear"))
    dwd_typ = chain["fronts"].get("dwd_typ") or ""
    if sig:
        st("fronts", "warn", "st_front_passes")
    elif chain["fronts"].get("dwd"):
        st("fronts", "info", "st_front_weak")
    elif passed:
        st("fronts", "info", "st_front_rear")
    else:
        st("fronts", "ok", "st_front_none")
    fo = _per_day_index(wl.get("foehn"), [date]).get(date) or {}
    sw = _per_day_index(wl.get("starkwind_punkte"), [date]).get(date) or {}
    chain["fronts"]["facts"] = [
        {"k": _lbl("fx_dwd"), "v": (_front_type(dwd_typ) if dwd_typ else "—")},
        {"k": _lbl("fx_signature"), "v": (_lbl("fx_sig_yes") + " " + sig["hour"][:2] + "h") if sig else _lbl("fx_sig_no")},
    ]
    # Foehn / Bise
    bi = _per_day_index(wl.get("bise"), [date]).get(date) or {}
    if fo.get("sued_active") or fo.get("nord_active"):
        st("foehn", "warn", "st_foehn_on")
    elif bi.get("active"):
        st("foehn", "warn", "st_bise_on")
    elif (sw.get("max_gust_kmh") or 0) >= 40:
        st("foehn", "info", "st_foehn_gusty")
    else:
        st("foehn", "ok", "st_foehn_off")
    claim = fo.get("claim") or {}
    dps = [v for v in (claim.get("delta_p_sued_max_hpa"), claim.get("delta_p_nord_max_hpa")) if isinstance(v, (int, float))]
    chain["foehn"]["facts"] = [
        {"k": _lbl("fx_dp"), "v": (f"{max(dps):.0f} hPa" if dps else "—")},
        {"k": _lbl("fx_gust"), "v": (f"{int(sw['max_gust_kmh'])} km/h" if sw.get("max_gust_kmh") else "—")},
    ]
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
        md["facts"] = [{"k": _lbl("md_var_" + k), "v": ("✓" if k in md.get("agree", []) else "✗")}
                       for k in ("wind", "rain", "cloud")]
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
        # Gesamtlage Schweiz in einem Satz: erster Satz des Wochen-Leads (der
        # beschreibt die Grosswetterlage), dazu der kurze Tages-Hinweis.
        # Ein kurzer KI-Satz je Tag (day_lines); aeltere Caches: erster
        # tagesreiner Satz des Leads statt frueher drei (zu viel Text)
        "situation": (_day_line(wetterlage, date)
                      or _situation_sentences(((wetterlage.get("llm_overview") or {})
                                               .get("short") or "").strip(), date, 1)),
        "day_hint": _day_summaries(wetterlage, dates).get(date, ""),
        "fronts": {**_front_block(fronts, passagen, dates, date, wetterlage),
                   "lines": _front_lines(fronts, passagen, date),
                   "zugbahn": _zugbahn_text(wetterlage, date)},
        "foehn": {"foehn": _foehn_text(wetterlage, date), "bise": _bise_text(wetterlage, date),
                  "fazit": _foehn_bise_fazit(wetterlage, date),
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
    """Gefahren-Eintrag des Tages: aus llm_overview.hazards (Schalter + KI-Saetze),
    sonst — aelterer Cache ohne das Feld — nur die Schalter, frisch gerechnet."""
    for h in ((wetterlage.get("llm_overview") or {}).get("hazards")) or []:
        if isinstance(h, dict) and h.get("date") == date and h.get("checks"):
            return h
    from engine.synoptic_llm import hazard_checks
    for h in hazard_checks(wetterlage):
        if h["date"] == date:
            return {**h, "items": []}
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


def _extent_word(wet_share) -> str:
    """Flaechenanteil -> Wort. Ein Pilot kann mit "93 % der Spots nass" nichts
    anfangen, mit "verbreitet" sofort."""
    v = float(wet_share or 0)
    if v >= config.SYNOPTIC_HAZARD_EXTENT_WIDESPREAD:
        return _lbl("hz_extent_widespread")
    if v >= config.SYNOPTIC_HAZARD_EXTENT_SCATTERED:
        return _lbl("hz_extent_scattered")
    return _lbl("hz_extent_isolated")


def _rain_word(p90_mm) -> str:
    """Spitzenintensitaet (P90 mm/h) -> Wort."""
    v = float(p90_mm or 0)
    if v >= config.SYNOPTIC_HAZARD_RAIN_MM_SEVERE:
        return _lbl("hz_rain_severe")
    if v >= config.SYNOPTIC_HAZARD_RAIN_MM_HEAVY:
        return _lbl("hz_rain_heavy")
    if v >= config.SYNOPTIC_HAZARD_RAIN_MM_MODERATE:
        return _lbl("hz_rain_moderate")
    return _lbl("hz_rain_light")


def _runs(hit: list) -> list:
    """Zusammenhaengende Fenster-Abschnitte: [morning, afternoon, evening] ->
    [[morning], [afternoon, evening]]."""
    order = [w[0] for w in config.SYNOPTIC_DAY_WINDOWS]
    idx = sorted(order.index(w) for w in hit)
    runs = []
    for i in idx:
        if runs and i == runs[-1][-1] + 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    return [[order[i] for i in r] for r in runs]


def _wechselnd_phrase(hit: list) -> str:
    """Jeder Abschnitt einzeln: "am Vormittag und wieder ab Nachmittag"."""
    last = config.SYNOPTIC_DAY_WINDOWS[-1][0]
    parts = []
    for r in _runs(hit):
        a, b = _lbl("win_" + r[0]), _lbl("win_" + r[-1])
        if len(r) == 1:
            parts.append(_lbl("hz_run_single").format(a=a))
        elif r[-1] == last:
            parts.append(_lbl("hz_run_open").format(a=a))
        else:
            parts.append(_lbl("hz_run_span").format(a=a, b=b))
    return _lbl("hz_run_join").join(parts)


def _shape_phrase(shape: dict) -> str:
    # "gemischt" wird in _hazard_windows_text je Zone aufgeloest
    if shape["shape"] == "wechselnd" and shape.get("hit"):
        return _wechselnd_phrase(shape["hit"])
    """"ab Nachmittag", "nur Vormittag", "Mittag bis Abend" — aus day_shape."""
    return _lbl("hz_shape_" + shape["shape"]).format(
        a=_lbl("win_" + shape["from"]), b=_lbl("win_" + shape["to"]))


def _hazard_windows_text(check: dict) -> str:
    """Tagesverlauf als Code-Satz. Unterscheiden sich die Zonen im Zeitpunkt,
    steht er je Zone — "Alpennordhang ab Mittag, Tessin nur Abend" ist die
    Information, nach der der Pilot morgens sucht."""
    from engine.synoptic_llm import _day_shape
    f = check.get("facts") or {}
    shape = f.get("day_shape")
    if not shape:
        return ""
    wins = f.get("windows") or {}
    per_zone = {z: _day_shape({z: w}) for z, w in wins.items()}
    per_zone = {z: sh for z, sh in per_zone.items() if sh}
    # Konsolidieren statt auflisten. Ein gemeinsamer Verlauf steht ohne Ort;
    # zwei Gruppen bekommen beide ihren Ort (sonst weiss niemand, fuer wen die
    # erste Haelfte gilt); ab drei Gruppen nur noch der frueheste Einsatz —
    # die Vereinigung ("ganztags") waere dort schlicht falsch.
    grouped = {}
    for z, sh in per_zone.items():
        grouped.setdefault((sh["shape"], sh["from"], sh["to"]), []).append(z)

    def where(zs):
        return _join_days([_zone_in(z) for z in zs])

    if len(grouped) <= 1:
        spans = _shape_phrase(shape)
    elif len(grouped) == 2:
        main_key, exc_key = sorted(grouped, key=lambda k: -len(grouped[k]))
        spans = _lbl("hz_windows_but").format(
            main=f"{_shape_phrase(per_zone[grouped[main_key][0]])} {where(grouped[main_key])}",
            exception=f"{_shape_phrase(per_zone[grouped[exc_key][0]])} {where(grouped[exc_key])}")
    else:
        order = [w[0] for w in config.SYNOPTIC_DAY_WINDOWS]
        first = min(order.index(k[1]) for k in grouped)
        early = [z for k, zs in grouped.items() if order.index(k[1]) == first for z in zs]
        return _lbl("hz_windows_staggered").format(a=_lbl("win_" + order[first]),
                                                   zones=where(early))
    return _capitalize(_lbl("hz_windows").format(spans=spans))


def _hazard_tomorrow_text(check: dict) -> str:
    """Folgetag-Trend als Text — NICHT fuer die Tages-Warnbox.

    Die Warnungen stehen in Sektion 2 ("Heute im Detail") und sind
    tagesrein; diese Zeile gehoert in eine Sektion, die das ganze
    3-Tage-Fenster zeigt (Sektion 1).
    """
    tm = (check.get("facts") or {}).get("tomorrow")
    if not tm or not tm.get("trend"):
        return ""
    return _lbl("hz_tm_" + tm["trend"])


def _hazard_cause(topic: str, check: dict, wetterlage: dict, date: str) -> str:
    """Die synoptische Ursache der Warnung als Halbsatz — dasselbe Prinzip wie
    in der Kette: die Warnung kommt aus den Daten, die Ursache aus der Lage."""
    wl = wetterlage or {}
    flow = _per_day_index(wl.get("flow_overhead"), [date]).get(date) or {}
    abbr = _SECTOR_ABBR.get(flow.get("sector", ""), "")
    sector = _lbl("lg_sector_" + abbr) if abbr else ""
    if topic == "RAIN":
        sig, _ = _front_signature(wl, date)
        if sig:
            return _lbl("hz_cause_rain_front")
        zones = set(check.get("zones") or [])
        if abbr in ("S", "SW", "SE") and "alpennordhang" not in zones:
            return _lbl("hz_cause_rain_south").format(sector=sector)
        if abbr in ("N", "NW", "W") and "alpennordhang" in zones:
            return _lbl("hz_cause_rain_north").format(sector=sector)
        return _lbl("hz_cause_rain_flow").format(sector=sector) if sector else ""
    if topic == "WIND":
        wp = _per_day_index(wl.get("wind_pattern"), [date]).get(date) or {}
        drivers = {(wp.get(side) or {}).get("wind_driver") for side in ("alpennord", "alpensued")}
        if "hoehenwind" in drivers and sector:
            return _lbl("hz_cause_wind_aloft").format(sector=sector)
        return _lbl("hz_cause_wind_gusts")
    if topic == "FOEHN":
        fo = _per_day_index(wl.get("foehn"), [date]).get(date) or {}
        side = "sued" if fo.get("sued_active") else "nord"
        dp = (fo.get("claim") or {}).get(f"delta_p_{side}_max_hpa")
        return _lbl("hz_cause_foehn").format(dp=f"{dp:.0f}") if isinstance(dp, (int, float)) else ""
    if topic == "THUNDER":
        regime, tkey = _lage_regime(wl, date)
        zones = set(check.get("zones") or [])
        cap = _lbl("hz_cause_thunder_cap") if (regime == "hoch" or tkey == "up") and "alpennordhang" not in zones else ""
        return _lbl("hz_cause_thunder").format(cap=cap)
    if topic == "BISE":
        bi = _per_day_index(wl.get("bise"), [date]).get(date) or {}
        dp = bi.get("delta_p_hpa")
        return _lbl("hz_cause_bise").format(dp=f"{dp:+.0f}") if isinstance(dp, (int, float)) else ""
    return ""


def _hazard_code_text(topic: str, check: dict, timing: bool = True, cause: str = "") -> str:
    """Der Code-Satz mit Zahl je Gefahr — steht immer, auch ohne KI-Satz.
    Reihenfolge: Ausmass/Zahl, Tagesverlauf, Boeen. NUR dieser Tag.

    timing=False: Zeitfenster und Verlauf weglassen — dann nennt sie der
    KI-Satz direkt darueber schon (geprueft auf zu spaeten Beginn), und die
    Zeile wiederholte sie nur (User 16.09.2026: zu viel Text)."""
    base = _hazard_base_text(topic, check)
    if cause:
        base = base.rstrip(".") + " " + cause
    parts = [base]
    if timing:
        parts += [_hazard_windows_text(check), _hazard_course_text(check)]
    parts.append(_hazard_gust_text(check))
    return " ".join(p for p in parts if p)


def _hazard_course_text(check: dict) -> str:
    """Verlauf innerhalb des Tages (bisher nur Foehn)."""
    course = (check.get("facts") or {}).get("course")
    return _lbl("hz_course_" + course) if course else ""


def _hazard_gust_text(check: dict) -> str:
    """Boeen-Beleg im Lee (bisher nur Foehn)."""
    kmh = (check.get("facts") or {}).get("lee_gust_kmh")
    return _lbl("hz_foehn_gust").format(kmh=kmh) if kmh else ""


def _hazard_base_text(topic: str, check: dict) -> str:
    f = check.get("facts") or {}
    zones = _zones_text(check.get("zones") or [], where=True)
    # Foehn nennt die Lee-Seite als Gebiet, nicht als Ortsangabe —
    # "im Lee im Tessin" waere doppelt gemoppelt.
    zones_plain = _zones_text(check.get("zones") or [])
    if topic == "RAIN":
        return _lbl("hz_code_rain").format(zones=zones,
                                           extent=_extent_word(f.get("wet_share")),
                                           intensity=_rain_word(f.get("p90_mm")))
    if topic == "THUNDER":
        return _lbl("hz_code_thunder").format(zones=zones) + " " + _lbl("thunder_caveat")
    if topic == "FOEHN":
        side = "north" if f.get("side") == "nord" else "south"
        level = _lbl("level_danger" if f.get("peak") == "danger" else "level_caution")
        return _lbl("hz_code_foehn").format(side=_lbl(side), level=level,
                                            h=f.get("hours", 0), zones=zones_plain)
    if topic == "BISE":
        return _lbl("bise_line").format(strength=f.get("strength") or "",
                                        dp=f"{float(f.get('delta_p_hpa') or 0):+.1f}")
    if topic == "WIND":
        # Gleiche Klasse buendeln: "verblasen am Alpennordhang und im Wallis"
        by_class = {}
        for z, c in (f.get("classes") or {}).items():
            by_class.setdefault(c, []).append(z)
        classes = ", ".join(
            f"{_lbl('hz_class_' + c)} {_join_days([_zone_in(z) for z in zs])}"
            for c, zs in by_class.items())
        # keine eigene km/h-Zahl: die Spitze steht im Hoehenwind-Abschnitt
        return _capitalize(_lbl("hz_code_wind").format(classes=classes))
    return ""


def _ch_warnings(wetterlage: dict, date: str) -> dict:
    """Warnungen als Gesamtlage Schweiz: zuerst die Schalter (Regen? Foehn? …,
    vom Code), dann je aktiver Gefahr der KI-Satz (wo in der Schweiz, woher,
    wohin) plus der Code-Satz mit Zahl. Die Regionen folgen erst danach —
    ihre Warn-Chips stehen in den Regionszeilen."""
    from engine.synoptic_llm import HAZARD_TOPICS
    day = _hazard_day(wetterlage, date) if wetterlage else None
    if not day:
        return {"checks": [], "entries": [], "any": False, "has_ki": False}
    ki = {i.get("topic"): i.get("text", "") for i in day.get("items") or []}
    checks, items = [], []
    for topic in HAZARD_TOPICS:
        c = day["checks"].get(topic) or {}
        label = _lbl("hz_" + topic)
        checks.append({"topic": topic, "label": label, "active": bool(c.get("active")),
                       "level": c.get("level", "warn")})
        if not c.get("active"):
            continue
        items.append({"topic": topic, "label": label, "severity": c.get("level", "warn"),
                      "sev_label": _lbl("sev_" + c.get("level", "warn")),
                      "ki_text": ki.get(topic, ""),
                      "code_text": _hazard_code_text(topic, c, timing=not ki.get(topic),
                                                     cause=_hazard_cause(topic, c, wetterlage, date))})
    items.sort(key=lambda e: e["severity"] != "stop")
    # "entries", nicht "items": Jinja loest w.items auf die dict-Methode auf
    return {"checks": checks, "entries": items, "any": bool(items),
            "has_ki": any(e["ki_text"] for e in items)}


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
                   "warnings_ch", "hz_none")


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

    # Betreff: Abo-Regionen, Aufzaehlung, nie ein Superlativ (wie v2)
    # dieselbe Tages-Einstufung wie die Kacheln, sonst widerspricht der Betreff
    good = [d for d in days if (verdicts.get(d.get("date")) or {}).get("tier") == "green"]
    cond = [d for d in days if (verdicts.get(d.get("date")) or {}).get("tier") == "conditional"]
    # Worte der Kacheln (Safe / Caution / Not safe), nicht "fliegbar": ob
    # geflogen wird, entscheidet der Pilot (Entscheid 16.09.2026)
    if good:
        subject = _capitalize(_lbl("subj_safe").format(days=_join_days([_day_name(d) for d in good])))
    elif cond:
        subject = _capitalize(_lbl("subj_caution").format(days=_join_days([_day_name(d) for d in cond])))
    else:
        subject = _lbl("subj_not_safe")

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
