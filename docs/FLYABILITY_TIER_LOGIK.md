# Flyability-Tier-Logik: gray / green / violet

## Was ist das Flyability-Tier?

Pro Spot und Tag ordnet Wingcast ein **Tier** zu, das die thermische Flugqualität in 3 Stufen klassifiziert (orthogonal zur Sicherheit aus Phase 1):

| Tier | Bedeutung | Frontend-Farbe |
|------|-----------|----------------|
| `gray` | Abgleiter / kaum nutzbare Thermik | Sky-Blue (#0ea5e9) — Royal Premium, früher Bronze #B08D57 |
| `green` | Solider Thermiktag, lokale Flüge möglich | Grün |
| `violet` | Top-XC-Bedingungen, XC-Tag | Violett (#a78bfa) |

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

Eine Stunde zählt als **produktive Thermik-Stunde**, wenn alle drei Bedingungen erfüllt sind (Mai 2026):

| Bedingung | Schwelle | Konstante in `config.py` |
|-----------|----------|--------------------------|
| Climb-Rate | ≥ 0.7 m/s | `PRODUCTIVE_CLIMB_MIN` |
| Höhenband (Thermik-Top über Startplatz/Region-Ref) | ≥ `min_band_depth(climb, terrain)` | berechnet in `thermik_calculator.py` |
| Kein THERMAL-ROUGH-UNUSABLE / -WIND-UNUSABLE / -TORN-UNUSABLE | — | (SHEAR/FRAGMENTED zählen MIT; **TORN gated seit 2026-06-04**, anker-korrigiert — siehe `TQ_TORN_FLYABILITY.md`) |

**Bewölkungs-Schwellen entfallen seit Mai 2026** (war Doppelbestrafung der eigenen Berechnung):

Die `climb_rate` wird in `thermik_calculator.py` (Funktion `_calculate_climb_rate_for_hour`) bereits aus `direct_radiation` + `diffuse_radiation` über den sensiblen Wärmefluss H abgeleitet. Wolken-Dämpfung steckt also **physikalisch in climb_rate drin** (siehe Code-Kommentar `thermik_calculator.py:1367-1369`: "W*-Deardorff beinhaltet die Bewölkungsdämpfung bereits ... wir dürfen hier nicht nochmals künstlich mit einem sun_factor multiplizieren").

Eine zusätzliche Cloud-Cover-Schwelle wäre Doppelbestrafung — und ICON-D2 `cloud_cover_mid` ist flächige Bedeckung, **nicht** optische Dicke. Bei dünnem Altostratus zeigt mid=100% trotzdem swr=800 W/m² (Beobachtung aus Cache 16.05.2026 für Wallis/Goms, Berner Oberland u.a.). Die Strahlung ist der verlässlichere Proxy und ist in climb bereits eingepreist.

**Wolken-% bleiben weiterhin relevant für:**
- LLM-Labels (`VIEL_BEWOELKUNG` / `GUTE_EINSTRAHLUNG`) als Sky-Beschreibung
- `cu_clean_top` als Cu-Marker-Booster (Rating 6) — Latentwärme-Boost ist echter Mehrwert über die Engine
- `OVERCAST-DANGER` Cloud-Entry-Sicherheit
- Aber **NICHT** als Productivity-Gate.

Die Konstanten `PRODUCTIVE_LOW_CLOUD_MAX = 80` und `PRODUCTIVE_MID_CLOUD_MAX = 90` in `config.py` sind nicht mehr im Productivity-Pfad verwendet (deprecated, können später entfernt werden).

**Mess-Checkpoint Mai 2026** (über 145 Region-Tage): 57% der Tage bekommen mehr produktive Stunden (Durchschnitt +1.67h, max +7h). 21 Region-Tage ändern den Tier — alle in Richtung "besser". Keine Demotion irgendwo (Self-Correction: wenn die Sonne wirklich weg ist, sinkt climb automatisch → Stunde fällt durch climb-Schwelle).

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

Zur Transparenz für die LLM enthält der TAGESPROFIL-Block einen expliziten Counter (seit Mai 2026):

```
→ PRODUKTIVE-THERMIK: 4h (Climb ≥0.7 m/s, ausreichendes Höhenband, kein ROUGH-UNUSABLE, kein WIND-UNUSABLE, kein TORN-UNUSABLE). Min für green-Tag: 4h. HINWEIS: Bewölkungs-% sind KEIN Productivity-Gate mehr (Mai 2026) — die Sonnen-Dämpfung steckt bereits in climb_rate über die strahlungsbasierte H-Berechnung.
```

Der Hint erscheint **nur** wenn `thermal_hours_total > 0`. Die Skill-Prompts referenzieren diesen Counter im Selbst-Check:

- N ≥ 4 → green/violet möglich
- N < 2 → fly_status MUSS gray sein
- 2 ≤ N < 4 → Grenzfall, abhängig von Peak und Wind

Zusätzlich enthalten die Hour-Lines seit Mai 2026 die Strahlungs-Werte direkt:

```
... Bewoelkung 100% (tief 0%, mittel 100%, hoch 100%) | Strahlung 750 W/m² (direkt 388) | ...
```

Damit kann der LLM bei Diskrepanz zwischen Cloud-% und Strahlung selbst die Realität erkennen ("dünne Schleier-Bewölkung, Sonne kommt durch"). **WICHTIG:** Die W/m²-Werte sind LLM-intern — dürfen NIEMALS roh an den User durchgereicht werden, sondern in Fliegersprache übersetzt (siehe `skills/shared/01_global/01_core_principles.md` Punkt 2d).

---

## Cache-Struktur

Die Override-Schicht greift auf einen Cache zu, der pro Spot/Region und Tag während des Context-Builds gefüllt wird:

```python
self._ctx_tq_cache[f"{name}|{date_str}"] = {
    "thermal_hours_total": int,        # Stunden mit climb >= 0.3 m/s
    "tq_danger_h": int,                # Stunden mit UNUSABLE-Tag
    "peak_climb_proxy": float,         # Peak Climb-Rate des Tages
    "productive_thermal_h": int,       # Stunden mit climb >= 0.7 + Band ok + kein UNUSABLE (Mai 2026: KEIN Cloud-Check mehr)
    "productive_h_strict": int,        # wie oben, aber climb >= 1.5 m/s
    "working_height_agl_m": int,       # Median Thermik-Top AGL über strict-Stunden
}
```

Cache-Migration ist nicht nötig — die Override-Logik nutzt `tq.get(..., 0)` Defaults und überschreibt alte Cache-Einträge bei der nächsten Analyse.

---

## Konfiguration

Alle Schwellen in `config.py`:

```python
PRODUCTIVE_CLIMB_MIN = 0.7       # m/s — Mindest-Climb für "produktive" Stunde
PRODUCTIVE_LOW_CLOUD_MAX = 80    # DEPRECATED Mai 2026 — nicht mehr im Productivity-Pfad
PRODUCTIVE_MID_CLOUD_MAX = 90    # DEPRECATED Mai 2026 — nicht mehr im Productivity-Pfad
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
