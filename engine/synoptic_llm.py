"""LLM-Caller + Validierungs-/Korrektur-Loop fuer den Wetterlage-Block.

Nimmt das deterministisch erzeugte Strukturfeld aus synoptic_context.build_*
und laesst den LLM daraus die Texte fuers Briefing generieren (lead,
hazards, day_lines). Die frueheren Zonen-Texte sind seit 04.10.2026 weg —
sie erschienen nur auf der Synoptik-Seite, die jetzt nur noch die Karte zeigt.

Architektur (ersetzt den alten Loesch-Post-Filter):
  1. LLM bekommt nur das fertige Strukturfeld, keine Rohzahlen.
  2. Output-Format:
     {"lead": str,
      "hazards": [{"items": [{topic, text}]}, ...],   # je Tag, Themen vom Code
      "day_lines": [str, ...]}                        # je Tag ein Satz
     — Zuordnung hazards[i]/day_lines[i] <-> forecast_dates[i] per POSITION.
  3. _validate() prueft INHALTLICH (Verbotsbegriffe, erfundene Regionen,
     Foehn-Lee-Inversion, Foehn-Talwerte, Schema) — und loescht NICHTS.
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
from engine._common import (_weekday_de, deepseek_thinking_kwargs,
                            parse_llm_json)

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

# Fronten-Vokabular: verboten, solange das Strukturfeld keine DWD-Durchgaenge
# liefert (`fronten.durchgaenge` leer/fehlend). Mit Durchgaengen ist es
# erlaubt — die KI hat dann Daten, keine Vermutung.
_FRONT_PATTERNS = [
    re.compile(r"\bkaltfront\b", re.IGNORECASE),
    re.compile(r"\bwarmfront\b", re.IGNORECASE),
    re.compile(r"\bokklusion\b", re.IGNORECASE),
    re.compile(r"\bfrontdurchgang\b", re.IGNORECASE),
    re.compile(r"\bpraefrontal\b", re.IGNORECASE),
    re.compile(r"\bpostfrontal\b", re.IGNORECASE),
]
_FORBIDDEN_PATTERNS = _FRONT_PATTERNS + [
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

# Foehn am Talboden (Briefing, docs/FOEHN.md): Die Foehn-Talpunkte bestaetigen
# die Foehnlage oder nicht (foehn.per_day[].tal). Unbestaetigt muss der Text
# sagen, dass der Foehn in der Hoehe bleibt — und darf ihn nicht in die Taeler
# legen. km/h-Zahlen zum Foehn nur aus den Talwerten (eine Zahl, eine Quelle).
_FOEHN_ALOFT_RE = re.compile(
    r"(in der h(?:oe|ö)he|bleibt oben|greift nicht (?:bis )?(?:in die t|durch)|"
    r"nicht bis (?:in die t|zum boden|auf den talboden)|aloft|"
    r"stays? (?:up )?(?:high|above)|above the valleys|without reaching|"
    r"(?:does|do) not reach (?:the |down to the )?(?:valley|ground)|"
    r"not reach(?:ing)? (?:the |down to the )?(?:valley|ground))", re.IGNORECASE)
_FOEHN_VALLEY_CLAIM_RE = re.compile(
    r"(gusty in the (?:foehn |lee )?valleys|in the (?:foehn |lee )?valleys|"
    r"(?:reaches|reaching|breaks? through to) the (?:valley|ground)|valley floors?|"
    r"in den (?:f(?:oe|ö)hn|lee)?-?t(?:ae|ä)lern|bis in die t(?:ae|ä)ler|"
    r"am (?:tal)?boden)", re.IGNORECASE)
_KMH_RE = re.compile(r"(\d+)\s*(?:[–-]\s*(\d+)\s*)?km/h", re.IGNORECASE)


def _kmh_numbers(text: str) -> list:
    out = []
    for m in _KMH_RE.finditer(text or ""):
        out.append(int(m.group(1)))
        if m.group(2):
            out.append(int(m.group(2)))
    return out


def _fold(text: str) -> str:
    return (text or "").lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")


def _tal_stem(name: str) -> str:
    """Erkennungsmerkmal eines Talnamens: die ersten 5 Buchstaben des laengsten
    Worts ('St. Galler Rheintal' -> 'rhein', 'Reusstal' -> 'reuss')."""
    words = [w for w in re.split(r"[\s/–-]+", _fold(name)) if w]
    return max(words, key=len)[:5] if words else ""


def _tal_allowed_kmh(tal: dict) -> set:
    if not tal or not tal.get("n_bestaetigt"):
        return set()
    out = {tal.get("wind_min_kmh"), tal.get("wind_max_kmh"), tal.get("gust_max_kmh")}
    for t in tal.get("taeler") or []:
        if t.get("bestaetigt"):
            out |= {t.get("wind_min_kmh"), t.get("wind_max_kmh"), t.get("gust_max_kmh")}
    return {x for x in out if isinstance(x, int)}


def _foehn_tal_problems(text: str, tal: dict, *, require_name: bool,
                        require_aloft: bool, only_foehn_sentences: bool) -> list:
    """[(kind, message)] — Talbezug eines Foehn-Texts gegen foehn.per_day[].tal."""
    from foehn_talpunkte import tal_namen
    if not isinstance(text, str) or not tal:
        return []
    probs = []
    scope = text
    if only_foehn_sentences:
        scope = " ".join(x for x in re.split(r"(?<=[.!?;])\s+", text)
                         if _FOEHN_MENTION_RE.search(x))
    allowed = _tal_allowed_kmh(tal)
    bad = sorted({n for n in _kmh_numbers(scope) if n not in allowed})
    if bad:
        probs.append(("foehn_number_mismatch",
                      f"km/h-Zahl(en) {bad} zum Foehn stimmen nicht mit den Talwerten "
                      f"ueberein. Erlaubt: "
                      f"{sorted(allowed) if allowed else 'KEINE Zahl (Foehn am Talboden nicht bestaetigt)'} "
                      f"— genau diese Werte aus `tal_wind_kmh`/`tal_gust_max_kmh`, sonst keine."))
    names = tal_namen(tal)
    folded = _fold(scope)
    if names:
        if require_name and not any(_tal_stem(n) and _tal_stem(n) in folded for n in names):
            probs.append(("foehn_tal_missing",
                          f"Der Foehn ist am Talboden bestaetigt in {names}. Der Satz MUSS "
                          f"mindestens eines dieser Taeler nennen (Name wie geliefert)."))
    else:
        claim = _FOEHN_VALLEY_CLAIM_RE.search(scope)
        if claim and not _FOEHN_ALOFT_RE.search(scope):
            probs.append(("foehn_tal_overclaim",
                          f"{claim.group(0)!r} legt den Foehn in die Taeler — an keinem der "
                          f"{tal.get('n_total', 0)} Foehn-Talpunkte zeigt das Modell Foehnwind. "
                          f"Das ist falsch."))
        if require_aloft and not _FOEHN_ALOFT_RE.search(scope):
            probs.append(("foehn_tal_unconfirmed",
                          "Kein Foehn-Talpunkt zeigt Foehnwind — der Satz MUSS sagen, dass der "
                          "Foehn laut Modell in der Hoehe bleibt und nicht in die Taeler "
                          "durchgreift (z.B. 'stays aloft and does not reach the valleys'); "
                          "nie 'ruhig/geschuetzt'."))
    return probs


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


def refresh_synoptic_overview_lang(sctx: dict, analysis_client,
                                   analysis_model: str, lang: str) -> Optional[dict]:
    """Zweite Sprachfassung des Wetterlage-Blocks fuer das oeffentliche Briefing.

    Nimmt das fertige Strukturfeld des Hauptlaufs (deterministisch und
    sprachneutral), erzeugt nur den LLM-Teil neu in `lang` — mit demselben
    Validator und Korrektur-Loop — und schreibt synoptic_context.<lang>.json.
    Thread-lokal (i18n.lang_override): Web-Requests und Mails bleiben in LANG.
    Fuer die Server-Sprache gibt es nichts zu tun, dann kommt sctx zurueck.
    """
    import copy
    import i18n
    from engine import synoptic_context as sc

    if lang == i18n.get_server_lang():
        return sctx
    out = copy.deepcopy(sctx)
    with i18n.lang_override(lang):
        overview = generate_synoptic_overview(out, analysis_client, analysis_model)
    out["llm_overview"] = overview   # None, wenn der Validator nichts durchliess
    out["lang"] = lang
    try:
        sc._write_synoptic_cache(out, lang=lang)
    except Exception as e:
        logger.warning("synoptic cache (%s) schreiben fehlgeschlagen: %s", lang, e)
    return out


def generate_synoptic_overview(synoptic_context: dict, analysis_client,
                               analysis_model: str) -> Optional[dict]:
    """Generiert den Wetterlage-Block mit Validierungs-/Korrektur-Loop.

    Ablauf: LLM-Call → _validate() → bei Fehlern Korrektur-Nachricht mit
    konkreter Fehlerliste anhaengen und neu generieren (max _MAX_ATTEMPTS).
    Nach erschoepften Versuchen wird die beste Version chirurgisch bereinigt
    ausgeliefert (nie leer, solange irgendetwas Valides da ist) und der
    Admin per Mail alarmiert.

    Returns:
        {"short": str,                      # lead (Mail + Briefing)
         "hazards": [...], "day_lines": [...],
         "attempts": int, "unresolved": [str], "generated_at": str}
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
            parsed = parse_llm_json(raw)
        except ValueError as e:
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
    # Die Fehlertexte sind deutsch — ohne ausdrueckliche Vorgabe antwortet der
    # LLM im EN-Modus nach ein, zwei Runden deutsch (Vorfall 16.09.2026).
    import i18n
    language = ("OUTPUT LANGUAGE: ENGLISH. The error notes below are in German, "
                "but write EVERY text field (lead, hazards, day_lines) in "
                "English, exactly as the system prompt requires.\n\n"
                if i18n.get_current_lang() == "en" else
                "AUSGABESPRACHE: DEUTSCH. Schreibe alle Textfelder auf Deutsch.\n\n")
    return (
        "KORREKTUR NOETIG / CORRECTION REQUIRED\n\n"
        f"{language}"
        "Deine letzte Antwort hatte folgende Fehler:\n"
        f"{lines}\n\n"
        "Erzeuge das KOMPLETTE JSON neu (gleiches Format: "
        '{"lead": "...", '
        '"hazards": [{"items": [{"topic": "<THEMA>", "text": "..."}]}], '
        '"day_lines": ["...", "..."]}) '
        "und behebe ALLE genannten Punkte. Alle uebrigen Regeln aus dem "
        "System-Prompt gelten unveraendert. Nur das JSON, kein Kommentar."
    )


# ============================================================================
# INTERNAL: Validierung (prueft, loescht NICHTS)
# ============================================================================

def _verr(scope: str, kind: str, message: str) -> dict:
    return {"scope": scope, "kind": kind, "message": message}


def _fronts_ok(ctx: dict) -> bool:
    """True, wenn das Strukturfeld DWD-Frontdurchgaenge traegt — dann darf
    die KI Fronten nennen."""
    return bool(((ctx or {}).get("fronten") or {}).get("durchgaenge"))


def _find_forbidden_term(text: str, fronts_ok: bool = False) -> Optional[str]:
    """Findet das erste Verbots-Pattern in einem Text. Liefert das
    Pattern als Debug-String oder None. fronts_ok=True laesst das
    Fronten-Vokabular durch (Strukturfeld hat DWD-Durchgaenge)."""
    if not isinstance(text, str):
        return "non_string"
    for pattern in _FORBIDDEN_PATTERNS:
        if fronts_ok and pattern in _FRONT_PATTERNS:
            continue
        if pattern.search(text):
            return pattern.pattern
    return None


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


# Gewitter-Wortfeld. Gewitter-Signale sind gewitter_share (weather_code
# 95/96/99) ODER konvektion.gewitter (Ensemble + Anker, seit 03.08.2026) —
# hohe CAPE allein heisst weiterhin nur "labile Luft".
_GEWITTER_RE = re.compile(r"(gewitter|thunderstorm|thunder\b)", re.IGNORECASE)


# Zone(n), die bei aktivem Foehn die boeige LEE-Seite sind (Gefahren-Schalter
# FOEHN: betroffene Zonen).
_FOEHN_LEE_ZONES = {
    "nord": ("tessin",),                      # Nordfoehn -> Tessin ist Lee
    "sued": ("alpennordhang", "wallis"),      # Suedfoehn -> Nordseite/Foehntaeler
}

def _validate(parsed: dict, ctx: dict) -> list:
    """Prueft den LLM-Output inhaltlich und strukturell.

    Erwartetes Format: {"lead": str, "hazards": [...], "day_lines": [...]}

    Liefert eine Fehlerliste [{scope, kind, message}] — leere Liste = OK.
    Loescht bewusst NICHTS: die Reaktion (Korrektur-Runde / chirurgisches
    Bereinigen / Alarm) entscheidet der Aufrufer.
    """
    errors = []
    valid_centers = _collect_valid_center_labels(ctx)

    # --- lead -----------------------------------------------------------
    lead = parsed.get("lead")
    if not isinstance(lead, str) or not lead.strip():
        errors.append(_verr("lead", "schema",
                            "`lead` fehlt oder ist leer — Pflichtfeld "
                            "(Fliesstext-String, 4-6 Saetze, max 130 Woerter)."))
    else:
        bad = _find_forbidden_term(lead, _fronts_ok(ctx))
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
        # Foehn-Talwerte: Zahlen nur aus den Talpunkten; ohne bestaetigtes Tal
        # keinen Foehn "in den Taelern" (lead gilt fuer alle Tage zusammen)
        tals = [c["checks"]["FOEHN"]["facts"].get("tal") for c in hazard_checks(ctx)
                if c["checks"]["FOEHN"]["active"]]
        tals = [t for t in tals if t]
        if tals:
            merged = {"n_total": max(t.get("n_total", 0) for t in tals),
                      "n_bestaetigt": sum(t.get("n_bestaetigt", 0) for t in tals),
                      "taeler": [x for t in tals for x in (t.get("taeler") or [])]}
            for t in tals:
                if t.get("n_bestaetigt"):
                    merged.update({k: t[k] for k in ("wind_min_kmh", "wind_max_kmh", "gust_max_kmh")})
            for kind, msg in _foehn_tal_problems(lead, merged, require_name=False,
                                                 require_aloft=False, only_foehn_sentences=True):
                errors.append(_verr("lead", kind, msg))
        n_words = len(lead.split())
        if n_words > 150:
            errors.append(_verr("lead", "too_long",
                                f"`lead` hat {n_words} Woerter — erlaubt sind "
                                f"max 130. Kuerzen."))

    # --- hazards + day_lines --------------------------------------------
    errors.extend(_validate_hazards(parsed, ctx))
    errors.extend(_validate_day_lines(parsed, ctx))
    errors.extend(_language_errors(parsed))
    return errors


# ============================================================================
# INTERNAL: Finalisierung (Praefixe, Neutralisierung, optionales Bereinigen)
# ============================================================================

def _finalize(parsed: dict, ctx: dict, attempts: int,
              unresolved: list, prune: bool = False) -> Optional[dict]:
    """Baut aus dem (validierten oder besten) LLM-Output das Cache-Format.

    prune=True (nur nach erschoepften Versuchen): verletzende Teile werden
    chirurgisch entfernt — ein verletzender lead faellt weg, verletzende
    Gefahren-Saetze/Tagessaetze einzeln. Alles andere bleibt erhalten.
    `short` heisst aus Kompatibilitaet so (Mail, Briefing).
    """
    valid_centers = _collect_valid_center_labels(ctx)
    lead = parsed.get("lead") if isinstance(parsed.get("lead"), str) else ""
    lead = lead.strip()
    if prune and lead:
        if _find_forbidden_term(lead, _fronts_ok(ctx)) or \
                _check_pressure_region_mentions(lead, valid_centers):
            logger.warning("Nicht behebbarer lead entfernt: '%s'", lead)
            lead = ""

    # Kalenderwochen-Begriffe → zeitraum-neutral. Sicherheitsnetz zum
    # Skill-Verbot; der Cast ist ein rollierender Block ab heute.
    lead = _neutralize_calendar_week_text(lead)
    hazards = _finalize_hazards(parsed, ctx, prune)
    day_lines = _finalize_day_lines(parsed, ctx, prune)
    # Wortlaut-Waechter: Urteile ("No foehn", "safe") -> Datenbezug. Gleicher
    # Waechter wie bei den Analysen (engine/wording_guard.py).
    from engine.wording_guard import soften_clearance, soften_result
    lead = soften_clearance(lead, label="Wetterlage")
    hazards = soften_result(hazards, label="Wetterlage")
    day_lines = soften_result(day_lines, label="Wetterlage")

    if not lead and not any(h.get("items") for h in hazards) \
            and not any(d.get("text") for d in day_lines):
        logger.warning("generate_synoptic_overview: nach Bereinigung nichts "
                       "Valides uebrig — Block wird ausgelassen")
        return None

    return {
        "short": lead,
        # Gefahren schweizweit (Briefing-Warnungen)
        "hazards": hazards,
        # ein kurzer Satz je Tag fuer die Tages-Sektion des Briefings
        "day_lines": day_lines,
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
        + "  - Verbote aus dem Skill (Trog/hPa-Werte) gelten weiterhin — auch\n"
        + "    wenn die Wissensbasis diese Begriffe erklaert. Fronten nur aus\n"
        + "    `fronten.durchgaenge`, nie aus der Wissensbasis.\n\n"
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
        "foehn": _foehn_for_llm(ctx.get("foehn")),
        "zones": _zones_for_llm(ctx),
        # vom Code geschaltete Gefahren je Tag — nur diese darf `hazards` nennen
        "hazards_per_day": _hazards_for_llm(hazard_checks(ctx)),
        "zugbahn": _zugbahn_for_llm(ctx.get("zugbahn")),
        # DWD-Frontdurchgaenge je Zone — die einzige Quelle fuer Fronten-Saetze
        "fronten": _strip_provenance(ctx.get("fronten")),
        # Frontdurchgang in den eigenen Prognosedaten je Zone/Tag (Belege)
        "frontsignatur": _strip_provenance(ctx.get("frontsignatur")),
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


def _foehn_for_llm(field: Optional[dict]) -> Optional[dict]:
    """Foehn-Block ohne die Talpunkt-Details: die Talwerte bekommt der LLM einmal,
    kompakt in `hazards_per_day` (eine Zahl, eine Quelle)."""
    out = _strip_provenance(field)
    if out and isinstance(out.get("per_day"), list):
        out["per_day"] = [{k: v for k, v in d.items() if k != "tal"}
                          if isinstance(d, dict) else d for d in out["per_day"]]
    return out


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


# ============================================================================
# GEFAHREN SCHWEIZWEIT (hazards) — Code schaltet, LLM beschreibt den Ort
# ============================================================================
# Die Briefing-Warnungen beginnen mit einer Gesamteinschaetzung fuer die
# Schweiz (Regen? Foehn? ...). OB eine Gefahr an einem Tag aktiv ist,
# entscheidet allein hazard_checks() aus dem Strukturfeld; der LLM liefert je
# aktivem Thema 1-2 Saetze, WO in der Schweiz und woher/wohin. Ein Thema, das
# der Code nicht schaltet, ist eine erfundene Gefahr und wird abgelehnt.

HAZARD_TOPICS = ("RAIN", "THUNDER", "FOEHN", "BISE", "WIND")

# Laengen der Briefing-Saetze (Wunsch User 16.09.2026: "kurz, auf den Punkt").
# Harte Grenzen im Validator — "halte dich kurz" allein befolgt der LLM nicht.
HAZARD_MAX_WORDS = 25
DAY_LINE_MAX_WORDS = 35

# Urteil ueber das Fliegen — gehoert dem Piloten, nie dem Satz
# (User 16.09.2026: "er soll nie sagen kein nutzbares Fenster").
_VERDICT_RE = re.compile(
    rf"(\b(?:nicht\s+|un)?fliegbar\w*|\b(?:un)?flyable\b|nutzbare?[sn]?\s+(?:flug)?fenster|"
    rf"usable\s+window|\btop-?tag\b|\btop\s+day\b|\bperfekt\w*|\bperfect\b|\bideal\w*|"
    rf"unm(?:oe|{_O_UMLAUT})glich|\bimpossible\b|empfehl\w*|\brecommend\w*|"
    rf"\bnicht\s+fliegen\b|\bdon'?t\s+fly\b|\bno\s+flying\b|\bflying\s+is\s+off\b)",
    re.IGNORECASE)
# Satzende = Punkt/Ausrufe-/Fragezeichen, dann Leerzeichen und Grossbuchstabe
_SENTENCE_BREAK_RE = re.compile(r"[.!?](?=\s+[A-Z\u00c4\u00d6\u00dc])")


# Deutscher Text im EN-Modus. Umlaute sind ein sicheres Zeichen (die englischen
# Zonennamen haben keine); dazu Funktionswoerter, die im Englischen nicht
# vorkommen — erst ab zwei verschiedenen, damit ein einzelnes "die" nicht zaehlt.
_DE_CHARS_RE = re.compile("[\u00e4\u00f6\u00fc\u00df\u00c4\u00d6\u00dc]")
_DE_WORDS_RE = re.compile(r"\b(und|der|die|das|ein|eine|einer|einem|einen|mit|im|ab|bei|wird|nicht|sich|auf|ueber|zum|zur|vom|am|es)\b",
                          re.IGNORECASE)


def _looks_german(text: str) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    if _DE_CHARS_RE.search(text):
        return True
    return len({m.group(1).lower() for m in _DE_WORDS_RE.finditer(text)}) >= 2


def _language_errors(parsed: dict) -> list:
    """Im EN-Modus: jedes Textfeld, das deutsch aussieht, als `wrong_language`."""
    import i18n
    if i18n.get_current_lang() != "en":
        return []
    found = []
    if _looks_german(parsed.get("lead")):
        found.append("lead")
    for i, h in enumerate(parsed.get("hazards") or []):
        for item in (h.get("items") or []) if isinstance(h, dict) else []:
            if isinstance(item, dict) and _looks_german(item.get("text")):
                found.append(f"hazards[{i}].{item.get('topic')}")
    for i, line in enumerate(parsed.get("day_lines") or []):
        if _looks_german(line):
            found.append(f"day_lines[{i}]")
    if not found:
        return []
    return [_verr("language", "wrong_language",
                  f"Diese Felder sind DEUTSCH, die Ausgabesprache ist ENGLISCH: "
                  f"{found[:8]}{' …' if len(found) > 8 else ''}. Schreibe ALLE "
                  f"Textfelder auf Englisch (Zonen: Northern Alps, Valais, Ticino, "
                  f"Grisons).")]


def _word_count(text: str) -> int:
    return len((text or "").split())


def _length_problems(text: str, max_words: int, field: str) -> list:
    """Ein Satz, hoechstens max_words Woerter."""
    problems = []
    n = _word_count(text)
    if n > max_words:
        problems.append(("too_long",
                         f"{field}: {n} Woerter — erlaubt sind hoechstens {max_words}. "
                         f"Auf den Punkt bringen: Details und Zahlen stehen im "
                         f"Briefing ohnehin daneben."))
    if _SENTENCE_BREAK_RE.search(text or ""):
        problems.append(("more_than_one_sentence",
                         f"{field}: GENAU EIN Satz — mehrere Saetze zusammenziehen "
                         f"oder den weniger wichtigen streichen."))
    return problems


def _verdict_problem(text: str, field: str) -> list:
    hit = _VERDICT_RE.search(text or "")
    if not hit:
        return []
    return [("verdict",
             f"{field}: {hit.group(0)!r} ist ein Urteil ueber das Fliegen. Ob "
             f"geflogen wird, entscheidet der Pilot — beschreibe nur, was das "
             f"Wetter tut und wo.")]

# Ortsbezug im Gefahren-Satz: Zonen-Namen, Alpenseiten, Grosslandschaften.
_PLACE_RE = re.compile(
    rf"(alpennord|alpens(?:ue|{_U_UMLAUT})d|nordalpen|s(?:ue|{_U_UMLAUT})dalpen|"
    rf"northern\s+alps|southern\s+alps|(?:north|south)(?:ern)?\s+(?:side|slope)|"
    rf"nordseite|s(?:ue|{_U_UMLAUT})dseite|nordhang|s(?:ue|{_U_UMLAUT})dhang|"
    rf"wallis|valais|tessin|ticino|graub(?:ue|{_U_UMLAUT})nden|grisons|engadin|"
    rf"mittelland|jura|voralpen|pre-?alps|inneralpin|inner-?alpine)",
    re.IGNORECASE,
)


# Tageszeit-Bezug im Gefahren-Satz (de + en). "mittag" deckt auch
# Vormittag/Nachmittag ab, "morgens" nicht mit "morgen" (Folgetag) verwechseln.
_TIME_RE = re.compile(
    rf"(vormittag|mittag|nachmittag|abend|morgens|am morgen|fr(?:ue|{_U_UMLAUT})h|"
    rf"tagesverlauf|ganztags|ganzen tag|sp(?:ae|{_A_UMLAUT})ter|"
    rf"\d{{1,2}}\s*uhr|ab \d{{1,2}}|bis \d{{1,2}}|"
    rf"morning|midday|noon|afternoon|evening|all day|through the day|"
    rf"\d{{1,2}}(?::\d{{2}})?\s*(?:am|pm))",
    re.IGNORECASE,
)


# Zonen-Protokoll statt Wetterbericht: "Alpennordhang: nass, Tessin: trocken".
# Ein Prognosetext kommt ohne Doppelpunkt und ohne Aufzaehlungszeichen aus —
# beides ist hier deshalb ein sicheres Zeichen fuer eine Liste.
_ENUM_RE = re.compile(r"(:|\s\u00b7\s|\s\|\s|\s\u2013\s\w+\s\u2013\s)")


# Verweis auf einen ANDEREN Tag. Die Gefahren-Saetze stehen in der Tages-
# Sektion des Briefings ("Heute im Detail") — dort gilt ausschliesslich der
# eine Tag. Mehrtages-Entwicklung gehoert in den `lead` (3-Tage-Sektion),
# genauso wie _situation_sentences() im Briefing Saetze mit fremdem Wochentag
# aussortiert. "morgens"/"am Morgen" ist eine Tageszeit und bleibt erlaubt.
_CROSS_DAY_RE = re.compile(
    r"(\bFolgetag|\bfolgetags|\b(?:ue|\u00fc)bermorgen\b|(?<![A-Za-z\u00c4\u00d6\u00dc])morgen\b(?!s)|"
    r"\bVortag|\bnext day\b|\btomorrow\b|\byesterday\b|\bthe day after\b|"
    # Satzanfang "Morgen ..." meint den Folgetag; die Tageszeit hiesse
    # "Am Morgen" und bleibt damit erlaubt.
    r"(?:^|[.!?]\s+)Morgen\b(?!s)|"
    r"\b(Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)\b|"
    r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b)")


# --- Beginn je Zone gegen die Fensterdaten ----------------------------------
# Zonen-Erwaehnungen im Fliesstext (de + en). Nur fuer die Onset-Pruefung —
# der Ortsbezug an sich laeuft ueber _PLACE_RE.
_ZONE_ALIASES = {
    "alpennordhang": (r"alpennord\w*", r"nordalpen", r"northern\s+alps",
                      r"north(?:ern)?\s+side\s+of\s+the\s+alps"),
    "wallis": (r"wallis", r"valais"),
    "tessin": (r"tessin", r"ticino"),
    "graubuenden_engadin": (rf"graub(?:ue|{_U_UMLAUT})nden", r"grisons",
                            r"engadin\w*"),
}
# Zeitwort -> Fenster, in dem der genannte Verlauf BEGINNT
_ONSET_WORDS = (
    # \b ueberall: "mittag" steckt sonst in "Nachmittag" und "Vormittag"
    (r"\b(?:ganzen\s+tag|ganzt(?:ae|\u00e4)g\w*|all\s+day|throughout\s+the\s+day)", "morning"),
    (r"\b(?:vormittag\w*|morgens|am\s+morgen|fr(?:ue|\u00fc)h\w*|morning|early)", "morning"),
    (r"\b(?:nachmittag\w*|afternoon)", "afternoon"),
    (r"\b(?:mittag\w*|midday|noon)", "midday"),
    (r"\b(?:abend\w*|evening)", "evening"),
)
# "bis Mittag" / "until the evening" nennt ein ENDE, keinen Beginn
_UNTIL_RE = re.compile(r"(?:bis(?:\s+(?:zum|zur|in\s+den))?|until|till)\s+(?:the\s+|am\s+|dem\s+|den\s+)?$",
                       re.IGNORECASE)
_CLAUSE_SPLIT_RE = re.compile(r"[;,.]|\bwhile\b|\bw(?:ae|\u00e4)hrend\b|\bwhereas\b",
                              re.IGNORECASE)


def _stated_onset(clause: str) -> Optional[str]:
    """Fruehestes Zeitfenster, das der Teilsatz als BEGINN nennt (oder None)."""
    order = [w[0] for w in config.SYNOPTIC_DAY_WINDOWS]
    found = []
    for pattern, window in _ONSET_WORDS:
        for m in re.finditer(pattern, clause, re.IGNORECASE):
            if _UNTIL_RE.search(clause[:m.start()]):
                continue
            found.append(window)
    return min(found, key=order.index) if found else None


def _onset_too_late(text: str, windows_by_zone: dict) -> list:
    """Zonen, fuer die der Satz einen SPAETEREN Beginn nennt als die Daten.

    Returns: [(zone, genannt, laut_daten)]. Geprueft werden nur Zonen, die in
    `windows_by_zone` stehen — was nicht betroffen ist, darf frei beschrieben
    werden ("im Wallis bleibt es trocken").
    """
    order = [w[0] for w in config.SYNOPTIC_DAY_WINDOWS]
    out = []
    for clause in _CLAUSE_SPLIT_RE.split(text or ""):
        onset = _stated_onset(clause)
        if onset is None:
            continue
        for zone, aliases in _ZONE_ALIASES.items():
            wins = windows_by_zone.get(zone)
            if not wins:
                continue
            if not any(re.search(a, clause, re.IGNORECASE) for a in aliases):
                continue
            first = min(wins, key=order.index)
            if order.index(onset) > order.index(first):
                out.append((zone, onset, first))
    return out


def _num(v) -> float:
    return float(v) if isinstance(v, (int, float)) else 0.0


def _zone_entry(ctx: dict, key: str, i: int, zone: str) -> dict:
    """Zonen-Eintrag aus precip_zones/wind_zones am Forecast-Tag i."""
    per_day = (ctx.get(key) or {}).get("per_day") or []
    if i >= len(per_day):
        return {}
    return ((per_day[i].get("zones") or {}).get(zone)) or {}


# --- Tagesverlauf ----------------------------------------------------------
# Die Tagespauschale ist fuer den Piloten die falsche Aufloesung: "Regen am
# Alpennordhang" kann ein verlorener Tag sein oder ein fliegbarer Vormittag
# mit Abbruch um 13 Uhr. Beides steht in den Fenster-Aggregaten
# (precip_zones/wind_zones -> windows), wir heben es nur in die Gefahr hoch.

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
    if topic == "BISE":
        return abs(_num(f.get("delta_p_hpa")))
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
    bise_by_date = {d.get("date"): d for d in (ctx.get("bise") or {}).get("per_day") or []
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
        bi = bise_by_date.get(date) or {}

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
                                "tal": fo.get("tal") if side else None,
                                "delta_p_min_hpa": (foehn_thr.get("delta_p_danger_hpa", 8)
                                                    if peak == "danger"
                                                    else foehn_thr.get("delta_p_caution_hpa", 4))}},
            "BISE": {"active": bool(bi.get("active")), "level": "warn", "zones": [],
                     "facts": {"strength": bi.get("strength"),
                               "delta_p_hpa": bi.get("delta_p_hpa")}},
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


def _hazards_for_llm(checks: list) -> list:
    """Nur die aktiven Themen je Tag, mit Zonen und Tagesverlauf.

    `day_shape`/`windows` sind der Tagesverlauf innerhalb DIESES Tages —
    vom Code entschieden, der LLM formuliert sie nur aus. Der Folgetag-Trend
    (`facts["tomorrow"]`) geht bewusst NICHT an den LLM: der Gefahren-Satz
    steht in der Tages-Sektion und darf keinen anderen Tag nennen.
    """
    out = []
    for c in checks:
        active = {}
        for topic in HAZARD_TOPICS:
            v = c["checks"][topic]
            if not v["active"]:
                continue
            f = v.get("facts") or {}
            entry = {"zones": v["zones"]}
            if topic == "FOEHN":
                entry["side"] = f.get("side")
                entry["peak"] = f.get("peak")          # caution | danger
                if f.get("course"):
                    entry["course"] = f["course"]      # innerhalb DIESES Tages
                tal = f.get("tal")
                if tal:
                    from foehn_talpunkte import tal_kurzname, tal_namen
                    entry["tal_checked"] = True
                    entry["tal_confirmed"] = tal_namen(tal)
                    entry["tal_unconfirmed_n"] = tal.get("n_total", 0) - tal.get("n_bestaetigt", 0)
                    if tal.get("n_bestaetigt"):
                        entry["tal_wind_kmh"] = f"{tal['wind_min_kmh']}-{tal['wind_max_kmh']}"
                        entry["tal_gust_max_kmh"] = tal["gust_max_kmh"]
                        entry["tal_gust_valley"] = tal_kurzname(tal.get("gust_tal", ""))
                elif f.get("lee_gust_kmh"):
                    entry["lee_gust_kmh"] = f["lee_gust_kmh"]
            if f.get("day_shape"):
                entry["day_shape"] = f["day_shape"]["shape"]
                entry["windows"] = f.get("windows") or {}
            active[topic] = entry
        out.append({"date": c["date"], "active": active})
    return out


def _hazard_text_problems(text, topic: str, ctx: dict, i: int, day_checks: dict,
                          valid_centers: set) -> list:
    """Inhaltliche Fehler eines Gefahren-Satzes als [(kind, message)]."""
    if not isinstance(text, str) or not text.strip():
        return [("schema", "Eintrag braucht ein nicht-leeres `text`-Feld.")]
    problems = []
    # Tagesverlauf: wenn der Code sagt, dass die Gefahr NICHT ganztags gilt,
    # muss der Satz die Zeit nennen — sonst wird aus einem fliegbaren
    # Vormittag ein verlorener Tag (Vorfall 25.07.2026, Tagespauschale).
    shape = ((day_checks.get(topic) or {}).get("facts") or {}).get("day_shape")
    if (shape and shape["shape"] == "gemischt"
            and len({m.group(0).lower() for m in _TIME_RE.finditer(text)}) < 2):
        problems.append(("time_not_differentiated",
                         f"Die Zonen verlaufen an diesem Tag UNTERSCHIEDLICH "
                         f"(`windows` je Zone: "
                         f"{((day_checks.get(topic) or {}).get('facts') or {}).get('windows')}). "
                         f"Eine einzige Zeitangabe fuer alle ist falsch — nenne "
                         f"den Verlauf je Raum, z.B. 'den ganzen Tag an der "
                         f"Alpennordseite, im Wallis nur morgens und abends'."))
    elif shape and shape["shape"] != "ganztags" and not _TIME_RE.search(text):
        problems.append(("no_time",
                         f"Die Gefahr gilt nicht den ganzen Tag "
                         f"(`day_shape` = {shape['shape']}, Fenster "
                         f"{shape['hit']}) — der Satz MUSS die Tageszeit "
                         f"nennen (z.B. 'ab dem Nachmittag', 'nur am "
                         f"Vormittag')."))
    bad = _find_forbidden_term(text, _fronts_ok(ctx))
    if bad:
        problems.append(("forbidden_term",
                         f"`text` enthaelt einen verbotenen Begriff (Muster: {bad})."))
    invalid = _check_pressure_region_mentions(text, valid_centers)
    if invalid:
        problems.append(("invalid_region",
                         f"`text` nennt nicht detektierte Regionen: {invalid}. "
                         f"Erlaubt: {_allowed_centers(valid_centers)}."))
    if not day_checks["FOEHN"]["active"]:
        hit = _FOEHN_MENTION_RE.search(text)
        if hit:
            problems.append(("foehn_not_active",
                             f"An diesem Tag ist FOEHN nicht aktiv — {hit.group(0)!r} "
                             f"darf im Gefahren-Satz nicht vorkommen."))
    elif _text_inverts_foehn_lee(text, day_checks["FOEHN"]["facts"]["side"]):
        problems.append(("foehn_lee_inversion",
                         "Foehn aktiv — die Lee-Seite darf nicht als "
                         "geschuetzt/ruhig beschrieben werden."))
    if topic == "FOEHN" and day_checks["FOEHN"]["active"]:
        problems.extend(_foehn_tal_problems(
            text, day_checks["FOEHN"]["facts"].get("tal"),
            require_name=True, require_aloft=True, only_foehn_sentences=False))
    if not day_checks["THUNDER"]["active"]:
        hit = _GEWITTER_RE.search(text)
        if hit:
            problems.append(("gewitter_without_signal",
                             f"An diesem Tag ist THUNDER nicht aktiv — "
                             f"{hit.group(0)!r} ist nicht gedeckt."))
    facts = (day_checks.get(topic) or {}).get("facts") or {}
    for zone, stated, first in _onset_too_late(text, facts.get("windows") or {}):
        problems.append(("onset_too_late",
                         f"Der Satz nennt fuer {zone} einen Beginn ab {stated!r}, "
                         f"laut `windows` ist die Zone aber schon ab {first!r} "
                         f"betroffen ({facts['windows'][zone]}). Einen spaeteren "
                         f"Beginn zu nennen als die Daten ist gefaehrlich — der "
                         f"Pilot haelt die Stunden davor fuer fliegbar. Nenne "
                         f"den Verlauf dieser Zone so, wie er in `windows` steht."))
    cross_hit = _CROSS_DAY_RE.search(text)
    if cross_hit:
        problems.append(("cross_day",
                         f"{cross_hit.group(0)!r} verweist auf einen anderen "
                         f"Tag. Der Gefahren-Satz steht in der TAGES-Sektion "
                         f"des Briefings und gilt ausschliesslich fuer diesen "
                         f"einen Tag — kein Folgetag, kein Vortag, kein "
                         f"Wochentag. Mehrtages-Entwicklung gehoert in `lead`."))
    problems.extend(_length_problems(text, HAZARD_MAX_WORDS, "Gefahren-Satz"))
    problems.extend(_verdict_problem(text, "Gefahren-Satz"))
    enum_hit = _ENUM_RE.search(text)
    if enum_hit:
        problems.append(("enumeration",
                         f"{enum_hit.group(0)!r} macht aus dem Satz eine "
                         f"Gebiets-Liste. Der Gefahren-Satz ist ein "
                         f"Wetterbericht-Satz: die Gefahr SETZT EIN, GREIFT "
                         f"UEBER, KLINGT AB — Ort und Zeit gehoeren in den "
                         f"Satzfluss ('Ab Mittag greift von Westen her Regen "
                         f"auf die Alpennordseite ueber'), nicht als "
                         f"'<Gebiet>: <Zustand>' hintereinander."))
    if not _PLACE_RE.search(text):
        problems.append(("no_place",
                         "Der Gefahren-Satz nennt keinen Ort. Pflicht: Zonen-Name "
                         "(Alpennordhang, Wallis, Tessin, Graubuenden/Engadin) oder "
                         "Alpennord-/Alpensuedseite, Mittelland, Jura."))
    return problems


def _validate_hazards(parsed: dict, ctx: dict) -> list:
    """Prueft `hazards`: ein Eintrag pro Tag, genau die vom Code geschalteten
    Themen, jeder Satz mit Ortsbezug und ohne erfundene Gefahr."""
    errors = []
    fc_dates = ctx.get("forecast_dates") or []
    checks = hazard_checks(ctx)
    valid_centers = _collect_valid_center_labels(ctx)
    any_active = any(v["active"] for c in checks for v in c["checks"].values())

    hz = parsed.get("hazards")
    if hz is None and not any_active:
        return errors
    if not isinstance(hz, list):
        errors.append(_verr("hazards", "schema",
                            "`hazards` fehlt oder ist keine Liste — Pflichtfeld: "
                            'ein Eintrag {"items": [...]} pro forecast_date, '
                            "gleiche Reihenfolge."))
        return errors
    if fc_dates and len(hz) != len(fc_dates):
        errors.append(_verr("hazards", "schema",
                            f"`hazards` hat {len(hz)} Eintraege, erwartet "
                            f"{len(fc_dates)} — genau einer pro Tag."))

    for i, c in enumerate(checks):
        scope = f"hazards[{i}]"
        active = [t for t in HAZARD_TOPICS if c["checks"][t]["active"]]
        entry = hz[i] if i < len(hz) else None
        items = entry.get("items") if isinstance(entry, dict) else None
        if not isinstance(items, list):
            if active:
                errors.append(_verr(scope, "schema",
                                    f'Eintrag braucht {{"items": [...]}} mit den '
                                    f"aktiven Themen {active}."))
            continue
        written = []
        for item in items:
            topic = item.get("topic") if isinstance(item, dict) else None
            if topic not in HAZARD_TOPICS:
                errors.append(_verr(scope, "unknown_topic",
                                    f"Unbekanntes Thema {topic!r} — erlaubt: "
                                    f"{list(HAZARD_TOPICS)}."))
                continue
            if topic not in active:
                errors.append(_verr(f"{scope}.{topic}", "hazard_not_active",
                                    f"{topic} ist an diesem Tag laut "
                                    f"`hazards_per_day` NICHT aktiv — Eintrag "
                                    f"streichen. Aktiv sind nur: {active or 'keine'}."))
                continue
            if topic in written:
                errors.append(_verr(f"{scope}.{topic}", "duplicate",
                                    f"{topic} doppelt — genau ein Eintrag je Thema."))
                continue
            written.append(topic)
            for kind, msg in _hazard_text_problems(item.get("text"), topic, ctx,
                                                   i, c["checks"], valid_centers):
                errors.append(_verr(f"{scope}.{topic}", kind, msg))
        missing = [t for t in active if t not in written]
        if missing:
            errors.append(_verr(scope, "hazard_missing",
                                f"Aktive Gefahren ohne Satz: {missing}. Fuer jedes "
                                f"aktive Thema genau ein Eintrag."))
    return errors


def _day_line_problems(text, ctx: dict, i: int, day_checks: dict,
                       valid_centers: set) -> list:
    """Inhaltliche Fehler eines Tagessatzes als [(kind, message)]."""
    if not isinstance(text, str) or not text.strip():
        return [("schema", "Tagessatz muss ein nicht-leerer String sein.")]
    problems = []
    problems.extend(_length_problems(text, DAY_LINE_MAX_WORDS, "Tagessatz"))
    problems.extend(_verdict_problem(text, "Tagessatz"))
    bad = _find_forbidden_term(text, _fronts_ok(ctx))
    if bad:
        problems.append(("forbidden_term",
                         f"Tagessatz enthaelt einen verbotenen Begriff (Muster: {bad})."))
    invalid = _check_pressure_region_mentions(text, valid_centers)
    if invalid:
        problems.append(("invalid_region",
                         f"Tagessatz nennt nicht detektierte Regionen: {invalid}. "
                         f"Erlaubt: {_allowed_centers(valid_centers)}."))
    hit = _CROSS_DAY_RE.search(text)
    if hit:
        problems.append(("cross_day",
                         f"{hit.group(0)!r} verweist auf einen anderen Tag — der "
                         f"Tagessatz gilt nur fuer diesen einen Tag."))
    if not day_checks["FOEHN"]["active"] and _FOEHN_MENTION_RE.search(text):
        problems.append(("foehn_not_active",
                         "An diesem Tag ist FOEHN nicht aktiv — kein Foehn im Tagessatz."))
    if not day_checks["THUNDER"]["active"] and _GEWITTER_RE.search(text):
        problems.append(("gewitter_without_signal",
                         "An diesem Tag ist THUNDER nicht aktiv — keine Gewitter im Tagessatz."))
    return problems


def _validate_day_lines(parsed: dict, ctx: dict) -> list:
    """`day_lines`: je forecast_date genau ein kurzer Satz, tagesrein, ohne Urteil."""
    errors = []
    fc_dates = ctx.get("forecast_dates") or []
    lines = parsed.get("day_lines")
    if not isinstance(lines, list):
        return [_verr("day_lines", "schema",
                      "`day_lines` fehlt oder ist keine Liste — Pflichtfeld: je "
                      "forecast_date EIN Satz (max "
                      f"{DAY_LINE_MAX_WORDS} Woerter), gleiche Reihenfolge.")]
    if fc_dates and len(lines) != len(fc_dates):
        errors.append(_verr("day_lines", "schema",
                            f"`day_lines` hat {len(lines)} Eintraege, erwartet "
                            f"{len(fc_dates)} — genau einer pro Tag."))
    checks = hazard_checks(ctx)
    valid_centers = _collect_valid_center_labels(ctx)
    for i, c in enumerate(checks):
        if i >= len(lines):
            break
        for kind, msg in _day_line_problems(lines[i], ctx, i, c["checks"], valid_centers):
            errors.append(_verr(f"day_lines[{i}]", kind, msg))
        fo = c["checks"]["FOEHN"]
        if fo["active"] and isinstance(lines[i], str):
            for kind, msg in _foehn_tal_problems(lines[i], fo["facts"].get("tal"),
                                                 require_name=False, require_aloft=False,
                                                 only_foehn_sentences=True):
                errors.append(_verr(f"day_lines[{i}]", kind, msg))
    return errors


def _finalize_day_lines(parsed: dict, ctx: dict, prune: bool) -> list:
    """Cache-Format: [{date, text}] je forecast_date; fehlerhafte Saetze nur beim
    Prune leer (das Briefing faellt dann auf den ersten Lead-Satz zurueck)."""
    lines = parsed.get("day_lines") if isinstance(parsed.get("day_lines"), list) else []
    valid_centers = _collect_valid_center_labels(ctx)
    out = []
    for i, c in enumerate(hazard_checks(ctx)):
        text = lines[i] if i < len(lines) else ""
        text = text.strip() if isinstance(text, str) else ""
        if text and prune and _day_line_problems(text, ctx, i, c["checks"], valid_centers):
            logger.warning("Nicht behebbarer Tagessatz entfernt (day %d): '%s'", i + 1, text)
            text = ""
        out.append({"date": c["date"],
                    "text": _neutralize_calendar_week_text(text) if text else ""})
    return out


def _finalize_hazards(parsed: dict, ctx: dict, prune: bool) -> list:
    """Cache-Format: [{date, checks, items: [{topic, text}]}] je forecast_date.
    checks kommen vom Code und stehen auch ohne LLM-Satz da. Nicht geschaltete
    Themen fallen immer weg, fehlerhafte Saetze nur beim Prune."""
    raw = parsed.get("hazards") if isinstance(parsed.get("hazards"), list) else []
    valid_centers = _collect_valid_center_labels(ctx)
    out = []
    for i, c in enumerate(hazard_checks(ctx)):
        entry = raw[i] if i < len(raw) else None
        items_raw = entry.get("items") if isinstance(entry, dict) else None
        by_topic = {}
        for item in items_raw if isinstance(items_raw, list) else []:
            if not isinstance(item, dict):
                continue
            topic = item.get("topic")
            text = item.get("text")
            if (topic not in HAZARD_TOPICS or not c["checks"][topic]["active"]
                    or topic in by_topic or not isinstance(text, str) or not text.strip()):
                continue
            text = text.strip()
            if prune and _hazard_text_problems(text, topic, ctx, i,
                                               c["checks"], valid_centers):
                logger.warning("Nicht behebbarer Gefahren-Satz entfernt "
                               "(%s day %d): '%s'", topic, i + 1, text)
                continue
            by_topic[topic] = _neutralize_calendar_week_text(text)
        out.append({
            "date": c["date"],
            "checks": c["checks"],
            "items": [{"topic": t, "text": by_topic[t]}
                      for t in HAZARD_TOPICS if t in by_topic],
        })
    return out
