#!/usr/bin/env python3
"""Sync-Waechter fuer die zweisprachigen Skill-/Prompt-Bausteine (DE -> EN).

PROBLEM, das dieses Skript loest
--------------------------------
Die EN-Versionen einiger Prompt-Bausteine sind HAND-Uebersetzungen der
deutschen Originale. Aendert jemand das deutsche Original, bleibt die englische
Datei still auf dem alten Stand ("Drift") — niemand merkt es, bis ein
englischer Nutzer veraltete Inhalte liest. Es gibt keine Auto-Uebersetzung.

Dieses Skript macht die Drift SICHTBAR: Es merkt sich pro EN-Datei den
SHA256-Hash der deutschen Quelle, aus der sie zuletzt synchronisiert wurde
(in skills/i18n_sync.json). Beim Pruefen vergleicht es den gespeicherten Hash
mit dem AKTUELLEN Hash der DE-Quelle:
  - gleich   -> OK (EN ist auf dem Stand der DE-Quelle)
  - anders   -> DRIFT (DE wurde geaendert, EN wurde NICHT nachgezogen)

Damit beantwortet ein Lauf die Frage "welche Bloecke muss ich in BEIDEN
Sprachen anfassen?" eindeutig.

Pairing-Konventionen (identisch zu prompts._load_shared / _load_skill)
----------------------------------------------------------------------
  skills/shared/en/<rel>  <->  skills/shared/de/<rel>
  skills/en/<file>        <->  skills/<file>
Neue EN-Dateien werden automatisch erkannt (kein manueller Eintrag noetig).

Workflow
--------
  python scripts/check_i18n_sync.py            # pruefen (exit 1 bei Drift)
  python scripts/check_i18n_sync.py --update    # nach dem Nachziehen: Stand stempeln

Typischer Ablauf bei einer Aenderung am deutschen Wording:
  1. DE-Datei aendern.
  2. `--update`? NEIN. Erst pruefen -> Skript zeigt die betroffene(n) EN-Datei(en).
  3. EN-Datei(en) inhaltlich nachziehen.
  4. `--update` -> stempelt die neuen DE-Hashes (Drift verschwindet).

Pre-Deploy-Gate: Exit-Code != 0 bei Drift/Problemen -> in deploy.sh einhaengbar.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"
MANIFEST = SKILLS / "i18n_sync.json"

# (EN-Wurzel, DE-Wurzel) — die DE-Quelle einer EN-Datei ergibt sich aus
# de_root / <pfad-relativ-zur-en_root>.
PAIR_ROOTS = [
    (SKILLS / "shared" / "en", SKILLS / "shared" / "de"),
    (SKILLS / "en", SKILLS),
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    """Repo-relativer POSIX-Pfad (portabel im Manifest)."""
    return path.relative_to(REPO).as_posix()


def discover_pairs() -> list[dict]:
    """Findet alle EN-Dateien und ihre DE-Quelle nach Konvention.

    Returns Liste von dicts: {en, de, de_exists}. en/de sind repo-relative Pfade.
    """
    pairs: list[dict] = []
    for en_root, de_root in PAIR_ROOTS:
        if not en_root.is_dir():
            continue
        for en_path in sorted(en_root.rglob("*.md")):
            de_path = de_root / en_path.relative_to(en_root)
            pairs.append({
                "en": _rel(en_path),
                "de": _rel(de_path),
                "de_exists": de_path.is_file(),
                "_de_abs": de_path,
            })
    return pairs


def load_manifest() -> dict:
    if MANIFEST.is_file():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"_doc": "", "pairs": {}}


def save_manifest(stamps: dict) -> None:
    data = {
        "_doc": ("Pro EN-Uebersetzung der SHA256-Hash der DE-Quelle beim letzten Sync. "
                 "Pruefen: python scripts/check_i18n_sync.py ; Stempeln nach Nachziehen: --update. "
                 "Schluessel = EN-Pfad (repo-relativ)."),
        "pairs": dict(sorted(stamps.items())),
    }
    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_check() -> int:
    pairs = discover_pairs()
    manifest = load_manifest()
    stamps = manifest.get("pairs", {})

    ok, drift, untracked, missing_de = [], [], [], []
    for p in pairs:
        en, de = p["en"], p["de"]
        if not p["de_exists"]:
            missing_de.append(p)
            continue
        cur = _sha256(p["_de_abs"])
        rec = stamps.get(en)
        if rec is None:
            untracked.append(p)
        elif rec != cur:
            drift.append(p)
        else:
            ok.append(p)

    # Verwaiste Manifest-Eintraege (EN-Datei existiert nicht mehr)
    known_en = {p["en"] for p in pairs}
    stale = [en for en in stamps if en not in known_en]

    print(f"i18n-Sync-Check  ({len(pairs)} EN-Dateien)\n" + "=" * 50)
    if ok:
        print(f"\n✅ AKTUELL ({len(ok)}):")
        for p in ok:
            print(f"   {p['en']}")
    if drift:
        print(f"\n\U0001f534 DRIFT — DE geaendert, EN NICHT nachgezogen ({len(drift)}):")
        for p in drift:
            print(f"   {p['en']}")
            print(f"      DE-Quelle: {p['de']}")
    if untracked:
        print(f"\n⚠️  NICHT GESTEMPELT — EN ohne Manifest-Eintrag ({len(untracked)}):")
        for p in untracked:
            print(f"   {p['en']}  (DE: {p['de']})")
        print("   -> nach Pruefung der EN-Aktualitaet: --update")
    if missing_de:
        print(f"\n⚠️  DE-QUELLE FEHLT — EN ohne deutsches Original ({len(missing_de)}):")
        for p in missing_de:
            print(f"   {p['en']}  (erwartet: {p['de']})")
    if stale:
        print(f"\n⚠️  VERWAISTER EINTRAG — Manifest kennt nicht-existente EN-Datei ({len(stale)}):")
        for en in stale:
            print(f"   {en}  -> mit --update bereinigt")

    problems = len(drift) + len(untracked) + len(missing_de) + len(stale)
    print("\n" + "=" * 50)
    if problems == 0:
        print("Alles synchron. ✅")
        return 0
    print(f"{problems} Punkt(e) zu klaeren (siehe oben). Exit 1.")
    return 1


def cmd_update() -> int:
    """Stempelt die aktuellen DE-Hashes fuer alle vorhandenen Paare.

    NUR ausfuehren, wenn die EN-Dateien inhaltlich auf dem Stand der DE-Quellen
    sind — der Stempel bedeutet 'EN ist mit dieser DE-Version synchron'.
    """
    pairs = discover_pairs()
    stamps = {}
    skipped = []
    for p in pairs:
        if not p["de_exists"]:
            skipped.append(p)
            continue
        stamps[p["en"]] = _sha256(p["_de_abs"])
    save_manifest(stamps)
    print(f"Manifest gestempelt: {len(stamps)} Paare -> {_rel(MANIFEST)}")
    if skipped:
        print(f"⚠️  {len(skipped)} EN-Datei(en) ohne DE-Quelle uebersprungen:")
        for p in skipped:
            print(f"   {p['en']}  (erwartet: {p['de']})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="DE->EN Prompt-Baustein Sync-Waechter")
    ap.add_argument("--update", action="store_true",
                    help="Aktuelle DE-Hashes stempeln (nach dem Nachziehen der EN-Dateien).")
    args = ap.parse_args()
    return cmd_update() if args.update else cmd_check()


if __name__ == "__main__":
    sys.exit(main())
