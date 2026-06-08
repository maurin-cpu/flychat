"""
Smoke-Test: OpenAI Prompt-Cache-Hit-Rate fuer Spot- und Region-Analysen.

Feuert 5 Spot-Analysen + 3 Region-Analysen sequenziell ab und misst pro Call:
- Prompt-Tokens gesamt
- Davon gecacht (cached_tokens aus response.usage.prompt_tokens_details)
- Hit-Rate

Erwartung: Erster Call = 0% (Cache-Miss), Folge-Calls >= 80% (System-Prompt stabil).
Dauerhafte Hit-Rate < 30% --> Cache-Invalidation-Problem (z.B. variables Datum am Prompt-Anfang).
"""
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
from prompts import SPOT_COMBINED_PROMPT, REGION_COMBINED_PROMPT
from chat_engine import WingcastEngine
from source_area import get_all_regions
from spots import load_spots

api_key = os.environ.get("OPENAI_API_KEY")
model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
if not api_key:
    print("FEHLER: OPENAI_API_KEY nicht gesetzt")
    sys.exit(1)

client = OpenAI(api_key=api_key, timeout=120.0)

print(f"Model: {model}")
print(f"SPOT_COMBINED_PROMPT:   ~{int(len(SPOT_COMBINED_PROMPT)/3.5)} tokens")
print(f"REGION_COMBINED_PROMPT: ~{int(len(REGION_COMBINED_PROMPT)/3.5)} tokens")
print()

# --- Engine laden ---
print("Lade Engine + gecachte Wetterdaten...")
engine = WingcastEngine()
engine.load_weather_from_cache()

date_str = datetime.now().strftime("%Y-%m-%d")
print(f"Datum: {date_str}")
print()

# --- Preise (Stand April 2026) ---
# gpt-4o-mini: input $0.15 / 1M, cached $0.075 / 1M (50% off), output $0.60 / 1M
PRICE_INPUT = 0.15 / 1_000_000
PRICE_CACHED = 0.075 / 1_000_000
PRICE_OUTPUT = 0.60 / 1_000_000


def run_llm(system_prompt: str, user_content: str, label: str):
    """Feuert 1 LLM-Call + extrahiert Cache-Metriken."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        max_tokens=1100,
        response_format={"type": "json_object"},
    )
    usage = response.usage
    prompt_tok = usage.prompt_tokens
    output_tok = usage.completion_tokens
    details = getattr(usage, "prompt_tokens_details", None)
    cached_tok = getattr(details, "cached_tokens", 0) if details else 0
    uncached_tok = prompt_tok - cached_tok
    hit_rate = cached_tok / prompt_tok if prompt_tok else 0.0

    cost_nocache = prompt_tok * PRICE_INPUT + output_tok * PRICE_OUTPUT
    cost_actual = uncached_tok * PRICE_INPUT + cached_tok * PRICE_CACHED + output_tok * PRICE_OUTPUT
    savings = cost_nocache - cost_actual

    print(
        f"  [{label:20s}] prompt={prompt_tok:5d}  cached={cached_tok:5d}  "
        f"hit={hit_rate*100:5.1f}%  output={output_tok:4d}  "
        f"kosten=${cost_actual*1000:.4f}/1k  gespart=${savings*1000:.4f}/1k"
    )
    return {
        "prompt": prompt_tok,
        "cached": cached_tok,
        "uncached": uncached_tok,
        "output": output_tok,
        "hit_rate": hit_rate,
        "cost_actual": cost_actual,
        "cost_nocache": cost_nocache,
    }


# --- Spots sammeln (5 Stueck mit Kontext) ---
print("=" * 78)
print("SPOT-ANALYSEN (5 sequenziell)")
print("=" * 78)

all_spots = load_spots()
spot_calls = []
picked = 0
for spot in all_spots:
    if picked >= 5:
        break
    ctx = engine._build_single_spot_context(spot, date_str) if hasattr(engine, '_build_single_spot_context') else None
    if not ctx:
        continue
    user_msg = (
        f"AKTUELLE LOKALZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"{ctx}"
    )
    label = f"spot #{picked+1} {spot['name'][:12]}"
    res = run_llm(SPOT_COMBINED_PROMPT, user_msg, label)
    spot_calls.append(res)
    picked += 1

if not spot_calls:
    print("  Kein Spot-Kontext verfuegbar - refresh_weather noetig?")

# --- Regionen (3 sequenziell) ---
print()
print("=" * 78)
print("REGION-ANALYSEN (3 sequenziell)")
print("=" * 78)

all_regions = get_all_regions()
region_calls = []
picked = 0
for region in all_regions:
    if picked >= 3:
        break
    ctx = engine._build_single_region_context(region, date_str)
    if not ctx:
        continue
    user_msg = (
        f"AKTUELLE LOKALZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"{ctx}"
    )
    label = f"region #{picked+1} {region['region'][:10]}"
    res = run_llm(REGION_COMBINED_PROMPT, user_msg, label)
    region_calls.append(res)
    picked += 1

# --- Zusammenfassung ---
print()
print("=" * 78)
print("ZUSAMMENFASSUNG")
print("=" * 78)

for name, calls in [("Spot", spot_calls), ("Region", region_calls)]:
    if not calls:
        continue
    total_prompt = sum(c["prompt"] for c in calls)
    total_cached = sum(c["cached"] for c in calls)
    total_output = sum(c["output"] for c in calls)
    total_cost = sum(c["cost_actual"] for c in calls)
    total_nocache = sum(c["cost_nocache"] for c in calls)
    overall_hit = total_cached / total_prompt if total_prompt else 0
    saved_pct = (total_nocache - total_cost) / total_nocache * 100 if total_nocache else 0

    print(f"\n{name}-Analysen ({len(calls)} Calls):")
    print(f"  Prompt-Tokens total:  {total_prompt:,}")
    print(f"  Davon gecacht:        {total_cached:,}  ({overall_hit*100:.1f}%)")
    print(f"  Output-Tokens total:  {total_output:,}")
    print(f"  Tatsaechliche Kosten: ${total_cost*1000:.4f} / 1k Calls")
    print(f"  Ohne Cache:           ${total_nocache*1000:.4f} / 1k Calls")
    print(f"  Ersparnis durch Cache: {saved_pct:.1f}%")

    # Hochrechnung auf Produktivlauf
    if name == "Spot":
        scale = 2435 / len(calls)
    else:
        scale = 150 / len(calls)
    print(f"  Hochrechnung auf {int(len(calls)*scale)} Calls/Produktivlauf:")
    print(f"    Mit Cache:    ${total_cost * scale:.4f}")
    print(f"    Ohne Cache:   ${total_nocache * scale:.4f}")
    print(f"    Gespart:      ${(total_nocache - total_cost) * scale:.4f} / Lauf")

print()
print("Interpretation:")
print("  Erster Call jedes Blocks: Hit-Rate ~0%    (Cache-Miss, normal)")
print("  Folge-Calls:              Hit-Rate >=80%  = Caching funktioniert")
print("  Folge-Calls <30%:         Cache-Invalidation-Problem untersuchen")
