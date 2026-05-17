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
            max_tokens=4000,
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
    out = {
        "forecast_dates": ctx.get("forecast_dates"),
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
                     "char": d["alpennord"].get("value"),
                     "wet_share": d["alpennord"].get("wet_share"),
                     "n_spots": d["alpennord"].get("n_spots"),
                 },
                 "alpensued": {
                     "char": d["alpensued"].get("value"),
                     "wet_share": d["alpensued"].get("wet_share"),
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
