"""A/B-Vergleich zweier Analyse-Modelle auf den Test-Spots.

Fragestellung: Bleibt die SICHERHEITS-Bewertung gleich, wenn ANALYSIS_MODEL
gewechselt wird?

Methode (sauber kontrolliert):
- Wetter wird EINMAL geholt → beide Modelle sehen exakt dieselbe Datenbasis.
- Dann je Modell die volle LLM-Analyse, Output pro LAUF weggesichert.
- Diff NUR auf safety_status.
- Gefaehrliche Richtung wird separat gezaehlt: Referenz=not_safe, Kandidat=safe
  → das Modell wuerde einen unsicheren Tag freigeben. Das ist das K.O.-Kriterium.

WICHTIG: temp=0.2 ist NICHT deterministisch. Ein Teil der Flips ist Jitter, kein
Modell-Signal. Darum vorher/nachher eine Baseline mit ZWEIMAL demselben Modell
fahren und die Flip-Zahl des A/B daran messen (A/B 27.07: 91.4% vs 95.1% Baseline
→ Differenz nicht vom Rauschen unterscheidbar).

Aufruf (28 Spots, ~$1 gesamt):
    WINGCAST_SPOT_CSV=test python cost_testing/ab_model_compare.py
    # optional eigene Modelle:
    WINGCAST_SPOT_CSV=test python cost_testing/ab_model_compare.py deepseek-v4-flash deepseek-v4-pro
    # Jitter-Baseline (zweimal dasselbe Modell):
    WINGCAST_SPOT_CSV=test python cost_testing/ab_model_compare.py deepseek-v4-flash deepseek-v4-flash

Aendert NICHTS dauerhaft: die Modell-Umstellung passiert nur im Speicher
(apply_overrides), data/config_overrides.json bleibt unberuehrt.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ab_compare")

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env")
except ImportError:
    pass

# Referenz-Modell zuerst, Kandidat zweitens. Default = Jitter-Baseline
# (deepseek-chat ist seit 24.07.2026 abgeschaltet und taugt nicht mehr als Referenz).
DEFAULT_MODELS = ["deepseek-v4-flash", "deepseek-v4-flash"]
OUT_DIR = _REPO / "cost_testing"


def _safety_status(entry: dict) -> str:
    """Robust gegen verschachtelte ('safety'-Subdict) und flache Form."""
    if not isinstance(entry, dict):
        return "?"
    if isinstance(entry.get("safety"), dict):
        return entry["safety"].get("safety_status", "?")
    return entry.get("safety_status", "?")


def _flatten(analyses: dict) -> dict[str, str]:
    """{spot|date: safety_status} aus dem spot_analyses-Format."""
    out: dict[str, str] = {}
    for spot, days in analyses.items():
        for date, entry in days.items():
            out[f"{spot}|{date}"] = _safety_status(entry)
    return out


def _run_one(eng, model: str, run_idx: int) -> dict:
    """Setzt Modell, faehrt die Analyse, sichert Output, liefert Metriken.

    run_idx (1=Referenz, 2=Kandidat) landet im Dateinamen: bei identischen
    Modellnamen (Jitter-Messung) wuerden Ref und Kandidat sonst in dieselbe
    Datei schreiben und der Diff verglich die zweite Datei mit sich selbst.
    """
    import config_overrides
    changed = config_overrides.apply_overrides({"ANALYSIS_MODEL": model})
    eng.reload_llm_clients()
    logger.info(">>> Lauf %d mit ANALYSIS_MODEL=%s (provider=%s, effektiv=%s) changed=%s",
                run_idx, model, eng.analysis_provider, eng.analysis_model, changed)

    done = {}
    last_error = None
    for evt in eng.run_all_analyses_stream():
        ev = (evt or {}).get("event")
        data = (evt or {}).get("data", {}) or {}
        if ev == "phase":
            logger.info("  PHASE: %s", data.get("phase"))
        elif ev == "done":
            done = data
        elif ev == "error":
            last_error = data.get("message")
            logger.error("  ERROR-Event: %s", last_error)
    if not done:
        raise RuntimeError(f"Lauf ({model}) ohne 'done' (last_error={last_error})")

    # NICHT hart auf spot_analyses.json: die Engine schreibt sprachabhaengig
    # (EN -> spot_analyses_en.json). Frueher wurde deshalb der eingefrorene
    # DE-Altbestand mit sich selbst verglichen -> falsche 100% PASS.
    src = Path(eng.analyses_file)
    if not src.exists():
        raise RuntimeError(f"Analyse-Output nicht gefunden: {src}")
    tag = model.replace("/", "_")
    dst = OUT_DIR / f"ab_{run_idx}_{tag}.json"
    shutil.copy(src, dst)
    logger.info("  gesichert -> %s  (Quelle %s, calls=%s, est_usd=%s)",
                dst.name, src.name, done.get("total_calls"), done.get("est_usd"))
    return {"model": model, "file": dst, "done": done}


def _report(ref: dict, cand: dict) -> int:
    ref_map = _flatten(json.load(open(ref["file"], encoding="utf-8")))
    cand_map = _flatten(json.load(open(cand["file"], encoding="utf-8")))
    keys = sorted(set(ref_map) & set(cand_map))

    agree = 0
    flips = []          # alle safety_status-Abweichungen
    dangerous = []      # ref=not_safe -> cand=safe (Freigabe eines unsicheren Tags)
    FLYABLE = {"safe", "conditional"}
    for k in keys:
        a, b = ref_map[k], cand_map[k]
        if a == b:
            agree += 1
            continue
        flips.append((k, a, b))
        if a == "not_safe" and b in FLYABLE:
            dangerous.append((k, a, b))

    n = len(keys)
    pct = 100.0 * agree / n if n else 0.0
    rm, cm = ref["model"], cand["model"]
    ref_usd = ref["done"].get("est_usd") or 0
    cand_usd = cand["done"].get("est_usd") or 0
    saving = (1 - cand_usd / ref_usd) * 100 if ref_usd else 0

    print("\n" + "=" * 64)
    print(f"  A/B SAFETY-VERGLEICH   {rm}  (Ref)  vs  {cm}  (Kandidat)")
    print("=" * 64)
    print(f"  Spot-Tage verglichen:        {n}")
    print(f"  safety_status identisch:     {agree}/{n}  ({pct:.1f}%)")
    print(f"  Abweichungen gesamt:         {len(flips)}")
    print(f"  GEFAEHRLICHE Flips (not_safe->fliegbar): {len(dangerous)}")
    print(f"  Kosten Ref:   ${ref_usd:.3f}   Kandidat: ${cand_usd:.3f}   "
          f"Ersparnis: {saving:.0f}%")
    print("-" * 64)

    if flips:
        print("  Alle Abweichungen (Ref -> Kandidat):")
        for k, a, b in flips:
            mark = "  <-- GEFAEHRLICH" if (a == "not_safe" and b in FLYABLE) else ""
            print(f"    {k:42s} {a:12s} -> {b:12s}{mark}")
    else:
        print("  Keine einzige Safety-Abweichung. ")
    print("=" * 64)

    # Urteil
    ok = (pct >= 98.0) and (len(dangerous) == 0)
    if ok:
        print(f"  URTEIL: PASS — {cm} ist sicherheits-aequivalent. "
              f"Umstellung empfohlen (~{saving:.0f}% guenstiger).")
    elif dangerous:
        print(f"  URTEIL: FAIL — {len(dangerous)} gefaehrliche Freigaben. "
              f"Safety auf {rm} lassen, nur Flyability auf {cm}.")
    else:
        print(f"  URTEIL: GRENZWERTIG — {pct:.1f}% < 98%. Abweichungen oben "
              f"einzeln pruefen, bevor umgestellt wird.")
    print("=" * 64 + "\n")
    return 0 if ok else 3


def main() -> int:
    models = sys.argv[1:3] if len(sys.argv) >= 3 else DEFAULT_MODELS
    if os.environ.get("WINGCAST_SPOT_CSV") != "test":
        logger.warning("WINGCAST_SPOT_CSV != 'test' — Lauf nutzt die VOLLE Spot-Liste "
                       "(teuer!). Fuer den guenstigen A/B: export WINGCAST_SPOT_CSV=test")

    import config
    import config_overrides
    config_overrides.init()
    logger.info("Spot-CSV: %s", config.CSV_PATH.name)

    from chat_engine import WingcastEngine
    eng = WingcastEngine()
    original = config.get_model(config.ANALYSIS_PROVIDER, "analysis")

    logger.info("=== Schritt 1: Wetter EINMAL holen (gemeinsame Basis) ===")
    eng.refresh_weather()

    try:
        logger.info("=== Schritt 2: Referenz-Lauf (%s) ===", models[0])
        ref = _run_one(eng, models[0], 1)
        logger.info("=== Schritt 3: Kandidat-Lauf (%s) ===", models[1])
        cand = _run_one(eng, models[1], 2)
    finally:
        config_overrides.apply_overrides({"ANALYSIS_MODEL": original})
        eng.reload_llm_clients()
        logger.info("Modell im Speicher auf Original (%s) zurueckgesetzt.", original)

    return _report(ref, cand)


if __name__ == "__main__":
    sys.exit(main())
