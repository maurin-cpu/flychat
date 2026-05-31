"""
Test: zeigt, dass der Streckenflug-Pflichtsatz (xc_details) jetzt die REGION
als Quelle mit 'weil'/'weshalb' begruendet.

- Nutzt den ECHT zusammengebauten Spot-Flyability-Prompt (prompts.SPOT_FLYABILITY_PROMPT,
  inkl. der angepassten Skill-Bloecke).
- Nutzt den ECHTEN Region-Kontext-Block-Builder (_format_region_context_block).
- Zwei Faelle: starke Region (Rating 5) vs. schwache Region (Rating 2).
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import config
import prompts
from llm_client import build_client
from engine.weather_context import _format_region_context_block

provider = config.ANALYSIS_PROVIDER
model = config.get_model(provider, "analysis")
client = build_client(provider, config.get_api_key(provider))
print(f"Provider={provider}  Model={model}\n")

system_prompt = prompts.SPOT_FLYABILITY_PROMPT


def spot_block(name, elev, ri_line, extra_reserve):
    return (
        f"WETTERDATEN FUER STARTPLATZ: {name} (Hoehe {elev}m MSL) — TAG: 2026-06-01 (Mo)\n"
        f"═══ Kompakt-Tagesprofil (Stunden-/Drucklevel-Zeilen gekuerzt fuer Test) ═══\n"
        f"Verhaeltnis sauber/gesamt: 7/7h = 100%\n"
        f"→ PRODUKTIVE-THERMIK: laut RATING-INPUTS\n"
        f"{ri_line}\n"
        f"{extra_reserve}\n"
    )


def run_case(title, spot_user_block, region_result, spot_region):
    region_ctx = _format_region_context_block(region_result, spot_region)
    safety_ctx = (
        "\n### SICHERHEITSBEWERTUNG (IMMUTABLE) ###\n"
        "safety_status: safe\nsafe_window: 10:00-17:00\n"
        "no_go_reasons: []\ncaution_notes: []\n"
    )
    user_msg = f"{spot_user_block}\n{region_ctx}\n{safety_ctx}"

    print("=" * 78)
    print(title)
    print("=" * 78)
    print("--- REGION-KONTEXT-BLOCK (echt gebaut) ---")
    print(region_ctx)
    print()

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.2,
        max_tokens=1200,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content
    try:
        r = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"JSON-Fehler: {e}\nRAW:\n{raw}")
        return

    print(f"  experience_rating : {r.get('experience_rating')}")
    print(f"  xc_potential      : {r.get('xc_potential')}")
    print(f"  streckenflug      : {r.get('streckenflug')}")
    print(f"  >> xc_details     : {r.get('xc_details')}")
    print()


# ─────────────────────────────────────────────────────────────────────
# FALL A — Starke Region (Wallis, Rating 5), tiefer Spot. Erwartung:
# xc_details begruendet mit 'weil die Region starke Thermik/hohe Basis ...'
# ─────────────────────────────────────────────────────────────────────
region_strong = {
    "region_name": "Zentralwallis",
    "safety": {"safety_status": "safe", "safe_window": "10:00-18:00",
               "wind_calm_count": 8, "wind_moderate_count": 0, "wind_strong_count": 0,
               "foehn_risk": "none"},
    "flyability": {
        "fly_status": "violet", "flight_type": "Thermikflug", "peak_climb_rate": 2.8,
        "thermal_quality": "Kraeftige, saubere Thermik. Peak 2.8 m/s ueber 6h, Basis 3600m MSL, Cu sauber 25%.",
        "xc_potential": "high",
        "xc_details": "Klassiker-Tag, Streckenflug >100km ganztaegig moeglich.",
        "summary": "Hammertag im Wallis — hohe Basis, starke Kerne.",
    },
}
run_case(
    "FALL A — Starke Region (Rating 5) + tiefer Spot (1000m)",
    spot_block(
        "Fiesch (Talstart)", 1050,
        "→ RATING-INPUTS: prod_h_strict=6h, strong_h=4h, avg_climb_prod=2.4 m/s, "
        "sustained_peak=2.7 m/s, working_height_agl=2050m, cloud_structure=cu_clean_top",
        "→ Region-Arbeitshoehe ueber diesem Startplatz (working_height_at_spot_m): "
        "Median 2550m, Max 2600m@14:00, Min 2500m@11:00 (Spannweite 100m).",
    ),
    region_strong,
    {"region": "Zentralwallis", "id": "zentralwallis"},
)

# ─────────────────────────────────────────────────────────────────────
# FALL B — Schwache Region (Rating 2), gleicher Spot. Erwartung:
# xc_details begruendet mit 'weil die Region nur schwache Thermik/tiefe Basis ...'
# ─────────────────────────────────────────────────────────────────────
region_weak = {
    "region_name": "Mittelland West",
    "safety": {"safety_status": "safe", "safe_window": "11:00-16:00",
               "wind_calm_count": 5, "wind_moderate_count": 0, "wind_strong_count": 0,
               "foehn_risk": "none"},
    "flyability": {
        "fly_status": "gray", "flight_type": "Thermikflug", "peak_climb_rate": 1.3,
        "thermal_quality": "Schwache, kurze Thermik. Peak 1.3 m/s, Basis nur 1700m MSL, mixed.",
        "xc_potential": "low",
        "xc_details": "Kaum Strecke — knappe Basis, schwache Kerne.",
        "summary": "Mauer Suchtag im Mittelland.",
    },
}
run_case(
    "FALL B — Schwache Region (Rating 2) + gleicher Spot",
    spot_block(
        "Hausberg", 700,
        "→ RATING-INPUTS: prod_h_strict=3h, strong_h=1h, avg_climb_prod=1.2 m/s, "
        "sustained_peak=1.3 m/s, working_height_agl=900m, cloud_structure=mixed",
        "→ Region-Arbeitshoehe ueber diesem Startplatz (working_height_at_spot_m): "
        "Median 950m, Max 1000m@14:00, Min 850m@12:00 (Spannweite 150m).",
    ),
    region_weak,
    {"region": "Mittelland West", "id": "mittelland_west"},
)
