# PLAN: v4-flash Thinking abschalten (+ Beifang-Fixes)

**Stand:** 27.07.2026, Analyse+Test auf dem Server abgeschlossen. **Umsetzung erfolgt auf dem Dev-PC** (dort liegen uncommittete Änderungen, die nicht kollidieren sollen). Dieses Dokument ist die vollständige Übergabe.

## Warum

Seit 25.07 läuft `ANALYSIS_MODEL=deepseek-v4-flash` — Thinking-Modus ist dort **Default**. Kernbefund der Kosten-Analyse:

- `deepseek-chat` war laut DeepSeek-Changelog seit ~24.04.2026 nur ein **Alias für v4-flash non-thinking** (abgerechnet zu v4-flash-Preisen: $0.14 in / $0.28 out / $0.0028 cache-hit). Die Alias-Abschaltung am 24.07 hat also faktisch nur Thinking eingeschaltet, kein Modell gewechselt.
- Effekt: Output/Call ~880 → ~3500 Tok (75 % Thinking), Tageskosten ~$2 → $3.75–4.48 (deckt sich mit der echten DeepSeek-Rechnung), Phase 2 des Daily-Runs 15–18 → 63–77 min. Dazu sporadisch abgeschnittene JSONs (Thinking frisst das 6000er-Headroom) → teure Voll-Retries.

## A/B-Test 27.07 (Server, isolierte Kopie `/home/deploy/flychat_abtest/`)

Setup: 27 Test-Spots × 3 Tage = 81 Spot-Tage, gemeinsamer Wetter-Fetch, `WINGCAST_SPOT_CSV=test`, Prod-venv. Thinking-Disable via `extra_body={"thinking": {"type": "disabled"}}` — **Syntax gegen die echte API verifiziert** (Antwort ohne `reasoning_content`, Tokens wie non-thinking).

| Vergleich | identisch | Flips | gefährlich (not_safe→fliegbar) |
|---|---|---|---|
| thinking vs non-thinking | 74/81 (91,4 %) | 7 | **0** |
| non-thinking vs non-thinking (Jitter-Baseline) | 77/81 (95,1 %) | 4 | 0 |

Alle Flips (beide Vergleiche) sind safe↔conditional-Wackler an Grenzfällen, überwiegend am Grenztag 29.07, ohne `no_go_reasons`, beide Richtungen. Ein Fall (Alpler Tor 29.07) flippt sogar zwischen zwei identischen non-thinking-Läufen → **Mode-Differenz ist vom Jitter nicht unterscheidbar. Non-thinking ist safety-äquivalent.**

Messwerte non-thinking (identische Inputs, 2× reproduziert): 785 statt ~2750 Out-Tok/Call, 3,9× schneller (125 s statt ~490 s Testset), −36 % Kosten. Prod-Hochrechnung: **~$2.30–2.60 statt $4.48/Tag, Phase 2 wieder ~15–20 min.** Logs/Artefakte: `flychat_abtest/ab_thinking_run2.log`, `ab_jitter_run.log`, `cost_testing/ab_*.json`.

## Umsetzungs-Liste (Dev)

### 1. Thinking abschalten (der eigentliche Hebel)
Getestete Referenz-Implementierung (so lief der A/B, in der Server-Kopie in `llm_client.py::_CompletionsAPI.create`, deepseek-Branch):

```python
if p == "deepseek" and model.endswith("-nonthink"):
    model = model.removesuffix("-nonthink")
    extra = dict(extra)
    extra.setdefault("extra_body", {})["thinking"] = {"type": "disabled"}
```

Für Prod besser als Config-Schalter statt Pseudo-Modellname, z. B. `DEEPSEEK_DISABLE_THINKING` (default true für Analyse-Calls). **Scope beachten:** nur die Massen-Analyse (spot/region, `engine/analyzers.py`) — `SYNOPTIC_MODEL` (1 Call/Tag) darf laut Config-Hilfetext bewusst Reasoning behalten, Kosten irrelevant.

Folge-Aufräumer: `_REASONING_TOKEN_HEADROOM`-Pfad (`engine/_common.py:392`, Pattern „v4-flash" in `_REASONING_MODEL_PATTERNS`) — bei non-thinking ist das +6000-Headroom unnötig (schadet aber nicht; ungenutzte max_tokens kosten nichts).

### 2. `config.MODEL_PRICES` korrigieren (gegen api-docs.deepseek.com verifiziert 27.07)
- `deepseek-v4-flash`: `cached_in` **0.0028** (steht 0.035 → est_usd überschätzt ~$1.27/Tag)
- `deepseek-v4-pro`: real **$0.435 in / $0.87 out / $0.003625 cache-hit** (steht 1.74/3.48)
- `deepseek-chat`/`deepseek-reasoner`-Zeilen: tot (Alias abgeschaltet), raus oder als historisch markieren. Die est_usd-Historie in `cost_telemetry.jsonl` vor 25.07 ist wegen der Stale-Preise für Ära-Vergleiche unbrauchbar.

### 3. Cost-Cap komplett entfernen (User-Entscheid 27.07)
`LLM_COST_CAP_USD` (`config.py:1260`), `check_cap()`/`_cost_cap_tripped` (`engine/_common.py`), Aufrufe nur in `run_all_analyses_batch_stream` (`engine/analyzers.py:2379/2491/2647/2757`). Er war ohnehin wirkungslos: der Daily-Run nutzt `run_all_analyses_stream`, dort wird nie geprüft (27.07: est $5.75 > Cap 5.00, nichts ausgelöst).

### 4. A/B-Harness fixen (`cost_testing/ab_model_compare.py`) — zwei echte Bugs
- Kopiert `spot_analyses.json`, die Engine schreibt aber seit dem Sprach-Refactor **`spot_analyses_en.json`** → jeder Harness-Lauf seit dem Refactor verglich den eingefrorenen Altbestand (28.06) mit sich selbst und meldete scheinbar 100 % PASS.
- Bei identischen Modellnamen (Jitter-Messung) schreiben Ref und Kandidat in **dieselbe** `ab_<tag>.json` → ebenfalls Selbst-Diff. Fix: Laufindex in den Dateinamen.

### 5. Deploy (Server, nach Merge)
`git pull` → **danach** `systemctl restart wingcast` (Reihenfolge! 2× schiefgegangen, 03.07+18.07). Danach ersten Daily-Run prüfen: Phase-2-Dauer ~15–20 min, `out/call` ~800 in `cost_telemetry.jsonl`, keine `finish_reason=length`-Retries.

### Aufräumen Server (nach erfolgreicher Umstellung)
`rm -rf /home/deploy/flychat_abtest` (517 MB Testkopie mit den beschriebenen Patches).
