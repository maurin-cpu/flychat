"""
Ablations-Studie: Blockieren die statischen PILOTEN-VIGNETTEN im Skill, dass
die dynamischen Few-Shot-Labels befolgt werden?

Hypothese (User): Die fest verdrahteten Vignetten (u.a. 5er-Anker bei Peak ~2.6)
konkurrieren mit den Few-Shot-Labels und ueberstimmen sie. Test: was passiert,
wenn man "statt Vignetten die Labels" nimmt?

4 Arme auf denselben Region-Problem-Cases (LLM=5, Pilot<5), einziger Unterschied
ist Vignetten an/aus  x  Few-Shot an/aus:
  V+F+  Vignetten + Few-Shot   (~Produktion heute)
  V+F-  Vignetten, kein Few-Shot
  V-F+  KEINE Vignetten + Few-Shot   <- "statt Vignetten die Labels"
  V-F-  KEINE Vignetten, kein Few-Shot

Self-Ausschluss im Few-Shot-Block wie im A/B-Replay.

Usage: python scripts/ab_vignette_ablation.py [--limit N] [--temp 0.2]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import prompts
from openai import OpenAI
from scripts.replay_region_problem_cases import (
    build_user_message,
    effective_rating,
    load_problem_cases,
)
from scripts.ab_fewshot_region import fewshot_block_excluding

API_KEY = os.environ.get("DEEPSEEK_API_KEY")
BASE_URL = "https://api.deepseek.com/v1"
MODEL = "deepseek-chat"

# Schneidet den PILOTEN-VIGNETTEN-Abschnitt heraus (Divider+Header bis zur
# Abschluss-Zeile). Harte Schranken + Region-Cap bleiben erhalten.
_VIGNETTE_RE = re.compile(
    r"─{5,}\s*\nPILOTEN-VIGNETTEN.*?Sonst gilt: dein Pilotenurteil zaehlt, nicht eine Checkliste\.",
    re.DOTALL,
)


def strip_vignettes(prompt: str) -> str:
    return _VIGNETTE_RE.sub(
        "(Vignetten-Abschnitt fuer dieses Experiment entfernt.)", prompt
    )


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
        return json.loads(raw).get("experience_rating"), resp.usage
    except Exception:
        return None, resp.usage


ARMS = ["V+F+", "V+F-", "V-F+", "V-F-"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--temp", type=float, default=0.0)
    ap.add_argument("--reps", type=int, default=3)
    args = ap.parse_args()

    if not API_KEY:
        print("FEHLER: DEEPSEEK_API_KEY nicht gesetzt")
        sys.exit(1)

    cases = load_problem_cases()
    if args.limit:
        cases = cases[: args.limit]

    sys_vign = prompts.REGION_FLYABILITY_PROMPT
    sys_novign = strip_vignettes(sys_vign)
    removed = len(sys_vign) - len(sys_novign)
    print(f"Vignetten-Ablation, {len(cases)} Cases | Modell={MODEL} "
          f"temp={args.temp} reps={args.reps}")
    print(f"System-Prompt: {len(sys_vign)} chars | ohne Vignetten: {len(sys_novign)} "
          f"(−{removed} chars)")
    if removed < 200:
        print("WARNUNG: Vignetten-Strip hat fast nichts entfernt — Regex prüfen!")

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=45.0, max_retries=2)
    tok = {"in": 0, "out": 0}

    # Wetterdaten/Few-Shot je Case einmal vorbereiten (deterministisch).
    prepped = []
    for case in cases:
        _, gt = effective_rating(case)
        base = build_user_message(case)
        block, _ = fewshot_block_excluding(case)
        msg_fs = (block + "\n" + base) if block else base
        prepped.append((case, gt, base, msg_fs))
    gts = [gt for _, gt, _, _ in prepped]
    ziel = sum(gts) / len(gts)

    def run_once(rep_idx: int, show_table: bool) -> dict:
        """Ein kompletter Durchlauf aller Cases × Arme. Returns arm -> MAE."""
        rec = {a: [] for a in ARMS}
        if show_table:
            print(f"\n--- Rep {rep_idx+1}: Pro-Case-Tabelle ---")
            print(f"{'#':>3} {'Region':<24} {'gt':>2} " + " ".join(f"{a:>4}" for a in ARMS))
            print("-" * 60)
        for i, (case, gt, base, msg_fs) in enumerate(prepped, 1):
            name = (case.get("spot_or_region_id") or "?")[:24]
            row = {}
            for arm in ARMS:
                sysp = sys_vign if arm.startswith("V+") else sys_novign
                usr = msg_fs if arm.endswith("F+") else base
                try:
                    r, u = call_llm(client, sysp, usr, args.temp)
                except Exception as exc:
                    r, u = None, None
                    print(f"    {arm} fail: {exc}")
                if u:
                    tok["in"] += u.prompt_tokens
                    tok["out"] += u.completion_tokens
                row[arm] = r
                rec[arm].append((gt, r))
                time.sleep(0.1)
            if show_table:
                print(f"{i:>3} {name:<24} {gt:>2} " + " ".join(f"{str(row[a]):>4}" for a in ARMS))

        out = {}
        for arm in ARMS:
            pair = [(g, r) for g, r in rec[arm] if r is not None]
            n = len(pair)
            out[arm] = sum(abs(r - g) for g, r in pair) / n if n else float("nan")
        return out

    # Reps laufen lassen.
    per_rep = []
    for rep in range(args.reps):
        per_rep.append(run_once(rep, show_table=(rep == 0)))
        print(f"\nRep {rep+1} MAE: " + "  ".join(f"{a}={per_rep[-1][a]:.3f}" for a in ARMS))

    # Aggregat ueber Reps.
    print("\n" + "=" * 60)
    print(f"AGGREGAT ueber {args.reps} Reps (temp={args.temp}) | Pilot-Ziel Ø={ziel:.2f}")
    print("=" * 60)
    print(f"{'Arm':<6} {'MAE-Mittel':>11} {'MAE-Spanne':>22}")
    mean_mae = {}
    for arm in ARMS:
        vals = [pr[arm] for pr in per_rep]
        mean_mae[arm] = sum(vals) / len(vals)
        print(f"{arm:<6} {mean_mae[arm]:>11.3f}   [{min(vals):.3f} .. {max(vals):.3f}]")

    print("\nSCHLUESSEL-VERGLEICHE (Mittel-MAE, kleiner=besser):")
    print(f"  Few-Shot-Effekt MIT Vignetten:   {mean_mae['V+F-']:.3f} → {mean_mae['V+F+']:.3f}  "
          f"(Δ {mean_mae['V+F+']-mean_mae['V+F-']:+.3f})")
    print(f"  Few-Shot-Effekt OHNE Vignetten:  {mean_mae['V-F-']:.3f} → {mean_mae['V-F+']:.3f}  "
          f"(Δ {mean_mae['V-F+']-mean_mae['V-F-']:+.3f})")
    print(f"  'Labels statt Vignetten' (V-F+) vs heute (V+F+): "
          f"{mean_mae['V+F+']:.3f} → {mean_mae['V-F+']:.3f}  (Δ {mean_mae['V-F+']-mean_mae['V+F+']:+.3f})")

    cost = (tok["in"] / 1e6 * 0.27) + (tok["out"] / 1e6 * 1.10)
    print(f"\nTokens: {tok['in']} in + {tok['out']} out = ~${cost:.3f}")


if __name__ == "__main__":
    main()
