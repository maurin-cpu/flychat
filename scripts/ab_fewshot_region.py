"""
A/B-Replay: Wirkt der Few-Shot-Block kausal auf das Region-Rating?

Nimmt die Region-Problem-Cases (LLM=5, Pilot-Korrektur < 5) und analysiert
JEDEN Tag zweimal mit identischem Prompt/Modell/Temperatur — der einzige
Unterschied ist der Few-Shot-Block:

  Arm A (Kontrolle):   nur Rubric + Wetterdaten
  Arm B (Behandlung):  identisch + Few-Shot-Block davor

WICHTIG — Validitaet: Der Block schliesst den replayten Fall SELBST aus dem
Retrieval aus (zur Analysezeit existierte sein Label noch nicht). Sonst bekaeme
Arm B die Antwort geschenkt.

Misst pro Arm: Treffer gegen Pilot-Ziel, "immer noch >= orig"-Rate, Ø |Rating-GT|.
Plus gepaart: wie oft senkt B gegenueber A, wie oft naeher am Ziel.

Usage: python scripts/ab_fewshot_region.py [--limit N] [--temp 0.2]
Modell = data/config_overrides.json ANALYSIS_MODEL (Produktion: deepseek-chat).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import prompts
from openai import OpenAI
from engine import labeled_examples as le
# Nachbau der Produktions-User-Message aus dem bestehenden Replay.
from scripts.replay_region_problem_cases import (
    build_user_message,
    effective_rating,
    load_problem_cases,
)

API_KEY = os.environ.get("DEEPSEEK_API_KEY")
BASE_URL = "https://api.deepseek.com/v1"
MODEL = "deepseek-chat"


def fewshot_block_excluding(case) -> tuple[str, list[float]]:
    """Few-Shot-Block fuer den Fall, OHNE den Fall selbst (Self-Ausschluss).

    Returns (block_text, neighbor_effective_ratings).
    """
    feats = le._extract_features_from_label(case)
    if feats is None:
        return "", []
    cid = case.get("spot_or_region_id")
    cdate = case.get("target_date")
    # top_k=4 holen, Self entfernen, auf 3 kuerzen — wie Produktion (top_k=3).
    hits = le.retrieve_similar(feats, top_k=4, entity_type="region")
    hits = [h for h in hits
            if not (h.get("spot_or_region_id") == cid and h.get("target_date") == cdate)][:3]
    if not hits:
        return "", []

    def _eff(e):
        fb = e.get("user_feedback") or {}
        o = (e.get("llm_output_full") or {}).get("experience_rating")
        if fb.get("label") == "richtig":
            return o
        c = fb.get("corrected_experience_rating")
        return c if c is not None else o

    neigh = [float(_eff(h)) for h in hits if _eff(h) is not None]
    return le.format_for_prompt(hits), neigh


def call_llm(client, system_prompt, user_msg, temp):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        temperature=temp,
        max_tokens=1500,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content or "{}"
    try:
        rating = json.loads(raw).get("experience_rating")
    except Exception:
        rating = None
    return rating, resp.usage


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--temp", type=float, default=0.2)
    args = ap.parse_args()

    if not API_KEY:
        print("FEHLER: DEEPSEEK_API_KEY nicht gesetzt")
        sys.exit(1)

    cases = load_problem_cases()
    if args.limit:
        cases = cases[: args.limit]

    system_prompt = prompts.REGION_FLYABILITY_PROMPT
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=45.0, max_retries=2)

    print(f"A/B-Replay {len(cases)} Region-Cases (LLM=5, Pilot<5) | Modell={MODEL} temp={args.temp}")
    print(f"System-Prompt: {len(system_prompt)} chars\n")
    print(f"{'#':>3} {'Region':<26} {'gt':>2} {'A':>3} {'B':>3} {'blk':>4}  Δ(A→B)")
    print("-" * 64)

    rec = []  # (gt, a, b, block_mean)
    tin = tout = 0
    for i, case in enumerate(cases, 1):
        name = (case.get("spot_or_region_id") or "?")[:26]
        _, gt = effective_rating(case)
        base = build_user_message(case)
        block, neigh = fewshot_block_excluding(case)
        bmean = round(sum(neigh) / len(neigh), 1) if neigh else None

        try:
            a, ua = call_llm(client, system_prompt, base, args.temp)
        except Exception as exc:
            a, ua = None, None
            print(f"    A-call fail: {exc}")
        time.sleep(0.3)
        msg_b = (block + "\n" + base) if block else base
        try:
            b, ub = call_llm(client, system_prompt, msg_b, args.temp)
        except Exception as exc:
            b, ub = None, None
            print(f"    B-call fail: {exc}")
        time.sleep(0.3)
        for u in (ua, ub):
            if u:
                tin += u.prompt_tokens; tout += u.completion_tokens

        delta = (b - a) if (a is not None and b is not None) else None
        arrow = f"{delta:+d}" if delta is not None else " ?"
        rec.append((gt, a, b, bmean))
        print(f"{i:>3} {name:<26} {gt:>2} {str(a):>3} {str(b):>3} {str(bmean):>4}  {arrow}")

    print("\n" + "=" * 64)
    print("ZUSAMMENFASSUNG")
    print("=" * 64)

    gts = [x[0] for x in rec]
    A = [x[1] for x in rec]
    B = [x[2] for x in rec]

    def summarize(label, arr):
        pair = [(g, r) for g, r in zip(gts, arr) if r is not None]
        n = len(pair)
        hit = sum(1 for g, r in pair if r == g)
        stayed = sum(1 for g, r in pair if r >= 5)  # orig war 5
        mae = sum(abs(r - g) for g, r in pair) / n if n else float("nan")
        mean = sum(r for _, r in pair) / n if n else float("nan")
        print(f"\n{label}: n={n}")
        print(f"  Ø Rating          {mean:.2f}   (Pilot-Ziel Ø {sum(gts)/len(gts):.2f})")
        print(f"  Treffer = Pilot   {hit}/{n} ({100*hit//n if n else 0}%)")
        print(f"  immer noch 5      {stayed}/{n} ({100*stayed//n if n else 0}%)")
        print(f"  Ø |Rating - Ziel| {mae:.2f}")

    summarize("Arm A (OHNE Few-Shot)", A)
    summarize("Arm B (MIT Few-Shot)", B)

    # gepaart
    paired = [(g, a, b) for g, a, b, _bm in rec if a is not None and b is not None]
    npd = len(paired)
    down = sum(1 for g, a, b in paired if b < a)
    up = sum(1 for g, a, b in paired if b > a)
    same = sum(1 for g, a, b in paired if b == a)
    closer = sum(1 for g, a, b in paired if abs(b - g) < abs(a - g))
    worse = sum(1 for g, a, b in paired if abs(b - g) > abs(a - g))
    print(f"\nGEPAART (n={npd}):")
    print(f"  B senkt ggü. A     {down}   B hebt {up}   gleich {same}")
    print(f"  B näher am Ziel    {closer}   B weiter weg {worse}   gleich {npd-closer-worse}")

    cost = (tin / 1e6 * 0.27) + (tout / 1e6 * 1.10)
    print(f"\nTokens: {tin} in + {tout} out = ~${cost:.3f}")


if __name__ == "__main__":
    main()
