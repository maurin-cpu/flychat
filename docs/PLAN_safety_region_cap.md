# Plan: Safety-Konsistenz Region ↔ Spot

**Status:** Planung abgeschlossen, Implementierung nicht gestartet.
**Erstellt:** 2026-05-28
**Branch:** `main` (Single-Branch-Workflow)
**Wiederaufnahme:** Diese Datei lesen, dann mit Phase 1 starten.

---

## Ziel in einem Satz

Wenn die Region als `not_safe` eingestuft ist, soll ein Spot in dieser Region nicht ohne weiteres als `safe` erscheinen — aber wir wollen erst **messen**, wie haeufig und mit welcher Ursache der Inkonsistenz-Fall auftritt, bevor wir einen Cap-Mechanismus bauen.

## Hintergrund / Motivation

User-Beobachtung 2026-05-28: Bei roter Region (`not_safe`) erscheinen Spots in dieser Region als `safe` — das wirkt fuer den Piloten inkonsistent und untergraebt das Vertrauen ins Safety-System.

**Befund nach Code-Check (`engine/analyzers.py`):**
- `_safety_analysis_single_spot_day(spot, date_str, ctx)` bekommt **kein** `region_result` (Z322)
- Spot-Safety- und Region-Safety-Pipelines laufen heute **vollstaendig unabhaengig**
- `region_result` wird nur an Flyability weitergegeben (Z121) — und das auch nur fuer den Streckenflug-Block, der gerade entfernt wird
- Keine Logik existiert, die Spot.safety_status gegen Region.safety_status absichert

**Theoretische Faelle wo Spot trotz Region-`not_safe` legitim `safe` sein kann:**
- Spot im Lee bei flaechigem Region-Wind (Tal-System, geschuetzte Hangrichtung)
- Spot ausserhalb lokaler Gewitter-/Niederschlagszelle
- Region-Aggregat durch einzelne Hochwind-Refpoints verzerrt

**Theoretische Faelle wo Spot fixed sein muesste aber Engine `safe` sagt (= Bug):**
- Region erkennt Foehn, Spot mit passendem `kritischer_foehn` sieht nichts → Defekt in Spot-Foehn-Erkennung, **nicht** ein fehlender Cap
- Region erkennt grossflaechigen Hochwind aloft, Spot ignoriert ihn

→ Wir wissen heute nicht, welche Sorte Faelle die haeufige ist. Ohne Daten kein guter Cap.

## Entscheidungen (alle vom User bestaetigt)

1. **Evidenzbasiertes Vorgehen** — Telemetrie zuerst, Implementierung nach Datensicht.
2. **Drei Optionen im Auge behalten** — siehe Eskalations-Schwellen in Phase 3.
3. **Option C (voller Cap `max(spot, region)`) explizit ausgeschlossen** — verschenkt legitime Lee-Spots, hohe False-Positive-Rate.
4. **Safety bleibt deterministisch, kein LLM-Cap** — Engine-only.
5. **Skills bleiben unveraendert** — Safety-Cap beruehrt sie nicht.
6. **Telemetrie-Feld lebt in `_status_telemetry`** — bereits bestehende Stelle fuer interne Beobachtungen.
7. **Eskalations-Schwellen festgelegt** — < 5% Mismatch → A reicht; 5-20% mit klaren flaechigen Ursachen → B selektiv; > 20% → Pipeline-Audit statt Cap.

## Die drei Optionen (zur Erinnerung)

| Option | Wirkung | Status |
|---|---|---|
| **A — Caution-Awareness** | Spot uebernimmt Region-`no_go_reasons` als Spot-`caution_notes`. Keine Status-Aenderung, nur Sichtbarkeit. | Kandidat |
| **B — Conditional-Eskalation selektiv** | Wenn Region `not_safe` UND Region-Grund ist flaechig (Foehn-Match / Gewitter / widespread Regen / Hochwind aloft) → Spot `safe` → `conditional`. | Kandidat |
| **C — Voller Cap** | `spot.safety_status = max(spot, region.safety_status)` strikt | **Verworfen** |

---

## Vier Phasen

### Phase 1 — Telemetrie einbauen (30 Min Code)

- [ ] `engine/analyzers.py` — in `_build_and_analyze_spot` (oder direkt nach Spot-Safety-Berechnung) pruefen, ob `region_result` parallel verfuegbar ist (via `_lookup_region_result(spot.region_id, date_str)` — Pattern aus Z1521)
- [ ] Bei Region-Spot-Mismatch (Region.safety_status != Spot.safety_status) ein Telemetrie-Feld setzen:
  ```python
  spot_result["_status_telemetry"]["region_spot_safety_mismatch"] = {
      "region_status": region_result["safety_status"],
      "spot_status": spot_result["safety_status"],
      "region_no_go_reasons": region_result.get("no_go_reasons", []),
      "region_foehn_risk": region_result.get("foehn_risk", "none"),
      "spot_foehn_risk": spot_result.get("foehn_risk", "none"),
      "date": date_str,
  }
  ```
- [ ] **KEINE Status-Aenderung am Spot** — nur Logging.
- [ ] Test: ein Mismatch-Fall in Tests konstruieren → Telemetrie-Feld vorhanden, Status unveraendert.
- [ ] **Commit:** `feat(telemetry): region-spot-safety-mismatch logging (no enforcement)`

### Phase 2 — Daten sammeln (2 Wochen, User-Action)

- [ ] Cache taeglich regenerieren (existiert vermutlich als Cronjob / User-Workflow)
- [ ] Skript `scripts/extract_safety_mismatch_telemetry.py` (klein, ~30 Zeilen) — durchlaeuft Cache, extrahiert alle Records mit `_status_telemetry.region_spot_safety_mismatch != None` → jsonl
- [ ] Output: Anzahl Mismatch-Tage pro Region, dominante `no_go_reasons`, Foehn-Korrelation
- [ ] **Kein Commit fuer Phase 2** — User-Aktion, Daten liegen lokal.

### Phase 3 — Auswertung + Entscheidung (2h Analyse)

- [ ] Mismatch-Haeufigkeit pro Region und Gesamt
- [ ] Dominante Ursachen kategorisieren:
  - **Flaechige Ursachen** (sollten Spot betreffen): Foehn, widespread Gewitter / Regen, Hochwind aloft
  - **Lokale Ursachen** (Spot legitim besser): Bodenwind aus geschuetztem Sektor, lokale Gewitterzelle ausserhalb Spot
- [ ] Entscheidungsmatrix:
  - **< 5% Mismatch** → Option A reicht (Awareness genuegt, kein Cap noetig)
  - **5-20% mit klar flaechigen Ursachen** → Option B selektiv fuer diese Ursachen
  - **> 20%** → Pipeline-Audit: Spot-Pipeline erkennt flaechige Phaenomene nicht zuverlaessig → Defekt fixen, kein Cap
- [ ] **Output:** Entscheidung A oder B oder Audit, mit Begruendung in `_status_telemetry.cap_decision`

### Phase 4a — Option A: Caution-Awareness (~1h Code, falls Phase 3 = A)

- [ ] Deterministische Logik in `_post_process_safety_spot` (oder Safety-Merge):
  - Wenn Region.safety_status in {`not_safe`, `conditional`}:
    - `spot.caution_notes.append(f"Region {region_name} ist {region_status} wegen {top_no_go_reason} — lokal pruefen.")`
  - **KEIN** Status-Cap.
- [ ] Test: Spot bleibt `safe`, hat aber neue `caution_note` mit Region-Hinweis.
- [ ] Frontend zeigt `caution_notes` bereits an — nichts zu aendern.
- [ ] **Commit:** `feat(safety): Region-Caution-Awareness in Spot caution_notes`

### Phase 4b — Option B: Conditional-Eskalation selektiv (~2h Code + Tests, falls Phase 3 = B)

- [ ] Deterministische Cap-Regel **nur fuer flaechige Region-Phaenomene**:
  ```python
  if region_result.safety_status == "not_safe":
      flat_reasons = _classify_flat_reasons(region_result.no_go_reasons)
      foehn_match = (region_result.foehn_risk == "high" and spot["kritischer_foehn"] in flat_reasons["foehn_dirs"])
      thunderstorm = "thunderstorm" in flat_reasons
      widespread_rain = "widespread_rain" in flat_reasons
      if foehn_match or thunderstorm or widespread_rain:
          spot_result.safety_status = _max_severity(spot_result.safety_status, "conditional")
          spot_result.caution_notes.append(f"Region-Eskalation: {trigger}")
  ```
- [ ] **KEIN Cap fuer:** reinen Bodenwind (Spot kann legitim besser sein), Wind-Sektor (Spot-Konfig ist Quelle der Wahrheit), `wind_strong_count` (lokal sehr unterschiedlich)
- [ ] Tests: drei reale Faelle aus Phase 2 als Regression-Tests (positiv = eskaliert, negativ = bleibt safe)
- [ ] **Commit:** `feat(safety): selective Region-to-Spot conditional escalation`

---

## Risiken und Gegenmassnahmen

| Risiko | Mitigation |
|---|---|
| Telemetrie-Feld fehlt bei alten Cache-Eintraegen | Phase 1 ist read-only — Felder werden ab Deploy mitgeschrieben, alte Cache-Tage werden bei Regen ueberschrieben |
| Phase 3 Auswertung zeigt zu wenig Daten (selten Region not_safe) | 2 Wochen verlaengern oder historische Synoptik-Lagen (Foehn-Episoden) gezielt abdecken |
| Option B fuehrt zu Massen-Eskalationen (False-Positives) | Tests mit echten Phase-2-Datentagen vor Deploy; Conditional ist Pilot-freundlicher als not_safe |
| Pilot ignoriert neue caution_notes (Option A wirkungslos) | Frontend-Hervorhebung als Folge-Ticket bewerten, kein Scope hier |
| Region-Lookup-Pfad in Spot-Safety bricht bei No-Region-Spots | `_lookup_region_result` faellt heute schon auf None zurueck — Telemetrie nur wenn region_result existiert |

## Abnahme-Kriterien

1. **Phase 1:** Mismatch-Telemetrie sichtbar in Cache-Records, Spot-Status unveraendert, Tests gruen
2. **Phase 2:** mindestens 14 Tage-Records mit auswertbaren Mismatch-Datensaetzen
3. **Phase 3:** schriftliche Entscheidung A / B / Pipeline-Audit mit Zahlen
4. **Phase 4a oder 4b:** Implementierung mit Regression-Tests aus realen Phase-2-Faellen

## Was bleibt unveraendert

- Skills (Safety ist deterministisch, kein LLM-Spielraum)
- Rating-System (`experience_rating`, Region-Cap aus dem Streckenflug-Plan)
- Foehn-Pipeline (Phase 4b setzt darauf auf, ohne sie zu aendern)
- 218 historische Label-Beispiele

## Nicht im Scope

- Option C (voller Cap) — explizit verworfen
- LLM-Driven Safety-Decisions — Safety bleibt deterministisch
- Frontend-Hervorhebung der neuen caution_notes (Folge-Ticket)
- Cap fuer Rating (wurde im separaten Plan / jetzigen Skills bereits geregelt)

## Wiederaufnahme-Hinweise

1. **Diese Datei lesen** — `docs/PLAN_safety_region_cap.md`
2. **`git status`** pruefen — sollte clean sein
3. **TaskList pruefen** — Tasks #9-13 verfolgen die Phasen
4. **Letzten Commit pruefen** — `git log --oneline -5` zeigt wo wir stehen
5. **Status-Tracking:** Die Checkboxen oben zeigen welche Phase dran ist
