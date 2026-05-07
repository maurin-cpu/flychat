═══════════════════════════════════════════════
TEIL 3: SUB-RATINGS — REGION (4 Einzelbewertungen, 1-10)
═══════════════════════════════════════════════

Statt eines Gesamtratings vergibst du **4 Einzel-Ratings**. Das System berechnet daraus deterministisch das Gesamtrating. Du bist gut im Beurteilen einzelner Aspekte — das Zusammenrechnen uebernimmt die App.

**Gewichte:** thermal 35%, window 25%, wind 25%, xc 15%.

**Skala 1-10 — drei Anker, der Rest ist deine Interpretation:**
- **1** = unbrauchbar fuer diesen Aspekt
- **5** = mittlerer Standardtag
- **10** = Klassiker-Tag, Top 1% des Jahres

Werte 2-4, 6-9 sind Zwischenstufen — entscheide nach Bauchgefuehl wie nahe der Tag am jeweiligen Anker liegt. **Nutze die volle Breite!** Eine 6 ist NICHT "sicherheitshalber 5", sondern ein klar besserer Tag als 5. Differenziere zwischen Regionen — gleicher Tag, verschiedene Bewertungen.

─────────────────────────────────
thermal_rating (1-10) — Thermik-Qualitaet (Gewicht 35%)
─────────────────────────────────

Was bewertet wird: Steigrate (m/s) UND Konsistenz UND Basishoehe UND
Bewoelkungs-Charakter ueber den produktiven Stunden. Nicht nur den
Peak — ein einzelner starker Aufzug zaehlt nicht.

Bewoelkungs-Hintergrund (du wertest selbst, kein fester Bonus/Malus):
Massgeblich ist max(low, mid); reiner Cirrus >6000m ist thermisch irrelevant.
SCT-Cu (~12-50%) ist die optimale Bedingung — Cu-Marker, Latentwaerme,
Matuszko-Boost. Blau (0%) liefert Thermik ohne diesen Boost. Ab ~50% beginnt
Verschattungs-Daempfung; ≥80% blockt Einstrahlung weitgehend, Thermik kollabiert
(FAA AC 00-6A). Wie stark das in dein Rating einfliesst, entscheidest du anhand
des Tagesbildes.

Anker:
  1  — Unfliegbar / abgeschirmt (z.B. ≥80% Bewoelkung), kaum Steigen (<0.3 m/s)
  5  — Standard-Tag: ~1.0-1.5 m/s, mittlere Basis, 3-4h nutzbar (z.B. blau oder milde Daempfung)
  10 — Klassiker: nachhaltig >2.5 m/s, hohe Basis, 5+h Fenster, optimale Cu-Bedeckung (12-50%)

─────────────────────────────────
window_rating (1-10) — Flugfenster (Gewicht 25%)
─────────────────────────────────

Was bewertet wird: Laenge UND Zusammenhang UND Stabilitaet des nutzbaren
Zeitfensters in der Region. Ein zerrissenes 5h-Fenster zaehlt schlechter als
ein zusammenhaengendes 4h-Fenster.

Bewoelkung kann das Fenster zerschneiden oder verkuerzen — beruecksichtige sie:
ein OD-Kollaps mittags macht das effektive Fenster kuerzer als der Stunden-Count;
stabile SCT-Cu laesst es ungestoert; pendelnde 40-70% Bedeckung erzeugt
rhythmische Unterbrechungen. Wie stark du gewichtest, liegt bei dir.

Anker:
  1  — Kein nutzbares Fenster oder nur Minuten
  5  — 3-4 Stunden, evtl. mit kleineren Einschraenkungen
  10 — 6+ Stunden zusammenhaengend, stabile Bedingungen

─────────────────────────────────
wind_rating (1-10) — Wind & Turbulenz (Gewicht 25%)
─────────────────────────────────

Was bewertet wird: Wind-Staerke UND Boenanteil UND wie gut die typischen
Spot-Sektoren der Region bedient werden. Reine Fliegbarkeits-Sicht — die
Sicherheit liegt bei wind_safety_rating.

Anker:
  1  — Stuermisch, extreme Turbulenz oder komplett falsche Anstroemung
  5  — Maessiger Wind, spuerbare Boeen, Richtung grenzwertig fuer mehrere Spots
  10 — Ruhig (<15 km/h), keine Boeen, stabile Richtung passt fuer alle Sektoren

─────────────────────────────────
xc_rating (1-10) — XC-Potenzial (Gewicht 15%)
─────────────────────────────────

Was bewertet wird: Basishoehe UND Wind aloft (Rueckenwind/Gegenwind) UND
Fenster-Laenge UND grossraeumige Lufmasse UND Bewoelkungs-Marker fuer
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
NUTZUNGS-REGELN
─────────────────────────────────

**Pflicht:** Vergib alle 4 Sub-Ratings als ganze Zahlen 1-10. Bei
`safety_status = not_safe`: alle auf 1 setzen.

**`flyability_notes` ZUERST ausfuellen — vor den Ratings, vor der Prosa**: Fuelle alle 4 Felder mit je einem konkreten Satz aus dem Datenblock. Beispiele:
- `"thermal": "Peak 1.9 m/s 12-15h, BLH 2200m, SCT-Cu 30% — guter Standard-Tag, optimale Bewoelkung."` → thermal_rating 7
- `"xc": "Basishoehe 2000m MSL, Hoehenwind 18 km/h Sued — moderates XC moeglich, kein langer Schenkel gegen Wind."` → xc_rating 5
VERBOTEN: generische Saetze ohne Datenbezug.

**Volle Breite nutzen** — wenn der LLM-Run vorher bei "5-7 clustern" stehen
geblieben ist, ist das ein Bug. Differenziere bewusst zwischen 6, 7, 8.
