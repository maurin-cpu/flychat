# Wind & Böen — Konzept und Schwellen

> **SYNC-PFLICHT für Claude:** Diese Doku beschreibt das **lebende Konzept** der
> Wind/Böen-Behandlung. Wenn das Konzept geändert wird (Schwellen, Tags, Trends,
> Override-Logik), MUSS diese Datei mit aktualisiert werden — sonst geraten
> Code, Skills und Dokumentation auseinander. Die Memory-Notiz
> `wind_gust_harmonization.md` enthält denselben Sync-Pflicht-Hinweis.

## Übersicht

Wind und Böen werden in zwei Dimensionen klassifiziert:

| Dimension | Werte |
|---|---|
| **Quelle** | Boden (10m AGL) vs. Höhe (Flugbereich) — nur für Anzeige/Diagnose |
| **Charakter** | Wind (sustained Modellwind W) vs. Böen (Turbulenzrisiko T = W + Decay) |

Die **Schwellen sind identisch** für Boden und Höhe — die Asymmetrie liegt nur
zwischen Wind (strukturell hart) und Böen (LLM-Empfehlung mit Trend).

## Konstanten (`config.py`)

```python
# Wind (Boden + Höhe einheitlich)
WIND_WARN_KMH = 20      # → [WIND-WARN] / [ALOFT-WIND-WARN]
WIND_DANGER_KMH = 30    # → [WIND-DANGER] / [ALOFT-WIND-DANGER]

# Böen (Boden + Höhe einheitlich, nur Spots)
GUST_WARN_KMH = 30      # → [GUST-WARN] / [ALOFT-GUST-WARN]
GUST_DANGER_KMH = 40    # → [GUST-DANGER] / [ALOFT-GUST-DANGER]

# Stunden-Schwellen für Trend-Override
WIND_TREND_NOTSAFE_HOURS = 3      # WIND-TREND DURCHGEHEND_DANGER ≥ Xh → Auto-NoGo
WIND_TREND_CONDITIONAL_HOURS = 3  # safe → conditional Schwelle
GUST_TREND_FLOOR_HOURS = 3        # Boeen-Floor: gwarn/gdanger ≥ Xh → conditional
```

`ideal_wind_max` aus der CSV wird **nicht mehr verwendet** — weder im Code noch
im LLM-Kontext. Spots haben dieselben Wind-Schwellen wie Regionen.

## Tags

| Tag | Auslöser | Sichtbar bei |
|---|---|---|
| `[WIND-WARN]` | Bodenwind ≥ `WIND_WARN_KMH` und < `WIND_DANGER_KMH` | Spot + Region |
| `[WIND-DANGER]` | Bodenwind > `WIND_DANGER_KMH` | Spot + Region |
| `[ALOFT-WIND-WARN]` | Höhenwind W(z) im Flugbereich gleicher Bereich | Spot + Region |
| `[ALOFT-WIND-DANGER]` | Höhenwind W(z) > `WIND_DANGER_KMH` | Spot + Region |
| `[GUST-WARN]` | Bodenböen > `GUST_WARN_KMH` | nur Spot |
| `[GUST-DANGER]` | Bodenböen > `GUST_DANGER_KMH` | nur Spot |
| `[ALOFT-GUST-WARN]` | Höhenböen T(z) > `GUST_WARN_KMH` im Flugbereich | nur Spot |
| `[ALOFT-GUST-DANGER]` | Höhenböen T(z) > `GUST_DANGER_KMH` im Flugbereich | nur Spot |
| `[WIND-WRONG]` | Bodenwind-Richtung außerhalb Spot-Sektor | nur Spot |
| `[WIND-OK]` | Bodenwind-Richtung im Spot-Sektor | nur Spot |

**Entfernt (Apr 2026):** `[WIND-MODERATE]`, `[WIND-STRONG]`, `[WIND-CALM]` (Region),
`[STRONG-WIND-WARN]` (Spot), `[ALOFT-WARN]`, `[ALOFT-DANGER]`. Die alten Tag-Namen
existieren in keiner aktuellen Cache- oder Output-Form.

`[WIND-CALM]` bleibt als interner Marker im Region-`wind_status` erhalten, wird aber
nicht mehr als Tag im LLM-Output ausgegeben (= keine Tags = ruhig).

## Trends — 7 Pattern, 2 Achsen

Beide Trends nutzen das identische `TREND-VOKABULAR` (`skills/shared/_hazard_blocks.md`):
AUFKLAERUNG, ZUNEHMEND, EINGEKESSELT, EINGEKESSELT_KNAPP, DURCHGEHEND_WARN,
DURCHGEHEND_DANGER, VEREINZELT, STABIL.

| Trend | Quelle | Code | Ausgabe-Label |
|---|---|---|---|
| **WIND-TREND** | Bodenwind WARN/DANGER **+** Höhenwind WARN/DANGER summiert | `_detect_aloft_trend()` (historischer Name), `_format_aloft_trend_text()` | `WIND-TREND: <Pattern> — ...` |
| **GUST-TREND** | Bodenböen WARN/DANGER **+** Höhenböen WARN/DANGER summiert | `_detect_gust_trend()`, `_format_gust_trend_text()` | `GUST-TREND: <Pattern> — ...` |

> Die Funktionsnamen `_detect_aloft_trend` und `_format_aloft_trend_text` sind
> historisch (waren ursprünglich nur für Höhenwind). Sie liefern jetzt das
> kombinierte Boden+Höhe-Pattern. Beim nächsten Refactor umbenennen oder belassen
> — keine funktionale Notwendigkeit zur Umbenennung.

## Override-Verhalten (`engine/analyzers.py`)

### Auto-NoGo (hart, System-erzwungen)

| Trigger | Reaktion |
|---|---|
| WIND-TREND `DURCHGEHEND_DANGER` | `safety_status = not_safe`, `primary_no_go = WIND_DANGER` |
| WIND-TREND `EINGEKESSELT` mit Fenster < 3h | `safety_status = not_safe`, `primary_no_go = EINGEKESSELT-WIND` |
| WIND-TREND AUFKLAERUNG / VEREINZELT / EINGEKESSELT_KNAPP / ZUNEHMEND / DURCHGEHEND_WARN | **kein Override** — sauberes Fenster zählt, max. conditional |
| `[WIND-WRONG]` ganztägig | `not_safe`, `primary_no_go = Windrichtung` |
| Saubere Stunden < `CLEAN_WINDOW_MIN_HOURS` (3h) | `not_safe`, Start-Fenster zu kurz |

### Soft-Override (safe → conditional)

| Trigger | Reaktion |
|---|---|
| `aloft_d ≥ WIND_TREND_CONDITIONAL_HOURS` ODER `aloft_gd ≥ ...` | `safe → conditional`, Caution-Note mit korrekter Schwelle |
| Boeen-Floor: `gwarn ≥ 3h` ODER `gdanger ≥ 3h` (Boden + Höhe summiert) | `safe → conditional` mit Boeen-Caution-Note |

### LLM-Empfehlung (kein Auto-Override)

| Trigger | Skill-Anweisung |
|---|---|
| GUST-TREND `DURCHGEHEND_DANGER` | LLM **bevorzugt** `not_safe`, `primary_no_go = STARKE_BOEEN`. Nur bei klar sauberer 4h+ AUFKLAERUNG conditional. |
| GUST-TREND `EINGEKESSELT` mit Fenster < 3h | LLM bevorzugt `not_safe` (Sonderfall 2 Boden-Gefahren) |
| `[GUST-DANGER]` / `[ALOFT-GUST-DANGER]` ≥ 3h | LLM bevorzugt NoGo bei DURCHGEHEND-Trend, sonst conditional |

## Asymmetrie Wind vs. Böen — warum?

- **Wind sustained** (W) ist physikalisch bindend: Sustained 30+ km/h über 3 Stunden
  bedeutet kein realistisches Start-/Landungs-Fenster. Strukturelles Stopp-Kriterium
  → Auto-NoGo bei DURCHGEHEND_DANGER.
- **Böen** (T) sind Spitzen mit weicher Verteilung. Trend (AUFKLAERUNG vs. EINGEKESSELT)
  und sauberes Fenster sind kontextabhängig. LLM hat letztes Wort, Skills geben klare
  Empfehlung "bevorzugt NoGo" bei DURCHGEHEND_DANGER, aber kein hartes Auto-Override.
- **Boden vs. Höhe** ist nur eine Anzeige-Dimension — die Schwellen und Reaktionen
  sind identisch. Der Pilot sieht in caution_notes welche Quelle dominiert.

## Daten-Pipeline

```
weather_context.py (Tag-Generation)
  ├── Spot Pfad 1 — _build_weather_context (Spot Legacy)
  ├── Spot Pfad 2 — _build_single_spot_context (Per-Spot/Per-Day, neuer)
  └── Region Pfad — _build_single_region_context

  → emittiert Tags pro Stunde (WARN/DANGER) basierend auf 4 Konstanten
  → sammelt aloft_hours / aloft_danger_hours_list (Boden + Höhe vereint)
  → sammelt gust_hours / gust_danger_hours (Boden + Höhe vereint)

_common.py (Trend-Detektion)
  ├── _detect_aloft_trend() → WIND-TREND Pattern + max_calm_gap + ...
  └── _detect_gust_trend() → GUST-TREND Pattern + max_calm_gap + ...
                            (liefert seit Apr 2026 auch pattern_label)

_common.py (Trend-Texte)
  ├── _format_aloft_trend_text() → "WIND-TREND: <Pattern> — Wind (Boden+Hoehe) ..."
  └── _format_gust_trend_text() → "GUST-TREND: <Pattern> — Boeige Stunden ..."

analyzers.py (Override-Logik)
  ├── _post_process_combined_spot()
  │     ├── Wind-Auto-NoGo (DURCHGEHEND_DANGER / EINGEKESSELT < 3h)
  │     ├── Soft-Conditional (aloft_d / aloft_gd ≥ 3h)
  │     └── Boeen-Floor (gwarn/gdanger ≥ 3h → conditional)
  └── _post_process_combined_region()
        └── Wind-Auto-NoGo (analog Spot, ohne Boeen)

skills/shared/_hazard_blocks.md (LLM-Regeln)
  ├── BLOCK 2 — BODENWIND: WIND-TREND-Pflicht, Tags Boden + Region einheitlich
  ├── BLOCK 3 — BOEEN: GUST-TREND-Pflicht, "bevorzugt NoGo" bei DURCHGEHEND_DANGER
  └── BLOCK 4 — HOEHENWIND: WIND-TREND deckt Boden + Höhe gemeinsam ab
```

## Frontend (`static/js/meteogram.js`)

- `deriveDominantTag` produziert die neuen Tag-Namen.
- Aloft-Visual-Schwellen kommen aus `/api/thresholds` (`web.py:1289`) statt hartcodierter
  30/40 km/h. So bleibt das Meteogramm immer mit `config.py` synchron.
- Visual-Labels: "Höhenwind kräftig" (= WARN), "Höhenwind gefährlich" (= DANGER), analog
  für Böen.

## Wann diese Doku updaten?

**MUSS aktualisiert werden bei:**
- Schwellen-Änderung (`WIND_WARN_KMH`, `WIND_DANGER_KMH`, `GUST_WARN_KMH`, `GUST_DANGER_KMH`,
  `WIND_TREND_*_HOURS`, `GUST_TREND_FLOOR_HOURS`).
- Neue/entfernte Wind- oder Böen-Tags.
- Änderung der Override-Logik in `engine/analyzers.py`.
- Änderung der Trend-Detektion (neue Pattern, andere Schwellen für DURCHGEHEND etc.).
- Änderung der Skills-Regeln in `_hazard_blocks.md` BLOCK 2/3/4.
- Wiedereinführung von `ideal_wind_max` oder ähnlichen Spot-spezifischen Limits.

**Memory-Notiz:** `memory/wind_gust_harmonization.md` enthält die Sync-Pflicht.
Bei Änderungen beide Dateien aktualisieren.

**Skills-Sync:** Das System liest Schwellen über `{{cfg.WIND_*_KMH}}` und
`{{cfg.GUST_*_KMH}}` Platzhalter direkt aus `config.py` ein. Skill-Regeln
(z.B. "bevorzugt NoGo bei DURCHGEHEND_DANGER") sind aber in den `.md`-Dateien
hartcodiert und müssen bei Konzept-Änderungen mit angepasst werden.

## Historie

- **Apr 2026 — Phase 1**: Höhenböen aus Auto-NoGo entkoppelt. ALOFT-GUST-DANGER triggert
  keinen automatischen NoGo mehr. Boeen-Floor von `>0` auf `>=3h` angehoben.
- **Apr 2026 — Phase 2**: Konstanten + Tags vereinheitlicht. `WIND_MODERATE_KMH` →
  `WIND_WARN_KMH`, `ALOFT_DANGER_KMH` → `WIND_DANGER_KMH` (gleicher Wert),
  `STRONG-WIND-WARN` → `WIND-DANGER`, `ALOFT-WARN/DANGER` → `ALOFT-WIND-WARN/DANGER`,
  `WIND-MODERATE/STRONG/CALM` → `WIND-WARN/DANGER` (CALM raus).
- **Apr 2026 — Phase 3**: Trend-Logik vereinheitlicht. `HOEHENWIND-TREND` → `WIND-TREND`
  (Boden + Höhe summiert), `BOEEN-TREND` → `GUST-TREND` (war bereits Boden + Höhe).
  `_detect_gust_trend` liefert jetzt `pattern_label`. "Sturmwarnung ganztägig"-Override
  in `analyzers.py:165` entfernt — durch WIND-TREND-Override abgedeckt. Skills BLOCK 2/3/4
  umstrukturiert.
