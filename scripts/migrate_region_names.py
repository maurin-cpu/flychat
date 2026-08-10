#!/usr/bin/env python3
"""Regionen-Umbenennung 2026-08 — Migration und Verifikation.

Doku: docs/REGIONEN_UMBENENNUNG_2026-08.md
Mapping: data/region_renames_2026-08.csv  (einzige Quelle, hier nichts hartkodiert)

Default ist Dry-Run. Geschrieben wird nur mit --apply, und dann mit Backup
je Datei.

    python scripts/migrate_region_names.py                    # Dry-Run, alle Stufen
    python scripts/migrate_region_names.py --stage A          # nur Stufe A
    python scripts/migrate_region_names.py --stage A --apply  # schreiben
    python scripts/migrate_region_names.py --verify           # Restsuche nach Altnamen
    python scripts/migrate_region_names.py --show-ambiguous   # die Ostschweiz-Fundstellen

    # Server: nur die gitignorierten Daten, die nicht über git kommen
    python scripts/migrate_region_names.py --paths validation/gewitter \
        --paths validation/fronten --paths data/labeled_examples.jsonl --apply

EINMALIG. Der versionierte Bestand ist am 10.08.2026 migriert; der Marker
data/.region_rename_2026-08.done sperrt einen zweiten unbegrenzten --apply-Lauf.
Zusätzlich überspringt jede Datei sich selbst, sobald ihre .pre_rename-Sicherung
existiert. Grund: "Freiburger Voralpen" und "Berner Oberland" sind zugleich Alt-
und Neuname — ein zweiter Lauf schöbe die Kette eine Stufe weiter.

Die drei Fallen und wie sie hier behandelt werden:

  1. Ketten (Schwarzsee -> Freiburger Voralpen -> Berner Oberland -> Emmental):
     Zwei-Pass über Platzhalter. Erst jeder Altname -> \\x00<n>\\x00, dann
     Platzhalter -> Neuname. Reihenfolgeunabhängig, auch bei Ringtausch.

  2. Teilstrings ("Ostschweiz" steckt in "Alpstein / Ostschweiz"):
     Pass 1 arbeitet längster Suchbegriff zuerst, zusätzlich wortgrenzen-bewusst.

  3. Gleicher Name, andere Bedeutung (die Spalte `region` der Spot-CSVs trägt die
     grobe DHV-Herkunft und enthält ebenfalls "Ostschweiz"):
     Strukturierte Dateien laufen spaltenscharf, nicht über den Dateitext. Und
     der alleinstehende Name "Ostschweiz" wird in Fliesstext grundsätzlich NICHT
     ersetzt (STRUCTURED_ONLY) — dort ist er meist der Landesteil, nicht unsere
     Region. Diese Fundstellen listet --show-ambiguous zum Entscheiden auf.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAPPING = ROOT / "data" / "region_renames_2026-08.csv"

# Marker, dass der versionierte Bestand migriert ist. Liegt IM Repo (anders als
# die .pre_rename-Sicherungen, die gitignored sind und auf einem frischen Klon
# oder dem Server gar nicht existieren). Solange er da ist, verweigert das
# Skript einen unbegrenzten --apply-Lauf: die Migration ist nicht wiederholbar,
# weil "Freiburger Voralpen" und "Berner Oberland" zugleich Alt- und Neuname
# sind. Fuer die gitignorierten Server-Daten gibt es --paths.
DONE_MARKER = ROOT / "data" / ".region_rename_2026-08.done"

# Namen, die alleinstehend mehrdeutig sind: nur in strukturierten Feldern
# ersetzen (CSV-Spalte, GeoJSON-Property, JSON-Feld), nie in Fliesstext.
STRUCTURED_ONLY = {"Ostschweiz"}

# ... ausser hier: Dateien, in denen "Ostschweiz" nachweislich unsere Region ist.
# cost_testing-Goldens sind mitgeschriebene LLM-Prompts der Form
# "SPOT: Hirzli (Hirzli, Ostschweiz)"; REFPOINT_LISTE.md ist eine erzeugte
# Regionstabelle. Ohne diese Ausnahme laufen die Golden-Vergleiche nach der
# Migration auf, weil die Prompts den alten Namen behalten.
AMBIGUOUS_ALLOWED = (
    "cost_testing/",
    "docs/REFPOINT_LISTE.md",
)

# ---------------------------------------------------------------------------
# Was nie angefasst wird
# ---------------------------------------------------------------------------

EXCLUDE_DIRS = {
    ".git", "archive", "node_modules", "__pycache__", ".venv", "venv",
    ".pytest_cache", ".next", "dist", "build", ".claude",
    "meteo_research",      # datierte Protokolle
    "import_dhv",          # mappt Kantone auf die grobe DHV-Herkunft (Plan §3.2)
}

# Dateien, die die Zuordnung alt->neu SELBST enthalten. Sie müssen die alten
# Namen behalten — ein Lauf darüber würde die Übersetzungstabelle übersetzen
# und damit unbrauchbar machen.
EXCLUDE_PATHS = {
    "data/region_renames_2026-08.csv",           # das Mapping
    "docs/REGIONEN_UMBENENNUNG_2026-08.md",      # die Dokumentation dazu
    "subscriber.py",                             # _REGION_ID_RENAMES_2026_08
    "tests/test_subscriber_region_rename.py",    # prüft ebendiese Tabelle
    "scripts/migrate_region_names.py",           # dieses Skript
}

# data/wetterdaten.json stand hier einmal drin ("rollend, wird um 06:00 neu
# erzeugt"). Das stimmt — und war trotzdem falsch: die Datei hält unter dem
# Schlüssel `_regions` die Regions-Wetterdaten, geschlüsselt auf die Regions-ID
# (chat_engine.py: `cached.pop("_regions")`). Ohne Migration liefen nach dem
# Deploy 15 von 29 Regionen in "Keine Wetterdaten" — bis zum nächsten
# Pipeline-Lauf. Die Datei ist ~200 MB; ein Lauf darüber dauert entsprechend,
# ist aber notwendig. (Real passiert am 10.08.2026.)

EXCLUDE_GLOBS = [
    "validation/xcontest/*.md",   # datierte Analysen = Protokoll eines Stands
    "data/history/*",             # echte Chatverläufe (Entscheid 2026-08-10)
    "data/preview/*",             # Generat
    "**/*.bak",
    "**/*.bak_*",
    "**/*.backup",
    "**/*.backup_*",
    "**/*.pre-backfill.bak",
]

TEXT_SUFFIXES = {
    ".py", ".js", ".html", ".css", ".md", ".txt", ".json", ".jsonl",
    ".csv", ".geojson", ".yml", ".yaml", ".sql",
}

# ---------------------------------------------------------------------------
# Stufen und Handler
# ---------------------------------------------------------------------------

# Spot-CSVs: nur die Spalte analyse_region. Die Spalte `region` bleibt.
SPOT_CSVS = {
    "data/fluggebiete_pge.csv": "A",
    "data/fluggebiete_dhv.csv": "A",
    "data/fluggebiete_test.csv": "C",
    "data/fluggebiete_foehntest.csv": "C",
}
SPOT_CSV_COLUMNS = ("analyse_region",)

GEOJSONS = (
    "data/regionen_polygone_mapped.geojson",
    "data/regionen_referenzpunkte.geojson",
    "data/regionen_referenzpunkte_precip.geojson",
)
GEOJSON_PROPERTIES = ("id", "region")

REGIONEN_CSV = "data/regionen.csv"
REGIONEN_CSV_COLUMNS = ("id", "region_name")

# Weitere CSVs mit einer eindeutigen Regions-Spalte (spaltenscharf, damit auch
# der mehrdeutige Name "Ostschweiz" dort sicher ersetzt werden kann).
CSV_REGION_COLUMNS = {
    "validation/xcontest/observations.csv": ("region",),
    "validation/xcontest/sector_audit.csv": ("region",),
    "validation/xcontest/spot_aliases.csv": ("nearest_site_region", "region_pip",
                                             "region_recorded"),
}
CSV_REGION_PREFIXES = {
    "validation/xcontest/_raw/": ("region",),
}


def csv_columns_for(rel: str):
    if rel in CSV_REGION_COLUMNS:
        return CSV_REGION_COLUMNS[rel]
    for prefix, cols in CSV_REGION_PREFIXES.items():
        if rel.startswith(prefix) and rel.endswith(".csv"):
            return cols
    return None

# Neue `description` für regionen.csv (Plan §4). 10 der 19 Zeilen beschreiben
# nach der Umbenennung den alten Zuschnitt. Schlüssel ist die NEUE id.
NEW_DESCRIPTIONS = {
    "berner_oberland":        "Berner Oberland von Adelboden/Kandersteg über Lenk und Gstaad bis Interlaken",
    "emmental":               "Entlebuch/Emmental - Falkenflue und Marbachegg, hügelige Voralpen",
    "berner_alpen":           "Hochalpine Kette Jungfrauregion/Grindelwald bis Brienzer Rothorn - exponierte Grate",
    "zentrale_voralpen":      "Freistehende Innerschweizer Vorberge: Pilatus, Rigi, Zugerberg",
    "mittelbuenden":          "Mittelbünden: Lenzerheide, Savognin, Parpaner Rothorn - breite Alpentäler",
    "glarner_alpen":          "Glarner Alpen mit Startplätzen 1200-1700m (Braunwald, Elm, Fronalp) - alpiner Flugcharakter",
    "alpstein":               "Markante Kalkfelsen Appenzell und Toggenburg (Ebenalp, Kronberg, Chäserugg)",
    "loetschental":           "Lötschental - Lauchernalp / Hockenhorngrat, hochalpin",
    "zentralschweizer_alpen": "Zentralschweizer Alpen: Engelberg, Melchsee-Frutt, Stoos",
    "tafeljura":              "Tafeljura: Belchen / Wasserfallen",
}

STAGE_B_PREFIXES = (
    "data/weather_archive/",
    "data/region_analyses",
    "data/spot_analyses",
    "data/labeled_examples.jsonl",
    "validation/xcontest/observations.csv",
    "validation/xcontest/_raw/",
    "validation/xcontest/sector_audit.csv",
    "validation/xcontest/spot_aliases.csv",
    # Gewitter-Richter: liest die Regionsnamen aus regionen_polygone_mapped.geojson
    # (scripts/validation_common.py:30) — hängt also direkt am Rename. Gitignored,
    # die Masse liegt auf dem Server (Plan §3 kennt diesen Zweig noch nicht).
    "validation/gewitter/",
    "validation/fronten/",
)

# JSON-Dateien, die rekursiv über Schlüssel und Werte laufen (ids UND Namen).
DEEP_JSON_PREFIXES = (
    "data/weather_archive/",
    "data/region_analyses",
    "data/spot_analyses",
    "validation/gewitter/",
    "validation/fronten/",
)


def stage_of(rel: str) -> str:
    if rel in SPOT_CSVS:
        return SPOT_CSVS[rel]
    if rel == REGIONEN_CSV or rel in GEOJSONS:
        return "A"
    for p in STAGE_B_PREFIXES:
        if rel.startswith(p):
            return "B"
    return "C"


# ---------------------------------------------------------------------------
# Mapping laden
# ---------------------------------------------------------------------------

class Rule:
    __slots__ = ("alt", "neu", "typ", "regex", "structured_only", "token")

    def __init__(self, alt, neu, typ, idx):
        self.alt = alt
        self.neu = neu
        self.typ = typ
        self.structured_only = alt in STRUCTURED_ONLY
        self.token = f"\x00{idx}\x00"
        # Wortgrenzen: kein Buchstabe/Ziffer/Unterstrich direkt davor oder danach.
        # Umlaute zählen als Buchstabe, sonst würde "Mittelbünden" an "Mittelb"
        # aufgetrennt werden können.
        w = r"0-9A-Za-zÄÖÜäöüßéèàâç_"
        self.regex = re.compile(
            rf"(?<![{w}]){re.escape(alt)}(?![{w}])"
        )


def load_rules() -> list[Rule]:
    rules: list[Rule] = []
    with MAPPING.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            if not row.get("alt"):
                continue
            rules.append(Rule(row["alt"].strip(), row["neu"].strip(),
                              row["typ"].strip(), len(rules)))
    # Pass 1 immer längster Suchbegriff zuerst (Falle 2).
    rules.sort(key=lambda r: -len(r.alt))
    return rules


# ---------------------------------------------------------------------------
# Der eigentliche Ersetzer: Zwei-Pass über Platzhalter
# ---------------------------------------------------------------------------

def replace(text: str, rules: list[Rule], structured: bool) -> tuple[str, Counter]:
    """Ersetzt alle Altnamen/ids. `structured` erlaubt die mehrdeutigen Namen."""
    hits: Counter = Counter()
    used: list[Rule] = []
    for rule in rules:                                    # längster zuerst
        if rule.structured_only and not structured:
            continue
        new_text, n = rule.regex.subn(rule.token, text)
        if n:
            hits[rule.alt] += n
            used.append(rule)
            text = new_text
    for rule in used:                                     # Pass 2
        text = text.replace(rule.token, rule.neu)
    return text, hits


def replace_field(value, rules, structured=True):
    if isinstance(value, str):
        new, hits = replace(value, rules, structured)
        return new, hits
    return value, Counter()


# ---------------------------------------------------------------------------
# Handler je Dateityp
# ---------------------------------------------------------------------------

def handle_csv_columns(path: Path, rules, columns, rewrite_descriptions=False):
    """CSV spaltenscharf. Gibt (neuer_text, hits) zurück."""
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(text.splitlines(True))
    fieldnames = reader.fieldnames or []
    rows = list(reader)
    hits: Counter = Counter()

    for row in rows:
        for col in columns:
            if col in row and row[col]:
                row[col], h = replace_field(row[col], rules)
                hits += h
        if rewrite_descriptions and row.get("id") in NEW_DESCRIPTIONS:
            new_desc = NEW_DESCRIPTIONS[row["id"]]
            if row.get("description") != new_desc:
                row["description"] = new_desc
                hits["<description neu>"] += 1

    sio = io.StringIO(newline="")
    writer = csv.DictWriter(sio, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    result = sio.getvalue()
    if bom:
        result = "﻿" + result
    return result, hits


def _dump_like(original: str, data) -> str:
    """Gleiche Formatierung wie die Vorlage, damit der Diff nur die Namen zeigt."""
    compact = "\n" not in original.strip()
    if compact:
        out = json.dumps(data, ensure_ascii=False, separators=(", ", ": "))
    else:
        out = json.dumps(data, ensure_ascii=False, indent=2)
    return out + "\n" if original.endswith("\n") else out


_GEOJSON_PROP_RE = re.compile(
    r'"(?P<key>' + "|".join(GEOJSON_PROPERTIES) + r')":(?P<sp>\s*)"(?P<val>[^"\\]*)"'
)


def handle_geojson(path: Path, rules):
    """Nur die Properties `id` und `region`, direkt im Text.

    Bewusst kein json.load/dump-Umweg: regionen_polygone_mapped.geojson liegt
    als eine Zeile je Feature vor. Ein Neu-Serialisieren würde die Datei
    komplett umbrechen und den Diff unlesbar machen — man sähe nicht mehr, dass
    nur Namen geändert wurden. Die Property `name` (Landmarke wie "Ebenalp")
    bleibt unangetastet.
    """
    original = path.read_text(encoding="utf-8")
    hits: Counter = Counter()

    def _sub(m):
        new_val, h = replace(m.group("val"), rules, structured=True)
        hits.update(h)
        return f'"{m.group("key")}":{m.group("sp")}"{new_val}"'

    new_text = _GEOJSON_PROP_RE.sub(_sub, original)
    json.loads(new_text)                    # muss gültiges JSON bleiben
    return new_text, hits


def _walk_json(obj, rules, hits):
    """Rekursiv: Dict-Schlüssel UND String-Werte. Archiv schlüsselt auf ids."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            nk, h = replace_field(k, rules)
            hits += h
            out[nk] = _walk_json(v, rules, hits)
        return out
    if isinstance(obj, list):
        return [_walk_json(v, rules, hits) for v in obj]
    if isinstance(obj, str):
        nv, h = replace_field(obj, rules)
        hits += h
        return nv
    return obj


def handle_json_deep(path: Path, rules):
    original = path.read_text(encoding="utf-8")
    hits: Counter = Counter()
    data = _walk_json(json.loads(original), rules, hits)
    return _dump_like(original, data), hits


def handle_jsonl_deep(path: Path, rules):
    original = path.read_text(encoding="utf-8")
    hits: Counter = Counter()
    lines = []
    for line in original.splitlines():
        if not line.strip():
            lines.append(line)
            continue
        obj = _walk_json(json.loads(line), rules, hits)
        lines.append(json.dumps(obj, ensure_ascii=False))
    out = "\n".join(lines)
    return out + "\n" if original.endswith("\n") else out, hits


def handle_text(path: Path, rules, allow_ambiguous=False):
    text = path.read_text(encoding="utf-8")
    new, hits = replace(text, rules, structured=allow_ambiguous)
    return new, hits


def handler_for(rel: str):
    if rel in SPOT_CSVS:
        return lambda p, r: handle_csv_columns(p, r, SPOT_CSV_COLUMNS)
    if rel == REGIONEN_CSV:
        return lambda p, r: handle_csv_columns(p, r, REGIONEN_CSV_COLUMNS,
                                               rewrite_descriptions=True)
    cols = csv_columns_for(rel)
    if cols:
        return lambda p, r: handle_csv_columns(p, r, cols)
    if rel in GEOJSONS:
        return handle_geojson
    if rel.endswith(".json") and rel.startswith(DEEP_JSON_PREFIXES):
        return handle_json_deep
    if rel.endswith(".jsonl"):
        return handle_jsonl_deep
    if rel.startswith(AMBIGUOUS_ALLOWED):
        return lambda p, r: handle_text(p, r, allow_ambiguous=True)
    return handle_text


def is_flat_text(rel: str) -> bool:
    """Fliesstext ohne Feldstruktur — dort ist "Ostschweiz" mehrdeutig."""
    if csv_columns_for(rel) or rel in SPOT_CSVS or rel == REGIONEN_CSV:
        return False
    if rel in GEOJSONS or rel.endswith(".jsonl"):
        return False
    if rel.endswith(".json") and rel.startswith(DEEP_JSON_PREFIXES):
        return False
    return not rel.startswith(AMBIGUOUS_ALLOWED)


# ---------------------------------------------------------------------------
# Dateiauswahl
# ---------------------------------------------------------------------------

def is_excluded(rel: str) -> bool:
    parts = Path(rel).parts
    if any(p in EXCLUDE_DIRS for p in parts):
        return True
    if rel in EXCLUDE_PATHS:
        return True
    p = Path(rel)
    for pattern in EXCLUDE_GLOBS:
        if p.match(pattern):
            return True
    return False


def candidate_files(rules, only_paths=None) -> list[tuple[str, Path]]:
    alts = [r.alt for r in rules]
    needles = [a.encode("utf-8") for a in alts]
    found = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if is_excluded(rel):
            continue
        if only_paths and not rel.startswith(tuple(only_paths)):
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if any(n in raw for n in needles):
            found.append((rel, path))
    return sorted(found)


# ---------------------------------------------------------------------------
# Ambiguitäts-Bericht
# ---------------------------------------------------------------------------

def show_ambiguous(rules):
    risky = [r for r in rules if r.structured_only]
    print(f"\nMehrdeutige Namen ({', '.join(r.alt for r in risky)}) in Fliesstext-"
          f"Dateien — werden NICHT automatisch ersetzt:\n")
    total = 0
    for rel, path in candidate_files(rules):
        if not is_flat_text(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        # zuerst die längeren Namen ausblenden, sonst zählt "Alpstein / Ostschweiz" mit
        masked = text
        for r in rules:
            if not r.structured_only:
                masked = r.regex.sub(" ", masked)
        for r in risky:
            for m in r.regex.finditer(masked):
                line = masked.count("\n", 0, m.start()) + 1
                ctx = masked[max(0, m.start() - 60):m.end() + 60].replace("\n", " ")
                print(f"  {rel}:{line}  …{ctx.strip()}…")
                total += 1
    print(f"\n  {total} Fundstellen. Entscheiden: Landesteil (stehen lassen) "
          f"oder unsere Region (von Hand nachziehen).\n")


# ---------------------------------------------------------------------------
# Hauptlauf
# ---------------------------------------------------------------------------

def run(stages, apply_changes, quiet=False, only_paths=None):
    rules = load_rules()
    files = candidate_files(rules, only_paths)
    per_stage: dict[str, list] = {"A": [], "B": [], "C": []}
    for rel, path in files:
        per_stage[stage_of(rel)].append((rel, path))

    grand_hits: Counter = Counter()
    grand_files = 0
    grand_changed = 0

    for stage in ("A", "B", "C"):
        if stage not in stages:
            continue
        entries = per_stage[stage]
        stage_hits: Counter = Counter()
        changed = 0
        print(f"\n{'='*72}\nSTUFE {stage} — {len(entries)} Dateien mit Treffern")
        print("=" * 72)
        for rel, path in entries:
            handler = handler_for(rel)
            try:
                new_text, hits = handler(path, rules)
            except Exception as exc:                       # noqa: BLE001
                print(f"  !! {rel}: {type(exc).__name__}: {exc}")
                continue
            if not hits:
                if not quiet:
                    print(f"  -- {rel}: keine ersetzbaren Treffer "
                          f"(nur mehrdeutige oder geschützte Spalten)")
                continue
            changed += 1
            stage_hits += hits
            n = sum(hits.values())
            print(f"  {'->' if apply_changes else '  '} {rel}: {n} Ersetzungen")
            if not quiet and len(hits) <= 8:
                for alt, cnt in hits.most_common():
                    print(f"        {alt} -> {cnt}x")
            if apply_changes:
                backup = path.with_suffix(path.suffix + ".pre_rename")
                if backup.exists():
                    # Die Migration ist NICHT idempotent: "Freiburger Voralpen"
                    # und "Berner Oberland" sind zugleich Alt- und Neuname
                    # (Kette). Ein zweiter Lauf würde sie eine Stufe weiter
                    # schieben und Regionen verschmelzen.
                    print(f"      ÜBERSPRUNGEN — {backup.name} existiert bereits, "
                          f"die Datei wurde schon migriert")
                    changed -= 1
                    stage_hits -= hits
                    continue
                shutil.copy2(path, backup)
                if rel in SPOT_CSVS:
                    path.write_text(new_text.lstrip("﻿"), encoding="utf-8-sig",
                                    newline="")
                else:
                    path.write_text(new_text, encoding="utf-8", newline="\n")
        print(f"\n  Stufe {stage}: {changed} von {len(entries)} Dateien betroffen, "
              f"{sum(stage_hits.values())} Ersetzungen")
        grand_hits += stage_hits
        grand_files += len(entries)
        grand_changed += changed

    print(f"\n{'='*72}")
    print(f"GESAMT: {grand_changed} Dateien, {sum(grand_hits.values())} Ersetzungen"
          f"  [{'GESCHRIEBEN' if apply_changes else 'DRY-RUN, nichts geändert'}]")
    print("=" * 72)
    print("\nTop-Ersetzungen:")
    for alt, cnt in grand_hits.most_common(25):
        print(f"  {cnt:>7}x  {alt}")
    return grand_hits


def verify(rules):
    """Restsuche: diese Altnamen dürfen nach der Migration nicht mehr vorkommen.

    Ausgenommen sind die Namen der Kette, die zugleich Ziel einer anderen Zeile
    sind ("Freiburger Voralpen", "Berner Oberland" und ihre ids). Sie stehen
    nach der Migration völlig zu Recht im Bestand — nur meinen sie dann etwas
    anderes. Sie hier zu melden wäre ein Fehlalarm.
    """
    targets = {r.neu for r in rules}
    chain = sorted(r.alt for r in rules if r.alt in targets)
    print(f"\nRestsuche in genau dem Umfang, den die Migration anfasst "
          f"(spaltenscharf, geschützte Spalten bleiben aussen vor).\n"
          f"Ausgenommen als Fehlalarm: {', '.join(chain)}\n")
    rest: Counter = Counter()
    for rel, path in candidate_files(rules):
        handler = handler_for(rel)
        try:
            _, hits = handler(path, rules)
        except Exception as exc:                           # noqa: BLE001
            print(f"  !! {rel}: {type(exc).__name__}: {exc}")
            continue
        for alt, n in hits.items():
            if alt in targets or alt.startswith("<"):
                continue
            rest[alt] += n
            print(f"  {rel}: {n}x {alt}")
    if not rest:
        print("  0 Treffer — sauber.")
    else:
        print(f"\n  {sum(rest.values())} Reste in {len(rest)} verschiedenen Namen.")
    return rest


def main():
    try:                                   # Windows-Konsole ist cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", action="append", choices=["A", "B", "C"],
                    help="nur diese Stufe(n); default alle")
    ap.add_argument("--apply", action="store_true", help="wirklich schreiben")
    ap.add_argument("--verify", action="store_true", help="nur Restsuche")
    ap.add_argument("--show-ambiguous", action="store_true")
    ap.add_argument("--paths", action="append", metavar="PREFIX",
                    help="nur Pfade unter diesem Prefix (z.B. validation/gewitter). "
                         "Noetig fuer einen zweiten --apply-Lauf, etwa auf dem "
                         "Server fuer die gitignorierten Daten")
    ap.add_argument("--force", action="store_true",
                    help="Sperre des Marker-Files uebergehen (fast nie richtig)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not MAPPING.exists():
        sys.exit(f"Mapping fehlt: {MAPPING}")

    rules = load_rules()
    print(f"Mapping: {len(rules)} Regeln "
          f"({sum(1 for r in rules if r.typ=='name')} Namen, "
          f"{sum(1 for r in rules if r.typ=='variante')} Varianten, "
          f"{sum(1 for r in rules if r.typ=='id')} ids)")

    if args.show_ambiguous:
        show_ambiguous(rules)
        return
    if args.verify:
        verify(rules)
        return

    if args.apply and DONE_MARKER.exists() and not args.paths and not args.force:
        marker = DONE_MARKER.relative_to(ROOT)
        sys.exit("\n".join([
            "",
            f"ABGEBROCHEN: {marker} existiert - der versionierte Bestand ist",
            "bereits migriert.",
            "",
            "Die Migration ist NICHT wiederholbar: 'Freiburger Voralpen' und",
            "'Berner Oberland' sind zugleich Alt- und Neuname. Ein zweiter Lauf",
            "schoebe sie eine Stufe weiter und liesse Regionen verschmelzen.",
            "",
            "Fuer die gitignorierten Server-Daten den Umfang eingrenzen:",
            "  --paths validation/gewitter --paths validation/fronten \\",
            "  --paths data/labeled_examples.jsonl --apply",
            "",
        ]))

    run(set(args.stage or ["A", "B", "C"]), args.apply, args.quiet, args.paths)


if __name__ == "__main__":
    main()
