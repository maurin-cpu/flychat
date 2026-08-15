# GPT-5.6 Luna vs. DeepSeek V4 Flash — lohnt der Wechsel?

**Stand:** 15.08.2026 · **Anlass:** DeepSeek erhöht am 16.08.2026 die Preise ·
**Rechner:** `python cost_testing/compare_models.py`

---

## Antwort in drei Sätzen

1. **Heute** ist Luna **nicht** günstiger: $7.76 vs. $3.75 pro Lauf — Lunas
   Output-Preis ist 4.3× der von DeepSeek, und unser Workload ist zwar
   input-lastig, aber nicht input-*only*.
2. **Ab morgen** dreht sich das: DeepSeek off-peak landet bei ~$6.87, Luna
   **im Batch-Modus** bei $3.88 — dann ist Luna die günstigste Option und
   gleichzeitig das stärkere Modell.
3. Der Hebel ist nicht das Modell, sondern die **Batch-API**: die hat OpenAI,
   DeepSeek nicht. Ohne Batch ist Luna auch nach der Erhöhung teurer als
   DeepSeek off-peak.

---

## 1. Preise (USD pro 1M Token)

| Modell | Input | Cache-Hit | Output | Batch |
|---|---|---|---|---|
| `deepseek-v4-flash` — bis 16.08. 15:59 UTC | 0.140 | 0.0028 | 0.280 | keine Batch-API |
| `deepseek-v4-flash` — ab 16.08. 16:00 UTC, **off-peak** | ~0.213 | ~0.017 | **0.66** | — |
| `deepseek-v4-flash` — ab 16.08. 16:00 UTC, **peak** | ~0.426 | ~0.034 | **1.32** | — |
| `gpt-5.6-luna` | 0.200 | 0.020 | 1.200 | −50 %, stapelt mit Cache |

**Belegt** sind: alle Luna-Werte (OpenAI-Doku, mehrfach bestätigt, Preissenkung
um 80 % am 30.07.2026), die heutigen DeepSeek-Werte (`config.MODEL_PRICES`,
verifiziert 27.07.), das Umstellungsdatum 16.08. 16:00 UTC und der
Output-Peak-Preis $1.32 (Fortune, 13.08.).

**Geschätzt** sind die kursiven DeepSeek-Input- und Cache-Werte: DeepSeek hat sie
offiziell noch nicht publiziert. Sie sind aus einer Sekundärquelle abgeleitet, die
den geblendeten Aufschlag mit **1.96× Input, 2.94× Output, 7.84× Cache-Read**
angibt — bei Peak-Fenstern von 7 h/Tag und Off-Peak = halber Peak-Preis ergibt das
die Tabelle oben. Der so rückgerechnete Output-Peak ($1.28) trifft den belegten
Wert ($1.32) auf 3 % genau, was die Ableitung plausibel macht — **belegt ist sie
damit nicht**. `config.MODEL_PRICES` bleibt deshalb bis zur offiziellen Preisseite
auf den alten DeepSeek-Werten stehen.

> Der bitterste Posten ist nicht Output, sondern der **Cache-Read: ~7.8×**. Wir
> fahren 72 % Cache-Hit — genau der Rabatt, auf dem unsere Kalkulation ruht,
> schrumpft am stärksten.

## 2. Rechenprofil

Ein voller Lauf über die Complete-CSV (487 Spots), hochgerechnet aus dem
gemessenen Test-CSV-Lauf (`cost_testing/doku.md` §d):
**78.3M Input-Token, 1.88M Output-Token, 72 % Cache-Hit.**

Gegenprobe: dasselbe Profil ergibt für `gpt-4o-mini` $8.64 — die dokumentierte
Messung sagt ~$8.70. Das Profil trägt.

## 3. Ergebnis (30 Läufe/Monat)

| Variante | $/Lauf | $/Monat |
|---|---|---|
| `deepseek-v4-flash` heute | **3.75** | 113 |
| `gpt-5.6-luna` **Batch** | **3.88** | 116 |
| `gemini-2.5-flash-lite` | 4.35 | 131 |
| `deepseek-v4-flash` neu, off-peak | 6.87 | 206 |
| `gpt-5.6-luna` parallel | 7.76 | 233 |
| `deepseek-v4-flash` neu, peak | 13.73 | 412 |

## 4. Qualität — „gleiche Power" ist zu bescheiden

Luna ist auf den öffentlichen Benchmarks **besser**, nicht gleich: DeepSWE pass@1
67.2 % vs. 53.3 % für V4 Flash. In einem SaaS-Tool-Use-Test 5/12 vs. 4/12 Tasks.
Für unsere Aufgabe (strukturiertes JSON aus einem grossen Wetterkontext) sagt das
wenig — die Entscheidung fällt am `score_regression.py`-Gate, nicht am Benchmark.

## 5. Drei Vorbehalte, die die Rechnung kippen können

1. **Reasoning-Tokens.** Luna fährt `reasoning.effort` per Default auf `medium`,
   und Reasoning-Token werden **als Output** abgerechnet. Die $3.88 gelten nur mit
   `effort: "none"`/`"low"`. Dafür fehlt der Schalter — nötig wäre ein
   OpenAI-Pendant zu `deepseek_thinking_kwargs()` (`engine/_common.py:404`),
   angesteuert analog zu `config.DEEPSEEK_DISABLE_THINKING`. Ohne diesen Schalter
   ist ein Wechsel eine Wette, keine Ersparnis.
2. **Batch-Latenz.** Der Batch-Pfad läuft in vier sequenziellen Phasen
   (`engine/analyzers.py`, `batch_poll_*`). OpenAI garantiert 24 h, typisch sind
   5–30 min pro Batch. Der Tageslauf startet 06:00 (`config.DAILY_RUN_HOUR`), die
   Briefings hängen hinten dran — vier Batches können den Versand deutlich nach
   hinten schieben. Vor dem Umschalten einmal messen.
3. **Cache-Hit-Rate.** Die 72 % stammen aus einem gpt-4o-mini-Lauf. DeepSeeks
   Auto-Cache und OpenAIs Prefix-Cache greifen unterschiedlich; bei niedrigerer
   Hit-Rate steigen beide Seiten, aber Luna stärker (Input 0.20 vs. 0.14).

## 5b. Wann ist off-peak? — und was das für den Tageslauf heisst

Peak ist 01–04 und 06–10 UTC. In Schweizer Lokalzeit bleibt morgens **ein
Zwei-Stunden-Fenster**:

| | Peak (doppelt) | brauchbares Off-Peak-Fenster morgens |
|---|---|---|
| Sommer (CEST) | 03–06 und 08–12 lokal | **06:00–08:00 lokal** |
| Winter (CET) | 02–05 und 07–11 lokal | **05:00–07:00 lokal** |

Der Tageslauf startet 06:00 lokal (`config.DAILY_RUN_HOUR`) — im Sommer exakt auf
der Fensterkante, im Winter mit nur einer Stunde Luft bis zum Peak.

**Der Haken:** `_daily_run()` ist sequenziell — `refresh_weather()` läuft **vor**
der LLM-Analyse (`scheduler.py:530`). Die Calls starten also nicht um 06:00,
sondern um 06:00 + Refresh-Dauer. Ob wir das Fenster überhaupt treffen, weiss
niemand ohne Messung; `ts` (Ende der LLM-Phase) minus `duration_s` in
`data/cost_telemetry.jsonl` gibt es exakt her:

```bash
python cost_testing/compare_models.py --fenster
```

Kippt die LLM-Phase über 06:00 UTC, zahlt der überhängende Teil den doppelten
Tarif. Zwei Auswege, falls das Fenster nicht reicht:

- **Lauf an UTC hängen statt an Lokalzeit** — fix 04:00–04:15 UTC ganzjährig
  (= 06:00 lokal im Sommer, 05:00 im Winter). Kostet im Winter eine Stunde
  frühere Briefings, gibt dafür ganzjährig die vollen zwei Stunden.
- **Wetter-Refresh vorziehen**, damit die LLM-Phase am Fensteranfang steht statt
  am Ende.

Beides ist Schadensbegrenzung, keine Ersparnis (siehe unten).

## 6. Empfehlung

**Jetzt nichts umschalten.** Die Erhöhung ist morgen 16:00 UTC — bis dahin ist
DeepSeek konkurrenzlos. Danach in dieser Reihenfolge:

1. **Zuerst messen, wann die LLM-Phase wirklich läuft** (`--fenster`, §5b). Der
   Startzeitpunkt des Jobs sagt es nicht — der Wetter-Refresh liegt dazwischen.
   Erst danach entscheiden, ob der Lauf verschoben werden muss.
2. **Zwei Läufe nach dem 16.08. messen**, `data/cost_telemetry.jsonl` auswerten,
   echte DeepSeek-Preise in `config.MODEL_PRICES` nachtragen, dann
   `python cost_testing/compare_models.py --from-telemetry`. Erst hier steht die
   Vergleichszahl auf Messung statt auf Presseartikeln.
3. **Wenn Luna, dann Batch + Reasoning aus** — in dieser Kopplung, sonst lohnt es
   nicht. Reihenfolge: Schalter bauen → `analyze_once.py` auf der Test-CSV →
   `score_regression.py` gegen den Goldstandard → erst bei PASS auf Complete
   umstellen.
4. **`gemini-2.5-flash-lite` nicht vergessen** ($4.35, ohne Batch, ohne
   Reasoning-Falle). Der unaufgeregte Ausweg, falls Luna am Quality-Gate scheitert.

## 7. Was in diesem Zug schon geändert wurde

- `config.MODEL_PRICES` + `MODEL_PROVIDER_MAP`: `gpt-5.6-luna` eingetragen (damit
  im Admin-UI wählbar und in der Telemetrie korrekt bepreist).
- `engine/_common.py`: Kontextfenster 1.05M für Luna — sonst fiele der
  Wetterkontext auf den 128k-Default zurück.
- DeepSeek-Preise **bewusst unverändert**, mit Kommentar zur angekündigten
  Erhöhung und der Bedingung fürs Nachziehen.
- `cost_testing/compare_models.py`: rechnet jedes Preisschema gegen das Profil,
  mit Sanity-Check gegen die dokumentierte Messung.

## Quellen

- [Advancing the price-performance frontier with GPT-5.6 — OpenAI](https://openai.com/index/advancing-the-price-performance-frontier-with-gpt-5-6/)
- [GPT-5.6 Luna Model — OpenAI API Docs](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
- [OpenAI cuts GPT-5.6 Luna prices by 80 % — VentureBeat](https://venturebeat.com/technology/ai-price-wars-openai-cuts-gpt-5-6-luna-prices-by-80-as-model-competition-shifts-toward-cost)
- [GPT-5.6 Pricing: Sol, Terra and Luna Tiers — Finout](https://www.finout.io/blog/gpt-5.6-pricing-2026-sol-terra-and-luna-tiers-explained)
- [GPT 5.6 Luna Is 80 % Cheaper — The Real Story Is the Price of Thinking](https://augmentedmind.substack.com/p/gpt-56-luna-is-80-cheaper)
- [Prompt caching — OpenAI API Docs](https://developers.openai.com/api/docs/guides/prompt-caching)
- [DeepSeek increases prices for AI services by multiple times — Fortune](https://fortune.com/2026/08/13/deepseek-increases-prices-for-ai-services-by-multiple-times/)
- [DeepSeek raises some V4 prices by more than 10x — InfoWorld](https://www.infoworld.com/article/4209439/deepseek-raises-some-v4-prices-by-more-than-10x-as-ai-demand-strains-capacity.html)
- [DeepSeek API Pricing 2026: V4 Peak & Off-Peak — AI Pricing Guru](https://www.aipricing.guru/deepseek-pricing/)
- [DeepSeek-V4 Flash 0731 vs GPT-5.6 Luna on DeepSWE — Together AI](https://www.together.ai/blog/deepseek-v4-flash-0731-vs-gpt-5-6-luna-on-deepswe-cost-and-coding)
- [GPT 5.6 Luna vs DeepSeek V4 Flash: real SaaS tool use — Composio](https://composio.dev/content/gpt-5.6-luna-vs-deepseek-v4-flash)
