# Tags & Startfenster — Topic-Konzept

Dieses Dokument beschreibt das **einheitliche Tag-System** der Gleitcast-UI:
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
3. **Severity bedeutet was.** STOP = Flug verhindert. WARN = Sicherheits-Vorsicht
   (Pilot kann sich verletzen). REDUCER = Fliegbarkeit-Minderer ohne
   Sicherheitsbezug (Tag wird unattraktiver, nicht gefaehrlicher). GOOD =
   aktiver Pluspunkt.
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
| **WARN** | ⚠ | amber | Sicherheits-Vorsicht (Sicherheit, kein STOP) | Block 2 |
| **REDUCER** | ↓ | grau-blau | Fliegbarkeit-Minderer — drueckt Tagesqualitaet, KEIN Sicherheitsthema (Bewoelkung, schwache Thermik, mech. Klappern, kurzes Fenster) | Block 3 |
| **GOOD** | ✓ | gruen | Aktive Pluspunkte | Block 4 |

**Trennlinie WARN vs REDUCER**: WARN ist Sicherheits-Vorsicht (Pilot muss
aufpassen, koennte sich verletzen). REDUCER ist Fliegbarkeits-Minderung (Tag
wird unattraktiver, aber nicht gefaehrlicher). Bewoelkung, schwache Thermik,
mech. Klappern und kurze Flugfenster sind keine Sicherheitsthemen — sie
gehoeren ausdruecklich NICHT in WARN.

---

## Topic-Katalog

### Tabelle (autoritativ — Quelle der Severity-Logik)

WARN ist Sicherheits-Vorsicht. REDUCER ist Fliegbarkeit-Minderer (kein
Sicherheitsthema). Topics, die Tagesqualitaet druecken, ohne den Piloten zu
gefaehrden, gehoeren in REDUCER, nicht in WARN.

**Bewoelkung — Sicherheit vs Fliegbarkeit:**
- Wolken **auf oder unter** Startplatzhoehe mit hoher Bedeckung sind ein
  Sicherheitsthema (kein Sichtflug, Startplatz im Nebel) → STOP/WARN.
- Wolken **oberhalb** des Startplatzes sind kein Sicherheitsthema, sondern
  ein Fliegbarkeits-Minderer (weniger Sonne → schwaechere Thermik) → REDUCER.

**Wolkenbasis-Hoehe (BASE) — eigene Topic:**
- Tiefe Basis ueber dem Startplatz (`< 600` m AGL) → REDUCER (gedeckelte Thermik).
- Hohe Basis ueber dem Gipfel (`> 800` m ueber peak) → GOOD (Steigraum,
  XC-tauglich).

| Topic ID | Label | STOP wenn | WARN wenn (Sicherheit) | REDUCER wenn (Fliegbarkeit) | GOOD wenn | Sonst |
|---|---|---|---|---|---|---|
| `WIND_GROUND` | "Boeen" / "Wind" | `gust_danger_hours >= WIND_TREND_NOTSAFE_HOURS` ODER `wind_danger_hours >= WIND_TREND_NOTSAFE_HOURS` ODER `wind_ok_count == 0` | `gust_warn_hours >= 1` ODER `wind_warn_hours >= 1` (und kein STOP) | — | Richtung OK (`wind_ok_count > wind_wrong_count`) UND `gust_warn_hours == 0` UND `wind_warn_hours == 0` | — |
| `WIND_ALOFT` | "Hoehenwind" | `aloft_danger_hours >= WIND_TREND_NOTSAFE_HOURS` ODER `aloft_gust_danger_hours >= WIND_TREND_NOTSAFE_HOURS` | `aloft_warn_hours >= 1` ODER `aloft_gust_warn_hours >= 1` (und kein STOP) | — | beide 0 (kein WARN, kein STOP) | — |
| `FOEHN` | "Foehn" | `foehn_risk == "high"` | `foehn_risk == "moderate"` | — | — | low/none → kein Tag |
| `RAIN` | "Regen" | `rain_hours >= 1` | — | — | — | trocken → kein Tag |
| `THUNDERSTORM` | "Gewitter" | `thunderstorm_hours >= 1` ODER CAPE > `CAPE_DANGER_JKG` | — | — | — | — |
| `CLOUDS` | "Bewoelkung" | **geschlossene Decke auf/unter Startplatz** (`cloud_base <= elevation_m + OVERCAST_DANGER_BASE_BUFFER_M(100)` UND `cloud_cover_low >= OVERCAST_DANGER_COVER_PCT(80)`; bei `elevation_m >= 3000` zusätzlich `cloud_cover_mid >= 80`) — Sicht/IFR, Start in die Wolke ODER Abstieg durch geschlossene Decke. Identisch mit OVERCAST-DANGER-Gate | — | **(deterministisch)** tiefe Decke knapp ÜBER Platz: `elevation_m + 100 < cloud_base <= elevation_m + OVERCAST_REDUCER_BASE_MAX_M(400)` UND `cloud_cover_low >= OVERCAST_REDUCER_COVER_PCT(75)` — "Basis nahe Startplatz", eingeschränkte Arbeitshöhe, fliegbar/grün. **(LLM)** zusätzlich hohe Bedeckung oberhalb (Thermik-Dämpfung) | `avg_low_mid <= 40` ueber Thermikstunden | STOP=OVERCAST-DANGER, REDUCER ist KEIN Status-Downgrade |
| `BASE` | "Wolkenbasis" | — | — | LLM: tiefe Basis ueber dem Startplatz (`cloud_base - elevation_m < 600` m) — wenig Steigraum, Thermik gedeckelt | LLM: hohe Basis (`cloud_base - peak_height_m > 800` m) — viel Steigraum / XC-tauglich | `cloud_base == null` → kein Tag |
| `THERMAL` | "Thermik" | — | — | LLM: schwache aber nutzbare Thermik (`peak_climb_rate < 1.5` UND `productive_thermal_h >= 1`) | `peak_climb_rate >= 1.5` m/s | sonst kein Tag (Abgleiter-Tag) |
| `XC` | "XC" | — | — | — | `xc_potential in ("high", "moderate")` | "low" → kein Tag |
| `TURBULENCE` | "Klappern" | — | — | `rough_danger_h >= 1` (war INFO — mech. Klappern ist Komfort-Minderer) | — | — |
| `WINDOW` | "Flugfenster" | — | — | LLM: Fenster < `CLEAN_WINDOW_MIN_HOURS` ODER stark fragmentiert | LLM: Fenster ≥ 4h zusammenhaengend, Verhaeltnis ≥ 60 % | — |

### Reihenfolge innerhalb eines Severity-Blocks

Pro Severity-Block werden die Topics in dieser Reihenfolge gerendert:

1. `WIND_GROUND`
2. `WIND_ALOFT`
3. `FOEHN`
4. `RAIN`
5. `THUNDERSTORM`
6. `CLOUDS`
7. `BASE`
8. `THERMAL`
9. `XC`
10. `TURBULENCE`
11. `WINDOW`

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

### Quellen-Verteilung — Topic × Severity (autoritativ)

Spalten zeigen pro Severity, **wer den Tag setzen darf** (`B` = Backend
deterministisch, `L` = LLM interpretiert, `—` = nicht erlaubt). STOP und WARN
sind ueberall Backend-Hoheit (Sicherheits-Schweregrade nicht verhandelbar).

| Topic ID | STOP | WARN | REDUCER | GOOD | Begruendung Quellenwahl |
|---|:---:|:---:|:---:|:---:|---|
| `WIND_GROUND` | B | B | — | B | harte Schwellen aus `config.py` (WIND/GUST_DANGER/WARN, WIND_TREND_NOTSAFE_HOURS) |
| `WIND_ALOFT` | B | B | — | B | harte Schwellen, gleiche Logik wie Boden |
| `FOEHN` | B | B | — | — | aus Decision-Pipeline (`foehn_risk` ΔP-Logik) |
| `RAIN` | B | — | — | — | `rain_hours >= 1` deterministisch |
| `THUNDERSTORM` | B | — | — | — | `thunderstorm_hours` + CAPE deterministisch |
| `CLOUDS` | B | — | B+L | L | STOP: `cloud_base` vs `elevation_m` deterministisch (= OVERCAST-DANGER). REDUCER: deterministisch (Basis nahe Platz) UND LLM (Bedeckungs-Dämpfung); Merge nimmt höchste Severity. GOOD: LLM |
| `BASE` | — | — | L | L | LLM bewertet Wolkenbasis-Hoehe relativ zu Spot/Gipfel mit Begruendung |
| `THERMAL` | — | — | L | L | "schwach aber nutzbar" vs "torn" — pure Interpretation, Backend liefert nur `peak_climb_rate` als Sanity-Schwelle |
| `XC` | — | — | — | L | haengt von Hoehenwind-Richtung, Konvergenz-Linien, Wolkenstrasse ab |
| `TURBULENCE` | — | — | B | — | aus `rough_danger_h` / `tq_ratio` — deterministische Mechanik-Detection |
| `WINDOW` | — | — | L | L | LLM bewertet Fenster-Laenge / Nutzbarkeit qualitativ; Backend liefert die Stunden-Zahl als Input |
| `INVERSION` | — | — | L | — | LLM erkennt blockierende/limitierende Inversion aus Vertikalprofil |
| `SUNSHINE` | — | — | L | L | LLM bewertet Einstrahlungs-Qualitaet (Tagesverlauf, Wolkenbedeckung) |
| `CONVERGENCE` | — | — | — | L | LLM erkennt Konvergenzlinien als XC-Booster aus Wind-Profilen |

**Regel als Zusammenfassung:**
- **STOP / WARN** → ausschliesslich Backend (Sicherheits-Hoheit).
- **REDUCER / GOOD** → kann Backend (deterministische Daten wie `TURBULENCE`)
  oder LLM (Interpretation wie `THERMAL`, `BASE`, `WINDOW`) sein. Pro Topic
  ist die Quelle in der Tabelle oben fixiert.
- **Validator** verwirft jeden Tag, der nicht der hier definierten Topic ×
  Severity × Quelle-Matrix entspricht (siehe `validate_llm_tags()`).

### Neue LLM-Topics (geplant)

Aktuell in `flyability_limits` / `highlights` / `primary_reducer` /
`primary_booster` versteckt — sollen eigene Topic-IDs werden:

| Topic ID | Label | Wann | Severity-Range |
|---|---|---|---|
| `INVERSION` | "Inversion" | LLM erkennt blockierende oder limitierende Inversion (limitiert Steigen, kein Sicherheitsthema) | reducer |
| `WINDOW` | "Flugfenster" | LLM bewertet Fenster-Laenge / Nutzbarkeit | reducer / good |
| `SUNSHINE` | "Einstrahlung" | LLM bewertet Einstrahlungs-Qualitaet | reducer / good |
| `CONVERGENCE` | "Konvergenz" | LLM erkennt Konvergenzlinien als XC-Booster | good |

> `BASE` ist im Hauptkatalog (oben) — eigenes Topic mit reducer/good Severity-Range.

> **Hinweis:** Diese Topics sind ausschliesslich Fliegbarkeits-relevant — sie
> erzeugen NIE WARN (kein Sicherheitsthema), nur REDUCER oder GOOD. STOP ist
> Backend-Hoheit und kommt hier nie vor.

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
    "severity": "reducer",
    "label": "Bewoelkung",
    "value": "bedeckt 80 % Mittag",
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
- **WARN**: nur Backend. Sicherheits-Vorsicht hat klare Schwellen — das LLM
  darf keine WARN-Tags setzen. (Verhindert, dass Bewoelkung/Thermik faelschlich
  als Sicherheits-Warnung markiert wird.)
- **REDUCER / GOOD**: LLM darf setzen (interpretierte Bewertung der
  Fliegbarkeits-Qualitaet bzw. der Pluspunkte).

### Konflikt- und Sanity-Validierung

Backend validiert LLM-Tags gegen Daten-Plausibilitaet:

- LLM `THERMAL good` aber `peak_climb_rate < 1.5` m/s → Tag wird verworfen + geloggt
- LLM `CLOUDS good` aber `avg_low_mid > 70` ueber Thermikstunden → verworfen
- LLM `BASE good` aber `cloud_base - peak_height_m <= 800` m → verworfen
- LLM `BASE reducer` aber `cloud_base == null` ODER `cloud_base - elevation_m >= 600` → verworfen
- LLM-Topic nicht in Whitelist (`CLOUDS` / `BASE` / `THERMAL` / `XC` / `INVERSION` / `WINDOW` / `SUNSHINE` / `CONVERGENCE`) → verworfen
- LLM setzt STOP oder WARN → verworfen (Severity-Hoheit-Verletzung — nur Backend darf Sicherheits-Schweregrade setzen)

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
        "severity": "stop",          // "stop" | "warn" | "reducer" | "good"
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
- `severity` — `"stop" | "warn" | "reducer" | "good"`. Maximale Severity gewinnt.
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

↓ REDUCER
   Klappern       mech. Klappern ganztags
   Bewoelkung     bedeckt 85 % Thermikstunden (Basis ueber Startplatz)
   Wolkenbasis    400 m ueber Startplatz (gedeckelte Thermik)

✓ GOOD
   —
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
   Thermik       peak 2.3 m/s, 12-15 h
   Bewoelkung    tief 20 %, mittel 30 %
   Wolkenbasis   1200 m ueber Gipfel (viel Steigraum)
   XC            hohes Potenzial
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

- **2026-05-05** (spaeter) — INFO-Klasse durch **REDUCER** ersetzt. WARN ist
  jetzt strikt Sicherheit, REDUCER fasst Fliegbarkeits-Minderer zusammen
  (Bewoelkung, schwache Thermik, mech. Klappern, kurzes Fenster, Inversion,
  tiefe Basis). Bisheriges CLOUDS-WARN → REDUCER, TURBULENCE-INFO → REDUCER.
  THERMAL-REDUCER (schwach aber nutzbar) und WINDOW-Topic (kurzes Fenster)
  in den Katalog aufgenommen. Severity-Hoheit erweitert: WARN nur Backend
  (war: WARN auch LLM erlaubt) — verhindert dass Wolken/Thermik faelschlich
  als Sicherheits-Warnung markiert werden.
  - **CLOUDS Sicherheits-Branch** ergaenzt: Wolken **auf/unter** Startplatzhoehe
    mit hoher Bedeckung sind STOP/WARN (Sicht-Risiko), Wolken **ueber** dem
    Startplatz bleiben REDUCER (Thermik-Daempfung).
  - **BASE-Topic** in den Hauptkatalog promoviert: Wolkenbasis-Hoehe als
    eigenes Topic — REDUCER bei tiefer Basis (< 600 m ueber Startplatz),
    GOOD bei hoher Basis (> 800 m ueber Gipfel).
- **2026-05-05** — Architektur-Entscheidung Option C (Hybrid v5) dokumentiert:
  Backend liefert deterministische Topics (`WIND_GROUND`, `WIND_ALOFT`, `RAIN`,
  `THUNDERSTORM`, `FOEHN`, `TURBULENCE`), LLM liefert interpretierte Topics
  (`CLOUDS`, `THERMAL`, `XC`) plus geplante neue Topics (`INVERSION`, `BASE`,
  `WINDOW`, `SUNSHINE`, `CONVERGENCE`) ueber neues Feld `llm_tags`. STOP nur
  vom Backend. Noch nicht implementiert.
- **2026-05-04** — Initial. V4 Tag-Konzept mit 5 Klassen (WINDOW + STOP + WARN
  + GOOD + INFO), Topic-Katalog, Window-Klassifikation aus `config.py`-Schwellen.
