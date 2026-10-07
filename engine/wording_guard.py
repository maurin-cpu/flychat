"""Wortlaut-Waechter: Freigabe- und Urteilssprache aus KI-Texten entfernen.

Leitsatz: Wingcast empfiehlt nie, es beschreibt nur (skills/system_chat.md
Abschnitt 0a, Disclaimer in i18n.py). Der Skill verbietet "Empfehlung",
"du kannst fliegen" und Urteile wie "sicher"/"ideal" — aber Skill-Regeln ohne
Validator werden verletzt (Lehre aus der Synoptik-Zonen-Arbeit). Dieser
Waechter ist der Validator: ein deterministischer Ersatz der heikelsten
Formulierungen, bevor der Text den Piloten erreicht. Er aendert nur Woerter,
nie Aussagen (ein "nicht empfohlen" bleibt ein "nicht favorisiert"), und er
laesst Warnungen unangetastet — warnen ist immer erlaubt.

Sicherheits-Vokabular: safe = "no alerts", conditional = "alerts",
not_safe = "severe alerts" (DE: keine / — / schwere Warnhinweise).

Nicht angetastet wird das technische UI-Tag `[RECOMMENDED: ...]` — es
steuert die Hervorhebung auf der Karte und wird vom Frontend entfernt.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# Platzhalter, damit die Regeln das UI-Tag nie treffen.
_UI_TAG_RE = re.compile(r"\[RECOMMENDED:[^\]]*\]")
_UI_TAG_MARK = "\x00WCTAG{}\x00"

# (Muster, Ersatz) — Reihenfolge zaehlt: laengere Phrasen zuerst, damit
# "I recommend" nicht erst zu "I favor" und dann nochmals umgebaut wird.
# Gross-/Kleinschreibung des ersten Buchstabens bleibt erhalten (siehe _apply).
_RULES: tuple[tuple[re.Pattern, str], ...] = tuple(
    (re.compile(pat, re.IGNORECASE), rep) for pat, rep in (
        # --- Englisch: Freigabe ---
        (r"\bgo ahead and (fly|launch)\b",            r"conditions look workable to \1"),
        (r"\byou (can|could|may) (safely )?(fly|launch)\b", r"\3ing looks possible"),
        (r"\byou should (fly|launch)\b",              r"\1ing looks reasonable"),
        (r"\bcleared (to|for) (fly|launch|flying|launching)\b", r"without alerts for flying"),
        (r"\bgreen light\b",                          "no alerts"),
        (r"\bgo for it\b",                            "conditions look workable"),
        (r"\b(I|we) (would |'d )?recommend\b",        r"\1 would favor"),
        (r"\brecommendations?\b",                     "assessment"),
        (r"\brecommended\b",                          "favored"),
        (r"\brecommend\b",                            "favor"),
        # --- Englisch: Urteil ueber den Tag -> Befund der Pruefung ---
        (r"\bnot safe\b",                             "severe alerts"),
        (r"\bunsafe\b",                               "severe alerts"),
        (r"\bconditionally safe\b",                   "with alerts"),
        (r"\bsafe to (fly|launch)\b",                 r"without alerts for \1ing"),
        (r"\b(is|are|looks?|seems?|remains?) safe\b", r"\1 without alerts"),
        (r"\bsafely\b",                               "without alerts"),
        (r"\b(rather than|instead of|than) safe\b",  r"\1 without alerts"),
        (r"\ba safe (day|window|flight|option|choice|spot|bet)\b", r"a \1 without alerts"),
        (r"\bsafe (conditions|days?|windows?|flights?|flying|options?|periods?|phases?|hours|blocks?)\b", r"\1 without alerts"),
        (r"\bno-go\b",                                "severe alert"),
        (r"\bsafe (limits?|thresholds?|range|margin)\b", r"the \1"),
        (r"\bas safe\b",                              "as 'no alerts'"),
        (r"\brated safe\b",                           "rated 'no alerts'"),
        (r"\b(always|and|but|still|generally|overall) safe\b", r"\1 without alerts"),
        (r"\bsafe (synoptic|setup|situation|pattern|picture)\b", r"unremarkable \1"),
        # --- Englisch: Wetter als Tatsache -> Datenbezug ---
        (r"\bno foehn\b(?! (signs|wind|indicated))",  "no signs of foehn in the data"),
        (r"\bno bise\b(?! (signs|indicated))",        "no signs of Bise in the data"),
        (r"\b(north|south)(ern)? foehn situation\b",  r"data indicating \1 foehn"),
        (r"\bfoehn situation\b",                      "foehn indicated by the data"),
        # --- Englisch: Aufforderung an den Piloten -> Befund ---
        (r"\b(pilots|you) should (avoid|steer clear of|stay away from|skip)\b", "the alert covers"),
        (r"\b(pilots|you) should not (fly|launch)\b", r"severe alert for \2ing"),
        (r"\bavoid (flying|launching)\b",             r"alert for \1"),
        (r"\b(pilots|you) should (wait|hold off)\b",   "the alert applies"),
        (r"\b(perfect|ideal|excellent|risk-free|harmless) (conditions|day|window)\b", r"unremarkable \2"),
        # --- Deutsch: Freigabe ---
        (r"\bdu (kannst|darfst) (sicher |bedenkenlos )?(fliegen|starten)\b", r"\3 sieht möglich aus"),
        (r"\bdu solltest (fliegen|starten)\b",        r"\1 sieht vernünftig aus"),
        (r"\bgrünes Licht\b",                         "keine Warnhinweise"),
        (r"\bFreigabe\b",                             "Einschätzung"),
        (r"\bfreigegeben\b",                          "als fliegbar eingeschätzt"),
        (r"\bich würde empfehlen\b",                  "ich würde favorisieren"),
        (r"\bwir würden empfehlen\b",                 "wir würden favorisieren"),
        (r"\bich empfehle\b",                         "ich favorisiere"),
        (r"\bwir empfehlen\b",                        "wir favorisieren"),
        (r"\bempfehlen\b",                            "favorisieren"),
        (r"\bEmpfehlungen\b",                         "Einschätzungen"),
        (r"\bEmpfehlung\b",                           "Einschätzung"),
        (r"\bempfohlen\b",                            "favorisiert"),
        # --- Deutsch: Urteil -> Befund (nie "sicher" allein: "sicher nicht", "sicherlich") ---
        (r"\bnicht sicher\b",                         "mit schweren Warnhinweisen"),
        (r"\bbedingt sicher\b",                       "mit Warnhinweisen"),
        (r"\bsicher fliegbar\b",                      "fliegbar ohne Warnhinweise"),
        (r"\bsicherer (Flugtag|Tag)\b",               r"\1 ohne Warnhinweise"),
        (r"\bsichere[rn]? (Bedingungen|Option|Alternative|Wahl)\b", r"\1 ohne Warnhinweise"),
        (r"\b(perfekte|ideale|risikolose|unbedenkliche|harmlose)[rn]? (Bedingungen|Tag|Fenster)\b", r"unauffällige \2"),
        # --- Deutsch: Wetter als Tatsache -> Datenbezug ---
        (r"\bkein Föhn\b",                            "keine Föhn-Anzeichen in den Daten"),
        (r"\bkeine Bise\b(?!-)",                      "keine Bise-Anzeichen in den Daten"),
        (r"\b(Süd|Nord)föhnlage\b",                   r"\1föhn laut Daten"),
        (r"\bFöhnlage\b",                             "Föhn laut Daten"),
        # --- Deutsch: Aufforderung -> Befund ---
        (r"\bPiloten sollten (.{1,60}?) (meiden|vermeiden|auslassen)\b", r"der Warnhinweis gilt für \1"),
        (r"\b(Piloten sollten|du solltest) nicht (fliegen|starten)\b", "schwerer Warnhinweis für Flüge"),
        (r"\bsollte nicht geflogen werden\b",         "trägt einen schweren Warnhinweis"),
    )
)

def soften_result(result, label: str = "", log: bool = True):
    """Wendet den Waechter auf JEDEN Prosa-String eines Analyse-Ergebnisses an,
    beliebig tief (safety/flyability/streckenflug/hazard_notes/...). Strings ohne
    Leerzeichen (Enums wie `safe`, IDs, Daten) werden nie angefasst. Mutiert in
    place und gibt das Ergebnis zurueck."""
    if isinstance(result, dict):
        for key, val in result.items():
            result[key] = soften_result(val, label=label, log=log)
        return result
    if isinstance(result, list):
        return [soften_result(x, label=label, log=log) for x in result]
    if isinstance(result, str) and " " in result:
        return soften_clearance(result, label=label, log=log)
    return result


def soften_analysis_tree(tree: dict, kind: str = "") -> int:
    """Waechter ueber einen ganzen Cache {name: {datum: ergebnis}} — fuer
    Analysen, die VOR dem Waechter erzeugt wurden und noch alte Formulierungen
    tragen. Liefert die Zahl der geaenderten Ergebnisse."""
    changed = 0
    if not isinstance(tree, dict):
        return 0
    for name, days in tree.items():
        if not isinstance(days, dict):
            continue
        for day, res in days.items():
            if not isinstance(res, dict):
                continue
            before = json.dumps(res, ensure_ascii=False, sort_keys=True)
            # Kein Log pro Treffer — beim Cache-Load waeren das tausend Zeilen
            # je Neustart; der Aufrufer meldet die Summe.
            soften_result(res, label=f"{kind}{name}/{day}", log=False)
            if json.dumps(res, ensure_ascii=False, sort_keys=True) != before:
                changed += 1
    if changed:
        logger.info("%sCache: %d Analyse-Texte vom Wortlaut-Waechter nachgezogen", kind, changed)
    return changed


def _apply(pat: re.Pattern, rep: str, text: str) -> tuple[str, int]:
    """subn mit Erhalt der Gross-/Kleinschreibung am Satzanfang."""
    def _sub(m: re.Match) -> str:
        out = m.expand(rep)
        if m.group(0)[:1].isupper() and out[:1].islower():
            out = out[0].upper() + out[1:]
        return out
    return pat.subn(_sub, text)


def soften_clearance(text: str, label: str = "", log: bool = True) -> str:
    """Ersetzt Freigabe- und Urteilsformulierungen durch beschreibende Sprache.

    Liefert den Text unveraendert zurueck, wenn nichts zu tun ist. Treffer
    werden geloggt (Zaehler fuer die Validierung: wie oft bricht das LLM
    die Regel 0a?).
    """
    if not text or not isinstance(text, str):
        return text
    tags: list[str] = []

    def _stash(m: re.Match) -> str:
        tags.append(m.group(0))
        return _UI_TAG_MARK.format(len(tags) - 1)

    work = _UI_TAG_RE.sub(_stash, text)
    hits: list[str] = []
    for pat, rep in _RULES:
        work, n = _apply(pat, rep, work)
        if n:
            hits.append(f"{pat.pattern}×{n}")
    for i, tag in enumerate(tags):
        work = work.replace(_UI_TAG_MARK.format(i), tag)
    if hits and log:
        prefix = f"[{label}] " if label else ""
        logger.warning("%sFreigabe-/Urteilssprache ersetzt: %s", prefix, "; ".join(hits))
    return work
