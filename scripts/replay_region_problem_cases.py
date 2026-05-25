"""
Region-Replay: testet die Spot-5-Problem-Cases gegen den aktuellen Skill
(Schranke 3 gestrichen, Vignetten eingefuegt, Rating-5 weicher).

Filtert Cases mit LLM-Rating=5 + Pilot-Korrektur ungleich 5 (Region-Problemzone).
Nutzt REGION_FLYABILITY_PROMPT mit dem aktuellen Skill.

Usage: python scripts/replay_region_problem_cases.py [--limit N]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import prompts
from openai import OpenAI

DATA = Path(__file__).resolve().parent.parent / "data" / "labeled_examples.jsonl"
API_KEY = os.environ.get("DEEPSEEK_API_KEY")
BASE_URL = "https://api.deepseek.com/v1"
MODEL = "deepseek-chat"


def effective_rating(entry):
    llm = (entry.get("llm_output_full") or {}).get("experience_rating")
    fb = entry.get("user_feedback") or {}
    lab = fb.get("label")
    corr = fb.get("corrected_experience_rating")
    if lab == "richtig":
        return llm, llm
    if corr is not None:
        return llm, corr
    return llm, None


def load_problem_cases():
    """Region-Problem-Cases: LLM=5 mit Pilot-Korrektur < 5."""
    rows = []
    with open(DATA, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    out = []
    for r in rows:
        if r.get("entity_type") != "region":
            continue
        llm, gt = effective_rating(r)
        if llm != 5 or gt is None or gt == 5:
            continue
        agg = (r.get("weather_input") or {}).get("aggregates") or {}
        if agg.get("sustained_peak_mps") is None:
            continue
        out.append(r)
    return out


def build_user_message(case):
    name = case.get("spot_or_region_id", "?")
    date = case.get("target_date", "?")
    tier = case.get("terrain_tier", "?")
    agg = (case.get("weather_input") or {}).get("aggregates") or {}

    peak = agg.get("sustained_peak_mps")
    prod_h = agg.get("productive_h_strict")
    wh = agg.get("working_height_agl_m")
    cloud = agg.get("cloud_structure")
    low = agg.get("low_cloud_max") or 0
    mid = agg.get("mid_cloud_max") or 0

    orig_safety = (case.get("llm_output_full") or {}).get("safety", {})
    safety_status = orig_safety.get("status", "safe") if isinstance(orig_safety, dict) else "safe"

    now_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    parts = [
        f"AKTUELLE LOKALZEIT: {now_local}",
        "",
        f"REGION: {name}",
        f"  terrain_tier: {tier}",
        f"  target_date:  {date}",
        "",
        "WETTER-AGGREGATE (vor-berechnet):",
        f"→ RATING-INPUTS: prod_h_strict={prod_h}h (Climb ≥1.5 m/s), "
        f"sustained_peak={peak} m/s (max ueber 2h, kein Einzelspike), "
        f"working_height_agl={wh}m (Median Thermik-Top), "
        f"cloud_structure={cloud} (low={low}% mid={mid}%). "
        f"Diese Werte nutzt die Kategorien-Wahl direkt — nicht selbst nachzaehlen.",
        "",
        "SAFETY-RESULT (separat berechnet, hier nur Status):",
        f"  status: {safety_status}",
        "",
        "AUFGABE: Vergib experience_rating (1-5) gemaess Skill. JSON-Output mit "
        "mindestens den Feldern: experience_rating, recommendation.",
    ]
    return "\n".join(parts)


def call_llm(client, system_prompt, user_msg):
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.2,
        max_tokens=1500,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content or "{}"
    return raw, resp.usage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if not API_KEY:
        print("FEHLER: DEEPSEEK_API_KEY nicht gesetzt")
        sys.exit(1)

    cases = load_problem_cases()
    if args.limit:
        cases = cases[: args.limit]
    print(f"Replay {len(cases)} Region-Problem-Cases (LLM=5, Pilot<5) gegen aktuelles Skill")
    print(f"Modell: {MODEL}")
    print()

    system_prompt = prompts.REGION_FLYABILITY_PROMPT
    print(f"System-Prompt: {len(system_prompt)} chars")
    print()

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    new_dist = Counter()
    matches_gt = 0
    still_five = 0
    total_in = 0
    total_out = 0

    for i, case in enumerate(cases, 1):
        name = case.get("spot_or_region_id")
        llm_orig, gt = effective_rating(case)
        user_msg = build_user_message(case)
        try:
            raw, usage = call_llm(client, system_prompt, user_msg)
            parsed = json.loads(raw)
            new_rating = parsed.get("experience_rating")
            recommendation = parsed.get("recommendation", "")[:80]
        except Exception as exc:
            new_rating = None
            recommendation = f"ERROR: {exc}"
            usage = None

        total_in += usage.prompt_tokens if usage else 0
        total_out += usage.completion_tokens if usage else 0

        matched = "OK" if new_rating == gt else "--"
        if new_rating == 5:
            still_five += 1
        if new_rating == gt:
            matches_gt += 1
        new_dist[new_rating] += 1

        print(f"[{i:>2}/{len(cases)}] {name:<28s} orig=5 gt={gt} new={new_rating} {matched}  "
              f"{recommendation}")
        time.sleep(0.3)

    print()
    print("=" * 60)
    print("REGION-ERGEBNIS-ZUSAMMENFASSUNG")
    print("=" * 60)
    print(f"Cases: {len(cases)}")
    print(f"Original LLM-Rating: alle 5 (Problem-Cases mit Korrektur)")
    print()
    print(f"Neue Rating-Verteilung:")
    for r in sorted(new_dist.keys(), key=lambda x: (x is None, x)):
        n = new_dist[r]
        print(f"  Rating {r}: {n} ({n/len(cases)*100:.0f}%)")
    print()
    print(f"Treffer gegen Pilot-GT: {matches_gt}/{len(cases)} = {matches_gt/len(cases)*100:.0f}%")
    print(f"Immer noch Rating 5:    {still_five}/{len(cases)} = {still_five/len(cases)*100:.0f}%")
    print()
    cost = (total_in / 1e6 * 0.27) + (total_out / 1e6 * 1.10)
    print(f"Tokens: {total_in} in + {total_out} out = ~${cost:.3f}")


if __name__ == "__main__":
    main()
