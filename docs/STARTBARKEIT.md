# Startbarkeit — die dritte Kategorie neben Sicherheit und Fliegbarkeit

**Stand**: 2026-05-02
**Status**: dokumentiert nach Refactor (WIND-WRONG aus Hazards-Histogramm entfernt)

---

## Problem

Windrichtung am Spot ist **weder Sicherheit noch Fliegbarkeit**, sondern eine eigene dritte Kategorie:

| Kategorie | Frage | Beispiel-Tags |
|---|---|---|
| Sicherheit | Droht in der Luft Gefahr? | `[RAIN-WARN]`, `[WIND-DANGER]`, `[GUST-DANGER]`, `[THUNDERSTORM]` |
| Fliegbarkeit | Wie gut fliegt es sich? | `[SHEAR-DEGRADED]`, `[THERMAL-WIND-UNUSABLE]` |
| **Startbarkeit** | **Kann ich ueberhaupt starten?** | **`[WIND-OK]`, `[WIND-WRONG]`** |

Andere Flyability-Parameter (Thermik, Wolken, Hoehe) sagen "wie gut fliegt es sich" — Bewertung auf einer Skala. **Startbarkeit ist binaer**: Richtung passt oder passt nicht. Wenn die Richtung nicht stimmt, kann der Pilot gar nicht erst starten — egal wie gut Thermik oder Sichtbedingungen sind.

`[WIND-WRONG]` lebt dadurch zwischen den Stuehlen. Frueher tauchte es im Datenblock im Histogramm `Hauptgefahren am Tag:` neben echten Hazards wie `GUST-WARN` oder `SHEAR-DEGRADED` auf. Das LLM machte Pattern-Matching ("Tag steht in der Hauptgefahren-Liste -> ist Hauptgefahr") und schrieb `caution_notes` / drueckte den Status, obwohl die Skill-Regeln das Gegenteil verlangten.

## Konzept: drei Phasen

```
PHASE 0 — STARTBARKEIT (deterministisch, im Code)
  Pro Stunde: liegt [WIND-OK] vor?
    JA  -> Stunde ist Start-Kandidat.
    NEIN ([WIND-WRONG]) -> Stunde wird IGNORIERT (weder positiv noch negativ).
  Output: startbare_stunden, nicht_startbare_stunden
  -> Datenblock-Block: STARTBARKEIT (Windrichtungs-Filter)

PHASE 1 — SICHERHEIT (LLM)
  Bewertet die Hazards. WIND-WRONG kommt im Skill-Text NICHT vor.
  Output: safety_status, safe_window, safety_subratings

PHASE 2 — FLIEGBARKEIT (LLM)
  Input: IMMUTABLE safe_window (Schnitt aus Phase 0 startbar UND Phase 1 sicher).
  Output: fly_status, flight_subratings, streckenflug
```

Phase 0 ist deterministisch und im Code seit langem implementiert (`engine/weather_context.py`: `wind_ok_hours`, `wind_wrong_hours`, `clean_hours`). Sie wurde im Datenblock nur **nicht klar genug ausgewiesen**.

## Was sich konkret geaendert hat (2026-05-02)

### Code (`engine/weather_context.py`)

1. **`major_tags_order` bereinigt** (Z. ~394 und ~1917): `[WIND-WRONG]` entfernt aus der Liste, die das Histogramm `Hauptgefahren am Tag:` aufbaut. WIND-WRONG steht dort nicht mehr neben echten Hazards.
2. **`tag_counts` zaehlt WIND-WRONG nicht mehr** (im Spot-Pfad, beide Stellen Z. ~635 / ~1690): die fruehere Zeile `tag_counts[wind_status] += 1` (mit `wind_status = "[WIND-WRONG]"` falls `not is_ok`) ist entfernt. Tag-Histogramm enthaelt nur noch echte Hazards.
3. **STARTBARKEIT-Block prominent** (frueher "WIND-ZUSAMMENFASSUNG", Z. ~1854): umbenannt zu `═══ STARTBARKEIT (Windrichtungs-Filter, verbindlich!) ═══` mit Disclaimer-Zeile direkt unter dem Header:

   > "WIND-WRONG ist KEIN Hazard und KEINE Warnung — es ist ein reiner Startbarkeits-Filter. Stunden mit `[WIND-WRONG]` werden fuer Sicherheits- und Fliegbarkeits-Bewertung IGNORIERT (zaehlen nicht ins safe_window, loesen aber auch keine caution_notes/no_go_reasons aus)."

Region-Pipeline (Z. ~2300+) hat keinen WIND-WRONG (Region hat keinen Sektor) — dort waren keine Aenderungen noetig.

### Skills (`skills/shared/`)

- **`_input_map.md`**: neuer Block `ZWEI TAG-KATEGORIEN` ganz oben, klare Filter/Hazard-Trennung mit expliziter Liste der Konsequenzen ("kommt NIEMALS in caution_notes", etc.). Andere WIND-WRONG-Erwaehnungen reduziert auf Verweis.
- **`_core_principles.md`** Regel 4: drastisch verkuerzt von 6 Zeilen auf 1 Satz + Verweis auf `_input_map.md`. Ueberschrift jetzt "WIND-WRONG ist Startbarkeits-Filter, kein Hazard".
- **`_status_derivation.md`**: WIND-WRONG-Detail entfernt, Verweis auf `_input_map.md`.
- **`_hazards_spot.md`** Block 2 BODENWIND: WIND-WRONG-Zeile aus der Tags-Spots-Liste entfernt (Filter gehoert nicht in Hazard-Liste). Verweis auf STARTBARKEITS-FILTER.
- **`_spot_context.md`**: Kurzform mit Verweis statt Volldefinition.
- **`system_chat.md`**: WIND-WRONG nicht mehr als Risikofaktor framen.

### Tests (`tests/test_decision_engine.py`)

Neue `TestWindWrongIsNotHazard`-Klasse mit drei Regressions-Locks:

1. `test_wind_wrong_not_in_major_tags_order` — kein `"[WIND-WRONG]",` als Listen-Element in `weather_context.py` (Trailing-Komma-Pattern, vermeidet false positive auf der `wind_status`-Definitionszeile).
2. `test_wind_wrong_not_incremented_into_tag_counts` — keine Patterns wie `tag_counts[wind_status]` mehr im Spot-Pfad.
3. `test_startbarkeit_block_present` — Header `═══ STARTBARKEIT` und Disclaimer `KEIN Hazard` muessen im Code-String enthalten sein.

Suite-Status: 98/98 gruen (95 alte + 3 neue).

## Warum nicht WIND-WRONG zu Flyability machen?

Klingt naheliegend ("ist ja kein Sicherheitsthema"), wuerde aber bedeuten: der Safety-Skill muesste auch nicht-startbare Stunden auf Hazards bewerten ("um 13:00 ist Gewitter, aber das ist nur sportlich relevant weil sowieso WIND-WRONG"). Das verkompliziert Phase 1 ohne ein Problem zu loesen. Die binaere Filter-Natur von WIND-WRONG passt nicht zu Flyability-Skalen.

## Warum nicht WIND-WRONG ganz aus dem Datenblock werfen?

Die Information ist **nuetzlich** (Pilot will wissen wann er starten kann). Sie muss nur **kategorisch getrennt** sein, nicht versteckt. Deshalb der eigene STARTBARKEIT-Block.

## Folgerichtige Skill-Architektur (Vision, nicht umgesetzt)

Die langfristige Vision ist eine prozessuale Skill-Hierarchie, die dem Bewertungs-Fluss folgt statt thematisch aufzuteilen:

```
skills/
├── _meta/
│   ├── numerik_regeln.md
│   └── glossar_index.md
├── phase1_safety/
│   ├── 1a_datenblock_lesen.md
│   ├── 1b_startbarkeits_filter.md      # WIND-OK / WIND-WRONG zentral
│   ├── 1c_hazards_und_trends.md
│   ├── 1d_spot_delta.md
│   └── 1e_status_und_subratings.md
├── phase2_flyability/
│   ├── 2a_input_immutable.md
│   ├── 2b_thermik_bewertung.md
│   ├── 2c_wolken_und_hoehe.md
│   ├── 2d_subratings_und_prosa.md
│   └── 2e_streckenflug.md
└── ...
```

Nicht jetzt umgesetzt, weil die heutige Struktur (19 Files in `skills/shared/`) mit dem WIND-WRONG-Fix den konkreten Schmerzpunkt loest. Der groessere Refactor lohnt sich nur, wenn weitere Phasen-Verschmutzungen auftauchen.

## Referenzen

- Code-Aenderungen: `engine/weather_context.py` (Spot-Pipeline)
- Skill-Aenderungen: `skills/shared/_input_map.md` (zentrale Definition), andere Skills mit Verweisen
- Tests: `tests/test_decision_engine.py::TestWindWrongIsNotHazard`
- Konzept-Hauptdokument: `docs/RATING_CONCEPT.md`
