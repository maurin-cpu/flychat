# Weitermachen — LLM-Kosten/Qualität-Optimierung

**Letzte Session:** 2026-04-29 — Tooling fertig & validiert. Bereit für echte Optimierungs-Hebel.

> **Für Claude in neuer Session:** Dies ist der Wiedereinstiegspunkt für die laufende Arbeit am LLM-Kostenproblem. Volldoku in [`doku.md`](doku.md), Strategie in [`strategie.md`](strategie.md).

---

## Sofort-Setup (jede neue Shell)

```bash
cd /c/Users/mutsc/Projekte/flychat
export GLEITCAST_SPOT_CSV=test     # 28 Spots, ~$0.50/Lauf statt 487/$8.70
```

Verifizieren:
```bash
python -c "import config; from spots import load_spots; print(config.CSV_PATH.name, len(load_spots()))"
# Erwartet: fluggebiete_test.csv 28
```

---

## Was fertig ist (eingebaut & getestet)

| | Datei |
|---|---|
| Cost-Telemetrie pro Lauf | `engine/_common.py::BatchCostTracker`, `engine/analyzers.py` |
| Cost-Cap Notbremse | `config.LLM_COST_CAP_USD` (default 5.00) |
| Modell-Preise | `config.MODEL_PRICES` (7 Modelle) |
| Smoke-Lauf | `cost_testing/analyze_once.py` |
| Goldstandard einfrieren | `cost_testing/freeze_golden.py` |
| Regression-Score (kalibriert) | `cost_testing/score_regression.py` |
| Konzept-Doku | `strategie.md` (Status §5, Quality §6, Cost §7) |
| Test-Doku | `doku.md` |

**Validierungs-Stand:** 2 lokale Läufe gemacht, Score-Schwellen an gemessenen LLM-Jitter angepasst → Re-Run mit kalibrierten Schwellen ergab **99.4 % PASS**. Tooling ist ehrlich.

**Lokale Daten vorhanden:**
- `data/wetterdaten.json` (warm)
- `data/spot_analyses.json` (Lauf 2)
- `data/cost_telemetry.jsonl` (2 Zeilen)
- `cost_testing/golden/*.json` (12 Cases)

---

## Wichtige Befunde aus der Session

1. **Parallel-Modus nutzt bereits den Skill-Split** — Phasen `region_safety`/`region_fly`/`spot_safety`/`spot_fly` (nicht `*_combined`). Hebel 1 ist unabhängig vom Modus aktiv. Konzept-Doku korrigiert.

2. **`OPENAI_ANALYSIS_MODE` wird via UI-Overlay gesteuert**, nicht via `.env`. Speicherort: `data/config_overrides.json`. Beim App-Start ruft `main.py:16` `config_overrides.init()` und überschreibt `config`-Werte per `setattr`. ENV ist nur Fallback-Default.

3. **LLM-Jitter bei `temperature=0.2`** ist real:
   - `safety_status`/`flyability_tier` reproduzieren zu 100 %
   - `rating` schwankt um ±0.5–0.6 Punkte
   - `streckenflug_tier` schwankt ±1 Stufe
   - `caution_notes` Jaccard ~30 % typisch
   Schwellen sind danach kalibriert (siehe `score_regression.py` Kopfkommentar).

4. **Cost-Datenpunkt** (Test-CSV, parallel, gpt-4o-mini): 322 Calls, 4.5M In-Tokens, 72 % Cache-Hit, **$0.50/Lauf, 2.5 Min**.

---

## Nächste Schritte (in dieser Reihenfolge)

### Auf dem Server prüfen (5 Min)
- [ ] `cat data/config_overrides.json` → was steht bei `OPENAI_ANALYSIS_MODE`?
- [ ] Falls `parallel` → Admin-UI öffnen → "LLM-Analyse" auf `batch` → Save → restart Service
- [ ] Erwarteter Effekt: nächster Produktionslauf ~50 % günstiger durch Batch-API-Rabatt

### Auf dem Server Goldstandard erzeugen (10 Min)
- [ ] `python cost_testing/freeze_golden.py --limit 40` (mit Complete-CSV → mehr Variation)
- [ ] Sanity: `python cost_testing/score_regression.py --no-llm` → muss PASS sein

### Tier B — moderate Hebel mit Quality-Gate
- [ ] **`temperature` konfigurierbar machen** (~30 Min Code)
  - In `analyzers.py`: `temperature=getattr(config, 'LLM_TEMPERATURE', 0.2)`
  - In `config.py`: `LLM_TEMPERATURE = float(os.environ.get('LLM_TEMPERATURE', '0.2'))`
  - In `config_overrides.py` SCHEMA: float-Schema-Eintrag für UI-Steuerung
  - Tests können dann mit `LLM_TEMPERATURE=0.0` deterministisch laufen, Produktion bleibt 0.2
- [ ] **`max_tokens` tunen**: P95/P99 der `completion_tokens` aus `data/cost_telemetry.jsonl` ablesen, Limits in `analyzers.py` (Zeilen mit `max_tokens=`) anpassen
- [ ] **Pre-Filter-Regeln erweitern** (`engine/analyzers.py::_prefilter_not_safe`): jede neue Regel auf Goldstandard testen, z.B.:
  - Aloft-Wind > 50 km/h ganztägig → not_safe
  - CAPE > 1500 J/kg über > 4h → not_safe
  - Bewölkung 100 % low+mid > 6h → not_safe
  - Foehn-Sturm-Indikatoren über harten Schwellen

### Tier C — größter verbleibender Hebel (mit striktem Quality-Gate!)
- [ ] **`skills/shared/_hazard_blocks.md` trimmen** (21 KB → ~10 KB)
  - Erklärtexte raus, harte Schwellen behalten
  - Quality-Gate **muss** PASS bleiben — sonst zurückrollen
  - Erwartung: 10–15 % Input-Token-Ersparnis pro Safety-Call
- [ ] **Anthropic Prompt-Cache A/B**: `ANALYSIS_PROVIDER=anthropic` mit `cache_control` testen, Score-Vergleich

### Tier D — später / langfristig
- [ ] LLM-as-Judge für `summary`-Freitext (siehe Konzept §6.3)
- [ ] Shadow-Test-Mode (5 % Live-Traffic auf neue Variante, nightly-Vergleich)
- [ ] Multi-Provider-Router mit Fallback

---

## Standard-Test-Loop (Copy-Paste)

```bash
export GLEITCAST_SPOT_CSV=test

# Baseline einfrieren (vor Änderung)
python cost_testing/analyze_once.py
python cost_testing/freeze_golden.py --limit 20 --force

# CHANGE machen — Code, Prompt, Modus, ...

# Vergleichs-Lauf
python cost_testing/analyze_once.py
python cost_testing/score_regression.py --no-llm \
    --report cost_testing/reports/reg_change_$(date +%F).md
echo "Exit-Code: $?"   # 0 = PASS, 1 = FAIL
```

---

## Bei Problemen

- Detailliertes Troubleshooting in `doku.md` §7
- Konzept-Strategie in `strategie.md`
