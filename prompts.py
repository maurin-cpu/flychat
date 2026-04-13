"""
Chat- und Analyse-Prompts für Flychat.

Die Texte liegen unter skills/*.md (ein Skill = eine Markdown-Datei).
Beim Import werden sie geladen; Änderungen an den .md-Dateien wirken nach Neustart des Prozesses.
"""

from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parent / "skills"


def _load_skill(filename: str) -> str:
    path = _SKILLS_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Skill-Datei fehlt: {path}")
    return path.read_text(encoding="utf-8")


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
SPOT_ANALYSIS_PROMPT = _load_skill("spot_analysis_legacy.md")
SAFETY_CHECK_PROMPT = _load_skill("safety_check.md")
FLYABILITY_PROMPT = _load_skill("flyability.md")
REGION_SAFETY_CHECK_PROMPT = _load_skill("region_safety_check.md")
REGION_FLYABILITY_PROMPT = _load_skill("region_flyability.md")

# Für Tests oder externe Tools
SKILLS_DIR = _SKILLS_DIR
