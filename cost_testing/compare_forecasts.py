"""Vergleicht zwei komplette Forecasts Spot fuer Spot, Tag fuer Tag.

Gebaut fuer den Anbietervergleich (16.08.2026): der Server hat den Forecast
heute frueh mit DeepSeek gerechnet, `run_full_forecast.py` rechnet denselben
Wetterstand mit DeepInfra. Beide Seiten haben damit identische Eingaben --
jede Abweichung geht auf das Modell bzw. den Hoster zurueck.

Die zentrale Frage ist nicht "wie viele Abweichungen", sondern ob sie eine
RICHTUNG haben. Zufaellige Streuung eines Sprachmodells ist symmetrisch.
Wenn eine Seite systematisch haeufiger "sicher" sagt, waere das ein
Sicherheitsproblem und kein Rauschen -- deshalb wird die Richtung getrennt
ausgewiesen.

Aufruf:
    python cost_testing/compare_forecasts.py \
        --a reference_deepseek/spot_analyses_en.json --a-name DeepSeek \
        --b data/test_runs/latest/spot_analyses.json --b-name DeepInfra
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter
from pathlib import Path

# Sicherheits-Rangfolge: hoeher = freizuegiger. Fuer die Richtungsanalyse.
SAFETY_RANG = {"not_safe": 0, "error": 0, "": 0, "conditional": 1, "safe": 2}
XC_RANG = {"kein_xc": 0, "lokal": 1, "moderat": 2, "top": 3}


def _status(e: dict) -> str:
    return ((e.get("safety") or {}).get("safety_status")
            or e.get("status") or "")


def _xc(e: dict) -> str:
    return ((e.get("streckenflug") or {}).get("tier") or "")


def _stunden(text: str) -> set[int]:
    """Zieht Stunden aus '12:00-13:00, 17:00-18:00' als Menge."""
    out: set[int] = set()
    for a, b in re.findall(r"(\d{1,2}):\d{2}\s*[-–]\s*(\d{1,2}):\d{2}", text or ""):
        try:
            out.update(range(int(a), int(b)))
        except ValueError:
            pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Zwei Forecasts gegenueberstellen")
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--a-name", default="A")
    ap.add_argument("--b-name", default="B")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    A = json.loads(Path(args.a).read_text(encoding="utf-8"))
    B = json.loads(Path(args.b).read_text(encoding="utf-8"))

    paare = []
    for spot in sorted(set(A) & set(B)):
        for tag in sorted(set(A[spot]) & set(B[spot])):
            paare.append((spot, tag, A[spot][tag], B[spot][tag]))

    if not paare:
        print("Keine gemeinsamen Spot/Tag-Paare gefunden.")
        return 1

    # --- Sicherheitsurteil ---
    gleich = 0
    a_freizuegiger, b_freizuegiger = [], []
    kombis = Counter()
    for spot, tag, ea, eb in paare:
        sa, sb = _status(ea), _status(eb)
        kombis[(sa, sb)] += 1
        if sa == sb:
            gleich += 1
        elif SAFETY_RANG.get(sa, 0) > SAFETY_RANG.get(sb, 0):
            a_freizuegiger.append((spot, tag, sa, sb))
        else:
            b_freizuegiger.append((spot, tag, sa, sb))

    # --- Numerische Bewertungen ---
    # `rating` wird erst in der produktiven Nachbearbeitung berechnet und ist im
    # Testmodus durchgehend 0 — es wird nur ausgewiesen, wenn es tatsaechlich
    # variiert. Aussagekraeftig sind die Einzelbewertungen.
    ZAHLFELDER = [
        ("rating", lambda e: e.get("rating")),
        ("safety_rating", lambda e: e.get("safety_rating")),
        ("experience_rating", lambda e: e.get("experience_rating")),
        ("streckenflug.rating", lambda e: (e.get("streckenflug") or {}).get("rating")),
        ("wind_safety_rating", lambda e: e.get("wind_safety_rating")),
        ("gust_safety_rating", lambda e: e.get("gust_safety_rating")),
        ("cape_safety_rating", lambda e: e.get("cape_safety_rating")),
        ("rain_safety_rating", lambda e: e.get("rain_safety_rating")),
        ("thunderstorm_safety_rating", lambda e: e.get("thunderstorm_safety_rating")),
    ]
    zahl_stats = []
    for name, f in ZAHLFELDER:
        paarwerte = [(f(ea), f(eb)) for _, _, ea, eb in paare]
        paarwerte = [(x, y) for x, y in paarwerte
                     if isinstance(x, (int, float)) and isinstance(y, (int, float))]
        if not paarwerte:
            continue
        werte = [x for x, _ in paarwerte] + [y for _, y in paarwerte]
        if len(set(werte)) <= 1:
            continue  # konstant -> nichts zu vergleichen
        dd = [y - x for x, y in paarwerte]
        zahl_stats.append({
            "feld": name, "n": len(dd),
            "mittel": statistics.mean(dd),
            "betrag": statistics.mean(abs(d) for d in dd),
            "gleich": sum(1 for d in dd if d == 0),
            "gross": sum(1 for d in dd if abs(d) > 1.0),
        })
    diffs = []

    # --- Streckenflug ---
    xc_gleich = sum(1 for _, _, ea, eb in paare if _xc(ea) == _xc(eb))

    # --- Zeitfenster ---
    ueberlappungen = []
    for _, _, ea, eb in paare:
        ha = _stunden((ea.get("safety") or {}).get("safe_window") or ea.get("best_window") or "")
        hb = _stunden((eb.get("safety") or {}).get("safe_window") or eb.get("best_window") or "")
        if ha or hb:
            ueberlappungen.append(len(ha & hb) / len(ha | hb) if (ha | hb) else 1.0)

    n = len(paare)
    z = []
    z.append(f"# Forecast-Vergleich -- {args.a_name} vs. {args.b_name}\n")
    z.append(f"Verglichen: **{n} Spot/Tag-Bewertungen** "
             f"({len(set(s for s, _, _, _ in paare))} Spots), identische Wettereingabe.\n")
    z.append("\n## Sicherheitsurteil (das sicherheitskritische Feld)\n")
    z.append(f"- Identisch: **{gleich}/{n} ({100*gleich/n:.1f} %)**\n")
    z.append(f"- {args.a_name} freizuegiger: {len(a_freizuegiger)}\n")
    z.append(f"- {args.b_name} freizuegiger: {len(b_freizuegiger)}\n")
    schief = abs(len(a_freizuegiger) - len(b_freizuegiger))
    gesamt_abw = len(a_freizuegiger) + len(b_freizuegiger)
    if gesamt_abw:
        z.append(f"- Richtung: Ungleichgewicht {schief} von {gesamt_abw} Abweichungen "
                 f"({100*schief/gesamt_abw:.0f} % Schieflage) -- "
                 f"{'symmetrisch, sieht nach Streuung aus' if schief <= 0.25*gesamt_abw else 'EINSEITIG, genauer ansehen'}\n")
    if zahl_stats:
        z.append("\n## Numerische Bewertungen\n\n")
        z.append(f"Mittelwert-Differenz = {args.b_name} minus {args.a_name}. "
                 f"Ein Wert nahe 0 heisst: keine systematische Schieflage.\n\n")
        z.append("| Feld | n | Mittelwert-Diff | mittl. Betrag | identisch | Abw. > 1 |\n")
        z.append("|---|---|---|---|---|---|\n")
        for s in zahl_stats:
            z.append(f"| {s['feld']} | {s['n']} | {s['mittel']:+.3f} | {s['betrag']:.2f} | "
                     f"{100*s['gleich']/s['n']:.0f} % | {s['gross']} |\n")
    z.append("\n## Weitere Felder\n")
    z.append(f"- Streckenflug-Stufe identisch: {xc_gleich}/{n} ({100*xc_gleich/n:.1f} %)\n")
    if ueberlappungen:
        z.append(f"- Zeitfenster-Ueberlappung im Mittel: {100*statistics.mean(ueberlappungen):.1f} %\n")

    z.append("\n## Haeufigste Urteilskombinationen\n\n")
    z.append(f"| {args.a_name} | {args.b_name} | Faelle |\n|---|---|---|\n")
    for (sa, sb), c in kombis.most_common(8):
        mark = "" if sa == sb else "  <--"
        z.append(f"| {sa or '(leer)'} | {sb or '(leer)'}{mark} | {c} |\n")

    if a_freizuegiger or b_freizuegiger:
        z.append("\n## Abweichende Sicherheitsurteile (max. 25)\n\n")
        z.append(f"| Spot | Tag | {args.a_name} | {args.b_name} |\n|---|---|---|---|\n")
        for spot, tag, sa, sb in (a_freizuegiger + b_freizuegiger)[:25]:
            z.append(f"| {spot} | {tag} | {sa or '(leer)'} | {sb or '(leer)'} |\n")

    txt = "".join(z)
    print(txt)
    if args.report:
        p = Path(args.report)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
        print(f"\nReport: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
