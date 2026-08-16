"""Anbieter-Sonde: misst Tokens, Cache-Trefferquote, Tempo und Fehler pro Provider.

Hintergrund (16.08.2026): DeepSeek hat auf Peak/Off-Peak umgestellt und kostet
uns rund doppelt so viel. DeepInfra hostet dasselbe Modell (FP8) deutlich
guenstiger. Die Kostenrechnung dazu steht — sie haengt aber an EINER Annahme:
dass DeepInfras Cache bei unserem Prompt-Zuschnitt genauso greift wie der von
DeepSeek (dort gemessen: ~73 % der Input-Tokens). Genau das misst dieses Skript.

Was es NICHT misst: die Antwortqualitaet. Dafuer ist score_regression.py da.

Wichtig: das Skript fasst KEINE Produktivdaten an. Es schickt die eingefrorenen
Golden-Inputs durch den echten Split-Flow (wie score_regression.py) und liest
die usage-Felder der Responses mit. Es schreibt weder spot_analyses.json noch
wetterdaten.json noch die Kosten-Telemetrie.

Aufruf:
    python cost_testing/ab_provider_probe.py --provider deepseek  --cases 12
    python cost_testing/ab_provider_probe.py --provider deepinfra --cases 12

    # Beide nacheinander, Ergebnis als Markdown:
    python cost_testing/ab_provider_probe.py --both --cases 12 \
        --report cost_testing/reports/probe_$(date +%F).md

Der Cache braucht Anlauf: der erste Call einer Sequenz ist immer ein Miss.
Deshalb wird die Trefferquote zusaetzlich OHNE den ersten Call ausgewiesen —
das entspricht dem Daily-Run, der ~2800 Calls am Stueck macht.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
# eigenes Verzeichnis dazu — wir leihen uns die Reverse-Parser von score_regression
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

GOLDEN_DIR = _HERE / "golden"

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env")
except ImportError:
    pass


# ---------------------------------------------------------------- Messung ---
class UsageRecorder:
    """Haengt sich in den LLM-Client und schreibt jede Response mit.

    Bewusst als Monkeypatch auf _CompletionsAPI.create: so laeuft exakt der
    Produktionspfad (gleiche Prompts, gleiche Reihenfolge, gleiche Skills),
    und wir sehen trotzdem jede einzelne usage-Zeile.
    """

    def __init__(self):
        self.calls: list[dict] = []
        self.errors: list[str] = []
        self._orig = None

    def __enter__(self):
        import llm_client
        from engine._common import extract_usage_from_response as _extract_usage
        self._orig = llm_client._CompletionsAPI.create
        rec = self

        def wrapped(self_api, *args, **kwargs):
            t0 = time.perf_counter()
            try:
                resp = rec._orig(self_api, *args, **kwargs)
            except Exception as e:
                rec.errors.append(f"{type(e).__name__}: {e}")
                raise
            dt = time.perf_counter() - t0
            u = _extract_usage(resp)
            u["latency_s"] = dt
            rec.calls.append(u)
            return resp

        llm_client._CompletionsAPI.create = wrapped
        return self

    def __exit__(self, *exc):
        import llm_client
        if self._orig is not None:
            llm_client._CompletionsAPI.create = self._orig
        return False


def _summarise(calls: list[dict], model: str) -> dict:
    """Verdichtet die Einzel-Calls. Kosten via config.prices_for (zeitabhaengig)."""
    import config

    if not calls:
        return {}
    in_tok = sum(c["in_tok"] for c in calls)
    out_tok = sum(c["out_tok"] for c in calls)
    cached = sum(c["cached_tok"] for c in calls)
    lat = [c["latency_s"] for c in calls]

    # Ohne den ersten Call: der ist per Definition ein Cache-Miss (kalter Start).
    warm = calls[1:] or calls
    warm_in = sum(c["in_tok"] for c in warm)
    warm_cached = sum(c["cached_tok"] for c in warm)

    prices = config.prices_for(model) or {}
    kosten = None
    if prices:
        kosten = ((in_tok - cached) * prices["in"]
                  + cached * prices["cached_in"]
                  + out_tok * prices["out"]) / 1e6

    return {
        "calls": len(calls),
        "in_tok": in_tok,
        "out_tok": out_tok,
        "cached_tok": cached,
        "cache_pct": 100.0 * cached / in_tok if in_tok else 0.0,
        "cache_pct_warm": 100.0 * warm_cached / warm_in if warm_in else 0.0,
        "lat_median_s": statistics.median(lat),
        "lat_p95_s": sorted(lat)[int(len(lat) * 0.95)] if len(lat) > 1 else lat[0],
        "kosten_usd": kosten,
        "preise": prices,
    }


# ------------------------------------------------------------------ Lauf ----
def _run_cases(provider: str, model: str | None, max_cases: int) -> dict:
    """Schickt die Golden-Inputs durch den echten Split-Flow."""
    import config
    from score_regression import _parse_foehn_block, _parse_gust_block  # type: ignore

    config.ANALYSIS_PROVIDER = provider
    if model:
        setattr(config, f"{provider.upper()}_ANALYSIS_MODEL", model)
    model = model or config.get_model(provider, "analysis")

    if not config.get_api_key(provider):
        raise SystemExit(
            f"Kein API-Key fuer '{provider}'. Erwartet ENV {provider.upper()}_API_KEY "
            f"(bzw. Eintrag in .env)."
        )

    files = sorted(GOLDEN_DIR.glob("*.json"))
    if max_cases:
        files = files[:max_cases]
    if not files:
        raise SystemExit(f"Keine Golden-Cases in {GOLDEN_DIR}")

    from chat_engine import WingcastEngine
    eng = WingcastEngine()

    ok = 0
    with UsageRecorder() as rec:
        t0 = time.perf_counter()
        for f in files:
            gold = json.loads(f.read_text(encoding="utf-8"))
            spot = gold.get("spot") or gold.get("spot_name")
            date_str = gold.get("date") or gold.get("date_str")
            ctx = gold["input"]
            spot_obj = next((s for s in eng.spots if s["name"] == spot), None)
            if not spot_obj:
                rec.errors.append(f"Spot '{spot}' nicht in CSV")
                continue
            key = f"{spot}|{date_str}"
            eng._ctx_foehn_cache[key] = _parse_foehn_block(ctx)
            eng._ctx_gust_cache[key] = _parse_gust_block(ctx)
            try:
                safety = eng._safety_analysis_single_spot_day(spot_obj, date_str, ctx)
                if safety.get("safety_status") in ("safe", "conditional"):
                    eng._flyability_analysis_single_spot_day(
                        spot_obj, date_str, ctx, safety, region_result=None)
                ok += 1
            except Exception as e:
                rec.errors.append(f"{spot}|{date_str}: {type(e).__name__}: {e}")
        dauer = time.perf_counter() - t0

    res = _summarise(rec.calls, model)
    res.update({"provider": provider, "model": model, "cases_ok": ok,
                "cases_total": len(files), "dauer_s": dauer,
                "fehler": rec.errors})
    return res


# --------------------------------------------------------------- Ausgabe ----
def _fmt(r: dict) -> str:
    if not r or not r.get("calls"):
        return f"### {r.get('provider', '?')}\n\nKeine Calls zustande gekommen.\n"
    return (
        f"### {r['provider']}  (`{r['model']}`)\n\n"
        f"| Messgroesse | Wert |\n|---|---|\n"
        f"| Cases | {r['cases_ok']}/{r['cases_total']} ok |\n"
        f"| LLM-Calls | {r['calls']} |\n"
        f"| Input-Tokens | {r['in_tok']:,} |\n"
        f"| davon gecacht | {r['cached_tok']:,} ({r['cache_pct']:.1f} %) |\n"
        f"| Cache warm (ohne 1. Call) | {r['cache_pct_warm']:.1f} % |\n"
        f"| Output-Tokens | {r['out_tok']:,} |\n"
        f"| Latenz Median / P95 | {r['lat_median_s']:.2f} s / {r['lat_p95_s']:.2f} s |\n"
        f"| Dauer gesamt | {r['dauer_s']:.0f} s |\n"
        f"| Kosten dieser Stichprobe | ${r['kosten_usd']:.4f} |\n"
        f"| Fehler | {len(r['fehler'])} |\n"
    ).replace(",", "'")


def main() -> int:
    ap = argparse.ArgumentParser(description="Anbieter-Sonde: Cache, Tempo, Tokens")
    ap.add_argument("--provider", default=None, help="deepseek | deepinfra | ...")
    ap.add_argument("--model", default=None, help="Modellname (default: config)")
    ap.add_argument("--both", action="store_true",
                    help="deepseek und deepinfra nacheinander messen")
    ap.add_argument("--cases", type=int, default=12, help="Anzahl Golden-Cases")
    ap.add_argument("--report", default=None, help="Markdown-Report schreiben")
    a = ap.parse_args()

    if not a.both and not a.provider:
        ap.error("--provider oder --both angeben")

    provider_list = ["deepseek", "deepinfra"] if a.both else [a.provider]
    ergebnisse = []
    for p in provider_list:
        print(f"\n=== Sonde: {p} ({a.cases} Cases) ===", flush=True)
        r = _run_cases(p, a.model, a.cases)
        ergebnisse.append(r)
        print(_fmt(r), flush=True)
        for e in r["fehler"][:5]:
            print(f"   FEHLER: {e}", flush=True)

    if len(ergebnisse) == 2 and all(e.get("calls") for e in ergebnisse):
        ds, di = ergebnisse
        if ds["kosten_usd"] and di["kosten_usd"]:
            faktor = ds["kosten_usd"] / di["kosten_usd"]
            print(f"\n>> Gleiche Stichprobe: DeepSeek ${ds['kosten_usd']:.4f} vs "
                  f"DeepInfra ${di['kosten_usd']:.4f}  (Faktor {faktor:.2f}x)")
        print(f">> Cache warm: DeepSeek {ds['cache_pct_warm']:.1f} % vs "
              f"DeepInfra {di['cache_pct_warm']:.1f} %")

    if a.report:
        out = Path(a.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        txt = ["# Anbieter-Sonde\n",
               "Misst Tokens, Cache, Tempo — NICHT die Qualitaet ",
               "(dafuer `score_regression.py`).\n\n"]
        txt += [_fmt(r) + "\n" for r in ergebnisse]
        out.write_text("".join(txt), encoding="utf-8")
        print(f"\nReport: {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
