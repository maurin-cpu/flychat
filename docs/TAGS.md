# Tags & Startfenster — Topic-Konzept

Dieses Dokument beschreibt das **einheitliche Tag-System** der Wochencast-UI:
welche Topics existieren, welche Severities sie annehmen koennen, wie sie
deterministisch aus den Cache-Daten abgeleitet werden, und wie das
**Startfenster-Visual** funktioniert.

> **Sync-Pflicht (an Claude):** Bei Aenderungen an
> `engine/decision_engine.py:build_topic_tags`, `engine/decision_engine.py:build_start_window`,
> oder den Schwellen in `config.py`:
> - Tabelle `Topic-Katalog` aktualisieren (Wann STOP/WARN/GOOD/INFO).
> - Datum in *Letzte Aktualisierung* nachziehen, Changelog ergaenzen.
> - Frontend-Renderer `briefing.js:renderSpotLabels` muss die gleichen
>   `topic`/`severity`-Werte erkennen.

Letzte Aktualisierung: 2026-05-05 (Tag-Quellen Backend/LLM-Aufteilung dokumentiert)

---

## Designprinzipien

1. **Single source of truth.** Tags werden EINMAL deterministisch im Backend
   gebaut (`build_topic_tags`). Frontend rendert nur. Keine Auto-Tags im
   Frontend, keine LLM-Listen direkt anzeigen.
2. **Ein Topic = ein Tag.** Pro Topic erscheint pro Spot/Tag genau ein Tag,
   mit der hoechsten zutreffenden Severity. Keine Duplikate.
3. **Severity bedeutet was.** STOP = Flug verhindert. WARN = Sicherheits-Vorsicht.
   GOOD = aktiver Pluspunkt. INFO = Komfort-Hinweis ohne Sicherheitsbezug.
4. **Wenn nichts zu sagen ist, kein Tag.** Topics ohne klar zutreffende
   Severity werden weggelassen. Schwache Thermik = kein THERMAL-Tag (nicht
   `WARN: Thermik schwach`).
5. **Schwellen aus `config.py`.** Keine im Decision-Code hardcodierten Werte.

---

## 5 Klassen

| Klasse | Icon | Farbe | Funktion | UI-Position |
|---|---|---|---|---|
| **WINDOW** | 🛫 | mehrfarbig | Tageszeitleiste: wann kann ich starten | ganz oben |
| **STOP** | ⛔ | rot | Flugverhindernd (Sicherheit) | Block 1 |
| **WARN** | ⚠ | amber | Sicherheits-Vorsicht | Block 2 |
| **GOOD** | ✓ | gruen | Aktive Pluspunkte | Block 3 |
| **INFO** | ℹ | grau, dezent | Komfort, kein Sicherheitsthema | Block 4, kompakt |

---

## Topic-Katalog

### Tabelle (autoritativ — Quelle der Severity-Logik)

| Topic ID | Label | STOP wenn | WARN wenn | GOOD wenn | INFO wenn | Sonst |
|---|---|---|---|---|---|---|
| `WIND_GROUND` | "Boeen" / "Wind" | `gust_danger_hours >= WIND_TREND_NOTSAFE_HOURS` ODER `wind_danger_hours >= WIND_TREND_NOTSAFE_HOURS` ODER `wind_ok_count == 0` | `gust_warn_hours >= 1` ODER `wind_warn_hours >= 1` (und kein STOP) | Richtung OK (`wind_ok_count > wind_wrong_count`) UND `gust_warn_hours == 0` UND `wind_warn_hours == 0` | — | — |
| `WIND_ALOFT` | "Hoehenwind" | `aloft_danger_hours >= WIND_TREND_NOTSAFE_HOURS` ODER `aloft_gust_danger_hours >= WIND_TREND_NOTSAFE_HOURS` | `aloft_warn_hours >= 1` ODER `aloft_gust_warn_hours >= 1` (und kein STOP) | beide 0 (kein WARN, kein STOP) | — | — |
| `FOEHN` | "Foehn" | `foehn_risk == "high"` | `foehn_risk == "moderate"` | — | — | low/none → kein Tag |
| `RAIN` | "Regen" | `rain_hours >= 1` | — | — | — | trocken → kein Tag |
| `THUNDERSTORM` | "Gewitter" | `thunderstorm_hours >= 1` ODER CAPE > `CAPE_DANGER_JKG` | — | — | — | — |
| `CLOUDS` | "Bewoelkung" | overcast 8/8 ganztags (`avg_low_mid >= 90` und `cloud_total >= 95`) | `avg_low_mid >= 85` ueber Thermikstunden | `avg_low_mid <= 40` ueber Thermikstunden | — | — |
| `THERMAL` | "Thermik" | — | — | `peak_climb_rate >= 1.5` m/s | — | sonst kein Tag |
| `XC` | "XC" | — | — | `xc_potential in ("high", "moderate")` | — | "low" → kein Tag |
| `TURBULENCE` | "Klappern" | — | — | — | `rough_danger_h >= 1` | — |

### Reihenfolge innerhalb eines Severity-Blocks

Pro Severity-Block werden die Topics in dieser Reihenfolge gerendert:

1. `WIND_GROUND`
2. `WIND_ALOFT`
3. `FOEHN`
4. `RAIN`
5. `THUNDERSTORM`
6. `CLOUDS`
7. `THERMAL`
8. `XC`
9. `TURBULENCE`

So sehen User die wichtigsten Topics oben (Wind/Boeen zuerst, dann Atmosphaere,
dann Wetter, dann Komfort).

---

## Tag-Quellen — Backend vs LLM (geplant fuer v5)

> **Status:** Architektur-Entscheidung 2026-05-05, **noch nicht implementiert**.
> Aktuell (v4) baut das Backend **alle** Topics deterministisch aus Wetterdaten.
> Diese Sektion beschreibt den Ziel-Zustand (Option C — Hybrid).

### Designziel

Harte Wetter-Fakten kommen vom **Backend** (deterministisch, nicht
verhandelbar), weiche Bewertungen vom **LLM** (interpretiert mit Begruendung).
Beide Quellen werden zu **einem** `tags[]`-Array gemerged — das Frontend
unterscheidet die Quelle nicht.

### Quellen-Verteilung der bestehenden Topics

| Topic | Quelle | Begruendung |
|---|---|---|
| `WIND_GROUND` | **Backend** | harte Schwellen, keine Interpretation |
| `WIND_ALOFT` | **Backend** | harte Schwellen |
| `RAIN` | **Backend** | `rain_hours` zaehlen |
| `THUNDERSTORM` | **Backend** | hours + CAPE |
| `FOEHN` | **Backend** (aus Decision-Pipeline) | bereits hybrid mit ΔP-Logik |
| `TURBULENCE` | **Backend** (aus `tq_ratio`) | deterministische Mechanik-Detection |
| `CLOUDS` | **LLM** | Tagesverlauf interpretieren ("Cu am Morgen, spaeter Cs") |
| `THERMAL` | **LLM** | "schwach aber nutzbar" vs "torn" — Interpretation |
| `XC` | **LLM** | haengt von Hoehenwind-Richtung, Konvergenz-Linien, Wolkenstrasse ab |

### Neue LLM-Topics (geplant)

Aktuell in `flyability_limits` / `highlights` / `primary_reducer` /
`primary_booster` versteckt — sollen eigene Topic-IDs werden:

| Topic ID | Label | Wann | Severity-Range |
|---|---|---|---|
| `INVERSION` | "Inversion" | LLM erkennt blockierende oder limitierende Inversion | warn / info |
| `BASE` | "Basis" | LLM bewertet Wolkenbasis (tief/hoch relativ zu Spot) | warn / good / info |
| `WINDOW` | "Flugfenster" | LLM bewertet Fenster-Laenge / Nutzbarkeit | warn / good / info |
| `SUNSHINE` | "Einstrahlung" | LLM bewertet Einstrahlungs-Qualitaet | good / info |
| `CONVERGENCE` | "Konvergenz" | LLM erkennt Konvergenzlinien als XC-Booster | good |

### LLM-Output-Schema (geplant)

LLM produziert ein neues Feld `llm_tags` statt der heutigen Felder
`flyability_limits` / `highlights` / `primary_reducer` / `primary_booster`:

```json
"llm_tags": [
  {
    "topic": "THERMAL",
    "severity": "good",
    "label": "Thermik",
    "value": "peak 2.8 m/s, 12-15 h",
    "time": "12-15 h"
  },
  {
    "topic": "CLOUDS",
    "severity": "warn",
    "label": "Bewoelkung",
    "value": "bedeckt 80% Mittag",
    "time": "11-14 h"
  }
]
```

Backend-Merge-Logik:

```
final_tags = build_backend_topic_tags(...)        # WIND_*, RAIN, THUNDERSTORM, FOEHN, TURBULENCE
           + result["llm_tags"]                   # CLOUDS, THERMAL, XC, INVERSION, BASE, WINDOW, SUNSHINE, CONVERGENCE
final_tags = sort_by(severity, topic_order)
final_tags = deduplicate_by_topic(keep highest severity)
```

### Severity-Hoheit

- **STOP**: nur Backend. Sicherheit ist nicht verhandelbar — das LLM darf
  keine STOP-Tags setzen.
- **WARN / GOOD / INFO**: LLM darf setzen (interpretierte Bewertung).

### Konflikt- und Sanity-Validierung

Backend validiert LLM-Tags gegen Daten-Plausibilitaet:

- LLM `THERMAL good` aber `peak_climb_rate < 1.5` m/s → Tag wird verworfen + geloggt
- LLM `CLOUDS good` aber `avg_low_mid > 70` ueber Thermikstunden → verworfen
- LLM-Topic nicht in Whitelist (`CLOUDS` / `THERMAL` / `XC` / `INVERSION` / `BASE` / `WINDOW` / `SUNSHINE` / `CONVERGENCE`) → verworfen
- LLM setzt STOP → verworfen (Severity-Hoheit-Verletzung)

### Was bleibt unveraendert

- **Prosa-Felder** (`summary`, `wind_summary`, `safety_feedback`,
  `recommendation`, `streckenflug_summary`) bleiben — sie liefern den
  *Erklaerungs-Text* zu den Tags, gerendert in Hero-Rationale + Insights-Akkordeons.
- **Foehn-Decision-Pipeline** (`apply_foehn_decision`) bleibt — `foehn_risk`
  ist die Quelle fuer den FOEHN-Tag.
- **`caution_notes` / `no_go_reasons`** bleiben als LLM-Prosa fuer Hero-Begruendung
  (erster Satz wird als Rationale gezogen).

### Migration in einem Schritt (geplant)

1. Skill-Templates (`skills/shared/04_flyability/00_template_*.md`,
   `skills/shared/03_safety/00_template_*.md`) auf `llm_tags` umstellen.
2. `engine/analyzers.py:_finalize_tags` mergt Backend- + LLM-Tags.
3. Sanity-Validator in `engine/decision_engine.py:validate_llm_tags()`.
4. Legacy-Felder (`flyability_limits`, `highlights`, `primary_reducer`,
   `primary_booster`) ersatzlos entfernen.
5. Cache regenerieren.

---

## Tag-Schema (im Cache)

Jeder Spot/Region in `data/spot_analyses.json` bzw. `data/region_analyses.json`
erhaelt zwei neue Felder unter `safety`:

```jsonc
{
  "spot": "Niederbauen",
  "safety": {
    // ... existierende Felder ...
    "tags": [
      {
        "topic": "WIND_GROUND",      // Topic ID aus Tabelle oben
        "severity": "stop",          // "stop" | "warn" | "good" | "info"
        "label": "Boeen",            // Label fuer UI-Anzeige
        "value": "41 km/h",          // primaerer Wert (kann leer sein)
        "time": "13-16 h"            // Zeitfenster (kann leer sein)
      },
      // ...
    ],
    "start_window": [
      {"hour": 6,  "state": "neutral"},
      {"hour": 7,  "state": "neutral"},
      // ...
      {"hour": 12, "state": "startbar"},
      {"hour": 13, "state": "sportlich"},
      {"hour": 14, "state": "blockiert"},
      // ...
    ]
  }
}
```

### Feldformate

- `topic` — Eine der IDs aus Topic-Katalog. Genau einmal pro Tagesresultat.
- `severity` — `"stop" | "warn" | "good" | "info"`. Maximale Severity gewinnt.
- `label` — Topic-Label aus Tabelle (deutsch, fuer Frontend-Anzeige).
- `value` — Optionaler kurzer Wert. Beispiele: `"41 km/h"`, `"2.1 mm/h"`,
  `"DP 6.1 hPa"`, `"peak 2.3 m/s"`. Wenn nicht sinnvoll: `""`.
- `time` — Optionales Zeitfenster. Format: `"HH-HH h"` oder `"ganztags"` oder
  `""`. Soll knapp sein.

---

## Startfenster (WINDOW)

### Klassifikation pro Stunde

Das Startfenster nutzt **ausschliesslich** Boden-Wind/Boeen + Windrichtung —
keine Hoehenwerte, kein Foehn, kein Regen. Begruendung: Es geht um die
Frage "kann ich am Boden starten?". Hoehenrisiken (Foehn, Aloft-Wind) und
Wetter-NoGos (Regen, Gewitter) zeigen sich separat als STOP/WARN-Topics.

Pro Flugstunde (definiert durch `FLIGHT_HOURS_START..FLIGHT_HOURS_END` in
`config.py`) wird einer von vier Zustaenden vergeben:

| State | Bedingung (alle Schwellen aus `config.py`) |
|---|---|
| `startbar` | Richtung im Sektor (`is_wind_in_range`) UND `wind_speed_10m <= WIND_WARN_KMH` (20) UND `wind_gusts_10m <= GUST_WARN_KMH` (30) |
| `sportlich` | Richtung im Sektor UND (`WIND_WARN_KMH < wind_speed_10m <= WIND_DANGER_KMH`, also 20-30) ODER (`GUST_WARN_KMH < wind_gusts_10m <= GUST_DANGER_KMH`, also 30-40) |
| `blockiert` | `wind_speed_10m > WIND_DANGER_KMH` (>30) ODER `wind_gusts_10m > GUST_DANGER_KMH` (>40) ODER Richtung ausserhalb Sektor |
| `neutral` | Stunde ausserhalb der Flugstunden / Datenpunkt fehlt |

### UI-Visualisierung

Frontend rendert horizontale Zellen (eine pro Stunde) in der Reihenfolge der
Stunden, mit Farb-/Texturkodierung pro `state`:

- `startbar` — gruen, Voll-Block
- `sportlich` — amber, Halbschraffur
- `blockiert` — rot, Voll-Block
- `neutral` — grau, leer

Darunter erscheint eine kompakte Zusammenfassung (z.B. `"startbar 12-14 h,
sportlich 14-15 h"`), die zusammenhaengende Bloecke benennt.

### Was das WINDOW NICHT zeigt

- Kein Hoehenwind (`WIND_ALOFT`) — eigenes STOP/WARN-Topic.
- Kein Foehn — eigenes STOP/WARN-Topic.
- Kein Regen — bei `rain_hours >= 1` ist der Tag ohnehin durch RAIN-STOP
  abgedeckt.
- Keine Gewitter, kein CAPE — eigenes THUNDERSTORM-STOP-Topic.

So bleibt das Window-Visual eindeutig: "Wind & Boeen am Boden — kann ich
starten?". Jede andere Sicherheitsdimension hat ihren eigenen Tag.

---

## Schwellen-Quelle

Alle Werte aus `config.py`:

| Konstante | Wert | Verwendung |
|---|---|---|
| `WIND_WARN_KMH` | 20 | sportlich-Schwelle Bodenwind |
| `WIND_DANGER_KMH` | 30 | blockiert-Schwelle Bodenwind |
| `GUST_WARN_KMH` | 30 | sportlich-Schwelle Boeen |
| `GUST_DANGER_KMH` | 40 | blockiert-Schwelle Boeen |
| `WIND_DIRECTION_TOLERANCE_PCT` | 0.10 | Sektor-Toleranz Richtung |
| `WIND_TREND_NOTSAFE_HOURS` | 3 | STOP-Schwelle Stunden-Anzahl |
| `WIND_TREND_CONDITIONAL_HOURS` | 3 | WARN-Schwelle Stunden-Anzahl |
| `CAPE_DANGER_JKG` | 1500 | THUNDERSTORM-STOP |
| `FLIGHT_HOURS_START` / `FLIGHT_HOURS_END` | 6 / 21 | Window-Bereich |

> **Aenderungs-Regel:** Schwellen werden NUR in `config.py` veraendert. Diese
> Tabelle hier dokumentiert nur die Verwendung. Die `decision_engine` liest
> immer aus `config`, nie hardcodiert.

---

## Beispiele

### Schlechter Tag (Schauer + Boeen + Foehn)

```
🛫  Startfenster
06 08 10 12 14 16 18 20
░░ ░░ ░░ ▓▓ ▓▓ ▒▒ ⛔ ⛔
       startbar 12-14 h, sportlich 14-15 h

⛔ STOP
   Boeen        41 km/h    13-16 h
   Hoehenwind   36 km/h    12-16 h
   Regen        2.1 mm/h   10-11 h

⚠ WARN
   Foehn        DP 6.1 hPa Sued

✓ GOOD
   —

ℹ Hinweis · ruppig (mech. Klappern ganztags)
```

### Guter Tag

```
🛫  Startfenster
06 08 10 12 14 16 18 20
░░ ░░ ▓▓ ▓▓ ▓▓ ▓▓ ▒▒ ░░
       startbar 10-16 h (6h)

⚠ WARN
   Hoehenwind   28 km/h    14-16 h

✓ GOOD
   Thermik      peak 2.3 m/s, 12-15 h
   Bewoelkung   tief 20 %, mittel 30 %
   XC           hohes Potenzial
```

### Schwacher Abgleiter-Tag (kein THERMAL-Tag)

Ist `peak_climb_rate < 1.5` UND keine Sicherheitsthemen:
```
🛫  Startfenster
06 08 10 12 14 16 18 20
░░ ░░ ▓▓ ▓▓ ▓▓ ▒▒ ░░ ░░
       startbar 10-14 h (4h)

✓ GOOD
   Bewoelkung   tief 30 %, mittel 40 %

(kein Thermik-Tag — peak unter Schwelle)
```

Window verkuerzt sich automatisch (weniger ▓-Stunden), THERMAL faellt weg —
User versteht intuitiv "lohnt sich nicht zum Steigen".

---

## Migration & Kompatibilitaet

- `safety.tags` und `safety.start_window` werden **zusaetzlich** zu den
  bestehenden Feldern (`caution_notes`, `no_go_reasons`, `primary_reducer`,
  `primary_booster`, `foehn_risk` etc.) befuellt.
- Bestehende LLM-Prosa-Felder (`summary`, `wind_summary`, `recommendation`)
  bleiben unveraendert und werden weiter angezeigt — sie liefern den
  *Erklaerungs-Text* zu den Tags.
- `caution_notes` und `no_go_reasons` werden **nicht mehr direkt im
  briefing.js-Tag-Renderer** gerendert. Sie bleiben aber im
  `summary`/Begruendung sichtbar.

---

## Changelog

- **2026-05-05** — Architektur-Entscheidung Option C (Hybrid v5) dokumentiert:
  Backend liefert deterministische Topics (`WIND_GROUND`, `WIND_ALOFT`, `RAIN`,
  `THUNDERSTORM`, `FOEHN`, `TURBULENCE`), LLM liefert interpretierte Topics
  (`CLOUDS`, `THERMAL`, `XC`) plus geplante neue Topics (`INVERSION`, `BASE`,
  `WINDOW`, `SUNSHINE`, `CONVERGENCE`) ueber neues Feld `llm_tags`. STOP nur
  vom Backend. Noch nicht implementiert.
- **2026-05-04** — Initial. V4 Tag-Konzept mit 5 Klassen (WINDOW + STOP + WARN
  + GOOD + INFO), Topic-Katalog, Window-Klassifikation aus `config.py`-Schwellen.
