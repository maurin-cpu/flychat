"""LLM-Caller + Validierungs-/Korrektur-Loop fuer den Wetterlage-Block.

Nimmt das deterministisch erzeugte Strukturfeld aus synoptic_context.build_*
und laesst den LLM daraus eine Prosa-Version generieren (lead + days).

Architektur (ersetzt den alten Loesch-Post-Filter):
  1. LLM bekommt nur das fertige Strukturfeld, keine Rohzahlen.
  2. Output-Format (Synoptik 2.0, Zonen):
     {"lead": str,
      "zones": [{"zone": <id>, "days": [{text, flight_hint}]}, ...]}
     — Zuordnung days[i] <-> forecast_dates[i] per POSITION, Zonen ueber
     die zone-ID (nicht ueber die Reihenfolge). Die alte Source-Tag-Pflicht
     ist abgeschafft: sie hat nur Formfehler produziert (invalid_source
     loeschte am 05.07.2026 den halben Ueberblick) und keine echte
     Halluzinations-Sicherheit gebracht.
  3. _validate() prueft INHALTLICH (Verbotsbegriffe, erfundene Regionen,
     Foehn-Lee-Inversion, Schema/Vollstaendigkeit) — und loescht NICHTS.
  4. Bei Fehlern bekommt der LLM eine Korrektur-Nachricht mit der konkreten
     Fehlerliste und erzeugt neu — max. _MAX_ATTEMPTS Versuche.
  5. Nach erschoepften Versuchen: beste Version chirurgisch bereinigen
     (nur verletzende Teile entfernen, nie alles verwerfen) und
     Admin-Alarm per Mail (config.ADMIN_EMAIL) — kein stilles Loeschen mehr.
  6. Bei API-Fehler ueber alle Versuche → return None, Block wird ausgelassen.
"""

import json
import logging
import re
from datetime import datetime
from typing import Optional

import config
import prompts
from engine._common import _weekday_de, _WOCHENTAGE, deepseek_thinking_kwargs

logger = logging.getLogger(__name__)

# Max. LLM-Versuche pro Overview (1 Erstversuch + 3 Korrektur-Runden).
# 3 war zu knapp: Der Zonen-Block hat mehr Pruefflaechen als v1.0 (4 Zonen ×
# Tage statt einer flachen Liste), und am 25.07.2026 brauchte ein Lauf genau
# 3/3 — ohne Reserve. Die 4. Runde kostet nur im Fehlerfall einen Call.
_MAX_ATTEMPTS = 4

_WEEKDAYS_EN = ("Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday")


def _weekday_label(date_str: str) -> str:
    """Wochentagname in der aktiven UI-Sprache (i18n.get_current_lang()).

    Wird fuer das LLM-Payload UND das autoritative days-Praefix verwendet —
    beide muessen zusammenpassen, sonst schreibt der LLM im EN-Modus
    Mischformen wie "Sonntag (Sunday):" (Vorfall 05.07.2026: Payload
    lieferte deutsche Wochentage, Skill/Output waren englisch).
    """
    import i18n
    if i18n.get_current_lang() == "en":
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return _WEEKDAYS_EN[d.weekday()]
    return _weekday_de(date_str)


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
    # "CAPE" ist Modell-Jargon. Der Skill verlangt die Uebersetzung in
    # Pilotensprache ("labile Luft", "Ueberentwicklungs-Potenzial") —
    # der DE-Lauf 26.07.2026 schrieb trotzdem "labile Luft und hoher CAPE".
    re.compile(r"\bcape\b", re.IGNORECASE),
    # "Vb" ist die Zugbahn-Nummer nach van Bebber (Bahn V, Variante b).
    # Im Cast stand "a Vb low brings unsettled weather" — fuer Piloten
    # nichtssagend. Der gemeinte Sachverhalt heisst "Genua-Tief".
    # Bewusst case-sensitiv, damit die Schreibweise "Vb" gemeint ist und
    # nicht irgendein Kleinbuchstaben-Zufall.
    re.compile(r"\bVb\b"),
]

# Foehn-Erwaehnung in beliebiger Schreibweise (Nordfoehn, Foehnschneise,
# "foehn corridor"). Zulaessig nur an Tagen, an denen das Strukturfeld
# Foehn wirklich meldet — sonst ist es eine erfundene Gefahrenlage.
_FOEHN_MENTION_RE = re.compile(r"f(?:oe|ö|o)hn", re.IGNORECASE)


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
    """Generiert den Wetterlage-Block mit Validierungs-/Korrektur-Loop.

    Ablauf: LLM-Call → _validate() → bei Fehlern Korrektur-Nachricht mit
    konkreter Fehlerliste anhaengen und neu generieren (max _MAX_ATTEMPTS).
    Nach erschoepften Versuchen wird die beste Version chirurgisch bereinigt
    ausgeliefert (nie leer, solange irgendetwas Valides da ist) und der
    Admin per Mail alarmiert.

    Returns:
        {"short": str,                      # lead (Mail + UI-Kurzfassung)
         "zones": [{"zone", "label", "days": [{text, flight_hint}]}],
         "long": str, "long_with_sources": [...],   # Legacy-Kompatibilitaet
         "attempts": int, "unresolved": [str], "generated_at": str}
        — short/long/long_with_sources bleiben fuer Konsumenten ohne
        Zonen-Support erhalten (long_with_sources = groesste Zone).
        None nur bei API-Totalausfall oder wenn gar nichts Valides uebrig ist.
    """
    if not synoptic_context:
        return None
    if not analysis_client:
        logger.warning("generate_synoptic_overview: kein analysis_client")
        return None

    messages = [
        {"role": "system", "content": _compose_system_prompt()},
        {"role": "user", "content": _build_llm_payload(synoptic_context)},
    ]

    best = None  # (n_errors, parsed, errors) — beste bisherige Version
    last_errors = []
    attempts_done = 0

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        attempts_done = attempt
        raw = _call_llm(analysis_client, analysis_model, messages)
        if raw is None:
            # API-Fehler / leerer Output — Retry mit unveraenderter Konversation
            last_errors = [_verr("api", "api_error",
                                 "LLM-Call fehlgeschlagen oder leerer Output")]
            continue

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("generate_synoptic_overview: JSON parse failed "
                           "(Versuch %d): %s — raw[:300]=%r", attempt, e, raw[:300])
            parsed = None

        if parsed is None or not isinstance(parsed, dict):
            errors = [_verr("format", "invalid_json",
                            "Die Antwort war kein gueltiges JSON-Objekt. "
                            "Nur das JSON-Objekt liefern, keine Code-Fences.")]
        else:
            errors = _validate(parsed, synoptic_context)
            if best is None or len(errors) < best[0]:
                best = (len(errors), parsed, errors)

        if not errors:
            return _finalize(parsed, synoptic_context,
                             attempts=attempt, unresolved=[])

        logger.warning(
            "Wetterlage-Overview Versuch %d/%d: %d Fehler — %s",
            attempt, _MAX_ATTEMPTS, len(errors),
            "; ".join(f"[{e['scope']}] {e['message']}" for e in errors),
        )
        last_errors = errors

        if attempt < _MAX_ATTEMPTS:
            # Korrektur-Runde: vorherige Antwort + konkrete Fehlerliste anhaengen
            messages = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": _build_correction_message(errors)},
            ]

    # ------------------------------------------------------------------
    # Versuche erschoepft — Schicht 2: beste Version chirurgisch bereinigen
    # (nie alles verwerfen), Schicht 3: Admin alarmieren.
    # ------------------------------------------------------------------
    if best is None:
        logger.error("generate_synoptic_overview: kein parsebarer Output "
                     "nach %d Versuchen", attempts_done)
        _notify_admin(last_errors, attempts_done, delivered=False)
        return None

    _, parsed, errors = best
    result = _finalize(parsed, synoptic_context,
                       attempts=attempts_done, unresolved=errors, prune=True)
    _notify_admin(errors, attempts_done, delivered=result is not None)
    return result


# ============================================================================
# INTERNAL: LLM-Call + Korrektur-Nachricht
# ============================================================================

def _extract_json_object(text: str) -> Optional[str]:
    """Findet das LETZTE vollstaendige JSON-Objekt in einem Freitext.

    Fuer den reasoning_content-Fallback: der Reasoning-Kanal kann mehrere
    Entwuerfe enthalten — der letzte ist die finale Antwort.
    """
    if not isinstance(text, str):
        return None
    decoder = json.JSONDecoder()
    found = None
    i = text.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(text, i)
            if isinstance(obj, dict):
                found = text[i:end]
                i = text.find("{", end)
                continue
        except ValueError:
            pass
        i = text.find("{", i + 1)
    return found


def _call_llm(analysis_client, analysis_model: str,
              messages: list) -> Optional[str]:
    """Ein LLM-Versuch. Liefert den rohen Antwort-String oder None."""
    try:
        response = analysis_client.chat.completions.create(
            model=analysis_model,
            messages=messages,
            temperature=0.4,
            # 12000 statt 4000: Headroom fuer den Fall, dass Thinking
            # (SYNOPTIC_THINKING) reaktiviert wird — Reasoning-Tokens kommen
            # VOR der Antwort. Ungenutztes Budget kostet nichts. Bei
            # Truncation kommt finish_reason=length und das JSON ist
            # mittendrin abgeschnitten.
            max_tokens=12000,
            response_format={"type": "json_object"},
            # Thinking-Modus haengt am eigenen Schalter SYNOPTIC_THINKING
            # (Default aus — Ausfall 01.08.2026: v4-flash schreibt bei dieser
            # Output-Menge die Antwort in reasoning_content und laesst
            # content leer; Messzahlen in config.py bei SYNOPTIC_THINKING).
            **deepseek_thinking_kwargs(
                getattr(config, "SYNOPTIC_PROVIDER", ""), analysis_model,
                thinking_enabled=getattr(config, "SYNOPTIC_THINKING", False)),
        )
        finish = getattr(response.choices[0], "finish_reason", None)
        message = response.choices[0].message
        raw = message.content
        if not raw:
            # Thinking-Modus-Falle: v4-flash liefert die komplette Antwort
            # in reasoning_content und laesst content leer (finish=stop).
            # Ohne diesen Fallback scheitert der Thinking-Modus STILL.
            reasoning = getattr(message, "reasoning_content", None)
            salvaged = _extract_json_object(reasoning) if reasoning else None
            if salvaged:
                logger.warning(
                    "_call_llm: content leer (finish_reason=%s) — JSON aus "
                    "reasoning_content uebernommen (%d Zeichen Reasoning)",
                    finish, len(reasoning))
                return salvaged
            logger.warning("_call_llm: leerer LLM-Output (finish_reason=%s)", finish)
            return None
        if finish == "length":
            logger.warning("_call_llm: Output truncated bei max_tokens "
                           "— JSON ggf. unvollstaendig (finish_reason=length)")
        return raw
    except Exception as e:
        logger.error("_call_llm fehlgeschlagen: %s", e)
        return None


def _build_correction_message(errors: list) -> str:
    """Baut die Korrektur-Nachricht fuer die naechste LLM-Runde.

    Der Header enthaelt beide Keywords (DE-Skill: "KORREKTUR NOETIG",
    EN-Skill: "CORRECTION REQUIRED") — der Block funktioniert damit in
    beiden Sprachmodi ohne i18n-Weiche.
    """
    lines = "\n".join(f"- [{e['scope']}] {e['message']}" for e in errors)
    return (
        "KORREKTUR NOETIG / CORRECTION REQUIRED\n\n"
        "Deine letzte Antwort hatte folgende Fehler:\n"
        f"{lines}\n\n"
        "Erzeuge das KOMPLETTE JSON neu (gleiches Format: "
        '{"lead": "...", "zones": [{"zone": "<zone_id>", '
        '"days": [{"text": "...", "flight_hint": "..."}]}]}) '
        "und behebe ALLE genannten Punkte. Alle uebrigen Regeln aus dem "
        "System-Prompt gelten unveraendert. Nur das JSON, kein Kommentar."
    )


# ============================================================================
# INTERNAL: Validierung (prueft, loescht NICHTS)
# ============================================================================

def _verr(scope: str, kind: str, message: str) -> dict:
    return {"scope": scope, "kind": kind, "message": message}


def _find_forbidden_term(text: str) -> Optional[str]:
    """Findet das erste Verbots-Pattern in einem Text. Liefert das
    Pattern als Debug-String oder None."""
    if not isinstance(text, str):
        return "non_string"
    for pattern in _FORBIDDEN_PATTERNS:
        if pattern.search(text):
            return pattern.pattern
    return None


# Lob-Vokabular, das an beidseitig windkritischen Tagen (wind_class
# verblasen/stark_eingeschraenkt auf BEIDEN Seiten) verboten ist —
# DE + EN, bewusst kurze Liste mit eindeutigen Gesamturteils-Phrasen.
_PRAISE_RE = re.compile(
    r"(ideal|excellent|exzellent|hervorragend|perfekt|perfect|highlight|"
    r"top-?tag|beste[rn]?\s+(flug)?tag|best\s+day|"
    r"gute[rn]?\s+flug(tag|bedingungen)|good\s+(flying\s+day|conditions)|"
    r"great\s+(day|conditions))",
    re.IGNORECASE,
)

_WINDY_CLASSES = {"verblasen", "stark_eingeschraenkt"}


def _zone_wind_class(ctx: dict, zone: str, i: int) -> Optional[str]:
    """wind_class einer Zone am Forecast-Tag i (aus wind_zones), oder None."""
    wz = ctx.get("wind_zones") or {}
    per_day = wz.get("per_day") or []
    if i >= len(per_day):
        return None
    return (((per_day[i].get("zones") or {}).get(zone) or {})
            .get("wind_class"))


def _zone_gewitter_share(ctx: dict, zone: str, i: int) -> Optional[float]:
    """gewitter_share (Tages-Aggregat) einer Zone am Tag i, oder None."""
    pz = ctx.get("precip_zones") or {}
    per_day = pz.get("per_day") or []
    if i >= len(per_day):
        return None
    day = (((per_day[i].get("zones") or {}).get(zone) or {}).get("day") or {})
    share = day.get("gewitter_share")
    return share if isinstance(share, (int, float)) else None


def _zone_konvektion(ctx: dict, zone: str, i: int, key: str) -> list:
    """Weiche Konvektions-Signale (Ensemble/Wolkentop) einer Zone am Tag i.

    key: "gewitter" oder "ueberentwicklung". Leere Liste, wenn nichts da —
    aeltere Caches haben das Feld nicht.
    """
    per_day = (ctx.get("konvektion") or {}).get("per_day") or []
    if i >= len(per_day):
        return []
    return (((per_day[i].get("zones") or {}).get(zone) or {}).get(key)) or []


# Gewitter-Wortfeld. Gewitter-Signale sind gewitter_share (weather_code
# 95/96/99) ODER konvektion.gewitter (Ensemble + Anker, seit 03.08.2026) —
# hohe CAPE allein heisst weiterhin nur "labile Luft".
_GEWITTER_RE = re.compile(r"(gewitter|thunderstorm|thunder\b)", re.IGNORECASE)


# Zone(n), die bei aktivem Foehn die boeige LEE-Seite sind — dort sind
# Ruhe-/Schutz-Behauptungen im Zonentext auch OHNE Regionen-Token falsch.
_FOEHN_LEE_ZONES = {
    "nord": ("tessin",),                      # Nordfoehn -> Tessin ist Lee
    "sued": ("alpennordhang", "wallis"),      # Suedfoehn -> Nordseite/Foehntaeler
}

_CALM_CLAIM_RE = re.compile(
    r"(windgeschuetzt|windgeschützt|geschuetzt|geschützt|"
    r"sheltered|protected|windstill|windless|ruhig|windarm|windschwach|calm)",
    re.IGNORECASE,
)


def _validate(parsed: dict, ctx: dict) -> list:
    """Prueft den LLM-Output (Zonen-Format) inhaltlich und strukturell.

    Erwartetes Format:
      {"lead": str,
       "zones": [{"zone": <zone_id>, "days": [{text, flight_hint}, ...]}, ...]}

    Liefert eine Fehlerliste [{scope, kind, message}] — leere Liste = OK.
    Loescht bewusst NICHTS: die Reaktion (Korrektur-Runde / chirurgisches
    Bereinigen / Alarm) entscheidet der Aufrufer.
    """
    errors = []
    fc_dates = ctx.get("forecast_dates") or []
    valid_centers = _collect_valid_center_labels(ctx)
    foehn = ctx.get("foehn") or {}

    # --- lead -----------------------------------------------------------
    lead = parsed.get("lead")
    if not isinstance(lead, str) or not lead.strip():
        errors.append(_verr("lead", "schema",
                            "`lead` fehlt oder ist leer — Pflichtfeld "
                            "(Fliesstext-String, 4-6 Saetze, max 130 Woerter)."))
    else:
        bad = _find_forbidden_term(lead)
        if bad:
            errors.append(_verr("lead", "forbidden_term",
                                f"`lead` enthaelt einen verbotenen Begriff "
                                f"(Muster: {bad}). Umformulieren ohne "
                                f"Front-/Trog-Jargon und ohne hPa-/°C-Zahlen."))
        invalid_regions = _check_pressure_region_mentions(lead, valid_centers)
        if invalid_regions:
            errors.append(_verr("lead", "invalid_region",
                                f"`lead` nennt Druckzentren-Regionen, die im "
                                f"Strukturfeld NICHT detektiert sind: "
                                f"{invalid_regions}. Erlaubt sind ausschliesslich "
                                f"diese region_label: {_allowed_centers(valid_centers)}. "
                                f"Streiche die erfundene Region ersatzlos oder "
                                f"ersetze sie durch ein erlaubtes Label."))
        n_words = len(lead.split())
        if n_words > 150:
            errors.append(_verr("lead", "too_long",
                                f"`lead` hat {n_words} Woerter — erlaubt sind "
                                f"max 130. Kuerzen."))

    # --- zones: Schema + Vollstaendigkeit --------------------------------
    zones = parsed.get("zones")
    if not isinstance(zones, list):
        errors.append(_verr("zones", "schema",
                            "`zones` fehlt oder ist keine Liste — Pflichtfeld "
                            "(ein Eintrag pro Zone: "
                            f"{list(config.SYNOPTIC_ZONES)})."))
        return errors

    seen_zones = []
    for j, z in enumerate(zones):
        if not isinstance(z, dict):
            errors.append(_verr(f"zones[{j}]", "schema",
                                "Zonen-Eintrag muss ein Objekt sein "
                                '({"zone": "...", "days": [...]}).'))
            continue
        zone_id = z.get("zone")
        if zone_id not in config.SYNOPTIC_ZONES:
            errors.append(_verr(f"zones[{j}]", "unknown_zone",
                                f"`zone`={zone_id!r} ist keine gueltige Zone. "
                                f"Erlaubt sind exakt diese IDs: "
                                f"{list(config.SYNOPTIC_ZONES)}."))
            continue
        seen_zones.append(zone_id)
        errors.extend(_validate_zone(z, zone_id, ctx, fc_dates,
                                     valid_centers, foehn))

    missing = [z for z in config.SYNOPTIC_ZONES if z not in seen_zones]
    if missing:
        errors.append(_verr("zones", "incomplete",
                            f"Es fehlen Zonen: {missing}. Jede der "
                            f"{len(config.SYNOPTIC_ZONES)} Zonen braucht genau "
                            f"einen Eintrag — auch wenn dort wenig passiert."))
    dupes = [z for z in set(seen_zones) if seen_zones.count(z) > 1]
    if dupes:
        errors.append(_verr("zones", "duplicate",
                            f"Zonen doppelt vorhanden: {dupes}. Genau ein "
                            f"Eintrag pro Zone."))

    return errors


def _validate_zone(z: dict, zone_id: str, ctx: dict, fc_dates: list,
                   valid_centers: set, foehn: dict) -> list:
    """Prueft einen Zonen-Eintrag (days-Vollstaendigkeit + Inhalt pro Tag)."""
    errors = []
    days = z.get("days")
    if not isinstance(days, list):
        errors.append(_verr(f"zones[{zone_id}]", "schema",
                            "`days` fehlt oder ist keine Liste — ein Eintrag "
                            "pro forecast_date, gleiche Reihenfolge."))
        return errors
    if fc_dates and len(days) != len(fc_dates):
        errors.append(_verr(f"zones[{zone_id}]", "schema",
                            f"`days` hat {len(days)} Eintraege, erwartet "
                            f"{len(fc_dates)} — exakt einer pro Tag in "
                            f"forecast_dates-Reihenfolge, keiner fehlt, "
                            f"keiner doppelt."))

    for i, d in enumerate(days):
        scope = f"zones[{zone_id}].days[{i}]"
        if not isinstance(d, dict) or not isinstance(d.get("text"), str) \
                or not d["text"].strip():
            errors.append(_verr(scope, "schema",
                                "Eintrag braucht ein nicht-leeres `text`-Feld."))
            continue
        text = d["text"]
        hint = d.get("flight_hint")
        hint_str = hint if isinstance(hint, str) else ""

        bad = _find_forbidden_term(text)
        if bad:
            errors.append(_verr(scope, "forbidden_term",
                                f"`text` enthaelt einen verbotenen Begriff "
                                f"(Muster: {bad})."))

        invalid_regions = _check_pressure_region_mentions(text, valid_centers)
        if invalid_regions:
            errors.append(_verr(scope, "invalid_region",
                                f"`text` nennt nicht detektierte Regionen: "
                                f"{invalid_regions}. Erlaubt sind ausschliesslich "
                                f"diese region_label: "
                                f"{_allowed_centers(valid_centers)}."))

        # --- Foehn-Lee: zonen-basiert (der Zonentext nennt die Region oft
        # gar nicht mehr — die Zone IST die Ortsangabe) + Text-Heuristik.
        active_side = _foehn_active_side(foehn, fc_dates, i)
        if active_side:
            lee_zones = _FOEHN_LEE_ZONES.get(active_side, ())
            calm_hit = (_CALM_CLAIM_RE.search(text)
                        or _CALM_CLAIM_RE.search(hint_str))
            if zone_id in lee_zones and calm_hit:
                errors.append(_verr(scope, "foehn_lee_inversion",
                                    f"An diesem Tag ist "
                                    f"{active_side.capitalize()}foehn aktiv — "
                                    f"diese Zone ist die boeige LEE-Seite. Das "
                                    f"Wort {calm_hit.group(0)!r} ist hier "
                                    f"verboten, in `text` UND in `flight_hint`. "
                                    f"Trocken/sonnig darfst du schreiben — der "
                                    f"Wind-Teil MUSS aber die Boeigkeit nennen. "
                                    f"Baumuster: '<trocken/sonnig>, aber "
                                    f"boeiger {active_side.capitalize()}foehn "
                                    f"in den Lee-Taelern'. Ersetze das Wort, "
                                    f"streiche es nicht bloss."))
            elif _text_inverts_foehn_lee(text, active_side) or \
                    _text_inverts_foehn_lee(hint_str, active_side):
                lee = "Alpensuedseite" if active_side == "nord" else "Alpennordseite"
                errors.append(_verr(scope, "foehn_lee_inversion",
                                    f"{active_side.capitalize()}foehn aktiv — die "
                                    f"{lee} ist die boeige LEE-Seite und darf "
                                    f"nicht als geschuetzt/ruhig gelten."))
        else:
            # Kein Foehn an DIESEM Tag: `foehn.active` gilt fuer den ganzen
            # Zeitraum, die Gefahr aber nur an `days_affected`. Ohne diese
            # Pruefung wandert die Foehn-Warnung auf ruhige Tage (DE-Lauf
            # 26.07.2026: "Foehnschneisen kritisch" an einem foehnfreien Tag).
            foehn_hit = (_FOEHN_MENTION_RE.search(text)
                         or _FOEHN_MENTION_RE.search(hint_str))
            if foehn_hit:
                errors.append(_verr(scope, "foehn_not_active",
                                    f"An diesem Tag meldet das Strukturfeld "
                                    f"KEINEN Foehn — {foehn_hit.group(0)!r} darf "
                                    f"hier nicht vorkommen, weder in `text` noch "
                                    f"in `flight_hint`. Boeigkeit ohne Foehn "
                                    f"benennen (z.B. 'boeiger Talwind', "
                                    f"'starker Hoehenwind') oder weglassen."))

        # --- Gewitter nur mit Modell-Gewitter im Ruecken. Die Skill-Regel
        # ("nur bei gewitter_share > 0") war bisher nirgends verankert —
        # hohe CAPE verleitet den LLM zur Gewitter-Prosa (DE-Lauf
        # 26.07.2026: "Schauer und Gewitter" bei CAPE 1360, share 0).
        gew_share = _zone_gewitter_share(ctx, zone_id, i)
        ens_gewitter = _zone_konvektion(ctx, zone_id, i, "gewitter")
        if gew_share == 0 and not ens_gewitter:
            gew_hit = (_GEWITTER_RE.search(text)
                       or _GEWITTER_RE.search(hint_str))
            if gew_hit:
                errors.append(_verr(scope, "gewitter_without_signal",
                                    f"Weder `gewitter_share` noch "
                                    f"`konvektion.gewitter` zeigen an dem Tag "
                                    f"in dieser Zone ein Signal — "
                                    f"{gew_hit.group(0)!r} ist damit nicht "
                                    f"gedeckt. Hohe CAPE allein heisst "
                                    f"'labile Luft' / 'Ueberentwicklung "
                                    f"moeglich', NICHT Gewitter."))

        # --- Wind-Konsistenz: jetzt PRO ZONE (frueher nur wenn BEIDE
        # Alpenseiten windkritisch waren — eine verblasene Zone neben einer
        # ruhigen rutschte damit durch).
        wind_class = _zone_wind_class(ctx, zone_id, i)
        if wind_class in _WINDY_CLASSES:
            praise = _PRAISE_RE.search(text) or _PRAISE_RE.search(hint_str)
            if praise:
                errors.append(_verr(scope, "wind_contradiction",
                                    f"Diese Zone ist an dem Tag laut "
                                    f"`wind_day.wind_class` '{wind_class}', wird "
                                    f"aber gelobt ('{praise.group(0)}'). Wortwahl "
                                    f"muss die Windlage widerspiegeln: 'vielerorts "
                                    f"zu windig' / 'nur windgeschuetzte Lagen'."))

        if not isinstance(hint, str) or len(hint.strip()) < 3:
            errors.append(_verr(scope, "schema",
                                "`flight_hint` fehlt — Pflichtfeld (EIN kurzer "
                                "Satz Pilotensicht, max ~15 Woerter)."))
        else:
            bad = _find_forbidden_term(hint)
            if bad:
                errors.append(_verr(scope, "forbidden_term",
                                    f"`flight_hint` enthaelt einen verbotenen "
                                    f"Begriff (Muster: {bad})."))

    return errors


# ============================================================================
# INTERNAL: Finalisierung (Praefixe, Neutralisierung, optionales Bereinigen)
# ============================================================================

def _finalize(parsed: dict, ctx: dict, attempts: int,
              unresolved: list, prune: bool = False) -> Optional[dict]:
    """Baut aus dem (validierten oder besten) LLM-Output das Cache-Format.

    prune=True (nur nach erschoepften Versuchen): verletzende Teile werden
    chirurgisch entfernt — verletzender lead faellt weg, verletzende
    days-Eintraege fallen einzeln weg, verletzende flight_hints werden
    gestrippt. Alles andere bleibt erhalten (Nie-leer-Garantie, soweit
    irgendetwas Valides existiert).

    Feldnamen im Rueckgabewert bleiben aus Kompatibilitaet zum Frontend
    (briefing.js) und zur Mail (email_service) short/long/long_with_sources.
    """
    import i18n
    lang = "en" if i18n.get_current_lang() == "en" else "de"

    fc_dates = ctx.get("forecast_dates") or []
    valid_centers = _collect_valid_center_labels(ctx)
    foehn = ctx.get("foehn") or {}

    lead = parsed.get("lead") if isinstance(parsed.get("lead"), str) else ""
    lead = lead.strip()
    zones_raw = parsed.get("zones") if isinstance(parsed.get("zones"), list) else []

    if prune and lead:
        if _find_forbidden_term(lead) or \
                _check_pressure_region_mentions(lead, valid_centers):
            logger.warning("Nicht behebbarer lead entfernt: '%s'", lead)
            lead = ""

    by_zone = {}
    for z in zones_raw:
        if not isinstance(z, dict):
            continue
        zone_id = z.get("zone")
        if zone_id not in config.SYNOPTIC_ZONES or zone_id in by_zone:
            continue
        days_raw = z.get("days") if isinstance(z.get("days"), list) else []
        entries = []
        for i, d in enumerate(days_raw):
            if not isinstance(d, dict):
                continue
            text = d.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            text = text.strip()

            # Wochentag-Praefix VOR dem Prune autoritativ setzen — Position i
            # gilt fuer forecast_dates[i], unabhaengig davon was spaeter faellt.
            text = _apply_weekday_prefix(text, fc_dates, i)

            active_side = _foehn_active_side(foehn, fc_dates, i)
            lee_zone = (active_side
                        and zone_id in _FOEHN_LEE_ZONES.get(active_side, ()))
            if prune:
                if _find_forbidden_term(text) or \
                        _check_pressure_region_mentions(text, valid_centers) or \
                        (lee_zone and _CALM_CLAIM_RE.search(text)) or \
                        (active_side and _text_inverts_foehn_lee(text, active_side)) or \
                        (not active_side and _FOEHN_MENTION_RE.search(text)):
                    logger.warning("Nicht behebbarer days-Eintrag entfernt "
                                   "(%s day %d): '%s'", zone_id, i + 1, text)
                    continue

            entry = {"text": _neutralize_calendar_week_text(text)}
            hint = d.get("flight_hint")
            if isinstance(hint, str) and len(hint.strip()) >= 3:
                hint = hint.strip()
                if prune and (_find_forbidden_term(hint)
                              or (lee_zone and _CALM_CLAIM_RE.search(hint))
                              or (active_side
                                  and _text_inverts_foehn_lee(hint, active_side))
                              or (not active_side
                                  and _FOEHN_MENTION_RE.search(hint))):
                    logger.warning("Nicht behebbarer flight_hint entfernt "
                                   "(%s day %d): '%s'", zone_id, i + 1, hint)
                else:
                    entry["flight_hint"] = _neutralize_calendar_week_text(hint)
            entries.append(entry)
        if entries:
            by_zone[zone_id] = entries

    # Kalenderwochen-Begriffe → zeitraum-neutral. Sicherheitsnetz zum
    # Skill-Verbot; der Cast ist ein rollierender Block ab heute.
    lead = _neutralize_calendar_week_text(lead)

    if not lead and not by_zone:
        logger.warning("generate_synoptic_overview: nach Bereinigung nichts "
                       "Valides uebrig — Block wird ausgelassen")
        return None

    # Ausgabe-Reihenfolge = config.SYNOPTIC_ZONES (nicht LLM-Reihenfolge)
    zones_out = [
        {"zone": z,
         "label": config.SYNOPTIC_ZONE_LABELS[z][lang],
         "days": by_zone[z]}
        for z in config.SYNOPTIC_ZONES if z in by_zone
    ]

    # Legacy-Felder: `short` (Mail-Lead) unveraendert; `long_with_sources`
    # bleibt fuer Konsumenten ohne Zonen-Support befuellt — mit der groessten
    # Zone (Alpennordhang, ~2/3 aller Spots) statt einer Flach-Verkettung
    # aller vier Zonen, die mit 4x denselben Wochentagen unlesbar waere.
    legacy_zone = next((z for z in config.SYNOPTIC_ZONES if z in by_zone), None)
    legacy_entries = by_zone.get(legacy_zone, []) if legacy_zone else []

    return {
        "short": lead,
        "long": " ".join(
            f"{zo['label']} — " + " ".join(e["text"] for e in zo["days"])
            for zo in zones_out
        ),
        "short_with_sources": [{"text": lead}] if lead else [],
        "long_with_sources": legacy_entries,
        "zones": zones_out,
        "attempts": attempts,
        "unresolved": [f"[{e['scope']}] {e['message']}" for e in unresolved],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


# ============================================================================
# INTERNAL: Admin-Alarm (Schicht 3)
# ============================================================================

def _notify_admin(errors: list, attempts: int, delivered: bool) -> None:
    """Alarmiert den Admin per Mail, wenn der Overview nach allen
    Korrektur-Runden nicht fehlerfrei wurde. Kein stilles Loeschen mehr —
    Ausfaelle muessen sichtbar sein."""
    try:
        import email_service
        status = ("bereinigte Bestversion ausgeliefert" if delivered
                  else "NICHTS ausgeliefert — Wetterlage-Block fehlt")
        lines = "\n".join(f"- [{e['scope']}] {e['message']}" for e in errors) or "-"
        subject = (f"[Wingcast] Wetterlage-Block nach {attempts} "
                   f"LLM-Versuchen nicht fehlerfrei")
        text = (
            f"Der Synoptik-Ueberblick konnte nach {attempts} Versuchen nicht "
            f"fehlerfrei erzeugt werden.\n\n"
            f"Status: {status}\n\n"
            f"Verbleibende Fehler:\n{lines}\n\n"
            f"Zeitpunkt: {datetime.now().isoformat(timespec='seconds')}\n"
        )
        html = "<pre>" + text.replace("<", "&lt;").replace(">", "&gt;") + "</pre>"
        email_service.send_email_async(config.ADMIN_EMAIL, subject, html, text)
        logger.warning("Admin-Alarm gesendet: %s (%s)", subject, status)
    except Exception as e:
        logger.error("Admin-Alarm fehlgeschlagen: %s", e)


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
            forecast_dates_labeled.append({"date": d, "weekday": _weekday_label(d)})
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
        "konvektion": ctx.get("konvektion"),
        "bise": _strip_provenance(ctx.get("bise")),
        "vb_lage": _strip_provenance(ctx.get("vb_lage")),
        "foehn": _strip_provenance(ctx.get("foehn")),
        "zones": _zones_for_llm(ctx),
        "zugbahn": _zugbahn_for_llm(ctx.get("zugbahn")),
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


def _zones_for_llm(ctx: dict) -> Optional[dict]:
    """Zonen-Payload: pro Zone die per-Tag-Reihe aus Niederschlag (Tag +
    Tagesfenster) und Wind (Klasse + Anteile + Fenster-Verlauf).

    Kompakt gehalten: pro Fenster nur wet_share/p90_mm/gewitter_share/
    max_cape (Regen) bzw. share_wind_crit (Wind) — das reicht dem LLM
    fuer Tagesverlaufs-Sprache, ohne den Prompt aufzublaehen.
    """
    pz = ctx.get("precip_zones")
    wz = ctx.get("wind_zones")
    if not pz or not wz:
        return None

    import i18n
    lang = "en" if i18n.get_current_lang() == "en" else "de"

    wind_by_date = {d["date"]: d.get("zones") or {} for d in wz.get("per_day") or []}

    zones_out = {}
    for zone in config.SYNOPTIC_ZONES:
        per_day = []
        for d in pz.get("per_day") or []:
            zp = (d.get("zones") or {}).get(zone) or {}
            day = zp.get("day") or {}
            wins = zp.get("windows") or {}
            zw = (wind_by_date.get(d.get("date")) or {}).get(zone) or {}
            per_day.append({
                "date": d.get("date"),
                "precip_day": {k: day.get(k) for k in (
                    "wet_share", "p90_mm", "max_mm", "gewitter_share",
                    "max_wc", "max_cape", "max_coverage")},
                "precip_windows": {
                    wname: {k: w.get(k) for k in
                            ("wet_share", "p90_mm", "gewitter_share", "max_cape")}
                    for wname, w in wins.items()
                },
                "wind_day": {k: zw.get(k) for k in (
                    "wind_class", "share_wind_crit", "share_wind_warn",
                    "wind_driver", "median_aloft_kmh", "max_aloft_kmh",
                    "aloft_over_kmh")},
                "wind_windows": {
                    wname: w for wname, w in (zw.get("windows") or {}).items()
                },
            })
        zones_out[zone] = {
            "label": config.SYNOPTIC_ZONE_LABELS[zone][lang],
            "n_spots": (pz.get("n_spots_by_zone") or {}).get(zone),
            "per_day": per_day,
        }

    return {
        "windows_hours": {w["key"]: w["hours"] for w in pz.get("windows") or []},
        "by_zone": zones_out,
        "thresholds": {**(pz.get("thresholds") or {}),
                       **(wz.get("thresholds") or {})},
    }


def _zugbahn_for_llm(zb: Optional[dict]) -> Optional[dict]:
    """Zugbahn-Payload: Einsetz-Zeiten + Richtungs-Label pro Tag, ohne
    Provenance. Nur Tage mit mindestens einem Onset werden mitgegeben."""
    if not zb:
        return None
    per_day = []
    for d in zb.get("per_day") or []:
        onsets = d.get("onset_hour_by_group") or {}
        if not any(v is not None for v in onsets.values()):
            continue
        per_day.append({
            "date": d.get("date"),
            "onset_hour_by_group": onsets,
            "movement": d.get("movement"),
        })
    if not per_day:
        return None
    return {"per_day": per_day}


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
# INTERNAL: Pruef-Helfer (Regionen, Wochentage, Kalenderwoche, Foehn-Lee)
# ============================================================================

def _collect_valid_center_labels(ctx: dict) -> set:
    """Sammelt alle Region-Labels, die im Strukturfeld detektiert wurden.
    Saetze, die andere (erfundene) Regionen nennen, sind Fehler.
    """
    labels = set()
    for d in ctx.get("pressure_centers_per_day") or []:
        for c in d.get("centers") or []:
            labels.add(c.get("region_label"))
    return labels


def _allowed_centers(valid_centers: set) -> str:
    """Erlaubte Druckzentren-Labels als Liste fuer die Korrektur-Nachricht.

    Blosses Verbieten reicht dem LLM nicht — es erfindet sonst in der
    Korrektur-Runde die naechste Region (25.07.2026: "Adria"). Mit der
    Positivliste hat es eine Alternative zur Hand.
    """
    labels = sorted(str(c) for c in valid_centers if c)
    return str(labels) if labels else "(keine — dann gar keine Region nennen)"


# Praefix-Regex: "Heute:", "Morgen:", "Uebermorgen:", "Tag 1:" oder Wochentag
# (DE + EN, optional mit Klammer-Zusatz wie "Sonntag (Sunday):" — der LLM
# haengt im EN-Modus gerne die Uebersetzung an; ohne Klammer-Support wurde
# daraus "Sonntag: Sonntag (Sunday): ..." mit Doppel-Praefix, 05.07.2026).
_WEEKDAY_SET = {w.lower() for w in _WOCHENTAGE}
_PREFIX_RE = re.compile(
    r"^(Heute|Morgen|Uebermorgen|Übermorgen|Tag\s*\d+|Today|Tomorrow|Day\s*\d+|"
    r"Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag|"
    r"Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
    r"\s*(?:\([^)]{0,30}\))?\s*:\s*",
    re.IGNORECASE,
)


def _apply_weekday_prefix(text: str, forecast_dates: list, i: int) -> str:
    """Setzt das Wochentag-Praefix eines days-Eintrags autoritativ auf den
    korrekten Wochentag aus `forecast_dates[i]`. Der briefing.js-Renderer
    matcht nur `^(Montag|...|Sonntag):` — Eintraege mit "Heute:"/"Morgen:"
    oder verschobenen Wochentagen wuerden sonst als unbeschriftete
    Lead-Absaetze gerendert.

    Positions-Vertrag: days[i] gehoert zu forecast_dates[i] (Skill).
    Wir setzen das Praefix anhand der Position, unabhaengig davon, was
    der LLM gewaehlt hat.
    """
    if i >= len(forecast_dates):
        return text
    try:
        correct_wd = _weekday_label(forecast_dates[i])
    except Exception:
        return text
    # ALLE fuehrenden Praefix-Varianten abraeumen (auch gestapelte wie
    # "Sonntag: Sonntag (Sunday):"), dann kanonisch neu setzen.
    stripped = text
    for _ in range(3):
        m = _PREFIX_RE.match(stripped)
        if not m:
            break
        stripped = stripped[m.end():].lstrip()
    new_text = f"{correct_wd}: {stripped}"
    if new_text != text:
        logger.info("Wetterlage-Praefix normalisiert (day %d) -> '%s'",
                    i + 1, correct_wd)
    return new_text


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


def _neutralize_calendar_week_text(text: str) -> str:
    """Ersetzt Kalenderwochen-Begriffe in einem Text durch zeitraum-neutrale
    Formulierungen. Belt-and-suspenders zum Skill-Verbot.
    """
    if not text:
        return text
    new_text = text
    for pat, repl in _CALENDAR_WEEK_SUBS:
        new_text = pat.sub(repl, new_text)
    if new_text != text:
        logger.info("Kalenderwochen-Begriff neutralisiert: %r -> %r", text, new_text)
    return new_text


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


# Bekannte Region-Labels aus config.EUROPE_PRESSURE_GRID — gegen diese
# pruefen wir, ob der LLM eine Region nennt, die NICHT detektiert wurde.
_KNOWN_GRID_LABELS = {p["label"] for p in config.EUROPE_PRESSURE_GRID}


def _check_pressure_region_mentions(text: str, valid_centers: set) -> list:
    """Findet Region-Labels im Text, die im Grid existieren aber NICHT
    fuer den aktuellen Cast detektiert wurden.

    Anders als frueher wird IMMER geprueft (nicht nur bei Source-Tag
    pressure_centers_per_day) — der Skill verbietet nicht detektierte
    Regionen generell.

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
