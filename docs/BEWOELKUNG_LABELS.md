# Bewölkungs-Label-System

## Übersicht

Bewölkung beeinflusst die Thermik-Qualität und wird im Label-System in 3 Stufen
abgebildet. Grundlage: FAA Soaring Weather (AC 00-6A), Matuszko (2012).

Detaillierte Forschungsgrundlage: `meteo_research/cloud_cover_thermal_impact.md`

---

## Grundprinzip: tief und mittel wirken UNTERSCHIEDLICH

| Schicht | Höhe | Was sitzt da? | Wirkung |
|---------|------|---------------|---------|
| **Tief** | 0–3 km | Cu humilis/mediocris (Thermik-Cu) | **Bimodal**: 12-50% = Booster (Marker), ≥80% = Killer |
| **Mittel** | 3–8 km | Altostratus, Altocumulus | **Monoton dämpfend**: kein Sweet Spot, jedes % reduziert Einstrahlung |
| **Hoch** | >8 km | Cirrus | Ignoriert (Transmissivität 70-85%) |

**Konsequenz**: Wir verwenden NICHT `max(tief, mittel)`, sondern getrennte Schwellen mit
expliziten UND/ODER-Operatoren.

## Label-Definitionen

### GUTE_EINSTRAHLUNG (Booster, grün)

**Anzeige**: "Gute Sonne" mit Icon ☀

**Trigger** (LLM-gesteuert, in Skills definiert):
- **tief ≤ 50% mit Cu-Charakter UND mittel ≤ 30%** (SCT-Cu unten + freie Sicht oben)
- ODER **tief < 30% UND mittel < 30%** (klarer Himmel)
- Auch blauer Himmel (0%) ist ein Booster

**Meteorologische Begründung**:
- Optimale Cu-Bedeckung 12-50% (1-4 Oktas, SCT) liefert stärkste Thermik
- Cu markiert Thermik-Einstiege visuell
- Latentwärme-Boost durch Kondensation
- Matuszko-Effekt: Teils bewölkter Himmel liefert MEHR Solarenergie als wolkenlos
- Mittel ≤ 30%, weil Altostratus-Decke ab ~30% spürbar dämpft

### TOP-Tag (klassiker, Rating 6 = cu_clean_top)

Strenger als Booster. Voraussetzung für Rating 6:
- **tief 12-50% Cu** (echte Schönwetter-Cu als Marker, nicht nur klar)
- **mittel < 30%** (Altostratus würde die starke Thermik nicht zulassen)
- **hoch** beliebig (Cirrus egal)

Backend setzt `cloud_structure = "cu_clean_top"` exakt mit dieser Bedingung
(`engine/weather_context.py:96`).

### VIEL_BEWOELKUNG (Reducer, bronze)

**Anzeige**: "Viel Bewölkung" mit Icon ☁

**Trigger** (LLM-gesteuert, in Skills definiert):
Während >50% der Thermikstunden gilt:
- **tief ≥ 80%** (Cu-Overcast/Stratus blockiert von unten) ODER
- **mittel ≥ 70%** (Altostratus-Decke dämpft von oben)
- Starke Überentwicklung (OD) mit Abschirmung gehört auch hierher

**Meteorologische Begründung**:
- Ab tief 80% wird Sonne durch Cu-Overcast weitgehend blockiert
- Altostratus dämpft früher als Cu-Overcast: 70% mid = ~40-50% Einstrahlungsverlust
- Thermik stirbt (FAA: "Solar heating is cut off and thermals weaken or die")
- Nur noch Abgleiter- oder kurzer Thermik-Tag

### Neutralzone

- tief 50-80% ODER mittel 30-70%
- Dämpfung beginnt (FAA 5/10-Regel ab 50% tief)
- Thermik noch vorhanden aber abnehmend
- Weder Booster noch Reducer — gemischte Bedingungen

### OVERCAST (No-Go, rot) — unverändert

**Trigger** (deterministisch in chat_engine.py):
- cloud_cover ≥75% UND cloud_base < elevation + 500m
- Sicherheits-Tag: Cloud Entry Gefahr, Sicht eingeschränkt
- Hat nichts mit Thermik-Qualität zu tun, rein Safety

---

## Exklusionsregeln

In `label-catalog.js` definierte Exklusionsgruppen:
- `VIEL_BEWOELKUNG` ↔ `XC_BEDINGUNGEN` (können nicht gleichzeitig erscheinen)
- `VIEL_BEWOELKUNG` ↔ `GUTE_EINSTRAHLUNG` (widersprüchlich)

Bei Konflikt gewinnt immer der Reducer (sicherheitsrelevanter).

---

## Schwellen-Übersicht

| Schwelle | Wert | Typ | Wo definiert |
|----------|------|-----|-------------|
| Booster-Label (Top) | tief ≤ 50% Cu UND mittel ≤ 30% | LLM-Label | Skills (flyability, system_chat) |
| Booster-Label (Blau) | tief < 30% UND mittel < 30% | LLM-Label | Skills (flyability, system_chat) |
| Klassiker / cu_clean_top | tief 12-50% Cu UND mittel < 30% | Deterministisch | `engine/weather_context.py:96` |
| Produktive Stunde (tief) | ≤80% cloud_cover_low | Deterministisch | config.py `PRODUCTIVE_LOW_CLOUD_MAX = 80` |
| Produktive Stunde (mittel) | ≤90% cloud_cover_mid | Deterministisch | config.py `PRODUCTIVE_MID_CLOUD_MAX = 90` |
| Reducer-Label | tief ≥ 80% ODER mittel ≥ 70% | LLM-Label | Skills (flyability, system_chat) |
| CLOUDS-Tag 'good' | tief ≤ 50% UND mittel ≤ 30% | LLM-Label | Skills (templates) |
| OVERCAST-DANGER | ≥75% total + Basis tief | Deterministisch | chat_engine.py (3 Stellen) |

**Warum tief und mittel getrennt behandeln?** Tief = Cumulus (humilis/mediocris) sind **Thermik-Marker** — bimodal: 12-50% optimal, ≥80% killt. Mittel = Altostratus/Altocumulus sind **Strahlungs-Dämpfer** — monoton: jedes % Bedeckung reduziert Einstrahlung, kein Sweet Spot. Eine `max(tief, mittel)`-Schwelle würde beide Mechanismen symmetrisch behandeln, was physikalisch falsch ist:
- Tag mit `tief = 25% Cu` + `mittel = 60% Altostratus` → unter `max = 60%` Neutralzone, aber real „mässige Cu-Thermik mit gedämpfter Einstrahlung"
- Tag mit `tief = 0%` + `mittel = 85% Altostratus` → unter `max = 85%` Reducer, aber Prosa würde fälschlich „Wolken tief" suggerieren

**Wichtig**: Die Schwellen dienen verschiedenen Zwecken:
- **Labels** (Booster/Reducer) = Qualitäts-Wahrnehmung für den Piloten — getrennte tief/mittel-Schwellen
- **Produktive Stunde** = Technische Berechnung für Flyability-Tier — getrennt tief<80% UND mittel<90%
- **OVERCAST-DANGER** = Sicherheit (Wolkenbasis-Proximity)

---

## Cirrus-Ausnahme

Hohe Bewölkung (Cirrus, >6000m) wird **ignoriert**:
- Transmissivität 70-85% — kaum Einfluss auf Thermik
- Nur tief+mittel <30% → kein Label (weder Booster noch Reducer)
- Cirrus-Overcast mit gutem THERMIK-PROXY → normal bewerten, KEIN gray!

---

## Betroffene Dateien

### Frontend
- `static/js/label-catalog.js` — Label-Definitionen, Exklusionsgruppen

### Backend
- `config.py` — `PRODUCTIVE_LOW_CLOUD_MAX = 80`, `PRODUCTIVE_MID_CLOUD_MAX = 90`
- `chat_engine.py` — `_LABEL_KEYS_REDUCER`, `_LABEL_KEYS_BOOSTER`, OVERCAST-DANGER Logik

### Skills (LLM-Prompts)
- `skills/spot_combined_analysis.md` — Bewölkungs-Labels Guidance + primary_booster/reducer Keys
- `skills/region_combined_analysis.md` — Bewölkungs-Labels Guidance + primary_booster/reducer Keys
- `skills/flyability.md` — Bewölkungs-Labels + Produktive-Stunden-Schwelle
- `skills/region_flyability.md` — Bewölkungs-Labels + Produktive-Stunden-Schwelle
- `skills/system_chat.md` — Tier-Tabelle Bewölkung

### Dokumentation
- `meteo_research/cloud_cover_thermal_impact.md` — Wissenschaftliche Grundlage
- `docs/BEWOELKUNG_LABELS.md` — Diese Datei

---

## Änderungshistorie

### Apr 2026 — Bewölkungs-Labels eingeführt
- **Neu**: `GUTE_EINSTRAHLUNG` Booster-Label (≤50% Cu = optimal)
- **Neu**: `VIEL_BEWOELKUNG` Reducer-Label (≥80% = Sonne blockiert)
- **Rename**: `HOHE_BEWOELKUNG` → `VIEL_BEWOELKUNG` (alter Name suggerierte "hohe Wolken" statt "hoher Bedeckungsgrad")
- **Schwelle**: `PRODUCTIVE_CLOUD_MAX` von 70% auf 80% angehoben (Forschung: Thermik bis ~80% vorhanden)
- **Forschungsbasis**: FAA AC 00-6A, Matuszko (2012), USHPA, Pagen

### Apr 2026 — Low/Mid-Trennung für Produktiv-Stunde
- **Aufgeteilt**: `PRODUCTIVE_CLOUD_MAX` → `PRODUCTIVE_LOW_CLOUD_MAX = 80` + `PRODUCTIVE_MID_CLOUD_MAX = 90`
- **Grund**: `max(low, mid) ≤ 80` markierte Tage mit blauem Himmel-unten aber Altostratus-Decke fälschlich als "nicht produktiv", obwohl das Thermik-Modell (cloud-attenuierte SW-Radiation) noch solides Steigen ausgab.
- **Research-Basis**: Cloud Impact Sektion 6 differenziert tief (direkter Boden-Shade) vs. mittel (indirekt über Einstrahlung, "praktisch tot" laut FAA erst >87%).
- **Effekt**: Altostratus-Tage mit 87-90% mid kippen nicht mehr automatisch auf Abgleiter/gray.

### Mai 2026 — Label-Schwellen physikalisch sauber getrennt
- **Vorher**: Booster/Reducer-Labels und CLOUDS-Tag nutzten `max(tief, mittel)` bzw. `tief + mittel`
- **Problem**: Verschmierte zwei physikalisch unterschiedliche Mechanismen (Cu-Marker vs. Altostratus-Dämpfer). Inkonsistenz zwischen verschiedenen Skill-Stellen (drei verschiedene Operatoren).
- **Neu**:
  - Booster: `tief ≤ 50% Cu UND mittel ≤ 30%` (oder beides klar < 30%)
  - Reducer: `tief ≥ 80% ODER mittel ≥ 70%`
  - CLOUDS-Tag 'good': `tief ≤ 50% UND mittel ≤ 30%` (= Booster-konsistent)
  - Top/Klassiker (Rating 6): cu_clean_top = `tief 12-50% Cu UND mittel < 30%` (im Code so seit v1.6)
- **Effekt**: Tage mit Cu unten und Altostratus-Decke oben werden korrekt klassifiziert. Rating 6 reserviert für echt klare Tage mit Cu.
- **Geänderte Dateien**: `skills/shared/04_flyability/03_prose_style.md`, `00_template_spot.md`, `00_template_region.md`, `04_flight_subratings_spot.md`, `04_flight_subratings_region.md`, `skills/system_chat.md`, `docs/BEWOELKUNG_LABELS.md`.
