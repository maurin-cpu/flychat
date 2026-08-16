# Forecast-Vergleich -- DeepSeek vs. DeepInfra
Verglichen: **1482 Spot/Tag-Bewertungen** (494 Spots), identische Wettereingabe.

## Sicherheitsurteil (das sicherheitskritische Feld)
- Identisch: **1375/1482 (92.8 %)**
- DeepSeek freizuegiger: 42
- DeepInfra freizuegiger: 65
- Richtung: Ungleichgewicht 23 von 107 Abweichungen (21 % Schieflage) -- symmetrisch, sieht nach Streuung aus

## Numerische Bewertungen

Mittelwert-Differenz = DeepInfra minus DeepSeek. Ein Wert nahe 0 heisst: keine systematische Schieflage.

| Feld | n | Mittelwert-Diff | mittl. Betrag | identisch | Abw. > 1 |
|---|---|---|---|---|---|
| safety_rating | 613 | +0.577 | 0.73 | 52 % | 90 |
| experience_rating | 1000 | -0.060 | 0.38 | 74 % | 79 |
| streckenflug.rating | 1482 | +0.000 | 0.06 | 94 % | 0 |
| wind_safety_rating | 981 | +0.221 | 0.83 | 46 % | 116 |
| gust_safety_rating | 981 | +0.309 | 0.69 | 50 % | 121 |
| cape_safety_rating | 981 | +1.145 | 1.19 | 45 % | 387 |
| rain_safety_rating | 981 | +1.034 | 1.20 | 57 % | 271 |
| thunderstorm_safety_rating | 981 | +1.214 | 1.26 | 42 % | 384 |

## Weitere Felder
- Streckenflug-Stufe identisch: 1400/1482 (94.5 %)
- Zeitfenster-Ueberlappung im Mittel: 90.9 %

## Haeufigste Urteilskombinationen

| DeepSeek | DeepInfra | Faelle |
|---|---|---|
| not_safe | not_safe | 782 |
| conditional | conditional | 572 |
| not_safe | conditional  <-- | 41 |
| conditional | not_safe  <-- | 28 |
| safe | safe | 21 |
| conditional | safe  <-- | 19 |
| conditional | error  <-- | 13 |
| not_safe | error  <-- | 5 |

## Abweichende Sicherheitsurteile (max. 25)

| Spot | Tag | DeepSeek | DeepInfra |
|---|---|---|---|
| Alp Stein | 2026-08-18 | conditional | not_safe |
| Alpe del Caviano | 2026-08-18 | conditional | not_safe |
| Arosa - Hoernli - Hörnli | 2026-08-16 | conditional | not_safe |
| Artelengrat-2180 | 2026-08-16 | conditional | not_safe |
| Bietschhorn | 2026-08-16 | conditional | not_safe |
| Calanda | 2026-08-16 | conditional | not_safe |
| Cima di Medeglia | 2026-08-16 | conditional | not_safe |
| Crete de Thyon-2060 (Veysonnaz) | 2026-08-17 | conditional | not_safe |
| Crêt-du-Midi | 2026-08-18 | conditional | error |
| Dent de Vaulion | 2026-08-16 | conditional | error |
| Engelberg - Brunni - Schonegg | 2026-08-16 | conditional | not_safe |
| Gandlouenegrat | 2026-08-18 | conditional | not_safe |
| Gibel-1360 | 2026-08-18 | conditional | error |
| Graitery | 2026-08-16 | conditional | error |
| Jatzmeder-2090 | 2026-08-18 | conditional | error |
| Käserstatt | 2026-08-16 | conditional | not_safe |
| La Breya (Orsieres, Champex) | 2026-08-17 | conditional | error |
| La Dôle | 2026-08-18 | conditional | error |
| Les Giettes | 2026-08-16 | conditional | error |
| Les Giettes | 2026-08-18 | conditional | error |
| Les Verneys | 2026-08-18 | safe | conditional |
| L’Alpe des Chaux | 2026-08-16 | conditional | not_safe |
| Madrisa nord-ost | 2026-08-18 | conditional | not_safe |
| Mauborget | 2026-08-16 | conditional | not_safe |
| Monte Lema | 2026-08-17 | conditional | not_safe |
