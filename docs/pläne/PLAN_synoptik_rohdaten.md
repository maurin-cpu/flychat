# PLAN — Synoptik-Rohdaten: dem Modell Material zum Selberdenken geben

**Stand:** 2026-08-01 · **Status:** zur Freigabe — **keine Umsetzung ohne Freigabe**
**Betrifft:** `engine/synoptic_llm.py` (Payload + Output-Schema + `_validate()`) ·
`engine/synoptic_context.py` (History-Verdichter) · `prompts.py`/Skill ·
`data/synoptic_audit/` · `data/weather_archive/` · `cost_testing/ab_model_compare.py`

**Anlass:** Der Wetterlage-LLM bekommt heute nur fertig klassifizierte Etiketten
(`lage_label: "Nordfoehnlage"`, `t850_trend: "insgesamt waermer"`) — die
Mustererkennung passiert vollstaendig deterministisch in
`engine/synoptic_context.py`. Eigenstaendige Muster- oder Trend-Erkennung durch
das Modell ist damit unmoeglich; der Qualitaets-A/B vom 01.08. (Thinking AN
brachte 6/1/0 statt 1/0/1 Validator-Treffer, u.a. erfundenes Gewitter) zeigt:
Reasoning ueber Etiketten produziert nur Konfabulation. Der Druckwellen-Fall
(Plan Synoptik-Phaenomen-Erkennung, R²=0.73 vs. 0.03) zeigt umgekehrt, dass
Prognostiker-Ansichten auf Rohdaten echten Mehrwert liefern koennen.

Vorarbeit erledigt (Commit `c747f70`, 01.08.): `SYNOPTIC_THINKING`-Schalter
(Default aus) + `reasoning_content`-Fallback in `_call_llm()`. Der
Thinking-Modus ist damit gefahrlos reaktivierbar, sobald dieser Plan ihm
Input gibt, ueber den sich nachzudenken lohnt.

---

## 1. Rohdaten in den Payload

Beide Bloecke werden in `build_synoptic_context()` bereits berechnet
(`engine/synoptic_context.py:209-210`), landen aber nur im Audit-File —
`_build_llm_payload()` schliesst sie bewusst aus (`engine/synoptic_llm.py:830-832`).

| Block | Inhalt | Groesse | Vorschlag |
|---|---|---|---|
| `ch_snapshots` | pro Forecast-Tag: `msl_hpa`, `t850_c`, `gh850_m`, `wind_700{speed,dir}` (CH-Mittel ueber 494 Spots) | ~525 Zeichen | **aufnehmen** — das ist die minimale Zahlenbasis fuer Trend-Aussagen (Druckanstieg, Kaltluftadvektion, Winddrehung) |
| `europe_grid` | 16 Gitterpunkte (Island…Genua), `msl_by_day` je Punkt | ~2'010 Zeichen | **aufnehmen, auf ganze hPa gerundet** — Zweck ist Gradienten/Verlagerung erkennen, Zehntel-hPa sind Scheinpraezision und kosten nur Tokens |
| `n_spots`, `msl_source` (in `ch_snapshots`) | Provenance | — | **strippen** (wie `decided_by` via `_strip_provenance`-Logik) |

Kosten: zusammen ~600 Tokens auf heute ~30'000 Input-Tokens (+2 %) — vernachlaessigbar.

Abgrenzung, im Prompt festzuschreiben: Die Rohdaten sind **Interpretations-Material**,
nicht neue Autoritaet. Fuer WAS passiert bleiben die Strukturfelder autoritativ
(gleiches Muster wie der bestehende Wissensbasis-Block, `synoptic_llm.py:807-818`).
Die Verbotsliste (`_FORBIDDEN_PATTERNS`: hPa-Werte, Trog, CAPE …) gilt im
Prosa-Text unveraendert — Rohzahlen rein heisst NICHT Rohzahlen raus in den Cast.

## 2. Zeitachse (Gedaechtnis ueber Tage)

Zwei vorhandene Quellen, beide server-lokal:

- **`data/synoptic_audit/YYYY-MM-DD.json`** — die damalige Lage-Einschaetzung
  inkl. `ch_snapshots`/`europe_grid` (Retention 30 Tage,
  `config.SYNOPTIC_AUDIT_KEEP_DAYS`, reicht).
- **`data/weather_archive/YYYY-MM-DD.json`** — was tatsaechlich eintraf
  (~9–11 MB/Tag, kompletter Wettercache). Muss deterministisch verdichtet
  werden, bevor irgendetwas davon in den Payload darf.

Vorschlag: neuer Verdichter `build_synoptic_history(n_days)` in
`engine/synoptic_context.py`, Ergebnis als `history`-Block in den Payload:

```
history: [
  {date, lage_label,                      # aus synoptic_audit (Soll damals)
   msl_hpa, t850_c, wind_700,             # aus ch_snapshots des Audit-Files
   ist: {regen_zonen: [...], max_wind_class: ...}}   # aus weather_archive,
]                                          # auf dieselben 4 Zonen verdichtet
```

- **Wie viele Tage:** Vorschlag **5** (Entscheid offen, §7). Weniger als 3
  zeigt keinen Trend, mehr als 7 blaeht auf ohne synoptischen Mehrwert.
- **Verdichtung:** eine Zeile pro Tag, Budget gesamt ≤ ~500 Tokens. Das
  `ist`-Aggregat nutzt dieselben Zonen-Metriken wie `precip_zones`/`wind_zones`
  (wiederverwenden, nicht neu erfinden).
- **Ehrlichkeit der Ist-Werte:** `weather_archive` ist Modell-Ist (Open-Meteo),
  keine Messung. Fuer den Payload-Trend okay; fuer die VERIFIKATION von
  Beobachtungen (§4) gilt weiter: nur MeteoSchweiz-Stationen als Wahrheit.
- **Luecken:** Audit-Files fehlen an manchen Tagen (z.B. 23.07.) — der
  Verdichter muss Luecken auslassen koennen, ohne den Block zu verwerfen.

## 3. Getrenntes Feld fuer eigenstaendige Beobachtungen

Der heutige `_validate()` bestraft zu Recht jede Aussage ohne
Strukturfeld-Deckung — der Zonen-Text ist sicherheitsrelevant und bleibt so.
Eigenstaendige Modell-Beobachtungen brauchen einen eigenen Kanal:

- Neues Output-Feld `observations` (Liste, max. 3), jedes Element:
  `{text, based_on, scope}` — `based_on` benennt die Rohdaten-Grundlage
  (z.B. "msl_hpa Island −13 hPa in 3 Tagen"), `scope` Zone(n)+Tag(e).
- **Fliesst NICHT in die Flugempfehlung**: nicht in `flight_hint`, nicht in
  `lead`, kein Einfluss auf Zonen-Texte. `_finalize()` reicht das Feld
  getrennt durch (`llm_overview.observations`).
- **Validierung light statt 1:1-Deckungspflicht:** Verbotsbegriffe und
  erfundene Regionen (`invalid_region` gegen das Grid-Vokabular) gelten auch
  hier; die Deckungspflicht gegen Strukturfelder entfaellt — dafuer ist das
  Feld da. Widerspricht eine Observation einem Strukturfeld hart
  (Gewitter-Behauptung bei `gewitter_share=0`), wird sie gestrippt, nicht
  der Block verworfen.
- **Anzeige-Entscheid (offen, §7):** Phase 1 empfohlen NUR loggen/archivieren
  (Audit-File + Verifikations-CSV), nicht im Cast anzeigen. Sichtbar erst,
  wenn §4 eine Trefferquote belegt. Lehre aus Synoptik-Zonen v2: Skill-Regeln
  ohne Validator-Verankerung werden verletzt — dieselbe Vorsicht hier fuer
  ein Feld ohne Erfolgsbilanz.

## 4. Verifikation der Beobachtungen

Die Maschinerie existiert (`validation/fronten/` mit Auto-Report,
`validation/xcontest/`, `observations.csv`-Muster) — sie braucht nur
maschinenpruefbare Beobachtungen:

- `observations` bekommen deshalb neben dem Freitext ein strukturiertes
  `claim`-Feld: `{feld: "msl_hpa"|"regen"|"wind", zone/scope, richtung:
  "steigt"|"faellt"|"tritt_ein", zeitraum: [date, date]}`. Ohne pruefbaren
  Claim keine Observation (Skill-Regel + Validator-Check auf Schema).
- Taeglicher Auto-Check (Scheduler, analog `validation/fronten`): Claim gegen
  eingetroffene Daten pruefen — Druck/Temperatur gegen die naechsten
  `ch_snapshots`, Regen/Wind gegen MeteoSchweiz-Stationen
  (`scripts/meteoschweiz_stations.py`), NICHT gegen Modell-Ist.
- Ergebnis in `synoptic_validation/observations.csv`
  (Spalten analog `validation/fronten/observations.csv`) + Auto-Report.
  Metrik: Trefferquote je Claim-Typ. Erst ab belegter Quote (Vorschlag:
  ≥70 % ueber ≥20 Claims) wird §3 im Cast sichtbar geschaltet.

## 5. Braucht dieser Schritt Reasoning? — Messung, keine Glaubensfrage

Reihenfolge zwingend: erst §1+§2 im Payload, dann messen — vorher denkt das
Modell nur ueber Etiketten nach, und genau das hat der 01.08.-A/B als
wertlos belegt.

- **Harness:** `cost_testing/ab_model_compare.py`, Input-Replay ueber
  archivierte Tage aus `data/synoptic_audit/` — mehrere Wetterlagen
  (Hochdruck, Druckwellen-/Fronttag, Foehn, Gewitterlage), nicht nur einer.
- **Metriken:** `_validate()`-Treffer + Faktentreue gegen Strukturfeld
  (wie 01.08.) + Claim-Trefferquote aus §4 + `out_tok` + Anteil
  Endlos-Reasoning-Laeufe.
- **Baseline (01.08.2026, voller Prod-Call):** Thinking AN = 6/1/0
  Validator-Treffer, 8/8 leerer `content`, 1/8 Endlos-Reasoning (12k Tokens
  ohne Antwort); AUS = 1/0/1, ~870 out_tok.
- **Einschalt-Kriterium:** Reasoning nur, wenn messbar besser — weniger
  Validator-Treffer UND bestandene Konfabulations-Gegenprobe (kein erfundenes
  Gewitter bei `gewitter_share=0`, kein Foehn ohne Strukturfeld-Foehn) UND
  hoehere Claim-Trefferquote in §4.
- **Risiko Ausgabemenge einplanen:** Der Call kippt schon heute an der
  Output-Groesse (4 Zonen × 3 Tage); §1+§2 vergroessern Input, `observations`
  vergroessert Output. Payload- und Output-Laenge MESSEN (Harness loggt
  in/out_tok), nicht schaetzen. Der `reasoning_content`-Fallback (`c747f70`)
  faengt den Leer-`content`-Fall ab; gegen Endlos-Reasoning zusaetzlich:
  bei `finish_reason=length` ohne verwertbares JSON automatischer Retry
  desselben Versuchs mit `thinking=disabled` (Degradations-Pfad statt
  verlorenem Versuch).

## 6. Ausdruecklich NICHT einbauen: LLM-Analysetexte als Input

Geprueft und verworfen (01.08.):

- Zweite Hand: `spot_analyses_en.json` ist selbst LLM-Output aus demselben
  `weather_cache` — keine neue Information, nur neues Rauschen.
- Groesse: 7.8 MB gegen ~30 KB heutigen Payload.
- Das `zones`-Aggregat verdichtet dieselben Spots bereits numerisch aus der
  Quelle.
- Kette wuerde umgedreht: heute Synoptik → Briefing; sonst waere das grosse
  Bild ein Mittelwert aus 494 Lokaltexten.

**Als Option offen (nicht Teil dieses Plans):** Gegenprobe HINTERHER —
deterministischer Konsistenz-Check, ob der fertige Wetterlage-Text den
Zonen-Analysen widerspricht (z.B. Zone „gut fliegbar" im Cast vs. Mehrheit
`not_safe` in den Spot-Analysen derselben Zone). Waere ein Validator-Baustein,
kein LLM-Input.

---

## 7. Offene Entscheide vor dem Start

| # | Frage | Empfehlung |
|---|---|---|
| 1 | Zeitachse: 3, 5 oder 7 Vortage? | 5 |
| 2 | `europe_grid` voll oder auf ganze hPa gerundet? | gerundet |
| 3 | `observations` Phase 1: nur loggen oder sofort im Cast anzeigen? | nur loggen, sichtbar erst nach §4-Quote |
| 4 | Sichtbarkeits-Schwelle fuer §3 | ≥70 % Treffer ueber ≥20 Claims |
| 5 | A/B-Umfang fuer §5 | ≥8 archivierte Tage, ≥4 Lagetypen, je 3 Laeufe/Modus |
| 6 | Degradations-Pfad (Thinking-Retry non-thinking) schon in Phase 1 einbauen? | ja, ist klein und schuetzt den 06:22-Lauf |

## 8. Reihenfolge der Umsetzung (nach Freigabe)

1. **Payload:** `ch_snapshots` + `europe_grid` (gerundet, gestrippt) in
   `_build_llm_payload()`, Prompt-Abgrenzung, Token-Messung. Tests analog
   `TestBuildLlmPayload`.
2. **Zeitachse:** `build_synoptic_history()` + `history`-Block, Luecken-Test,
   Token-Messung.
3. **Observations-Kanal:** Output-Schema + Validierung light + `_finalize()`-
   Durchreichung, NUR Logging (kein UI).
4. **Verifikation:** Auto-Check + `synoptic_validation/observations.csv` +
   Report. Ab hier sammeln lassen (Wochen, nicht Tage).
5. **Reasoning-A/B** nach §5 — erst danach Entscheid ueber `SYNOPTIC_THINKING=1`.

Schritte 1–3 sind je fuer sich klein und einzeln deploybar; 4 laeuft dann
unbeaufsichtigt; 5 ist ein Messtag.
