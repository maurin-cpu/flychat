# Flyability-Tier-Logik: gray / green / violet

## Was ist das Flyability-Tier?

Pro Spot und Tag ordnet Gleitcast ein **Tier** zu, das die thermische Flugqualität in 3 Stufen klassifiziert (orthogonal zur Sicherheit aus Phase 1):

| Tier | Bedeutung | Frontend-Farbe |
|------|-----------|----------------|
| `gray` | Abgleiter / kaum nutzbare Thermik | Bronze (#B08D57) |
| `green` | Solider Thermiktag, lokale Flüge möglich | Grün |
| `violet` | Top-XC-Bedingungen, legendärer Tag | Violett |

Zusätzlich `no_data` (echtes Grau #9ca3af) wenn keine Daten verfügbar.

Die LLM (Claude) trifft die initiale Bewertung anhand des Wetter-Kontexts. Anschliessend prüft eine **deterministische Override-Schicht** das LLM-Urteil und korrigiert systematische Fehlbewertungen.

---

## Violett-Kriterien (XC-Tag)

Violett ist **kein** Auto-Override — die LLM entscheidet final. Der TAGESPROFIL-Block zeigt jedoch einen expliziten `→ VIOLETT-Kandidat: …` Hint, wenn **alle** folgenden Schwellen erfüllt sind:

| Feld | Schwelle | Konstante in `config.py` |
|------|----------|--------------------------|
| Peak-Thermik (Proxy) | ≥ 2.5 m/s | `VIOLET_PEAK_MIN` |
| Produktive Stunden | ≥ 5 | `VIOLET_HOURS_MIN` |
| ROUGH-UNUSABLE-Anteil | < 30 % | `VIOLET_ROUGH_MAX` |
| Gesamt-UNUSABLE-Anteil | < 30 % | `VIOLET_UNUSABLE_MAX` |
| Ø tiefe Wolken (über Thermikstunden) | ≤ 50 % | `VIOLET_CLOUD_LOW_MAX` |
| Ø mittlere Wolken (über Thermikstunden) | ≤ 50 % | `VIOLET_CLOUD_MID_MAX` |

**Cloud-Schwellen basieren auf `meteo_research/cloud_cover_thermal_impact.md` Sektion 1+6:**
- 12–50 % Cu = OPTIMAL (SCT, Matuszko-Effekt, Latentwärme-Boost).
- 50–60 % Cu = Dämpfung beginnt (FAA).
- Altostratus ab ~50 % reduziert Einstrahlung signifikant.

Violett erfordert damit die optimale Cu-Zone (oder Blau-Thermik 0 %), nicht den Dämpfungsbereich. 60–80 % Cu kann ein guter Thermiktag sein → bleibt green.

**Mittelwerte werden NUR über Thermikstunden** (climb ≥ 0.3 m/s) gebildet, damit Morgenstunden mit Hochnebel den Schnitt nicht verfälschen (analog zur `productive_thermal_h`-Logik).

---

## Die zentrale Metrik: `productive_thermal_h`

Eine Stunde zählt als **produktive Thermik-Stunde**, wenn alle drei Bedingungen erfüllt sind:

| Bedingung | Schwelle | Konstante in `config.py` |
|-----------|----------|--------------------------|
| Climb-Rate | ≥ 0.7 m/s | `PRODUCTIVE_CLIMB_MIN` |
| Tiefe Wolken (<3 km) | ≤ 80 % | `PRODUCTIVE_LOW_CLOUD_MAX` |
| Mittlere Wolken (3–6 km) | ≤ 90 % | `PRODUCTIVE_MID_CLOUD_MAX` |
| Kein THERMAL-ROUGH-UNUSABLE | — | (SHEAR/TORN/FRAGMENTED zählen MIT) |

**Wolken-Differenzierung** (Basis: `meteo_research/cloud_cover_thermal_impact.md` Sektion 6): Tiefe Wolken werfen direkt Schatten auf die Quellfläche und werden bei ≥80% harter Blocker (FAA-Soaring-Regel). Mittlere Wolken (Altostratus) sitzen über der Thermik-Arbeitshöhe und dämpfen nur indirekt über reduzierte Einstrahlung — "praktisch tot" laut FAA erst >87%, daher Schwelle 90%. Diese Trennung verhindert, dass hohe Altostratus-Decken bei blauem Himmel-unten einen soliden Thermiktag fälschlich als "nicht produktiv" markieren.

**Warum diese Definition?**
Frühere Logik nutzte zwei Metriken (`avg_low_mid_cloud` Mittelwert + `flyable_thermal_h` Counter mit ≥0.5 m/s). Problem: Morgenstunden mit dichten Wolken UND nur 0.3-1.0 m/s Climb verzerrten den Wolken-Mittelwert nach oben — obwohl in diesen Stunden eh kein nennenswertes Steigen herrschte. Beispiel Voralpen 16.04.2026: 4-5h klare Mittagsthermik wurde fälschlich als "Abgleiter" eingestuft, weil der Schnitt durch Morgenwolken auf 70-80 % gezogen wurde.

Die neue Single-Metric-Definition ist physikalisch sauber: **Bewölkung wird nur dort gezählt, wo überhaupt eine produktive Stunde möglich wäre.**

---

## Override-Logik

Nach der LLM-Bewertung greifen drei Tier-Korrekturen — implementiert in `chat_engine.py` an drei Stellen:

1. `_analyze_single_spot_combined` (~Z. 3140) — Spot Combined Analysis
2. `_analyze_single_region_combined` (~Z. 3380) — Region Combined Analysis
3. `_run_batch_analysis` (~Z. 4322) — Batch Analysis (Refresh)

### Downgrade: green/violet → gray

Wenn die LLM `green` oder `violet` gewählt hat, wird zu `gray` degradiert wenn **eine** der folgenden Bedingungen erfüllt ist:

| Bedingung | Begründung |
|-----------|------------|
| `thermal_hours_total == 0` oder `peak < 0.3` m/s | Keine Thermik überhaupt |
| `unusable_pct > 50 %` | Mehr als die Hälfte der Thermikstunden sind durch Wind unbrauchbar |
| `productive_thermal_h < 2` (`PRODUCTIVE_HOURS_DOWNGRADE`) | Zu wenig Stunden, in denen Climb + Wolken + Wind zusammenpassen |

### Upgrade: gray → green

Wenn die LLM `gray` gewählt hat, wird zu `green` aufgewertet wenn **beide** Bedingungen erfüllt sind:

| Bedingung | Wert |
|-----------|------|
| `productive_thermal_h >= 4` (`PRODUCTIVE_HOURS_FOR_GREEN`) | Mindestens 4 produktive Stunden |
| `unusable_pct < 50 %` | Mehrheitlich saubere Thermik |

Beim Upgrade werden zusätzlich folgende Felder konsistent gesetzt:
- `peak_climb_rate` = `peak` (gerundet)
- `flight_type` = `"Thermikflug"` bei peak ≥ 1.5 m/s, sonst `"Soaring+Thermik"`
- `flight_duration_estimate` entsprechend
- `xc_potential` = `"moderate"` ab 5 produktiven Stunden
- `recommendation` als System-Korrektur-Text

Das ist nötig, weil die LLM unter `gray` typischerweise pessimistische Textfelder schreibt (z.B. `peak_climb_rate` auf 1.0 gecappt, `recommendation` als "Abgleiter").

---

## LLM-Hint im Wetter-Kontext

Zur Transparenz für die LLM enthält der TAGESPROFIL-Block einen expliziten Counter:

```
→ PRODUKTIVE-THERMIK: 4h (Climb ≥0.7 m/s, tief ≤80%, mittel ≤90%, kein ROUGH-UNUSABLE). Min für green-Tag: 4h.
```

Der Hint erscheint **nur** wenn `thermal_hours_total > 0`. Die Skill-Prompts (`skills/flyability.md`, `skills/region_flyability.md`, `skills/spot_combined_analysis.md`, `skills/region_combined_analysis.md`) referenzieren diesen Counter im Selbst-Check:

- N ≥ 4 → green/violet möglich
- N < 2 → fly_status MUSS gray sein
- 2 ≤ N < 4 → Grenzfall, abhängig von Peak und Wind

Die früheren Hints `→ CLOUD-FLOOR (System-erzwungen)` und `→ CLOUD-INFO` sind ersatzlos entfallen — die Wolken-Information ist jetzt im `productive_thermal_h`-Counter integriert.

---

## Cache-Struktur

Die Override-Schicht greift auf einen Cache zu, der pro Spot/Region und Tag während des Context-Builds gefüllt wird:

```python
self._ctx_tq_cache[f"{name}|{date_str}"] = {
    "thermal_hours_total": int,        # Stunden mit climb >= 0.3 m/s
    "tq_danger_h": int,                # Stunden mit UNUSABLE-Tag
    "peak_climb_proxy": float,         # Peak Climb-Rate des Tages
    "productive_thermal_h": int,       # Stunden mit climb >= 0.7 + Wolken <= 70 + kein UNUSABLE
}
```

Cache-Migration ist nicht nötig — die Override-Logik nutzt `tq.get(..., 0)` Defaults und überschreibt alte Cache-Einträge bei der nächsten Analyse.

---

## Konfiguration

Alle Schwellen in `config.py`:

```python
PRODUCTIVE_CLIMB_MIN = 0.7       # m/s — Mindest-Climb für "produktive" Stunde
PRODUCTIVE_LOW_CLOUD_MAX = 80    # % — Max cloud_cover_low (direkter Boden-Shade)
PRODUCTIVE_MID_CLOUD_MAX = 90    # % — Max cloud_cover_mid (indirekte Dämpfung)
PRODUCTIVE_HOURS_FOR_GREEN = 4   # Mindest-Stunden für gray->green Upgrade
PRODUCTIVE_HOURS_DOWNGRADE = 2   # Untere Schwelle: green/violet -> gray

# Violett-Kandidat-Schwellen (LLM-Hint, kein Override)
VIOLET_PEAK_MIN = 2.5            # m/s
VIOLET_HOURS_MIN = 5             # produktive Stunden
VIOLET_ROUGH_MAX = 30            # % — Max ROUGH-UNUSABLE-Anteil
VIOLET_UNUSABLE_MAX = 30         # % — Max Gesamt-UNUSABLE-Anteil
VIOLET_CLOUD_LOW_MAX = 50        # % — Ø tief über Thermikstunden
VIOLET_CLOUD_MID_MAX = 50        # % — Ø mittel über Thermikstunden
```

---

## Trade-offs

**Vorteile:**
- Eine Metrik statt zwei → einfacher debuggbar
- Physikalisch sauber: Wolken zählen nur in thermisch nutzbaren Stunden
- Konsistente 70 %-Schwelle in Code, Skills und Doku
- Behebt den Voralpen-Fall (16.04.2026) ohne neue Magic Numbers

**Nachteile:**
- Bewusstes Aufgeben des "harten" Cloud-Floor-Downgrade. Wenn die LLM `green` entscheidet aber `productive_thermal_h` nur 2-3 ist, bleibt es jetzt bei `green` (vorher hätte `avg_low_mid > 80 %` runtergedrückt). Mit dem strengeren Climb-Schwellwert (0.7 statt 0.5 m/s) ist das aber konservativ.
- Skills mussten umlernen — eine kurze Inkonsistenz zwischen LLM-Antworten und neuer Logik möglich (1-2 Refreshes bis Cache neu aufgebaut).

**Nicht im Scope:**
Eine "Soaring-Exception" (gray-Tag aber Wind 15-30 km/h passend für reines Hangsoaring ohne Thermik) ist eine separate spätere Erweiterung.
