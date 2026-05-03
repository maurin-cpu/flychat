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

Was bewertet wird: Steigrate (m/s) UND Konsistenz UND Basishoehe ueber den
produktiven Stunden. Nicht nur den Peak — ein einzelner starker Aufzug
zaehlt nicht.

Anker:
  1  — Unfliegbar / abgeschirmt, kaum Steigen (<0.3 m/s)
  5  — Standard-Tag: ~1.0-1.5 m/s, mittlere Basis, 3-4h nutzbar
  10 — Klassiker: nachhaltig >2.5 m/s, hohe Basis, 5+h Fenster

─────────────────────────────────
window_rating (1-10) — Flugfenster (Gewicht 25%)
─────────────────────────────────

Was bewertet wird: Laenge UND Zusammenhang UND Stabilitaet des nutzbaren
Zeitfensters in der Region. Ein zerrissenes 5h-Fenster zaehlt schlechter als
ein zusammenhaengendes 4h-Fenster.

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
Fenster-Laenge UND grossraeumige Lufmasse fuer Strecken-Fliegen in der Region.

Anker:
  1  — Kein XC moeglich, nur lokal/Soaring
  5  — Moderates XC: 20-50 km, lokal-XC bequem, kein langer Schenkel
  10 — Top-XC: hohe Basis, Rueckenwind, 100+ km realistisch

─────────────────────────────────
NUTZUNGS-REGELN
─────────────────────────────────

**Pflicht:** Vergib alle 4 Sub-Ratings als ganze Zahlen 1-10. Bei
`safety_status = not_safe`: alle auf 1 setzen.

**Volle Breite nutzen** — wenn der LLM-Run vorher bei "5-7 clustern" stehen
geblieben ist, ist das ein Bug. Differenziere bewusst zwischen 6, 7, 8.
