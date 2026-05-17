═══════════════════════════════════════════════
TEIL 4: STRECKENFLUG (nur Spot, Rating 1–5)
═══════════════════════════════════════════════

Synthese aus Spot-Bewertung + Region-Kontext → `streckenflug.rating` (Integer **1–5**).

**Eigene Achse, unabhaengig vom Spot-`experience_rating`.** Spot lokal top (4), Region schwach → Streckenflug 2-3. Spot mittel (3), Region stark + ruhig → Streckenflug 4-5.

─────────────────────────────────
SKALA
─────────────────────────────────

| Rating | Bedeutung |
|---|---|
| **1** | Nichts fliegbar / Abgleiter |
| **2** | Lokal (Hangsoaring/Hausrunde) |
| **3** | Kurzes Wegfliegen (Talquerung, ~10-30km) |
| **4** | Weit (~30-100km XC, FAI-Dreiecke) |
| **5** | Klassiker (>100km, Top-XC) |

─────────────────────────────────
REGION-KONTEXT NUTZEN
─────────────────────────────────

Datenblock enthaelt Abschnitt **`### REGION-KONTEXT (bereits analysiert)`** mit:
- `experience_rating`, `peak_climb_rate`, `thermal_quality` der Region
- `wind_calm_count`, `wind_moderate_count`, `wind_strong_count`
- `summary` der Region

**Wenn fehlt oder `nicht verfuegbar`:** Setze rating NUR aus Spot-Daten (kein XC-Boost moeglich → max **3**). `limiting_factor = "region_context_missing"`.

─────────────────────────────────
SYNTHESE-REGELN
─────────────────────────────────

- **Rating 5:** Spot=5 UND Region=5 UND `wind_strong_count = 0`.
- **Rating 4:** Spot ∈ {4,5} UND Region ∈ {4,5} UND `wind_strong_count < 2h`.
- **Rating 3:** Spot ∈ {3,4,5} UND Region ∈ {3,4,5}.
- **Rating 2:** Spot fliegbar (≥2) aber Region schwach (≤2) ODER Region ≥2h Hoehenwind/Foehn → nur lokal.
- **Rating 1:** `safety_status = not_safe` ODER Spot = 1 ODER Region `wind_strong_count ≥ 4h`.

**Konflikt-Check (PFLICHT):** Spot fliegbar aber Region ≥2h WIND-STRONG / Hoehenwind / Foehn → rating max **2** mit `limiting_factor = "region_wind_aloft"`.

─────────────────────────────────
LIMITING_FACTOR (Schluessel)
─────────────────────────────────

- `"none"` — kein limitierender Faktor (rating ≥ 4)
- `"spot_not_flyable"` — Safety verhindert XC
- `"spot_wind_direction"` — Wind aus falschem Sektor am Spot
- `"region_wind_aloft"` — Hoehenwind in Region zu kraeftig
- `"weak_regional_thermals"` — Region-Thermik schwach (≤2)
- `"ceiling_low"` — Basis zu tief fuer XC
- `"abgleiter_only"` — kein nennenswerter Thermikflug
- `"region_context_missing"` — Region nicht verfuegbar

Bei Rating 1: IMMER `limiting_factor` setzen. Bei Rating 5: `"none"`.

─────────────────────────────────
JSON-OUTPUT
─────────────────────────────────

```json
"streckenflug": {
  "rating": 3,
  "limiting_factor": "ceiling_low"
}
```

KEINE weiteren Felder. KEIN `tier`, KEIN `summary`. Streckenflug-Prosa gehoert in `xc_details` im Haupt-Output.
