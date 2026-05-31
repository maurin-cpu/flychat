# Skills-Architektur

**Stand:** RATING_CONCEPT v1.3 / Phase 4b umgesetzt + Tagesfenster-Refactor (Mai 2026).
**Source of Truth fuer Konzept-Regeln:** `docs/RATING_CONCEPT.md`.
Diese Doku beschreibt **wie die Skill-Files die LLM-Calls steuern** — nicht das Bewertungs-Konzept selbst.

---

## 1. Was ein "Skill" ist

Ein Skill ist eine Markdown-Datei unter `skills/`, die einen LLM-Prompt
oder einen Prompt-Baustein enthaelt. Es gibt zwei Klassen:

- **Pipeline-Files** (z.B. `spot_safety.md`) — werden direkt als System-Prompt
  an Claude geschickt. Enthalten Rolle, Aufgabe, JSON-Schema und einen Insert-Marker
  fuer Shared-Bausteine.
- **Shared-Bausteine** (`skills/shared/<NN_kategorie>/<NN_name>.md`) — werden ueber Marker
  in Pipeline-Files eingefuegt. Liefern Querschnitts-Wissen (Anti-Halluzinations-
  Regeln, Tag-Definitionen, Sub-Rating-Tabellen).

Platzhalter `{{cfg.KEY}}` in den Files werden beim Laden gegen
`config.KEY` ersetzt — Schwellen aendern sich also live ohne Skill-Edit.

---

## 2. Architektur: prozessual + numeriert

### 2.1 Drei Verarbeitungs-Schichten

```
┌──────────────────────────────────────────────────────────────┐
│ SCHICHT 0 — DETERMINISTISCH (Code, keine LLM-Verantwortung)  │
├──────────────────────────────────────────────────────────────┤
│ • Tag aktiv? (active_window_start oder None) — gleitcast/    │
│   engine/weather_context.py:_determine_active_window_start   │
│ • Datenblock-Slicing (Stunden vor Tagesbeginn weg)           │
│ • Pre-Filter not_safe (kein Fenster, ganztaegig Regen, …)    │
│ • Hazard-Tag-Berechnung pro Stunde                           │
│ • Trend-Berechnung, TAGESPROFIL-Histogramm                   │
└──────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ SCHICHT 1 — SAFETY (LLM-Call)                                │
├──────────────────────────────────────────────────────────────┤
│ Input:  Datenblock mit gefilterten Stunden + TAGESFENSTER-   │
│         Header                                               │
│ Aufgabe: Hazards bewerten, Status ableiten, Sub-Ratings      │
│ Output: safety_status, safe_window, no_go, caution, ratings  │
└──────────────────────────────────────────────────────────────┘
                           │ IMMUTABLE Safety-Output
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ SCHICHT 2 — FLYABILITY (LLM-Call)                            │
├──────────────────────────────────────────────────────────────┤
│ Input:  IMMUTABLE Safety-Output + selber Datenblock          │
│ Aufgabe: Thermik, Wolken, TQ, Streckenflug                   │
│ Output: fly_status, flight-Sub-Ratings, streckenflug         │
└──────────────────────────────────────────────────────────────┘
```

**Vier LLM-Calls:** `spot_safety`, `spot_flyability`, `region_safety`, `region_flyability`. Combined-Pfad wurde Mai 2026 entfernt — wer beide Phasen will, ruft sie sequenziell (das tut `_build_and_analyze_spot/region` in `engine/analyzers.py`).

### 2.2 Tag-Drei-Kategorien-Modell

Das ganze Skill-System ist um die **drei Tag-Kategorien** organisiert:

| Kategorie | Beispiele | Phase | Skill-Verantwortung |
|-----------|-----------|-------|---------------------|
| **Startbarkeits-Filter** | `[WIND-OK]`, `[WIND-WRONG]` | Schicht 0 (Code) + Skill `_tagesfenster` | Keine Hazards. Code schneidet Datenblock vor Tagesbeginn weg. Skill erklaert dem LLM, was es im aktiven Tag noch sieht. |
| **Hazard-Tags** | `[WIND-DANGER]`, `[RAIN-WARN]`, `[GUST-DANGER]`, `[CAPE-DANGER]`, etc. | Phase 1 (Safety) | `_tags_safety` listet alle, `_hazards_*` definiert Anwendung |
| **Thermik-Qualitaets-Tags** | `[SHEAR-*]`, `[THERMAL-TORN-*]`, `[THERMAL-WIND-*]`, `[THERMAL-ROUGH-*]` | Phase 2 (Flyability) | `_tags_flyability` listet Mechanismen, `_flyability_rules` + `_prose_style` definieren Anwendung |

---

## 3. Skill-Verzeichnis-Struktur

Skills liegen unter `skills/shared/<NN_kategorie>/<NN_name>.md`. Numerisches Praefix
zeigt **die Lade-Reihenfolge**, sowohl auf Subordner-Ebene (Kategorie-Sequenz)
als auch auf File-Ebene (Position innerhalb der Kategorie).

```
skills/shared/
├── 01_global/                       in JEDEM Call
│   ├── 01_core_principles.md
│   └── 02_input_format.md
├── 02_tagesfenster/                 Schicht 0 — eigene Kategorie
│   └── 01_tagesfenster.md
├── 03_safety/                       Phase 1
│   ├── 00_template_spot.md          ← Wrapper (ROLLE + JSON-Schema, Insert-Marker)
│   ├── 00_template_region.md        ← Wrapper
│   ├── 01_tags_safety.md
│   ├── 02_hazards_spot.md           (mode-alternativ)
│   ├── 02_hazards_region.md
│   ├── 03_status_derivation.md
│   └── 04_safety_subratings.md
├── 04_flyability/                   Phase 2
│   ├── 00_template_spot.md          ← Wrapper (ROLLE + JSON-Schema, Insert-Marker)
│   ├── 00_template_region.md        ← Wrapper
│   ├── 01_tags_flyability.md
│   ├── 02_flyability_rules.md
│   ├── 03_prose_style.md
│   ├── 04_flight_subratings_spot.md (mode-alternativ; enthält seit Mai 2026 den Streckenflug-Pflichtsatz)
│   └── 04_flight_subratings_region.md
└── 05_context/                      mode-spezifisch, kontextuell eingefuegt
    ├── _spot_context.md
    └── _region_context.md
```

**`00_template_*.md`** sind die "Außenhüllen" pro Call: ROLLE/Persona, AUFGABE, Insert-Marker, JSON-Schema und phase-spezifische Selbst-Checks. Praefix `00_` weil sie konzeptionell vor allen anderen Files stehen — die anderen werden ueber den Marker IN sie eingefuegt. Vorher lagen diese als `spot_safety.md`/`spot_flyability.md`/`region_safety.md`/`region_flyability.md` direkt unter `skills/`; im Mai-2026-Refactor in die jeweiligen Phase-Subordner verschoben und Selbst-Checks von redundanten Wiederholungen geshared Regeln befreit (Begruendung 2c, fly_status mechanisch, Boeen-Grounding Spot — alles bereits in shared).

**Hinweis zu gleichen File-Nummern:** Dateien mit gleichem Numerik-Praefix (z.B. `02_hazards_spot.md` und `02_hazards_region.md`) sind **Mode-Alternativen** — pro Call wird genau eine geladen, nie beide. Selbe Lade-Position, andere Variante.

**Hinweis zu `05_context/`:** Context-Files haben kein Nummern-Praefix, weil sie kontextuell eingefuegt werden (nach Hazards in Safety, nach Input-Format in Flyability). Der Composer kennt die Einfuegestelle.

---

## 4. Composer (`prompts.py`)

### 4.1 Lazy-Loading

```python
prompts.SYSTEM_PROMPT             # → skills/system_chat.md
prompts.SPOT_SAFETY_PROMPT        # → composed
prompts.SPOT_FLYABILITY_PROMPT    # → composed
prompts.REGION_SAFETY_PROMPT      # → composed
prompts.REGION_FLYABILITY_PROMPT  # → composed
```

`__getattr__` macht das **lazy** — jeder Zugriff re-liest die Files und re-rendert
Platzhalter. Config-Aenderungen ueber das Admin-UI greifen damit ohne Restart.
Konvention: `import prompts; prompts.X` — **nicht** `from prompts import X`
(letzteres bindet den Wert beim Import-Zeitpunkt fest).

### 4.2 Lade-Matrix pro Call

Die Reihenfolge entspricht 1:1 den Numerik-Praefixen.

| # | Skill | spot_safety | spot_fly | region_safety | region_fly |
|---:|---|:-:|:-:|:-:|:-:|
| 1 | `01_global/01_core_principles.md` | ✓ | ✓ | ✓ | ✓ |
| 2 | `01_global/02_input_format.md` | ✓ | ✓ | ✓ | ✓ |
| 3 | `03_safety/01_tags_safety.md` | ✓ | — | ✓ | — |
| 3 | `04_flyability/01_tags_flyability.md` | — | ✓ | — | ✓ |
| 4 | `02_tagesfenster/01_tagesfenster.md` | ✓ | — | ✓ | — |
| 5 | `03_safety/02_hazards_spot.md` | ✓ | — | — | — |
| 5 | `03_safety/02_hazards_region.md` | — | — | ✓ | — |
| 6 | `05_context/_spot_context.md` | ✓ | ✓ | — | — |
| 6 | `05_context/_region_context.md` | — | — | ✓ | ✓ |
| 7 | `03_safety/03_status_derivation.md` | ✓ | — | ✓ | — |
| 8 | `03_safety/04_safety_subratings.md` | ✓ | — | ✓ | — |
| 9 | `04_flyability/02_flyability_rules.md` | — | ✓ | — | ✓ |
| 10 | `04_flyability/03_prose_style.md` | — | ✓ | — | ✓ |
| 11 | `04_flyability/04_flight_subratings_spot.md` | — | ✓ | — | — |
| 11 | `04_flyability/04_flight_subratings_region.md` | — | — | — | ✓ |

**Pro Call** werden die in der jeweiligen Spalte mit ✓ markierten Skills geladen (plus den `00_template_*`-Wrapper). Streckenflug ist seit Mai 2026 **kein eigenes File mehr**, sondern als „STRECKENFLUG-PFLICHTSATZ" in `04_flight_subratings_spot.md` integriert — daher kein Spot-Extra-Skill. Kein Phase-1-Material in Phase-2-Calls und umgekehrt.

### 4.3 Composer-Logik (Pseudocode)

```python
SAFETY = [
    "01_global/01_core_principles.md",
    "01_global/02_input_format.md",
    "03_safety/01_tags_safety.md",
    "02_tagesfenster/01_tagesfenster.md",
    "03_safety/02_hazards_spot.md",      # mode-conditional → _region.md
    # → _context wird hier eingefuegt
    "03_safety/03_status_derivation.md",
    "03_safety/04_safety_subratings.md",
]

FLYABILITY = [
    "01_global/01_core_principles.md",
    "01_global/02_input_format.md",
    "04_flyability/01_tags_flyability.md",
    # → _context wird hier eingefuegt (nach _input_format, da kein _hazards)
    "04_flyability/02_flyability_rules.md",
    "04_flyability/03_prose_style.md",
    "04_flyability/04_flight_subratings_region.md",   # mode-conditional → _spot.md
    # → _streckenflug wenn mode=spot
]
```

**Mode-Conditionals:**
- `mode == "spot"` → `04_flight_subratings_region.md` wird zu `_spot.md` (enthält den Streckenflug-Pflichtsatz)
- `mode == "region"` → `02_hazards_spot.md` wird zu `_region.md`

**Context-Insertion:** `05_context/_<mode>_context.md` wird nach den Hazards eingefuegt (Safety-Phase) oder nach `02_input_format.md` (Flyability-Phase).

---

## 5. Pipeline-Files (skills/)

| Datei | Mode | Phase | Insert-Marker |
|-------|------|-------|---------------|
| `system_chat.md` | Chat | — | — |
| `chat_capabilities_guide.md` | Chat | — | — |
| `foehn_chat_knowledge.md` | Chat | — | — |
| `foehn_llm_regional_guide.md` | Analyse-Header | — | — |
| `weekly_briefing.md` | Briefing | — | — |
| `email_week_lead.md` | Mail | — | — |

**Pipeline-Templates** (`spot_safety.md`, `spot_flyability.md`, `region_safety.md`, `region_flyability.md`) sind seit Mai 2026 nicht mehr auf Top-Level — sie leben als `00_template_<mode>.md` in `skills/shared/03_safety/` bzw. `04_flyability/`. Insert-Marker bleiben `<!-- INSERT_SHARED_SAFETY -->` / `<!-- INSERT_SHARED_FLYABILITY -->`.

---

## 6. Shared-Bausteine im Detail

### 6.1 `01_global/` — in jedem Call geladen

**`01_core_principles.md`** — Anti-Halluzinations-Kern.
- Regel 1 (rechnen verboten) + 1a (runden verboten) + 2 (Tags vertrauen) + 2a (Histogramm-Grounding) + 2a-bis (Trend-Zeilen interpretieren) + 2b (Zahlen 1:1) + 2c (Begruendungen aus Datenblock).
- Regel 3 (Sicherheit ≠ Fliegbarkeit, Architektur-Aussage).
- Regel 4 (Tagesfenster-Schicht ist eigene Kategorie, Verweis auf `_tagesfenster`).
- Glossar (Flugbereich, Buffer-Zone, PRODUKTIVE-THERMIK, VIOLETT-Kandidat, etc.).

**`02_input_format.md`** — Datenblock-Anatomie.
- Wie liest die LLM den Datenblock: Stunden-Zeilen, Drucklevel, TAGESPROFIL.
- Drei-Kategorien-Uebersicht (Verweis auf `_tags_safety` / `_tags_flyability` / `_tagesfenster`).
- Marker: `*` Flugbereich, `~` Buffer-Zone.

### 6.2 `02_tagesfenster/` — Schicht 0, eigene Kategorie

**`01_tagesfenster.md`** — Tagesfenster-Skill.
- Erklaert dem LLM, dass der Datenblock bereits ab dem ersten qualifizierenden Start-Fenster zugeschnitten wurde (Header `Tag aktiv ab HH:00`).
- Aufgabe: Fenster-Narrative im aktiven Tag (1 Fenster vs. fragmentiert, Laenge, Wind-Dreh).
- WIND-WRONG nach Tagesbeginn = Lande-Hinweis, kein Hazard.
- 4 konkrete Beispiele.

### 6.3 `03_safety/` — Phase 1

**`01_tags_safety.md`** — Hazard-Tag-Liste.
- DANGER-Level: RAIN-WARN, WIND-DANGER, ALOFT-WIND-DANGER, GUST-DANGER, ALOFT-GUST-DANGER, THUNDERSTORM, CAPE-DANGER, OVERCAST-DANGER.
- WARN-Level: WIND-WARN, ALOFT-WIND-WARN, GUST-WARN, ALOFT-GUST-WARN, CAPE-WARN.
- Stunden-Klassifikation (RUHIG/SPORTLICH/UNFLIEGBAR), `safe_window`-Definition.
- Verweis auf `_tagesfenster` fuer WIND-OK/WRONG.

**`02_hazards_spot.md` / `02_hazards_region.md`** — die 6 (Region) bzw. 7 (Spot) Gefahren-Bloecke + Trend-Vokabular.
- KERNREGEL Stunden-Klassifikation.
- TREND-VOKABULAR mit 7 Mustern (AUFKLAERUNG, ZUNEHMEND, EINGEKESSELT, DURCHGEHEND-WARN/DANGER, VEREINZELT, STABIL).
- EINGEKESSELT-Sonderfaelle.
- **Spot-Variante:** 7 Gefahrenbloecke (Regen, Bodenwind, Boeen, Hoehenwind, Foehn, Konvektion, Wolken).
- **Region-Variante:** 6 Bloecke ohne Boeen (kein Tag-Set fuer Boeen auf Region-Ebene).

**`03_status_derivation.md`** — 35 %-Regel + Status-Ableitung (`safe`/`conditional`/`not_safe`).

**`04_safety_subratings.md`** — 5 Sub-Rating-Tabellen 1–10:
wind / gust / aloft / foehn / weather. Weakest-Link-Aggregation, Override-Architektur, Trend-Pflicht.

### 6.4 `04_flyability/` — Phase 2

**`01_tags_flyability.md`** — Thermik-Qualitaets-Tags.
- SHEAR-DEGRADED/UNUSABLE (Windscherung).
- THERMAL-TORN-DEGRADED/UNUSABLE (Buoyancy/Shear-Ratio).
- THERMAL-ROUGH-DEGRADED/UNUSABLE (Boeigkeit, nur Spot).
- THERMAL-WIND-DEGRADED/UNUSABLE (BL-Mean-Wind).
- Verweis auf `_flyability_rules` fuer Anwendung.

**`02_flyability_rules.md`** — IMMUTABLE-Input + Anker.
- 2-Achsen-Architektur-Header.
- fly_status-Mapping-Tabelle.
- Sub-Rating-Anker (Schwacher Tag / Solider Tag / Top-Tag).
- TQ-Downgrade-Regel auf Sub-Ratings.
- PRODUKTIVE-THERMIK-Check + Conditional-Flag-Regel.

**`03_prose_style.md`** — TQ-Tag → natuerliche Sprache. Konsistenz-Pflicht (Text passt zu thermal_rating). Bewoelkungs-Labels (Booster/Reducer/Neutralzone/Cirrus).

**`04_flight_subratings_spot.md`** — 5 Subs (thermal 30 %, window 20 %, wind 10 %, xc 15 %, altitude 25 %).

**`04_flight_subratings_region.md`** — 4 Subs (thermal 35 %, window 25 %, wind 25 %, xc 15 %).

**Streckenflug** — XC-Synthese (kein_xc / lokal / moderat / top), Konflikt-Check fuer Region-Hoehenwind. Seit Mai 2026 **kein eigenes File mehr** (`05_streckenflug.md` entfernt), sondern als „STRECKENFLUG-PFLICHTSATZ" in `04_flight_subratings_spot.md` integriert. Nur Spot+Flyability.

### 6.5 `05_context/` — mode-spezifisch

**`_spot_context.md`** — Sektor-Konzept (Verweis auf `_tagesfenster`), Spot-Bemerkungs-Logik (3 Schritte: Klassifizieren SAFETY/FLYABILITY/BEIDES, Extrahieren, Nachjustieren).

**`_region_context.md`** — Magnitude-basierte Wind-Tags ohne Sektor. Boeen-Verbot fuer Region-Texte. Foehn-Richtungs-Check (Sued/Nord/Beide-Filter).

---

## 7. LLM-Output vs. Engine-Compute

Der zentrale Trennstrich in v1.3: **Was die LLM ausgibt** vs. **was die Engine
deterministisch ableitet**. Verstanden als Pipeline:

```
Datenblock → LLM → roher JSON → Engine-Postprocess → finaler Cache-Eintrag
```

### 7.1 LLM-Output (was die Skills verlangen)

**Safety-Phase:**
- `safety_status` — `safe` / `conditional` / `not_safe`
- `safe_window` — Zeitbereich
- `no_go_reasons[]`, `caution_notes[]`
- `primary_no_go`, `primary_caution`
- `wind_summary`, `wind_shear`
- `foehn_risk` — `none|low|moderate|high`
- **5 Safety-Sub-Ratings 1–10**: `wind_safety_rating`, `gust_safety_rating`,
  `aloft_safety_rating`, `foehn_safety_rating`, `weather_safety_rating`
- `summary` (Prosa, 4–6 Saetze)

**Flyability-Phase:**
- `fly_status` — `gray|green|violet` (LLM darf weiterhin setzen, **wird ueberschrieben**)
- `flyability_tier` — gleicher Wert (Synonym)
- `flight_type`, `flight_duration_estimate`, `peak_climb_rate`
- `xc_potential`, `xc_details`, `soaring_options`, `bemerkung_check`
- `best_window`, `flyability_limits[]`, `highlights[]`
- `recommendation`, `confidence`, `primary_reducer`, `primary_booster`
- **4–5 Flight-Sub-Ratings 1–10**: `thermal_rating`, `window_rating`,
  `wind_rating`, `xc_rating` + (Spot) `altitude_rating`
- `is_conditional`, `conditional_reason`
- `streckenflug{}` (Spot only): `tier`, `rating`, `summary`, `limiting_factor`,
  `region_context_available`

### 7.2 Engine-Compute (was die App ableitet) — v1.5

In `engine/_common.py` und `engine/decision_engine.py`:

| Feld | Quelle | Zweck |
|------|--------|-------|
| `experience_rating` (1–5) | **LLM direkt** | LLM-natives Rating — keine Aggregation |
| `experience_score` (0–100) | `experience_rating × 10` (inline) | Reine UI-Skalierung, kein Aggregations-Schritt |
| `flyability_tier` | **LLM direkt** (gray/green/violet) | LLM-natives Tier, keine Code-Ableitung |
| `fly_status` | identisch mit flyability_tier | Synonym, fuers UI |
| `safety_rating` (0–10) | `_compute_safety_rating` | **Weakest-Link** der 8 Safety-Sub-Ratings |
| `safety_score` (0–100) | `_compute_safety_score` | safety_rating × 10 |
| `safety_band` | `compute_safety_band` | **Hybrid**: Hard-Overrides + safety_score → green/amber/red/no_data |
| `comfort_index` (0–100) | `compute_comfort_index` | Texture-Wert aus rough_pct (kein Rating-Effekt) |

**Einziges Code-Override fuer Rating/Tier (v1.5):** Safety-Gate. Wenn
`safety_band == "red"` ODER `safety_status == "not_safe"`:

```
flyability_tier   → ""
experience_rating → 0
experience_score  → 0
```

**Hard-Overrides der Decision-Engine** (THUNDERSTORM, CAPE-DANGER, RAIN-WARN,
BOEEN-FLOOR, FoehnDanger usw.) erzwingen `safety_status`/`safety_band`
deterministisch, bevor die Score-Logik greift.

### 7.3 Begriffs-Klarstellung

Diese Begriffe **gibt es im Code**:

- `rating` = 0–10 Flyability-Gesamtrating (deterministisch aus Sub-Ratings)
- `experience_stars` = 0–5 User-Sprache "Rating 1–5"
- `safety_rating` = 0–10 Safety-Gesamtrating (Weakest-Link der 5 Subs)
- `safety_band` = green/amber/red/no_data (Hybrid)
- `flyability_tier` / `fly_status` = gray/green/violet (View-abgeleitet)
- `comfort_index` = 0–100 Texture
- `active_window_start` = Stunde (0-23) oder None — vom Code bestimmt

Diese Begriffe **gibt es NICHT** (oft in Konversation verwendet, aber nicht
im Schema):

- ~~`rating_flyability`~~ — heisst `rating` oder `experience_score`/`experience_stars`
- ~~`rating_safety`~~ — heisst `safety_rating` oder `safety_score`/`safety_band`

---

## 8. Hot-Reload & Lokales Testen

Da `_load_skill` jeden Aufruf re-liest, kann man Skill-Files **live editieren**
und den Effekt im naechsten Request sehen — ohne `python web.py` Restart.
Voraussetzung: Cache-Regen (alte Analysen aus dem Cache invalidieren oder
Cache umschalten).

---

## 9. Aenderungs-Logbuch

### Mai 2026 — Tagesfenster-Refactor + prozessuale Numerierung + Template-Konsolidierung

- **Combined-Pfad entfernt:** `_combined_analysis_single_*` und `_post_process_combined_*` aus `engine/analyzers.py`. `SPOT_COMBINED_PROMPT`/`REGION_COMBINED_PROMPT` aus `_LAZY_ATTRS`. Combined-Phase aus `compose_analysis_prompt`. Dateien `spot_combined.md` und `region_combined.md` geloescht.
- **Tagesfenster als eigene Kategorie:** Code (`weather_context.py:_determine_active_window_start`) bestimmt den Tagesbeginn deterministisch und schneidet den Datenblock vor diesem Punkt weg. Header `═══ TAGESFENSTER ═══` mit Begruendung. Skill `02_tagesfenster/01_tagesfenster.md` erklaert dem LLM die Konsequenzen.
- **`_input_map.md` gesplittet:**
  - `01_global/02_input_format.md` (NEU) — Datenblock-Anatomie + Drei-Kategorien-Uebersicht.
  - `03_safety/01_tags_safety.md` (NEU) — Hazard-Tags + Stunden-Klassifikation.
  - `04_flyability/01_tags_flyability.md` (NEU) — TQ-Tags-Mechanismen.
- **Numerierte Subordner-Struktur:** `01_global` / `02_tagesfenster` / `03_safety` / `04_flyability` / `05_context`. Files innerhalb in Lade-Reihenfolge nummeriert.
- **Pipeline-Templates verschoben + getrimmt:** Die 4 Pipeline-Files (`spot_safety.md` etc.) lagen vorher direkt unter `skills/` — Inkonsistenz nach Reorg. Verschoben nach `03_safety/00_template_<mode>.md` und `04_flyability/00_template_<mode>.md`. Composer ruft jetzt `_load_shared(...)` statt `_load_skill(...)` fuer sie auf. Selbst-Checks befreit von Wiederholungen geteilter Regeln (Begruendung 2c, fly_status-mechanisch, Boeen-Grounding Spot, "Keine Zahlen erfinden") — diese stehen bereits in `01_core_principles.md`, `02_flyability_rules.md` etc. ~3.5K Tokens gespart ueber alle 4 Prompts.
- **WIND-WRONG-Bereinigung:** Alle Verweise auf `[WIND-WRONG]` als Hazard aus Skills entfernt. Filter-Logik lebt jetzt komplett im Code (Schicht 0) plus dem Tagesfenster-Skill.
- **Pre-Filter konsolidiert:** `_prefilter_not_safe` nutzt `active_window_start` aus dem Cache statt drei separater wind_ok-Regeln.

---

## 10. Querverweise

- **Konzept-Regeln:** `docs/RATING_CONCEPT.md` (v1.3, §1–§11)
- **Decisions-Log:** `docs/DECISIONS.md` (Sektion 5 + 5a fuer Phase-4b-Architektur)
- **Tier-Logik (Legacy-View):** `docs/FLYABILITY_TIER_LOGIK.md`
- **Datenmodell-Hintergruende:** `docs/THERMIK_MODELL.md`, `docs/WIND_BOEEN_KONZEPT.md`,
  `docs/BOEEN_MODELL.md`, `docs/BEWOELKUNG_LABELS.md`
- **Smoke-Tests:** `docs/SMOKE_TESTS.md`
