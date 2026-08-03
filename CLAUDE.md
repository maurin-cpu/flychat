# CLAUDE.md — flychat

## Daten-Wegweiser: wo hole ich was für Vergleiche/Validierungen?

**Grundregel:** Die Maschinendaten entstehen auf dem **Server** — der lokale
Ordner ist oft veraltet. Vor jeder Auswertung aktuelle Daten holen:
`.\scripts\sync_from_server.ps1` (Windows). Server: `deploy@178.105.39.152`,
Projekt `/home/deploy/flychat`, App läuft als `wingcast.service`.

| Ich brauche … | Ort | Achtung |
|---|---|---|
| **Eingefrorene Tagesprognose** (Basis jeder Validierung) | `data/weather_archive/YYYY-MM-DD.json` — Server vollständig, seit 31.07. inkl. `thunder_ensemble` je Region | 23.07.2026 existiert nicht (Deploy-Stash-Verlust). Nie die Live-Datei als Beleg nehmen |
| **Live-Lauf** (aktuelles 5-Tage-Fenster) | `data/wetterdaten.json` — nur Server aktuell, gitignored | **Rollendes Fenster** — Vergangenheit fällt täglich raus. Für Belege sofort archivieren |
| **Gewitter-Validierung** (Warnung vs. SMN-Messung, täglich) | `validation/gewitter/` — `messwerte/`, `urteile/`, `scoreboard.json`, `AUTO_REPORT.md` | Maschinendaten sind server-lokal (gitignored) → per Sync holen. Grenzen des Richters: dortiges README |
| **Fronten-/XContest-Validierung** | `validation/fronten/`, `validation/xcontest/` | gleiche Bauart, Konvention in `validation/README.md` |
| **Echte Messwerte** (Wahrheit) | MeteoSchweiz OGD SwissMetNet — Zugriff fertig gebaut in `scripts/validation_common.py` (Zehnminutenwerte, Station→Region-Mapping, Gewitter-Signatur) | Prognose ≠ Messung. Stundenwerte verwässern Gewitter-Signaturen — Zehnminutenwerte nehmen |
| **Regionen/Referenzpunkte** | `data/regionen_referenzpunkte.geojson`, `data/regionen_polygone_mapped.geojson` | Regionsnamen ≠ Fremdanbieter-Namen — immer über Koordinaten zuordnen |
| **Modell-Rückblick** (beliebige Vergangenheit) | Open-Meteo `historical-forecast-api` (icon_ch1/ch2, icon_d2, icon_eu, gfs) | **Ensemble ist rückwirkend NICHT rekonstruierbar** (Member identisch nach ~3 Tagen) — nur vorwärts über die Snapshots |
| **Backup** (falls etwas fehlt) | Server `~/flychat-backup/` — additiv, täglich 07:30 Cron | Übergangslösung lokale Platte; Storage Box später (`docs/BACKUP.md`) |

## Harte Lehren (alle 2026 real passiert)

1. **Modell gegen Modell ist keine Validierung.** XC Therm als Massstab
   erzeugte Fehlschlüsse, die die SMN-Messung am selben Tag umdrehte
   (02.08., `validation/gewitter/PATTERNS.md`).
2. **Zahlen aus Logs/Docs sind kein Beleg** — vor Verwendung gegen den
   archivierten Datensatz nachrechnen.
3. **Rollende Dateien sofort einfrieren**, sonst ist die Datenbasis am
   Folgetag weg (Böenfront 30.07.).

## Fachliche Einstiegspunkte

- Gewitter/Blitz-Logik + Backtest-Befunde: `docs/GEWITTER.md` (§0c)
- Validierungs-Konvention: `validation/README.md`
- Offene Pläne: `docs/pläne/` (Plan wird gelöscht, sobald umgesetzt und
  in `docs/` dokumentiert)
