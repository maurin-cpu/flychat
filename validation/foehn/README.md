# validation/foehn — Föhnwarnung gegen den amtlichen Föhnindex

**Richter (Wahrheit):** MeteoSchweiz-Föhnindex `wcc006s0` (SwissMetNet OGD),
Zehnminutenwerte UTC, Code 0 = kein Föhn, 1 = Föhnmischluft, 2 = Föhn.
Verfahren Dürr (2008): potentielle Temperatur Tal vs. Kamm (Gütsch),
Windsektor, Windstärke/Böe, Feuchte — objektiv, stationsspezifisch
kalibriert. Verfügbar für 39 Stationen, historisch ab 2020
(`…_t_historical_2020-2029.csv`) und laufend (`…_t_recent.csv`).
Hintergrund: `meteo_research/foehn_valley_forecasting.md`.

**Prüfling:** `foehn_indicators.evaluate_foehn` — die unveränderte
Produktivlogik (Δp Lugano−Zürich, 700-hPa-Wind über Zürich, Feuchte/Böen
Zürich) — gerechnet auf Open-Meteo `historical-forecast-api` mit
`best_match`, weil `fetch_foehn_data` keinen `models`-Parameter setzt.
Stündlich UTC, 2024-01-01 bis 2026-09-26 (1000 Tage).

**Skript:** `scripts/backtest_foehn.py` → `AUTO_REPORT.md`, `scoreboard.json`.

## Grenzen des Richters — was die Wahrheit NICHT sagen kann

1. **Talboden, nicht Startplatz.** Der Index gilt am Stationsniveau
   (400–1600 m). Föhn, der über einem Kaltluftsee liegt und den Talboden nie
   erreicht, ist dort Index 0 — für einen Start auf 1500–2000 m kann er
   trotzdem real und gefährlich sein. Ein „Fehlalarm" in diesem Ordner heisst
   deshalb: *kein Föhn am Talboden im Flugfenster* — nicht: *kein Föhn*.
   Höher gelegene Stationen (Elm 958 m, Engelberg 1036 m, Davos 1594 m) sind
   die beste verfügbare Näherung an die Starthöhe.
2. **Nur wo Stationen stehen.** Oberengadin (Malojawind), Surselva,
   Lötschental, Walliser Hochalpen haben keinen Index. Puschlav, Bergell,
   Sottoceneri haben einen, liegen aber ausserhalb unserer Regionen.
3. **Nordföhn-Kriterien nicht dokumentiert.** Dürr 2008 beschreibt nur
   Südföhn; MeteoSchweiz publiziert den Index auch für Tessin/Südbünden. Die
   dort verwendeten Schwellen sind uns nicht bekannt.
4. **Mischluft (Index 1) ist ein Graubereich.** Chur (viel Kaltluft aus
   Seitentälern) und Sion (fast die Hälfte aller Föhnstunden) haben hohe
   Mischluft-Anteile; sie werden getrennt gezählt und weder als Treffer noch
   als Fehlalarm gewertet.
5. **Der Prüfling ist die heutige Logik, nicht das heutige Modell 1:1.**
   `best_match` historisch ist Open-Meteos rückwirkende Modellwahl; sie
   entspricht der Produktion, kann aber im Detail vom damaligen Live-Lauf
   abweichen. Für Δp und 700-hPa-Wind ist der Unterschied klein.

## Ablage

```
validation/foehn/
├─ README.md          dieses Dokument
├─ SCHEMA.md          Dateiformate
├─ PATTERNS.md        kuratierte Befunde (der Ertrag)
├─ AUTO_REPORT.md     maschinell (gitignored)
├─ scoreboard.json    maschinell (gitignored)
├─ messwerte/         <ABK>_foehnindex_2024-.csv — reduzierte OGD-Wahrheit (gitignored, nachladbar)
└─ modell/            Open-Meteo-Stundenreihen Zürich/Lugano (gitignored, nachladbar)
```

Alles unter `messwerte/` und `modell/` ist Klasse C (jederzeit neu
beschaffbar) und deshalb nicht in Git.
