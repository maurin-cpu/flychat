"""Gefahren-Schalter und Strukturfeld-Refresh fuer den Wetterlage-Block.

Bis 25.10.2026 liess dieses Modul einen LLM die Briefing-Texte schreiben
(Lead, Gefahren-Saetze, Tagessaetze; Skill synoptic_overview.md, Validator
mit bis zu 4 Korrekturrunden). Abgeschaltet und entfernt: das Briefing zeigt
die Warnungen nur noch als Labels und erklaert sie in den Bloecken der Kette
(docs/BRIEFING.md §5). Der Modulname bleibt fuer die Aufrufer.

Uebrig:
  - refresh_synoptic_overview(_lang): Strukturfeld bauen und cachen,
    llm_overview bleibt null
  - hazard_checks(): welche Gefahren (Regen, Gewitter, Foehn, Wind) die Daten
    je Tag schalten — Quelle der Warnungs-Labels im Briefing
"""

import logging
import re
from typing import Optional

import config

logger = logging.getLogger(__name__)


def refresh_synoptic_overview(weather_cache: dict, analysis_client,
                              analysis_model: str) -> Optional[dict]:
    """Deterministisches Strukturfeld bauen und nach data/synoptic_context.json
    schreiben. Wird vom Scheduler (oder bei manuellem Refresh) 1x/Tag aufgerufen.

    Der KI-Text (llm_overview) ist seit 25.10.2026 abgeschaltet: Das Briefing
    zeigt die Warnungen nur noch als Labels, erklaert werden sie in den
    Bloecken der Kette — Lead und Tagessatz hatten schon vorher keinen Abnehmer
    mehr. llm_overview bleibt explizit null; das Briefing rechnet die
    Gefahren-Schalter dann selbst (hazard_checks). analysis_client/-model
    bleiben in der Signatur fuer die Aufrufer.

    Returns:
        Das Strukturfeld, oder None wenn die Basis-Detektion fehlschlaegt.
    """
    from engine import synoptic_context as sc

    sctx = sc.build_synoptic_context(weather_cache, write_audit=True)
    if sctx is None:
        return None
    sctx["llm_overview"] = None
    return sctx


def refresh_synoptic_overview_lang(sctx: dict, analysis_client,
                                   analysis_model: str, lang: str) -> Optional[dict]:
    """Zweite Sprachfassung des Wetterlage-Blocks fuer das oeffentliche Briefing.

    Das Strukturfeld ist sprachneutral; die Texte baut das Briefing selbst in
    `lang`. Seit dem Abschalten des KI-Texts (25.10.2026) ist das nur noch
    eine Kopie mit Sprachvermerk in synoptic_context.<lang>.json.
    Fuer die Server-Sprache gibt es nichts zu tun, dann kommt sctx zurueck.
    """
    import copy
    import i18n
    from engine import synoptic_context as sc

    if lang == i18n.get_server_lang():
        return sctx
    out = copy.deepcopy(sctx)
    out["llm_overview"] = None
    out["lang"] = lang
    try:
        sc._write_synoptic_cache(out, lang=lang)
    except Exception as e:
        logger.warning("synoptic cache (%s) schreiben fehlgeschlagen: %s", lang, e)
    return out


_WINDY_CLASSES = {"verblasen", "stark_eingeschraenkt"}


def _zone_konvektion(ctx: dict, zone: str, i: int, key: str) -> list:
    """Weiche Konvektions-Signale (Ensemble/Wolkentop) einer Zone am Tag i.

    key: "gewitter" oder "ueberentwicklung". Leere Liste, wenn nichts da —
    aeltere Caches haben das Feld nicht.
    """
    per_day = (ctx.get("konvektion") or {}).get("per_day") or []
    if i >= len(per_day):
        return []
    return (((per_day[i].get("zones") or {}).get(zone) or {}).get(key)) or []


# Zone(n), die bei aktivem Foehn die boeige LEE-Seite sind (Gefahren-Schalter
# FOEHN: betroffene Zonen).
_FOEHN_LEE_ZONES = {
    "nord": ("tessin",),                      # Nordfoehn -> Tessin ist Lee
    "sued": ("alpennordhang", "wallis"),      # Suedfoehn -> Nordseite/Foehntaeler
}


def _foehn_active_side(foehn_struct: dict, forecast_dates: list,
                       i: int) -> Optional[str]:
    """Liefert die aktive Foehn-Seite ("nord"/"sued") am Forecast-Tag i,
    oder None wenn an dem Tag kein Foehn aktiv ist.

    Matcht forecast_dates[i] gegen foehn.per_day per date — robust auch
    wenn per_day separat sortiert ist.
    """
    if not foehn_struct or i >= len(forecast_dates):
        return None
    per_day = foehn_struct.get("per_day") or []
    per_day_by_date = {d.get("date"): d for d in per_day if isinstance(d, dict)}
    day_foehn = per_day_by_date.get(forecast_dates[i])
    if not day_foehn:
        return None
    if day_foehn.get("nord_active"):
        return "nord"
    if day_foehn.get("sued_active"):
        return "sued"
    return None


# Ohne Bise (User 12.10.2026: "Bise ist egal, wichtig ist nur Nord-/Suedfoehn").
HAZARD_TOPICS = ("RAIN", "THUNDER", "FOEHN", "WIND")


def _num(v) -> float:
    return float(v) if isinstance(v, (int, float)) else 0.0


def _zone_entry(ctx: dict, key: str, i: int, zone: str) -> dict:
    """Zonen-Eintrag aus precip_zones/wind_zones am Forecast-Tag i."""
    per_day = (ctx.get(key) or {}).get("per_day") or []
    if i >= len(per_day):
        return {}
    return ((per_day[i].get("zones") or {}).get(zone)) or {}


_WINDOW_KEYS = tuple(w[0] for w in config.SYNOPTIC_DAY_WINDOWS)


def _zone_windows(ctx: dict, key: str, i: int, zone: str) -> dict:
    """Tagesfenster-Aggregate einer Zone am Tag i ({} bei aelteren Caches)."""
    return _zone_entry(ctx, key, i, zone).get("windows") or {}


def _hit_windows(windows: dict, field: str, threshold: float,
                 strict: bool = False) -> list:
    """Fenster-Keys (in Tagesreihenfolge), in denen `field` die Schwelle reisst."""
    out = []
    for w in _WINDOW_KEYS:
        v = (windows.get(w) or {}).get(field)
        if v is None:
            continue
        v = _num(v)
        if v > threshold if strict else v >= threshold:
            out.append(w)
    return out


_KONV_SPAN_RE = re.compile(r"(\d{1,2}):\d{2}\s*[-–]\s*(\d{1,2}):\d{2}")


def _konvektion_windows(entries: list) -> list:
    """Fenster-Keys aus den Konvektions-Zeitspannen ("14:00-16:00").

    Fallback, wenn der Modell-Niederschlag kein Gewitter-Fenster zeigt, das
    Ensemble/Wolkentop-Signal aber eine Zeitspanne nennt.
    """
    hours = set()
    for e in entries or []:
        for part in (e if isinstance(e, (list, tuple)) else [e]):
            m = _KONV_SPAN_RE.search(str(part))
            if m:
                lo, hi = int(m.group(1)), int(m.group(2))
                hours.update(range(lo, max(hi, lo + 1)))
    if not hours:
        return []
    return [w for w, h_lo, h_hi in config.SYNOPTIC_DAY_WINDOWS
            if any(h_lo <= h < h_hi for h in hours)]


def _day_shape(windows_by_zone: dict) -> Optional[dict]:
    """Tagesverlauf der Gefahr ueber alle betroffenen Zonen zusammengefasst.

    Returns: {"shape", "from", "to", "hit"} oder None, wenn keine
      Fensterdaten vorliegen (aeltere Caches, Foehn/Bise: nur Tageswerte).
      shape — "ganztags" | "ab" | "bis" | "nur" | "spanne" | "wechselnd"
              | "gemischt" (die Zonen verlaufen unterschiedlich)

    Verlaufen die Zonen unterschiedlich, ist die Vereinigung ihrer Fenster
    KEINE Aussage: eine ganztags nasse Zone machte sonst den ganzen Tag zu
    "ganztags", auch wo es erst am Nachmittag einsetzt (Vorfall 16.09.2026).
    """
    hit = [w for w in _WINDOW_KEYS
           if any(w in wins for wins in windows_by_zone.values())]
    if not hit:
        return None
    per_zone = {tuple(_shape_of(wins)[k] for k in ("shape", "from", "to"))
                for wins in windows_by_zone.values() if wins}
    if len(per_zone) > 1:
        return {"shape": "gemischt", "from": hit[0], "to": hit[-1], "hit": hit}
    return {**_shape_of(hit), "hit": hit}


def _shape_of(hit: list) -> dict:
    """Form EINER Fensterliste: {"shape", "from", "to"}."""
    hit = [w for w in _WINDOW_KEYS if w in hit]
    idx = [_WINDOW_KEYS.index(w) for w in hit]
    if len(hit) == len(_WINDOW_KEYS):
        shape = "ganztags"
    elif idx != list(range(idx[0], idx[-1] + 1)):
        shape = "wechselnd"          # Luecke drin: Vormittag und Abend, Mittag frei
    elif len(hit) == 1:
        shape = "nur"
    elif idx[-1] == len(_WINDOW_KEYS) - 1:
        shape = "ab"                 # setzt ein und bleibt bis Tagesende
    elif idx[0] == 0:
        shape = "bis"                # von Tagesbeginn an, klingt dann ab
    else:
        shape = "spanne"
    return {"shape": shape, "from": hit[0], "to": hit[-1]}


_LEVEL_RANK = {"none": 0, "caution": 1, "danger": 2}


def _foehn_course(windows: dict) -> Optional[str]:
    """Verlauf des Foehns INNERHALB des Tages: "zunehmend" | "abflauend" |
    "gleich" (None ohne Fensterdaten).

    Der Pilot fragt nicht "wie viele Stunden", sondern "greift er durch,
    solange ich in der Luft bin?". Gewichtet wird die Spitze je Fenster
    (caution/danger), die Stundenzahl entscheidet nur bei Gleichstand.
    """
    if not windows:
        return None
    score = {}
    for w in _WINDOW_KEYS:
        v = windows.get(w) or {}
        score[w] = _LEVEL_RANK.get(v.get("peak", "none"), 0) * 10 + _num(v.get("hours"))
    early = max(score.get("morning", 0), score.get("midday", 0))
    late = max(score.get("afternoon", 0), score.get("evening", 0))
    if not early and not late:
        return None
    if late > early:
        return "zunehmend"
    if early > late:
        return "abflauend"
    return "gleich"


def _lee_gust_kmh(ctx: dict, i: int, lee_zones) -> Optional[int]:
    """Staerkste Boeen-Spitze (P90) im Lee — die Spur des Foehns in den
    Winddaten. Ohne Fensterdaten None."""
    gusts = []
    for z in lee_zones:
        for w in (_zone_entry(ctx, "wind_zones", i, z).get("windows") or {}).values():
            g = (w or {}).get("p90_gust_kmh")
            if g:
                gusts.append(_num(g))
    return round(max(gusts)) if gusts else None


def _hazard_strength(topic: str, check: dict) -> float:
    """Vergleichsmass einer Gefahr fuer den Folgetag-Trend — je Thema die
    Groesse, die der Pilot als 'mehr' empfindet."""
    f = check.get("facts") or {}
    if topic == "RAIN":
        return _num(f.get("wet_share"))
    if topic == "FOEHN":
        return _num(f.get("hours"))
    return float(len(check.get("zones") or []))   # THUNDER/WIND: Flaeche


def _attach_outlook(days: list) -> None:
    """Setzt facts["tomorrow"] je aktiver Gefahr — in-place.

    Nur fuer Auswertungen ueber das ganze Prognosefenster (3-Tage-Sektion);
    der tagesreine Gefahren-Satz und die Tages-Warnbox nutzen es NICHT.

    {"active": bool, "trend": "vorbei"|"zunehmend"|"abklingend"|"gleich"};
    None am letzten Tag des Prognosefensters (kein Folgetag bekannt).
    """
    ratio = getattr(config, "SYNOPTIC_HAZARD_TREND_RATIO", 1.25)
    for i, c in enumerate(days):
        nxt = days[i + 1] if i + 1 < len(days) else None
        for topic in HAZARD_TOPICS:
            cur = c["checks"][topic]
            if not cur["active"]:
                continue
            if nxt is None:
                cur["facts"]["tomorrow"] = None
                continue
            n = nxt["checks"][topic]
            if not n["active"]:
                cur["facts"]["tomorrow"] = {"active": False, "trend": "vorbei"}
                continue
            a = _hazard_strength(topic, cur)
            b = _hazard_strength(topic, n)
            trend = ("zunehmend" if b >= a * ratio
                     else "abklingend" if a >= b * ratio else "gleich")
            cur["facts"]["tomorrow"] = {"active": True, "trend": trend}


def hazard_checks(ctx: dict) -> list:
    """Deterministische Gefahren-Schalter je forecast_dates-Tag.

    Returns: [{"date", "checks": {TOPIC: {"active", "level", "zones", "facts"}}}]
      level  — "stop" | "warn" (Stufe fuer die Anzeige)
      zones  — betroffene Zonen-IDs (bei FOEHN die Lee-Zonen)
      facts  — Kennzahlen fuer den Code-Satz der Anzeige, nicht fuer den LLM
    Fehlende Felder (aeltere Caches) schalten das Thema einfach nicht.
    """
    fc_dates = ctx.get("forecast_dates") or []
    foehn = ctx.get("foehn") or {}
    foehn_by_date = {d.get("date"): d for d in foehn.get("per_day") or []
                     if isinstance(d, dict)}
    foehn_thr = foehn.get("thresholds") or {}
    rain_thr = getattr(config, "SYNOPTIC_HAZARD_RAIN_WET_SHARE", 0.2)

    win_rain = getattr(config, "SYNOPTIC_HAZARD_WINDOW_WET_SHARE", 0.2)
    win_gew = getattr(config, "SYNOPTIC_HAZARD_WINDOW_GEWITTER_SHARE", 0.0)
    win_wind = getattr(config, "SYNOPTIC_HAZARD_WINDOW_WIND_SHARE", 0.3)

    out = []
    for i, date in enumerate(fc_dates):
        rain_z, thunder_z, wind_z = [], [], []
        rain_share = rain_mm = thunder_share = aloft = 0.0
        wind_classes = {}
        # {zone: [fenster]} — nur fuer betroffene Zonen, leer bei alten Caches
        rain_wins, thunder_wins, wind_wins = {}, {}, {}
        for z in config.SYNOPTIC_ZONES:
            day = _zone_entry(ctx, "precip_zones", i, z).get("day") or {}
            pw = _zone_windows(ctx, "precip_zones", i, z)
            share = _num(day.get("wet_share"))
            if share >= rain_thr:
                rain_z.append(z)
                rain_share = max(rain_share, share)
                rain_mm = max(rain_mm, _num(day.get("p90_mm")))
                hit = _hit_windows(pw, "wet_share", win_rain)
                if hit:
                    rain_wins[z] = hit
            g = _num(day.get("gewitter_share"))
            konv = _zone_konvektion(ctx, z, i, "gewitter")
            if g > 0 or konv:
                thunder_z.append(z)
                thunder_share = max(thunder_share, g)
                # Fenster aus dem Modell-Anteil, sonst aus den Konvektions-
                # Zeitspannen ("Sopraceneri", "14:00-16:00")
                hit = (_hit_windows(pw, "gewitter_share", win_gew, strict=True)
                       or _konvektion_windows(konv))
                if hit:
                    thunder_wins[z] = hit
            w = _zone_entry(ctx, "wind_zones", i, z)
            if w.get("wind_class") in _WINDY_CLASSES:
                wind_z.append(z)
                wind_classes[z] = w["wind_class"]
                aloft = max(aloft, _num(w.get("median_aloft_kmh")))
                hit = _hit_windows(w.get("windows") or {},
                                   "share_wind_crit", win_wind)
                if hit:
                    wind_wins[z] = hit

        side = _foehn_active_side(foehn, fc_dates, i)
        fo = foehn_by_date.get(date) or {}
        peak = fo.get(f"peak_{side}") if side else None
        # Foehn auch ohne Druckschwelle, wenn Taeler trockenen Wind aus Foehnrichtung
        # zeigen (User 14.10.2026; Blog wetterkunde/foehn: Andeer/Davos/Visp ein
        # Drittel der Foehnstunden unter 4 hPa). Dann: Talbezug statt Druckstufe.
        valley_signs = None
        if not side:
            cand = [(s_, t_) for s_, t_ in ((fo.get("taeler") or {}).items()) if t_ and t_.get("n_dir_dry")]
            if cand:
                side, tv = max(cand, key=lambda st: st[1]["n_dir_dry"])
                valley_signs = {"n": tv["n_dir_dry"], "n_total": tv.get("n_total", 0),
                                "taeler": [e.get("tal", "") for e in tv.get("taeler") or [] if e.get("dir_dry")],
                                "gust_max_kmh": max((e.get("all_gust_max_kmh") or 0)
                                                    for e in tv.get("taeler") or [] if e.get("dir_dry"))}

        lee_zones = list(_FOEHN_LEE_ZONES.get(side, ())) if side else []
        foehn_wins_raw = (fo.get(f"{side}_windows") or {}) if side else {}
        foehn_hit = [w for w in _WINDOW_KEYS
                     if (foehn_wins_raw.get(w) or {}).get("hours")]
        foehn_wins = {z: foehn_hit for z in lee_zones} if foehn_hit else {}

        out.append({"date": date, "checks": {
            "RAIN": {"active": bool(rain_z), "level": "warn", "zones": rain_z,
                     "facts": {"wet_share": round(rain_share, 2),
                               "p90_mm": round(rain_mm, 1),
                               "windows": rain_wins,
                               "day_shape": _day_shape(rain_wins)}},
            "THUNDER": {"active": bool(thunder_z), "level": "stop", "zones": thunder_z,
                        "facts": {"gewitter_share": round(thunder_share, 2),
                                  "windows": thunder_wins,
                                  "day_shape": _day_shape(thunder_wins)}},
            "FOEHN": {"active": bool(side),
                      "level": "stop" if peak == "danger" else "warn",
                      "zones": lee_zones,
                      "facts": {"side": side, "peak": peak,
                                "hours": fo.get(f"{side}_hours", 0) if side else 0,
                                "windows": foehn_wins,
                                "day_shape": _day_shape(foehn_wins),
                                "course": _foehn_course(foehn_wins_raw),
                                "lee_gust_kmh": _lee_gust_kmh(ctx, i, lee_zones),
                                # Foehn am Talboden (foehn_tal_for_day) — None ohne Talreihe
                                # oder wenn nur die Talmerkmale ausloesen (eigene Fakten)
                                "tal": fo.get("tal") if side and not valley_signs else None,
                                "valley_signs": valley_signs,
                                "delta_p_min_hpa": (foehn_thr.get("delta_p_danger_hpa", 8)
                                                    if peak == "danger"
                                                    else foehn_thr.get("delta_p_caution_hpa", 4))}},
            "WIND": {"active": bool(wind_z),
                     "level": "stop" if "verblasen" in wind_classes.values() else "warn",
                     "zones": wind_z,
                     "facts": {"classes": wind_classes,
                               "median_aloft_kmh": round(aloft),
                               "windows": wind_wins,
                               "day_shape": _day_shape(wind_wins)}},
        }})
    _attach_outlook(out)
    return out
