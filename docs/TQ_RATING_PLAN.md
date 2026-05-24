# Plan — TQ-Tags (SHEAR/TORN/ROUGH) via Segment-Anteil ins experience_rating

**Status:** Entwurf, vom User approved. Ausführung pausiert.
**Erstellt:** 2026-05-23
**Kontext:** Diskussion in Chat-Session, ausgelöst durch User-Frage "sollen TQ-Tags Flugqualität beeinflussen?".

---

## Problemstellung

Heute (Stand 2026-05-23) haben die drei TQ-Mechanismen **null deterministische Wirkung** auf `experience_rating`:

- **SHEAR-UNUSABLE** und **THERMAL-TORN-UNUSABLE**: keine Decision feuert, Skill verbietet dem LLM die Nutzung (`04_flight_subratings_spot.md:15-17`)
- **THERMAL-ROUGH-UNUSABLE**: triggert nur Safety (`safe→conditional` bei `rough_pct>50%` via `decide_flyability_mech_danger`)
- `productive_thermal_h` zählt SHEAR/TORN-UNUSABLE-Stunden **als produktiv** (meteorologisch falsch — zerrissene Blase ist nicht nutzbar)
- LLM sieht zwar Coverage-Counts, darf sie aber nicht fürs Rating verwerten

**Veraltete Memory-Notiz:** "SHEAR/TORN cappen bei max violet→green, ROUGH triggert gray-Downgrade" — die alten `decide_flyability_low_reward`-Funktionen sind weg (`decision_engine.py:509-513`), nur Klapper-Safety blieb.

---

## Meteo-Fundierung

Die drei Mechanismen sind physikalisch unabhängig und gut belegt (`meteo_research/wind_shear_thermal_quality.md`):

| Tag | Mechanismus | Quelle | Schwelle (Voralpen) |
|---|---|---|---|
| **SHEAR** | Vertikale Windänderung kippt Blasen | meteoblue, DHV, Glendening | 1.5 / 2.5 km/h/100m |
| **TORN** | B/S-Ratio Auftriebs- vs. Scher-Produktion | Glendening RASP | B/S<5 / <3 |
| **ROUGH** | Mechanische Turbulenz mischt Blase | Whiteman, Stull | GF≥1 / ≥2 |
| **WIND** | Grundwind durch BLH verhindert Ablösung | DHV, Whiteman | 25 / 32 km/h |

**Wichtiger Befund:** `weather_context.py:1106-1174` berechnet bereits **pro Segment** der Thermiksäule eigene Tags und gibt `tq_ratio = {"total": 8, "clean": 7, "tags": {"SHEAR-DEG": 1}}` zurück. Diese Segment-Granularität wird heute nur als String fürs LLM gerendert — der binäre Hourly-Tag (Worst-Case über alle Segmente) ist der, der in `productive_thermal_h` und Cache-Counter geht.

**User-Insight:** Eine Stunde mit SHEAR nur im obersten Segment (7/8 sauber) ist meteorologisch nutzbar — der Pilot fliegt einfach niedriger.

---

## Kern-Prinzip

Alle drei TQ-Mechanismen werden **segment-granular** ausgewertet. Eine Stunde gilt als produktiv, wenn **≥66% der Thermiksäule sauber** sind. Kein binärer Worst-Case-Tag mehr für Produktivitäts-/Safety-Logik.

**User-Entscheidungen:**
- Schwelle: **0.66** für produktiv
- **Keine** Altitude-Gewichtung (einfacher Prozent-Cut)
- **ROUGH** wird ebenfalls anteilig (nicht binär), Safety-Decision auch über Segment-Anteil

**Kein deterministischer Rating-Cap** — LLM bewertet mit Intensität/Trend/Coverage. Doppel-Counting-Schutz via Skill-Regel.

---

## Schritt 1 — `tq_ratio` in den Hourly-Cache schreiben

**Goal:** Segment-Granularität verfügbar, wo `productive_thermal_h` und Safety-Decisions sie brauchen.

**File:** `engine/weather_context.py`

**Änderungen:**
- `_thermal_quality_tags` (L988-1176) schreibt `tq_ratio` heute nur ins `debug`-Dict
- Aufrufer (Spot ~L1780-1820, Region ~L2960-2990) müssen `tq_ratio` aus `debug` in den Stunden-Datensatz übernehmen
- Pro Stunde ableiten und in Hourly-Datensatz speichern:
  - `tq_clean_pct = clean / total`
  - `rough_clean_pct = (total - tags.get("ROUGH-UNU", 0)) / total`
  - `shear_clean_pct = (total - tags.get("SHEAR-UNU", 0)) / total`
  - `torn_clean_pct = (total - tags.get("TORN-UNU", 0)) / total`

**Verify:** Cache-Inspektion eines Spots — Stundenobjekte enthalten neue Felder.

---

## Schritt 2 — `productive_thermal_h` nutzt 66%-Cut

**Goal:** Stunden mit überwiegend zerrissener Säule fallen aus dem Produktiv-Zähler. Stunden mit nur oben SHEAR/TORN bleiben drin.

**Files:** `engine/weather_context.py` — 3 Stellen analog

- L1929-1936 (Spot `productive_thermal_h`)
- ~L2669 (Region `productive_thermal_h`)
- ~L4752 (Batch-Pfad)

**Change:**
```python
# alt:
"[THERMAL-ROUGH-UNUSABLE]" not in unusable_hits
and "[THERMAL-WIND-UNUSABLE]" not in unusable_hits

# neu:
hour["tq_clean_pct"] >= 0.66
and "[THERMAL-WIND-UNUSABLE]" not in unusable_hits
```

**Begründung WIND bleibt binär:** Wenn Grundwind > Zone-Schwelle, kann sich Blase gar nicht erst organisiert ablösen — kein Säulen-Effekt, sondern Bodenproblem.

**Cloud-Maxima bleiben unverändert.**

**Verify:**
- Vignette: Tag mit SHEAR nur in oberstem Segment (7/8 = 87%) → bleibt produktiv
- Vignette: Tag mit SHEAR über halbe Säule (4/8 = 50%) → fällt raus
- Bestehende Tests in `tests/test_decision_engine.py` ggf. Erwartungswerte updaten

---

## Schritt 3 — Safety-Decision `decide_flyability_mech_danger` segment-basiert

**Goal:** ROUGH → `safe→conditional` triggert nicht mehr bei "Stunde hatte irgendwo ROUGH" sondern bei "Stunden, in denen >50% der Säule ROUGH waren".

**File:** `engine/decision_engine.py:518-562`

**Change:**
```python
# alt:
rough_h = tq.get("rough_danger_h", 0)
rough_pct = (rough_h / tht) * 100
if rough_pct <= 50: return None

# neu:
rough_affected_h = tq.get("rough_affected_h", 0)  # vorberechnet in weather_context.py
rough_affected_pct = (rough_affected_h / tht) * 100
if rough_affected_pct <= 50: return None
```

`rough_affected_h` wird in `weather_context.py` aggregiert: Anzahl Thermikstunden mit `rough_clean_pct < 0.5`.

**Verify:**
- Bestehender Test: Tag mit 6/8 Stunden hartem ROUGH (ganze Säule) bleibt `conditional`
- Neu: Tag mit 6/8 Stunden ROUGH nur oben (rough_clean_pct=0.87) bleibt `safe`

---

## Schritt 4 — Cache-Aggregate für LLM-Kontext

**Goal:** LLM sieht Segment-Severity, nicht nur Stunden-Counts.

**File:** `engine/weather_context.py:2284-2295` (Spot-Cache) + `:3237-3244` (Region)

**Neue Felder:**
- `tq_clean_ratio_avg` — Ø `clean_pct` über alle Thermikstunden
- `tq_partial_hours` — Stunden mit `0.5 ≤ clean_pct < 0.66` (LLM: "teilweise nutzbar")
- `tq_zerrissen_hours` — Stunden mit `clean_pct < 0.5`
- Pro Mechanismus: `shear_affected_h`, `torn_affected_h`, `rough_affected_h` (mech_clean_pct<0.5)

**LLM-Kontext-Block** (`weather_context.py:2334-2384`) zeigt:

```
THERMIK-QUALITÄT (Säulen-Anteile):
- 3h überwiegend zerrissen (<50% sauber), 2h teilweise (50-66%)
- Mechanismen: SHEAR 4h, TORN 2h, ROUGH 1h (>50% Säule betroffen)
- Ø Säulen-Reinheit: 78%
```

**Verify:**
- Cache-Snapshot zeigt neue Felder
- `score_regression.py` Reverse-Parser ergänzen (Memory SYNC-PFLICHT)

---

## Schritt 5 — LLM-Skill öffnen

**Files:**
- `skills/shared/04_flyability/01_tags_flyability.md:8-14` — Verbot lockern
- `skills/shared/04_flyability/04_flight_subratings_spot.md:15-17` — TQ aus Ignore-Liste raus
- `skills/shared/04_flyability/04_flight_subratings_region.md:15-17` — analog
- `skills/shared/04_flyability/03_prose_style.md:5,18` — Prosa-Verbot lockern

**Neue Skill-Regel (Wortlaut):**

> **TQ-Tags und experience_rating**
>
> TQ wird segment-granular ausgewertet — eine SHEAR-Stunde mit 7/8 Segmenten sauber heißt: nur das oberste Achtel der Säule ist betroffen, der Pilot fliegt einfach niedriger. Das ist kein Rating-Killer.
>
> Dämpfe das experience_rating um 1 Stufe, wenn:
> - `tq_zerrissen_hours ≥ 50%` der Thermikstunden (überwiegend zerrissene Säulen) ODER
> - ein einzelner Mechanismus (SHEAR/TORN/ROUGH) `affected_h ≥ 50%`
>
> **Doppel-Counting:** SHEAR und TORN korrelieren physikalisch (Scherung erzeugt B/S<3). Treten sie zusammen auf, zähle sie als EINEN Mechanismus.
>
> **Trend:** Stunden-Verteilung beachten — TQ vormittags + clean nachmittags = bessere Bewertung als verteilt.
>
> ROUGH-affected ≥50% triggert via Decision-Engine bereits `safe→conditional` (Safety-Pfad).

**Verify (3 Vignetten manuell durch LLM, DeepSeek):**
1. Clean Tag, climb 2.5, prod_h 6 → Rating 5
2. 6h TORN über ganze Säule → Rating 3-4
3. 6h SHEAR nur oberstes Segment (clean_pct 0.87) → Rating 4-5 (kaum gedämpft)
4. 6h SHEAR + 6h TORN gleichzeitig über halbe Säule → Rating 3 (korreliert, einmal zählen)

---

## Bewusst NICHT im Plan

- ❌ Deterministischer Cap "unusable_pct>50 → max 4" — Doppel-Counting-Falle, ignoriert Trend
- ❌ TQ in `safety_status` reinziehen (außer ROUGH-Klapper, bleibt wie heute)
- ❌ Trend-Berechnung im Code (`_compute_tq_trend`) — Stunden-Liste reicht dem LLM
- ❌ Intensitäts-Felder wie `shear_excess_kmh100m` — erst wenn Binärtags zu grob
- ❌ Altitude-Gewichtung (User-Entscheidung: einfacher Prozent-Cut)

---

## Reihenfolge

1. **Schritt 1 + 2 zusammen** — Cache-Schreiben + 66%-Cut für `productive_thermal_h`
2. **Schritt 3** — Safety-Decision auf Segment-Anteil
3. **Schritt 4** — Aggregate für LLM-Kontext
4. **Schritt 5** — Skill öffnen (erst wenn 1-4 stabil)

---

## Sync-Pflicht (durch alle Schritte)

- `docs/RATING_ARCHITECTURE.md` — TQ jetzt LLM-Rating-Input, Segment-Granularität
- `docs/DECISIONS.md` — `decide_flyability_mech_danger` Logik auf Segment-Anteil aktualisiert
- `docs/TAGS.md` — Segment-Ratio-Auswertung dokumentieren
- `memory/rating_v2_architecture.md` + `memory/MEMORY.md` — veraltete "max violet→green"-Notiz raus, neue Segment-Logik rein
- `score_regression.py` — neue Cache-Felder im Reverse-Parser

---

## Offene Punkte / Risiken

- **Tests:** Bestehende Tests in `tests/test_decision_engine.py` (32 Tests) müssen durchlaufen. Wo Erwartungswerte sich ändern (Tag mit ROUGH nur oben blieb `conditional`, soll jetzt `safe` bleiben), bewusst updaten und im Test-Kommentar dokumentieren.
- **Score-Regression-Cache:** Per Memory `score_regression_caches.md` — neue Decision-Logik braucht passenden Reverse-Parser, sonst Test-Blindheit.
- **Goldene Vignetten:** `cost_testing/golden/` enthält viele Spot-Snapshots — manche Ratings werden sich ändern. Nach Schritt 5 Stichproben prüfen.
- **Cache-Invalidierung:** Bestehende `wetterdaten.json` Felder fehlen — beim ersten Lauf nach Deployment werden Tag-Aggregate neu berechnet.

---

## Wiedereinstieg

Beim nächsten Mal: lies dieses File, dann starte mit Schritt 1+2 zusammen (`engine/weather_context.py` — Hourly-Cache befüllen + Produktiv-Check umstellen). Schritt 3 direkt danach in `engine/decision_engine.py`. Vignetten-Tests erst nach Schritt 4.
