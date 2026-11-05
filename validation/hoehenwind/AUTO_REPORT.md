# AUTO_REPORT — Höhenwind-Richtung vs. Stärke

_Maschinell erzeugt von `richtung_vs_staerke.py` — nicht von Hand editieren._

Zeitraum 2026-01-01 bis 2026-11-04, 12:00 Ortszeit. Prognose: Open-Meteo historical-forecast-api, `icon_d2`, Wind 700 hPa. Wahrheit: SwissMetNet, Vektor-Mittel der Zehnminutenwerte 11:30–12:30.

Stationen: COV Piz Corvatsch (3294 m), GOR Gornergrat (3129 m), GUE Gütsch, Andermatt (2286 m), JUN Jungfraujoch (3571 m), SAE Säntis (2501 m), WFJ Weissfluhjoch (2691 m).
Ausgelassen: 53 Fälle gemessene Windstille, 3 Fälle ohne Messung oder Prognose.

Zufall wäre: Median 90°, 75 % daneben, 50 % grob falsch.

## Zeitachsenbeweis (Korrelation Modell-T700 ↔ gemessene Temperatur, Lag in h)

| Station | -3 | -2 | -1 | +0 | +1 | +2 | +3 |
|---|---|---|---|---|---|---|---|
| JUN | 0.975 | 0.979 | 0.982 | 0.985 | **0.986** | 0.985 | 0.983 |
| GOR | 0.979 | 0.984 | 0.987 | **0.988** | 0.986 | 0.981 | 0.975 |
| COV | 0.983 | 0.987 | 0.990 | 0.992 | **0.993** | 0.992 | 0.989 |
| WFJ | 0.976 | 0.979 | 0.981 | **0.981** | 0.981 | 0.979 | 0.976 |
| SAE | 0.967 | 0.970 | 0.972 | 0.974 | **0.975** | 0.974 | 0.973 |
| GUE | 0.961 | 0.964 | 0.965 | **0.965** | 0.965 | 0.964 | 0.962 |

## Test A — je Station (alle Stationen zusammen)

| Modellstärke km/h | n | Median-Fehler | daneben (>45°) | grob falsch (>90°) |
|---|---|---|---|---|
| 0–5 | 212 | 85° | 73 % | 47 % |
| 5–10 | 331 | 57° | 58 % | 36 % |
| 10–15 | 305 | 39° | 45 % | 19 % |
| 15–20 | 257 | 29° | 32 % | 14 % |
| 20–25 | 183 | 32° | 37 % | 11 % |
| 25–30 | 145 | 29° | 30 % | 6 % |
| 30–40 | 177 | 25° | 28 % | 3 % |
| >40 | 182 | 21° | 19 % | 2 % |

### JUN Jungfraujoch (n=290)

| Modellstärke km/h | n | Median-Fehler | daneben (>45°) | grob falsch (>90°) |
|---|---|---|---|---|
| 0–5 | 19 | 69° | 58 % | 42 % |
| 5–10 | 48 | 42° | 48 % | 31 % |
| 10–15 | 46 | 33° | 39 % | 15 % |
| 15–20 | 47 | 22° | 13 % | 2 % |
| 20–25 | 33 | 31° | 27 % | 9 % |
| 25–30 | 32 | 24° | 12 % | 0 % |
| 30–40 | 43 | 20° | 14 % | 2 % |
| >40 | 22 | 13° | 23 % | 5 % |

### GOR Gornergrat (n=290)

| Modellstärke km/h | n | Median-Fehler | daneben (>45°) | grob falsch (>90°) |
|---|---|---|---|---|
| 0–5 | 104 | 99° | 79 % | 54 % |
| 5–10 | 79 | 132° | 84 % | 71 % |
| 10–15 | 39 | 81° | 72 % | 46 % |
| 15–20 | 28 | 80° | 68 % | 39 % |
| 20–25 | 22 | 37° | 41 % | 14 % |
| 25–30 | 9 | 54° | 56 % | 33 % |
| 30–40 | 7 | 10° | 14 % | 0 % |
| >40 | 2 | 9° | 0 % | 0 % |

### COV Piz Corvatsch (n=299)

| Modellstärke km/h | n | Median-Fehler | daneben (>45°) | grob falsch (>90°) |
|---|---|---|---|---|
| 0–5 | 29 | 75° | 79 % | 34 % |
| 5–10 | 76 | 31° | 33 % | 16 % |
| 10–15 | 76 | 15° | 11 % | 5 % |
| 15–20 | 52 | 16° | 2 % | 0 % |
| 20–25 | 31 | 17° | 3 % | 0 % |
| 25–30 | 15 | 13° | 0 % | 0 % |
| 30–40 | 12 | 16° | 0 % | 0 % |
| >40 | 8 | 24° | 12 % | 0 % |

### WFJ Weissfluhjoch (n=303)

| Modellstärke km/h | n | Median-Fehler | daneben (>45°) | grob falsch (>90°) |
|---|---|---|---|---|
| 0–5 | 15 | 74° | 60 % | 40 % |
| 5–10 | 53 | 61° | 64 % | 30 % |
| 10–15 | 59 | 48° | 54 % | 19 % |
| 15–20 | 46 | 39° | 43 % | 17 % |
| 20–25 | 42 | 38° | 45 % | 14 % |
| 25–30 | 26 | 45° | 50 % | 8 % |
| 30–40 | 37 | 46° | 57 % | 0 % |
| >40 | 25 | 20° | 32 % | 0 % |

### SAE Säntis (n=303)

| Modellstärke km/h | n | Median-Fehler | daneben (>45°) | grob falsch (>90°) |
|---|---|---|---|---|
| 0–5 | 17 | 68° | 65 % | 41 % |
| 5–10 | 32 | 41° | 47 % | 16 % |
| 10–15 | 35 | 47° | 51 % | 14 % |
| 15–20 | 39 | 29° | 33 % | 8 % |
| 20–25 | 27 | 30° | 41 % | 11 % |
| 25–30 | 29 | 26° | 28 % | 3 % |
| 30–40 | 39 | 16° | 18 % | 3 % |
| >40 | 85 | 18° | 6 % | 0 % |

### GUE Gütsch, Andermatt (n=307)

| Modellstärke km/h | n | Median-Fehler | daneben (>45°) | grob falsch (>90°) |
|---|---|---|---|---|
| 0–5 | 28 | 81° | 68 % | 46 % |
| 5–10 | 43 | 66° | 67 % | 33 % |
| 10–15 | 50 | 57° | 64 % | 24 % |
| 15–20 | 45 | 52° | 53 % | 27 % |
| 20–25 | 28 | 62° | 64 % | 18 % |
| 25–30 | 34 | 36° | 41 % | 6 % |
| 30–40 | 39 | 33° | 36 % | 10 % |
| >40 | 40 | 40° | 38 % | 5 % |

## Test B — Kachel-Ebene: Vektor-Mittel über die Stationen (307 Tage)

| gemittelte Modellstärke km/h | n | Median-Fehler | daneben (>45°) | grob falsch (>90°) |
|---|---|---|---|---|
| 0–5 | 25 | 45° | 48 % | 24 % |
| 5–10 | 58 | 28° | 29 % | 14 % |
| 10–15 | 62 | 22° | 13 % | 2 % |
| 15–20 | 43 | 21° | 19 % | 0 % |
| 20–25 | 45 | 21° | 7 % | 0 % |
| 25–30 | 32 | 19° | 12 % | 0 % |
| 30–40 | 27 | 10° | 4 % | 0 % |
| >40 | 15 | 9° | 0 % | 0 % |

### Nach Einigkeit der Stationen im Modell (R = |Vektormittel| / Skalarmittel)

| R | n | Median-Fehler | daneben |
|---|---|---|---|
| 0.00–0.50 | 6 | 65° | 50 % |
| 0.50–0.70 | 15 | 45° | 47 % |
| 0.70–0.85 | 41 | 31° | 24 % |
| 0.85–0.95 | 104 | 21° | 18 % |
| 0.95–1.00 | 141 | 17° | 10 % |
