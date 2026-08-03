# Topout-Stichprobe — Region-Thermik P50 vs P75 vs best30%

## ERGEBNIS (2026-06-07) — P75 umgesetzt

**16 echte XContest-Topouts** (Max-Hoehe MSL, vom User abgelesen 2026-06-07) vom
28.-30.05.2026, je gegen die P50/P75/best30-Vorhersage der **Launch-Region** gestellt.
Roh: `_raw/topout_altitudes_2026-05-28_30.tsv` · Analyse: `debug_scripts/topout_vs_percentile.py`

**max_height (Thermik-Decke) vs Topout, n=16:**

| Aggregator | mean Bias | median Bias | mean \|Bias\| | Topout > Vorhersage |
|--|--|--|--|--|
| P50 (alt) | **−300 m** | **−371 m** | 476 m | **13 / 16** |
| **P75 (neu)** | +44 m | +96 m | **321 m** | 7 / 16 |
| best30 | +151 m | +252 m | 376 m | 5 / 16 |

**lcl (Wolkenbasis, muss ≥ Topout sein):** P50 erzeugt **7/16** physikalisch unmoegliche
Faelle (Basis unter erflogener Hoehe), P75 nur 5/16, best30 3/16.

→ **Verdikt:** P50 unterschaetzt systematisch (Median 371m zu tief). P75 nahezu bias-frei,
kleinster Fehler. **Umgesetzt** fuer max_height + lcl (climb_rate bleibt Median) in
`fetch_weather.py:_spot_p75`. Siehe `SYSTEM_CHANGES.md` (2026-06-07).

**Pro Flug (Launch-Region-Anker; lange Fluege = nur Anker):**

| Pilot | Datum | Region | km | Topout | mh P50 | mh P75 | mh B30 | lcl P50 | lcl P75 | lcl B30 |
|--|--|--|--|--|--|--|--|--|--|--|
| Daniel Berger | 05-30 | Oberwallis / Goms | 166 | 4057 | 3287 | 3634 | 3634 | 4155 | 4307 | 4308 |
| Roman Allenbach | 05-30 | Oberwallis / Goms | 127 | 4201 | 3287 | 3634 | 3634 | 4155 | 4307 | 4308 |
| Kris Eggleton | 05-30 | Berner Voralpen | 107 | 3866 | 3386 | 3786 | 3924 | 3682 | 3913 | 4071 |
| Ruedi Bircher | 05-30 | Zentralschweizer Voralpen | 87 | 3317 | 3055 | 3385 | 3564 | 3458 | 3737 | 3894 |
| Marc Hadorn | 05-30 | Berner Voralpen | 60 | 3921 | 3386 | 3786 | 3924 | 3682 | 3913 | 4071 |
| Stefano Schnappenberger | 05-29 | Oberwallis / Goms | 303 | 3995 | 3402 | 3602 | 3635 | 4152 | 4371 | 4357 |
| Marco Larcher | 05-29 | Alpstein / Ostschweiz | 114 | 3221 | 2720 | 2976 | 3038 | 3457 | 3579 | 3638 |
| Oliver de Roibo | 05-29 | Glarnerland / Walensee | 68 | 3563 | 3355 | 3798 | 3845 | 3186 | 3436 | 3489 |
| Fred Meylan | 05-29 | Unterwallis | 47 | 3699 | 3606 | 3823 | 4070 | 3777 | 4365 | 4693 |
| Samuel Rigoni | 05-29 | Tessin Zentral | 42 | 3636 | 3114 | 3764 | 3893 | 2815 | 3220 | 3288 |
| Martin Bühler | 05-28 | Glarnerland / Walensee | 24 | 2920 | 3252 | 3367 | 3389 | 2930 | 3018 | 3106 |
| Yannic Loritz | 05-28 | Alpstein / Ostschweiz | 23 | 2664 | 2495 | 2856 | 2990 | 2930 | 3052 | 3054 |
| Rolf Eichenberger | 05-28 | Mittelland Zentral | 31 | 1999 | 2977 | 3152 | 3335 | 2973 | 3164 | 3312 |
| Simon Beglinger | 05-28 | Zentralschweizer Voralpen | 35 | 3161 | 3259 | 3601 | 3765 | 2991 | 3088 | 3187 |
| Beat Keller | 05-28 | Alpstein / Ostschweiz | 38 | 2725 | 2495 | 2856 | 2990 | 2930 | 3052 | 3054 |
| Ondrej Prochazka | 05-28 | Mattertal / Saastal | 229 | 4574 | 3635 | 4198 | 4312 | 3775 | 4006 | 4222 |

**Caveat:** XContest = beste Tracks → Topout = erreichbare Decke starker Tage. Die 3
Faelle, in denen P50 schon reichte (Bühler/Eichenberger/Beglinger), sind alle kurze
Fluege <35 km. P50 genuegt an schwachen Tagen, unterschaetzt an starken XC-Tagen.

---

## Alte Kandidatenliste (vor 2026-06-07, NICHT abgelesen — durch obige Auswertung ueberholt)

**So fuellst du es aus:** Such den Piloten auf xcontest.org, oeffne seinen Flug an dem Datum,
lies **max. Altitude** (hoechste erreichte Hoehe, m MSL) ab und trag sie in die letzte Spalte.
Topout ist eine UNTERGRENZE der Wolkenbasis (Pilot klinkt meist knapp unter Basis aus).

Vergleich: unsere "max_height" = vorhergesagte Thermik-Decke MSL (am naechsten am Topout).
"lcl" = vorhergesagte Wolkenbasis MSL (sollte >= Topout liegen).

| # | Datum | Terrain | Region | km | Pilot | Start | max_height P50 | P75 | best30 | lcl P50 | P75 | best30 | **Topout abgelesen** |
|--|--|--|--|--|--|--|--|--|--|--|--|--|--|
| 1 | 2026-05-25 | alpen | Berner Voralpen | 225 | Emanuel Hofmann | 10:09 | 3435 | 3913 | 4108 | 3468 | 3746 | 3837 | _____ |
| 2 | 2026-05-28 | alpen | Alpstein / Ostschweiz | 81 | Beat Weyeneth | 11:45 | 2495 | 2856 | 2990 | 2930 | 3052 | 3054 | _____ |
| 3 | 2026-05-24 | alpen | Alpstein / Ostschweiz | 43 | Tony Marty | 14:39 | 3058 | 3416 | 3418 | 2788 | 2967 | 3002 | _____ |
| 4 | 2026-05-29 | hochalpin | Oberwallis / Goms | 328 | Lars Meerstetter | 09:30 | 3402 | 3602 | 3635 | 4152 | 4371 | 4357 | _____ |
| 5 | 2026-05-30 | hochalpin | Berner Oberland | 155 | KURT HÄNNI | 13:59 | 2728 | 2960 | 2900 | 3365 | 3547 | 3511 | _____ |
| 6 | 2026-05-24 | hochalpin | Engadin Ober | 41 | Matias Marugg | 11:58 | 4248 | 4482 | 4483 | 4498 | 4701 | 4754 | _____ |
| 7 | 2026-05-27 | jura | Jura West | 214 | Noé Court | 11:01 | 2605 | 2744 | 2771 | 2967 | 3138 | 3313 | _____ |
| 8 | 2026-05-21 | jura | Jura Zentral | 98 | KURT HAENNI | 11:36 | 1821 | 2000 | 2084 | 2252 | 2443 | 2563 | _____ |
| 9 | 2026-05-30 | jura | Jura Zentral | 66 | Umbricht Fabian | 13:51 | 2141 | 2469 | 2489 | 3738 | 3884 | 3972 | _____ |
| 10 | 2026-05-21 | mittelland | Mittelland Ost | 48 | B. Ritzmann | 12:40 | 1702 | 2910 | 2910 | 2329 | 2468 | 2468 | _____ |
| 11 | 2026-05-27 | voralpen | Freiburger Voralpen | 336 | Noah Kiener | 09:10 | 3126 | 3512 | 3632 | 3306 | 3513 | 3627 | _____ |
| 12 | 2026-05-25 | voralpen | Schwarzsee / Gantrisch | 87 | Vincent Aeby | 11:57 | 3292 | 3350 | 3350 | 2785 | 2914 | 2914 | _____ |
| 13 | 2026-05-24 | voralpen | Mittelland Zentral | 43 | Thomas Baumann | 15:43 | 2748 | 3302 | 3453 | 2858 | 3112 | 3213 | _____ |