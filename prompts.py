"""
Chat- und Analyse-Prompts für Gleitcast.

Die Texte liegen unter skills/*.md (ein Skill = eine Markdown-Datei).
Beim Import werden sie geladen; Änderungen an den .md-Dateien wirken nach Neustart des Prozesses.
"""

from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parent / "skills"
_SHARED_DIR = _SKILLS_DIR / "shared"

# Reihenfolge der Shared-Bausteine, wie sie in den Analyse-Prompt eingefügt werden.
# Pädagogische Ordnung: Prinzipien → Input-Karte → Gefahren → Override → Fliegbarkeit → Formulierung → Sub-Ratings.
_SHARED_BLOCKS = [
    "_core_principles.md",
    "_input_map.md",
    "_hazard_blocks.md",
    "_tages_override.md",
    "_flyability_tiers.md",
    "_formulierungs_tabelle.md",
    "_subratings_tables.md",
]

_INSERT_MARKER = "<!-- INSERT_SHARED -->"


def _load_skill(filename: str) -> str:
    path = _SKILLS_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Skill-Datei fehlt: {path}")
    return path.read_text(encoding="utf-8")


def _load_shared(filename: str) -> str:
    path = _SHARED_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Shared-Baustein fehlt: {path}")
    return path.read_text(encoding="utf-8")


def compose_analysis_prompt(mode: str) -> str:
    """Komponiert den Analyse-Prompt aus einem Mode-Template + Shared-Bausteinen.

    mode = 'spot' → skills/spot_analysis.md mit eingefügten Shared-Blöcken.
    mode = 'region' → skills/region_analysis.md mit eingefügten Shared-Blöcken.

    Das Template muss den Marker '<!-- INSERT_SHARED -->' enthalten; dort werden die
    Shared-Bausteine in fester Reihenfolge (siehe _SHARED_BLOCKS) eingesetzt.
    """
    if mode not in ("spot", "region"):
        raise ValueError(f"Unbekannter Analyse-Mode: {mode!r}")
    template = _load_skill(f"{mode}_analysis.md")
    if _INSERT_MARKER not in template:
        raise ValueError(f"{mode}_analysis.md enthält keinen {_INSERT_MARKER}-Marker")
    shared = "\n\n".join(_load_shared(name) for name in _SHARED_BLOCKS)
    return template.replace(_INSERT_MARKER, shared)


SYSTEM_PROMPT = _load_skill("system_chat.md")
CAPABILITIES_GUIDE = _load_skill("chat_capabilities_guide.md")
FOEHN_CHAT_KNOWLEDGE = _load_skill("foehn_chat_knowledge.md")
_FOEHN_LLM_REGIONAL_GUIDE_TEMPLATE = _load_skill("foehn_llm_regional_guide.md")


def format_foehn_llm_regional_guide() -> str:
    """Regionaler Erklärblock für den LLM-Kontext; Zahlen aus foehn_indicators (eine Quelle)."""
    from foehn_indicators import (
        SUEDFOEHN_DIR_END,
        SUEDFOEHN_DIR_START,
        THRESHOLD_CREST_WIND_CAUTION,
        THRESHOLD_DELTA_P_CAUTION,
        THRESHOLD_DELTA_P_DANGER,
    )

    return _FOEHN_LLM_REGIONAL_GUIDE_TEMPLATE.format(
        crest_caution=THRESHOLD_CREST_WIND_CAUTION,
        dp_caution=THRESHOLD_DELTA_P_CAUTION,
        dp_danger=THRESHOLD_DELTA_P_DANGER,
        sued_end=SUEDFOEHN_DIR_END,
        sued_start=SUEDFOEHN_DIR_START,
    )
SPOT_COMBINED_PROMPT = compose_analysis_prompt("spot")
REGION_COMBINED_PROMPT = compose_analysis_prompt("region")
WEEKLY_BRIEFING_PROMPT = _load_skill("weekly_briefing.md")

# Für Tests oder externe Tools
SKILLS_DIR = _SKILLS_DIR
