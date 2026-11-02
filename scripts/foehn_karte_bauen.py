"""Föhn-Karte jetzt aus den Live-Prognosen bauen — für die lokale Prüfung auf localhost.

Ruft decide_foehn_summary auf (friert dabei data/foehn_karte.json ein, siehe engine/synoptic_context)
und ersetzt im lokalen data/synoptic_context.json NUR den Block "foehn", damit Pille und Labels
der Seite zum Briefing passen. Auf dem Server übernimmt das der Morgenlauf; diese Datei ist
server-lokal und gitignored.

Aufruf:  python scripts/foehn_karte_bauen.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import foehn_indicators as fi  # noqa: E402
from foehn_talpunkte import fetch_talpunkt_wind  # noqa: E402
from engine.synoptic_context import decide_foehn_summary  # noqa: E402
import foehn_karte  # noqa: E402


def main() -> int:
    import config_overrides
    config_overrides.init()     # Konfigurator-Werte (FORECAST_DAYS usw.) wie im Server
    days = config.FORECAST_DAYS
    karte = fi.fetch_wind_karte(forecast_days=days)
    if not karte:
        print("Windkarte konnte nicht geladen werden (Open-Meteo).")
        return 1
    dates = sorted({t[:10] for t in karte["time"]})[:days]
    tal = fetch_talpunkt_wind(forecast_days=days)
    if not tal:
        print("Talpunkte konnten nicht geladen werden — Karte entsteht ohne Täler.")

    foehn = decide_foehn_summary(dates, weather_cache={"_meta": {"foehn_tal_series": tal}})
    store = foehn_karte.lade()
    print(f"foehn_karte.json: {config.FOEHN_KARTE_PATH} "
          f"({'geschrieben' if store else 'NICHT geschrieben — siehe Log'}), Tage: {dates}")

    cache_path = config.SYNOPTIC_CACHE_PATH
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        cache["foehn"] = foehn
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"synoptic_context.json: nur Block 'foehn' ersetzt ({len(foehn.get('per_day', []))} Tage)")
    else:
        print("synoptic_context.json fehlt lokal — Pille/Labels bleiben leer, Karte funktioniert trotzdem.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
