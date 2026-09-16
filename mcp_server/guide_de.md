# Leitfaden: Meteogramm-Daten wie ein Pilot lesen

Dieser Leitfaden beschreibt, wie erfahrene Gleitschirmpiloten Prognosedaten
auswerten. Er ist **keine Bewertung** und ersetzt keinen Entscheid des Piloten.
Alle Zahlen stammen aus Modellprognosen (Open-Meteo: ICON-CH1/CH2, ICON-D2/EU);
Prognose ist nicht Messung.

## Reihenfolge, die sich bewaehrt hat

1. `overview` — welche Tage/Regionen kommen ueberhaupt in Frage?
2. `day_table` fuer den besten Tag — **alle** Startplaetze in einer Zeile pro Spot,
   nie aus einer Teilmenge schliessen. Oder `search_spots` mit Umkreis/Filtern,
   das meldet, was es warum aussortiert hat.
3. `spot_series` fuer die Kandidaten einer Region — Stundenverlauf + Hoehenprofil.
4. `spot_detail` / `spot_meteogram` / `spot_altitude_wind` fuer 2–4 Favoriten.
5. `spot_info` — Bemerkungen zum Startplatz (Talwind, Landeplatz, lokale Regeln)
   **vor** der Empfehlung lesen.

## Was pro Stunde geprueft wird (Flugstunden 06–17 Uhr)

| Groesse | Woran man es sieht | Faustregel |
|---|---|---|
| **Windrichtung** | `WIND-OK` = Bodenwind liegt im Startsektor (±10 % Toleranz); unter 5 km/h ist die Richtung egal | Ohne WIND-OK kein Start. Dreht der Wind waehrend des Fluges, ist das ein Lande-Thema |
| **Bodenwind** | km/h 10 m ueber Grund | 20–30 sportlich (`WIND-WARN`), > 30 unfliegbar (`WIND-DANGER`) |
| **Boeen** | Boeen 10 m; Exzess = Boeen − Mittelwind | > 30 sportlich (`GUST-WARN`), > 40 unfliegbar (`GUST-DANGER`). Grosser Exzess bei schwachem Wind = Turbulenz |
| **Hoehenwind** | 850/700 hPa und Hoehenprofil (`*` markiert die Flugschicht) | In der Flugschicht 20–30 sportlich, > 30 unfliegbar. **Boden schwach, Hoehe stark (Verhaeltnis > 3:1, z. B. 850 hPa > 30 bei Boden < 10) = versteckter Foehn/Scherung** — das ist der klassische Fehler beim reinen Bodenwind-Blick |
| **Foehn** | ΔP Nord–Sued in hPa, Level none/caution/danger, Richtung Sued/Nord; `Föhn-kritisch` sagt, welche Richtung fuer den Spot zaehlt | ΔP 4–7 hPa Vorsicht, ≥ 8 hPa gefaehrlich. Foehn ist tagsueber flach (kein Trend), kippt aber ploetzlich |
| **Regen / Front** | mm pro Stunde, `RAIN-WARN` ab 0.05 mm | Regenstunde = unfliegbar. Regen vor und nach einem trockenen Fenster („eingekesselt") ist riskanter als ein Regenende am Morgen |
| **Gewitter** | `THUNDERSTORM` (Wettercode 95/96/99), Ensemble-Anteil der Region in %, CAPE J/kg | CAPE > 800 Ueberentwicklung moeglich, > 1500 gefaehrlich. Gewitter ≠ Ueberentwicklung |
| **Wolkenbasis** | Basis m MSL gegen Startplatzhoehe | Basis unter Startplatz = Startverbot; > 1000 m ueber Start = unproblematisch. Bewoelkung an sich ist ein Thermik-, kein Sicherheitsthema |
| **Thermik** | Steigen m/s (Proxy), Top m MSL, produktive Stunden (≥ 0.7 m/s, Band nutzbar) | < 1.0 m/s Abgleiter; 1.5–2.0 solide; ≥ 2.5 Streckentag. Top − Start = nutzbares Band |

## Stunden einteilen

- **RUHIG**: keine WARN/DANGER-Tags. **SPORTLICH**: mindestens ein WARN. **UNFLIEGBAR**: ein DANGER, Regen, Gewitter, Basis unter Start.
- Ein **Startfenster** braucht mindestens 2 zusammenhaengende Stunden WIND-OK ohne DANGER.
  Weniger als 2 h: nicht planbar.
- Anteil sauberer Stunden am Tag: < 35 % heikel, 35–60 % gemischt, > 60 % normal.

## Verlauf lesen (der wichtigste Teil)

- **Ueber die Zeit**: Zunehmende Boeen am Nachmittag → frueh starten und frueh landen.
  Nachlassender Wind am Abend → Abendflug. Ein Fenster, das zwischen zwei Gefahrenphasen
  liegt („eingekesselt"), braucht Reserve: mindestens 90 min vor der Rueckkehr der
  Gefahr am Boden sein.
- **Ueber die Hoehe**: Nimmt der Wind mit der Hoehe stark zu (Start 5 → +2000 m 30 km/h),
  ist die Thermik oben verblasen, die Basis unerreichbar, und man treibt ab.
  Dreht die Richtung mit der Hoehe (Boden W, oben S), kuendigt sich oft Foehn oder
  eine Front an.
- **Trendpfeile** in `day_table` (↗ ↘ →) vergleichen das erste mit dem letzten
  Drittel der Flugstunden — bei ↗ immer die Stundenreihe anschauen.

## Was diese Daten nicht koennen

- Die Modelle rechnen mit 1–2 km Raster. Talwinde, Hangwinde und lokale Duesen sind
  oft schlechter abgebildet als der grossraeumige Wind — die `spot_info`-Bemerkungen
  enthalten das Erfahrungswissen dazu.
- `wind_gusts` im Hoehenprofil ist ein **Turbulenzrisiko**, kein gemessener Boenwert.
- Ein Ensemble-Gewitteranteil ist eine Wahrscheinlichkeit, kein Ja/Nein.
- Nach 30 h ohne neuen Prognoselauf sind die Daten nur noch grobe Orientierung.
