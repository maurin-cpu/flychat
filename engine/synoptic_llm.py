"""LLM-Caller + Validierungs-/Korrektur-Loop fuer den Wetterlage-Block.

Nimmt das deterministisch erzeugte Strukturfeld aus synoptic_context.build_*
und laesst den LLM daraus eine Prosa-Version generieren (lead + days).

Architektur (ersetzt den alten Loesch-Post-Filter):
  1. LLM bekommt nur das fertige Strukturfeld, keine Rohzahlen.
  2. Output-Format ist flach: {"lead": str, "days": [{text, flight_hint}]}
     — Zuordnung days[i] <-> forecast_dates[i] per POSITION. Die alte
     Source-Tag-Pflicht ist abgeschafft: sie hat nur Formfehler produziert
     (invalid_source loeschte am 05.07.2026 den halben Ueberblick) und
     keine echte Halluzinations-Sicherheit gebracht.
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
from engine._common import _weekday_de, _WOCHENTAGE

logger = logging.getLogger(__name__)

# Max. LLM-Versuche pro Overview (1 Erstversuch + 2 Korrektur-Runden).
_MAX_ATTEMPTS = 3


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
        {"short": str, "long": str, "long_with_sources": [{text, flight_hint}],
         "attempts": int, "unresolved": [str], "generated_at": str}
        — Feldnamen short/long/long_with_sources bleiben aus Kompatibilitaet
        zu briefing.js / email_service erhalten (lead -> short, days -> long).
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

def _call_llm(analysis_client, analysis_model: str,
              messages: list) -> Optional[str]:
    """Ein LLM-Versuch. Liefert den rohen Antwort-String oder None."""
    try:
        response = analysis_client.chat.completions.create(
            model=analysis_model,
            messages=messages,
            temperature=0.4,
            # v4-flash laeuft im Thinking-Mode — Reasoning-Tokens VOR der
            # Antwort. Plus 5-Tage-Output (lead + days mit flight_hint)
            # sprengt 4000. Bei Truncation kommt finish_reason=length
            # und das JSON ist mittendrin abgeschnitten.
            max_tokens=12000,
            response_format={"type": "json_object"},
        )
        finish = getattr(response.choices[0], "finish_reason", None)
        raw = response.choices[0].message.content
        if not raw:
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
        '{"lead": "...", "days": [{"text": "...", "flight_hint": "..."}]}) '
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


def _validate(parsed: dict, ctx: dict) -> list:
    """Prueft den LLM-Output inhaltlich und strukturell.

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
                            "(Fliesstext-String, 5-7 Saetze, max 150 Woerter)."))
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
                                f"{invalid_regions}. Nur die gelieferten "
                                f"region_label verwenden."))
        n_words = len(lead.split())
        if n_words > 170:
            errors.append(_verr("lead", "too_long",
                                f"`lead` hat {n_words} Woerter — erlaubt sind "
                                f"max 150. Kuerzen."))

    # --- days: Schema + Vollstaendigkeit ---------------------------------
    days = parsed.get("days")
    if not isinstance(days, list):
        errors.append(_verr("days", "schema",
                            "`days` fehlt oder ist keine Liste — Pflichtfeld "
                            "(ein Eintrag pro forecast_date, gleiche Reihenfolge)."))
        return errors
    if fc_dates and len(days) != len(fc_dates):
        errors.append(_verr("days", "schema",
                            f"`days` hat {len(days)} Eintraege, erwartet "
                            f"{len(fc_dates)} — exakt einer pro Tag in "
                            f"forecast_dates-Reihenfolge, keiner fehlt, "
                            f"keiner doppelt."))

    # --- days: Inhalt pro Eintrag ----------------------------------------
    for i, d in enumerate(days):
        scope = f"days[{i}]"
        if not isinstance(d, dict) or not isinstance(d.get("text"), str) \
                or not d["text"].strip():
            errors.append(_verr(scope, "schema",
                                "Eintrag braucht ein nicht-leeres `text`-Feld."))
            continue
        text = d["text"]

        bad = _find_forbidden_term(text)
        if bad:
            errors.append(_verr(scope, "forbidden_term",
                                f"`text` enthaelt einen verbotenen Begriff "
                                f"(Muster: {bad})."))

        invalid_regions = _check_pressure_region_mentions(text, valid_centers)
        if invalid_regions:
            errors.append(_verr(scope, "invalid_region",
                                f"`text` nennt nicht detektierte Regionen: "
                                f"{invalid_regions}."))

        active_side = _foehn_active_side(foehn, fc_dates, i)
        if active_side and _text_inverts_foehn_lee(text, active_side):
            lee = "Alpensuedseite" if active_side == "nord" else "Alpennordseite"
            errors.append(_verr(scope, "foehn_lee_inversion",
                                f"An diesem Tag ist {active_side.capitalize()}foehn "
                                f"aktiv — die {lee} ist die boeige LEE-Seite und "
                                f"darf NICHT als geschuetzt/ruhig beschrieben "
                                f"werden."))

        hint = d.get("flight_hint")
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
            if active_side and _text_inverts_foehn_lee(hint, active_side):
                errors.append(_verr(scope, "foehn_lee_inversion",
                                    f"`flight_hint` beschreibt die Foehn-Lee-"
                                    f"Seite als geschuetzt/ruhig, obwohl "
                                    f"{active_side.capitalize()}foehn aktiv ist."))

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
    fc_dates = ctx.get("forecast_dates") or []
    valid_centers = _collect_valid_center_labels(ctx)
    foehn = ctx.get("foehn") or {}

    lead = parsed.get("lead") if isinstance(parsed.get("lead"), str) else ""
    lead = lead.strip()
    days_raw = parsed.get("days") if isinstance(parsed.get("days"), list) else []

    if prune and lead:
        if _find_forbidden_term(lead) or \
                _check_pressure_region_mentions(lead, valid_centers):
            logger.warning("Nicht behebbarer lead entfernt: '%s'", lead)
            lead = ""

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
        if prune:
            if _find_forbidden_term(text) or \
                    _check_pressure_region_mentions(text, valid_centers) or \
                    (active_side and _text_inverts_foehn_lee(text, active_side)):
                logger.warning("Nicht behebbarer days-Eintrag entfernt "
                               "(day %d): '%s'", i + 1, text)
                continue

        entry = {"text": text}
        hint = d.get("flight_hint")
        if isinstance(hint, str) and len(hint.strip()) >= 3:
            hint = hint.strip()
            if prune and (_find_forbidden_term(hint) or
                          (active_side and
                           _text_inverts_foehn_lee(hint, active_side))):
                logger.warning("Nicht behebbarer flight_hint entfernt "
                               "(day %d): '%s'", i + 1, hint)
            else:
                entry["flight_hint"] = hint
        entries.append(entry)

    # Kalenderwochen-Begriffe → zeitraum-neutral. Sicherheitsnetz zum
    # Skill-Verbot; der Cast ist ein rollierender Block ab heute.
    lead = _neutralize_calendar_week_text(lead)
    for e in entries:
        e["text"] = _neutralize_calendar_week_text(e["text"])
        if "flight_hint" in e:
            e["flight_hint"] = _neutralize_calendar_week_text(e["flight_hint"])

    if not lead and not entries:
        logger.warning("generate_synoptic_overview: nach Bereinigung nichts "
                       "Valides uebrig — Block wird ausgelassen")
        return None

    return {
        "short": lead,
        "long": " ".join(e["text"] for e in entries),
        "short_with_sources": [{"text": lead}] if lead else [],
        "long_with_sources": entries,
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
                     "gewitter_share": d["alpennord"].get("gewitter_share"),
                     "max_wc": d["alpennord"].get("max_wc"),
                     "max_cape": d["alpennord"].get("max_cape"),
                     "max_coverage": d["alpennord"].get("max_coverage"),
                     "n_spots": d["alpennord"].get("n_spots"),
                 },
                 "alpensued": {
                     "peak_mm": d["alpensued"].get("peak_mm"),
                     "wet_share": d["alpensued"].get("wet_share"),
                     "gewitter_share": d["alpensued"].get("gewitter_share"),
                     "max_wc": d["alpensued"].get("max_wc"),
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


# Praefix-Regex: "Heute:", "Morgen:", "Uebermorgen:", "Tag 1:" oder Wochentag.
_WEEKDAY_SET = {w.lower() for w in _WOCHENTAGE}
_PREFIX_RE = re.compile(
    r"^(Heute|Morgen|Uebermorgen|Übermorgen|Tag\s*\d+|"
    r"Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)\s*:\s*",
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
        correct_wd = _weekday_de(forecast_dates[i])
    except Exception:
        return text
    m = _PREFIX_RE.match(text)
    if m:
        existing = m.group(1).strip()
        if existing.lower() == correct_wd.lower():
            return text
        logger.info("Wetterlage-Praefix korrigiert (day %d): '%s' -> '%s'",
                    i + 1, existing, correct_wd)
        return f"{correct_wd}: {text[m.end():].lstrip()}"
    logger.info("Wetterlage-Praefix ergaenzt (day %d, kein Praefix): '%s'",
                i + 1, correct_wd)
    return f"{correct_wd}: {text.lstrip()}"


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
