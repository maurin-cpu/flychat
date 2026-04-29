# Testing — Kosten-Telemetrie & Qualitäts-Regression

**Stand:** 2026-04-29
**Ziel:** Jede LLM-Optimierung messbar machen — Kosten *und* Qualität — bevor sie produktiv geht.

Schwester-Dokument: [`strategie.md`](strategie.md) (Hebel & Strategie).

---

## TL;DR

- **`cost_testing/analyze_once.py`** — Smoke-Lauf: Wetter holen + LLM-Analyse einmal durchziehen. Schreibt `data/cost_telemetry.jsonl`.
- **`cost_testing/freeze_golden.py`** — friert Cases als Goldstandard ein (Wetter-Input + Output) in `cost_testing/golden/`.
- **`cost_testing/score_regression.py`** — vergleicht aktuelles Pipeline-Output gegen Goldstandard, gibt PASS/FAIL.
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
python cost_testing/analyze_once.py
```
- Schritt 1 (Wetter-Refresh): ~3-4 Min lokal, auch mit Cache (Validierung)
- Schritt 2 (LLM-Analyse): ~2-3 Min, ~$0.50
- Schreibt `data/spot_analyses.json`, `data/region_analyses.json`, `data/cost_telemetry.jsonl`

### Schritt 2 — Goldstandard einfrieren
```bash
python cost_testing/freeze_golden.py --limit 20 --force
```
- Erzeugt `cost_testing/golden/spot_<name>_<datum>.json` (12-20 Files je nach Daten-Vielfalt)
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
python cost_testing/score_regression.py --no-llm \
    --report cost_testing/reports/reg_$(date +%F).md
```

**Voller Modus** (eingefrorenen Input durch aktuelle Pipeline schicken — ~$0.05 für 20 Calls):
```bash
python cost_testing/score_regression.py \
    --report cost_testing/reports/reg_$(date +%F).md
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
`cost_testing/reports/reg_<datum>.md` enthält pro abweichendem Case die genauen Diffs:
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
python cost_testing/analyze_once.py
python cost_testing/freeze_golden.py --limit 20 --force

# 2. CHANGE machen — Code, Prompt, Modus, Schwelle, was auch immer

# 3. Neuer Lauf
python cost_testing/analyze_once.py

# 4. Vergleich
python cost_testing/score_regression.py --no-llm \
    --report cost_testing/reports/reg_change_$(date +%F).md
echo "Exit-Code: $?"
```

- Exit `0` → PASS, Änderung qualitätsneutral, in Produktion ausrollen
- Exit `1` → FAIL, `cost_testing/reports/reg_*.md` zeigt welche Felder wandern, Änderung überdenken

---

## 5. Bekannte Befunde aus dem Setup

### a) Parallel-Modus nutzt bereits Skill-Split
Beobachtung aus den Logs: im `parallel`-Modus tauchen Phasen `region_safety`/`region_fly`/`spot_safety`/`spot_fly` auf — *nicht* `spot_combined`. Das heißt: Hebel 1 (Skill-Split) ist auch ohne Modus-Wechsel aktiv. Das `strategie.md` war an dieser Stelle ungenau.

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
- [ ] Auf dem Server `python cost_testing/freeze_golden.py --limit 40` fahren mit der **Complete-CSV** (genug Daten für ein robustes 40-Case-Set). Dann nach jeder Optimierung `score_regression.py --no-llm` als Quality-Gate.

### Tier B — Ersparnis bei niedrigem Risiko
- [ ] **`temperature=0.0` als ENV/Overlay konfigurierbar machen** (Doku: `strategie.md` §6 — eigentlich nicht direkt Kosten, aber Test-Determinismus). Implementierung: ~30 Min, in Produktion default `0.2`, in Tests `0.0`.
- [ ] **`max_tokens` pro Phase prüfen**: P95/P99 der `completion_tokens` aus `cost_telemetry.jsonl` ablesen, Limits passend setzen.
- [ ] **Pre-Filter-Regeln erweitern** (`engine/analyzers.py::_prefilter_not_safe`): jede neue Regel mit dem Goldstandard testen.

### Tier C — größerer Hebel mit Quality-Gate
- [ ] **`skills/shared/_hazard_blocks.md` trimmen** (21 KB → ~10 KB). Vor/Nach-Vergleich strikt mit dem Goldstandard. Erwartet 10–15 % Input-Token-Ersparnis pro Safety-Call.
- [ ] **Anthropic Prompt-Cache A/B**: `ANALYSIS_PROVIDER=anthropic` + `cache_control` einbauen, parallel zur OpenAI-Variante. Score-Vergleich entscheidet.

### Tier D — später
- [ ] LLM-as-Judge für `summary`-Freitext-Felder (Konzept §6.3 in `strategie.md`)
- [ ] Shadow-Test-Mode für riskantere Hebel (5 % Live-Traffic auf neue Variante, Vergleich nightly)
- [ ] Multi-Provider-Router mit Fallback

---

## 7. Troubleshooting

### `freeze_golden.py` schreibt Cases ohne `input`
→ Wetter-Cache nicht geladen. Skript ruft intern `eng.load_weather_from_cache()` — der lädt aus `data/wetterdaten.json`. Prüfen ob die Datei da und nicht leer.

### `score_regression.py` Exit 2 ("keine Goldstandard-Cases")
→ `cost_testing/golden/` ist leer. Vorher `freeze_golden.py` laufen lassen.

### `score_regression.py` Exit 1 — FAIL nach Code-Änderung
→ `cost_testing/reports/reg_*.md` öffnen, pro Case die Diffs ansehen.
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
| `cost_testing/analyze_once.py` | Lokaler Smoke-Lauf (refresh_weather + LLM-Analyse einmal) |
| `cost_testing/freeze_golden.py` | Goldstandard einfrieren aus `data/spot_analyses.json` + Wetter-Cache |
| `cost_testing/score_regression.py` | Score-Vergleich aktuell vs Goldstandard, PASS/FAIL |
| `engine/_common.py::BatchCostTracker` | Aggregiert Tokens pro Phase, schreibt JSONL |
| `engine/_common.py::extract_usage_from_response` | Liest Tokens aus OpenAI/Anthropic-Response |
| `engine/analyzers.py::_record_call_usage` | Hook in jedem per-Call zum Tracker reporten |
| `config.py::MODEL_PRICES` | USD/1M-Tokens, zentral pflegen |
| `config.py::LLM_COST_CAP_USD` | Notbremse |
| `config.py::COST_TELEMETRY_PATH` | Output-Pfad JSONL |
| `cost_testing/golden/*.json` | Eingefrorene Cases (gitignored — pro Branch/Server eigenes Set) |
| `data/cost_telemetry.jsonl` | Telemetrie-Trend (gitignored, append-only) |
| `cost_testing/reports/reg_*.md` | Regressions-Reports pro Lauf (gitignored) |
| `strategie.md` | Übergeordnete Strategie & Hebel |

---

## 9. Letzter Stand der lokalen Sessions

Drei `analyze_once`-Läufe wurden gemacht. Daraus:

- Lauf 1 → Goldstandard 12 Cases eingefroren
- Lauf 2 → Score gegen Golden mit ursprünglichen Schwellen: **91.9 % FAIL** (4 hohe Regressionen, alle aus `temperature=0.2`-Jitter)
- Schwellen kalibriert (rating ≤ 1.0, caution Jaccard ≥ 0.3, streckenflug ±1 Stufe, ≤ 6 hohe Regressionen)
- Re-Score mit kalibrierten Schwellen: **99.4 % PASS** ✓
- 1 verbleibender Diff (Waldrand/2026-04-29: caution_notes Jaccard 0.00) bleibt absichtlich drin als ehrliches Drift-Signal

**Tooling validiert. Bereit für echte Optimierungs-Tests.**

---

## 10. Hebel-Tests vom 2026-04-29

Alle drei in `strategie.md` skizzierten Haupthebel wurden mit Test-CSV (28 Spots) gegen den 12-Case-Goldstandard getestet. Baseline: `parallel + gpt-4o-mini`, Mittel aus 2 Läufen = **$0.5125 / 158 s / 322 Calls**.

### Ergebnis-Übersicht

| Hebel | Effekt USD | Effekt Dauer | Quality | Empfehlung |
|---|---|---|---|---|
| 1 — Batch-API | nicht messbar (Lauf hängengeblieben) | Lauf > 53 Min ohne Verarbeitung | n/a | nachts wiederholen |
| 2 — Trim Hazard-Blocks (21 KB → 16.5 KB) | **+8 %** ($0.5548) | +32 % (208 s) | **FAIL** 4 krit. | abhaken |
| 3 — Provider-Wechsel zu Gemini Flash Lite | **-31 %** ($0.3533) | +98 % (314 s) | **FAIL** 5 krit. + 6 hohe + 1 `error`-State | nicht produktiv |

### Hebel 1 — OpenAI Batch-API

- ENV `LLM_ANALYSIS_MODE=batch` setzen reicht — keine Code-Änderung nötig
- Lauf am Nachmittag eingereicht: 4 Batches sequenziell (region_safety/region_fly/spot_safety/spot_fly)
- Batch 1 (Region-Safety, 145 Requests) hing **53 Min in OpenAI-Queue mit 0/145 verarbeitet**, dann manuell abgebrochen + via API gecancelled
- Cache-Discount stapelt sich auf Batch-Discount → theoretisch ~50 % USD-Ersparnis bei freiem Queue-Window
- **Vermutung:** US-Bürozeiten überlasten Free/Standard-Tier-Queue. Nächtlicher Cron könnte zuverlässig laufen.
- Action: separater nächtlicher Test, keine Tagesversuche mehr

### Hebel 2 — Hazard-Blocks-Datei trimmen

- `skills/shared/_hazard_blocks.md` von 20'909 → 16'517 Bytes (-21 %) durch Tabellen-Konsolidierung von TREND-VOKABULAR + EINGEKESSELT-Sonderfällen
- Sicherheits-Schwellen (cfg-Variablen, GROUNDING-REGEL, BÖEN-FLOOR, EINGEKESSELT-Logik) blieben 1:1 erhalten
- **Quality-Drift trotzdem signifikant:** safety_status wanderte für Hummel 05-01 (safe→conditional), Tisch 05-01 (conditional→safe — *zu nachsichtig, gefährlich*), Weissenstein 05-01 (conditional→not_safe + flyability verloren)
- **USD-Effekt sogar negativ:** mehr Total-Calls (345 vs 321), Cache-Hit fiel von 69 % → 61 % (Skill-Datei Cache-invalidiert), Lauf wurde 50 s länger
- **Lehre:** Cache dominiert die Kosten. Strukturelle Änderung am System-Prompt verschiebt sowohl Cache-Hit als auch LLM-Verhalten. Trim-Hebel ist nicht trivial.
- Datei wurde rückgerollt (`git checkout`)

### Hebel 3 — Provider-Wechsel zu Gemini Flash Lite

- Anthropic Haiku 4.5 wurde *vor* dem Test rechnerisch ausgeschlossen: Basispreise 7× Input / 8× Output gegen gpt-4o-mini → auch mit 90 %-Cache-Rabatt **4× teurer als Baseline**
- Gemini 2.5 Flash Lite ist in `MODEL_PRICES` mit $0.10/M in / $0.025/M cached / $0.40/M out → -50 % theoretisch
- `llm_client.py` hat funktionierenden Gemini-Adapter — nur ENV `ANALYSIS_PROVIDER=gemini` + `GEMINI_API_KEY` in `.env` nötig
- **Real gemessen: -31 %** (cached_pct fiel von 69 % auf 63 %, mehr Output-Tokens 177k vs 109k)
- **Häufige 503-Errors** ("model experiencing high demand") — Retries fingen sie ab, verdoppelten aber Laufzeit auf 314 s
- Quality: 5 kritische Regressionen, dazu **1 hartes `error` an Bergstation 05-01** (vermutlich JSON-Parse-Fehler im Adapter)
- **Pattern:** Tisch und Weissenstein wandern bei JEDEM Modell-/Prompt-Wechsel — sind echte Edge-Cases, nicht Zufalls-Jitter
- Action: nicht produktiv setzen

### Lehren

1. **Kostenstruktur ist cache-dominiert.** Bei 69 % Cache-Hit auf gpt-4o-mini sind 73 % der Input-Kosten gecacht abgerechnet. Trim-Hebel verlieren dadurch viel ihrer rechnerischen Wirkung — *und* die Strukturänderung killt obendrein den Cache.
2. **Modellwechsel = echte Quality-Drift.** Auch bei "äquivalenten" Light-Modellen verschieben sich safety_status-Schwellen, vor allem an Edge-Cases. Goldstandard fängt das zuverlässig ab — ohne den hätten wir es nicht gesehen.
3. **Batch-API ist potenziell der größte Hebel,** aber nur wenn die Queue-Latenz im Cron-Window passt. Tests zu Bürozeiten sind Verschwendung.
4. **`error`-State im Score-Report war hilfreich** — wird ohne Goldstandard nicht erkannt, weil produktiv nur "es lief halt 1 Spot weniger" auffällt.

### Nächste Schritte

- [ ] Nächtlicher Batch-Test (Hebel 1) via Server-Cron um 03:00. Wenn Queue durchläuft → produktiv schalten.
- [ ] Tier-B-Hebel aus §6 (max_tokens-Tuning, Pre-Filter-Erweiterung) sind weiterhin offen und risikoarm.
- [ ] Goldstandard sollte vor produktiven Skill-Edits standardmässig durchlaufen — speziell bei `_hazard_blocks.md`.
