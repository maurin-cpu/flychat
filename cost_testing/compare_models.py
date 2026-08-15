#!/usr/bin/env python3
"""Was kostet ein voller Analyse-Lauf bei welchem Modell?

Rechnet das gemessene Token-Profil eines Laufs gegen mehrere Preisschemata.
Kein LLM-Call, keine Netzwerkzugriffe — reine Arithmetik auf Messwerten.

Profil-Quelle (Default): der dokumentierte gpt-4o-mini-Lauf auf der Test-CSV
(28 Spots, 4.5M In-Tok, 108K Out-Tok, 72 % Cache-Hit — cost_testing/doku.md §d),
hochgerechnet auf die Complete-CSV (487 Spots). Der Sanity-Check unten muss die
dort dokumentierten ~$8.70 reproduzieren; tut er das nicht, stimmt das Profil
nicht mehr und die ganze Tabelle ist wertlos.

Besser als die Hochrechnung: echte Zahlen aus data/cost_telemetry.jsonl:

    python cost_testing/compare_models.py --from-telemetry

Hintergrund + Quellenlage der Preise: docs/LLM_KOSTEN_VERGLEICH_2026-08.md
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402

TEST_CSV_SPOTS, COMPLETE_CSV_SPOTS = 28, 487
MEASURED_IN_TOK, MEASURED_OUT_TOK, MEASURED_CACHE_HIT = 4_500_000, 108_000, 0.72

# Preisschemata, die (noch) nicht in config.MODEL_PRICES stehen: angekuendigt,
# aber unbelegt (DeepSeek ab 16.08.) oder Batch-Variante mit gestapeltem Cache.
EXTRA_SCHEMES = {
    "deepseek-v4-flash (NEU off-peak, geschaetzt)": {"in": 0.213, "cached_in": 0.017, "out": 0.660},
    "deepseek-v4-flash (NEU peak, geschaetzt)":     {"in": 0.426, "cached_in": 0.034, "out": 1.320},
    "gpt-5.6-luna (Batch, Cache gestapelt)":        {"in": 0.100, "cached_in": 0.010, "out": 0.600},
}


def kosten(in_tok, out_tok, cache_hit, preise):
    return (in_tok * (1 - cache_hit) * preise["in"] / 1e6
            + in_tok * cache_hit * preise["cached_in"] / 1e6
            + out_tok * preise["out"] / 1e6)


def profil_hochgerechnet():
    skala = COMPLETE_CSV_SPOTS / TEST_CSV_SPOTS
    return MEASURED_IN_TOK * skala, MEASURED_OUT_TOK * skala, MEASURED_CACHE_HIT


def profil_aus_telemetrie(pfad):
    zeilen = [json.loads(z) for z in pathlib.Path(pfad).read_text().splitlines() if z.strip()]
    if not zeilen:
        raise SystemExit(f"{pfad} ist leer — erst einen Lauf machen.")
    r = zeilen[-1]
    in_tok, out_tok = r["total_in_tok"], r["total_out_tok"]
    return in_tok, out_tok, (r["total_cached_tok"] / in_tok if in_tok else 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-telemetry", nargs="?", const=str(config.COST_TELEMETRY_PATH),
                    metavar="JSONL", help="letzte Zeile aus cost_telemetry.jsonl statt Hochrechnung")
    ap.add_argument("--laeufe-pro-monat", type=int, default=30)
    args = ap.parse_args()

    if args.from_telemetry:
        in_tok, out_tok, hit = profil_aus_telemetrie(args.from_telemetry)
        quelle = f"gemessen ({args.from_telemetry}, letzter Lauf)"
    else:
        in_tok, out_tok, hit = profil_hochgerechnet()
        quelle = f"hochgerechnet: Test-CSV-Messung x {COMPLETE_CSV_SPOTS}/{TEST_CSV_SPOTS} Spots"

    print(f"Profil ({quelle}):")
    print(f"  {in_tok/1e6:.1f}M In-Tok, {out_tok/1e6:.2f}M Out-Tok, {hit*100:.0f} % Cache-Hit\n")

    schemata = list(config.MODEL_PRICES.items()) + list(EXTRA_SCHEMES.items())
    zeilen = [(name, kosten(in_tok, out_tok, hit, p)) for name, p in schemata]
    for name, usd in sorted(zeilen, key=lambda z: z[1]):
        print(f"  {name:<46} ${usd:7.2f}/Lauf   ${usd*args.laeufe_pro_monat:8.0f}/Monat")

    if not args.from_telemetry:
        ist = dict(zeilen)["gpt-4o-mini"]
        ok = abs(ist - 8.70) < 0.30
        print(f"\nSanity-Check gpt-4o-mini: ${ist:.2f} vs. dokumentierte $8.70 "
              f"-> {'OK' if ok else 'ABWEICHUNG — Profil pruefen!'}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
