═══════════════════════════════════════════════
TEIL 3: SUB-RATINGS — SPOT (5 Einzelbewertungen, 1-10)
═══════════════════════════════════════════════

Statt eines Gesamtratings vergibst du **5 Einzel-Ratings**. Das System berechnet daraus deterministisch das Gesamtrating. Du bist gut im Beurteilen einzelner Aspekte — das Zusammenrechnen uebernimmt die App.

**Gewichte:** thermal 30%, window 20%, wind 10%, xc 15%, **altitude 25%**.

**Skala 1-10 — drei Anker, der Rest ist deine Interpretation:**
- **1** = unbrauchbar fuer diesen Aspekt
- **5** = mittlerer Standardtag
- **10** = Klassiker-Tag, Top 1% des Jahres

Werte 2-4, 6-9 sind Zwischenstufen — entscheide nach Bauchgefuehl wie nahe der Tag am jeweiligen Anker liegt. **Nutze die volle Breite!** Eine 6 ist NICHT "sicherheitshalber 5", sondern ein klar besserer Tag als 5. Differenziere zwischen Spots — gleicher Tag, verschiedene Bewertungen.

─────────────────────────────────
thermal_rating (1-10) — Thermik-Qualitaet (Gewicht 30%)
─────────────────────────────────

Was bewertet wird: Steigrate (m/s) UND Konsistenz UND Basishoehe ueber den
produktiven Stunden. Nicht nur den Peak — ein einzelner starker Aufzug
zaehlt nicht.

Anker:
  1  — Unfliegbar / abgeschirmt, kaum Steigen (<0.3 m/s)
  5  — Standard-Tag: ~1.0-1.5 m/s, mittlere Basis, 3-4h nutzbar
  10 — Klassiker: nachhaltig >2.5 m/s, hohe Basis, 5+h Fenster

─────────────────────────────────
window_rating (1-10) — Flugfenster (Gewicht 20%)
─────────────────────────────────

Was bewertet wird: Laenge UND Zusammenhang UND Stabilitaet des nutzbaren
Zeitfensters. Ein zerrissenes 5h-Fenster zaehlt schlechter als ein
zusammenhaengendes 4h-Fenster.

Anker:
  1  — Kein nutzbares Fenster oder nur Minuten
  5  — 3-4 Stunden, evtl. mit kleineren Einschraenkungen
  10 — 6+ Stunden zusammenhaengend, stabile Bedingungen

─────────────────────────────────
wind_rating (1-10) — Wind & Turbulenz (Gewicht 10%)
─────────────────────────────────

Was bewertet wird: Bodenwind-Staerke UND Boenanteil UND Richtung relativ
zum Spot-Sektor. Reine Fliegbarkeits-Sicht — die Sicherheit liegt bei
wind_safety_rating.

Anker:
  1  — Stuermisch, extreme Turbulenz oder komplett falsche Richtung
  5  — Maessiger Wind, spuerbare Boeen, Richtung grenzwertig im Sektor
  10 — Ruhig (<15 km/h), keine Boeen, stabile Richtung im Sektor

─────────────────────────────────
xc_rating (1-10) — XC-Potenzial (Gewicht 15%)
─────────────────────────────────

Was bewertet wird: Basishoehe UND Wind aloft (Rueckenwind/Gegenwind) UND
Fenster-Laenge UND grossraeumige Lufmasse fuer Strecken-Fliegen.

Anker:
  1  — Kein XC moeglich, nur lokal/Soaring
  5  — Moderates XC: 20-50 km, lokal-XC bequem, kein langer Schenkel
  10 — Top-XC: hohe Basis, Rueckenwind, 100+ km realistisch

─────────────────────────────────
altitude_rating (1-10) — Steigraum ueber Startplatz (Gewicht 25%)
─────────────────────────────────

Was bewertet wird: Wie hoch komme ich ueber den Startplatz (AGL) UND wie
lange kann ich diese Hoehe halten. Bewertet wird primaer der **Median ueber
die produktiven Stunden**, nicht der Tagespeak — ein einzelner Aufzug zaehlt
nicht.

Im Wetterkontext findest du pro Stunde `THERMIK-PROXY: X m/s bis YYYYm MSL` —
das ist die fliegbare Thermik-Obergrenze (gecappt bei der Wolkenbasis LCL).
Ziehe die Startplatzhoehe (`elevation_m`, im Spot-Header) ab, um die Hoehe
ueber Grund (AGL) zu erhalten.

Anker:
  1  — ≤100m AGL oder nur Soaring/Hangwind, keine echte Thermik
  5  — ~600m AGL durchschnittlich ueber die produktiven Stunden
  10 — ≥2000m AGL ueber den Grossteil der produktiven Stunden, volle Alpen-Hoehe

─────────────────────────────────
NUTZUNGS-REGELN
─────────────────────────────────

**Pflicht:** Vergib alle 5 Sub-Ratings als ganze Zahlen 1-10. Bei
`safety_status = not_safe`: alle auf 1 setzen.

**Volle Breite nutzen** — wenn der LLM-Run vorher bei "5-7 clustern" stehen
geblieben ist, ist das ein Bug. Differenziere bewusst zwischen 6, 7, 8.
