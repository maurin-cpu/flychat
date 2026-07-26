"""Erzeugt den Zonen-Wetterlage-Block aus dem AKTUELLEN Wettercache und
legt ihn neben den bestehenden (alten) Block — ohne Prod-Caches zu
ueberschreiben.

Zweck: Vorher/Nachher-Vergleich der Synoptik 2.0 (4 Flugwetter-Zonen,
Tagesfenster, Zugbahn) gegen die alte Nord/Sued-Tagespauschale, plus
Rohdaten-Faktencheck der Zeitfenster-Aussagen.

Run:  python scripts/preview_synoptik_zonen.py
      python scripts/preview_synoptik_zonen.py --no-llm   (nur Strukturfeld)
      python scripts/preview_synoptik_zonen.py --lang de  (Gegenprobe DE,
          waehrend der Server fuer die Forum-Demo auf LANG=en laeuft)
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config_overrides  # noqa: E402
config_overrides.init()  # LANG/Modelle wie in Produktion

import config  # noqa: E402
from engine import synoptic_context as sc  # noqa: E402
from engine import synoptic_llm as sl  # noqa: E402


def build_ctx(weather_cache: dict, old_ctx: dict) -> dict:
    """Altes Strukturfeld + neue Zonen-Felder (ohne Neu-Fetch der
    Druckzentren — die stehen schon im gecachten Kontext)."""
    dates = old_ctx["forecast_dates"]
    zone_map = sc.build_spot_zone_map()
    ctx = dict(old_ctx)
    ctx["precip_zones"] = sc.decide_precip_pattern_zones(weather_cache, dates,
                                                         zone_map)
    ctx["wind_zones"] = sc.decide_wind_pattern_zones(weather_cache, dates,
                                                     zone_map)
    ctx["zugbahn"] = sc.decide_zugbahn(weather_cache, dates, zone_map)
    return ctx


def print_factcheck(ctx: dict) -> None:
    """Rohdaten-Faktencheck: Zeitfenster-Verlauf pro Zone und Tag."""
    pz = ctx["precip_zones"]
    wz = {d["date"]: d["zones"] for d in ctx["wind_zones"]["per_day"]}
    wins = [w["key"] for w in pz["windows"]]
    print("\n" + "=" * 78)
    print("ROHDATEN-FAKTENCHECK (wet_share / p90mm je Fenster | wind crit)")
    print("=" * 78)
    for day in pz["per_day"]:
        print(f"\n{day['date']}")
        for zone, zv in day["zones"].items():
            cells = " ".join(
                f"{w[:3]}:{(zv['windows'][w]['wet_share'] or 0):.2f}"
                f"/{(zv['windows'][w]['p90_mm'] or 0):.1f}"
                for w in wins)
            zw = (wz.get(day["date"]) or {}).get(zone) or {}
            print(f"  {zone:22} {cells}  | wind={zw.get('wind_class')} "
                  f"crit={zw.get('share_wind_crit')} driver={zw.get('wind_driver')}")
    print("\nZugbahn:")
    for d in ctx["zugbahn"]["per_day"]:
        print(f"  {d['date']}  onset={d['onset_hour_by_group']}  {d['movement']}")


def print_overview(title: str, ov: dict) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)
    if not ov:
        print("(kein Output)")
        return
    print("\nLEAD:\n" + (ov.get("short") or "(leer)"))
    zones = ov.get("zones")
    if zones:
        for z in zones:
            print(f"\n--- {z['label']} ---")
            for d in z["days"]:
                print(f"  {d['text']}")
                if d.get("flight_hint"):
                    print(f"     -> {d['flight_hint']}")
    else:
        for e in ov.get("long_with_sources") or []:
            print(f"\n  {e['text']}")
            if e.get("flight_hint"):
                print(f"     -> {e['flight_hint']}")
    print(f"\n[attempts={ov.get('attempts')} unresolved={ov.get('unresolved')}]")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true",
                    help="nur Strukturfeld + Faktencheck, kein LLM-Call")
    ap.add_argument("--lang", choices=("de", "en"),
                    help="Sprache nur fuer diesen Lauf ueberschreiben "
                         "(Default: LANG aus config_overrides)")
    args = ap.parse_args()
    if args.lang:
        config.LANG = args.lang   # Prozess-lokal, schreibt keine Config zurueck

    weather_cache = json.loads(
        (config.DATA_DIR / "wetterdaten.json").read_text(encoding="utf-8"))
    old_ctx = json.loads(
        Path(config.SYNOPTIC_CACHE_PATH).read_text(encoding="utf-8"))

    ctx = build_ctx(weather_cache, old_ctx)
    print_factcheck(ctx)

    print_overview("ALT — bisheriger Block (aus synoptic_context.json)",
                   old_ctx.get("llm_overview"))

    if args.no_llm:
        return 0

    from llm_client import build_client
    client = build_client(config.SYNOPTIC_PROVIDER,
                          config.get_api_key(config.SYNOPTIC_PROVIDER),
                          timeout=120.0)
    if client is None:
        print("\nKein LLM-Client fuer Provider "
              f"{config.SYNOPTIC_PROVIDER} — nur Strukturfeld gezeigt.")
        return 1

    print(f"\n... LLM-Call ({config.SYNOPTIC_MODEL}, lang={config.LANG}) ...")
    new_ov = sl.generate_synoptic_overview(ctx, client, config.SYNOPTIC_MODEL)
    print_overview("NEU — Zonen-Block (Synoptik 2.0)", new_ov)

    out = ROOT / "data" / "_preview_synoptik_zonen.json"
    out.write_text(json.dumps(
        {"forecast_dates": ctx["forecast_dates"],
         "precip_zones": ctx["precip_zones"],
         "wind_zones": ctx["wind_zones"],
         "zugbahn": ctx["zugbahn"],
         "llm_overview_neu": new_ov,
         "llm_overview_alt": old_ctx.get("llm_overview")},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nGeschrieben: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
