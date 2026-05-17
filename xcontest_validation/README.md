# XContest Validation — Forecast vs. Realität

## Zweck

Wir sammeln hier laufend Auszüge der XContest-Tageswertung (Top-N Flüge Schweiz) und
gleichen sie mit unseren Region- und Spot-Ratings für denselben Tag ab. Ziel ist, über
Zeit ein Daten-Korpus aufzubauen, mit dem wir systematische Forecast-Fehler
identifizieren und die Kalibrierung optimieren können.

## Wichtige Einschränkung — was XContest sagt und was nicht

- XContest zeigt **nur die guten Flüge** (typischerweise ab ~40 km, je nach Liga).
- **Viele Flüge ab Spot X** = Spot war an dem Tag mit hoher Sicherheit gut fliegbar
  (Lower Bound auf Bedingungen).
- **Wenige oder keine Flüge ab Spot X** ≠ Spot war schlecht. Mögliche Gründe für
  Abwesenheit:
  - Wenige Piloten in der Region
  - Topografie macht 40+ km Strecken unattraktiv
  - Wochentag / Wetter-Vorbericht hat Piloten anderswohin gelockt
  - Spot fehlt in unserer DB (Coverage-Lücke)

→ **Wir leiten aus "0 Launches" keine Aussage über unser Rating ab.**

## Was wir pro Tag dokumentieren

In `YYYY-MM-DD.md`:

1. **Rohdaten-Zusammenfassung**: Top-N Flüge mit Startplatz, Distanz, Airtime, Startzeit
2. **Region-Vergleich**: Tabelle Launches-pro-Region × unser Rating (safety/exp/xc/status)
3. **Spot-Vergleich**: Tabelle Launches-pro-Spot × unser Rating
4. **Findings**, gegliedert in:
   - Confirms (Rating passt zur Realität)
   - Underrated (wir zu vorsichtig — Rating tiefer als Real-Performance)
   - False-Positives (wir not_safe / harte Warnung, aber Spot war fliegbar)
   - Coverage-Gaps (produktive Spots fehlen in unserer DB)
   - Bugs / Anomalien (z.B. `limiting_factor: region_context_missing`)

## Was wir in `PATTERNS.md` akkumulieren

Wiederkehrende Issues über mehrere Tage — pro Issue:
- Welche Spots/Regionen
- Wie oft schon gesehen (Tageszähler)
- Mögliche Ursache (welche Decision/Regel feuert?)
- Status (offen / in Untersuchung / gefixt / nicht reproduzierbar)

So wird die Datei selbst zum Optimierungs-Backlog.

## Methodik im Detail

- **Datenquelle**: Manuelle Eingabe via Chat (User postet XContest-Top-100-Auszug)
- **Region-Mapping**: Spotname → Region via `data/fluggebiete_complete.csv`
  (Spalte `analyse_region`); für nicht-gelistete Spots manuelles Mapping basierend
  auf Geografie
- **Spot-Mapping**: Direkte Lookup in `data/spot_analyses.json`; bei
  Nicht-Treffer fuzzy-match (Prefix) und Variante-Namen prüfen
- **Rating-Quelle**: `data/region_analyses.json` und `data/spot_analyses.json`,
  jeweils für den XContest-Tag
- **Felder pro Eintrag**:
  - `safety_rating` (1-10, 0 wenn not_safe)
  - `experience_rating` (1-5)
  - `streckenflug.rating` (1-5)
  - `status` (safe / conditional / not_safe)
  - `_decisions_applied` (Liste der gefeuerten Decision-Engine-Regeln)

## Sample-Größe Roadmap

- ≥10 Tage: erste belastbare Muster sichtbar
- ≥30 Tage: regionale Verteilung statistisch tragfähig
- ≥3 Monate: Saisonale Muster, Kalibrierungs-Empfehlungen pro Terrain-Tier möglich

## File-Convention

- `YYYY-MM-DD.md` — eine Datei pro analysiertem XContest-Tag
- `PATTERNS.md` — akkumulierter Issue-Tracker, wird bei jeder Analyse aktualisiert
- `README.md` — diese Datei

Keine Auto-Generierung, kein Skript. Manuell, aber konsistent dokumentiert.
