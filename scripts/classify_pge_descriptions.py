"""LLM-Klassifikation der PGE takeoff_description-Texte.

Liest data/_pge_ch_snapshot.json, klassifiziert jeden non-empty takeoff_description
via DeepSeek in {flug, sicherheit}, cached in data/pge_description_classifications.json
und schreibt das Ergebnis in data/fluggebiete_pge.csv (Spalten bemerkungen_flug,
bemerkungen_sicherheit).

Resumable: bereits klassifizierte PGE-IDs werden uebersprungen.
Aufruf: PYTHONIOENCODING=utf-8 python scripts/classify_pge_descriptions.py
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from llm_client import build_client  # noqa: E402

PGE_PATH = ROOT / "data" / "_pge_ch_snapshot.json"
CSV_PATH = ROOT / "data" / "fluggebiete_pge.csv"
CACHE_PATH = ROOT / "data" / "pge_description_classifications.json"

PROVIDER = "deepseek"
MODEL = config.get_model(PROVIDER, "analysis")  # deepseek-v4-flash

SYSTEM_PROMPT = """Du klassifizierst englische Paragliding-Startplatz-Beschreibungen \
fuer eine deutschsprachige Wetter-Bewertungs-App.

Output GENAU als JSON-Objekt mit zwei Feldern:
{
  "flug": "<flug-/qualitaetsrelevante Infos auf Deutsch>",
  "sicherheit": "<sicherheitsrelevante Hinweise auf Deutsch>"
}

Regeln:
- Auf Deutsch zusammenfassen, NICHT 1:1 uebersetzen. Knapp, 1-3 Saetze pro Feld.
- "flug" = nuetzlich fuer Flug-Planung: Tageszeit (morgens/nachmittags), Saison, \
beste Windbedingungen, Aufstiegsweg, Landeplatz, Rampe/Wiese, Thermik-Hinweise.
- "sicherheit" = warnt vor Gefahren oder Restriktionen: Hindernisse, Hochspannung, \
Rotor/Turbulenz, Steinschlag, Lawinen, Wildtier-/Naturschutzzonen, Flugverbote, \
Eigentums-Konflikte, gefaehrliche Landeplaetze, Personenfreigaben.
- Wenn eine Kategorie nichts enthaelt: leerer String "".
- Keine Spekulation, nur was im Text steht.
- Niemals beide Felder mit dem gleichen Satz fuellen.
"""


def load_cache() -> dict[str, dict[str, str]]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_cache(cache: dict[str, dict[str, str]]) -> None:
    tmp = CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CACHE_PATH)


def classify(client, description: str) -> dict[str, str]:
    """Einzeln klassifizieren. Liefert {"flug": "...", "sicherheit": "..."}."""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": description},
        ],
        temperature=0.1,
        max_tokens=1024,
        response_format={"type": "json_object"},
    )
    content = (response.choices[0].message.content or "").strip()
    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        # Fence-Stripping fallback
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:].strip()
            obj = json.loads(content)
        else:
            raise
    flug = (obj.get("flug") or "").strip()
    sicherheit = (obj.get("sicherheit") or "").strip()
    return {"flug": flug, "sicherheit": sicherheit}


def classify_all():
    pge = json.loads(PGE_PATH.read_text(encoding="utf-8"))
    features = pge["features"]

    # Sammle Features mit description
    todo = []
    for f in features:
        desc = (f["properties"].get("takeoff_description") or "").strip()
        if desc:
            todo.append((str(f.get("id")), f["properties"].get("name", ""), desc))

    cache = load_cache()
    print(f"PGE features mit Description: {len(todo)}")
    print(f"Bereits im Cache:             {sum(1 for tid, _, _ in todo if tid in cache)}")
    print(f"Provider/Modell:              {PROVIDER}/{MODEL}")
    print()

    client = build_client(PROVIDER, config.get_api_key(PROVIDER))
    if client is None:
        print(f"FEHLER: Konnte {PROVIDER}-Client nicht initialisieren. API-Key gesetzt?")
        sys.exit(1)

    new_done = 0
    failed = 0
    t0 = time.time()
    for i, (pid, name, desc) in enumerate(todo, 1):
        if pid in cache:
            continue
        try:
            result = classify(client, desc)
        except Exception as e:
            failed += 1
            print(f"  [{i:>3}/{len(todo)}] FAIL {pid} {name[:30]}: {type(e).__name__}: {e}")
            continue
        cache[pid] = result
        new_done += 1
        if new_done % 5 == 0:
            save_cache(cache)
        flug_short = result["flug"][:50].replace("\n", " ")
        sich_short = result["sicherheit"][:50].replace("\n", " ")
        print(f"  [{i:>3}/{len(todo)}] OK   {pid:>6} {name[:28]:<28} F:{flug_short:<50} | S:{sich_short}")
    save_cache(cache)
    dt = time.time() - t0
    print()
    print(f"Done. {new_done} new classifications, {failed} failures in {dt:.1f}s")
    return cache


def write_to_csv(cache: dict[str, dict[str, str]]):
    """Schreibt cache in fluggebiete_pge.csv. Matching ueber lat/lon (5 decimals)."""
    pge = json.loads(PGE_PATH.read_text(encoding="utf-8"))
    # build coord -> classification map
    coord_map = {}
    for f in pge["features"]:
        pid = str(f.get("id"))
        if pid not in cache:
            continue
        lon, lat = f["geometry"]["coordinates"]
        key = (round(lat, 5), round(lon, 5))
        coord_map[key] = cache[pid]

    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
    matched = 0
    for r in rows:
        try:
            key = (round(float(r["latitude"]), 5), round(float(r["longitude"]), 5))
        except ValueError:
            continue
        cls = coord_map.get(key)
        if cls:
            r["bemerkungen_flug"] = cls["flug"]
            r["bemerkungen_sicherheit"] = cls["sicherheit"]
            matched += 1

    with CSV_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {matched} classified rows -> {CSV_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    cache = classify_all()
    write_to_csv(cache)
