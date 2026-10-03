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

Tests: `python -m pytest tests/test_mcp_*.py` (offline).

## Betrieb (seit 09/2026)

- `wingcast-mcp.service` (streamable-http, 127.0.0.1:5100), Caddy leitet
  `https://app.wingcast.ch/mcp` dorthin, `/healthz` fürs Monitoring. Offen, Rate-Limit
  pro IP (60/min), kein Login.
- Export läuft im Scheduler nach dem Wetter-Refresh (`scheduler._run_mcp_export`).
- `deploy.sh` installiert die Unit und startet den Dienst neu.

## Nutzungs-Telemetrie (seit 03.10.2026)

`mcp_server/telemetry.py` hängt als Middleware des MCP-SDK vor jedem Aufruf und
meldet an PostHog (gleicher Projekt-Key wie App und Briefing, `app = "mcp"`):

| Event | wann | Eigenschaften |
|---|---|---|
| `mcp_tool_called` | jeder `tools/call` | `tool`, `ok`, `duration_ms`, `client_kind`, `user_agent` (gekürzt), `client_name/version` (falls der Client sich nennt) |
| `mcp_initialize` | Start einer Client-Verbindung | `client_kind`, `client_name/version` |

**Wer zählt als Nutzer?** Der Server kennt keine Konten. `distinct_id` ist ein
gesalzener Hash aus Client-IP + User-Agent (`MCP_CLIENT_SALT`, Standard
`wingcast-mcp`) — pseudonym, keine IP verlässt den Server. Grenze: über den
claude.ai-Connector kommen alle Nutzer von Anthropic-Servern und fallen auf wenige
Kennungen zusammen → „Clients" ist eine **Untergrenze**, kein Nutzerzähler. Echte
Zahlen gäbe es erst mit einem Token pro Nutzer (nicht gebaut).

Events sind personenlos (`$process_person_profile = false`, keine Personen-Profile).
Ohne `POSTHOG_KEY` passiert nichts; zusätzlich steht jeder Aufruf als Zeile im
journal (`mcp tools/call tool=… client=… mcp:<hash> …ms`). Ein Fehler der
Telemetrie erreicht das Tool nie (Tests: `tests/test_mcp_telemetry.py`).

**Dashboard** „MCP-Server Nutzung" in PostHog (EU): legt
`python scripts/posthog_mcp_dashboard.py` an — braucht einen *persönlichen*
API-Key (`POSTHOG_PERSONAL_API_KEY`, Scopes dashboard:write + insight:write) und
`POSTHOG_PROJECT_ID`; `--dry-run` druckt nur die Definition. Inhalt: Aufrufe/Tag,
Clients/Tag und /Woche, Aufrufe je Tool, Clients nach Art, Verbindungsstarts,
Fehlerquote, p95-Antwortzeit. Abschalten für Tests: `build_server(telemetry_sink=False)`.

## Bewusst noch nicht gebaut

- **Open-Meteo-Lizenz** (CC BY, freie API nicht kommerziell) vor einer Veröffentlichung klären.
- Sprache: Blöcke und Tags sind deutsch; keine Übersetzung in v1.
