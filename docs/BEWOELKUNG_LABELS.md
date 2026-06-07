# Bewölkungs-Label-System

## Übersicht

Bewölkung wird im Label-System in 3 Stufen abgebildet als **Sky-Beschreibung** —
NICHT als Productivity-Gate (Mai 2026). Grundlage: FAA Soaring Weather (AC 00-6A),
Matuszko (2012).

**Wichtig (Mai 2026):** Die Thermik-Engine berechnet `climb_rate` bereits aus der
Sonneneinstrahlung (`direct_radiation` + `diffuse_radiation` → H → climb). Die
Wolken-Dämpfung steckt also physikalisch in der `climb_rate` drin. Cloud-Cover-%
sind **kein Productivity-Gate mehr** — eine zusätzliche Schwelle wäre Doppel-
bestrafung der eigenen Engine. Wolken-Labels beschreiben den **Himmel** (Pilot
will wissen ob's bedeckt ist), beeinflussen aber das Rating nicht direkt. Nur
`cu_clean_top` (12-50% Cu unten + klar oben) bleibt als Rating-Booster für
Rating 6 (Cu-Marker + Latentwärme = echter Mehrwert über die Engine).

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

### OVERCAST (No-Go, rot) — überarbeitet Juni 2026

**Trigger** (deterministisch in `engine/weather_context.py`, 3 Stellen):
- **Dichte, geschlossene Wolkendecke AUF oder UNTER Startplatzhöhe:**
  `cloud_base ≤ elevation + 100m` UND geschlossene Decke
  (`cloud_cover_low ≥ 80%`, bei hochalpinem Platz `elevation ≥ 3000m` zusätzlich `cloud_cover_mid ≥ 80%`).
- Deckt zwei Gefahren ab: Start direkt in die Wolke **und** geschlossene Decke
  unter dem Piloten, durch die er zum Landeplatz absteigen müsste.
- Wolken **oberhalb** des Startplatzes sind KEINE Gefahr (nur Thermik-Reducer) → kein Stop.
- Schwellen in `config.py`: `OVERCAST_DANGER_BASE_BUFFER_M=100`, `OVERCAST_DANGER_COVER_PCT=80`, `OVERCAST_MID_BAND_MIN_M=3000`.
- Open-Meteo-Schichten: low 0–3km, mid 3–8km, high >8km (MSL).
- Hat nichts mit Thermik-Qualität zu tun, rein Safety.

**Frühere Regel (bis Mai 2026):** `cloud_cover ≥75% UND cloud_base < elevation + 500m` —
flaggte Luftraum bis 500m ÜBER dem Platz fälschlich als not_safe (Confound, siehe
Scheidegg-2026-06-05-Analyse) und zählte hohe Schichten (high/cirrus) über `cloud_cover` mit.

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
| Booster-Label (Top) | tief ≤ 50% Cu UND mittel ≤ 30% | LLM-Label (Sky-Info) | Skills (flyability, system_chat) |
| Booster-Label (Blau) | tief < 30% UND mittel < 30% | LLM-Label (Sky-Info) | Skills (flyability, system_chat) |
| Klassiker / cu_clean_top | tief 12-50% Cu UND mittel < 30% | Deterministisch (Rating-6-Booster) | `engine/weather_context.py:96` |
| ~~Produktive Stunde (tief)~~ | ~~≤80% cloud_cover_low~~ | **DEPRECATED Mai 2026** | `PRODUCTIVE_LOW_CLOUD_MAX` nicht mehr im Productivity-Pfad |
| ~~Produktive Stunde (mittel)~~ | ~~≤90% cloud_cover_mid~~ | **DEPRECATED Mai 2026** | `PRODUCTIVE_MID_CLOUD_MAX` nicht mehr im Productivity-Pfad |
| Reducer-Label | tief ≥ 80% ODER mittel ≥ 70% | LLM-Label (Sky-Info, kein Rating-Cap) | Skills (flyability, system_chat) |
| CLOUDS-Tag 'good' | tief ≤ 50% UND mittel ≤ 30% | LLM-Label (Sky-Info) | Skills (templates) |
| OVERCAST-DANGER | Basis ≤ elev+100m UND tief ≥80% (hochalpin auch mittel ≥80%) | Deterministisch (Safety, nicht Thermik) | `engine/weather_context.py` (3 Stellen), `config.OVERCAST_DANGER_*` |

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

### Mai 2026 — Strahlung wird Wahrheit, Cloud-% nur noch Sky-Info

- **Grosse Umstellung:** Cloud-Cover-% sind **kein Productivity-Gate mehr**.
  Die `productive_thermal_h`-Logik in `engine/weather_context.py` wurde von
  4 Bedingungen (climb + low + mid + band) auf 3 (climb + band + kein UNUSABLE)
  reduziert. Begründung: `climb_rate` wird in `thermik_calculator.py` bereits
  aus `direct_radiation` + `diffuse_radiation` berechnet — Wolken-Dämpfung
  steckt physikalisch in climb drin. Eine zusätzliche Cloud-Schwelle war
  Doppelbestrafung (siehe Code-Kommentar `thermik_calculator.py:1367-1369`).
- **Aufgedeckter Bug:** ICON-D2 `cloud_cover_mid` ist flächige Bedeckung, nicht
  optische Dicke. Bei dünnem Altostratus zeigt mid=100% trotzdem swr=800-980 W/m²
  am Boden (77% der "hoch bewölkten" Stunden im Cache 16.05.2026 zeigten diese
  Diskrepanz). Strahlung ist der verlässlichere Proxy.
- **Skill-Anpassungen:** Rating-Caps wegen Bewölkung ("tief ≥ 80% → max 1-2",
  "mittel ≥ 70% → max 2-3") wurden aus `system_chat.md` und allen
  `04_flight_subratings_*.md` entfernt. `cu_clean_top` bleibt einziger
  cloud-basierter Rating-Booster (für Rating 6, Latentwärme-Mehrwert).
- **Hour-Lines erweitert:** `Strahlung X W/m² (direkt Y)` ist jetzt in jeder
  Hour-Line sichtbar (Spot + Region). LLM hat damit den Strahlungswert direkt
  vor sich. **W/m²-Rohzahlen dürfen NIEMALS an den User durchgereicht werden**
  — in Fliegersprache übersetzen (`skills/shared/01_global/01_core_principles.md`
  Punkt 2d).
- **Region-strict-Bug nebenbei gefixt:** `productive_h_strict` wurde im
  Region-Loop nie inkrementiert → alle Regionen hatten permanent
  `working_height_agl_m=0`. Jetzt analog zum Spot-Loop.
- **Mess-Checkpoint** (145 Region-Tage): +1.67h durchschnittlich, 21 Tier-Kipper
  (alle in Richtung besser), 0 Demotion. Self-Correction: bei echt schlechter
  Sonne sinkt climb → Stunde fällt automatisch durch `PRODUCTIVE_CLIMB_MIN`.
- **Geänderte Dateien:** `engine/weather_context.py` (4 Stellen),
  `skills/shared/04_flyability/{03_prose_style,00_template_spot,00_template_region,04_flight_subratings_spot,04_flight_subratings_region}.md`,
  `skills/system_chat.md`, `skills/shared/01_global/01_core_principles.md`,
  `docs/FLYABILITY_TIER_LOGIK.md`, `docs/BEWOELKUNG_LABELS.md`.

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
