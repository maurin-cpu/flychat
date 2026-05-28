# Plan: Eine Bewertung, eine Analyse

**Status:** Planung abgeschlossen, Implementierung nicht gestartet.
**Erstellt:** 2026-05-28
**Branch:** `main` (Single-Branch-Workflow)
**Wiederaufnahme:** Diese Datei lesen, dann mit Paket 1 starten.

---

## Ziel in einem Satz

Spots zeigen statt zwei Bewertungen (Erlebnis + Streckenflug) nur noch eine — die Streckenflug-Einschätzung wandert als Pflicht-Satz in den Analyse-Text, das LLM trifft alle Entscheidungen, die Engine setzt nichts hart durch.

## Hintergrund / Motivation

User-Beobachtung 2026-05-28: Region rating 3 + Spot rating 5 wirkte seltsam, weil die Region keinen Streckenflug zulaesst aber der Spot ein "xc_tag" verspricht. Recherche (XC Therm, Burnair, Velitherm, xcmag, Flybubble) hat gezeigt: kein etabliertes Tool macht hartes Capping, aber die Pilotenliteratur ist klar — Streckenflug-Versprechen setzt regionale Bedingungen voraus.

User-Entscheidung: kognitive Vereinfachung auf eine Achse, Streckenflug als Pflicht-Satz im Analyse-Text.

## Entscheidungen (alle vom User bestaetigt)

1. **Eine Achse:** `experience_rating` 1-5 bleibt die einzige Bewertung
2. **Streckenflug-Block entfaellt komplett** — JSON-Feld `streckenflug` (rating + limiting_factor) wird aus dem System entfernt
3. **Streckenflug-Pflicht-Satz in der Prosa** — LLM muss in `xc_details` mindestens einen Satz zum Streckenflug schreiben, der die Region-Auswertung beruecksichtigt
4. **Cap-Schwelle bei 4/5** — Bewertung 4 oder 5 nur wenn Region.experience_rating >= Spot-Rating; sonst max 3
5. **Region fehlt → kein Cap** — wenn Region-Analyse no_data/error ist, bleibt Spot wie LLM ihn setzt
6. **KEINE Engine-Overrides** — alle Entscheidungen trifft das LLM, Engine sanitisiert nur das Datenmodell
7. **`xc_potential`** (high/moderate/low) bleibt als interne Klassifikation im JSON, wird im Frontend nicht prominent gezeigt
8. **Frontend:** Streckenflug-Pille und -Sektion komplett entfernen
9. **Cache:** keine Migration, nach Deploy komplett regenerieren
10. **Hoehen-Reserve-Vergleich Region vs. Spot — konkret mit bestehendem Feld `working_height_agl_m` plus Tagesspannweite.** Das Feld existiert schon im Region-Result (`weather_context.py:2297, analyzers.py:2102`, Median Thermik-Top AGL ueber produktive Stunden, Quelle `_prod_tops_agl`). Heute wird nur der Median berechnet — fuer Variante C zusaetzlich Min, Max und Argmax-Stunde aus derselben `_prod_tops_agl`-Liste ableiten (trivial, gleicher Datenpunkt). Die Hoehen-Reserve am Spot ist Subtraktion: `working_height_at_spot_m = (region.elevation_ref + region.working_height_agl_m) − spot.elevation_m`, ausgegeben als Median **plus Best-Stunde mit Zeitstempel**. Begruendung Variante C statt nur Median: Tagesentwicklung sichtbar; hoher Spot, der morgens unter Thermik-Top liegt aber mittags ueber, sieht "Median 500m, Best 1100m@14:00 → Mittagsfenster fuer kurzen XC". Mit reinem Median wuerde der Mittagsfenster-Fall verschwinden.
11. **Eskalations-Kriterium fuer Cap-Drift** — falls Telemetrie (Region-Rating vs. Spot-Rating) > 10% Drift ueber 2 Wochen zeigt, wird die Cap-Regel als harter Engine-Override eingezogen (Reversal von Entscheidung 6). Vorbereitung: Telemetrie-Feld `_status_telemetry.cap_drift` ab Tag 1 mitschreiben.

## Die neue Bewertungs-Logik (Skill-Vorgabe ans LLM)

**Hoehen-Reserve am Spot (= "working_height_at_spot_m") — als Tagesspannweite:**

Drei Werte pro Tag, alle aus derselben Quelle (`_prod_tops_agl` Liste, bereits berechnet):
```
working_height_at_spot_m_median = (region.elevation_ref + median(_prod_tops_agl))            − spot.elevation_m
working_height_at_spot_m_max    = (region.elevation_ref + max(_prod_tops_agl))               − spot.elevation_m
working_height_at_spot_m_min    = (region.elevation_ref + min(_prod_tops_agl))               − spot.elevation_m
best_hour_str                   = Zeitstempel der Stunde mit max(_prod_tops_agl) (z.B. "14:00")
```

Quelle Region-Felder: bereits berechnet in `engine/weather_context.py:2297` als Median. Min/Max/Argmax aus derselben `_prod_tops_agl`-Liste ableiten (neu, ~10 Zeilen Code). Region-Config: `elevation_ref` (default 1200m).

**Bewertungs-Matrix (Spot — beide Achsen muessen erfuellt sein):**

Massgebend ist `working_height_at_spot_m_max` (Best-Stunde), nicht der Median. Begruendung: ein Pilot startet zur besten Stunde, nicht zum Tagesdurchschnitt. Der Median dient als Sanity-Check, der Min als Information ueber den Vor-/Nachmittagsbereich.

| Bewertung | km-Klasse (XC-Pilotenliteratur) | Region.experience_rating | working_height_at_spot_m_max (Best-Stunde) |
|---|---|---|---|
| 5 | Klassiker / >100km | = 5 | >= 2000m |
| 4 | XC 30-100km / FAI-Dreiecke | >= 4 | >= 1500m |
| 3 | Talquerung 10-30km / Halbtag | >= 3 ODER lokales Wohlfuehlen reicht | >= 1000m |
| 2 | Hausrunde / Lokal / Soaring | egal | >= 500m |
| 1 | Abgleiter | egal | < 500m oder <= 0 (Spot am Top) |

**Zeitfenster-Pflichtsatz:** Wenn `working_height_at_spot_m_max − working_height_at_spot_m_min >= 500m` (Tagesspannweite gross), MUSS der Pflichtsatz in `xc_details` das Best-Hour-Fenster benennen, z.B. "Mittagsfenster 13-15 Uhr fuer Streckenflug, vormittags lokal" — sonst genuegt ein allgemeiner Satz.

Schwellen-Herleitung (Pilotenliteratur, festhalten in `docs/RATING_CONCEPT.md`):
- 2000m AGL ueber Spot = klassische Cross-Country-Arbeitshoehe (Burnair-Faustregel, xcmag Standard-XC)
- 1500m AGL = robuste XC-Hoehe fuer 30-100km Strecken / FAI
- 1000m AGL = Talquerung machbar (kurzer XC)
- 500m AGL = Soaring/Hausrunde
- < 500m oder negativ = Abgleiter, Spot effektiv am Thermik-Top

**Konkrete Beispielfaelle (zwingend als Anker-Beispiele in `04_flight_subratings_spot.md`):**

1. **Klassiker-Tag, niedriger Spot, stabile Thermik:** Region elev_ref=1200, _prod_tops_agl=[1900, 2000, 2050, 2000, 1950]m (sehr stabil). Median 2000m, Max 2050m@14:00, Min 1900m@10:00. Spot auf 1000m → Reserve median 2200m, max 2250m, min 2100m. Region-Rating 5. → **Spot-Rating 5**. Pflichtsatz: "Klassiker mit 2200m Arbeitshoehe ueber Startplatz, Streckenflug >100km ganztaegig moeglich." (Kein Mittagsfenster noetig, weil Spannweite < 500m.)

2. **Hoher Spot, gleicher Tag:** wie oben aber Spot auf 2700m. Reserve median −500m, max −450m, min −600m. → **Spot-Rating 1-2**. Pflichtsatz: "Spot bereits ueber Region-Thermik-Top — kein Wegfliegen moeglich, allenfalls lokales Soaring an Reliefkante."

3. **Hoher Spot mit Mittagsfenster:** Region elev_ref=1500, _prod_tops_agl=[800, 1100, 1900, 2200, 1800, 1300]m (steile Tagesentwicklung). Median 1550m, Max 2200m@14:00, Min 800m@10:00. Spot auf 2200m. Reserve median 850m, **max 1500m@14:00**, min 100m@10:00. Spannweite 1400m >> 500m → Pflicht-Zeitfenster-Satz. Region-Rating 4. → **Spot-Rating 3** (Mittagsfenster reicht fuer Talquerung). Pflichtsatz: "Mittagsfenster 13-15 Uhr mit 1500m Arbeitshoehe — kurzer Streckenflug 10-30km moeglich. Vormittags und spaeter Nachmittag nur lokales Soaring."

4. **Region fehlt:** kein Region-Result → Reserve kann nicht berechnet werden. → max **Spot-Rating 3**, Pflichtsatz: "Ohne Region-Kontext keine XC-Aussage, reine Spot-Einschaetzung."

Region-Bewertung **und** working_height_agl_m + elevation_ref werden im Spot-Prompt mitgeliefert (heute fehlt beides — zwei Bugs, siehe Pre-Check Z68).

---

## Pre-Check-Inventar (read-only, abgeschlossen 2026-05-28)

### Repo-Lage
- Working tree clean — keine uncommitted Fixes
- Keine Test-Datei referenziert `streckenflug` direkt (Gluecksfall, keine Test-Migration noetig)
- 218 historische Label-Beispiele in `data/labeled_examples.jsonl`, davon 123 mit Streckenflug-Erwaehnung — bleiben unveraendert als historische Aufzeichnung

### Skills (sieben Dateien)
| Datei | Aktion |
|---|---|
| `skills/shared/04_flyability/05_streckenflug.md` | **loeschen** |
| `skills/shared/04_flyability/04_flight_subratings_spot.md` | Rating-Skala neu, Region-Voraussetzung fuer 4/5 ergaenzen, Streckenflug-Pflichtsatz vorschreiben, Z107 (Verweis auf streckenflug.rating) entfernen, Z243-244 (Konsistenz-Regel) entfernen |
| `skills/shared/04_flyability/02_flyability_rules.md` | Z8 (Achse 3: streckenflug.rating) entfernen |
| `skills/shared/04_flyability/00_template_spot.md` | JSON-Schema ohne `streckenflug`-Block (Z7, Z15, Z31, Z42, Z69) |
| `skills/shared/04_flyability/00_template_region.md` | Z9 und Z42 (Streckenflug-Erwaehnung) entfernen |
| `skills/system_chat.md` | Achsen-Beschreibung reduzieren (Z48, Z50, Z104, Z106, Z252, Z264) |
| `skills/chat_capabilities_guide.md` | Achse-3-Beschreibung raus (Z100, Z162, Z461) |

### Engine (fuenf Dateien, ~30 Stellen)
| Datei | Stellen | Aktion |
|---|---|---|
| `engine/analyzers.py` | Z95, Z749-754, Z836-845, Z1508, Z1677, Z1969, Z1988-1998, Z2003-2026, Z2193, Z2537, Z2849, Z3055, Z3333, Z3520-3522, Z3588, Z3642 | `streckenflug`-Setzen + Lesen entfernen, `_post_process_flyability_spot` schlanker; `_ = region_result` bleibt (wird nicht mehr fuer Cap genutzt, aber Param-Signatur bleibt fuer Callsite-Kompat) |
| `engine/weather_context.py` | Z2297 (Region-Pfad) + Z3250 (zweiter Region-Pfad) | **Neue Aggregation Variante C** aus bestehender `_prod_tops_agl`-Liste: zusaetzlich zum Median nun `working_height_agl_max_m`, `working_height_agl_min_m` und `working_height_agl_best_hour` (HH:MM-Stempel der Stunde mit max). Stundenstempel: die Hourly-Schleife trackt heute `_prod_tops_agl.append(thermal_top_agl)` — parallel `_prod_tops_agl_with_hour.append((thermal_top_agl, dt.hour))` ergaenzen. ~15 Zeilen Code. |
| `engine/analyzers.py` | Z2102 (`working_height_agl_m` wird schon ins Result geschrieben) + analoge Stellen | drei neue Felder ins Region-Result schreiben: `working_height_agl_max_m`, `working_height_agl_min_m`, `working_height_agl_best_hour`. Plus `region_elevation_ref_m` aus Region-Config spiegeln. |
| `engine/weather_context.py` | Z266-338 `_format_region_context_block` | **Bug-Fix 1:** `Region.experience_rating` prominent im Block ausgeben. **Bug-Fix 2:** Variante-C-Block — vier Zeilen ausgeben (siehe Skill-Vorgabe oben): Region-Arbeitshoehe-AGL (Median/Min/Max@Best-Hour), Region-Thermik-Top-MSL, Spot-Elevation, **Hoehen-Reserve am Spot (Median/Min/Max@Best-Hour)**. Berechnung in Block-Code: `(region.elevation_ref + working_height_agl_max_m) − spot.elevation_m` etc. Signatur erweitern: `_format_region_context_block(region_result, spot_region, spot_elevation_m)`. Footer-Hinweis: "Cap-Regel: nutze working_height_at_spot_m_max (Best-Stunde) fuer die Bewertung — 5 nur wenn >=2000m UND Region=5; 4 nur wenn >=1500m UND Region >=4; 3 nur wenn >=1000m. Wenn Spannweite max-min >= 500m: Pflicht Zeitfenster-Satz mit Best-Hour in xc_details." |
| `engine/chat_orchestrator.py` | Z346-350 | `streckenflug_rating` aus Chat-Day-Context entfernen |
| `engine/_common.py` | Z765-766 | `_sanitize_llm_result`-Block fuer `streckenflug` entfernen |
| `prompts.py` | Z169-171 | Skill-Bundling: `04_flyability/05_streckenflug.md` nicht mehr laden |

### Web / Skripte
| Datei | Stellen |
|---|---|
| `web.py` | Z2635-2637: `streckenflug_rating` + `streckenflug_limiting_factor` aus Spot-Payload entfernen |
| `scripts/snapshot_weather.py` | Z246, Z254-256: Streckenflug-Felder im Snapshot entfernen |

### Frontend (vier Dateien)
| Datei | Stellen |
|---|---|
| `static/js/analysis-view.js` | Z13 Kommentar, Z446-499 Streckenflug-Metric-Block, Z529-530 Streckenflug-Insight-Sektion — komplett entfernen |
| `static/js/briefing.js` | Z1613-1622: XC-Sektion + `sf`-Variable entfernen |
| `static/js/rating-info.js` | Z151-152: Erklaerungstext umschreiben zur Ein-Achsen-Architektur |
| `static/js/chat.js` | Z1102-1118: drei Quick-Action-Buttons "Streckenflug-Rating"-Text umformulieren |
| `static/css/style.css` | Z3535-3571: `.mga-metric.streckenflug` und `.mga-insight.streckenflug` Klassen entfernen (kosmetisch) |

### Admin-Template
| Datei | Stellen |
|---|---|
| `templates/admin/testing_review.html` | Z243-244, Z300, Z320: Streckenflug-Vergleichsfeld entfernen |

### Dokumentation (acht Dateien)
| Datei | Aktion |
|---|---|
| `docs/RATING_CONCEPT.md` | groesste Ueberarbeitung — neue Ein-Achsen-Architektur dokumentieren, Cap-Regel beschreiben, Begruendung festhalten (warum eine Achse, warum keine Engine-Overrides) |
| `docs/RATING_ARCHITECTURE.md` | v2.1 → v3.0, Streckenflug-Achse raus |
| `docs/RATING_FARBKONZEPT.md` | Streckenflug-Erwaehnung raus |
| `docs/DECISIONS.md` | Sektion 5/5a — Streckenflug-Decision-Tags raus; neue Decision dokumentieren (kein neuer Engine-Tag, da LLM-only) |
| `docs/SKILLS_ARCHITECTURE.md` | streckenflug-Skill-File-Verweis raus |
| `docs/TAGS.md` | falls Streckenflug-Tags referenziert, raus |
| `docs/STARTBARKEIT.md` | Streckenflug-Erwaehnungen pruefen |
| `docs/ADMIN_GOLDSTANDARD_REGRESSION.md` | Goldstandard-Vergleichsfelder anpassen |

### Was bleibt unveraendert
- `xc_potential` (high/moderate/low) — interne Klassifikation, bleibt im JSON
- `xc_details` — Prosa-Feld, wird zum Pflicht-Traeger des Streckenflug-Satzes
- `safety_status` / `safety_band` — orthogonal
- Foehn-Pipeline
- Re-Narrate-Pfad
- `_status_telemetry` / SubRatingFloor — bleibt
- Decision-Engine sonst
- 218 historische Label-Beispiele

---

## Sieben Arbeitspakete (Reihenfolge)

### Paket 1 — Skills ueberarbeiten (90 Min, hoch-eingeschaetzt wegen Brittleness)
- [ ] `05_streckenflug.md` loeschen
- [ ] `04_flight_subratings_spot.md` — **Rating-Matrix als 2-Achsen-Tabelle (Region.experience_rating × working_height_at_spot_m mit konkreten m-Schwellen aus Entscheidung 10)**. Pflicht-Vergleich `working_height_at_spot_m` (aus Region-Block uebernehmen, NICHT selbst rechnen) und km-Klasse-Zuordnung (5=Klassiker >100km, 4=XC 30-100km, 3=Talquerung 10-30km, 2=lokal, 1=Abgleiter). Streckenflug-Pflichtsatz in `xc_details` muss die konkrete Reserve-Zahl nennen ("XYZm Arbeitshoehe ueber Startplatz") und die km-Klasse benennen. **Vier Anker-Beispiele** (Klassiker niedriger Spot, Klassiker hoher Spot mit Cap, Spot ueber Region-Top, Region fehlt) — Zahlen aus dem Plan uebernehmen
- [ ] `02_flyability_rules.md` — Achse 3 raus
- [ ] `00_template_spot.md` — JSON-Schema ohne `streckenflug`
- [ ] `00_template_region.md` — Streckenflug-Erwaehnungen raus, `peak_thermal_top_m` als neues Pflicht-Feld dokumentieren
- [ ] `system_chat.md` — Achsen-Beschreibung reduzieren
- [ ] `chat_capabilities_guide.md` — Achse 3 raus
- [ ] **Commit:** `feat(skills): rating semantics — eine Achse, Streckenflug als Pflicht-Satz`

### Paket 2a — Region-Kontext-Bug-Fix mit Variante C (eigener Commit, 60 Min, bisectable)
- [ ] `engine/weather_context.py` Z2297/Z3250 — Aggregation erweitern: aus `_prod_tops_agl` zusaetzlich max, min und Argmax-Stundenstempel berechnen; dafuer `_prod_tops_agl_with_hour: list[tuple[int, int]]` parallel aufbauen
- [ ] `engine/analyzers.py` Z2102 + analoge Stellen — alle vier Werte ins Region-Result schreiben (`working_height_agl_m`, `working_height_agl_max_m`, `working_height_agl_min_m`, `working_height_agl_best_hour`); `region_elevation_ref_m` aus Config spiegeln; in allen Region-Code-Pfaden setzen (safe + conditional)
- [ ] `engine/weather_context.py` `_format_region_context_block` — Signatur um `spot_elevation_m` erweitern. Variante-C-Output (vier Zeilen): Region-Rating, Region-Arbeitshoehe-AGL mit Spannweite, Region-Thermik-Top-MSL, Hoehen-Reserve am Spot mit Median + Best-Stunde. Footer-Hinweis erst in Paket 2b umschreiben.
- [ ] Callsites von `_format_region_context_block` mitziehen
- [ ] **Commit:** `fix(weather): Region-Rating + working_height_at_spot mit Tagesspannweite im Spot-Prompt`

### Paket 2b — Streckenflug-Block entfernen (eigener Commit, 60 Min)
- [ ] `engine/weather_context.py` — Footer-Hinweis auf Cap-Regel umschreiben (Bezug auf eine Achse + Hoehen-Reserve)
- [ ] `engine/analyzers.py` — `streckenflug`-Setzen + Lesen entfernen
- [ ] `engine/chat_orchestrator.py` — `streckenflug_rating` aus Chat-Context
- [ ] `engine/_common.py` — `_sanitize_llm_result`-Block raus
- [ ] `prompts.py` — Skill-Bundling raus
- [ ] `web.py` — Spot-Payload bereinigen
- [ ] `scripts/snapshot_weather.py` — Snapshot-Felder raus
- [ ] **Cache-Lesepfad pruefen:** gibt es strikte Deserialisierung (Pydantic / dict-Schluessel-Check), die ein **fehlendes** `streckenflug`-Feld in alten Cache-Dateien ablehnt? Falls ja: tolerantes Lesen sicherstellen, bis Cache regeneriert ist
- [ ] **Commit:** `refactor(engine): streckenflug-Block entfernt`

### Paket 3 — Tests (30 Min)
- [ ] `python -m unittest tests.test_decision_engine` — Baseline gruen?
- [ ] Neue Tests fuer Datenmodell:
  - `streckenflug`-Key NICHT in Spot-Result nach `_post_process_flyability_spot`
  - `_format_region_context_block` enthaelt `experience_rating` der Region
  - Region-Result enthaelt die vier neuen Felder (`working_height_agl_m`, `_max_m`, `_min_m`, `_best_hour`) in allen Pfaden (safe und conditional)
  - Aggregations-Test fuer Variante C: `_prod_tops_agl = [800, 1100, 1900, 2200, 1800, 1300]` mit Stunden [10,11,12,13,14,15] → median=1550, max=2200, max_hour=13, min=800, min_hour=10
  - Rechentest fuer Block: elev_ref=1500, working_height_agl_max_m=2200, best_hour=13, spot.elevation_m=2200 → Block enthaelt Zeile mit "max 1500m@13:00" als Reserve am Spot
  - Spannweiten-Test: max-min >= 500m → Block-Output enthaelt expliziten Hinweis "Spannweite gross — Zeitfenster-Pflichtsatz noetig"
- [ ] Alle 130+ Tests muessen gruen bleiben
- [ ] **Commit:** `test: Datenmodell ohne streckenflug-Feld + Hoehen-Reserve-Block`

### Paket 4 — Frontend aufraeumen (45 Min)
- [ ] `analysis-view.js` — Streckenflug-Metric + Insight raus
- [ ] `briefing.js` — XC-Sektion raus
- [ ] `rating-info.js` — Erklaerungstext umschreiben
- [ ] `chat.js` — Quick-Actions umformulieren
- [ ] `style.css` — Streckenflug-Klassen entfernen
- [ ] **Browser-Test:** Dev-Server starten, ein Spot in Region mit Cap-Case anschauen
- [ ] **Commit:** `feat(frontend): streckenflug-Pille entfernt, Analyse-Text prominent`

### Paket 5 — Admin-Tool (10 Min)
- [ ] `templates/admin/testing_review.html` — Streckenflug-Vergleichsfelder entfernen
- [ ] **Commit:** `chore(admin): streckenflug aus Goldstandard-Review entfernt`

### Paket 6 — Dokumentation (30 Min)
- [ ] `docs/RATING_CONCEPT.md` — Ein-Achsen-Architektur, Cap-Regel, Begruendung
- [ ] `docs/RATING_ARCHITECTURE.md` — v3.0
- [ ] `docs/RATING_FARBKONZEPT.md` — Streckenflug raus
- [ ] `docs/DECISIONS.md` — neue Decision dokumentieren
- [ ] `docs/SKILLS_ARCHITECTURE.md` — Skill-File-Verweis raus
- [ ] `docs/TAGS.md`, `docs/STARTBARKEIT.md`, `docs/ADMIN_GOLDSTANDARD_REGRESSION.md` — durchschauen, anpassen
- [ ] **Commit:** `docs: RATING_CONCEPT v3.0 — eine Achse, eine Analyse`

### Paket 7 — Cache regenerieren (User-Action)
- [ ] User startet Cache-Regen via Web-UI oder Script
- [ ] Stichprobentest an einem realen Tag: Bewertung 5 nur wenn Region 5
- [ ] Frontend zeigt keinen Streckenflug-Block mehr

---

## Risiken und Gegenmassnahmen

| Risiko | Mitigation |
|---|---|
| LLM ignoriert Cap-Regel (Spot 5 bei Region 3) | Telemetrie loggt `_status_telemetry.cap_drift` mit Region-Rating, Spot-Rating und Hoehen-Reserve; bei Drift > 10% nach 2 Wochen → Entscheidung 11 (harter Engine-Override) ziehen |
| Veralteter Cache beim ersten Start | Cache wird direkt nach Deploy regeneriert, keine Kompat-Schicht; Engine liest tolerant (fehlendes `streckenflug` in altem Cache crasht nicht) |
| Streckenflug-Satz fehlt im Prosa-Text | Skill macht es zur expliziten Pflicht mit Anker-Beispielen |
| Frontend zeigt Lueck wenn `streckenflug`-Feld weg ist (alte Cache-Datei + neuer JS-Code) | JS-Code defensiv: `a.streckenflug_rating` wird optional behandelt, kein Crash |
| `working_height_agl_m` ist Median ueber produktive Stunden — Spike-Stunden gehen nicht ein | Bestehende Quelle ist konservativ (Filter productive_h_strict mit climb >= 1.5 m/s + Cloud-OK, siehe `weather_context.py:1488`). Kein neuer Aggregations-Code noetig. |
| Hoehen-Reserve negativ bei Hoehen-Spots — LLM verwirrt | Skill-Anker-Beispiel 3 (Spot ueber Region-Top mit Reserve −200m) explizit; Block-Output schreibt negative Reserve als `working_height_at_spot_m: -200m (Spot ueber Region-Thermik-Top)` damit LLM die Lage erkennt |
| LLM rechnet selbst statt vorgegebene Reserve zu nutzen | Block-Output schreibt Reserve **als fertige Zahl** vor; Skill verbietet explizit Eigen-Rechnung ("nutze working_height_at_spot_m aus dem Block, rechne nicht selbst") |
| Rollback noetig (Cap-Regel macht Probleme) | Single-Branch + `git revert <commit-range>` + Cache-Regen. Commits sind bewusst klein (Paket 2a/2b getrennt) — revert kann selektiv erfolgen |

## Abnahme-Kriterien

1. Pro Spot eine Bewertung und ein Analyse-Block mit Streckenflug-Satz
2. Keine Streckenflug-Pille mehr in der UI
3. Bestehende Test-Suite (130 Tests) bleibt gruen
4. Cache neu generiert, alte Datenfeld-Reste sind weg
5. Manueller Stichprobentest an einem Klassiker-Tag: Bewertung 5 erscheint nur wenn Region=5 **und** working_height_at_spot_m_max (Best-Stunde) >= 2000m
6. Spot-Prompt enthaelt nachweislich (Prompt-Dump im Debug-Modus pruefen):
   - `Region.experience_rating`
   - Region-Arbeitshoehe-AGL **mit Median, Min und Max@Best-Hour**
   - `Region.elevation_ref`
   - `spot.elevation_m`
   - **berechneter Wert** `working_height_at_spot_m` als Median + Min + Max@Best-Hour-Zeile
7. Hoehen-Spot-Mittagsfenster-Stichprobe **mit konkreten Zahlen:** Spot mit `elevation_m = 2200m` in Region elev_ref=1500, `_prod_tops_agl = [800, 1100, 1900, 2200, 1800, 1300]@[10,11,12,13,14,15]`. Erwartet: Block schreibt "Reserve am Spot: Median 850m, Max 1500m@13:00, Min 100m@10:00". LLM-Output: **Spot-Rating 3** mit `xc_details`-Pflichtsatz, der "1500m" und "13:00" oder "Mittagsfenster" konkret nennt.
8. Stabiler-Klassiker-Stichprobe **mit konkreten Zahlen:** Region.experience_rating=5, `_prod_tops_agl=[1900,2000,2050,2000,1950]` (Spannweite 150m, < 500m → kein Zeitfenster-Pflichtsatz), Spot.elevation_m=1000. Erwartet: Spot-Rating 5, allgemeiner XC-Pflichtsatz ohne Zeitfenster-Detail.
9. Schwach-Region-Stichprobe: Region.experience_rating=3, working_height_agl_max_m=800m → kein Spot-Rating 4 oder 5, unabhaengig vom Spot. Pflichtsatz: "Region-Arbeitshoehe nur ~800m AGL, kein XC moeglich."

---

## Wiederaufnahme-Hinweise (fuer naechste Session / anderen Rechner)

1. **Diese Datei lesen** — `docs/PLAN_eine_bewertung_eine_analyse.md`
2. **`git status`** pruefen — sollte clean sein
3. **Letzten Commit pruefen** — `git log --oneline -5` zeigt wo wir stehen
4. **Status-Tracking:** Die Checkboxen oben zeigen welches Paket dran ist. Nach Abschluss eines Pakets Checkboxen abhaken und committen.
5. **Memory-Pointer:** Memory-Entry `plan_eine_bewertung_eine_analyse` verweist auf diese Datei
6. **Recherche-Quellen** (falls noetig):
   - XC Therm Regtherm Topographie-Regionen
   - Burnair FAQ "Konflikt Spot vs Region"
   - Velitherm hoehendifferenziert
   - xcmag Stability & Inversions / Seabreeze Convergence
   - Flybubble Thermal Hunting

## Offene Punkte

- Keine. Alle User-Entscheidungen sind getroffen, Pre-Check ist abgeschlossen.

## Nicht im Scope

- Pilotenprofil-Filter (Backlog §10.1)
- Pure-Rohdaten-Modus (Backlog §10.2)
- Lernen aus Klick-Mustern (Backlog §10.3)
- Aenderungen am Safety-Pipeline
- Aenderungen an der Foehn-Logik
- Aenderungen an Tags-System v5
