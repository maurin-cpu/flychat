"""
Ablations-Studie (SPOT-Variante): Sind die statischen PILOTEN-VIGNETTEN im
Spot-Skill durch die dynamischen Few-Shot-Labels ersetzbar?

Spot-Pendant zu scripts/ab_vignette_ablation.py (das nur Regionen testet).
Gleiche 4-Arm-Logik, aber auf Spot-Problemfaellen, mit dem Spot-Prompt und
dem Spot-Few-Shot-Retrieval (entity_type="spot", inkl. weicher Regions-
Praeferenz _W_REGION_PENALTY).

4 Arme auf denselben Spot-Problem-Cases (LLM=5, Pilot<5), einziger Unterschied
ist Vignetten an/aus  x  Few-Shot an/aus:
  V+F+  Vignetten + Few-Shot   (~Produktion nach Spot-Pfad-Deploy)
  V+F-  Vignetten, kein Few-Shot
  V-F+  KEINE Vignetten + Few-Shot   <- "statt Vignetten die Labels"
  V-F-  KEINE Vignetten, kein Few-Shot

Self-Ausschluss im Few-Shot-Block: der replayte Fall wird aus seinem eigenen
Retrieval entfernt (zur Analysezeit existierte sein Label noch nicht).

WICHTIG — Abdeckung: load_problem_cases (Spot) filtert auf tier in
(alpen, voralpen) + working_height < 900m. Duenne Tiers (jura, mittelland,
hochalpin) sind hier NICHT vertreten — die Vignetten-Entbehrlichkeit dort
bleibt ungetestet.

Usage: python scripts/ab_vignette_ablation_spot.py [--limit N] [--temp 0.0] [--reps 3]
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
from engine import labeled_examples as le
from scripts.replay_problem_cases import (
    build_user_message,
    effective_rating,
    load_problem_cases,
)

API_KEY = os.environ.get("DEEPSEEK_API_KEY")
BASE_URL = "https://api.deepseek.com/v1"
MODEL = "deepseek-chat"

# Schneidet den PILOTEN-VIGNETTEN-Abschnitt heraus (Divider+Header bis zur
# Abschluss-Zeile). Harte Schranken + Region-Cap bleiben erhalten. Identische
# Regex wie die Region-Ablation — matcht im Spot-Prompt ebenso (verifiziert).
_VIGNETTE_RE = re.compile(
    r"─{5,}\s*\nPILOTEN-VIGNETTEN.*?Sonst gilt: dein Pilotenurteil zaehlt, nicht eine Checkliste\.",
    re.DOTALL,
)


def strip_vignettes(prompt: str) -> str:
    return _VIGNETTE_RE.sub(
        "(Vignetten-Abschnitt fuer dieses Experiment entfernt.)", prompt
    )


def fewshot_block_excluding(case) -> str:
    """Few-Shot-Block fuer den Spot-Fall, OHNE den Fall selbst (Self-Ausschluss).

    Mirror von ab_fewshot_region.fewshot_block_excluding, aber entity_type="spot".
    _extract_features_from_label liefert fuer Spots auch die analyse_region mit,
    sodass retrieve_similar die weiche Regions-Praeferenz anwendet.
    """
    feats = le._extract_features_from_label(case)
    if feats is None:
        return ""
    cid = case.get("spot_or_region_id")
    cdate = case.get("target_date")
    hits = le.retrieve_similar(feats, top_k=4, entity_type="spot")
    hits = [h for h in hits
            if not (h.get("spot_or_region_id") == cid and h.get("target_date") == cdate)][:3]
    if not hits:
        return ""
    return le.format_for_prompt(hits)


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

    sys_vign = prompts.SPOT_FLYABILITY_PROMPT
    sys_novign = strip_vignettes(sys_vign)
    removed = len(sys_vign) - len(sys_novign)
    print(f"Vignetten-Ablation SPOT, {len(cases)} Cases | Modell={MODEL} "
          f"temp={args.temp} reps={args.reps}")
    print(f"System-Prompt: {len(sys_vign)} chars | ohne Vignetten: {len(sys_novign)} "
          f"(-{removed} chars)")
    if removed < 200:
        print("WARNUNG: Vignetten-Strip hat fast nichts entfernt - Regex pruefen!")

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=45.0, max_retries=2)
    tok = {"in": 0, "out": 0}

    # Wetterdaten/Few-Shot je Case einmal vorbereiten (deterministisch).
    prepped = []
    n_with_block = 0
    for case in cases:
        _, gt = effective_rating(case)
        base = build_user_message(case)
        block = fewshot_block_excluding(case)
        if block:
            n_with_block += 1
        msg_fs = (block + "\n" + base) if block else base
        prepped.append((case, gt, base, msg_fs))
    gts = [gt for _, gt, _, _ in prepped]
    ziel = sum(gts) / len(gts)
    print(f"Few-Shot-Block verfuegbar fuer {n_with_block}/{len(prepped)} Cases "
          f"(sonst faellt F+ auf F- zurueck)")

    def run_once(rep_idx: int, show_table: bool) -> dict:
        """Ein kompletter Durchlauf aller Cases x Arme. Returns arm -> MAE."""
        rec = {a: [] for a in ARMS}
        if show_table:
            print(f"\n--- Rep {rep_idx+1}: Pro-Case-Tabelle ---")
            print(f"{'#':>3} {'Spot':<28} {'gt':>2} " + " ".join(f"{a:>4}" for a in ARMS))
            print("-" * 64)
        for i, (case, gt, base, msg_fs) in enumerate(prepped, 1):
            name = (case.get("spot_or_region_id") or "?")[:28]
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
                print(f"{i:>3} {name:<28} {gt:>2} " + " ".join(f"{str(row[a]):>4}" for a in ARMS))

        out = {}
        for arm in ARMS:
            pair = [(g, r) for g, r in rec[arm] if r is not None]
            n = len(pair)
            out[arm] = sum(abs(r - g) for g, r in pair) / n if n else float("nan")
        return out

    per_rep = []
    for rep in range(args.reps):
        per_rep.append(run_once(rep, show_table=(rep == 0)))
        print(f"\nRep {rep+1} MAE: " + "  ".join(f"{a}={per_rep[-1][a]:.3f}" for a in ARMS))

    print("\n" + "=" * 64)
    print(f"AGGREGAT ueber {args.reps} Reps (temp={args.temp}) | Pilot-Ziel Oe={ziel:.2f}")
    print("=" * 64)
    print(f"{'Arm':<6} {'MAE-Mittel':>11} {'MAE-Spanne':>22}")
    mean_mae = {}
    for arm in ARMS:
        vals = [pr[arm] for pr in per_rep]
        mean_mae[arm] = sum(vals) / len(vals)
        print(f"{arm:<6} {mean_mae[arm]:>11.3f}   [{min(vals):.3f} .. {max(vals):.3f}]")

    print("\nSCHLUESSEL-VERGLEICHE (Mittel-MAE, kleiner=besser):")
    print(f"  Few-Shot-Effekt MIT Vignetten:   {mean_mae['V+F-']:.3f} -> {mean_mae['V+F+']:.3f}  "
          f"(D {mean_mae['V+F+']-mean_mae['V+F-']:+.3f})")
    print(f"  Few-Shot-Effekt OHNE Vignetten:  {mean_mae['V-F-']:.3f} -> {mean_mae['V-F+']:.3f}  "
          f"(D {mean_mae['V-F+']-mean_mae['V-F-']:+.3f})")
    print(f"  'Labels statt Vignetten' (V-F+) vs heute (V+F+): "
          f"{mean_mae['V+F+']:.3f} -> {mean_mae['V-F+']:.3f}  (D {mean_mae['V-F+']-mean_mae['V+F+']:+.3f})")

    cost = (tok["in"] / 1e6 * 0.27) + (tok["out"] / 1e6 * 1.10)
    print(f"\nTokens: {tok['in']} in + {tok['out']} out = ~${cost:.3f}")


if __name__ == "__main__":
    main()
