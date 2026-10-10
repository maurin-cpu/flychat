"""Sprach-Waechter: deutsche Reste in englischen Analyse-Texten ersetzen.

Gemessen 10.10.2026 am Server-Cache (EN-Modus): 55 % der Spot- und 66 % der
Regions-Analysen trugen deutsche Woerter in sichtbaren Feldern — "no
Gewitters", "dichte Wolkendecke", "Foehn-Warnhinweis … Boeen an exponierten
Stellen", Tag-Labels "Thermik"/"Bewoelkung". Quellen waren unuebersetzte
Prompt-Bausteine, der Tag-Sanitizer mit nur deutscher Tabelle und deutsche
Code-Texte der Decision-Engine. Die Quellen sind behoben; dieser Waechter ist
der Validator dahinter (Lehre: Skill-Regeln ohne Validator werden verletzt)
und zieht beim Laden auch Analysen nach, die vor dem Fix erzeugt wurden.

Er ersetzt nur BEKANNTE Begriffe (eigene Code-Texte und ein kurzes Glossar),
keine freie Uebersetzung. Im DE-Modus tut er nichts.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# Felder, die Namen oder Rohdaten tragen — nie anfassen.
_SKIP_KEYS = frozenset({
    "spot", "region", "region_name", "name", "spot_name", "region_id", "id",
    "date", "_decisions_applied", "bemerkung", "bemerkung_flug", "bemerkung_sicherheit",
})

# Tag-Labels (Einzelwoerter, vom LLM gesetzt). Gemessen 10.10.2026.
_LABEL_MAP = {
    "thermik": "Thermal", "thermikaktivitaet": "Thermal", "thermikaktivität": "Thermal",
    "bewoelkung": "Clouds", "bewölkung": "Clouds", "wolken": "Clouds",
    "fenster": "Window", "zeitfenster": "Window",
    "sonne": "Sunshine", "sonneneinstrahlung": "Sunshine", "sonnenschein": "Sunshine",
    "einstrahlung": "Sunshine",
    "strecke": "XC", "streckenpotenzial": "XC", "streckenflug": "XC",
    "boeen": "Gusts", "böen": "Gusts",
    "hoehenwind": "Upper wind", "höhenwind": "Upper wind",
    "regen": "Rain", "niederschlag": "Rain",
    "foehn": "Foehn", "föhn": "Foehn",
    "turbulenz": "Turbulence", "wolkenbasis": "Cloud base", "basis": "Cloud base",
}

# Glossar fuer Fliesstext — laengere Formen zuerst. Wortgrenzen, Gross-/
# Kleinschreibung egal; ein grosser Anfangsbuchstabe bleibt erhalten.
_GLOSSARY = (
    ("Gewittern", "thunderstorms"), ("Gewitters", "thunderstorms"), ("Gewitter", "thunderstorm"),
    ("Hoehenboeen", "gusts aloft"), ("Höhenböen", "gusts aloft"),
    ("Bodenboeen", "ground gusts"), ("Bodenböen", "ground gusts"),
    ("Hoehenscherung", "wind shear aloft"), ("Höhenscherung", "wind shear aloft"),
    ("Hoehenwind", "upper wind"), ("Höhenwind", "upper wind"),
    ("Boeen", "gusts"), ("Böen", "gusts"),
    ("Wolkendecke", "cloud cover"), ("Bewoelkung", "cloud cover"), ("Bewölkung", "cloud cover"),
    ("Thermik", "thermals"), ("Regen", "rain"),
    ("Nordfoehn", "north foehn"), ("Nordföhn", "north foehn"),
    ("Suedfoehn", "south foehn"), ("Südfoehn", "south foehn"), ("Südföhn", "south foehn"),
)

_FOEHN_DIR = {"süd": "south", "sued": "south", "nord": "north"}

_rules_cache: list | None = None


def _template_rule(de: str, en: str):
    """DE-Vorlage mit {platzhaltern} -> (Regex, EN-Vorlage)."""
    parts = re.split(r"\{(\w+)\}", de)
    pat = ""
    for i, part in enumerate(parts):
        pat += re.escape(part) if i % 2 == 0 else f"(?P<{part}>[^,;:—]+?)"
    return re.compile(pat), en


def _rules() -> list:
    """(Regex, Ersatz) in Anwendungsreihenfolge; einmal gebaut."""
    global _rules_cache
    if _rules_cache is not None:
        return _rules_cache
    import i18n
    from engine._common import _TAG_NATURAL, _TAG_NATURAL_EN

    rules: list = []
    # 1. Eigene Code-Texte der Decision-Engine (Vorlagen aus i18n, laengste zuerst).
    tmpl = [(v["de"], v["en"]) for k, v in i18n.STRINGS.items()
            if k.startswith("decision.") and v.get("de") and v.get("en") and v["de"] != v["en"]
            and len(v["de"]) > 6]
    for de, en in sorted(tmpl, key=lambda x: -len(x[0])):
        rules.append(("tmpl",) + _template_rule(de, en))
    # 2. Klartext-Begriffe des Tag-Sanitizers (DE-Fassung -> EN-Fassung).
    phrases = {}
    for tag, de in _TAG_NATURAL:
        phrases.setdefault(de, _TAG_NATURAL_EN[tag.upper()])
    # 3. Glossar.
    for de, en in _GLOSSARY:
        phrases.setdefault(de, en)
    for de in sorted(phrases, key=len, reverse=True):
        rules.append(("word", re.compile(r"(?<![\w-])" + re.escape(de) + r"(?![\w])", re.IGNORECASE),
                      phrases[de]))
    _rules_cache = rules
    return rules


def _keep_case(m: re.Match, out: str) -> str:
    """Grossschreibung nur am Satzanfang — deutsche Nomen sind immer gross,
    das sagt im Englischen nichts ("no Gewitter" -> "no thunderstorm")."""
    before = m.string[:m.start()].rstrip()
    if (not before or before[-1] in ".!?:—") and out[:1].islower():
        return out[0].upper() + out[1:]
    return out


def englishify_text(text: str) -> str:
    """Ersetzt bekannte deutsche Begriffe/Code-Texte durch Englisch. Nur EN-Modus."""
    if not text or not isinstance(text, str):
        return text
    import i18n
    if i18n.get_current_lang() != "en":
        return text
    out = text
    for kind, pat, rep in _rules():
        if kind == "tmpl":
            def _sub(m, rep=rep):
                vals = {k: _FOEHN_DIR.get(v.strip().lower(), v) if k == "dir" else v
                        for k, v in m.groupdict().items()}
                try:
                    return rep.format(**vals)
                except (KeyError, IndexError):
                    return m.group(0)
            out = pat.sub(_sub, out)
        else:
            out = pat.sub(lambda m, rep=rep: _keep_case(m, rep), out)
    return out


def english_label(label):
    """Tag-Label (Einzelwort) ins Englische, falls bekannt deutsch. Nur EN-Modus."""
    if not isinstance(label, str) or not label:
        return label
    import i18n
    if i18n.get_current_lang() != "en":
        return label
    return _LABEL_MAP.get(label.strip().lower(), label)


def englishify_result(obj, _key: str = ""):
    """Wendet den Waechter beliebig tief auf ein Analyse-Ergebnis an. Fliesstext
    (Strings mit Leerzeichen) wird ersetzt, `label`-Felder ueber die Label-
    Tabelle; Enums/IDs/Namen bleiben unberuehrt. Mutiert in place."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _SKIP_KEYS:
                continue
            if k == "label" and isinstance(v, str):
                obj[k] = english_label(v)
            else:
                obj[k] = englishify_result(v, k)
        return obj
    if isinstance(obj, list):
        return [englishify_result(x, _key) for x in obj]
    if isinstance(obj, str) and " " in obj:
        return englishify_text(obj)
    return obj


def englishify_analysis_tree(tree: dict, kind: str = "") -> int:
    """Waechter ueber einen ganzen Cache {name: {datum: ergebnis}}. Liefert die
    Zahl der geaenderten Ergebnisse (0 im DE-Modus)."""
    import i18n
    if i18n.get_current_lang() != "en" or not isinstance(tree, dict):
        return 0
    changed = 0
    for days in tree.values():
        if not isinstance(days, dict):
            continue
        for res in days.values():
            if not isinstance(res, dict):
                continue
            before = json.dumps(res, ensure_ascii=False, sort_keys=True)
            englishify_result(res)
            if json.dumps(res, ensure_ascii=False, sort_keys=True) != before:
                changed += 1
    if changed:
        logger.info("%sCache: %d Analysen vom Sprach-Waechter ins Englische nachgezogen", kind, changed)
    return changed
