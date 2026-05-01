# Skills-Architektur

**Stand:** RATING_CONCEPT v1.3 / Phase 4b umgesetzt.
**Source of Truth fuer Konzept-Regeln:** `docs/RATING_CONCEPT.md`.
Diese Doku beschreibt **wie die Skill-Files die LLM-Calls steuern** — nicht das Bewertungs-Konzept selbst.

---

## 1. Was ein "Skill" ist

Ein Skill ist eine Markdown-Datei unter `skills/`, die einen LLM-Prompt
oder einen Prompt-Baustein enthaelt. Es gibt zwei Klassen:

- **Pipeline-Files** (z.B. `spot_safety.md`) — werden direkt als System-Prompt
  an Claude geschickt. Enthalten Rolle, Aufgabe, JSON-Schema und einen Insert-Marker
  fuer Shared-Bausteine.
- **Shared-Bausteine** (`skills/shared/_*.md`) — werden ueber Marker in
  Pipeline-Files eingefuegt und liefern Querschnitts-Wissen (Anti-Halluzinations-
  Regeln, Tag-Definitionen, Sub-Rating-Tabellen).

Platzhalter `{{cfg.KEY}}` in den Files werden beim Laden gegen
`config.KEY` ersetzt — Schwellen aendern sich also live ohne Skill-Edit.

---

## 2. Loader & Komposition

Alles laeuft ueber `prompts.py`.

### 2.1 Skill laden

```python
prompts.SYSTEM_PROMPT          # → skills/system_chat.md
prompts.SPOT_SAFETY_PROMPT     # → composed
prompts.SPOT_FLYABILITY_PROMPT # → composed
prompts.SPOT_COMBINED_PROMPT   # → composed
```

`__getattr__` macht das **lazy** — jeder Zugriff re-liest die Datei und re-rendert
Platzhalter. Config-Aenderungen ueber das Admin-UI greifen damit ohne Restart.
Konvention: `import prompts; prompts.X` — **nicht** `from prompts import X`
(letzteres bindet den Wert beim Import-Zeitpunkt fest).

### 2.2 Komposition (`compose_analysis_prompt`)

Pro Mode (`spot`/`region`) und Phase (`safety`/`flyability`/`combined`) wird
ein vollstaendiger System-Prompt aus einem Pipeline-Template + Shared-Bloecken
zusammengesetzt:

| Phase | Template | Insert-Marker | Shared-Bloecke |
|-------|----------|---------------|----------------|
| `safety` | `{mode}_safety.md` | `<!-- INSERT_SHARED_SAFETY -->` | core, input, hazards, status_derivation, safety_subratings, mode_context |
| `flyability` | `{mode}_flyability.md` | `<!-- INSERT_SHARED_FLYABILITY -->` | core, input, flyability_rules, prose_style, flight_subratings, mode_context, [streckenflug spot-only] |
| `combined` | `{mode}_combined.md` | `<!-- INSERT_SHARED -->` | alle Bloecke + mode_context + [streckenflug spot-only] |

`mode_context` = `_spot_context.md` oder `_region_context.md`, Mode-conditional eingefuegt.
`hazards` = `_hazards_spot.md` oder `_hazards_region.md` (Region-Variante schmaler, ohne Boeen-Block).
`flight_subratings` = `_flight_subratings_spot.md` (5 Subs) oder `_flight_subratings_region.md` (4 Subs).

Reihenfolge der Bloecke ist die paedagogische Lese-Ordnung:
Prinzipien → Datenformat → Gefahren → Override → Safety-Sub-Ratings →
Fliegbarkeits-Achse → Sprache → Flight-Sub-Ratings.

**Spot vs. Region:** Wenn `mode == "spot"`, wird `_flight_subratings_region.md`
durch `_flight_subratings_spot.md` ersetzt — Spot hat 5 Sub-Ratings inkl.
`altitude_rating` (Steigraum ueber Startplatz, 25 % Gewicht), Region hat 4.

Wenn `mode == "region"`, wird `_hazards_spot.md` durch `_hazards_region.md`
ersetzt — die Region-Variante laesst Block 3 (Boeen) und ALOFT-GUST-Anteile
weg. Spart ~1.7K Token pro Region-Call ohne Inhaltsverlust (Region-Tags
existieren dort nicht).

### 2.3 Aktive Konsumenten

| Skill | Konsument | Phase |
|-------|-----------|-------|
| `system_chat.md` | `chat_engine.py` | Chat-System-Prompt |
| `chat_capabilities_guide.md` | `chat_engine.py` | Chat-Kontext (Tools, Tags) |
| `foehn_chat_knowledge.md` | `chat_engine.py` | Chat-Foehn-Wissen |
| `foehn_llm_regional_guide.md` | `prompts.format_foehn_llm_regional_guide()` | Analyse-Header |
| `spot_combined.md` | `engine/analyzers.py:280` | Spot-Analyse Combined-Flow |
| `region_combined.md` | `engine/analyzers.py:803` | Region-Analyse Combined-Flow |
| `spot_safety.md` / `spot_flyability.md` | Split-Flow | optional, nicht default |
| `region_safety.md` / `region_flyability.md` | Split-Flow | optional, nicht default |
| `weekly_briefing.md` | Briefing-Pipeline | Wochen-Fazit |
| `email_week_lead.md` | `email_service.py:595` | Mail-Lead 1-2 Saetze |

**Combined ist heute der Default-Pfad fuer Spot/Region-Analysen** — Safety und
Flyability werden in einem LLM-Call beurteilt. Die Split-Files existieren als
Token-Spar-Variante (kleinere Prompts, separate Cache-Hits), sind aber nicht
ueberall verdrahtet.

---

## 3. Datei-Inventar

### 3.1 Pipeline-Files (skills/)

| Datei | Mode | Phase |
|-------|------|-------|
| `system_chat.md` | Chat | — |
| `chat_capabilities_guide.md` | Chat | — |
| `foehn_chat_knowledge.md` | Chat | — |
| `foehn_llm_regional_guide.md` | Analyse-Header | — |
| `spot_combined.md` | spot | combined |
| `spot_safety.md` | spot | safety |
| `spot_flyability.md` | spot | flyability |
| `region_combined.md` | region | combined |
| `region_safety.md` | region | safety |
| `region_flyability.md` | region | flyability |
| `weekly_briefing.md` | Briefing | — |
| `email_week_lead.md` | Mail | — |

### 3.2 Shared-Bausteine (skills/shared/)

Generische Bausteine (in beiden Modes):

| Datei | Zweck |
|-------|-------|
| `_core_principles.md` | Anti-Halluzinations-Regeln 2a/2b/2c, Zahlen 1:1, WIND-WRONG-Semantik |
| `_input_map.md` | Datenblock-Aufbau: Stunden-Zeilen, Drucklevel, TAGESPROFIL |
| `_status_derivation.md` | 35 %-Regel, Status-Ableitung (vorher `_tages_override.md`) |
| `_safety_subratings.md` | 5 Safety-Sub-Ratings (wind/gust/aloft/foehn/weather), Weakest-Link |
| `_flyability_rules.md` | 2-Achsen-Architektur, Sub-Rating-Anker, TQ-Downgrade-Regel (vorher `_safety_experience.md`) |
| `_prose_style.md` | TQ-Tags → natuerliche Sprache, Bewoelkungs-Labels, Konsistenz-Pflicht (vorher `_formulierungs_tabelle.md`) |

Mode-spezifische Bausteine (mode-conditional eingefuegt):

| Datei | Mode | Zweck |
|-------|------|-------|
| `_hazards_spot.md` | spot | Alle 7 Gefahrenbloecke inkl. Block 3 Boeen (vorher `_hazard_blocks.md`) |
| `_hazards_region.md` | region | 6 Gefahrenbloecke ohne Boeen, ohne ALOFT-GUST — schmaler |
| `_spot_context.md` | spot | WIND-OK/WRONG-Sektor + Bemerkungs-Logik (SAFETY/FLYABILITY/BEIDES) |
| `_region_context.md` | region | Magnitude-Wind-Tags, kein Boeen-Modell, Foehn-Richtungs-Check |
| `_flight_subratings_region.md` | region | 4 Flight-Sub-Ratings (thermal/window/wind/xc) |
| `_flight_subratings_spot.md` | spot | 5 Flight-Sub-Ratings (+ altitude_rating, 25 % Gewicht) |
| `_streckenflug.md` | spot, flyability/combined | XC-Synthese top/moderat/lokal/kein_xc + Konflikt-Check |

---

## 4. LLM-Output vs. Engine-Compute

Der zentrale Trennstrich in v1.3: **Was die LLM ausgibt** vs. **was die Engine
deterministisch ableitet**. Verstanden als Pipeline:

```
Datenblock → LLM → roher JSON → Engine-Postprocess → finaler Cache-Eintrag
```

### 4.1 LLM-Output (was die Skills verlangen)

**Safety-Phase / Combined-Safety-Teil:**
- `safety_status` — `safe` / `conditional` / `not_safe`
- `safe_window` — Zeitbereich
- `no_go_reasons[]`, `caution_notes[]`
- `primary_no_go`, `primary_caution`
- `wind_summary`, `wind_shear`
- `foehn_risk` — `none|low|moderate|high`
- **5 Safety-Sub-Ratings 1–10**: `wind_safety_rating`, `gust_safety_rating`,
  `aloft_safety_rating`, `foehn_safety_rating`, `weather_safety_rating`
- `summary` (Prosa, 4–6 Saetze)

**Flyability-Phase / Combined-Flyability-Teil:**
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

### 4.2 Engine-Compute (was die App ableitet)

In `engine/_common.py` und `engine/decision_engine.py`:

| Feld | Quelle | Zweck |
|------|--------|-------|
| `rating` (0–10) | `_compute_rating_from_subratings` | Gewichteter Mix aus 4–5 Flight-Sub-Ratings |
| `experience_score` (0–100) | `_compute_experience_score` | rating × 10, kosmetische Skala |
| `experience_stars` (0–5) | `_compute_experience_stars` | Mapping experience_score → Sterne (§8.3) |
| `safety_rating` (0–10) | `_compute_safety_rating` | **Weakest-Link** der 5 Safety-Sub-Ratings |
| `safety_score` (0–100) | `_compute_safety_score` | safety_rating × 10 |
| `safety_band` | `compute_safety_band` | **Hybrid**: Hard-Overrides + safety_score → green/amber/red/no_data |
| `comfort_index` (0–100) | `compute_comfort_index` | Texture-Wert aus rough_pct (kein Rating-Effekt) |
| `flyability_tier` | `compute_legacy_flyability_tier` | **§9.7 View**: aus (safety_band, experience_stars) |
| `fly_status` | identisch mit flyability_tier | Synonym, fuers UI |

**Single Source of Truth (§9.7):** Der LLM-Output von `flyability_tier`/`fly_status`
wird in `analyzers.py:1884` ueberschrieben durch `compute_legacy_flyability_tier`:

```
safety_band == 'red'                  → ''
stars >= 4 AND safety_band == 'green' → 'violet'
stars >= 2                            → 'green'
sonst                                 → 'gray'
```

**Hard-Overrides der Decision-Engine** (THUNDERSTORM, CAPE-DANGER, RAIN-WARN,
BOEEN-FLOOR, FoehnDanger usw.) erzwingen `safety_status`/`safety_band`
deterministisch, bevor die Score-Logik greift.

### 4.3 Begriffs-Klarstellung

Diese Begriffe **gibt es im Code**:

- `rating` = 0–10 Flyability-Gesamtrating (deterministisch aus Sub-Ratings)
- `experience_stars` = 0–5 User-Sprache "Rating 1–5"
- `safety_rating` = 0–10 Safety-Gesamtrating (Weakest-Link der 5 Subs)
- `safety_band` = green/amber/red/no_data (Hybrid)
- `flyability_tier` / `fly_status` = gray/green/violet (View-abgeleitet)
- `comfort_index` = 0–100 Texture

Diese Begriffe **gibt es NICHT** (oft in Konversation verwendet, aber nicht
im Schema):

- ~~`rating_flyability`~~ — heisst `rating` oder `experience_score`/`experience_stars`
- ~~`rating_safety`~~ — heisst `safety_rating` oder `safety_score`/`safety_band`

---

## 5. Pro-Skill-Steckbrief

### 5.1 system_chat.md
Chat-System-Prompt. Erfahrener Gleitschirm-Fluglehrer. Definiert harte Regel:
Voranalysen sind bindend, `not_safe` darf NIE empfohlen werden. Nennt Skill-
Referenzen, Bewertungs-Modell, Antwort-Regeln, Visualisierungs-Tags, Tool-Nutzung.

**Hinweis:** File enthaelt teilweise **veraltete Referenzen** (Bronze/Gruen/
Violett als Primaer-Sprache, alte Skill-Namen). Capabilities-Guide ist
Konzept-aktueller — bei Konflikt Capabilities-Guide vorziehen.

### 5.2 chat_capabilities_guide.md
Faehigkeiten-Inventar fuer den Chat-Berater. Beschreibt 28+ Spots, 29 Regionen,
3 Tools (geocode, isochrone, clear_map), 11 Visualisierungs-Tags. Konzept v1.3
explizit nachgezogen (safety_band + experience_stars als 2 Achsen, comfort_index
als Texture, Legacy-Felder gekennzeichnet).

### 5.3 foehn_chat_knowledge.md
Foehn-Wissensbasis fuer Chat-Antworten. Sued vs. Nord, regionale Besonderheiten,
versteckter Foehn, Schwellen, Synergien (Foehn + Kaltfront/Thermik/Inversion).

### 5.4 foehn_llm_regional_guide.md
Analyse-Header-Block. Format-Platzhalter `{dp_caution}`, `{crest_caution}`,
`{sued_start/end}` werden via `prompts.format_foehn_llm_regional_guide()`
gefuellt aus `foehn_indicators.py`-Konstanten.

### 5.5 spot_combined.md / region_combined.md
Aktive Default-Pipelines. Verlangen safety_status + alle Sub-Ratings + alle
Prosa-Felder in einem JSON. Insert-Marker `<!-- INSERT_SHARED -->`.

### 5.6 spot_safety.md / region_safety.md
Split-Variante Phase 1. Nur Safety-Felder. `<!-- INSERT_SHARED_SAFETY -->`.

### 5.7 spot_flyability.md / region_flyability.md
Split-Variante Phase 2. Sieht `IMMUTABLE SAFETY INPUT` aus Phase 1.
`<!-- INSERT_SHARED_FLYABILITY -->`.

### 5.8 weekly_briefing.md
Wochen-Fazit fuer das Briefing. Liefert `best_weekday`, `week_summary`,
`week_rating`, `top_regions[]`, `day_highlights[]` als JSON. Score-Mapping
hangt momentan noch am Tier (violet=9, green=6) statt an `experience_stars`.

### 5.9 email_week_lead.md
1-2 Saetze Wochen-Lead fuer die Mail. Nur Wind-Richtung + spezielle
Phaenomene. Kein JSON.

### 5.10 _core_principles.md
Anti-Halluzinations-Kern. Regel 1 (rechnen verboten), 1a (runden verboten),
2 (Tags vertrauen), 2a (Histogramm-Grounding), 2a-bis (Trend-Zeilen interpretieren),
2b (Zahlen 1:1), 2c (Begruendungen aus Datenblock), 3 (Sicherheit ≠ Fliegbarkeit),
4 (WIND-WRONG ist Start-Bedingung). Glossar.

### 5.11 _input_map.md
Wie liest die LLM den Datenblock: Stunden-Zeilen, Tags (DANGER/WARN/Richtung/TQ),
Drucklevel (`*` Flugbereich, `~` Buffer), TAGESPROFIL-Block.

### 5.12 _hazards_spot.md / _hazards_region.md
KERNREGEL Stunden-Klassifikation (RUHIG/SPORTLICH/UNFLIEGBAR + STARTBAR/NICHT-STARTBAR).
TREND-VOKABULAR mit 7 Mustern (AUFKLAERUNG, ZUNEHMEND, EINGEKESSELT, DURCHGEHEND-
WARN/DANGER, VEREINZELT, STABIL). EINGEKESSELT-Sonderfaelle (Hoehenwind, Boden-
Gefahren).
**Spot-Variante:** 7 Gefahrenbloecke (Regen, Bodenwind, Boeen, Hoehenwind,
Foehn, Konvektion, Wolken).
**Region-Variante:** 6 Bloecke ohne Boeen (Block 3 entfaellt, ALOFT-GUST-Anteile
in Block 4 weggekuerzt) — Region-Tag-Set kennt keine Boeen.

### 5.13 _status_derivation.md
35 %-Regel und Status-Ableitung (Start-Fenster ≥ X h → safe/conditional/not_safe).

### 5.14 _safety_subratings.md
5 Sub-Rating-Tabellen 1–10 fuer Safety: wind / gust / aloft / foehn / weather.
Weakest-Link-Aggregation, Override-Architektur, Trend-Pflicht.

### 5.15 _flyability_rules.md
2-Achsen-Architektur-Header. fly_status-Mapping-Tabelle (rating + safety_band → tier).
Sub-Rating-Anker (Schwacher Tag / Solider Tag / Top-Tag mit thermal_rating-Bereichen).
Numerik-Regel. TQ-Downgrade-Regel auf Sub-Ratings. PRODUKTIVE-THERMIK-Check.
Conditional-Flag-Regel.

### 5.16 _flight_subratings_region.md / _flight_subratings_spot.md
Flight-Sub-Rating-Tabellen 1–10. Region: 4 Subs (thermal 35 %, window 25 %,
wind 25 %, xc 15 %). Spot: 5 Subs (thermal 30 %, window 20 %, wind 10 %, xc 15 %,
altitude 25 %). Spot-Variante hat zusaetzlich `altitude_rating` (AGL-Skala).

### 5.17 _prose_style.md
TQ-Tag → natuerliche Sprache (SHEAR/TORN/ROUGH/WIND-DEGRADED/UNUSABLE).
Konsistenz-Pflicht (Text passt zu thermal_rating). Bewoelkungs-Labels
(Booster/Reducer/Neutralzone/Cirrus).

### 5.18 _spot_context.md
WIND-OK/WIND-WRONG Sektor-Definition + "Saubere Stunde"-Begriff fuer Spots.
Spot-Bemerkungs-Logik (3 Schritte: Klassifizieren SAFETY/FLYABILITY/BEIDES,
Extrahieren, Nachjustieren).

### 5.19 _region_context.md
Magnitude-basierte Wind-Tags ohne Sektor. Boeen-Verbot fuer Region-Texte.
Foehn-Richtungs-Check (Sued/Nord/Beide-Filter).

### 5.20 _streckenflug.md
XC-Synthese (kein_xc / lokal / moderat / top) basierend auf Spot-Bewertung +
Region-Kontext. Konflikt-Check fuer Region-Hoehenwind. Wird nur in
Spot+combined/flyability eingefuegt.

---

## 6. Hot-Reload & Lokales Testen

Da `_load_skill` jeden Aufruf re-liest, kann man Skill-Files **live editieren**
und den Effekt im naechsten Request sehen — ohne `python web.py` Restart.
Voraussetzung: Cache-Regen (alte Analysen aus dem Cache invalidieren oder
Cache umschalten).

Smoke-Test fuer Prompt-Caching: `debug_scripts/smoke_test_prompt_cache.py`.
Misst Token-Groesse von `SPOT_COMBINED_PROMPT` / `REGION_COMBINED_PROMPT`
und prueft Cache-Hit-Verhalten.

---

## 7. Bekannte Drift-Stellen (Review-Stand 2026-05-01)

Nicht blocking, aber zu beruecksichtigen wenn man Skills anfasst:

- `system_chat.md` Z. 37–40, 68, 106 referenzieren nicht-existente Files
  (`safety_check.md`, `flyability.md`, `region_safety_check.md`).
- `system_chat.md` Z. 80–91 fuehrt Bronze/Gruen/Violett als Primaer-Sprache
  statt 2-Achsen — Capabilities-Guide ist konzept-aktueller.
- `weekly_briefing.md` Z. 36 mappt Score noch auf Tier statt
  `experience_stars`.
— (alle bekannten Drift-Stellen behoben in der Konsolidierung 2026-05-01.)

---

## 8. Querverweise

- **Konzept-Regeln:** `docs/RATING_CONCEPT.md` (v1.3, §1–§11)
- **Decisions-Log:** `docs/DECISIONS.md` (Sektion 5 + 5a fuer Phase-4b-Architektur)
- **Tier-Logik (Legacy-View):** `docs/FLYABILITY_TIER_LOGIK.md`
- **Datenmodell-Hintergruende:** `docs/THERMIK_MODELL.md`, `docs/WIND_BOEEN_KONZEPT.md`,
  `docs/BOEEN_MODELL.md`, `docs/BEWOELKUNG_LABELS.md`
- **Smoke-Tests:** `docs/SMOKE_TESTS.md`
