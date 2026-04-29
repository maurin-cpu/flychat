# Testing — Kosten-Telemetrie & Qualitäts-Regression

**Stand:** 2026-04-29
**Ziel:** Jede LLM-Optimierung messbar machen — Kosten *und* Qualität — bevor sie produktiv geht.

Schwester-Dokument: [`KOSTEN_REDUKTION_KONZEPT.md`](../KOSTEN_REDUKTION_KONZEPT.md) (Hebel & Strategie).

---

## TL;DR

- **`debug_scripts/analyze_once.py`** — Smoke-Lauf: Wetter holen + LLM-Analyse einmal durchziehen. Schreibt `data/cost_telemetry.jsonl`.
- **`debug_scripts/freeze_golden.py`** — friert Cases als Goldstandard ein (Wetter-Input + Output) in `tests/golden/`.
- **`debug_scripts/score_regression.py`** — vergleicht aktuelles Pipeline-Output gegen Goldstandard, gibt PASS/FAIL.
- **Lokal IMMER mit `GLEITCAST_SPOT_CSV=test`** (28 statt 487 Spots → ~$0.50 statt ~$8.70 pro Lauf).

---

## 1. Setup (einmalig pro Shell-Session)

```bash
cd /c/Users/mutsc/Projekte/flychat
export GLEITCAST_SPOT_CSV=test     # 28 Spots statt 487
```

Verifizieren:
```bash
python -c "import config; from spots import load_spots; \
  print('CSV:', config.CSV_PATH.name, 'Spots:', len(load_spots()))"
# Erwartet: CSV: fluggebiete_test.csv  Spots: 28
```

---

## 2. Cost-Telemetrie

### Was sie tut
Pro Analyse-Lauf wird **eine JSONL-Zeile** in `data/cost_telemetry.jsonl` angehängt mit:
- Tokens pro Phase (region_safety, region_fly, spot_safety, spot_fly)
- Cache-Hit-Anteil
- Pre-Filter-Skip-Count
- USD-Schätzung (Preise in `config.MODEL_PRICES`)
- Dauer
- Errors

### Wo sie eingebaut ist
- `engine/_common.py::BatchCostTracker` — Klasse
- `engine/analyzers.py::run_all_analyses_stream` (parallel) + `run_all_analyses_batch_stream` (batch) — Tracker pro Lauf
- `engine/analyzers.py::_record_call_usage` — sammelt Tokens pro Call

### Notbremse (Cost-Cap)
- ENV `LLM_COST_CAP_USD` (default `5.00`)
- Beim Batch-Pfad: nach jeder Phase wird Summe geprüft, bei Überschreitung sauberer Abbruch.

### Auswerten
Trend ansehen:
```bash
cat data/cost_telemetry.jsonl | python -c "
import sys, json
for l in sys.stdin:
    r = json.loads(l)
    print(f\"{r['ts']} {r['mode']:8s} calls={r['total_calls']:4d} \"
          f\"in={r['total_in_tok']:>9,d} out={r['total_out_tok']:>6,d} \"
          f\"cached={r['total_cached_tok']:>9,d} skip={r['prefilter_skipped']:>3d} \"
          f\"\${r['est_usd']:.3f} {r['duration_s']:>5.1f}s\")"
```

---

## 3. Goldstandard-Workflow

### Konzept
Goldstandard friert **Wetter-Input + Output zusammen** ein. Beim späteren Score wird derselbe Wetter-Input wieder durch die Pipeline geschickt — Output-Diff misst rein die **Code-Veränderung**, nicht Wetter-Wechsel.

### Schritt 1 — Daten erzeugen (oder vorhanden lassen)
```bash
python debug_scripts/analyze_once.py
```
- Schritt 1 (Wetter-Refresh): ~3-4 Min lokal, auch mit Cache (Validierung)
- Schritt 2 (LLM-Analyse): ~2-3 Min, ~$0.50
- Schreibt `data/spot_analyses.json`, `data/region_analyses.json`, `data/cost_telemetry.jsonl`

### Schritt 2 — Goldstandard einfrieren
```bash
python debug_scripts/freeze_golden.py --limit 20 --force
```
- Erzeugt `tests/golden/spot_<name>_<datum>.json` (12-20 Files je nach Daten-Vielfalt)
- Ausgewogen: safe / conditional / not_safe / edge
- `--force` überschreibt bestehende Files
- `--dry-run` listet was geschrieben würde, ohne zu schreiben

Inhalt eines Golden-Files:
```json
{
  "spot": "Balderen",
  "date": "2026-04-30",
  "frozen_at": "2026-04-29T11:11:19+00:00",
  "frozen_at_commit": "b46ba27",
  "safety_status": "conditional",
  "input": "<5-7 KB Wetter-Kontext-String>",
  "output": { ...komplettes Analyse-Result... }
}
```

### Schritt 3 — Score-Vergleich

**Schnell-Modus** (kein neuer LLM-Call, aktuelles `spot_analyses.json` vs Golden):
```bash
python debug_scripts/score_regression.py --no-llm \
    --report data/reg_$(date +%F).md
```

**Voller Modus** (eingefrorenen Input durch aktuelle Pipeline schicken — ~$0.05 für 20 Calls):
```bash
python debug_scripts/score_regression.py \
    --report data/reg_$(date +%F).md
```

### Vergleichs-Felder & Schwellen (kalibriert nach gemessener LLM-Jitter)

| Feld | Gewicht | Schwelle | Schwere |
|---|---|---|---|
| `safety_status` | 10 | exakter Match | **kritisch** |
| `flyability_tier` | 10 | exakter Match | **kritisch** |
| `safe_window` | 5 | Stundenüberlappung ≥ 80 % | hoch |
| `rating` | 5 | \|Δ\| ≤ 1.0 | hoch |
| `no_go_reasons` | 3 | Jaccard ≥ 0.7 (sicherheitskritisch streng) | mittel |
| `caution_notes` | 3 | Jaccard ≥ 0.3 (Freitext, Jitter normal) | mittel |
| `streckenflug_tier` | 3 | ≤ 1 Stufe Differenz (top > moderat > lokal > kein_xc) | mittel |

### Acceptance-Gate (Exit-Code 1 wenn verletzt)
- 0 kritische Regressionen
- ≤ 6 hohe Regressionen
- Score ≥ 90 %

### Report lesen
`data/reg_<datum>.md` enthält pro abweichendem Case die genauen Diffs:
```markdown
## Bergstation / 2026-05-01
Score: 36/39

- streckenflug_tier(mittel): gold='top' got='moderat' stufen_diff=1
```

---

## 4. Standard-Test-Loop für eine Optimierung

```bash
export GLEITCAST_SPOT_CSV=test

# 1. Baseline einfrieren (jetzt, vor jeder Änderung)
python debug_scripts/analyze_once.py
python debug_scripts/freeze_golden.py --limit 20 --force

# 2. CHANGE machen — Code, Prompt, Modus, Schwelle, was auch immer

# 3. Neuer Lauf
python debug_scripts/analyze_once.py

# 4. Vergleich
python debug_scripts/score_regression.py --no-llm \
    --report data/reg_change_$(date +%F).md
echo "Exit-Code: $?"
```

- Exit `0` → PASS, Änderung qualitätsneutral, in Produktion ausrollen
- Exit `1` → FAIL, `data/reg_*.md` zeigt welche Felder wandern, Änderung überdenken

---

## 5. Bekannte Befunde aus dem Setup

### a) Parallel-Modus nutzt bereits Skill-Split
Beobachtung aus den Logs: im `parallel`-Modus tauchen Phasen `region_safety`/`region_fly`/`spot_safety`/`spot_fly` auf — *nicht* `spot_combined`. Das heißt: Hebel 1 (Skill-Split) ist auch ohne Modus-Wechsel aktiv. Das `KOSTEN_REDUKTION_KONZEPT.md` war an dieser Stelle ungenau.

Konsequenz: Ein Wechsel von `parallel` auf `batch` bringt **nur den 50 %-Batch-API-Rabatt** — nicht zusätzlich Skill-Split-Effekt. Der Skill-Split ist überall gleich aktiv.

### b) Modus-Schalter sitzt im UI-Overlay
`LLM_ANALYSIS_MODE` wird **nicht** via `.env` gesetzt, sondern via Admin-UI → speichert in `data/config_overrides.json`. Beim App-Start in `main.py:16` ruft `config_overrides.init()` und überschreibt `config.LLM_ANALYSIS_MODE` per `setattr`.

Aktuellen Wert prüfen:
```bash
cat data/config_overrides.json   # falls vorhanden
# falls nicht da: gilt Code-Default "parallel" (config.py:718)
```

### c) Reproduzierbarkeit auf identischer Eingabe
Zwei Läufe mit identischen Daten ohne Code-Änderung ergaben:
- `safety_status` und `flyability_tier`: 100 % identisch ✓
- `rating`: schwankt um ±0.5–0.6 Punkte
- `streckenflug_tier`: ±1 Stufe
- `caution_notes`: ~30 % Text-Überlappung typisch

Das ist normaler `temperature=0.2` LLM-Jitter und nicht-vermeidbar ohne Code-Änderung.

### d) Cost-Datenpunkt (Test-CSV, parallel, gpt-4o-mini)
- 322 Calls (29 Regionen × 5 Tage + 28 Spots × 5 Tage, abzüglich Skips)
- 4.5M Input-Tokens, 108K Output-Tokens
- 66–72 % Cache-Hit (gpt-4o-mini auto-Cache)
- ~$0.50 pro Lauf
- Hochgerechnet auf Complete-CSV (487 Spots): ~$8.70 pro Lauf

---

## 6. Wo wir weitermachen

### Sofort verfügbar (ohne Code-Änderung)
- [ ] Auf dem **Server** prüfen, was `LLM_ANALYSIS_MODE` gerade ist:
  ```bash
  cat data/config_overrides.json | grep LLM_ANALYSIS_MODE
  ```
  Falls `parallel` → in der Admin-UI auf `batch` wechseln (50 % Tokens-Rabatt durch Batch-API).
- [ ] Auf dem Server `python debug_scripts/freeze_golden.py --limit 40` fahren mit der **Complete-CSV** (genug Daten für ein robustes 40-Case-Set). Dann nach jeder Optimierung `score_regression.py --no-llm` als Quality-Gate.

### Tier B — Ersparnis bei niedrigem Risiko
- [ ] **`temperature=0.0` als ENV/Overlay konfigurierbar machen** (Doku: `KOSTEN_REDUKTION_KONZEPT.md` §6 — eigentlich nicht direkt Kosten, aber Test-Determinismus). Implementierung: ~30 Min, in Produktion default `0.2`, in Tests `0.0`.
- [ ] **`max_tokens` pro Phase prüfen**: P95/P99 der `completion_tokens` aus `cost_telemetry.jsonl` ablesen, Limits passend setzen.
- [ ] **Pre-Filter-Regeln erweitern** (`engine/analyzers.py::_prefilter_not_safe`): jede neue Regel mit dem Goldstandard testen.

### Tier C — größerer Hebel mit Quality-Gate
- [ ] **`skills/shared/_hazard_blocks.md` trimmen** (21 KB → ~10 KB). Vor/Nach-Vergleich strikt mit dem Goldstandard. Erwartet 10–15 % Input-Token-Ersparnis pro Safety-Call.
- [ ] **Anthropic Prompt-Cache A/B**: `ANALYSIS_PROVIDER=anthropic` + `cache_control` einbauen, parallel zur OpenAI-Variante. Score-Vergleich entscheidet.

### Tier D — später
- [ ] LLM-as-Judge für `summary`-Freitext-Felder (Konzept §6.3 in `KOSTEN_REDUKTION_KONZEPT.md`)
- [ ] Shadow-Test-Mode für riskantere Hebel (5 % Live-Traffic auf neue Variante, Vergleich nightly)
- [ ] Multi-Provider-Router mit Fallback

---

## 7. Troubleshooting

### `freeze_golden.py` schreibt Cases ohne `input`
→ Wetter-Cache nicht geladen. Skript ruft intern `eng.load_weather_from_cache()` — der lädt aus `data/wetterdaten.json`. Prüfen ob die Datei da und nicht leer.

### `score_regression.py` Exit 2 ("keine Goldstandard-Cases")
→ `tests/golden/` ist leer. Vorher `freeze_golden.py` laufen lassen.

### `score_regression.py` Exit 1 — FAIL nach Code-Änderung
→ `data/reg_*.md` öffnen, pro Case die Diffs ansehen.
- Nur `caution_notes`-Jitter? → akzeptabel, könnte LLM-Drift sein
- `safety_status` / `flyability_tier` gewandert? → echter Quality-Loss, Änderung zurückrollen oder nachjustieren

### Lauf wird zu teuer
→ ENV `LLM_COST_CAP_USD=2.0` setzen, Batch bricht bei Überschreitung sauber ab.

### Lauf hängt im Schritt 1 (Wetterdaten)
→ Open-Meteo / MeteoSwiss-API langsam. Cache existiert? `ls -la data/wetterdaten.json`. Bei kaltem Cache kann Schritt 1 lokal eine Stunde dauern (ca. 28 Spots × ~10 Forecast-Endpoints). Erst-Lauf einmal abwarten, dann ist der Cache warm.

---

## 8. Datei-Übersicht

| Datei | Rolle |
|---|---|
| `debug_scripts/analyze_once.py` | Lokaler Smoke-Lauf (refresh_weather + LLM-Analyse einmal) |
| `debug_scripts/freeze_golden.py` | Goldstandard einfrieren aus `data/spot_analyses.json` + Wetter-Cache |
| `debug_scripts/score_regression.py` | Score-Vergleich aktuell vs Goldstandard, PASS/FAIL |
| `engine/_common.py::BatchCostTracker` | Aggregiert Tokens pro Phase, schreibt JSONL |
| `engine/_common.py::extract_usage_from_response` | Liest Tokens aus OpenAI/Anthropic-Response |
| `engine/analyzers.py::_record_call_usage` | Hook in jedem per-Call zum Tracker reporten |
| `config.py::MODEL_PRICES` | USD/1M-Tokens, zentral pflegen |
| `config.py::LLM_COST_CAP_USD` | Notbremse |
| `config.py::COST_TELEMETRY_PATH` | Output-Pfad JSONL |
| `tests/golden/*.json` | Eingefrorene Cases (gitignored — pro Branch/Server eigenes Set) |
| `data/cost_telemetry.jsonl` | Telemetrie-Trend (gitignored, append-only) |
| `data/reg_*.md` | Regressions-Reports pro Lauf (gitignored) |
| `KOSTEN_REDUKTION_KONZEPT.md` | Übergeordnete Strategie & Hebel |

---

## 9. Letzter Stand der lokalen Sessions

Drei `analyze_once`-Läufe wurden gemacht. Daraus:

- Lauf 1 → Goldstandard 12 Cases eingefroren
- Lauf 2 → Score gegen Golden mit ursprünglichen Schwellen: **91.9 % FAIL** (4 hohe Regressionen, alle aus `temperature=0.2`-Jitter)
- Schwellen kalibriert (rating ≤ 1.0, caution Jaccard ≥ 0.3, streckenflug ±1 Stufe, ≤ 6 hohe Regressionen)
- Re-Score mit kalibrierten Schwellen: **99.4 % PASS** ✓
- 1 verbleibender Diff (Waldrand/2026-04-29: caution_notes Jaccard 0.00) bleibt absichtlich drin als ehrliches Drift-Signal

**Tooling validiert. Bereit für echte Optimierungs-Tests.**
