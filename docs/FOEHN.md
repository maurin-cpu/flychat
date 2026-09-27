# Föhn — Warnlogik, Datenlage, Prüfung

Stand 27.09.2026. Recherche und Literatur:
`meteo_research/foehn_valley_forecasting.md`. Belege: `validation/foehn/`.

## Für den Manager

- Die Föhnwarnung ist **national**: eine Druckdifferenz Lugano−Zürich für
  die ganze Schweiz, regional nur nach Süd/Nord/Beide gefiltert.
- Sie ist seit 27.09.2026 **gegen Messungen geprüft** (MeteoSchweiz-Föhnindex,
  16 Talstationen, 1000 Tage): In den grossen Föhntälern trifft sie 91–99 %
  der Föhnstunden, warnt aber in 60–85 % der Warnstunden ohne Föhn am Boden;
  inneralpin (Visp, Andeer, Davos) verpasst sie jede zweite Föhnstunde.
- Entscheid 27.09.: Schwellen bleiben **4 hPa** (Süd und Nord) — bewusst
  konservativ. Regionen mit `Beide` tragen dadurch an ~53 % aller Tage eine
  Föhn-Vorsicht. Das ist gewollt und bekannt.
- Seit 27.09. werden die Grundlagen der Warnung **täglich eingefroren**;
  die Prüfung läuft ab jetzt vorwärts statt rekonstruiert.

## Warnlogik (`foehn_indicators.evaluate_foehn`)

Eingaben (Open-Meteo, stündlich, Modellwahl `best_match`):
Druck auf Meereshöhe Zürich (47.37/8.55) und Lugano (46.00/8.96),
700-hPa-Wind über Zürich, Feuchte und Böen Zürich.

| Stufe | Südföhn (Regionen Süd/Beide) | Nordföhn (Regionen Nord/Beide) |
|---|---|---|
| caution | Δp = Lugano−Zürich ≥ 4 hPa **und** 700-hPa-Wind im Südhalbkreis 90–270° · oder Kammwind 135–225° ≥ 54 km/h | Δp = Zürich−Lugano ≥ 4 hPa · oder Kammwind 315–45° ≥ 54 km/h |
| danger | Δp ≥ 8 hPa (mit Südhalbkreis) · oder Kammwind ≥ 180 km/h | Δp ≥ 8 hPa · oder Kammwind ≥ 180 km/h |

Fehlt die Windrichtung, gilt der Δp-Trigger ohne Sektorbedingung.
Die Sektorbedingung ist neu seit 27.09.2026 (Backtest: −4 % Fehlalarmstunden,
−1.5 Punkte Trefferquote in Altdorf — kleiner Gewinn, physikalisch begründet:
ohne Südkomponente in der Höhe kein Südföhn, Jansing et al. 2022).

Die Regionszuordnung geschieht über `kritischer_foehn` in `data/regionen.csv`
und `data/fluggebiete_pge.csv`. Downstream: `engine/decision_engine.py`
(`compute_foehn_decision`) hebt Safety-Status an, `foehn_risk` landet in den
Analysen, Briefing-Zeile `Foehn=<low|mod|high>` = Maximum über Regionen.

## Datenablage

| Was | Wo | Dauer |
|---|---|---|
| Stundenreihe Zürich/Lugano des Laufs | `data/wetterdaten.json` → `_meta.foehn_series` | rollend |
| Föhn-Grundlagen des Tages (Flugfenster, Δp, Wind, Richtung, Stufe Süd/Nord) | `data/weather_archive/YYYY-MM-DD.json` → `foehn` | dauerhaft (Klasse A) |
| Endurteil pro Spot/Region | Snapshot `spots/*/foehn_risk`, `regions/*/foehn_risk` | dauerhaft |
| Wahrheit | MeteoSchweiz-Föhnindex `wcc006s0`, OGD, 39 Stationen, 10 min, ab 2020 | extern, nachladbar |

## Prüfung

`scripts/backtest_foehn.py` rechnet die Produktivlogik auf Open-Meteo
`historical-forecast-api` und vergleicht stündlich im Flugfenster mit dem
Stationsindex. Befunde kuratiert in `validation/foehn/PATTERNS.md`, Grenzen
des Richters (Talboden ≠ Startplatz!) in `validation/foehn/README.md`.

## Bekannte Grenzen und offene Schritte

1. **Inneralpin blind**: Föhn in Visp/Andeer/Davos entsteht bei Δp < 4 hPa;
   die nationale Zahl kann ihn nicht sehen (P-3).
2. **Nordföhn-Warnung an 36 % aller Tage**, in Magadino 81 % der Warnstunden
   ohne Föhn am Boden (P-5). Bewusst belassen.
3. **Kammwind ist keiner**: 700 hPa über Zürich ≠ Alpenkamm (P-6).
4. Nächster Schritt (offen, nicht freigegeben): Modell-Föhnindex pro Tal nach
   Dürr (2008) — Talpunkt + Kammpunkt, Δθ, Sektor, Feuchte — als eigene
   Punkt-Ebene, am Modell kalibriert (ICON-Kaltbias −1.5 K), gegen dieselben
   Stationen gemessen. Zuerst Reuss/Rheintal (Fehlalarme), dann Wallis/Bünden
   (verpasste Stunden), dann Tessin.
