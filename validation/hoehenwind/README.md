# validation/hoehenwind/ — Stimmt die Höhenwind-Richtung der Tageskachel?

**Frage:** Ab welcher prognostizierten Windstärke auf 700 hPa (≈3000 m) zeigt der
Richtungspfeil der Tageskachel (Briefing Sektion 1) zuverlässig in die richtige
Richtung, und darunter „umlaufend“?

**Richter (Wahrheit) seit 05.11.2026: Radiosonden** 700 hPa, 12 UTC (IGRA2, NOAA NCEI: Payerne, Stuttgart, München, Novara-Cameri) — `radiosonde.py`, `kachel_backtest.py`, `karte_vs_ballon.py`. Gipfel taugen für die Richtung nicht (Hang-/Thermikwind am Messort, siehe PATTERNS.md).

**Erster Richter (Gipfel):** SwissMetNet-Gipfelstationen (MeteoSchweiz OGD,
Zehnminutenwerte `fkl010z0`/`dkl010z0`), Vektor-Mittel 11:30–12:30 Ortszeit:
Jungfraujoch, Gornergrat, Piz Corvatsch, Weissfluhjoch, Säntis, Gütsch.

**Prognose:** Open-Meteo `historical-forecast-api`, `icon_d2` (wie
`config.PRESSURE_LEVEL_PRIMARY_MODEL`), Wind 700 hPa um 12:00 an den Stationskoordinaten.

**Lauf:** `python validation/hoehenwind/richtung_vs_staerke.py [--von] [--bis]`
→ `AUTO_REPORT.md`, `ergebnis.json`. Rohdaten-Cache im System-Temp.
Einmaliger Backtest, kein täglicher Lauf.

## Grenzen des Richters

- **6 Stationen statt ~500 Spots.** Test B bildet die Kachel (Vektor-Mittel über
  die Schweiz) nur grob nach.
- **Gelände.** Gipfelstationen messen umgelenkten Wind. Gornergrat (Mattertal) und
  Gütsch (Gotthard) liegen auch bei kräftigem Wind oft daneben: Das ist Kanalisierung
  am Messort, kein Modellfehler auf 700 hPa. Säntis und Gütsch liegen unter 700 hPa.
- **Kurze Vorlaufzeit.** Die historical-forecast-api setzt die jeweils ersten
  Stunden der Läufe zusammen. Für Tag 2/3 der Kachel ist der Fehler grösser als hier.
- **Zeitachse:** über die Temperatur geprüft (Lag 0/+1 h gleichauf, Unterschied
  ≤0.001). Die Jahreszeit dominiert die Korrelation, deshalb trennt der Beweis
  schwach. Die Stichprobe von Hand (3 Tage, Sommer- und Winterzeit) passt.
