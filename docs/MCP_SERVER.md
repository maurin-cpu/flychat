# MCP-Server „wingcast“ — Forecast-Daten für ein externes Claude (Experiment)

Stand 16.09.2026. Status: **Experiment, lokal lauffähig, nicht deployt.**

## Worum es geht

Piloten sollen in ihrem eigenen Claude fragen können „Wo kann ich in den nächsten
Tagen fliegen?“ Claude bekommt dafür **Rohdaten und deterministische Kennzahlen**
der App (dieselben Zahlen wie im Meteogramm), aber **keine LLM-Analysen und keine
Ratings**. Claude liest die Daten so, wie ein Pilot das Meteogramm liest — Verlauf
über die Zeit *und* über die Höhe.

Die Tokens bezahlt das Claude-Abo des Piloten. Die App rechnet nur einmal pro Tag
alles vor (~90 s), der MCP-Prozess liest danach nur noch Dateien.

## Warum drei Dichten

494 Startplätze × 3 Tage = 1'482 Spot-Tage. Ein voller Spot-Tag-Block sind ~3'000
Tokens; alles lesen ginge nicht. Darum:

| Stufe | Tool | Umfang | Zweck |
|---|---|---|---|
| Überblick | `overview` | ~1'500 Tokens | Welche Tage/Regionen kommen in Frage |
| Alle Spots eines Tages | `day_table(date)` | ~25'000 Tokens (494 Zeilen) | Claude sieht **jeden** Spot: Fenster, Wind min→max mit Trendpfeil, Böen, 700 hPa, Wind Start→+3000 m, Regen, CAPE, Föhn, Thermik, Basis |
| Serverseitig gesiebt | `search_spots(...)` | ~2'500 Tokens | Filter über alle Spot-Tage; meldet **wie viele warum** ausgeschlossen wurden |
| Verlauf | `spot_series(spots\|region:, date)` | ~600 Tokens/Spot | Stundenreihen 06–17 Uhr + Höhenprofil 09/12/15 Uhr (Start bis +3000 m) |
| Detail | `spot_detail`, `spot_meteogram`, `spot_altitude_wind` | ~3'000 Tokens/Spot | Voller Block mit Tags, Rohreihen, Höhenprofil je Stunde |
| Stammdaten | `spot_info`, `list_regions`, `find_spots_near`, `foehn`, `data_status` | klein | Bemerkungen, Regionen, Umkreis, Föhn-Zeitreihe |

Resource `wingcast://guide/pilot_evaluation` (`mcp_server/guide_de.md`) erklärt Claude,
wie Piloten die Parameter lesen. Prompts `where_can_i_fly`, `evaluate_spot` geben den Ablauf vor.

## Architektur

```
App-Prozess (Engine im Speicher)  ──build_export()──▶  data/mcp_export/build-<ts>/  ◀──  python -m mcp_server
  mcp_server/export.py                                  meta, spots, regions,            (liest nur Dateien,
                                                        screening.jsonl, foehn,           ~50 MB RSS)
                                                        blocks/, meteogram/, altitude/
                                                        CURRENT (Pointer, atomar)
```

- Export-Quellen: `engine._build_single_spot_context(mode="dashboard")` (Block + Caches
  `_ctx_gust_cache`/`_ctx_tq_cache`/`_ctx_foehn_cache`), `web.format_data_for_charts`,
  `web.format_altitude_wind_for_charts`, `foehn_indicators.evaluate_foehn`.
- Einzige Änderung am App-Code: `clean_hour_list` im Gust-Cache (`engine/weather_context.py`).
- `data/mcp_export/` ist Klasse C (gitignored), ~90 MB pro Build, 2 Builds bleiben.
- Frische: > 30 h Warnbanner, > 72 h verweigern die Sieb-Tools. Vergangene Tage fallen raus.
- Bereichsfilter (Tage, Regionen, Umkreis) zählen nicht als Ausschluss; „Basis unter Start“
  ist standardmässig kein Ausschluss (eine Stratus-Stunde am Morgen strich sonst 286/494).

## Lokal ausprobieren

```
.\scripts\sync_from_server.ps1          # aktuelles data/wetterdaten.json
python scripts/build_mcp_export.py      # ~100 s, schreibt data/mcp_export/
```
`.mcp.json` im Projektroot registriert den Server für Claude Code (stdio). Danach in
Claude Code z. B.: „Wo kann ich am Donnerstag fliegen, max 1 h von Luzern?“

Tests: `python -m pytest tests/test_mcp_*.py` (35 Tests, offline).

## Bewusst noch nicht gebaut

- **Kein Scheduler-Hook** — Export von Hand, solange es ein Experiment ist. Später:
  `_run_mcp_export(engine)` in `scheduler._daily_run` nach dem Wetter-Refresh.
- **Kein Deploy** — Phase 2 wäre `wingcast-mcp.service` (streamable-http, Port 5100),
  Caddy `mcp.wingcast.ch`, offen mit Rate-Limit pro IP (Entscheid 16.09.).
- **Open-Meteo-Lizenz** (CC BY, freie API nicht kommerziell) vor einer Veröffentlichung klären.
- Sprache: Blöcke und Tags sind deutsch; keine Übersetzung in v1.
