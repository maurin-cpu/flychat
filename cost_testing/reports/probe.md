# Anbieter-Sonde
Misst Tokens, Cache, Tempo — NICHT die Qualitaet (dafuer `score_regression.py`).

### deepseek  (`deepseek-v4-flash`)

| Messgroesse | Wert |
|---|---|
| Cases | 20/20 ok |
| LLM-Calls | 17 |
| Input-Tokens | 351'352 |
| davon gecacht | 296'960 (84.5 %) |
| Cache warm (ohne 1. Call) | 84.5 % |
| Output-Tokens | 15'603 |
| Latenz Median / P95 | 8.35 s / 9.29 s |
| Dauer gesamt | 140 s |
| Kosten dieser Stichprobe | $0.0243 |
| Fehler | 0 |

### deepinfra  (`deepseek-ai/DeepSeek-V4-Flash`)

| Messgroesse | Wert |
|---|---|
| Cases | 20/20 ok |
| LLM-Calls | 17 |
| Input-Tokens | 351'014 |
| davon gecacht | 296'704 (84.5 %) |
| Cache warm (ohne 1. Call) | 84.5 % |
| Output-Tokens | 16'035 |
| Latenz Median / P95 | 8.23 s / 10.93 s |
| Dauer gesamt | 147 s |
| Kosten dieser Stichprobe | $0.0131 |
| Fehler | 0 |

