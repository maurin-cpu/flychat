# Gewitter-Validierung — Warnung gegen Messung

Prüft täglich, ob unsere Gewitteranzeige (Blitz-Symbol aus Ensemble + Anker,
`docs/GEWITTER.md`) stimmt. Richter sind **echte Stationsmessungen** —
SwissMetNet-**Zehnminutenwerte** (MeteoSchweiz OGD), ~144 Stationen den 29
Regionen zugeordnet. Stundenwerte verwässern die Signatur (beide realen
Gewitter vom 02.08. fielen auf Stundenbasis unter die Schwellen).

Entstanden am 03.08.2026 aus dem ersten Saison-Backtest (15.05.–02.08.,
2'320 Regionstage — Befunde in `docs/GEWITTER.md` §0c). Zweck des laufenden
Betriebs: die **Ensemble-Schwellen eichen**, die rückwirkend nicht prüfbar
sind (Member-Archiv existiert nur vorwärts, seit 31.07.).

## Was als „Gewitter" zählt (Mess-Signatur)

An mindestens einer Station der Region, im selben gleitenden 30-Minuten-Fenster:

```
Regen ≥ 3 mm/30min   UND   (Böensprung ≥ 15 km/h ODER Temperatursturz ≥ 2 K
                            gegenüber 30 min davor)
```

Daneben: **Schauer** = Regenguss ohne Sturm-Zeichen (Beleg für hochgewachsene
Wolken = Überentwicklung), **Sonnenanteil 12–18 Uhr** (widerlegt Bewölkungs-
Warnungen) und **Ausfluss** = Böensprung + Temperatursturz + Druckanstieg
*ohne* Regen — konvektive Kaltluft, deren Regenkern die Station verfehlt hat
*oder* eine trockene Front (30.07.!). Ausfluss ist darum bewusst **kein
Gewitter-Beweis**: er wird nur gespeichert (nie angezeigt, ändert kein
Urteil) und beziffert über die Zeit den blinden Fleck der Gewitter-Signatur —
z. B. wie viele „Fehlalarme" eine Ausfluss-Signatur daneben hatten.
Schwellen: `scripts/validation_common.py`.

## Die Messung kommt mit einem Tag Verzögerung (04.08.2026)

MeteoSchweiz führt die Zehnminuten-Dateien (`t_recent`) **einmal täglich gegen
11:00 UTC** nach; danach stehen alle Werte bis zur letzten UTC-Mitternacht
drin. Ein Lauf am frühen Morgen sieht vom Vortag darum nur **00:00–01:50**
Lokalzeit — und das sah im Urteil aus wie ein *stiller Tag*, nicht wie
fehlende Daten. Genau so ist der 03.08. ins Scoreboard gelaufen (12 statt 144
Werte je Station, gefunden am 04.08.).

Drei Konsequenzen, alle im Code verankert:

1. Validiert wird der **jüngste vollständig publizierte Tag**
   (`letzter_vollstaendiger_tag`) — im 06:00-Lauf also **D-2**, nicht der
   Vortag. Nach 14 Uhr lokal reicht D-1.
2. Ein unvollständiger Tag wird **nicht gespeichert** (`tag_vollstaendig`:
   Median-Ende der Stationen ≥ 23:00). Ein bereits gespeicherter
   unvollständiger Tag wird beim nächsten Lauf neu geholt — der Cache darf
   den Fehler eines zu frühen Laufs nicht festschreiben.
3. Der Join Prognose ↔ Messung läuft über den **normalisierten** Regionsnamen
   (`validation_common.norm_region`). „Waadtländer Alpen" (Prognose) und
   „Waadtlaender Alpen" (Polygon-Datei) waren dieselbe Region; über den rohen
   Namen fand sie ihre eigene Messung nie und zählte still als ereignislos.
   Die Polygon-Datei trägt seit 10.08.2026 ebenfalls den Umlaut — der
   normalisierte Join bleibt für die bereits gespeicherten Messwerte nötig.

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
letzten vollständig publizierten Tag — siehe Verzögerung oben; `--backfill`
holt Lücken ab 31.07. nach — älter geht nicht, das Ensemble-Archiv beginnt
dort).
