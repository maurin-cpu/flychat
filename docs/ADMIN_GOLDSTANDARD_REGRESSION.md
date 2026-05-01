# Goldstandard & Regression — Admin-Sektion 4

Dieses Dokument beschreibt im Detail die Sektion **„4. Goldstandard & Regression"** auf
`/admin/testing`. Die Sektion ist ein UI-Wrapper um die bestehenden CLI-Tools
`cost_testing/freeze_golden.py` und `cost_testing/score_regression.py` und ermöglicht
es, qualitätsregressionen am LLM-Stack ohne Terminal-Zugriff zu erkennen.

---

## 1. Wofür gibt es das?

Das LLM (gpt-4o-mini, gemini-flash, claude-haiku, deepseek) ist nichtdeterministisch:
selbst bei `temperature=0.2` schwanken einzelne Felder leicht zwischen Läufen
(z. B. `rating` ±0.5, `caution_notes` Jaccard ~0.3). Wenn man einen **Hebel** ziehen will
— Modell wechseln, Prompt kürzen, Pre-Filter erweitern, Provider tauschen — muss man
sicher sein, dass die Qualität nicht einbricht.

**Goldstandard-Workflow:**

1. **Einfrieren** — eine repräsentative Stichprobe (~20 Cases) der aktuellen Live-Analysen wird als „Wahrheit" weggelegt: Spot, Datum, exakter Wetter-Input, exaktes LLM-Output.
2. **Hebel ziehen** — Code/Prompt/Modell ändern.
3. **Regression** — neue Pipeline gegen die eingefrorene Wahrheit fahren, gewichteten Score + harte Acceptance-Schwellen prüfen.
4. **PASS** → Hebel akzeptieren. **FAIL** → zurückrollen oder verfeinern.

Die Schwellen sind **kalibriert auf die natürliche LLM-Jitter** (siehe
`score_regression.py` Kopfkommentar). Ein PASS-Score von 99,4 % bei zwei aufeinander
folgenden Läufen ohne Code-Änderung wurde gemessen und als untere Vertrauensgrenze
verwendet.

---

## 2. Workflow im Überblick

```
                    ┌─────────────────────────────────────┐
                    │   Live-Analyse läuft (täglich)      │
                    │   → data/spot_analyses.json         │
                    │   → data/wetterdaten.json (Input)   │
                    └────────────────┬────────────────────┘
                                     │
                                     ▼
                    ┌─────────────────────────────────────┐
                    │   Goldstandard einfrieren           │
                    │   freeze_golden.py --limit 20       │
                    │   → cost_testing/golden/spot_*.json │
                    │      (Spot + Date + Input + Output) │
                    └────────────────┬────────────────────┘
                                     │
                          ─── Hebel ziehen ───
                                     │
                                     ▼
                    ┌─────────────────────────────────────┐
                    │   Regression starten                │
                    │   score_regression.py [--no-llm]    │
                    │   → cost_testing/reports/*.md       │
                    └────────────────┬────────────────────┘
                                     │
                       ┌─────────────┴─────────────┐
                       ▼                           ▼
                    PASS (Exit 0)              FAIL (Exit 1)
                Hebel akzeptieren        Zurückrollen / verfeinern
```

---

## 3. UI-Sektion 4 — Bedienung

### 3.1 Status-Header

```
Cases im Goldstandard
12 (juengster Case: 2026-04-29T13:52:48)
```

- **Cases** — Anzahl `.json`-Dateien in `cost_testing/golden/`. Jeder Case ist
  ein eingefrorenes (Spot, Datum, Input, Output)-Tupel.
- **Juengster Case** — Modification-Time der zuletzt geschriebenen Goldstandard-Datei.
  Wenn dieser Wert älter als 1–2 Wochen ist und Code-Änderungen liefen, neu einfrieren.

### 3.2 Goldstandard einfrieren (linke Karte)

| Feld                            | Wirkung                                                                                        |
| ------------------------------- | ---------------------------------------------------------------------------------------------- |
| **Limit**                       | Maximale Anzahl Cases, die eingefroren werden. Default 20, sinnvoll 10–40. Mehr = robuster, aber teurer im Regression-Lauf. |
| **bestehende Cases ueberschreiben** (Force) | Wenn aktiv: vorhandene `spot_<name>_<date>.json` werden ersetzt. Sonst nur neu fehlende. |
| **`freeze_golden.py` ausfuehren** | Subprocess-Call, Timeout 180 s. Synchron — UI bleibt geblockt bis fertig.                     |

**Was technisch passiert:**

1. Lädt aktuell gecachte `data/spot_analyses.json` und passende Wetterdaten.
2. Wendet `_select_balanced(rows, limit)` an: sucht eine ausgewogene Mischung aus
   `safe`, `conditional`, `not_safe`, Edge-Cases (Föhn-Risiko, conditional_reason),
   plus Random-Rest. Rationale in `freeze_golden.py:_select_balanced`.
3. Pro selektierten Case schreibt eine Datei `cost_testing/golden/spot_<name>_<date>.json`
   mit folgendem Schema:

   ```json
   {
     "spot": "Balderen",
     "date": "2026-04-30",
     "frozen_at": "2026-04-30T...Z",
     "frozen_at_commit": "<git sha>",
     "input": "<weather_context_str — exakt wie an LLM uebergeben>",
     "output": { ... komplettes Analyse-Result aus spot_analyses.json ... }
   }
   ```

4. **Wichtig**: Goldstandard liest die **Live**-Analysen, nicht die Test-Run-Analysen.
   Vor dem Einfrieren also entweder warten bis der Daily-Scheduler frisch gelaufen ist,
   oder manuell `engine.refresh_weather()` + Live-Analyse triggern.

**Force vs. nicht-Force:**

- `--force` erst nutzen, wenn Felder am Goldstandard-Schema selber geändert wurden,
  oder wenn das alte Set fundamental veraltet ist (Modell-Wechsel, Prompt-Rewrite).
- Sonst läuft man Gefahr, den Score gegen sich selbst zu kalibrieren — der Hebel,
  den man eigentlich messen will, schlägt sich dann gleich im Goldstandard nieder.

### 3.3 Regression starten (rechte Karte)

| Feld                          | Wirkung                                                                                         |
| ----------------------------- | ----------------------------------------------------------------------------------------------- |
| **Modus: `--no-llm`**         | Vergleicht **aktuelle `data/spot_analyses.json`** gegen Golden. Kein LLM-Call, sehr schnell (~5–30 s). Default. |
| **Modus: mit LLM**            | Sendet den **gespeicherten Input** des Goldens an den **aktuellen** LLM-Stack und vergleicht den **frischen Output** gegen den eingefrorenen. Langsam (mehrere Min, 1 Call pro Case), kostet Tokens. |
| **Max Cases**                 | Begrenzt auf die ersten N Cases. 0 = alle. Sinnvoll bei `mit-LLM` für schnelle Stichproben.       |
| **`score_regression.py` ausfuehren** | Subprocess-Call, Timeout 180 s im no-llm-Modus, 1500 s mit-LLM. Synchron.               |

**Wann welchen Modus?**

- **`--no-llm`** — Smoke-Test: hat sich die *deterministische* Pipeline geändert
  (Pre-Filter, Decision-Engine, Pre-/Post-Processing)? Diff = Code-Bug.
- **`mit LLM`** — Echter Hebel-Test: hat sich die *LLM-Antwort* geändert?
  Diff = Prompt/Modell-Effekt. Hier zählt jeder Cent — Test-Set so klein wie möglich
  halten.

### 3.4 Letzte Reports (Liste)

- Liste der jüngsten 15 Markdown-Reports aus `cost_testing/reports/`.
- Klick auf Dateinamen → öffnet `/admin/testing/reports/<name>` mit pre-formatted
  Markdown-Inhalt.
- Anzeige pro Eintrag: `<name> · <mtime> · <size> · <erste Zeile>`.
- Path-Traversal ist serverseitig blockiert (`engine.test_mode.read_report` filtert
  `Path(name).name`).

---

## 4. Vergleichs-Felder & Schwellen

`score_regression.py` vergleicht 7 Felder pro Case mit verschiedenen Schwellen.
Die Schwellen sind kalibriert über zwei aufeinanderfolgende Läufe **ohne Code-Änderung**
— alles unterhalb einer Schwelle ist „echte Regression", alles darüber ist „LLM-Jitter".

| Feld                | Severity   | Gewicht | Kriterium                                       |
| ------------------- | ---------- | ------- | ----------------------------------------------- |
| `safety_status`     | kritisch   | 10      | Exakter Match (`safe`/`conditional`/`not_safe`) |
| `flyability_tier`   | kritisch   | 10      | Exakter Match                                   |
| `safe_window`       | hoch       | 5       | Stundenüberlappung ≥ 80 %                       |
| `rating`            | hoch       | 5       | `|delta|` ≤ 1.0 (gemessener Jitter bis 0.6)     |
| `no_go_reasons`     | mittel     | 3       | Jaccard ≥ 0.7 (sicherheitskritisch, streng)     |
| `caution_notes`     | mittel     | 3       | Jaccard ≥ 0.3 (Freitext, Jitter normal)         |
| `streckenflug.tier` | mittel     | 3       | Differenz ≤ 1 Stufe in `top > moderat > lokal > kein_xc` |

**Maximaler Score pro Case:** 39 Punkte.
**Bei 20 Cases:** Max 780 Punkte.

### Acceptance-Gate (Exit-Code)

Das Skript exited mit `0` (PASS) **nur wenn alle drei Bedingungen** erfüllt sind:

1. **0 kritische Regressionen** — kein einziger Case mit falschem `safety_status`
   oder `flyability_tier`. Diese Felder steuern direkt UI-Farben und Briefing-Text;
   eine Inversion (z. B. ein not_safe-Tag wird zu safe) ist sicherheitskritisch.
2. **≤ 6 hohe Regressionen** — `safe_window` und `rating` dürfen in Summe maximal
   6× über alle Cases regredieren. Bei 20 Cases sind das 30 mögliche Slots, also
   ≤ 20 % Drift wird toleriert.
3. **Gewichteter Score ≥ 90 %** — Summe `case_score / case_max` ≥ 0.90.

Wird auch nur eine Bedingung verletzt, exited mit `1` (FAIL).

---

## 5. Report-Format

Jeder Report ist eine Markdown-Datei in `cost_testing/reports/`. Schema:

```markdown
# Regression-Report — 2026-04-29T14:51:07+00:00

- Cases: 12
- Score: 461/468 (98.5%)
- Kritische Regressionen: 0
- Hohe Regressionen: 1

## Balderen / 2026-04-30
Score: 33/39

- rating(hoch): |delta|=1.50
- caution_notes(mittel): jaccard=0.25 ...

## Brunnihütte / 2026-05-01
Score: 36/39

- safe_window(hoch): overlap=72% gold=[8,9,10,11,12] got=[9,10,11,12,13]
```

Jeder Case mit Diffs hat eine `## Spot / Date`-Sektion mit den genauen Fail-Reasons.
Erfolgreiche Cases (kein Diff) tauchen nicht im Report auf.

---

## 6. Empfohlener Hebel-Test-Loop

Wenn du z.B. den **Provider von OpenAI auf Gemini wechseln** willst:

```
1. Aktuelle Live-Analyse läuft sauber durch (data/spot_analyses.json frisch).

2. Sektion 4 → "freeze_golden.py ausfuehren"
   Limit: 20, Force: aus
   → cost_testing/golden/ enthält 20 OpenAI-Wahrheits-Cases.

3. Baseline absichern:
   Sektion 4 → "score_regression.py ausfuehren"
   Modus: --no-llm
   → muss PASS sein (Score nahe 100 %, weil Cache identisch zum Golden).
   Wenn nicht, ist deine Pipeline schon kaputt — Hebel nicht ziehen.

4. Hebel ziehen — /admin/config → ANALYSIS_PROVIDER auf gemini.

5. Test-Lauf in Sektion 3 starten (Frozen Snapshot, 28 Spots).
   → data/test_runs/latest/ wird mit gemini-Outputs befüllt.

6. ⚠️ Achtung: --no-llm vergleicht Live-Analysen, nicht test_runs.
   Für ehrlichen Vergleich: "Modus mit LLM" — score_regression.py sendet
   den Goldstandard-Input an den NEUEN gemini-Stack und vergleicht.

7. Reports öffnen, Drift bewerten:
   - PASS → Hebel akzeptieren, Goldstandard mit gemini neu einfrieren.
   - FAIL → Provider zurück auf openai, Bug analysieren.
```

---

## 7. Beispiel-Reports interpretieren

Aus deinem aktuellen Bestand:

| Report                  | Bedeutung                                                                               |
| ----------------------- | --------------------------------------------------------------------------------------- |
| `reg_repro.md`          | Reproduzierbarkeits-Test: zwei Läufe ohne Änderung. Drift = LLM-Jitter, dient als Baseline. |
| `reg_sanity.md`         | Smoke-Test mit `--no-llm`. Score muss nahe 100 % sein, sonst ist die Decision-Engine kaputt. |
| `reg_calibrated.md`     | Endgültiger Lauf nach Schwellen-Kalibrierung. 99.4 % PASS — Tooling validiert.          |
| `reg_hebel2.md`         | Erster Hebel angewandt (z. B. Prompt-Trimming, Mode-Wechsel parallel/batch).             |
| `reg_hebel3_gemini.md`  | Provider-Wechsel auf Gemini. Hier interessant: ist die Qualität noch im Rahmen?         |

---

## 8. Troubleshooting

### „FEHLER: data/spot_analyses.json nicht vorhanden"

Goldstandard kann nur aus aktuellen Live-Analysen einfrieren. Erst Daily-Scheduler
laufen lassen oder `engine.refresh_weather()` + Live-Analyse manuell triggern.

### „WARN: Keine Wetterdaten geladen — Input wird leer sein"

Die `wetterdaten.json` fehlt oder ist veraltet. Der Goldstandard friert dann nur
das *Output* ein, der *Input* wird leer. Das entwertet den `mit-LLM`-Modus, weil
keine Eingabe an die Pipeline geschickt werden kann. Erst Wetter-Cache
aktualisieren.

### „Acceptance-Gate: FAIL" obwohl Code nicht geändert

Wahrscheinlich LLM-Jitter über die Toleranzschwellen hinaus. Mehrmals laufen lassen,
falls konsistent → echte Regression suchen. Falls nicht reproduzierbar → ggf.
`max-cases` erhöhen für stabilere Statistik, oder Goldstandard mit `--force`
neu einfrieren.

### Subprocess-Timeout

- `--no-llm`: 180 s sollten reichen (vergleicht nur Cache).
- `mit-LLM`: 1500 s = 25 Min. Bei großem Goldstandard (40+ Cases) mit langsamem
  Provider (Anthropic) kann es eng werden. Im Notfall: `Max Cases` reduzieren.

### Path-Traversal bei Report-View

Reports werden über `Path(name).name` validiert — nur Dateinamen ohne Pfad-Komponenten,
nur `.md`-Endung. Versuche wie `../../etc/passwd` werfen 404, nicht 500.

---

## 9. Datei-/Pfad-Übersicht

| Pfad                                                | Inhalt                                                       |
| --------------------------------------------------- | ------------------------------------------------------------ |
| `cost_testing/freeze_golden.py`                     | CLI: Goldstandard einfrieren                                 |
| `cost_testing/score_regression.py`                  | CLI: Regression-Score                                        |
| `cost_testing/golden/spot_<name>_<date>.json`       | Eingefrorene Cases                                           |
| `cost_testing/reports/reg_*.md`                     | Regression-Reports                                           |
| `engine/test_mode.py::FREEZE_GOLDEN_SCRIPT`         | UI-Subprocess-Wrapper                                        |
| `engine/test_mode.py::list_reports()`               | Liest Reports-Liste für Sektion 4                            |
| `engine/test_mode.py::read_report()`                | Path-Traversal-sicherer Reader                               |
| `web.py::/admin/testing/freeze-golden`              | UI-Endpoint Goldstandard einfrieren                          |
| `web.py::/admin/testing/run-regression`             | UI-Endpoint Regression starten                               |
| `web.py::/admin/testing/reports/<name>`             | UI-Endpoint Report-Renderer                                  |
| `templates/admin/testing.html` (Sektion 4)          | UI-Markup                                                    |
| `templates/admin/testing_report.html`               | Markdown-Render-Template                                     |

---

## 10. Was die Sektion **nicht** kann (bewusst)

- **Keine Async-Ausführung** — beide Subprocess-Calls laufen synchron, der HTTP-Request
  blockiert bis fertig. Bei `mit-LLM` über 25 Min kann der Browser timeouten. Lösung
  bei Bedarf: SSE-Stream wie für die Test-Analyse in Sektion 3.
- **Kein automatisches Re-Freezing** nach PASS. Bewusst — das soll man manuell
  bestätigen, sonst kalibriert man den Test gegen sich selbst.
- **Keine LLM-as-Judge** für die Freitext-Felder (`summary`, `recommendation`).
  Caution-Notes werden via Jaccard verglichen — ein semantisch identisches
  Re-Phrasing wird trotzdem als Diff gewertet. Toleranz bewusst auf 0.3 gesetzt.
- **Keine Per-Provider-Goldstandards.** Wer Provider regelmäßig wechselt, muss
  vor jedem Wechsel einen passenden Goldstandard bereitstellen.
