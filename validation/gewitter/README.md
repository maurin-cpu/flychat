# Gewitter-Validierung — Warnung gegen Messung

Prüft täglich, ob unsere Gewitteranzeige (Blitz-Symbol aus Ensemble + Anker,
`docs/GEWITTER.md`) stimmt. Richter sind **echte Stationsmessungen** —
SwissMetNet-Stundenwerte (MeteoSchweiz OGD), ~144 Stationen den 29 Regionen
zugeordnet.

Entstanden am 03.08.2026 aus dem ersten Saison-Backtest (15.05.–02.08.,
2'320 Regionstage — Befunde in `docs/GEWITTER.md` §0c). Zweck des laufenden
Betriebs: die **Ensemble-Schwellen eichen**, die rückwirkend nicht prüfbar
sind (Member-Archiv existiert nur vorwärts, seit 31.07.).

## Was als „Gewitter" zählt (Mess-Signatur)

An mindestens einer Station der Region, in derselben Stunde:

```
Regen ≥ 4 mm/h   UND   (Böensprung ≥ 15 km/h ODER Temperatursturz ≥ 2 K
                        gegenüber der Vorstunde)
```

Daneben: **Schauer** = Regen ≥ 2 mm/h (Beleg für hochgewachsene Wolken =
Überentwicklung) und **Sonnenanteil 12–18 Uhr** (widerlegt Bewölkungs-
Warnungen). Schwellen: `scripts/validation_common.py`.

## Grenzen des Richters — beim Lesen immer mitdenken

1. **~5 Stationen pro Region.** Ein isoliertes Berggewitter kann zwischen den
   Stationen durchziehen. „Fehlalarm" heisst: *an den Stationen* nichts
   gemessen — ein Teil davon kann real gewesen sein. Fehlalarm-Raten sind
   Obergrenzen, verpasste Gewitter untererfasst.
2. **Signatur ≠ Blitzmessung.** Trockene oder regenarme Gewitter fehlen;
   heftige Nicht-Gewitter-Schauer können die Signatur auslösen. Freie
   Blitzdaten gibt es nicht (geprüft 01.08., nicht erneut anrennen).
3. **Ein Sommer = ein Wetterregime.** Schwellen jährlich nachprüfen.
4. Bewertet wird der **Tageslauf** (kurzer Vorlauf) — über die 3–5-Tage-
   Vorschau sagt das nichts.
5. **Flugzeit (10–18 Uhr) und Abend (18–24 Uhr) immer getrennt** — abends
   gewittert es häufiger (7,1 % vs. 5,3 % der Regionstage), sonst verzerrt
   der Abend jede Quote.

## Dateien

| Datei | Inhalt |
|---|---|
| `messwerte/YYYY-MM-DD.json` | SMN-Stundenwerte je Station + Ereignisse je Region (archiviert — nie auf die Live-Quelle verweisen) |
| `urteile/YYYY-MM-DD.json` | je Region: gewarnt? gemessen? → Urteil + Zeitversatz, je Fenster |
| `scoreboard.json` | laufende Summen — **alle Ensemble-Schwellen (40/50/60 %) parallel** aus den Roh-Prozenten, damit die Schwellen-Wahl kein neues Sammeln braucht |
| `AUTO_REPORT.md` | maschineller Tagesstand, nie von Hand editieren |
| `PATTERNS.md` | kuratierte Befunde (von Hand) |

Tages-Skript: `scripts/validate_gewitter_daily.py` (Scheduler, morgens für den
Vortag; `--backfill` holt Lücken ab 31.07. nach — älter geht nicht, das
Ensemble-Archiv beginnt dort).
