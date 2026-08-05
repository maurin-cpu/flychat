"""Ad-hoc: prueft, ob interne Feld-Namen (sustained_peak etc.) in der
user-facing Prosa durchsickern. Nutzt die Replay-Maschinerie, generiert aber
VOLLE Prosa und grept alle Text-Felder nach den Identifiern.

Usage: python debug_scripts/test_fieldname_leak.py [--limit N]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import os
import prompts
from openai import OpenAI
from scripts.replay_problem_cases import load_problem_cases, build_user_message

IDENTIFIERS = [
    "sustained_peak", "prod_h_strict", "productive_h_strict",
    "working_height_agl", "cloud_structure", "climb_rate", "low_cloud", "mid_cloud",
]
TEXT_FIELDS = ["recommendation", "thermal_quality", "flyability_notes",
               "soaring_options", "summary"]

API_KEY = os.environ.get("DEEPSEEK_API_KEY")
client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com/v1")


def find_leaks(parsed):
    hits = []
    for field in TEXT_FIELDS:
        val = parsed.get(field)
        if not isinstance(val, str):
            continue
        for ident in IDENTIFIERS:
            if re.search(re.escape(ident), val, re.IGNORECASE):
                hits.append((field, ident, val))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()

    cases = load_problem_cases()[: args.limit]
    print(f"Teste {len(cases)} Cases auf Feld-Namen-Leaks\n")
    total_leaks = 0

    for i, case in enumerate(cases, 1):
        name = case.get("spot_or_region_id")
        user_msg = build_user_message(case)
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": prompts.SPOT_FLYABILITY_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2, max_tokens=1500,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(resp.choices[0].message.content or "{}")
        leaks = find_leaks(parsed)
        if leaks:
            total_leaks += len(leaks)
            print(f"[{i}] {name}: LEAK")
            for field, ident, val in leaks:
                print(f"     {field} <- '{ident}': {val[:160]}")
        else:
            print(f"[{i}] {name}: clean")

    print(f"\n{'='*50}\nGesamt-Leaks: {total_leaks}")
    sys.exit(1 if total_leaks else 0)


if __name__ == "__main__":
    main()
