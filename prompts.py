"""
Chat- und Analyse-Prompts für Gleitcast.

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

# Safety-Phase: nur Gefahren-relevante Blöcke (spart ~10K tokens vs. Combined)
_SHARED_BLOCKS_SAFETY = [
    "_core_principles.md",
    "_input_map.md",
    "_hazard_blocks.md",
    "_tages_override.md",
]

# Flyability-Phase: nur Fliegbarkeits-relevante Blöcke
_SHARED_BLOCKS_FLYABILITY = [
    "_core_principles.md",
    "_input_map.md",
    "_flyability_tiers.md",
    "_formulierungs_tabelle.md",
    "_subratings_tables.md",
]

_INSERT_MARKER = "<!-- INSERT_SHARED -->"
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


def compose_analysis_prompt(mode: str, phase: str = "combined") -> str:
    """Komponiert den Analyse-Prompt aus einem Mode-Template + Shared-Bausteinen.

    mode = 'spot' | 'region'
    phase = 'combined' | 'safety' | 'flyability'

    combined → skills/{mode}_analysis.md + alle Shared-Blöcke (bisheriges Verhalten)
    safety  → skills/{mode}_safety.md + nur Safety-Blöcke (~7K tokens)
    flyability → skills/{mode}_flyability.md + nur Flyability-Blöcke (~10K tokens)

    Jeder Aufruf re-liest die Datei und re-rendert die Platzhalter — daher
    greifen Config-Aenderungen live.
    """
    if mode not in ("spot", "region"):
        raise ValueError(f"Unbekannter Analyse-Mode: {mode!r}")
    if phase not in ("combined", "safety", "flyability"):
        raise ValueError(f"Unbekannte Analyse-Phase: {phase!r}")

    if phase == "combined":
        template = _load_skill(f"{mode}_analysis.md")
        marker = _INSERT_MARKER
        blocks = _SHARED_BLOCKS
    elif phase == "safety":
        template = _load_skill(f"{mode}_safety.md")
        marker = _INSERT_MARKER_SAFETY
        blocks = _SHARED_BLOCKS_SAFETY
    else:  # flyability
        template = _load_skill(f"{mode}_flyability.md")
        marker = _INSERT_MARKER_FLYABILITY
        blocks = _SHARED_BLOCKS_FLYABILITY

    if marker not in template:
        raise ValueError(f"{mode}_{phase}.md enthält keinen {marker}-Marker")
    shared = "\n\n".join(_load_shared(name) for name in blocks)
    return template.replace(marker, shared)


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
    "SPOT_COMBINED_PROMPT":     lambda: compose_analysis_prompt("spot"),
    "REGION_COMBINED_PROMPT":   lambda: compose_analysis_prompt("region"),
    "SPOT_SAFETY_PROMPT":       lambda: compose_analysis_prompt("spot", "safety"),
    "SPOT_FLYABILITY_PROMPT":   lambda: compose_analysis_prompt("spot", "flyability"),
    "REGION_SAFETY_PROMPT":     lambda: compose_analysis_prompt("region", "safety"),
    "REGION_FLYABILITY_PROMPT": lambda: compose_analysis_prompt("region", "flyability"),
    "WEEKLY_BRIEFING_PROMPT":   lambda: _load_skill("weekly_briefing.md"),
}


def __getattr__(name: str):
    if name in _LAZY_ATTRS:
        return _LAZY_ATTRS[name]()
    raise AttributeError(f"module 'prompts' has no attribute {name!r}")


# Für Tests oder externe Tools
SKILLS_DIR = _SKILLS_DIR
