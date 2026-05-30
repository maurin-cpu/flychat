# Few-Shot-Pipeline — Plan

> **Status:**
>   - Schritt 1 (Labels sammeln): **live**.
>   - Schritt 2 (Retrieval + Prompt-Injection): **live** seit 2026-05-15 (Region-Pfad).
>     Spot-Pfad + weiche Regions-Präferenz **implementiert 2026-05-30, noch nicht
>     deployed** (uncommitted; Engine-Code braucht Service-Restart). Details unten.
>   - Schritt 3 (Eval-Suite): noch nicht implementiert.
> **Erstellt:** 2026-05-12
> **Scope:** Schritte 1-3 einer LLM-Kalibrierungs-Strategie. Schritt 4 (Auto-Prompt-Optimization via DSPy) ist ausserhalb dieses Plans.
>
> **Siehe auch den Abschnitt „Update 2026-05-30" weiter unten** — empirischer Nachweis, dass Few-Shot-Labels und die Skill-Vignetten **Substitute** sind.

## Schritt 2 — Wie es konkret arbeitet (Stand 2026-05-15)

**Code-Stellen:**
- `engine/labeled_examples.py`: `_load_label_index()`, `retrieve_similar()`,
  `format_for_prompt()`, `build_few_shot_block()` — In-Memory-Index mit
  mtime-Invalidation, distanz-basierte Top-k-Suche.
- `engine/analyzers.py::_build_few_shot_for()`: liest Live-Features aus
  `_ctx_tq_cache`, ruft Retrieval, schreibt Decision-Tag in
  `_ctx_fewshot_cache`.
- `engine/analyzers.py::_flyability_analysis_single_region_day` und
  Batch-Pfad (Z. ~2430): injizieren den Beispiel-Block im User-Prompt
  **vor** dem Wetter-Kontext.
- `engine/analyzers.py::_post_process_flyability_region`: haengt den
  Decision-Tag aus `_ctx_fewshot_cache` an `_decisions_applied`.
- `chat_engine.py`: `_ctx_fewshot_cache = {}` initialisiert, wird zusammen
  mit den anderen ctx-Caches geleert.

**Features fuer Similarity-Matching (per Region/Tag):**
- `terrain_tier` (mittelland | jura | voralpen | alpen | hochalpin)
- `sustained_peak_mps` (aus `_ctx_tq_cache`)
- `productive_h_strict` (Stunden mit Climb ≥ 1.5 m/s)
- `avg_low_cloud_thermal_h` / `avg_mid_cloud_thermal_h` (Schnitt ueber
  Thermikstunden)

**Distanz-Metrik:**
```
dist = 3.0 × |peak_diff| + 0.5 × |prod_h_diff|
       + 0.05 × |low_diff| + 0.05 × |mid_diff|
```
Skill: Peak ist wichtigstes Signal (×3), dann Dauer, dann Wolken.

**Retrieval-Strategie:**
1. Filter auf `entity_type == "region"` AND gleichen `terrain_tier`.
2. Wenn Pool < `MIN_TIER_POOL` (3): erweitere auf Nachbar-Tiere
   (TIER_NEIGHBOURS Mapping).
3. Wenn immer noch leer: `FewShot:none(tier=X)`, kein Block.
4. Top-3 nach Distanz, in Prompt injiziert.

**Konfigurations-Konstanten** (engine/labeled_examples.py):
- `MAX_LABEL_AGE_DAYS = 90` — Saison-Drift-Schutz.
- `MIN_TIER_POOL = 3` — Schwelle fuer Tier-Nachbarschafts-Fallback.
- Distanz-Gewichte `_W_PEAK = 3.0`, `_W_PROD_H = 0.5`, `_W_CLOUD = 0.05`.

**Decision-Tags (sichtbar in `_decisions_applied`):**
- `FewShot:hochalpin,3 examples` — 3 Labels injiziert.
- `FewShot:none(tier=jura)` — leerer Pool, kein Block.
- `FewShot:none(no_tq_cache)` — Cache-Miss (sollte nicht passieren).
- `FewShot:none(incomplete_features)` — peak oder prod_h null.

**Coverage heute (2026-05-15):**
- 26 von 40 Labels haben vollstaendige Aggregates (peak/prod_h gesetzt).
- 14 aeltere Labels stammen aus der Zeit vor `_attach_rating_inputs`
  und werden ignoriert — Backfill via Re-Analyse moeglich.
- Pool pro Tier: hochalpin 15, mittelland 12, alpen 7, voralpen 3, jura 3.
- Spots haben 0 Labels — Few-Shot wirkt nur auf Region-Calls.

**Tests:** `tests/test_few_shot.py` (18 Tests).

## Update 2026-05-30 — Spot-Pfad, Regions-Präferenz & Wirksamkeit

> **Code-Stand: implementiert, Tests grün (18), aber NICHT committed/deployed.**
> Engine-Code → Gleitcast-Service (:5000) braucht Restart, damit es greift.

### A) Spot-Pfad verdrahtet

Die Retrieval-/Storage-Schicht war schon entity-type-fähig (`retrieve_similar(entity_type=…)`,
`build_few_shot_block(entity_type=…)`), aber im Spot-Flyability-Call nirgends aufgerufen.
141 Spot-Labels lagen ungenutzt. Drei Stellen in `engine/analyzers.py` ergänzt:

1. `_flyability_analysis_single_spot_day` — injiziert den Block vor dem Kontext
   (analog Region), `entity_type="spot"`.
2. Batch-Pfad in `run_all_analyses_batch_stream` (Spot-Flyability-Phase) — dito.
3. `_post_process_flyability_spot` — hängt den `FewShot:`-Decision-Tag an
   `_decisions_applied`.

Cache-Key für Spots ist `f"{name}|{date_str}"` (= `_ctx_tq_cache`-Key aus
`weather_context.py`, identisch zu dem, was `_build_few_shot_for` erwartet).

### B) Weiche Regions-Präferenz für Spots

**Problem:** Ø nur ~1,2 Labels/Spot (120 Spots, max 4) — „5 Labels vom selben Spot"
gibt es nie. Das Retrieval poolt deshalb über den `terrain_tier`, nicht pro Spot.
Was fehlte: **Lokalität** (gleiche Region / geografische Nähe floss nicht ins Ranking).

**Lösung:** weicher Distanz-Aufschlag `_W_REGION_PENALTY = 1.5` in `retrieve_similar`,
**nur für `entity_type=="spot"`** — Kandidaten aus fremder `analyse_region` bekommen
den Aufschlag, ein deutlich wetter-ähnlicherer Nachbar-Tag schlägt ihn aber weiterhin.
Kein hartes Region-Filtern (würde dünne Regionen verhungern lassen: nur 13 von 20
Regionen haben ≥3 Labels). `analyse_region` wandert dazu in den Index
(`_extract_features_from_label`) und in die Query (`_build_few_shot_for(..., region=…)`,
Spot-Aufrufer übergeben `spot.get("analyse_region")`).

**Empirisch (Leave-one-out, alle Spot-Labels):** Anteil Nachbarn aus *gleicher* Region
steigt **39 % → 63 %**, 0 leere Retrievals (Pool unverändert, nur Reihenfolge). Stärke
über `_W_REGION_PENALTY` justierbar.

### C) Wirkt Few-Shot überhaupt? — und das Vignetten-Verhältnis

Das LLM bewertet **systematisch zu optimistisch** (Region 65 %, Spot 62 % der Labels
„zu_optimistisch"; Ø ~1 Punkt zu hoch). Untersucht mit zwei Replay-Harnessen gegen das
Produktionsmodell `deepseek-chat` (Self-Ausschluss des replayten Falls aus dem Retrieval):

- `scripts/ab_fewshot_region.py` — A/B mit/ohne Few-Shot auf Region-Problemfällen
  (LLM=5, Pilot<5).
- `scripts/ab_vignette_ablation.py` — 4-Arm V±/F± (Vignetten an/aus × Few-Shot an/aus),
  Flags `--reps`, `--temp`.

**Kernbefund (über 3 Läufe konsistent, MAE = mittl. Abstand zum Pilot-Ziel, kleiner=besser):**

| Arm | nur Vignetten | nur Labels | beide | weder noch |
|---|---|---|---|---|
| MAE | ~0,41 | ~0,44 | ~0,41–0,44 | ~0,6–0,7 |

→ **Vignetten und Few-Shot-Labels sind Substitute, keine Komplemente.** Beide bekämpfen
denselben Optimismus-Fehler. Few-Shot *auf* den Vignetten draufgesetzt bringt keinen
messbaren Zusatznutzen (redundant, nicht blockiert). **Mindestens einer** der beiden
Mechanismen ist nötig — ohne beides bricht die Kalibrierung ein. „Labels statt
Vignetten" (V−F+ ≈ V+F+) hält die Qualität und ist self-updating; auch bei temp=0
reproduziert.

Die Vignetten liegen in `skills/shared/04_flyability/04_flight_subratings_{spot,region}.md`
(Abschnitt „PILOTEN-VIGNETTEN"); die harten Schranken (`peak<2.5 → max 4`,
`peak<1.0 → max 1`) und die Region-Cap-Tabelle sind **separat** und bleiben.

**Wichtige Einschränkung:** n=27 Region-Fälle, Ganzzahl-Ratings → MAE-Differenzen von
~0,04 entsprechen *einem* Fall; V+F+/V+F−/V−F+ sind innerhalb des Rauschens
ununterscheidbar. **Robust** ist nur „mindestens einer nötig" und „Labels können
Vignetten ersetzen". Spots haben keine Few-Shot-Historie → Substituierbarkeit dort
strukturell plausibel, aber nicht direkt belegt.

### Offene Fix-Richtungen (analysiert, nicht umgesetzt)

1. **Vignetten verschlanken/streichen, auf Labels setzen** — Handpflege weg,
   self-updating; Daten sagen, Qualität hält.
2. **Few-Shot-Block verbindlicher formulieren** (harte aggregierte Anweisung statt
   weichem „folge … wenn ähnlich", Platzierung näher an der Entscheidung). Gegen
   Überkorrektur: Streuung der Nachbar-Ratings berücksichtigen.

### Architektur-Frage: Brauchen wir den Rating-Skill noch, oder reicht Labels-only?

Aufgeworfen 2026-05-30: Wenn Labels und Vignetten Substitute sind — könnte man das
Rating *direkt* aus den Labels machen und den Skill weglassen, weil der Skill die
Labels „übersteuert"?

**Was die Daten dazu sagen (und was nicht):** Die Ablation entfernte nur die Vignetten,
nicht „den Skill". Wichtig ist der **V−F−**-Arm (voller Skill ohne Vignetten, ohne
Labels): das war der **optimistischste** Arm (Ø 4,48, MAE ~0,6–0,7). → Der Rubric
(Skala + Schranken + Region-Cap) übersteuert die Labels **nicht nach oben**; er ist
selbst zu optimistisch und *braucht* eine Korrektur. Vignetten und Labels sind beide
nur Korrektur-Patches darauf. Die Optimismus-Tendenz kommt von großzügigen Schwellen
(z. B. Peak ≥ 2,5 → 5) + dem Modell-Default, nicht daher, dass der Skill gegen die
Labels „gewinnt".

**Was der Skill leistet, das Labels nicht ersetzen:**
1. **Skala-Definition** — was „3" bedeutet (Labels tragen nur die Zahl).
2. **Harte Caps / Cross-Dependencies** — `peak<2.5→max4`, Region-Cap (hängt von
   `Region.experience_rating` + `working_height_at_spot_m` ab) — Logik, kein Lookup.
3. **Strukturierter Output** — `recommendation`, `thermal_quality`, `summary`,
   `xc_details`, Tags, 8 Safety-Sub-Ratings, `is_conditional`. Labels speichern nichts
   davon.
4. **Cold-Start / Abdeckung** — dünne Tiers/Regionen (jura=3, mittelland=2 Labels)
   hätten im reinen Label-Ansatz kein Signal.
5. **Zirkularität** — Labels wurden *mit* dem Skill im Loop erzeugt (Korrekturen relativ
   zu skill-produzierten Ratings).

**Fazit:** Skill komplett ersetzen → nein (Skala, Caps, Output-Schema, Cold-Start). Der
valide Kern: die *heuristischen* Skill-Teile (Vignetten, evtl. großzügige
Schwellen-Prosa) sind durch Labels ersetzbar; die *strukturellen/definitorischen* Teile
bleiben. Die Frage ist nicht „Skill vs. Labels", sondern **„welche Skill-Teile sind
Heuristik (→ Labels) und welche sind Struktur (→ bleibt)".**

**Testbar:** neuer Ablations-Arm „minimaler Skill" (nur Skala + harte Caps +
Output-Schema, keine Vignetten/heuristische Prosa) **+ Labels**, gegen heute (voller
Skill). Trifft er gleich gut, ist der heuristische Mittelteil entbehrlich. Erweiterung
von `scripts/ab_vignette_ablation.py`.

## Zweck

Die LLM-Analysen (Spot- und Region-Einschätzungen) sollen über echtes Pilot-Feedback kalibriert werden, ohne Fine-Tuning. Mechanismus:

1. Reale Analysen werden vom Nutzer bewertet (Schritt 1).
2. Bei jeder neuen Analyse werden die 3 ähnlichsten gelabelten Fälle in den Prompt injiziert (Schritt 2).
3. Eine Eval-Suite verhindert Regressionen bei Prompt-Änderungen (Schritt 3).

Few-Shot ist **komplementär zur Decision-Engine**, kein Ersatz:

- Decision-Engine (`engine/decision_engine.py`) = harte deterministische Regeln (Safety-kritisch, OverclaimRelax, FoehnCaution etc.).
- Few-Shot = weiche Kalibrierung der LLM-Prosa und der Grauzonen (flight_category, Rating-Tier, Caution-Formulierungen).

---

## Pipeline-Übersicht

```
┌─────────────────────────────────────────────────────────────────┐
│  SCHRITT 1: Daten sammeln (verändert Analyse-Pfad NICHT)        │
│                                                                  │
│  User öffnet Spot → System ruft LLM → Analyse erscheint          │
│                                          │                       │
│                                          ▼                       │
│                              [Feedback-Buttons unten]            │
│                                          │                       │
│                                          ▼                       │
│                              POST /api/feedback                  │
│                                          │                       │
│                                          ▼                       │
│                       data/labeled_examples.jsonl                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (Pool ≥ 5 pro Terrain-Tier)
┌─────────────────────────────────────────────────────────────────┐
│  SCHRITT 2: Retrieval + Prompt-Injection                         │
│                                                                  │
│  User öffnet Spot → Feature-Vektor berechnen                     │
│                  → Top-3 ähnliche Cases aus JSONL holen          │
│                  → in System-Prompt injizieren                   │
│                  → LLM-Call mit Few-Shot                         │
│                  → Analyse erscheint (kalibrierter)              │
│                  → Feedback-Buttons immer noch da → Pool wächst  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  SCHRITT 3: Eval-Suite (Qualitäts-Gate)                          │
│                                                                  │
│  CLI-Tool über JSONL → ruft Prompt-Pfad → vergleicht gegen Label │
│  → Confusion-Matrix + Regressions-Liste                          │
│  → Pre-Deploy-Gate                                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Reihenfolge und Abhängigkeiten

| Schritt | Voraussetzung | Effekt auf System |
|---|---|---|
| 1 | keine | nur Daten-Sammlung, Analyse-Output unverändert |
| 2 | JSONL ≥ 5 Einträge pro genutztem Terrain-Tier | Prompt-Verhalten ändert sich, Few-Shot wirkt |
| 3 | JSONL ≥ 30 Einträge insgesamt | reines Test-/Eval-Tool, kein Produktiv-Pfad |

**Schritt 1 und 2 sind Code-seitig parallel entwickelbar**, aber Schritt 2 wirkt erst, wenn der Pool aus Schritt 1 gefüllt ist. Cold-Start siehe unten.

---

## Schritt 1: Labeled-Examples-Pipeline

### 1.1 UI-Konzept

Pro Spot- und Region-Analyse, am Ende des Detail-Containers:

```
┌─ War diese Einschätzung treffend? ──────────────────────────┐
│  [ Richtig ]  [ Zu optimistisch ]  [ Zu pessimistisch ]     │
│  [ Falscher Tag ▼ ]                                         │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Optional: was hätte stattdessen stehen sollen?        │  │
│  │                                                       │  │
│  └───────────────────────────────────────────────────────┘  │
│                                              [ Senden ]     │
└─────────────────────────────────────────────────────────────┘
```

- **Richtig**: 1-Click, kein Textfeld nötig.
- **Zu optimistisch / Zu pessimistisch**: Klick + optionale Korrektur-Prosa.
- **Falscher Tag**: Dropdown mit den aktuellen Tags der Analyse, User wählt den falschen.
- Bestätigung nach Send: "Danke — fließt in zukünftige Einschätzungen ein."
- Pro Analyse nur 1 Feedback (Dedup via `analysis_id`); zweites Feedback überschreibt das erste.

### 1.2 Endpoint

`POST /api/feedback` in `web.py`:

```
Request body:
{
  "analysis_id": "spot_niederrickenbach_2026-05-08",
  "label": "zu_optimistisch",
  "wrong_tag_topic": null,
  "correction_text": "...",
  "corrected_category": "abgleiter"
}

Response:
{ "ok": true, "stored_at": "2026-05-08T19:00:00" }
```

Server:
1. Lädt analysis_id aus `data/spot_analyses.json` oder `data/region_analyses.json` (Aufbau analog zu bestehendem `/api/analyses`).
2. Lädt zugehörigen Wetter-Slice aus `data/wetterdaten.json` (zum Zeitpunkt der Analyse → cached, sonst aktueller Stand mit Warnung).
3. Baut Snapshot (Schema siehe 1.3).
4. Append-only an `data/labeled_examples.jsonl` mit Lock-File (`labeled_examples.jsonl.lock`).

### 1.3 JSONL-Schema

Eine Zeile pro Eintrag, JSON-Objekt. **Pflichtfelder fett.**

| Feld | Typ | Pflicht | Beschreibung |
|---|---|---|---|
| **`analysis_id`** | string | ja | Eindeutiger Schlüssel: `{spot|region}_{id}_{date}_{window}`, dient als Dedup-Key |
| **`source`** | enum | ja | `production` (aus UI) oder `manual` (Cold-Start-Seeds) |
| **`timestamp`** | ISO-string | ja | Zeitpunkt der Label-Erstellung |
| **`schema_version`** | string | ja | aktuelle Rating-Schema-Version, z.B. `"v1.6"` (aus RATING_CONCEPT.md) |
| **`model_id`** | string | ja | LLM-Modell, das die Original-Analyse erzeugt hat (`claude-sonnet-4-6` etc.) |
| **`prompt_hash`** | string | ja | Hash des verwendeten Skill-Templates + Capabilities-Guide |
| **`spot_or_region_id`** | string | ja | z.B. `"niederrickenbach"` oder `"voralpen_zentral"` |
| **`entity_type`** | enum | ja | `spot` oder `region` |
| **`terrain_tier`** | enum | ja | `mittelland`, `jura`, `voralpen`, `alpen`, `hochalpin` (aus `data/regionen.csv`) |
| **`target_date`** | ISO-date | ja | Datum, für das die Analyse galt |
| **`weather_input`** | object | ja | kompletter Wetter-Slice (siehe 1.4) |
| **`decisions_applied`** | string[] | ja | Inhalt von `result["_decisions_applied"]` |
| **`llm_output_full`** | object | ja | Original-Analyse-Output (Strukturfelder + Prosa) |
| **`user_feedback`** | object | ja | siehe 1.5 |
| `labeled_by` | string | nein | Hash des Users (IP+UA-Hash, GDPR-konform) |
| `notes_internal` | string | nein | freies Feld für manuelle Annotationen (Curation) |

#### 1.4 `weather_input` — was rein muss

Soviel, dass `engine/decision_engine.py` die Decisions reproduzieren kann + soviel, dass der Feature-Vektor (Schritt 2) berechenbar bleibt:

```json
{
  "hourly": { ... slice aus wetterdaten.json für target_date ... },
  "aggregates": {
    "wind_10m_max": 22,
    "wind_850hpa_mean": 35,
    "gust_excess_max": 14,
    "foehn_risk_peak": 4.1,
    "foehn_direction_dominant": "S",
    "climb_peak": 2.4,
    "productive_thermal_h": 5,
    "blh_max": 2100,
    "low_cloud_max": 35,
    "mid_cloud_max": 40,
    "rough_pct": 12
  },
  "elevation_m": 1180,
  "month": 5
}
```

`hourly` ist der schwerste Teil (~5-15 KB pro Tag). Akzeptabel: bei 1000 Labels ~10 MB. JSONL bleibt grep-bar und versionierbar.

#### 1.5 `user_feedback` — Struktur

```json
{
  "label": "zu_optimistisch",
  "wrong_tag_topic": null,
  "wrong_tag_label": null,
  "correction_text": "Föhn 4.1 + 850hPa 42 km/h: abgleiter, nicht soaring.",
  "corrected_category": "abgleiter",
  "corrected_tier": null
}
```

`label` ist ein Enum:

| Wert | Bedeutung |
|---|---|
| `richtig` | Analyse passt, kein Korrekturbedarf |
| `zu_optimistisch` | Bewertung war zu wohlwollend (z.B. soaring statt abgleiter) |
| `zu_pessimistisch` | Bewertung war zu streng (z.B. gray statt green) |
| `falscher_tag` | mindestens 1 Tag ist sachlich falsch — `wrong_tag_topic` + `wrong_tag_label` Pflicht |

`corrected_category` / `corrected_tier`: optional, hochwertig für Few-Shot (zeigt explizit, was hätte sein sollen).

### 1.6 Persistenz-Details

- **Pfad**: `data/labeled_examples.jsonl` (eine JSON pro Zeile, append-only).
- **Atomarität**: `with open(..., "a")` + `fcntl.flock` (Unix). Auf Windows-Dev: simpler in-process lock.
- **Backup**: tägliches Snapshot wie für `spot_analyses.json` (siehe bestehende `*.backup.json`-Konvention).
- **Größenlimit**: ab 50 MB rotieren in `labeled_examples.{YYYY}.jsonl` (vorerst nicht nötig).
- **Versionsverwaltung**: NICHT in Git committed (User-Daten, kann sensitiv sein). `.gitignore` ergänzen.

---

## Schritt 2: Few-Shot-Retrieval

### 2.1 Feature-Vektor

12 Dimensionen, alle z-normalisiert gegen Pool-Statistiken:

| Feature | Quelle (in `weather_input.aggregates`) | Gewicht | Begründung |
|---|---|---|---|
| `wind_10m_max` | direkt | 2.0 | sicherheitskritisch |
| `wind_850hpa_mean` | direkt | 1.5 | Höhenwind-Scherung |
| `gust_excess_max` | direkt | 2.0 | Turbulenz-Treiber |
| `foehn_risk_peak` | direkt | 2.0 | binäre Entscheidung |
| `climb_peak` | direkt | 1.0 | Thermik-Qualität |
| `productive_thermal_h` | direkt | 1.5 | Flyability-Anker |
| `blh_max` | direkt | 0.5 | sekundär |
| `low_cloud_max` | direkt | 0.8 | Wolkendeckel |
| `mid_cloud_max` | direkt | 0.5 | sekundär |
| `season_sin` | `sin(2π·month/12)` | 0.3 | saisonale Kontinuität |
| `season_cos` | `cos(2π·month/12)` | 0.3 | saisonale Kontinuität |
| `rough_pct` | direkt | 1.0 | mech. Turbulenz |

**Harte Filter (NICHT in Distanz):**
- `terrain_tier` muss exakt matchen.
- `foehn_direction_dominant` muss matchen, falls beide Cases `foehn_risk_peak > 2.0`.

### 2.2 Retrieval-Algorithmus

```
1. compute_feature_vector(current_request) → v_q
2. pool = load_labeled_pool()
3. Filter:
   - schema_version == current
   - label ∈ {richtig, zu_optimistisch, zu_pessimistisch, falscher_tag} mit correction_text != None
   - terrain_tier == v_q.terrain_tier
   - abs(month_distance) ≤ 2
4. z-normalize beide Seiten gegen pool_stats
5. distances = [weighted_l2(v_q, p) for p in filtered]
6. top_k = sorted(distances)[:K=3]
7. diversity_check: paarweise Distanz > τ=0.3, sonst ersetze
8. return formatted_examples
```

**Pool-Mindestgröße:** wenn `len(filtered) < 5`, gib `None` zurück → kein Few-Shot für diesen Call (lieber aus als irreführend).

### 2.3 Prompt-Injection-Format

Injiziert in `chat_orchestrator.py` zwischen `CAPABILITIES_GUIDE` und User-Frage:

```
<kalibrierungs_beispiele>
Drei ähnliche Fälle aus dem bisherigen Feedback-Pool. Verwende sie
als Kalibrierungs-Anker, nicht als feste Regeln.

[1] Niederrickenbach, 2026-04-12, Voralpen — RICHTIG bestätigt
   Wetter: Wind 10m 18 km/h, 850hPa 32 km/h SW, Gust-Excess 10,
           Föhn 2.8, Climb 1.6, productive_h 5, Cloud low/mid 30/40%
   Decisions: GustFloor
   Bewertung: flight_category "klassiker", caution: ["Föhn-Tendenz"]

[2] Pilatus, 2026-05-08, Voralpen — KORRIGIERT (war zu optimistisch)
   Wetter: Wind 10m 22 km/h, 850hPa 42 km/h S, Gust-Excess 14,
           Föhn 4.1, Climb 2.4, productive_h 5
   Decisions: FoehnCaution(4.1), AloftConditional
   Ursprünglich: "soaring"
   Korrekt: "abgleiter" — Höhenwind-Scherung + Föhn > 4.0 dominieren
            die starke Thermik.

[3] Brunni, 2026-04-22, Voralpen — RICHTIG bestätigt
   ...
</kalibrierungs_beispiele>
```

**Token-Budget:** ~150-180 Tokens pro Beispiel × 3 ≈ 500 Tokens.
**Hartes Limit pro Beispiel:** 200 Tokens (Truncation am Ende).

Mindestens 1 Korrektur-Case in Top-3, falls verfügbar — dort steckt das eigentliche Lehrsignal.

### 2.4 Code-Integration

**Neues Modul:** `engine/few_shot_retrieval.py`

| Funktion | Zweck |
|---|---|
| `load_labeled_pool() -> list[LabeledCase]` | Liest JSONL, cached in-memory bis Refresh |
| `compute_feature_vector(weather_input, terrain_tier, month) -> np.array` | 12-Dim-Vektor |
| `retrieve_top_k(v_q, pool, k=3) -> list[LabeledCase]` | Filter + Distanz + Diversität |
| `format_for_prompt(cases) -> str` | Render-Block für Prompt |

**Aufrufer:**
- `engine/chat_orchestrator.py` für interaktiven Chat (vor LLM-Call).
- `engine/analyzers.py` in `_post_process_spot` / `_post_process_region` für Batch-Analyse (vor LLM-Call).

**Config in `data/config_overrides.json`:**

```json
{
  "few_shot": {
    "enabled": false,
    "k": 3,
    "min_pool_size_per_tier": 5,
    "max_season_distance_months": 2,
    "diversity_threshold": 0.3,
    "max_tokens_per_example": 200
  }
}
```

Feature-Flag default OFF — wird erst aktiviert, wenn Pool füllt.

### 2.5 Tracking

Jeder Call mit aktivem Few-Shot schreibt in `result["_few_shot_applied"]`:

```json
{
  "active": true,
  "k": 3,
  "case_ids": ["spot_niederrickenbach_2026-04-12", "..."],
  "max_distance": 0.62
}
```

Analog zu `_decisions_applied` — Debug-Pfad.

---

## Schritt 3: Eval-Suite (Andocken)

Erweitert `score_regression.py` um einen Modus `--llm-eval`:

```
python score_regression.py --llm-eval --sample 50
```

**Was passiert:**
1. Lädt 50 Cases aus `labeled_examples.jsonl` mit `label != richtig` (= Cases mit Ground-Truth-Korrektur).
2. Ruft den echten Analyse-Pfad mit dem damaligen `weather_input` auf.
3. Vergleicht aktuelle Ausgabe gegen Ground-Truth:
   - **Strukturell:** `flight_category` match, `flyability_tier` match, Tags-Set Jaccard.
   - **LLM-Judge (optional, `--judge`):** zweiter LLM-Call: "Stimmt die Prosa mit dem Korrektur-Text überein?"
4. Output: Confusion-Matrix + Top-10 Regressionen.

**Integration:** Pre-Deploy als manueller Gate. Später optional in CI.

---

## Cold-Start-Strategie

Schritt 2 wartet sonst Wochen auf Real-Feedback. Workaround: manuelle Seeds direkt im JSONL.

1. Sobald Schritt 1 deployed ist + Schema steht: Pilot schreibt 15-20 Hand-Cases.
2. Verteilung: 3-4 pro Terrain-Tier, gemischt richtig/zu_optimistisch/zu_pessimistisch.
3. Gleiche Struktur wie Real-Cases, nur `source: "manual"`.
4. Filterbar via `source` falls später raus gewünscht.

**Wichtig:** Seed-Cases müssen echte `weather_input`-Slices haben (nicht erfunden). Pfad:

```
1. Pilot wählt ein vergangenes Datum + Spot.
2. Lädt Snapshot aus data/wetterdaten.json (oder Backup).
3. Notiert in JSONL mit korrektem Label + Korrekturtext.
```

---

## Edge-Cases

| Fall | Symptom | Behandlung |
|---|---|---|
| Pool zu klein in einem Tier | < 5 Cases nach Filter | Few-Shot OFF für diesen Call, kein Fallback auf anderes Tier |
| Konflikt-Cases | zwei nahe Inputs, gegensätzliche Labels | Pool-Load loggt Warning, behalte neueren |
| Schema-Drift | Rating v1.6 → v1.7, alte Labels nicht mehr 1:1 | Filter `schema_version == current` beim Pool-Load |
| Decision-Engine-Drift | `decide_*` umdefiniert, alte `decisions_applied` veraltet | Labels markieren LLM-Entscheidung, nicht Strukturfelder (die kommen aus Decision-Engine, nicht aus Pool) |
| Wetter-Cache rotiert | Original-Snapshot weg | `weather_input` ist im JSONL eingebettet, nicht referenziert — robust |
| Token-Inflation | Korrektur-Text zu lang | Hartes Limit 200 Tokens pro Case, Truncation |
| User-Trolling | Spam-Feedback | Rate-Limit pro `labeled_by`-Hash (z.B. 20/Tag), Admin-Review-Flag |
| Mehrfach-Feedback | User klickt nochmal | Dedup via `analysis_id`, zweites Feedback überschreibt erstes |

---

## Sync-Pflicht (an Claude)

Bei Änderungen an:

- **`engine/few_shot_retrieval.py`** (neu): Feature-Vektor, Gewichte, Retrieval-Logik → Tabelle 2.1 + Abschnitt 2.2 hier aktualisieren.
- **`web.py`** `/api/feedback`-Endpoint: Schema-Änderung → Abschnitt 1.2 + 1.3 hier aktualisieren.
- **`docs/RATING_CONCEPT.md`** Schema-Version: alte Labels invalidieren → `schema_version`-Filter dokumentieren.
- **Skill-Templates** in `skills/`: wenn `flight_category`-Enum geändert → Cold-Start-Seeds prüfen.

Suchhilfen: `grep -rn "few_shot" engine/ web.py`, `grep -n "labeled_examples" .`

---

## Offene Fragen (vor Implementation klären)

1. **Auth für `/api/feedback`**: aktuell öffentlich? Soll Feedback nur authentifizierten Subscribern offen sein (`subscriber.py`-Hash)?
2. **Region-vs-Spot-Pool**: getrennte Pools oder gemeinsam mit `entity_type`-Filter? Empfehlung: gemeinsam, mit Filter.
3. **`prompt_hash`-Generierung**: aktuell kein zentraler Hash. Vorschlag: `sha256(skill_template + capabilities_guide + rating_concept_version)[:8]`.
4. **Diversitäts-Threshold τ**: 0.3 ist Bauchgefühl. Wird in Eval-Suite empirisch validiert.
5. **Cold-Start-Seeds wer/wann**: vor oder nach Schritt-1-Deploy? Vorschlag: nach, damit Schema in der Praxis getestet ist.

---

## Timeline (Schätzung)

| Phase | Aufwand | Voraussetzung |
|---|---|---|
| Schritt 1 (UI + Endpoint + Schema) | 2-3 Tage | Plan-Review abgeschlossen |
| Cold-Start-Seeds | 0.5 Tage | Schritt 1 deployed |
| Schritt 2 (Retrieval + Injection) | 2 Tage | Schema stabil, Pool ≥ 15 Seeds |
| Schritt 3 (Eval-Suite) | 1-2 Tage | Pool ≥ 30 Cases |
| Pool-Wachstum auf 100 Cases | 4-8 Wochen | passiv, durch User-Feedback |

---

## Nächste Schritte

1. **Plan-Review** durch Maurin: insbesondere Schema (Abschnitt 1.3-1.5), Feature-Vektor (2.1), offene Fragen.
2. **`.gitignore`** ergänzen: `data/labeled_examples.jsonl`.
3. **Skeleton-Implementation Schritt 1**: leerer Endpoint + Schema-Validator + UI-Widget hinter Feature-Flag.
4. **Cold-Start-Seeds** sobald Schema steht.
