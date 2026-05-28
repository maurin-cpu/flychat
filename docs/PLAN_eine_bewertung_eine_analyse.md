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

## Die neue Bewertungs-Logik (Skill-Vorgabe ans LLM)

| Bewertung | Bedeutung | Voraussetzung |
|---|---|---|
| 5 | Klassiker | Region.experience_rating = 5 |
| 4 | Starker XC-tauglicher Tag | Region.experience_rating >= 4 |
| 3 | Solider Halbtag, Hausrunde | lokales Wohlfuehlen reicht |
| 2 | Suchtag | wie bisher |
| 1 | Abgleiter | wie bisher |

Region-Bewertung wird im Spot-Prompt mitgeliefert (heute fehlt sie — Bug).

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
| `engine/weather_context.py` | Z266-338 `_format_region_context_block` | **Bug-Fix:** `Region.experience_rating` prominent im Block ausgeben (fehlt heute, Streckenflug-Skill Z26 rechnet schon damit). Footer-Hinweis Z278-280 + Z327 + Z333-337 umschreiben: "Nutze fuer Cap-Regel — Spot rating 4/5 nur wenn Region >= Spot" |
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

### Paket 1 — Skills ueberarbeiten (45 Min)
- [ ] `05_streckenflug.md` loeschen
- [ ] `04_flight_subratings_spot.md` — Rating-Skala neu, Region-Voraussetzung 4/5, Streckenflug-Pflichtsatz
- [ ] `02_flyability_rules.md` — Achse 3 raus
- [ ] `00_template_spot.md` — JSON-Schema ohne `streckenflug`
- [ ] `00_template_region.md` — Streckenflug-Erwaehnungen raus
- [ ] `system_chat.md` — Achsen-Beschreibung reduzieren
- [ ] `chat_capabilities_guide.md` — Achse 3 raus
- [ ] **Commit:** `feat(skills): rating semantics — eine Achse, Streckenflug als Pflicht-Satz`

### Paket 2 — Engine saeubern (60 Min)
- [ ] `engine/weather_context.py` — Region-Rating im Block ausgeben (Bug-Fix), Footer-Hinweis umschreiben
- [ ] `engine/analyzers.py` — `streckenflug`-Setzen + Lesen entfernen
- [ ] `engine/chat_orchestrator.py` — `streckenflug_rating` aus Chat-Context
- [ ] `engine/_common.py` — `_sanitize_llm_result`-Block raus
- [ ] `prompts.py` — Skill-Bundling raus
- [ ] `web.py` — Spot-Payload bereinigen
- [ ] `scripts/snapshot_weather.py` — Snapshot-Felder raus
- [ ] **Commit:** `refactor(engine): streckenflug-Block entfernt, Region-Rating im Spot-Prompt`

### Paket 3 — Tests (15 Min)
- [ ] `python -m unittest tests.test_decision_engine` — Baseline gruen?
- [ ] Neue Tests fuer Datenmodell:
  - `streckenflug`-Key NICHT in Spot-Result nach `_post_process_flyability_spot`
  - `_format_region_context_block` enthaelt `experience_rating` der Region
- [ ] Alle 130+ Tests muessen gruen bleiben
- [ ] **Commit:** `test: Datenmodell ohne streckenflug-Feld`

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
| LLM ignoriert Cap-Regel (Spot 5 bei Region 3) | Telemetrie loggt `_status_telemetry` mit Region-Rating und Spot-Rating; nach 2 Wochen Skill-Schaerfung wenn Drift > 10% |
| Veralteter Cache beim ersten Start | Cache wird direkt nach Deploy regeneriert, keine Kompat-Schicht |
| Streckenflug-Satz fehlt im Prosa-Text | Skill macht es zur expliziten Pflicht mit Anker-Beispielen |
| Frontend zeigt Lueck wenn `streckenflug`-Feld weg ist (alte Cache-Datei + neuer JS-Code) | JS-Code defensiv: `a.streckenflug_rating` wird optional behandelt, kein Crash |

## Abnahme-Kriterien

1. Pro Spot eine Bewertung und ein Analyse-Block mit Streckenflug-Satz
2. Keine Streckenflug-Pille mehr in der UI
3. Bestehende Test-Suite (130 Tests) bleibt gruen
4. Cache neu generiert, alte Datenfeld-Reste sind weg
5. Manueller Stichprobentest an einem Klassiker-Tag: Bewertung 5 erscheint nur wenn Region 5

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
