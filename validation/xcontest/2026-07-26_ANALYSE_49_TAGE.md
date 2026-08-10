# Sammel-Analyse 49 Tage — Trennschärfe der Thermik-Prognose

> **Hinweis (10.08.2026):** Dieses Protokoll nennt die Regionsnamen im Stand
> **vor** der Umbenennung. Zuordnung alt→neu:
> `data/region_renames_2026-08.csv` · `docs/REGIONEN_UMBENENNUNG_2026-08.md`.
> Der Text bleibt bewusst unverändert — Befunde rückwirkend umzuschreiben
> würde sie fälschen.

**Datum**: 2026-07-26 · **Zeitraum der Flugdaten**: 18.05.–25.07.2026 ·
**Auslöser**: Vergleich unserer Steigwerte mit XC Therm (25.07.) — der Verdacht
„unsere Skala ist zu heiss" hat sich als der falsche Ansatz erwiesen.

Diese Analyse ist **tagesübergreifend** und ersetzt für die nachgelieferten Tage
(21.06.–25.07.) die einzelnen Tages-`.md` — es geht nicht um Spot-Ratings eines
Tages, sondern um eine systematische Eigenschaft des Modells.

---

## Methodik — und warum die erste Auswertung ungültig war

Erster Versuch: Rang-Korrelation zwischen unserer regionalen Steigraten-Prognose
und der real geflogenen Bestleistung je Region. Ergebnis war −0.32 (scheinbar
invers). **Dieser Test ist ungültig** — er verletzt die Regel aus `README.md`:

> Wenige oder keine Flüge ab Spot X ≠ Spot war schlecht.
> → Wir leiten aus „0 Launches" keine Aussage über unser Rating ab.

Gültig ist nur die eine Richtung: *weite Flüge ab X ⇒ X war gut*. Der Test wurde
deshalb einseitig neu gebaut (`scripts/validate_climb_onesided.py`): gemessen wird
der **Perzentil-Rang bewiesen guter Regionen** in unserer Tages-Rangliste.
50 % = Zufall, kleiner = unsere Rangfolge trifft es.

**Kontroll-Test** (Pflicht, sonst ist kein Nullbefund interpretierbar): dieselbe
Metrik mit Grössen, die trennen *müssen*. Wenig Böen → 39 %, wenig Regen → 39 %.
Die Metrik erkennt also Signal.

**Datenbasis**: 49 Tage mit Archiv-Snapshot, 509 Region-Tage mit bewiesenen
Flügen, davon 233 über 60 km und 134 über 100 km.

---

## Befund 1 — die thermischen Felder trennen räumlich nicht

| Ranking-Grösse | Median-Perzentil (≥60 km) |
|---|---|
| wenig Böen zuerst *(Kontrolle)* | **39 %** |
| wenig Regen zuerst *(Kontrolle)* | **39 %** |
| produktive Thermik-Stunden | 48 % |
| unser Steigen (Tages-Max) | 52 % |
| Strahlung | 52 % |
| wenig tiefe Wolken | 52 % |
| max. Thermikhöhe | **57 %** (schlechter als Zufall) |

Die Wind- und Regenfelder ordnen die Regionen brauchbar, die thermischen nicht.

## Befund 2 — es ist keine Streuung, sondern eine feste Schieflage je Region

Perzentil unseres Steigen-Rankings an Tagen, an denen die Region durch Flüge
≥60 km als gut **bewiesen** war:

| Region | n | Median-Perzentil | Tagesbeste dort |
|---|---|---|---|
| Jura Zentral | 21 | **100 %** | 303 km |
| Alpstein / Ostschweiz | 16 | 87 % | 214 km |
| Berner Oberland | 17 | 87 % | 155 km |
| Genferseeregion | 5 | 78 % | 158 km |
| Schwarzsee / Gantrisch | 11 | 70 % | 117 km |
| Mittelland Zentral | 6 | 67 % | 113 km |
| Jura West | 10 | 63 % | 214 km |
| … | | | |
| Berner Voralpen | 14 | 30 % | 225 km |
| Freiburger Voralpen | 24 | 26 % | 336 km |
| Unterwallis | 13 | 26 % | 184 km |
| Prättigau-Davos | 11 | 17 % | 252 km |

Der Jura liegt an 21 bewiesen guten Tagen praktisch immer auf dem **letzten**
Rang von 23 Regionen.

## Befund 3 — die Regions-Zuordnung ist korrekt (ursprüngliche Gegenbehauptung widerlegt)

Zwischenzeitlich stand hier der Befund, 64 von 494 Spots seien der falschen
`analyse_region` zugeordnet (u. a. Niesen unter „Freiburger Voralpen"). Das war
**falsch** — es war ein Artefakt des Kriteriums „Distanz zum Median-Zentrum der
Region", das bei grossflächigen Regionen zwangsläufig Falschtreffer erzeugt.

Punkt-in-Polygon gegen `data/regionen_polygone_mapped.geojson`: **476 von 494
Spots** liegen im Polygon ihrer eingetragenen Region, 17 knapp aussenhalb bei
passender nächstgelegener Region, **0 echte Widersprüche**. Niesen liegt im
Polygon „Freiburger Voralpen" — die Region reicht per Definition ins Simmental.
Details und die einzige Randfall-Abweichung: I-017 in `PATTERNS.md`.

**Was für die Interpretation von Befund 2 bleibt:** die Regionsnamen sind teils
irreführend breit — „Freiburger Voralpen" umfasst 70 Spots bis zum Niesen,
„Berner Oberland" nur 4 Spots im Entlebuch. Das Paar *Berner Oberland (87 %)* /
*Freiburger Voralpen (26 %)* ist damit ein **Benennungs**-Effekt: verglichen werden
nicht die Gebiete, die die Namen suggerieren. Jura Zentral (21 Spots, kompakt) und
Alpstein/Ostschweiz bleiben unberührt — deren Schieflage ist echt.

## Befund 4 — Tagesqualität funktioniert, aber schwächer als am Klein-Sample

National, n=49 Tage: Spearman(Steigen, Tages-Best-km) **+0.24**,
Spearman(produktive Thermik-Stunden, Tages-Best-km) **+0.42**.
Am 20-Tage-Sample waren es +0.48/+0.53 — das war von wenigen extremen
Schlechtwettertagen getrieben. `productive_thermal_h` ist der klar bessere
Tagesprädiktor als die Steigrate.

**Überschätzungs-Tage**: die drei höchsten Juli-Prognosen lieferten real am
wenigsten — 05.07. (3.05 m/s → 74 km), 10.07. (3.00 → 95 km),
16.07. (3.10 → 76 km).

---

## Was daraus folgt (Reihenfolge)

1. **Jura/Alpstein nachrechnen**: was macht die Kette an einem 200-km-Tag dort?
   Terrain-Klasse, H, z_i, Caps — am Archiv nachvollziehbar, ohne Produktänderung.
2. **Erst danach das Niveau** (1.45-Doppelzählung, DWD-Blending), mit
   mitskalierten Rating-Schwellen.

## Grenzen dieser Analyse — offen benannt

- **Rohdaten nur aggregiert abgelegt**: `_raw/strong_flights_2026-06-21_07-25.tsv`
  hält pro Tag+Startplatz nur den **besten Gleitschirmflug ab 60 km**
  (HG/RW/Starrflügler ausgefiltert). Flüge unter 60 km und die Flugzahl pro
  Startplatz sind für die nachgelieferten Tage **nicht** erfasst — die
  Tages-TSVs im Format des Paste-Parsers fehlen dort noch.
- **51 % der Startplätze nicht zuordenbar**: 186 der 363 Zeilen wurden als
  `coverage_gap` erfasst — u. a. Pizol, Brunni, Niederwil, Raimeux, Leysin,
  Moléson, Balderen, Jaman, Montoz. Teils echte DB-Lücken, teils mehrdeutige
  bzw. in XContest abgeschnittene Namen.
- **Juli-Snapshots ohne `analysis`-Block**: alle 24 Archivtage ab 01.07. haben
  leere `spots[*].analysis` — für Juli sind `our_*`-Felder nicht befüllbar, nur
  `wx_*`. Rating-Validierung ist für Juli damit nicht möglich (vgl. I-015).
- Das Perzentil ist ein **Relativmass**: eine Region kann auch dadurch hinten
  landen, dass unsere absolute Spannweite über alle Regionen klein ist
  (am 25.07. z. B. nur 2.20–3.25 m/s über 23 Regionen).
- 09.07. und 23.07. haben Flugdaten, aber **keinen Archiv-Snapshot** — nicht paarbar.
