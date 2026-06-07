"""LLM-Caller + Post-Filter fuer den Wetterlage-Block.

Nimmt das deterministisch erzeugte Strukturfeld aus synoptic_context.build_*
und laesst den LLM daraus eine Prosa-Version generieren (short + long).

Halluzinations-Schutz-Pipeline:
  1. LLM bekommt nur das fertige Strukturfeld, keine Rohzahlen.
  2. Skill-Prompt enthaelt Whitelist + Verbotsliste (siehe synoptic_overview.md).
  3. Post-Filter prueft pro Satz:
     a) Verbotsbegriffe (Kaltfront, Trog, hPa-Werte, ...) → Satz wird verworfen
     b) Source-Tags valide? → ungueltige Sources → Satz wird verworfen
     c) Erwaehnte Druckzentren-Region-Labels muessen im Strukturfeld stehen
  4. Bei API-Fehler oder leerem Output → return None, Block wird ausgelassen.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import config
import prompts
from engine._common import _weekday_de, _WOCHENTAGE

logger = logging.getLogger(__name__)


# ============================================================================
# VERBOTENE BEGRIFFE — synoptische Etiketten ohne Daten-Backing
# ============================================================================

_FORBIDDEN_PATTERNS = [
    re.compile(r"\bkaltfront\b", re.IGNORECASE),
    re.compile(r"\bwarmfront\b", re.IGNORECASE),
    re.compile(r"\bokklusion\b", re.IGNORECASE),
    re.compile(r"\bfrontdurchgang\b", re.IGNORECASE),
    re.compile(r"\bpraefrontal\b", re.IGNORECASE),
    re.compile(r"\bpostfrontal\b", re.IGNORECASE),
    re.compile(r"\btrogachse\b", re.IGNORECASE),
    re.compile(r"\bvorticity\b", re.IGNORECASE),
    re.compile(r"\bgeopotential\b", re.IGNORECASE),
    # Konkrete hPa-Werte ("1015 hPa", "998 hPa") — Pilot will Charakter, nicht Zahlen
    re.compile(r"\b\d{3,4}\s?hPa\b", re.IGNORECASE),
    # Konkrete Temperaturwerte mit Bezug zu Druckhoehe ("4 °C auf 850")
    re.compile(r"\b-?\d+\s?°C\s+auf\s+\d{3,4}", re.IGNORECASE),
    # "Trog" / "Ruecken" als synoptische Etiketten — auf wortgrenze isolieren
    re.compile(r"\btrog\b", re.IGNORECASE),
    re.compile(r"\bruecken\b", re.IGNORECASE),
]

_VALID_SOURCE_KEYS = {
    "lage_label",
    "pressure_influence",
    "pressure_centers_per_day",
    "flow_overhead",
    "t850_trend",
    "bise",
    "vb_lage",
    "foehn",
    "precip_pattern.alpennord",
    "precip_pattern.alpensued",
    "schneefallgrenze",
    "confidence_per_day",
}


# ============================================================================
# OEFFENTLICHE API
# ============================================================================

def refresh_synoptic_overview(weather_cache: dict, analysis_client,
                              analysis_model: str) -> Optional[dict]:
    """End-to-end: deterministisches Strukturfeld + LLM-Overview + Cache-Update.

    Wird vom Scheduler (oder bei manuellem Refresh) 1x/Tag aufgerufen.
    Schreibt das fertige Strukturfeld (inkl. llm_overview falls erfolgreich)
    nach data/synoptic_context.json. Bei Fehlern in einem Schritt wird der
    Block dennoch persistiert — fehlende Komponenten sind als null gekennzeichnet.

    Returns:
        Das vollstaendige Strukturfeld (mit oder ohne llm_overview), oder
        None wenn die Basis-Detektion komplett fehlschlaegt.
    """
    from engine import synoptic_context as sc

    sctx = sc.build_synoptic_context(weather_cache, write_audit=True)
    if sctx is None:
        return None

    overview = generate_synoptic_overview(sctx, analysis_client, analysis_model)
    if overview is not None:
        sctx["llm_overview"] = overview
        # Cache erneut schreiben — inkl. LLM-Text
        try:
            sc._write_synoptic_cache(sctx)
        except Exception as e:
            logger.warning("synoptic cache rewrite mit LLM-Output fehlgeschlagen: %s", e)
    else:
        sctx["llm_overview"] = None  # explizit null fuer Frontend-Logik

    return sctx


def generate_synoptic_overview(synoptic_context: dict, analysis_client,
                               analysis_model: str) -> Optional[dict]:
    """Ruft den LLM auf, generiert short + long Versionen.

    Args:
        synoptic_context: Output von synoptic_context.build_synoptic_context()
        analysis_client: LLM-Client (chat.completions.create-Interface)
        analysis_model: Model-Name, z.B. "gpt-4o-mini"

    Returns:
        {"short": str, "long": str, "short_with_sources": [...], "long_with_sources": [...]}
        oder None bei Fehler / leerem Output nach Post-Filter.
    """
    if not synoptic_context:
        return None
    if not analysis_client:
        logger.warning("generate_synoptic_overview: kein analysis_client")
        return None

    user_payload = _build_llm_payload(synoptic_context)
    system_prompt = _compose_system_prompt()

    try:
        response = analysis_client.chat.completions.create(
            model=analysis_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
            temperature=0.4,
            # v4-flash laeuft im Thinking-Mode — Reasoning-Tokens VOR der
            # Antwort. Plus 5-Tage-Output (short + long mit flight_hint +
            # sources) sprengt 4000. Bei Truncation kommt finish_reason=length
            # und das JSON ist mittendrin abgeschnitten → llm_overview=None.
            max_tokens=12000,
            response_format={"type": "json_object"},
        )
        finish = getattr(response.choices[0], "finish_reason", None)
        raw = response.choices[0].message.content
        if not raw:
            logger.warning("generate_synoptic_overview: leerer LLM-Output (finish_reason=%s)", finish)
            return None
        if finish == "length":
            logger.warning("generate_synoptic_overview: Output truncated bei max_tokens "
                           "— JSON ggf. unvollstaendig (finish_reason=length)")
    except Exception as e:
        logger.error("generate_synoptic_overview LLM-Call fehlgeschlagen: %s", e)
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("generate_synoptic_overview: JSON parse failed: %s — raw[:300]=%r",
                     e, raw[:300] if raw else None)
        return None

    short_with_src = parsed.get("short") or []
    long_with_src = parsed.get("long") or []

    if not isinstance(short_with_src, list) or not isinstance(long_with_src, list):
        logger.warning("generate_synoptic_overview: short/long keine Liste")
        return None

    # Post-Filter: Saetze verwerfen, die Verbotsbegriffe oder ungueltige Sources
    # enthalten ODER Druckzentren erwaehnen, die nicht im Strukturfeld stehen.
    valid_centers = _collect_valid_center_labels(synoptic_context)

    short_filtered = _filter_statements(short_with_src, valid_centers)
    long_filtered = _filter_statements(long_with_src, valid_centers)

    # Kalenderwochen-Begriffe ("Wochenmitte", "zum Wochenstart", ...) → zeitraum-
    # neutral. Sicherheitsnetz zum Skill-Verbot; der Cast ist ein rollierender
    # 5-Tage-Block ab heute, keine Kalenderwoche.
    short_filtered = _neutralize_calendar_week_terms(short_filtered)
    long_filtered = _neutralize_calendar_week_terms(long_filtered)

    # Wochentag-Normalisierung NUR fuer long (long_with_sources wird im
    # Frontend pro Tag gerendert; short ist Fliesstext und braucht das nicht).
    # Korrigiert "Heute:"/"Morgen:" sowie falsch verschobene Wochentag-Praefixe
    # auf den aus forecast_dates abgeleiteten korrekten Wochentag — sonst
    # rendert briefing.js die ersten Eintraege als unbeschriftete Lead-Absaetze.
    long_filtered = _normalize_weekday_prefixes(
        long_filtered, synoptic_context.get("forecast_dates") or []
    )

    # Foehn-Lee-Inversion: pro Tag pruefen, dass die Lee-Seite nicht als
    # "windgeschuetzt/ruhig" beschrieben wird, wenn der Foehn an dem Tag
    # aktiv ist (Nordfoehn → Suedseite Lee; Suedfoehn → Nordseite Lee).
    # Verstoss → text-Satz wird verworfen (analog zum Verbotsbegriff-Filter),
    # flight_hint mit gleicher Inversion ebenfalls.
    long_filtered = _filter_foehn_lee_inversion(
        long_filtered, synoptic_context.get("foehn") or {},
        synoptic_context.get("forecast_dates") or [],
    )

    # flight_hint pro long-Eintrag: optionales Pilotensicht-Satz-Feld.
    # Wird gegen Verbotsbegriffe gefiltert; bei Verstoss wird das Feld
    # einzeln verworfen, der ganze Eintrag bleibt aber stehen.
    long_filtered = _sanitize_flight_hints(long_filtered)

    # Vollstaendigkeits-Check: nur loggen, kein Fallback. LLM ist im Skill
    # auf Pflicht-Vollstaendigkeit verpflichtet — Lueckenwerden via
    # Skill-Compliance geloest, nicht durch Code-Synthese.
    fc_dates = synoptic_context.get("forecast_dates") or []
    if fc_dates and len(long_filtered) < len(fc_dates):
        logger.warning(
            "long_filtered hat nur %d Eintraege, erwartet %d (forecast_dates=%s). "
            "Skill-Compliance pruefen.",
            len(long_filtered), len(fc_dates), fc_dates,
        )

    if not short_filtered and not long_filtered:
        logger.warning(
            "generate_synoptic_overview: alle Saetze vom Post-Filter "
            "verworfen — Block wird ausgelassen (short_in=%d, long_in=%d)",
            len(short_with_src), len(long_with_src),
        )
        return None

    # Wenn ALLE short-Saetze verworfen wurden, aber long noch was hat → trotzdem
    # ausgeben, aber min. eine Variante muss Inhalt haben
    return {
        "short": " ".join(s["text"] for s in short_filtered),
        "long": " ".join(s["text"] for s in long_filtered),
        "short_with_sources": short_filtered,
        "long_with_sources": long_filtered,
        "rejected_count": (
            len(short_with_src) - len(short_filtered)
            + len(long_with_src) - len(long_filtered)
        ),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


# ============================================================================
# INTERNAL: System-Prompt + Knowledge-Base
# ============================================================================

def _compose_system_prompt() -> str:
    """Kombiniert den Synoptik-Skill mit der Wetterlagen-Wissensbasis.

    Architektur (Stage-Inversion-erhaltend):
      - Skill (synoptic_overview.md) definiert Regeln + Whitelist + Format
      - Wissensbasis (meteo_research/wetterlagen_pilotenwissen.md) liefert
        Hintergrundwissen ueber CH-Wetterlagen, damit der LLM die im
        Strukturfeld DETEKTIERTEN Lagen meteorologisch ehrlich
        interpretieren und in Pilotensprache formulieren kann.

    Wichtig: Die Wissensbasis ist ANHANG zum Skill, NICHT Ersatz. Sie darf
    NICHT verwendet werden, um Lagen zu erfinden — sie dient nur der
    Interpretation der bereits detektierten Strukturfelder.
    """
    skill = prompts.SYNOPTIC_OVERVIEW_PROMPT
    try:
        knowledge = prompts.WETTERLAGEN_PILOTENWISSEN
    except Exception as e:
        logger.warning("Wetterlagen-Pilotenwissen nicht ladbar: %s — "
                       "Synoptik-Block laeuft mit reduziertem Kontext", e)
        return skill

    return (
        skill
        + "\n\n"
        + "═══════════════════════════════════════════════\n"
        + "WISSENSBASIS — CH-WETTERLAGEN-HINTERGRUND\n"
        + "═══════════════════════════════════════════════\n\n"
        + "Im Folgenden findest du eine Wissensbasis ueber Schweizer\n"
        + "Wetterlagen — was Hoch, Tief, Foehn, Bise und der Alpenkamm\n"
        + "konkret bedeuten und welche regionalen Auswirkungen sie haben.\n\n"
        + "**Verwendung (STRIKT)**:\n"
        + "  - Nutze dieses Wissen NUR zur INTERPRETATION der im Strukturfeld\n"
        + "    DETEKTIERTEN Lagen — niemals zum Erfinden neuer Lagen.\n"
        + "  - Wenn z.B. `bise.active_any_day=true` ist, darfst du das Wissen\n"
        + "    nutzen, um zu formulieren wie Bise auf Mittelland und Wallis\n"
        + "    wirkt. Wenn `bise.active_any_day=false` ist, darfst du Bise\n"
        + "    nicht erwaehnen — auch wenn das Wissen Bise sehr ausfuehrlich\n"
        + "    beschreibt.\n"
        + "  - Die Strukturfeld-Daten sind die einzige autoritative Quelle\n"
        + "    fuer WAS gerade passiert. Die Wissensbasis sagt WAS DAS HEISST.\n"
        + "  - Verbote aus dem Skill (Kaltfront/Trog/hPa-Werte) gelten\n"
        + "    weiterhin — auch wenn die Wissensbasis diese Begriffe erklaert.\n\n"
        + knowledge
    )


# ============================================================================
# INTERNAL: Payload-Builder
# ============================================================================

def _build_llm_payload(ctx: dict) -> str:
    """Baut das User-Payload als kompaktes JSON-Strukturfeld.

    Wir geben dem LLM NUR die klassifizierten Felder, KEINE Rohzahlen
    (ch_snapshots/europe_grid bleiben aussen vor — sie sind im Audit-Log
    fuer Debug, aber nicht im LLM-Input).
    """
    # forecast_dates: pro Datum vorab den Wochentag berechnen, damit der LLM
    # nicht selbst Datums-Arithmetik machen muss. Frueher gab es nur die
    # nackten Date-Strings — LLM hat dann gelegentlich "Heute"/"Morgen" als
    # Praefix gesetzt oder den Wochentag um 1-2 Tage verschoben, weil er den
    # Wochentag falsch ableitete. Der briefing.js-Renderer fettstellt nur
    # Absaetze mit Wochentag-Praefix → fehlerhafte Labels fuehrten zu
    # luckenhaft wirkenden Wetterlage-Bloecken.
    raw_dates = ctx.get("forecast_dates") or []
    forecast_dates_labeled = []
    for d in raw_dates:
        try:
            forecast_dates_labeled.append({"date": d, "weekday": _weekday_de(d)})
        except Exception:
            forecast_dates_labeled.append({"date": d, "weekday": None})

    out = {
        "forecast_dates": forecast_dates_labeled,
        "lage_label": _strip_provenance(ctx.get("lage_label")),
        "pressure_influence": _strip_provenance(ctx.get("pressure_influence")),
        "flow_overhead": _flow_overhead_for_llm(ctx.get("flow_overhead")),
        "t850_trend": _strip_provenance(ctx.get("t850_trend")),
        "pressure_centers_per_day": [
            {"date": d["date"],
             "centers": [{"type": c["type"], "region_label": c["region_label"]}
                         for c in d.get("centers", [])]}
            for d in (ctx.get("pressure_centers_per_day") or [])
        ],
        "bise": _strip_provenance(ctx.get("bise")),
        "vb_lage": _strip_provenance(ctx.get("vb_lage")),
        "foehn": _strip_provenance(ctx.get("foehn")),
        "precip_pattern": {
            "per_day": [
                {"date": d["date"],
                 "alpennord": {
                     "peak_mm": d["alpennord"].get("peak_mm"),
                     "wet_share": d["alpennord"].get("wet_share"),
                     "max_cape": d["alpennord"].get("max_cape"),
                     "max_coverage": d["alpennord"].get("max_coverage"),
                     "n_spots": d["alpennord"].get("n_spots"),
                 },
                 "alpensued": {
                     "peak_mm": d["alpensued"].get("peak_mm"),
                     "wet_share": d["alpensued"].get("wet_share"),
                     "max_cape": d["alpensued"].get("max_cape"),
                     "max_coverage": d["alpensued"].get("max_coverage"),
                     "n_spots": d["alpensued"].get("n_spots"),
                 }}
                for d in (ctx.get("precip_pattern") or {}).get("per_day", [])
            ],
        },
        "schneefallgrenze": (
            None if ctx.get("schneefallgrenze") is None
            else {
                "value_m": ctx["schneefallgrenze"]["value"],
                "per_day": ctx["schneefallgrenze"]["per_day"],
            }
        ),
        "confidence_per_day": ctx.get("confidence_per_day") or [],
    }
    return (
        f"AKTUELLE LOKALZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"WETTERLAGE-STRUKTURFELD:\n{json.dumps(out, ensure_ascii=False, indent=2)}\n"
    )


def _strip_provenance(field: Optional[dict]) -> Optional[dict]:
    """Entfernt interne Provenance-Felder (decided_by, inputs, thresholds)
    vor LLM-Uebergabe — der LLM braucht sie nicht, sie wuerden nur Tokens
    fressen.
    """
    if field is None:
        return None
    return {k: v for k, v in field.items()
            if k not in ("decided_by", "inputs", "thresholds", "source")}


def _flow_overhead_for_llm(fo: Optional[dict]) -> Optional[dict]:
    """Wie _strip_provenance, aber bereinigt zusaetzlich die per_day-Eintraege
    von Rohzahlen (dir_deg, speed_kmh) — der LLM sieht nur sector + strength
    pro Tag, was zur Pilotensprache passt.
    """
    if fo is None:
        return None
    cleaned = _strip_provenance(fo)
    per_day = cleaned.get("per_day") or []
    cleaned["per_day"] = [
        {"date": d.get("date"),
         "sector": d.get("sector"),
         "strength": d.get("strength")}
        for d in per_day
    ]
    return cleaned


# ============================================================================
# INTERNAL: Post-Filter
# ============================================================================

def _collect_valid_center_labels(ctx: dict) -> set:
    """Sammelt alle Region-Labels, die im Strukturfeld detektiert wurden.
    Saetze, die andere (erfundene) Regionen nennen, werden verworfen.
    """
    labels = set()
    for d in ctx.get("pressure_centers_per_day") or []:
        for c in d.get("centers") or []:
            labels.add(c.get("region_label"))
    return labels


def _filter_statements(statements: list, valid_centers: set) -> list:
    """Filtert Saetze nach Verbotsbegriffen + Source-Validierung."""
    filtered = []
    for st in statements:
        if not isinstance(st, dict):
            continue
        text = st.get("text") or ""
        sources = st.get("sources") or []
        if not isinstance(text, str) or not text.strip():
            continue
        if not isinstance(sources, list):
            continue

        # Verbotsbegriffe?
        rejected_reason = None
        for pattern in _FORBIDDEN_PATTERNS:
            if pattern.search(text):
                rejected_reason = f"forbidden_term:{pattern.pattern}"
                break

        # Sources valide?
        if rejected_reason is None:
            invalid = [s for s in sources if s not in _VALID_SOURCE_KEYS]
            if invalid:
                rejected_reason = f"invalid_source:{invalid}"

        # Saetze ohne mindestens eine valide Source verwerfen
        if rejected_reason is None and not sources:
            rejected_reason = "no_sources"

        # Erwaehnte Druckzentren-Labels muessen im Strukturfeld stehen
        if rejected_reason is None and "pressure_centers_per_day" in sources:
            mentioned_invalid = _check_pressure_region_mentions(text, valid_centers)
            if mentioned_invalid:
                rejected_reason = f"invalid_region:{mentioned_invalid}"

        if rejected_reason:
            logger.info("Post-Filter verworfen: %s — '%s'", rejected_reason, text)
            continue
        filtered.append(st)
    return filtered


# Praefix-Regex: "Heute:", "Morgen:", "Uebermorgen:", "Tag 1:" oder Wochentag.
_WEEKDAY_SET = {w.lower() for w in _WOCHENTAGE}
_PREFIX_RE = re.compile(
    r"^(Heute|Morgen|Uebermorgen|Übermorgen|Tag\s*\d+|"
    r"Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)\s*:\s*",
    re.IGNORECASE,
)


def _normalize_weekday_prefixes(statements: list, forecast_dates: list) -> list:
    """Setzt das Wochentag-Praefix jedes Statements auf den korrekten
    Wochentag aus `forecast_dates`. Der briefing.js-Renderer matcht nur
    `^(Montag|...|Sonntag):` — Eintraege mit "Heute:"/"Morgen:" oder
    verschobenen Wochentagen werden sonst als unbeschriftete Lead-Absaetze
    gerendert, was den Wetterlage-Block luckenhaft wirken laesst.

    Annahme: statements[i] gehoert zum i-ten Forecast-Tag (per Skill-Vertrag).
    Wir setzen das Praefix anhand der Position autoritativ, unabhaengig
    davon, was der LLM gewaehlt hat.
    """
    if not statements or not forecast_dates:
        return statements
    out = []
    for i, st in enumerate(statements):
        if i >= len(forecast_dates):
            out.append(st)
            continue
        try:
            correct_wd = _weekday_de(forecast_dates[i])
        except Exception:
            out.append(st)
            continue
        text = st.get("text") or ""
        m = _PREFIX_RE.match(text)
        if m:
            existing = m.group(1).strip()
            if existing.lower() == correct_wd.lower():
                out.append(st)
                continue
            new_text = f"{correct_wd}: {text[m.end():].lstrip()}"
            logger.info(
                "Wetterlage-Praefix korrigiert (day %d): '%s' -> '%s'",
                i + 1, existing, correct_wd,
            )
        else:
            new_text = f"{correct_wd}: {text.lstrip()}"
            logger.info(
                "Wetterlage-Praefix ergaenzt (day %d, kein Praefix): '%s'",
                i + 1, correct_wd,
            )
        st2 = dict(st)
        st2["text"] = new_text
        out.append(st2)
    return out


# Kalenderwochen-Begriffe → zeitraum-neutral. Der Cast ist ein rollierender
# 5-Tage-Block ab HEUTE, KEINE Kalenderwoche (forecast_dates[0] kann jeder
# Wochentag sein). Begriffe wie "Wochenmitte"/"zum Wochenstart" unterstellen
# einen Montag-Start und sind irrefuehrend. Der Skill verbietet sie bereits;
# dieser Normalizer ist das deterministische Sicherheitsnetz fuer den Fall,
# dass der LLM sie trotzdem verwendet. WICHTIG: greift NICHT auf "Wochentag"
# /"Wochentage" (Tagesnamen-Bezug, voellig korrekt) — die Patterns matchen
# nur die Positions-/Zeitraum-Begriffe.
_CALENDAR_WEEK_SUBS = [
    (re.compile(r"\bdie\s+Woche\s+startet\b", re.IGNORECASE), "die kommenden Tage starten"),
    (re.compile(r"\bzum\s+Wochen(start|beginn)\b", re.IGNORECASE), "zu Beginn"),
    (re.compile(r"\bzu\s+Wochenbeginn\b", re.IGNORECASE), "zu Beginn"),
    (re.compile(r"\b(gegen|zum|am)\s+Wochenende\b", re.IGNORECASE), "zum Ende des Zeitraums"),
    (re.compile(r"\bin\s+der\s+Wochenmitte\b", re.IGNORECASE), "in der Mitte des Zeitraums"),
    (re.compile(r"\bzur\s+Wochenmitte\b", re.IGNORECASE), "zur Mitte des Zeitraums"),
    (re.compile(r"\bWochenmitte\b", re.IGNORECASE), "Mitte des Zeitraums"),
    (re.compile(r"\bdie\s+ganze\s+Woche\b", re.IGNORECASE), "den ganzen Zeitraum"),
    (re.compile(r"\b(ue?ber|über)\s+die\s+Woche\b", re.IGNORECASE), "über den Zeitraum"),
]


def _neutralize_calendar_week_terms(statements: list) -> list:
    """Ersetzt Kalenderwochen-Begriffe in `text` und `flight_hint` durch
    zeitraum-neutrale Formulierungen. Belt-and-suspenders zum Skill-Verbot.
    """
    if not statements:
        return statements
    out = []
    for st in statements:
        st2 = dict(st)
        for field in ("text", "flight_hint"):
            val = st2.get(field)
            if not val:
                continue
            new_val = val
            for pat, repl in _CALENDAR_WEEK_SUBS:
                new_val = pat.sub(repl, new_val)
            if new_val != val:
                logger.info("Kalenderwochen-Begriff neutralisiert: %r -> %r", val, new_val)
                st2[field] = new_val
        out.append(st2)
    return out


# Regex-Pattern fuer "windgeschuetzt/ruhig/geschuetzt"-Behauptungen auf
# Lee-Seiten. App-Konvention nutzt "ue/ae/oe" — wir matchen beide Varianten
# defensiv ueber explizite escape-Codes (kein literales ü/ö im Source-File,
# das im Build/Encoding gelegentlich kaputt geht).
_U_UMLAUT = "[u\u00fc]"     # u or ü
_A_UMLAUT = "[a\u00e4]"     # a or ä
_O_UMLAUT = "[o\u00f6]"     # o or ö

_LEE_SHELTER_TERMS_RE = re.compile(
    rf"(windgeschuetzt|windgesch{_U_UMLAUT}tzt|"
    rf"geschuetzt|gesch{_U_UMLAUT}tzt|"
    rf"windstill|ruhig|windarm|abgeschirmt)",
    re.IGNORECASE,
)
_ALPENNORD_RE = re.compile(
    rf"alpennord(?:seite|hang|en|h{_A_UMLAUT}ngen)?",
    re.IGNORECASE,
)
_ALPENSUED_RE = re.compile(
    rf"alpens(?:ued|{_U_UMLAUT}d)(?:seite|hang|en|h{_A_UMLAUT}ngen)?|"
    rf"tessin|"
    rf"s(?:ued|{_U_UMLAUT}d)b(?:uenden|{_U_UMLAUT}nden)",
    re.IGNORECASE,
)


def _text_inverts_foehn_lee(text: str, foehn_side: str) -> bool:
    """Returns True wenn `text` die Foehn-Lee-Seite (laut `foehn_side`)
    explizit als geschuetzt/ruhig/windgeschuetzt beschreibt.

    Heuristik: Suche das Lee-Seiten-Token und ein Shelter-Term im selben
    Satz (gleiches Statement → eine Sentence-Distanz reicht).
    """
    if not isinstance(text, str) or not text.strip():
        return False
    side = (foehn_side or "").lower()
    if side not in {"nord", "sued", "süd", "suedfoehn", "südfoehn", "nordfoehn"}:
        return False
    is_nord = side.startswith("nord")
    lee_re = _ALPENSUED_RE if is_nord else _ALPENNORD_RE

    for sentence in re.split(r"(?<=[\.\!\?])\s+", text):
        if not sentence.strip():
            continue
        if not lee_re.search(sentence):
            continue
        if _LEE_SHELTER_TERMS_RE.search(sentence):
            return True
    return False


def _filter_foehn_lee_inversion(statements: list, foehn_struct: dict,
                                forecast_dates: list) -> list:
    """Pro long-Statement[i] pruefen, ob es die Foehn-Lee-Seite an dem
    konkreten Forecast-Tag i als "geschuetzt/windgeschuetzt/ruhig"
    beschreibt, obwohl `foehn.per_day[i]` aktiven Foehn der entsprechenden
    Richtung meldet. Verstoss → `text` wird verworfen (Statement faellt
    raus, da `text` PFLICHT ist). Auch `flight_hint` wird gepruft und
    bei Verstoss entfernt (Statement bleibt aber stehen).

    Wir matchen den Index aus statements[i] auf forecast_dates[i] und
    schlagen damit foehn.per_day[i] nach (date-match — robust auch wenn
    foehn.per_day separat sortiert ist).
    """
    if not statements or not foehn_struct or not forecast_dates:
        return statements
    per_day = foehn_struct.get("per_day") or []
    per_day_by_date = {d.get("date"): d for d in per_day if isinstance(d, dict)}

    out = []
    for i, st in enumerate(statements):
        if i >= len(forecast_dates):
            out.append(st)
            continue
        date_str = forecast_dates[i]
        day_foehn = per_day_by_date.get(date_str)
        if not day_foehn:
            out.append(st)
            continue
        nord_active = bool(day_foehn.get("nord_active"))
        sued_active = bool(day_foehn.get("sued_active"))
        if not (nord_active or sued_active):
            out.append(st)
            continue
        active_side = "nord" if nord_active else "sued"

        text = st.get("text") or ""
        if _text_inverts_foehn_lee(text, active_side):
            logger.info(
                "Foehn-Lee-Inversion verworfen (day %s, side=%s): '%s'",
                date_str, active_side, text,
            )
            continue

        # flight_hint mit gleicher Inversion separat pruefen
        hint = st.get("flight_hint")
        if hint and _text_inverts_foehn_lee(hint, active_side):
            logger.info(
                "Foehn-Lee-Inversion in flight_hint verworfen (day %s, side=%s): '%s'",
                date_str, active_side, hint,
            )
            st = dict(st)
            st.pop("flight_hint", None)

        out.append(st)
    return out


def _hint_has_forbidden(text: str) -> Optional[str]:
    """Findet das erste Verbots-Pattern in einem Hint-Text. Liefert das
    Pattern als Debug-String oder None."""
    if not isinstance(text, str):
        return "non_string"
    for pattern in _FORBIDDEN_PATTERNS:
        if pattern.search(text):
            return pattern.pattern
    return None


def _sanitize_flight_hints(statements: list) -> list:
    """Validiert das optionale `flight_hint`-Feld jedes long-Eintrags
    gegen die Verbotsbegriffe. Verstoss → flight_hint wird entfernt,
    der Eintrag selbst bleibt aber stehen. Leere/zu kurze Hints werden
    ebenfalls entfernt (verhindert leere Zeilen im Frontend).
    """
    out = []
    for st in statements:
        if "flight_hint" not in st:
            out.append(st)
            continue
        hint = st.get("flight_hint")
        if not isinstance(hint, str) or len(hint.strip()) < 3:
            st2 = dict(st)
            st2.pop("flight_hint", None)
            out.append(st2)
            continue
        bad = _hint_has_forbidden(hint)
        if bad:
            logger.info("flight_hint verworfen (forbidden:%s): '%s'", bad, hint)
            st2 = dict(st)
            st2.pop("flight_hint", None)
            out.append(st2)
            continue
        st2 = dict(st)
        st2["flight_hint"] = hint.strip()
        out.append(st2)
    return out


# Bekannte Region-Labels aus config.EUROPE_PRESSURE_GRID — gegen diese
# pruefen wir, ob der LLM eine Region nennt, die NICHT detektiert wurde.
_KNOWN_GRID_LABELS = {p["label"] for p in config.EUROPE_PRESSURE_GRID}


def _check_pressure_region_mentions(text: str, valid_centers: set) -> list:
    """Findet Region-Labels im Text, die im Grid existieren aber NICHT
    fuer den aktuellen Cast detektiert wurden.

    Returns: Liste der ungueltigen Region-Erwaehnungen.
    """
    invalid = []
    text_lower = text.lower()
    for label in _KNOWN_GRID_LABELS:
        # Pruefe ob das Label (oder eine kanonische Kurzform) im Text vorkommt
        for variant in _label_variants(label):
            if variant in text_lower:
                if label not in valid_centers:
                    invalid.append(label)
                break
    return invalid


def _label_variants(label: str) -> list[str]:
    """Generiert sinnvolle Erwaehnungs-Varianten fuer ein Region-Label.

    Z.B. "Norditalien / Genua" → ["norditalien", "genua", "norditalien / genua"]
    """
    out = [label.lower()]
    # Slash-Trennung
    if "/" in label:
        out.extend(part.strip().lower() for part in label.split("/"))
    # Klammern raus
    if "(" in label:
        out.append(re.sub(r"\s*\([^)]*\)", "", label).strip().lower())
    return out
