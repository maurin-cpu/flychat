═══════════════════════════════════════════════
TEIL 3: SUB-RATINGS — REGION (3 Gate-Ratings, 1-10)
═══════════════════════════════════════════════

Statt eines Gesamtratings vergibst du **3 Gate-Ratings**. Das System berechnet daraus deterministisch das Gesamtrating. Du bist gut im Beurteilen einzelner Aspekte — das Zusammenrechnen uebernimmt die App.

**Formel (Liebig-Triple):** `experience_rating = min(thermal, altitude, xc)`
Alle drei sind gleichwertige Gates — das schwächste Glied limitiert. Ein Klassiker-Tag (10) braucht top Thermik UND top Steigraum UND top XC-Potenzial.
Window und Wind fliessen **nicht** ins Experience-Rating ein — sie sind ueber das Safety-Band und die Warnungen abgedeckt.

**Skala 1-10 — drei Anker, der Rest ist deine Interpretation:**
- **1** = unbrauchbar fuer diesen Aspekt
- **5** = mittlerer Standardtag
- **10** = Klassiker-Tag, Top 1% des Jahres

Werte 2-4, 6-9 sind Zwischenstufen — entscheide nach Bauchgefuehl wie nahe der Tag am jeweiligen Anker liegt. **Nutze die volle Breite!** Eine 6 ist NICHT "sicherheitshalber 5", sondern ein klar besserer Tag als 5. Differenziere zwischen Regionen — gleicher Tag, verschiedene Bewertungen.

─────────────────────────────────
thermal_rating (1-10) — Thermik-Qualitaet [GATE]
─────────────────────────────────

Was bewertet wird — alle vier Dimensionen zusammen, nicht nur den Peak:

1. **Stunden mit guter Thermik** — wie viele Stunden liegt die Steigrate bei ≥1.5 m/s?
   Wie viele bei ≥2.0 m/s? Ein langer guter Tag schlaegt einen kurzen Spitzentag.
2. **Steigrate** — Durchschnitt und Peak ueber die produktiven Stunden.
   Ein einzelner Aufzug zaehlt nicht — Konsistenz entscheidet.
3. **Basishoehe** — Durchschnittliche LCL/Wolkenbasis ueber die guten Stunden.
   Hohe Basis = mehr Spielraum, laengere Schraube.
4. **Bewoelkungs-Charakter** — max(low, mid) ist massgeblich; reiner Cirrus irrelevant.
   SCT-Cu (12-50%): optimale Bedingung. Blau: Thermik ohne Cu-Boost. ≥80%: kollabiert.

Anker (3 Referenzpunkte, der Rest ist deine Interpretation):
  1  — Unfliegbar: kaum nutzbare Thermik, <0.3 m/s oder abgeschirmt
  5  — Standard-Tag: ~1.0-1.5 m/s, mittlere Basis, 3-4h nutzbar
  10 — Klassiker: nachhaltig >2.5 m/s, hohe Basis, 5+h, optimale Cu, Top 1% des Jahres

─────────────────────────────────
xc_rating (1-10) — XC-Potenzial [GATE]
─────────────────────────────────

Was bewertet wird: Basishoehe UND Wind aloft (Rueckenwind/Gegenwind) UND
Fenster-Laenge UND grossraeumige Luftmasse UND Bewoelkungs-Marker fuer
Strecken-Fliegen in der Region.

Bewoelkungs-Hintergrund: SCT-Cu (~25-50%) liefert sichtbare Cu-Strassen und
erleichtert XC-Navigation. Blau-Tage sind XC-tauglich, aber Thermik-Suche ist
schwieriger. OD-Risiko oder grossflaechige hohe Bedeckung machen lange Schenkel
riskant. Wie stark das einfliesst, entscheidest du.

Anker:
  1  — Kein XC moeglich, nur lokal/Soaring
  5  — Moderates XC: 20-50 km, lokal-XC bequem, kein langer Schenkel
  10 — Top-XC: hohe Basis, Rueckenwind, 100+ km realistisch

─────────────────────────────────
altitude_rating (1-10) — Steigraum ueber Regionsgelände [GATE]
─────────────────────────────────

Was bewertet wird: Wie hoch komme ich ueber das typische Gelaende der Region
(AGL, Referenz `elevation_ref`) UND wie lange kann ich diese Hoehe halten.
Bewertet wird primaer der **Median ueber die produktiven Stunden**, nicht der
Tagespeak — ein einzelner Aufzug zaehlt nicht.

Im Wetterkontext findest du pro Stunde `THERMIK-PROXY: X m/s bis YYYYm MSL` —
das ist die fliegbare Thermik-Obergrenze (gecappt bei der Wolkenbasis LCL).
Ziehe `elevation_ref` der Region ab, um die Hoehe ueber Grund (AGL) zu erhalten.

Anker:
  1  — ≤100m AGL oder nur Soaring/Hangwind, keine echte Thermik
  5  — ~600m AGL durchschnittlich ueber die produktiven Stunden
  10 — ≥2000m AGL ueber den Grossteil der produktiven Stunden, volle Alpen-Hoehe

─────────────────────────────────
NUTZUNGS-REGELN
─────────────────────────────────

**Pflicht:** Vergib alle 3 Gate-Ratings (`thermal_rating`, `altitude_rating`, `xc_rating`) als ganze Zahlen 1-10. `window_rating` und `wind_rating` weglassen. Bei `safety_status = not_safe`: alle auf 1 setzen.

**`flyability_notes` ZUERST ausfuellen — vor den Ratings, vor der Prosa**: Fuelle alle 3 Felder (`thermal`, `altitude`, `xc`) mit je einem konkreten Satz aus dem Datenblock. Beispiele:
- `"thermal": "Peak 1.9 m/s 12-15h, BLH 2200m, SCT-Cu 30% — guter Standard-Tag, optimale Bewoelkung."` → thermal_rating 7
- `"xc": "Basishoehe 2000m MSL, Hoehenwind 18 km/h Sued — moderates XC moeglich, kein langer Schenkel gegen Wind."` → xc_rating 5
- `"altitude": "Proxy-Durchschnitt ~1800m MSL = ~1100m AGL ueber elevation_ref 700m — guter Steigraum."` → altitude_rating 6
VERBOTEN: generische Saetze ohne Datenbezug.

**Volle Breite nutzen** — wenn der LLM-Run vorher bei "5-7 clustern" stehen
geblieben ist, ist das ein Bug. Differenziere bewusst zwischen 6, 7, 8.
