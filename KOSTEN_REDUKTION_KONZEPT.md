# LLM-Analyse Kostenreduktion — Konzept

**Status:** Diagnose abgeschlossen, Umsetzung offen
**Auslöser:** Batch-Kosten ~$0.60 → ~$2 pro Lauf seit Commit `a916e88` (3–4× Anstieg)

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

## 5. Offene Fragen für nächste Session

- [ ] Wieviel kostet ein Batch-Lauf jetzt **exakt** (input/output Tokens loggen)?
- [ ] Existieren `safety_check.md` + `region_safety_check.md` noch? Falls nicht → aus shared-Blöcken neu komponieren
- [ ] Wieviel % der Spot-Tage werden vom Pre-Filter aktuell geskippt? (Logging in `_prefilter_not_safe` aktivieren)
- [ ] Ist Anthropic-Tier ausreichend für 140+ parallele Analysen? Rate-Limits prüfen
