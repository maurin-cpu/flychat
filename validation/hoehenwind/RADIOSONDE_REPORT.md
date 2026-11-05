# RADIOSONDE_REPORT — Kachel-Labels gegen Wetterballone (700 hPa)

_Maschinell erzeugt von `radiosonde.py` — nicht von Hand editieren._

305 Aufstiege 12 UTC (Payerne, Stuttgart, München, Novara-Cameri; ≥3 je Termin), 2026-01-01 bis 2026-11-04. „Daneben“ = Richtungsfehler > 45°.

## Teil 1 — Modell an den Ballon-Orten

### icon_d2

| Modellstärke km/h | n | Median-Fehler | daneben (>45°) | grob falsch (>90°) |
|---|---|---|---|---|
| 0–5 | 30 | 45° | 47 % | 17 % |
| 5–10 | 112 | 20° | 18 % | 7 % |
| 10–15 | 137 | 14° | 8 % | 1 % |
| 15–20 | 163 | 11° | 2 % | 0 % |
| 20–25 | 134 | 10° | 1 % | 0 % |
| 25–30 | 121 | 7° | 1 % | 0 % |
| 30–40 | 207 | 7° | 1 % | 0 % |
| >40 | 295 | 5° | 0 % | 0 % |

### ecmwf_ifs025

| Modellstärke km/h | n | Median-Fehler | daneben (>45°) | grob falsch (>90°) |
|---|---|---|---|---|
| 0–5 | 34 | 33° | 29 % | 9 % |
| 5–10 | 100 | 20° | 20 % | 6 % |
| 10–15 | 152 | 14° | 9 % | 1 % |
| 15–20 | 159 | 11° | 1 % | 0 % |
| 20–25 | 150 | 10° | 1 % | 0 % |
| 25–30 | 100 | 8° | 2 % | 0 % |
| 30–40 | 212 | 7° | 0 % | 0 % |
| >40 | 292 | 5° | 0 % | 0 % |

## Teil 2/3 — Kachel gegen Ballone

Label-Tage: {'pfeil': 208, 'teils': 54, 'wechselt': 27, 'kaum': 16}

| Prüfung | alle | Jan–Jun | Jul–Nov |
|---|---|---|---|
| pfeil_neu | {'n': 258, 'daneben_pct': 7} | {'n': 148, 'daneben_pct': 8} | {'n': 110, 'daneben_pct': 5} |
| pfeil_heute_gleiche_tage | {'n': 258, 'daneben_pct': 7} | {'n': 148, 'daneben_pct': 8} | {'n': 110, 'daneben_pct': 5} |
| pfeil_heute_alle_ab10 | {'n': 240, 'daneben_pct': 4} | {'n': 137, 'daneben_pct': 4} | {'n': 103, 'daneben_pct': 4} |
| wechselt_pfeil_waere | {'n': 27, 'daneben_pct': 19} | {'n': 19, 'daneben_pct': 16} | {'n': 8, 'daneben_pct': 25} |
| teils_richtig | {'n': 54, 'richtig_pct': 17} | {'n': 37, 'richtig_pct': 19} | {'n': 17, 'richtig_pct': 12} |
| kaum_richtig | {'n': 16, 'richtig_pct': 12} | {'n': 10, 'richtig_pct': 20} | {'n': 6, 'richtig_pct': 0} |
| kaum_ballone_uneinig_oder_ruhig | {'n': 16, 'pct': 12} | {'n': 10, 'pct': 20} | {'n': 6, 'pct': 0} |
| modelle_uneinig | {'n': 1, 'daneben_pct': 0} | {'n': 0, 'daneben_pct': None} | {'n': 1, 'daneben_pct': 0} |
| modelle_einig | {'n': 256, 'daneben_pct': 7} | {'n': 148, 'daneben_pct': 8} | {'n': 108, 'daneben_pct': 6} |
| ecmwf_kein_pfeil | {'n': 7, 'daneben_pct': 0} | {'n': 2, 'daneben_pct': 0} | {'n': 5, 'daneben_pct': 0} |
| kaum_beide_modelle | {'n': 9, 'richtig_pct': 22} | {'n': 8, 'richtig_pct': 25} | {'n': 1, 'richtig_pct': 0} |
