# LLM-Analyse Kostenreduktion — Konzept

**Status:** Hebel 1 (Skill-Split + 4-Phasen-Flow) im Code umgesetzt — **Qualitäts-Validierung & Kostenmessung offen**
**Auslöser:** Batch-Kosten ~$0.60 → ~$2 pro Lauf seit Commit `a916e88` (3–4× Anstieg)
**Leitprinzip:** *Kostensenkung ohne Qualitätsverlust — gemessen, nicht gehofft.* Jeder Hebel braucht eine numerische Acceptance-Gate, sonst wird er nicht aktiviert.

---

## 1. Diagnose — was sich strukturell geändert hat

### Vorher (Commit `396052e`, vor `a916e88`)
Batch lief in **2 Phasen**:
1. `SAFETY_CHECK_PROMPT` (~19 KB / ~4,900 tokens) — für ALLE Spots
2. `FLYABILITY_PROMPT` (~18 KB / ~4,680 tokens) — **nur für safe/conditional Spots**

→ Ø pro Spot-Tag: `4,900 + 0.5 × 4,680 ≈ 7,240 system tokens`
→ ~50 % der `not_safe`-Spots übersprangen die Flyability-Phase komplett.

### Nachher (HEAD, nach `a916e88` + `c00c6c4`)
Batch nutzt **eine einzige Combined-Phase** mit `SPOT_COMBINED_PROMPT`, komponiert aus `spot_analysis.md` + 7 `shared/`-Blöcken:

| Prompt | vorher | nachher | Faktor |
|---|---|---|---|
| spot system | 41 KB / ~10,300 tok | 72 KB / ~17,920 tok | **2.5×** |
| region system | 29 KB / ~7,160 tok | 65 KB / ~16,210 tok | **2.3×** |
| Context-Builder LOC | 625 | 972 | **1.55×** |

→ Combined läuft jetzt für **jeden** Spot-Tag, der den Pre-Filter passiert.
→ Wegfall des "Skip Flyability bei not_safe" eliminiert die 50%-Ersparnis aus Phase 2.

**Cost-Faktor gesamt:**
`2.5× system tokens × ~1.5× mehr Calls × größerer User-Context ≈ 3–4×` ✓ deckt sich mit Beobachtung.

---

## 2. Hebel zur Kostensenkung (geordnet nach Effekt × Aufwand)

### Hebel 1 — 3-Stufen-Flow: Pre-Filter → Safety → Flyability (GRÖSSTER HEBEL)
**Idee — vom User bestätigter Ziel-Flow:**

```
┌─────────────────────────┐
│ 1. PRE-FILTER           │  deterministisch, kein LLM
│    (engine/analyzers.py │  → kickt offensichtliche not_safe raus
│     _prefilter_not_safe)│    (kein WIND-OK, <3 saubere Stunden,
│                         │     ganztags Regen, etc.)
└────────┬────────────────┘
         │ Rest: alle die NICHT prefilter-not_safe sind
         ▼
┌─────────────────────────┐
│ 2. SAFETY-CHECK (LLM)   │  kleiner Prompt (~5K tokens)
│    SAFETY_CHECK_PROMPT  │  → safe / conditional / not_safe
│    REGION_SAFETY_CHECK_ │
│    PROMPT               │
└────────┬────────────────┘
         │ NUR safe + conditional
         │ (not_safe vom LLM bekommt KEINEN Flyability-Call)
         ▼
┌─────────────────────────┐
│ 3. FLYABILITY (LLM)     │  großer Combined-Prompt (~17K tokens)
│    FLYABILITY_PROMPT    │  → tier (gray/green/violet) + rating
│    REGION_FLYABILITY_   │    + streckenflug + recommendation
│    PROMPT               │
└─────────────────────────┘
```

**Warum das spart:** Der teure 17K-Token-Prompt läuft nur noch für Tage, die wirklich fliegbar sein können. Pre-Filter + Safety eliminieren ~50–70 % der Spots/Tage vor dem teuren Call.

**Umsetzung:**
- `SAFETY_CHECK_PROMPT` + `REGION_SAFETY_CHECK_PROMPT` reaktivieren (Skills existieren in Git-Historie unter `396052e:skills/safety_check.md` etc. → restaurieren oder aus shared-Blöcken neu komponieren, NUR Safety-Teile davon)
- `FLYABILITY_PROMPT` + `REGION_FLYABILITY_PROMPT` reaktivieren (Combined-Prompt minus Safety-Teil)
- Batch-Flow in `engine/analyzers.py` ab Zeile ~1780 (`run_batch_analysis`) auf 3 Stufen umbauen:
  - **Stufe 1**: Pre-Filter (existiert bereits, bleibt)
  - **Stufe 2**: Safety-Batch (Region + Spot, kleiner Prompt)
  - **Stufe 3**: Flyability-Batch (NUR safe/conditional, großer Prompt)
- Post-Processing splitten:
  - Safety-Overrides (`_post_process_safety`) nach Stufe 2
  - Flyability-Overrides (`_post_process_flyability`) nach Stufe 3
- Region-Kontext-Injection in Spot-Flyability bleibt erhalten (wichtig für streckenflug-Tier)

**Referenz-Code für alte 2-Phasen-Implementation:**
```bash
git show 396052e:chat_engine.py | sed -n '4250,4610p'
```

**Aufwand:** Mittel (2–3h). Skills neu komponieren + Batch-Flow umbauen + Post-Processing splitten + Tests.
**Ersparnis:** **40–50 %** (eliminiert ~50–70 % der teuren Flyability-Calls für not_safe-Spots).

---

#### 1.1 Skill-Architektur — wie wird der Split umgesetzt?

**Aktuell (1 Skill, 4 TEILE in einem Prompt):**

```
skills/spot_analysis.md (Template)
  ├─ TEIL 1: Sicherheit (safety_status, safe_window, no_go_reasons, ...)
  ├─ TEIL 2: Fliegbarkeit (fly_status, flight_type, thermal_quality, ...)
  ├─ TEIL 3: Sub-Ratings (thermal/wind/window/xc_rating)
  └─ TEIL 4: Streckenflug (streckenflug.tier, ...)

skills/shared/ (656 Lines, ~56 KB)  — komplett in JEDEM Combined-Call drin
  ├─ _hazard_blocks.md     21 KB  → eigentlich nur SAFETY relevant
  ├─ _flyability_tiers.md   7 KB  → nur FLYABILITY
  ├─ _subratings_tables.md  4 KB  → nur FLYABILITY
  ├─ _tages_override.md     4 KB  → nur FLYABILITY
  ├─ _input_map.md          6 KB  → BEIDE
  ├─ _core_principles.md    5 KB  → BEIDE
  └─ _formulierungs_tab.md  5 KB  → BEIDE
```

**Neu (Skill-Split entlang der Phasen):**

```
skills/
  spot_safety.md         (TEIL 1 + Bemerkungs-Logik Safety-Teil)
  spot_flyability.md     (TEIL 2+3+4 — bekommt Safety-Output als Input injiziert)
  region_safety.md       (analog für Region)
  region_flyability.md
  shared/
    _core_principles.md      → in BEIDEN Skill-Familien
    _input_map.md            → in BEIDEN
    _formulierungs_tab.md    → in BEIDEN
    _hazard_blocks.md        → NUR in *_safety.md  ← der dicke Brocken (21 KB)
    _flyability_tiers.md     → NUR in *_flyability.md
    _subratings_tables.md    → NUR in *_flyability.md
    _tages_override.md       → NUR in *_flyability.md
```

**Token-Mathematik pro Spot-Tag (geschätzt):**

| Stufe | system tokens | läuft wann? |
|---|---|---|
| Pre-Filter | 0 (deterministisch) | immer |
| Safety-LLM | ~7,300 | alles was Pre-Filter passiert |
| Flyability-LLM | ~9,700 | NUR safe/conditional (~50 % aller Spots) |

- Ø effektiv: `7,300 + 0.5 × 9,700 = ~12,150 tokens/Spot-Tag`
- Aktuell: `~17,900 tokens/Spot-Tag` (Combined läuft immer voll)
- → **~32 % Ersparnis** allein durch Skill-Split + Phase-Skip
- Dazu kommt: kleinerer max_tokens-Output für Safety-Phase (600 statt 1100) → weitere Output-Token-Ersparnis

#### 1.2 Drei knifflige Punkte beim Split

1. **Bemerkungs-Logik** (`bemerkung_check`) prüft heute Safety **und** Flyability vermischt im selben Schritt.
   → **Lösung:** Bemerkungen vor dem LLM-Call klassifizieren (SAFETY / FLYABILITY / BEIDES), dann pro Phase nur die relevanten Bemerkungen mitgeben. `bemerkung_check`-Output von Phase 3 enthält dann nur Flyability-Nachjustierungen, Safety-Bemerkungen sind in Phase-2-Output.

2. **Konsistenz Safety ↔ Flyability**: Phase 3 darf **nicht** Safety-Felder ändern, sonst widersprechen sich die Phasen.
   → **Lösung:** Klare Regel im Flyability-Prompt: *"Safety-Status ist Input, gegeben, nicht verhandelbar. Bewerte ausschließlich Flyability/Streckenflug für die safe-Stunden."* Phase-2-Output (`safety_status`, `safe_window`, `caution_notes`) wird als formatierter Block in den User-Content von Phase 3 injiziert (genau wie es im alten 2-Phasen-Code in `396052e` schon gemacht wurde, siehe `safety_context` in der Referenz).

3. **Region-Kontext-Injection** (Streckenflug nutzt Region-Daten): Bleibt wie heute.
   → **Reihenfolge bleibt:** Region-Safety → Region-Flyability → Spot-Safety → Spot-Flyability (mit Region-Result + Spot-Safety als Input). Insgesamt 4 Batch-Phasen statt heute 2 (Region-Combined + Spot-Combined). Mehr Round-Trips, aber jeder einzelne deutlich kleiner und für viele Spots/Tage übersprungen.

#### 1.3 Implementierungs-Reihenfolge

1. **Skills neu schneiden** (`skills/spot_safety.md`, `spot_flyability.md`, region-Pendants). `prompts.py` um `compose_safety_prompt()` + `compose_flyability_prompt()` erweitern.
2. **Bemerkungs-Klassifikation** vor dem Call (in `weather_context.py` oder Helper) — pro Spot Bemerkungen in `safety_bemerkungen` / `flyability_bemerkungen` aufteilen.
3. **Batch-Flow umbauen** in `engine/analyzers.py::run_batch_analysis`:
   Region-Safety → Region-Flyability → Spot-Safety → Spot-Flyability (4 Batches statt 2).
4. **Post-Processing splitten**: `_post_process_safety_*` und `_post_process_flyability_*` aus dem heutigen `_post_process_combined_*` extrahieren.
5. **Tests**: 5–10 Spots × 5 Tage durchlaufen, Output-Felder mit aktuellem Combined-Output diffen — keine fachliche Regression.

---

### Hebel 2 — Shared-Blöcke trimmen
**Idee:** `skills/shared/` enthält 56 KB pädagogischer Erklärungen, die das LLM kaum aktiv nutzt.

**Größte Brocken:**
- `_hazard_blocks.md` — 21 KB (~5,200 tokens) — viele Edge-Case-Erklärungen
- `_flyability_tiers.md` — 7 KB
- `_input_map.md` — 6 KB

**Umsetzung:**
1. Pro Shared-Block prüfen: welche Sektionen sind aktiv im Output sichtbar?
2. Erklärtexte ("Warum X?") raus, harte Regeln/Schwellen behalten
3. Beispiele auf 1 pro Regel reduzieren
4. A/B-Test: Output-Qualität auf 5 Test-Tagen vergleichen

**Aufwand:** Hoch (3–5h, weil Qualitäts-Regression vermieden werden muss).
**Ersparnis:** ~20–30 % wenn shared/ halbiert wird.

---

### Hebel 3 — Anthropic mit Prompt-Caching
**Idee:** `ANALYSIS_PROVIDER=anthropic` + `cache_control` auf System-Prompt. Claude Haiku 4.5 cached identische Prompt-Prefixes zu **10 %** des Normalpreises.

**Mathematik (28 Spots × 5 Tage = 140 Calls):**
- System-Prompt 17,920 tokens × 140 Calls = 2.5M System-Tokens
- Mit Caching: erster Call voll, danach 139× cached → effektiv 17,920 + 139×1,792 ≈ 267K tokens
- → ~10× weniger System-Tokens bezahlt

**Caveat:** Kein OpenAI-Batch-API → 50 %-Batch-Rabatt entfällt.
**Netto-Vergleich:**
- OpenAI Batch (jetzt): 2.5M × $0.075/M (gpt-4o-mini batch) = $0.19 nur System-Tokens
- Anthropic mit Cache: 267K × $1/M (Haiku, gecached zu $0.10/M effektiv) ≈ $0.27
- → ähnlich teuer? Nicht eindeutig besser, **MUSS gemessen werden**.

**Umsetzung:**
- ENV `ANALYSIS_PROVIDER=anthropic` setzen
- `cache_control: {"type": "ephemeral"}` Block am Ende des System-Prompts in `analyzers.py`
- Parallel-Modus statt Batch (Anthropic hat keine Batch-API mit 50% Rabatt)
- `LLM_MAX_WORKERS` hochziehen (Anthropic Tier rate limits prüfen)

**Aufwand:** Niedrig-Mittel (~2h Code + Tests).
**Ersparnis:** **Unklar — A/B-Test nötig.**

---

### Hebel 4 — Pre-Filter aggressiver
**Idee:** Mehr deterministische `not_safe`-Regeln in `_prefilter_not_safe()` (`engine/analyzers.py`), um LLM-Calls zu sparen.

**Mögliche neue Regeln:**
- CAPE > X über mehr als Y Stunden → Gewitter-NoGo (existiert teilweise)
- Aloft-Wind > 50 km/h ganztägig → not_safe ohne LLM
- Bewölkung 100% low+mid > 6h → kein flyability-fenster, könnte gray-pre-empten
- Foehn-Sturm-Indikatoren über harten Schwellen

**Aufwand:** Niedrig (~1h pro Regel).
**Ersparnis:** Klein bis mittel (5–15 %), abhängig von Wetterlage.

---

## 3. Empfohlene Reihenfolge

1. **Hebel 1 zuerst** — größter Effekt, klare Code-Änderung, reversibel via Git
2. **Hebel 4** parallel — billig, additiv zu Hebel 1
3. **Hebel 2** wenn Hebel 1 nicht reicht — vorsichtig mit Qualitäts-Regression
4. **Hebel 3** als A/B-Experiment — Messen statt raten

**Quick Win Combo:** Hebel 1 + Hebel 4 → realistisch **40–50 % Kostensenkung** (zurück auf ~$1 pro Batch) ohne Qualitäts-Risiko.

---

## 4. Wichtige Code-Stellen

| Datei | Zeile | Was |
|---|---|---|
| `engine/analyzers.py` | ~1780 | `run_batch_analysis()` — Combined-Batch-Flow (Hebel 1 hier) |
| `engine/analyzers.py` | ~1100 | `_prefilter_not_safe()` (Hebel 4 hier) |
| `prompts.py` | 147–148 | `compose_analysis_prompt()` — Combined-Prompt-Komposition |
| `skills/spot_analysis.md` | — | Template, 15 KB |
| `skills/region_analysis.md` | — | Template, 8.5 KB |
| `skills/shared/*.md` | — | 7 Blöcke, 56 KB total (Hebel 2 hier) |
| `config.py` | 664–681 | `ANALYSIS_PROVIDER` + `LLM_MODELS` (Hebel 3 hier) |

**Pre-Refactor Referenz:** Commit `396052e` zeigt den alten 2-Phasen-Flow:
```bash
git show 396052e:chat_engine.py | sed -n '4250,4480p'
```

---

## 5. Status & offene Fragen

### Was bereits umgesetzt ist (Stand: 2026-04-29)
- ✅ **Skill-Split**: `skills/spot_safety.md`, `spot_flyability.md`, `region_safety.md`, `region_flyability.md` existieren (Commit `4ff5822`)
- ✅ **`compose_analysis_prompt(mode, phase)`** mit `safety` / `flyability` / `combined` (`prompts.py:110`)
- ✅ **Phasen-Prompts**: `SPOT_SAFETY_PROMPT`, `SPOT_FLYABILITY_PROMPT`, `REGION_SAFETY_PROMPT`, `REGION_FLYABILITY_PROMPT` (`prompts.py:184–187`)
- ✅ **Post-Processing Split**: `_post_process_safety_spot/region` und `_post_process_flyability_spot/region` (`engine/analyzers.py:1601–1845`)
- ✅ **4-Phasen-Batch-Flow** in `run_batch_analysis`: Region-Safety → Region-Fly → Spot-Safety → Spot-Fly (`engine/analyzers.py:~1977–2300`)
- ✅ **Skip-Logik** für not_safe Spots (`engine/analyzers.py:2217–2219` → `_not_safe_minimal_flyability`)
- ✅ **Pre-Filter-Logging** zeigt Skip-Rate (`engine/analyzers.py:2155–2159`)
- ✅ **Decision-Engine** für deterministische Felder (Commits `3e51cf4`, `b46ba27`)
- ✅ **Per-Call Token-Logging** über `_log_prompt_cache_usage` (`engine/_common.py:74`)

### Offen — kritisch vor dem nächsten Optimierungsschritt
- ✅ **Per-Lauf Kosten-Telemetrie** umgesetzt: `BatchCostTracker` (`engine/_common.py`) loggt nach `data/cost_telemetry.jsonl`, eine Zeile pro `run_all_analyses_stream`-Lauf, mit Tokens/Phase + USD-Schätzung + Pre-Filter-Skip-Count. Funktioniert für Batch- UND Parallel-Modus.
- ✅ **Cost-Cap als Notbremse**: ENV `LLM_COST_CAP_USD` (default 5.00) bricht Batch sauber ab.
- ✅ **Goldstandard-Tooling**: `debug_scripts/freeze_golden.py` (Cases einfrieren) + `debug_scripts/score_regression.py` (Field-Level-Score + Acceptance-Gate). Auf dem Server auszuführen, wo `data/spot_analyses.json` + Wetter-Cache vorliegen.
- ⚠ **Klarstellung Modus-Schalter:** `LLM_ANALYSIS_MODE` wird **nicht via `.env`** gesteuert, sondern via UI-Overlay (`config_overrides.py` + `data/config_overrides.json`, geschrieben durch den Admin-UI-Schalter "LLM-Analyse: parallel | batch"). `config.py:718` ist nur der Code-Default (`"parallel"`), den `config_overrides.init()` beim App-Start überschreibt. Aktuellen Wert prüfen: Admin-UI öffnen ODER `cat data/config_overrides.json` auf dem Server. Falls dort `"parallel"` steht → in der UI auf `"batch"` wechseln (erwartete Sofort-Ersparnis ~50%, Hebel 1 ist im Code bereits umgesetzt, läuft aber nur im batch-Pfad).
- [ ] **Qualitäts-Baseline einfrieren**: `python debug_scripts/freeze_golden.py --limit 40` auf dem Server fahren, *bevor* der ENV-Schalter umgelegt wird. So hast du die Pre-Switch-Outputs als Vergleichsbasis.
- [ ] **Regression-Diff Parallel ↔ Batch** auf Test-Set: nach Umschalten `python debug_scripts/score_regression.py --no-llm --report data/reg_<datum>.md` → bestätigt dass der Split-Flow gleichwertige Outputs liefert.

### Offen — danach
- [ ] **Hebel 2** (`shared/`-Trimming): nur nach grünem Quality-Gate, A/B mit LLM-as-Judge.
- [ ] **Hebel 3** (Anthropic-Cache): A/B mit Cost-Tracker.
- [ ] **Hebel 4** (Pre-Filter-Regeln): jede neue Regel braucht eine False-Positive-Test-Charge.
- [ ] Anthropic-Tier: 140+ parallele Calls / Rate-Limit prüfen.

---

## 6. Qualitäts-Sicherung — *Kein Hebel ohne Acceptance-Gate*

**Grundregel:** Subjektive Begutachtung („sieht gut aus") ist verboten. Jede Optimierung muss numerisch widerlegbar sein.

### 6.1 Goldstandard-Test-Set
- **Umfang**: 8 Spots × 5 Tage × beide Modi (spot/region) = 40 Spot-Cases + 5–8 Region-Cases.
- **Auswahl**: 2 klar `safe` (z.B. Sommer-Westwind-Tag), 2 `conditional` (Foehn-Grenzfall), 2 `not_safe` (Sturm/Gewitter), 2 Edge-Cases (Wechselwetter, Inversion).
- **Speicherung**: `tests/golden/spot_<name>_<date>.json` — ein File pro Case, enthält:
  - vollständiger `weather_context` (Input)
  - vollständiges Combined-Result aus letztem grünen Stand (Pre-Skill-Split)
- **Erzeugung einmalig**: aus aktuellem `data/spot_analyses.json` extrahieren ODER über `debug_scripts/freeze_golden.py` (siehe §6.5).

### 6.2 Field-Level Regression-Score (deterministisch)

Pro Test-Case wird neuer Output gegen Goldstandard verglichen, **field-by-field**:

| Feld | Vergleichsregel | Gewicht | Regression wenn |
|---|---|---|---|
| `safety_status` | exakt | **kritisch** (10) | abweicht |
| `flyability_tier` | exakt | **kritisch** (10) | abweicht |
| `safe_window` | Stundenüberlappung ≥ 80 % | hoch (5) | < 80 % |
| `rating` | \|Δ\| ≤ 0.5 | hoch (5) | > 0.5 |
| `no_go_reasons` (Set) | Jaccard ≥ 0.7 | mittel (3) | < 0.7 |
| `caution_notes` (Set) | Jaccard ≥ 0.5 | mittel (3) | < 0.5 |
| `streckenflug.tier` | exakt | mittel (3) | abweicht |
| `summary` (Text) | Embedding-Cosine ≥ 0.85 ODER LLM-Judge ≥ 4/5 | niedrig (2) | beides nein |

**Acceptance-Gate**: Auf 40 Test-Cases:
- 0 kritische Regressionen
- ≤ 2 hohe Regressionen
- gewichteter Score ≥ 90 % des Goldstandards

Ist eine Bedingung verletzt → Hebel wird **nicht** aktiviert, Diff wird im PR sichtbar.

### 6.3 LLM-as-Judge für Freitext-Felder (`summary`, `recommendation`)

**Judge-Modell**: ein Modell-Tier *über* dem Analyse-Modell (z.B. wenn Analyse = Haiku 4.5, Judge = Sonnet 4.6). So kann der Judge nicht denselben blinden Fleck haben.

**Judge-Prompt** (Skelett, nach Mandat „No subjective grading"):
```
Du bist Qualitätsprüfer für Paragliding-Analysen. Beide Texte beschreiben
denselben Spot/Tag (Wetterkontext anbei).

GOLDSTANDARD: <text_old>
KANDIDAT:     <text_new>

Bewerte den KANDIDAT gegen GOLDSTANDARD nach diesen Kriterien
(jeweils 0–5, ganzzahlig):

A. Faktentreue — fehlt kein sicherheitsrelevantes Detail aus Goldstandard?
B. Aktionierbarkeit — kann ein Pilot daraus eine konkrete Entscheidung ableiten?
C. Spezifität — keine generischen Plattitüden, sondern Spot/Tag-spezifisch?
D. Konsistenz — keine Widersprüche zu safety_status / safe_window?

Antwort als JSON: {"A":n,"B":n,"C":n,"D":n,"verdict":"pass|warn|fail",
"reason":"<≤200 Zeichen>"}.
verdict=pass nur wenn alle ≥4. fail wenn ein Kriterium ≤2.
```

**Acceptance**: ≥ 90 % der Cases erreichen `pass`, **kein** `fail`.

### 6.4 Shadow-Test-Modus (für Hebel 2 + 3)

Statt einen Hebel hart zu schalten:
1. Im Live-Batch laufen *beide* Pfade (alt + neu) parallel auf 5–10 % der Spots.
2. Ergebnisse werden geloggt, **nicht** ausgeliefert. Konsumiert wird das alte System.
3. Nightly-Job vergleicht via §6.2 + §6.3.
4. Erst bei stabilem grünen Score über 3 aufeinanderfolgende Tage wird umgeschaltet.

Implementierung: ENV `SHADOW_PROVIDER=anthropic` + ENV `SHADOW_SAMPLE_RATE=0.1`. Schreibt nach `data/shadow_runs/<date>.jsonl`.

### 6.5 Konkrete Skripte (Tooling)

Neu zu erstellen unter `debug_scripts/`:

| Skript | Zweck |
|---|---|
| `freeze_golden.py` | Liest 40 Cases aus aktuellem `spot_analyses.json` + matched Wetterkontext aus `weather_context.py`, schreibt `tests/golden/*.json`. Einmal-Lauf nach manueller Sichtung. |
| `score_regression.py` | Lädt Golden-Set, fährt aktuellen Pipeline gegen die gefrorenen Inputs, berechnet Score gemäß §6.2, schreibt Report `data/regression_<date>.md` mit Field-Diffs. |
| `judge_summaries.py` | Ruft LLM-Judge auf alle `summary`-Diffs aus dem letzten `score_regression`-Lauf, schreibt `data/judge_<date>.jsonl`. |

CLI-Lauf vor jedem Hebel-PR: `python debug_scripts/score_regression.py && python debug_scripts/judge_summaries.py`. Mergen ist blockiert wenn ein Skript exit-code ≠ 0.

### 6.6 Umsetzungs-Reihenfolge §6
1. **Goldstandard einfrieren** (jetzt — *bevor* weitere Hebel angefasst werden, sonst gibt es nichts mehr zum Vergleichen).
2. `score_regression.py` schreiben + auf aktuellem Code laufen lassen → **Sanity-Check, dass der bereits umgesetzte Hebel 1 keine Regression eingeführt hat**.
3. Falls Score grün: §7 Telemetrie aufsetzen, Hebel 2 angehen.
4. Falls Score rot: Diff-Report analysieren, Skill-Split-Logik nachjustieren *bevor* irgendein weiterer Hebel kommt.

---

## 7. Kosten-Telemetrie — *„Always calculate cost" (Mandat)*

**Ziel:** Pro `run_batch_analysis`-Lauf eine Zeile in `data/cost_telemetry.jsonl` schreiben, die jederzeit eine Trend-Antwort auf „kostet es jetzt mehr oder weniger?" erlaubt.

### 7.1 Datenstruktur (`data/cost_telemetry.jsonl`, append-only)
```json
{"ts":"2026-04-29T18:00Z","commit":"<git sha>","provider":"openai_batch",
 "model":"gpt-4o-mini","phases":{
   "region_safety":{"calls":12,"in_tok":86400,"out_tok":3600,"cached_tok":0},
   "region_fly":   {"calls":7, "in_tok":67900,"out_tok":4900,"cached_tok":0},
   "spot_safety":  {"calls":140,"in_tok":1022000,"out_tok":42000,"cached_tok":0},
   "spot_fly":     {"calls":71,"in_tok":688700,"out_tok":63900,"cached_tok":0}
 },
 "prefilter_skipped":21,"total_tok":1979400,"est_usd":0.74,"duration_s":421}
```

### 7.2 Implementierungs-Ort
- `engine/analyzers.py::run_batch_analysis` aggregiert `usage` aus jedem `_poll_batch`-Result pro Phase.
- Neuer Helper `engine/_common.py::log_batch_cost(record: dict)` schreibt JSONL und loggt eine Summary-Zeile (`logger.info("[COST] Batch=$0.74 tokens=1.98M skip=21/161")`).
- Preise pro Modell zentral in `config.py::MODEL_PRICES` (USD pro 1M tok, in/out/cached).

### 7.3 Circuit Breaker — *„Halt on Anomaly" (Mandat)*
- ENV `LLM_COST_CAP_USD` (default 3.00). Während des Batches: nach jeder Phase Summe prüfen.
- Bei Überschreitung → Batch sauber abbrechen, `logger.error("[COST-BREAKER] cap=$X überschritten, Batch gestoppt")`, partielle Results bleiben gespeichert. Verhindert „runaway"-Szenarios (z.B. wenn jemand `LLM_MAX_WORKERS` zu hoch zieht oder ein Prompt versehentlich auf 50K Tokens wächst).

### 7.4 Trend-Validierung
Nach jedem grünen Optimierungs-PR:
```
python -c "import json; rows=[json.loads(l) for l in open('data/cost_telemetry.jsonl')]; \
  print(f'last 7d avg: ${sum(r[\"est_usd\"] for r in rows[-7:])/7:.2f}')"
```
Zielkorridor: **< $1.00 / Lauf** (zurück auf Pre-`a916e88`-Niveau bei gleicher Spot-Anzahl).

---

## 8. Empfohlene nächste Schritte (in genau dieser Reihenfolge)

1. **§7.1–7.2** umsetzen: Cost-Telemetrie aufsetzen (~2h). Liefert Datenpunkt für JEDE weitere Entscheidung.
2. **§6.5 `freeze_golden.py`** schreiben + 40 Cases einfrieren (~2h). Goldstandard ist jetzt unveränderlich.
3. **§6.5 `score_regression.py`** schreiben + auf aktuellem Code (Hebel 1 done) laufen (~2h). Bestätigt: keine Regression, oder zeigt wo nachjustiert werden muss.
4. **§7.3** Circuit Breaker einbauen (~30 min).
5. **3 Live-Batches** mit neuer Telemetrie laufen lassen → Ist-Kosten dokumentieren.
6. Erst danach: Hebel 2/3/4 angehen, jedes mit §6.2 + §6.3 + §7.4 als Gate.

**Erwartung:** Schritte 1–5 sollten zeigen, ob Hebel 1 alleine bereits den Großteil der Kostenersparnis bringt. Realistische Schätzung: Batch zurück bei $0.80–$1.20 *und* Qualität messbar konstant.
