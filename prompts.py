"""
Chat- und Analyse-Prompts für Wingcast.

Die Texte liegen unter skills/*.md (ein Skill = eine Markdown-Datei).

Skill-Texte enthalten Platzhalter der Form `{{cfg.KEY}}`, die beim Zugriff durch
den aktuellen Wert aus `config.X` ersetzt werden. Beispiel:
    "Wind > {{cfg.WIND_DANGER_KMH}} km/h"  -->  "Wind > 30 km/h"

Da die Prompts lazy via Modul-level `__getattr__` aufgelöst werden, greifen
Config-Änderungen (z.B. via Admin-UI) **sofort** beim nächsten Prompt-Zugriff —
kein Neustart nötig.

Consumer-Konvention: `import prompts` + `prompts.SYSTEM_PROMPT` statt
`from prompts import SYSTEM_PROMPT`, damit der Lazy-Access greift.
"""

import re
from pathlib import Path

import config

_SKILLS_DIR = Path(__file__).resolve().parent / "skills"
_SHARED_DIR = _SKILLS_DIR / "shared"
_METEO_RESEARCH_DIR = Path(__file__).resolve().parent / "meteo_research"

# Reihenfolge der Shared-Bausteine pro Phase. Combined-Pfad wurde entfernt
# (war Dead Code — alle Aufrufe gehen ueber `_build_and_analyze_*` = Split).
# Mode-spezifische Files (`_hazards_{mode}.md`, `_flight_subratings_{mode}.md`)
# werden in compose_analysis_prompt eingesetzt.
_SHARED_BLOCKS_SAFETY = [
    "01_global/01_core_principles.md",
    "01_global/02_input_format.md",
    "03_safety/01_tags_safety.md",
    "02_tagesfenster/01_tagesfenster.md",
    "03_safety/02_hazards_spot.md",
    "03_safety/03_status_derivation.md",
    "03_safety/04_safety_subratings.md",
]

_SHARED_BLOCKS_FLYABILITY = [
    "01_global/01_core_principles.md",
    "01_global/02_input_format.md",
    "04_flyability/01_tags_flyability.md",
    "04_flyability/02_flyability_rules.md",
    "04_flyability/03_prose_style.md",
    "04_flyability/04_flight_subratings_region.md",
]

_INSERT_MARKER_SAFETY = "<!-- INSERT_SHARED_SAFETY -->"
_INSERT_MARKER_FLYABILITY = "<!-- INSERT_SHARED_FLYABILITY -->"

# Platzhalter-Regex: {{cfg.KEY}} oder {{cfg.KEY|format}} (format ignoriert fuer jetzt).
# Namen akzeptiert: Grossbuchstaben + Zahlen + Unterstrich.
_CFG_PLACEHOLDER = re.compile(r"\{\{\s*cfg\.([A-Z][A-Z0-9_]*)\s*\}\}")


def _format_cfg_value(val) -> str:
    """Konvertiert einen Config-Wert zu einer lesbaren String-Darstellung.
    Integers bleiben Integers, Floats werden knapp formatiert."""
    if isinstance(val, bool):
        return "ja" if val else "nein"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        # Knapp: 2.5 statt 2.50, aber 0.70 bleibt 0.7
        if val == int(val):
            return str(int(val))
        s = f"{val:.2f}".rstrip("0").rstrip(".")
        return s
    return str(val)


def _render_placeholders(text: str) -> str:
    """Ersetzt alle {{cfg.KEY}}-Platzhalter durch den aktuellen config.KEY-Wert.
    Unbekannte Keys bleiben unveraendert (damit Bugs sichtbar werden statt
    stillschweigend falsche Werte zu liefern)."""
    def _repl(m):
        key = m.group(1)
        if not hasattr(config, key):
            return m.group(0)  # Platzhalter bleibt stehen - auffaellig fuer Debug
        return _format_cfg_value(getattr(config, key))
    return _CFG_PLACEHOLDER.sub(_repl, text)


def _load_skill(filename: str) -> str:
    """Laedt eine Skill-Datei und rendert alle {{cfg.KEY}}-Platzhalter."""
    path = _SKILLS_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Skill-Datei fehlt: {path}")
    raw = path.read_text(encoding="utf-8")
    return _render_placeholders(raw)


def _load_shared(filename: str) -> str:
    """Laedt einen Shared-Baustein und rendert Platzhalter."""
    path = _SHARED_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Shared-Baustein fehlt: {path}")
    raw = path.read_text(encoding="utf-8")
    return _render_placeholders(raw)


def _load_meteo_research(filename: str) -> str:
    """Laedt eine Recherche-Datei aus meteo_research/.

    Genutzt fuer Hintergrund-Wissensbasen, die dem LLM als Kontext mitgegeben
    werden (z.B. wetterlagen_pilotenwissen.md im Synoptik-Block). Diese Files
    sind reine Knowledge-Quellen — NICHT-determinierend, der LLM darf damit
    NUR interpretieren/formulieren, nicht Lagen erfinden.
    """
    path = _METEO_RESEARCH_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Meteo-Research-Datei fehlt: {path}")
    raw = path.read_text(encoding="utf-8")
    return _render_placeholders(raw)


def compose_analysis_prompt(mode: str, phase: str) -> str:
    """Komponiert den Analyse-Prompt aus Template (00_template_<mode>.md im
    jeweiligen Phase-Subordner) + Shared-Bausteinen.

    mode = 'spot' | 'region'
    phase = 'safety' | 'flyability'

    Jeder Aufruf re-liest die Datei und re-rendert die Platzhalter — daher
    greifen Config-Aenderungen live.
    """
    if mode not in ("spot", "region"):
        raise ValueError(f"Unbekannter Analyse-Mode: {mode!r}")
    if phase not in ("safety", "flyability"):
        raise ValueError(f"Unbekannte Analyse-Phase: {phase!r}")

    if phase == "safety":
        template = _load_shared(f"03_safety/00_template_{mode}.md")
        marker = _INSERT_MARKER_SAFETY
        blocks = list(_SHARED_BLOCKS_SAFETY)
    else:  # flyability
        template = _load_shared(f"04_flyability/00_template_{mode}.md")
        marker = _INSERT_MARKER_FLYABILITY
        blocks = list(_SHARED_BLOCKS_FLYABILITY)

    # Spots haben 5 Flight-Sub-Ratings (inkl. altitude_rating),
    # Regionen behalten die 4-Sub-Rating-Tabelle (keine Startplatzhoehe — Region-Spots
    # liegen auf verschiedenen Hoehen).
    if mode == "spot":
        blocks = [
            "04_flyability/04_flight_subratings_spot.md" if b == "04_flyability/04_flight_subratings_region.md" else b
            for b in blocks
        ]

    # Region-Pfade nutzen die schmalere Hazards-Variante (ohne Block 3 Boeen,
    # ohne ALOFT-GUST-Anteile). Spart ~1K Token pro Region-Call ohne Inhalts-
    # verlust — Region-LLMs koennen Boeen-Wissen ohnehin nicht anwenden.
    if mode == "region":
        blocks = [
            "03_safety/02_hazards_region.md" if b == "03_safety/02_hazards_spot.md" else b
            for b in blocks
        ]

    # Mode-spezifischer Context-Block. Wird direkt nach den Hazards-Bloecken
    # eingefuegt; bei Phase=flyability nach _input_format.md.
    context_block = "05_context/_spot_context.md" if mode == "spot" else "05_context/_region_context.md"
    hazards_block = "03_safety/02_hazards_spot.md" if mode == "spot" else "03_safety/02_hazards_region.md"
    insert_after = hazards_block if hazards_block in blocks else "01_global/02_input_format.md"
    insert_idx = blocks.index(insert_after) + 1
    blocks.insert(insert_idx, context_block)

    if marker not in template:
        raise ValueError(f"00_template_{mode}.md (phase={phase}) enthält keinen {marker}-Marker")
    shared = "\n\n".join(_load_shared(name) for name in blocks)
    composed = template.replace(marker, shared)

    # Sprach-Anweisung ans Ende (DE -> leer, Logik/Reasoning bleiben deutsch;
    # EN -> finale Ausgabe auf Englisch neu generiert). Siehe i18n.llm_lang_instruction.
    import i18n
    return composed + i18n.llm_lang_instruction()


def format_foehn_llm_regional_guide() -> str:
    """Regionaler Erklärblock für den LLM-Kontext; Zahlen aus foehn_indicators (eine Quelle)."""
    from foehn_indicators import (
        SUEDFOEHN_DIR_END,
        SUEDFOEHN_DIR_START,
        THRESHOLD_CREST_WIND_CAUTION,
        THRESHOLD_DELTA_P_CAUTION,
        THRESHOLD_DELTA_P_DANGER,
    )
    raw = _load_skill("foehn_llm_regional_guide.md")
    return raw.format(
        crest_caution=THRESHOLD_CREST_WIND_CAUTION,
        dp_caution=THRESHOLD_DELTA_P_CAUTION,
        dp_danger=THRESHOLD_DELTA_P_DANGER,
        sued_end=SUEDFOEHN_DIR_END,
        sued_start=SUEDFOEHN_DIR_START,
    )


# ---------------------------------------------------------------------------
# Lazy-Access via Modul-level __getattr__ (Python 3.7+).
#
# Greifen Consumer via `import prompts; prompts.SYSTEM_PROMPT` zu, wird bei
# jedem Zugriff frisch geladen + Platzhalter neu gerendert → Config-Aenderungen
# wirken sofort.
#
# HINWEIS: `from prompts import SYSTEM_PROMPT` bindet den Wert EINMAL beim
# Import-Zeitpunkt und sieht spaetere Aenderungen nicht. Consumer muessen daher
# `import prompts` + `prompts.SYSTEM_PROMPT` verwenden.
# ---------------------------------------------------------------------------

_LAZY_ATTRS = {
    "SYSTEM_PROMPT":            lambda: _load_skill("system_chat.md"),
    "CAPABILITIES_GUIDE":       lambda: _load_skill("chat_capabilities_guide.md"),
    "FOEHN_CHAT_KNOWLEDGE":     lambda: _load_skill("foehn_chat_knowledge.md"),
    "SPOT_SAFETY_PROMPT":       lambda: compose_analysis_prompt("spot", "safety"),
    "SPOT_FLYABILITY_PROMPT":   lambda: compose_analysis_prompt("spot", "flyability"),
    "REGION_SAFETY_PROMPT":     lambda: compose_analysis_prompt("region", "safety"),
    "REGION_FLYABILITY_PROMPT": lambda: compose_analysis_prompt("region", "flyability"),
    "SYNOPTIC_OVERVIEW_PROMPT": lambda: _load_skill("synoptic_overview.md"),
    "WETTERLAGEN_PILOTENWISSEN": lambda: _load_meteo_research("wetterlagen_pilotenwissen.md"),
}


def __getattr__(name: str):
    if name in _LAZY_ATTRS:
        return _LAZY_ATTRS[name]()
    raise AttributeError(f"module 'prompts' has no attribute {name!r}")


# Für Tests oder externe Tools
SKILLS_DIR = _SKILLS_DIR
