# Bewölkungs-Label-System

## Übersicht

Bewölkung beeinflusst die Thermik-Qualität und wird im Label-System in 3 Stufen
abgebildet. Grundlage: FAA Soaring Weather (AC 00-6A), Matuszko (2012).

Detaillierte Forschungsgrundlage: `meteo_research/cloud_cover_thermal_impact.md`

---

## Label-Definitionen

### GUTE_EINSTRAHLUNG (Booster, grün)

**Anzeige**: "Gute Sonne" mit Icon ☀

**Trigger** (LLM-gesteuert, in Skills definiert):
- max(tief, mittel) ≤50% mit Cu-Charakter (Scattered Cumulus, 12-50% = optimal)
- ODER klarer Himmel (<30%)
- Auch blauer Himmel (0%) ist ein Booster

**Meteorologische Begründung**:
- Optimale Cu-Bedeckung 12-50% (1-4 Oktas, SCT) liefert stärkste Thermik
- Cu markiert Thermik-Einstiege visuell
- Latentwärme-Boost durch Kondensation
- Matuszko-Effekt: Teils bewölkter Himmel liefert MEHR Solarenergie als wolkenlos

### VIEL_BEWOELKUNG (Reducer, bronze)

**Anzeige**: "Viel Bewölkung" mit Icon ☁

**Trigger** (LLM-gesteuert, in Skills definiert):
- max(tief, mittel) ≥80% während >50% der Thermikstunden
- Starke Überentwicklung (OD) mit Abschirmung

**Meteorologische Begründung**:
- Ab 80% wird Sonne weitgehend blockiert
- Thermik stirbt (FAA: "Solar heating is cut off and thermals weaken or die")
- Nur noch Abgleiter-Qualität

### Neutralzone (50-80%, kein Label)

- Dämpfung beginnt (FAA 5/10-Regel ab 50%)
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
| Booster-Label | ≤50% max(tief,mittel) | LLM-Label | Skills (spot/region_combined, flyability) |
| Produktive Stunde | <80% max(tief,mittel) | Deterministisch | config.py `PRODUCTIVE_CLOUD_MAX = 80` |
| Reducer-Label | ≥80% max(tief,mittel) | LLM-Label | Skills (spot/region_combined, flyability) |
| OVERCAST-DANGER | ≥75% total + Basis tief | Deterministisch | chat_engine.py (3 Stellen) |

**Wichtig**: Die Schwellen dienen verschiedenen Zwecken:
- **Labels** (Booster/Reducer) = Qualitäts-Wahrnehmung für den Piloten
- **Produktive Stunde** = Technische Berechnung für Flyability-Tier
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
- `config.py` — `PRODUCTIVE_CLOUD_MAX = 80`
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
