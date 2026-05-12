═══════════════════════════════════════════════
TEIL 4: STRECKENFLUG (nur Spot)
═══════════════════════════════════════════════

Synthese aus Spot-Bewertung + Region-Kontext: Wie gut eignet sich der Tag von DIESEM Spot aus fuer Strecke? → `streckenflug.tier`: `kein_xc / lokal / moderat / top`.

═══════════════════════════════════════════════
REGION-KONTEXT NUTZEN
═══════════════════════════════════════════════

Im Datenblock findest du einen Abschnitt **`### REGION-KONTEXT (bereits analysiert)`**. Dieser enthaelt die vorab durchgefuehrte Bewertung der Flugregion, in welcher der Spot liegt. **Nutze diesen Kontext ausschliesslich fuer TEIL 4 (Streckenflug)** — fuer die anderen Teile bewertest du den Spot weiterhin eigenstaendig.

Moegliche Inhalte:
- `flight_category`, `peak_climb_rate`, `thermal_quality` der Region
- `wind_calm_count`, `wind_moderate_count`, `wind_strong_count` (Region-weite Wind-Stunden)
- `xc_potential`, `xc_details`, `summary` der Region

**Wenn der Abschnitt fehlt oder `Region-Kontext: nicht verfuegbar` steht:**
- Setze `streckenflug.tier` basierend NUR auf Spot-Daten (kein XC-Boost moeglich → tier max "moderat").
- Setze `streckenflug.region_context_available = false`.
- Erwaehne im `streckenflug.summary`: "Region-Kontext fehlt — reine Spot-Einschaetzung."

**Synthese-Regeln (wenn Region-Kontext vorhanden):**
- **`top`**: Spot `flight_category ∈ {xc_tag, klassiker}` UND Region `flight_category ∈ {xc_tag, klassiker}` UND `wind_strong_count = 0`.
- **`moderat`**: Spot `flight_category ∈ {starker_thermikflug, xc_tag, klassiker}` UND Region `flight_category ∈ {solider_thermikflug, starker_thermikflug, xc_tag, klassiker}`.
- **`lokal`**: Spot fliegbar (Spot category mind. `kurzer_thermikflug`), aber Region-Thermik schwach (Region category ≤ `solider_thermikflug`) — nur lokale Thermik, keine Strecke.
- **`kein_xc`**: `safety_status = not_safe` ODER Spot `flight_category ∈ {abgleiter, soaring, kurzer_thermikflug}` ODER `flight_type ∈ {Abgleiter, Soaring}` ODER Region `wind_strong_count ≥ 4h`.

**Konflikt-Check (PFLICHT):**
Wenn Spot fliegbar aber Region hat ≥ 2h WIND-STRONG oder Warnung bzgl. Hoehenwind/Foehn → `streckenflug.tier` max "lokal", und `streckenflug.limiting_factor = "region_wind_aloft"`, im `summary` explizit die Region-Hoehenwinde mit Zahl erwaehnen.

Wenn Spot + Region beide stark: im `summary` das XC-Potenzial konkret beschreiben (z.B. Richtung, realistische Kilometer aus `xc_details` der Region).
