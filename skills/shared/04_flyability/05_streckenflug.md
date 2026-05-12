═══════════════════════════════════════════════
TEIL 4: STRECKENFLUG (nur Spot, Rating 1–6)
═══════════════════════════════════════════════

Synthese aus Spot-Bewertung + Region-Kontext: Wie gut eignet sich der Tag
von DIESEM Spot aus fuer Strecke? → `streckenflug.rating` als Integer **1–6**.

**Eigene Achse, unabhaengig vom Spot-`experience_rating`.** Spot kann lokal
top sein (rating 4), aber Region zeigt schwache Thermik → Streckenflug
limitiert (rating 2-3). Umgekehrt: Spot mittelmaessig (rating 3), Region
stark + ruhig → Streckenflug moeglich (rating 4-5).

═══════════════════════════════════════════════
STRECKENFLUG-SKALA (1-6)
═══════════════════════════════════════════════

| Rating | Bedeutung |
|---|---|
| **1** | Nichts fliegbar / Abgleiter-Niveau — keine Strecke moeglich |
| **2** | Nur ganz kurz fliegbar (wenige Minuten Hangflug) |
| **3** | Lokal fliegbar, kein Wegfliegen (Soaring laenger, am Spot bleibend) |
| **4** | Kurzes Wegfliegen moeglich (Talquerung, ~10–30km) |
| **5** | Weit (~30–150km XC, FAI-Dreiecke) |
| **6** | Klassiker (>150km, Top-XC-Tag) |

═══════════════════════════════════════════════
REGION-KONTEXT NUTZEN
═══════════════════════════════════════════════

Im Datenblock findest du einen Abschnitt **`### REGION-KONTEXT (bereits
analysiert)`**. Dieser enthaelt die vorab durchgefuehrte Bewertung der
Flugregion. **Nutze diesen Kontext fuer TEIL 4 (Streckenflug)** — fuer
die anderen Teile bewertest du den Spot weiterhin eigenstaendig.

Moegliche Inhalte:
- `experience_rating`, `peak_climb_rate`, `thermal_quality` der Region
- `wind_calm_count`, `wind_moderate_count`, `wind_strong_count` (Region-Wind)
- `summary` der Region

**Wenn der Abschnitt fehlt oder `Region-Kontext: nicht verfuegbar` steht:**
- Setze `streckenflug.rating` basierend NUR auf Spot-Daten (kein XC-Boost
  moeglich → rating max **4**).
- Erwaehne im `limiting_factor`: "region_context_missing".

═══════════════════════════════════════════════
SYNTHESE-REGELN (mit Region-Kontext)
═══════════════════════════════════════════════

**Rating 6 (klassiker):**
- Spot `experience_rating ∈ {5, 6}` UND Region `experience_rating ∈ {5, 6}`
  UND `wind_strong_count = 0`.

**Rating 5 (weit):**
- Spot `experience_rating ∈ {4, 5, 6}` UND Region `experience_rating ∈ {4, 5, 6}`
  UND `wind_strong_count < 2h`.

**Rating 4 (kurz wegfliegen):**
- Spot `experience_rating ∈ {3, 4, 5, 6}` UND Region `experience_rating ∈ {3, 4, 5, 6}`.

**Rating 3 (lokal, kein Wegfliegen):**
- Spot fliegbar (rating ≥ 2), aber Region-Thermik schwach (Region rating ≤ 2)
  ODER Region zeigt ≥ 2h Hoehenwind/Foehn-Warnung → nur lokal, keine Strecke.

**Rating 2 (ganz kurz):**
- Spot rating = 2 (kurzer_thermikflug) ODER Spot-Bemerkung "Mindestwind
  nicht erreicht" → nur ganz kurzer Flug moeglich.

**Rating 1 (nichts):**
- `safety_status = not_safe` ODER Spot `experience_rating = 1` ODER
  Region `wind_strong_count ≥ 4h`.

═══════════════════════════════════════════════
KONFLIKT-CHECK (PFLICHT)
═══════════════════════════════════════════════

Wenn Spot fliegbar aber Region hat ≥ 2h WIND-STRONG oder Warnung bzgl.
Hoehenwind/Foehn → `streckenflug.rating` max **3** (lokal), und
`limiting_factor = "region_wind_aloft"` mit Zahl-Bezug.

Wenn Spot + Region beide stark: `limiting_factor = "none"` und Rating
spiegelt das XC-Potenzial wider.

═══════════════════════════════════════════════
LIMITING_FACTOR (Schluessel)
═══════════════════════════════════════════════

Optional, kurzer String. Erlaubte Werte:
- `"none"` — kein limitierender Faktor (rating ≥ 5)
- `"spot_not_flyable"` — Safety verhindert XC
- `"spot_wind_direction"` — Wind aus falschem Sektor am Spot
- `"region_wind_aloft"` — Hoehenwind in der Region zu kraeftig
- `"weak_regional_thermals"` — Region-Thermik schwach (rating ≤ 2)
- `"ceiling_low"` — Basis bleibt zu tief fuer XC
- `"abgleiter_only"` — kein nennenswerter Thermikflug
- `"region_context_missing"` — Region nicht verfuegbar (Fallback)

Bei Rating 1: setze IMMER einen `limiting_factor` (warum nichts geht).
Bei Rating 6: `limiting_factor = "none"`.

═══════════════════════════════════════════════
JSON-FELDER (Spot-Output)
═══════════════════════════════════════════════

```json
"streckenflug": {
  "rating": 4,
  "limiting_factor": "ceiling_low"
}
```

KEINE weiteren Felder. KEIN `tier`, KEIN `summary`, KEIN `region_context_available`,
KEIN `rating`-Begriff in Prosa. Wenn du Streckenflug-Prosa schreiben willst,
nutze `xc_details` im Haupt-Output.
