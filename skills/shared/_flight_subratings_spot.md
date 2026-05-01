═══════════════════════════════════════════════
TEIL 3: SUB-RATINGS — SPOT (5 Einzelbewertungen, 1-10)
═══════════════════════════════════════════════

Statt eines Gesamtratings vergibst du **5 Einzel-Ratings**. Das System berechnet daraus deterministisch das Gesamtrating und clampt auf den Tier-Korridor. Du bist gut im Beurteilen einzelner Aspekte — das Zusammenrechnen uebernimmt die App.

**Gewichte:** thermal 30%, window 20%, wind 10%, xc 15%, **altitude 25%**.

─────────────────────────────────
thermal_rating (1-10) — Thermik-Qualitaet (Gewicht 30%)
─────────────────────────────────

| Wert | Bedeutung                                                      |
|------|----------------------------------------------------------------|
| 9-10 | Peak > 3 m/s, hohe Basis, konsistent ueber 5+ Stunden         |
| 7-8  | Peak 2-3 m/s, solide Basis, guter Tagesverlauf                 |
| 5-6  | Peak 1-2 m/s, maessige Basis oder gedaempft durch Bewoelkung   |
| 3-4  | Peak 0.5-1 m/s, schwache/kurze Thermik, tiefe Basis            |
| 1-2  | Kaum Thermik (<0.5 m/s) oder komplett abgeschirmt              |

─────────────────────────────────
window_rating (1-10) — Flugfenster (Gewicht 20%)
─────────────────────────────────

| Wert | Bedeutung                                                      |
|------|----------------------------------------------------------------|
| 9-10 | 6+ Stunden zusammenhaengendes Fenster, stabile Bedingungen     |
| 7-8  | 4-5 Stunden gutes Fenster, zuverlaessig nutzbar                |
| 5-6  | 3-4 Stunden, evtl. fragmentiert oder mit Einschraenkungen      |
| 3-4  | 1-2 Stunden oder stark fragmentiert                            |
| 1-2  | Kein nutzbares Fenster oder nur Minuten                        |

─────────────────────────────────
wind_rating (1-10) — Wind & Turbulenz (Gewicht 10%)
─────────────────────────────────

| Wert | Bedeutung                                                      |
|------|----------------------------------------------------------------|
| 9-10 | Ruhig (<15 km/h), keine Boeen, stabile Richtung im Sektor      |
| 7-8  | Leichter Wind (15-25 km/h), geringe Boeen, Richtung passt      |
| 5-6  | Maessiger Wind, spuerbare Boeen, Richtung grenzwertig          |
| 3-4  | Stark boeig, Richtung dreht, turbulent                         |
| 1-2  | Stuermisch, extreme Turbulenz, komplett falsche Richtung       |

─────────────────────────────────
xc_rating (1-10) — XC-Potenzial (Gewicht 15%)
─────────────────────────────────

| Wert | Bedeutung                                                      |
|------|----------------------------------------------------------------|
| 9-10 | Top-XC: hohe Basis, Rueckenwind, 100+ km realistisch           |
| 7-8  | Gutes XC: brauchbare Basis, 4+ Stunden, 50-100 km moeglich     |
| 5-6  | Moderates XC: kurze Strecken (20-50 km), eingeschraenkt        |
| 3-4  | Kaum XC: nur lokale Fluege, tiefe Basis oder kurzes Fenster    |
| 1-2  | Kein XC moeglich                                               |

─────────────────────────────────
altitude_rating (1-10) — Steigraum ueber Startplatz (Gewicht 25%)
─────────────────────────────────

**Bewertet zwei Aspekte gemeinsam**:
1. Wie hoch komme ich ueber den Startplatz (AGL)?
2. Wie lange kann ich diese Hoehe halten (Stunden mit gutem Steigraum)?

Im Wetterkontext findest du pro Stunde `THERMIK-PROXY: X m/s bis YYYYm MSL` — das ist die fliegbare Thermik-Obergrenze (gecappt bei der Wolkenbasis LCL). Ziehe die Startplatzhoehe (`elevation_m`, im Spot-Header) ab, um die Hoehe ueber Grund (AGL) zu erhalten. Bewertet wird primaer der **Median ueber die produktiven Stunden**, nicht der Tagespeak — ein einzelner Aufzug zaehlt nicht.

| Wert | Bedeutung (AGL ueber Spot)                                       |
|------|------------------------------------------------------------------|
| 10   | ≥ 2000m AGL ueber den Grossteil der produktiven Stunden — absolut krass, volle Alpen-Hoehe |
| 9    | ~1700m AGL solide gehalten, klar XC-tauglich                     |
| 8    | ~1300-1500m AGL gut gehalten                                     |
| 7    | ~1000m AGL — sehr gut, lokal-XC bequem moeglich                  |
| 6    | ~800m AGL fuer mehrere Stunden                                   |
| 5    | ~600m AGL durchschnittlich                                       |
| 4    | ~400-500m AGL — limitierter Steigraum                            |
| 3    | ~300m AGL — nur knapp ueber Spot                                 |
| 2    | ~150-200m AGL — nahe am Soaring                                  |
| 1    | ≤ 100m AGL oder nur Soaring/Hangwind, keine echte Thermik        |

**Anker:**
- 1000m AGL = **sehr gut** (~7)
- 1500m AGL = **stark** (~8)
- 2000m AGL = **absolut krass** (~10)

**Wichtig:**
- Wenn `max_thermal_height` nahe der Startplatzhoehe bleibt → niedrige Werte (1-3)
- Bedeckte/abgeschirmte Tage: oft niedrig, weil Thermik nicht hoch wachsen kann
- Bei reinen Soaring-Tagen ohne Thermik: 1-2

**WICHTIG: Nutze die volle Breite!** Jedes Sub-Rating unabhaengig bewerten. Differenziere zwischen Spots — gleicher Tag, verschiedene Bewertungen!

**Pflicht:** Vergib alle 5 Sub-Ratings als ganze Zahlen 1-10. Bei `safety_status = not_safe`: alle auf 1 setzen.
