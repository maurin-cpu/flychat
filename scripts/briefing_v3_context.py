"""
Kontext fuer die Briefing-Vorschau v3 — PREVIEW-ONLY.

Konzept: docs/pläne/PLAN_briefing_mail_v3.md. Kurz: die Mail folgt der
Analyse-Kette des Piloten (Lage -> Fronten -> Foehn/Bise -> Hoehenwind ->
Labilitaet -> Regionen), sie zaehlt Spots je Region statt einzelne Spots zu
kueren (Validierung: Spot-Rangfolge ist Rauschen), und jede Zahl bekommt einen
Satz. Woche ohne Fliesstext, Tag im Briefing-Stil.

Nimmt den Kontext aus `email_service.build_briefing_context()` und ergaenzt
alle `v3_`-Felder. Kein App-Code: email_service.py und
templates/email/ bleiben unberuehrt. Beim Uebernehmen wandert das hierher
nach email_service.py, die Labels nach i18n.py.
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
import statistics
from datetime import datetime, timezone
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
        regime = _REGIME[lang].get(p.get("regime", ""), (p.get("regime") or "").title())
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
        "ground_est":   "am Boden zu erwarten",
        "rule_23":      "⅔-Regel",
        "front_none":   "Keine Front im Vorhersagefenster (DWD).",
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
        "w_generic":    "{label} an {days}.",
        "sev_stop":     "Stopp",
        "sev_warn":     "Warnung",
        "alps_north":   "Alpennordseite",
        "alps_south":   "Alpensüdseite",
        "warnings_ch":  "Warnungen · Gesamtlage Schweiz",
        "hz_RAIN": "Regen", "hz_THUNDER": "Gewitter", "hz_FOEHN": "Föhn", "hz_BISE": "Bise",
        "hz_WIND": "Starker Wind",
        "hz_none":      "Keine Gefahr schweizweit.",
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
        "ground_est":   "expected at ground level",
        "rule_23":      "⅔ rule",
        "front_none":   "No front within the forecast window (DWD).",
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
        "w_generic":    "{label} on {days}.",
        "sev_stop":     "stop",
        "sev_warn":     "warning",
        "alps_north":   "northern Alps",
        "alps_south":   "southern Alps",
        "warnings_ch":  "Warnings · Switzerland overall",
        "hz_RAIN": "Rain", "hz_THUNDER": "Thunderstorms", "hz_FOEHN": "Foehn", "hz_BISE": "Bise",
        "hz_WIND": "Strong wind",
        "hz_none":      "No hazard across Switzerland.",
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
    # 2) Naechste Front auf der Karte — Distanz zur Schweiz (Faktum, keine Prognose)
    nearest = []
    for f in (fronts or {}).get("features") or []:
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if not coords:
            continue
        best = min(coords, key=lambda c: _haversine_km(46.8, 8.2, c[1], c[0]))
        d = _haversine_km(46.8, 8.2, best[1], best[0])
        nearest.append((d, f.get("properties", {}).get("typ", ""), best))
    nearest.sort(key=lambda x: x[0])
    for d, typ, pt in nearest[:2]:
        if d > 1200:
            continue
        key = "front_near" if d <= 400 else "front_far"
        lines.append(_lbl(key).format(typ=_front_type(typ), dist=int(round(d / 10) * 10),
                                      dir=_bearing_word(pt[1], pt[0])))
    if not lines:
        lines.append(_lbl("front_none"))
    return lines


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
    syn = _synoptik_today(wetterlage, dates, date) or {}
    strip = _strip_synoptik(wetterlage, dates).get(date, {})
    note = syn.get("pressure_note", "")
    for de in ("aufbauend", "fallend", "stabil"):
        note = note.replace(de, _lbl(f"trend_{de}"))
    return {
        "lage": {
            "label": syn.get("lage", ""),
            "centers": syn.get("centers", []),
            "pressure": syn.get("pressure_msl", ""),
            "pressure_note": note,
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
        "fronts": {"lines": _front_lines(fronts, passagen, date),
                   "zugbahn": _zugbahn_text(wetterlage, date)},
        "foehn": {"foehn": _foehn_text(wetterlage, date), "bise": _bise_text(wetterlage, date),
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
        },
        "stability": {
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


def _hazard_code_text(topic: str, check: dict, timing: bool = True) -> str:
    """Der Code-Satz mit Zahl je Gefahr — steht immer, auch ohne KI-Satz.
    Reihenfolge: Ausmass/Zahl, Tagesverlauf, Boeen. NUR dieser Tag.

    timing=False: Zeitfenster und Verlauf weglassen — dann nennt sie der
    KI-Satz direkt darueber schon (geprueft auf zu spaeten Beginn), und die
    Zeile wiederholte sie nur (User 16.09.2026: zu viel Text)."""
    parts = [_hazard_base_text(topic, check)]
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
                      "code_text": _hazard_code_text(topic, c, timing=not ki.get(topic))})
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
    cands = sorted(glob.glob(str(ROOT / "validation" / "fronten" / "aussagen" / "passagen_*.json")))
    return _load_json(Path(cands[-1])) if cands else None


# ----------------------------------------------------------------------
# Einstieg
# ----------------------------------------------------------------------

def build_v3_context(ctx: dict, briefing_data: dict, subscriber: dict,
                     focus_date: str = "") -> dict:
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
