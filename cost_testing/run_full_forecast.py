"""Kompletter Forecast-Lauf gegen einen frei waehlbaren Provider — isoliert.

Zweck (16.08.2026): den Anbietervergleich DeepSeek vs. DeepInfra nicht an
veralteten Goldfaellen entscheiden, sondern an einem echten, vollstaendigen
Tages-Forecast auf den aktuellen Wetterdaten.

Sicherheit: nutzt `engine.test_mode.run_test_analyses_stream`, das
  - die Eingabe aus dem eingefrorenen Snapshot `data/mocks/wetterdaten.json` zieht,
  - die Ausgabe nach `data/test_runs/latest/` umleitet,
  - und den Engine-State danach wiederherstellt.
Produktive `spot_analyses*.json` werden NICHT angefasst. Der Lauf holt auch
kein neues Wetter — sonst waere der Vergleich gegen den Server-Lauf wertlos,
weil beide Seiten unterschiedliche Eingaben haetten.

Voraussetzung:
    python -c "from engine import test_mode; test_mode.freeze_current_weather('complete')"

Aufruf:
    ANALYSIS_PROVIDER=deepinfra python cost_testing/run_full_forecast.py
    ANALYSIS_PROVIDER=deepinfra python cost_testing/run_full_forecast.py --days 1
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def main() -> int:
    ap = argparse.ArgumentParser(description="Kompletter Forecast gegen einen Provider")
    ap.add_argument("--provider", default=None,
                    help="ueberschreibt ANALYSIS_PROVIDER (deepseek | deepinfra | ...)")
    ap.add_argument("--days", type=int, default=None, help="nur N Vorhersagetage")
    a = ap.parse_args()

    import config
    import config_overrides
    config_overrides.init()

    # WICHTIG: erst NACH config_overrides.init() setzen. Das Overlay aus
    # data/config_overrides.json setzt ANALYSIS_MODEL und leitet daraus den
    # Provider ab — es ueberstimmt damit jede ENV-Variable. Genau daran ist am
    # 16.08. ein Lauf stillschweigend auf DeepSeek gelandet statt auf DeepInfra.
    gewuenscht = a.provider or os.environ.get("ANALYSIS_PROVIDER") or config.ANALYSIS_PROVIDER
    config.ANALYSIS_PROVIDER = gewuenscht
    prov = config.ANALYSIS_PROVIDER
    modell = config.get_model(prov, "analysis")

    if not config.get_api_key(prov):
        print(f"FEHLER: kein API-Key fuer Provider '{prov}'.")
        return 2

    from engine import test_mode
    meta = test_mode.frozen_weather_meta()
    if not meta:
        print("FEHLER: kein eingefrorener Wetter-Snapshot. Vorher freeze_current_weather('complete').")
        return 2
    if meta.get("spot_set") != "complete":
        print(f"FEHLER: Snapshot ist '{meta.get('spot_set')}', gebraucht wird 'complete'.")
        return 2

    print(f"Provider     : {prov}  ({modell})")
    print(f"Snapshot     : {meta.get('spot_count')} Spots, {meta.get('region_count')} Regionen, "
          f"Wetter-Lauf {meta.get('source_run_at')}")
    print(f"Sprache/Tage : LANG={config.LANG}, FORECAST_DAYS={config.FORECAST_DAYS}"
          + (f" (begrenzt auf {a.days})" if a.days else ""))
    print(f"Ausgabe      : {test_mode.TEST_RUN_LATEST_DIR}  (Produktivdaten unberuehrt)")
    print("-" * 66, flush=True)

    from chat_engine import WingcastEngine
    eng = WingcastEngine()

    # Sperre: die Engine loest Provider/Modell selbst auf. Weicht das vom
    # Gewuenschten ab, brechen wir ab — ein Lauf ueber den falschen Anbieter
    # kostet Geld und liefert eine wertlose Vergleichszahl.
    ist_prov = getattr(eng, "analysis_provider", None)
    ist_modell = getattr(eng, "analysis_model", None)
    print(f"Engine nutzt : {ist_prov}  ({ist_modell})")
    if ist_prov != prov:
        print(f"ABBRUCH: gewuenscht war '{prov}', die Engine nutzt '{ist_prov}'. "
              f"Vermutlich ueberschreibt data/config_overrides.json das Modell.")
        return 3
    print("-" * 66, flush=True)

    t0 = time.time()
    letzte = 0.0
    ergebnis = {}
    for evt in test_mode.run_test_analyses_stream(
            eng, use_frozen_input=True, spot_set="complete", n_days=a.days):
        ev = (evt or {}).get("event")
        d = (evt or {}).get("data", {}) or {}
        if ev == "phase":
            print(f"\n[{time.time()-t0:6.0f}s] Phase: {d.get('phase')}", flush=True)
        elif ev == "progress":
            # nicht jede Zeile drucken — sonst ist das Log unlesbar
            if time.time() - letzte > 20:
                letzte = time.time()
                print(f"[{time.time()-t0:6.0f}s]   {d.get('completed')}/{d.get('total')} "
                      f"({d.get('phase')})", flush=True)
        elif ev == "done":
            ergebnis = d
        elif ev == "error":
            print(f"FEHLER-Event: {d.get('message')}", flush=True)

    dauer = time.time() - t0
    print("-" * 66)
    if not ergebnis:
        print("Lauf hat kein 'done' erreicht.")
        return 1
    print(f"Calls        : {ergebnis.get('total_calls')}  "
          f"(Safety {ergebnis.get('safety_count')}, Fly {ergebnis.get('flyability_count')}, "
          f"Pre-Filter uebersprungen {ergebnis.get('prefilter_skipped')})")
    print(f"Kosten       : ${ergebnis.get('est_usd')}")
    print(f"Dauer        : {dauer/60:.1f} min")
    print(f"Ergebnisdatei: {test_mode.TEST_RUN_SPOT_ANALYSES_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
