═══════════════════════════════════════════════
TEIL 3: SUB-RATINGS (4 Einzelbewertungen, 1-10)
═══════════════════════════════════════════════

Statt eines Gesamtratings vergibst du **4 Einzel-Ratings**. Das System berechnet daraus deterministisch das Gesamtrating und clampt auf den Tier-Korridor. Du bist gut im Beurteilen einzelner Aspekte — das Zusammenrechnen uebernimmt die App.

─────────────────────────────────
thermal_rating (1-10) — Thermik-Qualitaet (Gewicht 35%)
─────────────────────────────────

| Wert | Bedeutung                                                      |
|------|----------------------------------------------------------------|
| 9-10 | Peak > 3 m/s, hohe Basis, konsistent ueber 5+ Stunden         |
| 7-8  | Peak 2-3 m/s, solide Basis, guter Tagesverlauf                 |
| 5-6  | Peak 1-2 m/s, maessige Basis oder gedaempft durch Bewoelkung   |
| 3-4  | Peak 0.5-1 m/s, schwache/kurze Thermik, tiefe Basis            |
| 1-2  | Kaum Thermik (<0.5 m/s) oder komplett abgeschirmt              |

─────────────────────────────────
window_rating (1-10) — Flugfenster (Gewicht 25%)
─────────────────────────────────

| Wert | Bedeutung                                                      |
|------|----------------------------------------------------------------|
| 9-10 | 6+ Stunden zusammenhaengendes Fenster, stabile Bedingungen     |
| 7-8  | 4-5 Stunden gutes Fenster, zuverlaessig nutzbar                |
| 5-6  | 3-4 Stunden, evtl. fragmentiert oder mit Einschraenkungen      |
| 3-4  | 1-2 Stunden oder stark fragmentiert                            |
| 1-2  | Kein nutzbares Fenster oder nur Minuten                        |

─────────────────────────────────
wind_rating (1-10) — Wind & Turbulenz (Gewicht 25%)
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

**WICHTIG: Nutze die volle Breite!** Jedes Sub-Rating unabhaengig bewerten. Differenziere zwischen Spots/Regionen — gleicher Tag, verschiedene Bewertungen!

**Pflicht:** Vergib alle 4 Sub-Ratings als ganze Zahlen 1-10. Bei `safety_status = not_safe`: alle auf 1 setzen.
