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
Föhnindex pro Tal: `scripts/backtest_foehn_tal.py` → `AUTO_REPORT_TAL.md`, `scoreboard_tal.json` (P-9).
Seit 04.10.2026 friert der Tages-Snapshot zusätzlich `foehn_tal` ein (Wind,
Böe, Richtung, Feuchte, T2m je Talpunkt und Flugstunde + Urteil des Briefings) —
damit lässt sich die Briefing-Bestätigung vorwärts gegen den Föhnindex prüfen.

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


## Täglich seit 14.10.2026 — Föhn-Block des Briefings gegen den Föhnindex

**Prüfling:** der Föhn-Block nach Talmerkmalen (`scripts/briefing_v3_context._foehn_valley_*`),
nachgerechnet aus dem Freeze `data/weather_archive/YYYY-MM-DD.json → foehn_tal` mit der
AKTUELLEN Regel (`evaluate_talpunkt` + gemessene Talsektoren `foehn_talpunkte.sektor_fuer`).
**Skript:** `scripts/validate_foehn_daily.py` (Scheduler nach der Gewitter-Validierung, Tag D-2).
**Ausgabe (server-lokal, gitignored):** `urteile/YYYY-MM-DD.json` (~7 KB/Tag),
`scoreboard_daily.json`, `AUTO_REPORT_DAILY.md`. **Datenarm:** keine Rohmessungen —
die Stationswerte werden per HTTP-Range geholt, gezählt und verworfen (User 14.10.2026).
Keine Alarm-Mail; Blick auf den Report nach Bedarf, mindestens monatlich.

Zwei Stufen: **voll** = alle drei Merkmale, **warn** = alle drei oder Föhnrichtung +
trockene Luft (Wind ≥ 16/Böe ≥ 22, Feuchte ≤ 68 % — Modellfehler aus dem Blog).
Erster Rückblick 05.–12.10.2026 (Stufe warn): 9 Treffer, 0 verpasst, 3 Fehlalarme bei
176 Tal-Tagen. Davos 07.10. war mit Feuchte ≤ 60 % verpasst → Grenze 68 % (Modell zu feucht).

Talsektoren (`data/foehn_talpunkte.geojson → sektor`): Messung MeteoSchweiz Jan–Okt 2026
(95 % der Föhnrichtungen + 20°) vereinigt mit ICON-CH2 an Föhntagen (26.–28.08. Süd,
26.03.–02.04. Nord; 95 % + 10°). Gegen Halbkreis: Station +1315 Treffer / −223 Fehlalarme,
Modell 491 → 537 Treffer; kein Tal verliert. Ohne Station (Verzasca, Riviera, Oberengadin):
Halbkreis. Höhenwind: Föhnrichtung SO–SW / NW–NO (Gütsch 2026: Süd 130–170°, Nord 315–30°,
West 0–1 %).
