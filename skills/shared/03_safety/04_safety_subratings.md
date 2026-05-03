═══════════════════════════════════════════════
SAFETY-SUB-RATINGS (5 Einzelbewertungen, 1-10)
═══════════════════════════════════════════════

Analog zu den Fliegbarkeits-Sub-Ratings vergibst du auch fuer die **Sicherheit**
Einzel-Ratings — fuenf an der Zahl: Wind, Boeen, Hoehenwind, Foehn, Wetter
(Niederschlag/Gewitter/CAPE/Sicht).

Das System aggregiert nach dem **Weakest-Link-Prinzip** — der **niedrigste**
der 5 Werte bestimmt den Safety-Score (0-100). Sicherheit ist asymmetrisch:
ein perfekter Wind kompensiert kein Gewitter-Risiko. Ein einzelner kritischer
Aspekt darf nicht durch gute Bewertungen anderer Aspekte verdeckt werden.

Formal: `safety_rating = min(wind, gust, aloft, foehn, weather)`, dann
`safety_score = safety_rating × 10`. Kombiniert wird das mit den Decision-
Engine-Hard-Overrides (FoehnDanger, AloftNotSafe, GustFloor, WindOk0, RAIN-
WARN, THUNDERSTORM, CAPE-DANGER, OVERCAST-DANGER usw.).

**Wichtig — Override-Architektur:**
Die Decision-Engine ueberschreibt den Score in harten Faellen deterministisch
(z.B. THUNDERSTORM → automatisch `safety_status=not_safe`). Du beurteilst NUR
den **Gradient zwischen safe und gefaehrlich** — die eindeutigen No-Go-Faelle
faengt der Override.

**Trend einrechnen — PFLICHT:**
Jedes Sub-Rating ist **vorausschauend**. Bewerte den schlechtesten plausiblen
Zustand waehrend der produktiven Stunden inklusive Trend. Ein Tag mit anfangs
ruhigem Wind, der ab 14h auf 35 km/h zunimmt, bekommt ein niedrigeres Rating
als ein Tag mit konstant 18 km/h — auch wenn der Snapshot um 11h gleich
aussieht. Trend-Vokabular (zunehmend / Aufklaerung / eingekesselt / stabil)
gehoert wie heute in `wind_summary` und `summary` als Prose.

**Skala 1-10 — drei Anker, der Rest ist deine Interpretation:**
- **1** = akut gefaehrlich (vor dem Hard-Override-Schwellenwert)
- **5** = grenzwertig, spuerbares Risiko
- **10** = unauffaellig, alles klar

Werte 2-4, 6-9 sind Zwischenstufen — entscheide nach Kontext wie nahe der
Tag am jeweiligen Anker liegt. **Nutze die volle Breite** — differenziere
bewusst zwischen 6, 7, 8.

─────────────────────────────────
wind_safety_rating (1-10) — Bodenwind / Mittelwind
─────────────────────────────────

Was bewertet wird: Mittelwind und Anstroemrichtung am Startplatz waehrend der
produktiven Stunden, inklusive Trend.

**Spot-Bemerkung lesen**: Default-Idealbereich ist {{cfg.WIND_IDEAL_MIN_KMH}}-{{cfg.WIND_IDEAL_MAX_KMH}} km/h fuer Thermik-Spots. Soaring-Spots wie z.B. Balderen brauchen einen MINDESTWIND (oft ab 15 km/h) — die Spot-Bemerkung im Prompt-Kontext nennt diese Anforderung explizit. Beruecksichtige sie aktiv.

Anker:
  1  — Stuermisch ({{cfg.WIND_DANGER_KMH}}+ km/h), Wind-OK=0, kompletter Wind-Aufbau ueber den Tag
  5  — Grenzwertig: ueber {{cfg.WIND_WARN_KMH}} km/h ODER unter Spot-Mindestwind ODER schraege Richtung ODER Aufbau-Trend
  10 — Wind im idealen Bereich des Spots, stabil ueber den ganzen Tag

─────────────────────────────────
gust_safety_rating (1-10) — Boenfaktor / Boen-Spitzen
─────────────────────────────────

Was bewertet wird: Boenfaktor + absolute Boen-Spitzen waehrend produktiver
Stunden, inklusive Trend.

Anker:
  1  — Extreme Boeen, Boenfaktor >2.0, Spitzen ueber {{cfg.GUST_DANGER_KMH}} km/h, oder GUST-DANGER-Tags
  5  — Aktiv: Boenfaktor 1.5-1.7, einzelne Spitzen ab {{cfg.GUST_WARN_KMH}} km/h ODER Boen-Aufbau erkennbar
  10 — Ruhig: Boenfaktor <1.3, keine Spitzen ueber 25 km/h, stabil

─────────────────────────────────
aloft_safety_rating (1-10) — Hoehenwind FL050-100
─────────────────────────────────

Was bewertet wird: Hoehenwind in 700-850 hPa. Hoher Hoehenwind kann Foehn-
Anriss anzeigen, auch wenn bodennah noch ruhig. Trend eingerechnet.

Anker:
  1  — Hoehensturm: ALOFT-NOT-SAFE oder mehrere ALOFT-DANGER-Tags
  5  — Erhoeht: ALOFT-CONDITIONAL-Tags vorhanden ODER klarer Aufbau-Trend
  10 — Schwacher Hoehenwind, keine Aloft-Tags, stabil

─────────────────────────────────
foehn_safety_rating (1-10) — Foehn-Risiko, synoptisch
─────────────────────────────────

Was bewertet wird: synoptisches Foehn-Risiko anhand Druckgefaelle, Anstroemung
und Trigger-Kombination. Aufbau/Abklingen eingerechnet — ein Foehn der ab
Mittag durchbricht zaehlt anders als ein Foehn der schon am Vortag wieder
abflaut.

**Hinweis**: Bei `foehn_risk=danger` setzt die Decision-Engine automatisch
`safety_status=not_safe` ueber den Hard-Override. Bei `foehn_risk=moderate`
ist dein Rating wichtig — es unterscheidet "leicht moderat" von "schon fast
danger".

Anker:
  1  — Akuter Foehn-Durchbruch (foehn_risk=high) oder klar bevorstehend
  5  — Foehn-Vorsicht (foehn_risk=moderate) ODER Aufbau erkennbar
  10 — Keine Foehn-Lage, kein Druckgefaelle, kein Trigger

─────────────────────────────────
weather_safety_rating (1-10) — Niederschlag / Gewitter / CAPE / Sicht
─────────────────────────────────

Was bewertet wird: alle "nicht-Wind"-Wetter-Hazards: Niederschlag, Gewitter,
CAPE/Ueberentwicklung, Sicht beim Start/Landung. Trend eingerechnet — z.B.
CAPE der ueber den Tag aufbaut zaehlt anders als stabile Bedingungen.

**Wolken-Logik (wichtig)**: Bewoelkung ist NUR ein Sicherheits-Thema, wenn
sie die **Sicht beim Start oder Landen beeintraechtigt** — d.h. wenn die
**Wolken-Basis auf oder unter Startplatzhoehe** liegt (Cloud-Entry-Risiko,
Pilot fliegt blind in Wolke / sieht den Startplatz nicht). Hohe oder
mittlere Wolken weit ueber dem Spot sind hier IRRELEVANT — die gehoeren
zur Fliegbarkeit (thermal_rating), nicht zur Sicherheit. Bodennebel oder
sehr tiefe Stratusbasis ueber dem Spot ist klar problematisch.

**Hinweis Hard-Overrides**: Bei `[THUNDERSTORM]`, `[RAIN-WARN]` als DANGER,
`[CAPE-DANGER]` oder `[OVERCAST-DANGER]` greift die Decision-Engine
automatisch und setzt `safety_status=not_safe`. Dein Rating bewertet die
GRADIENT-Faelle zwischen "alles klar" und "akut gefaehrlich".

Anker:
  1  — Vor Hard-Override-Schwelle: CAPE knapp unter DANGER, Wolken-Basis auf/unter Startplatzhoehe, Regen kurz vor RAIN-WARN
  5  — CAPE-WARN vorhanden ODER kurze Schauer am Rand der produktiven Stunden ODER Wolken-Basis kommt nahe an Startplatzhoehe
  10 — Keine Niederschlags-/Gewitter-Anzeichen, klare Sicht am Boden, kein CAPE-WARN

─────────────────────────────────
NUTZUNGS-REGELN
─────────────────────────────────

**Pflicht**: Vergib alle 5 Safety-Sub-Ratings als ganze Zahlen 1-10.

**Bei `safety_status = not_safe`** (egal welcher Trigger — Wind, Foehn,
Gewitter, Regen, CAPE, OVERCAST): alle 5 auf `1` setzen. Die Decision-Engine
erzwingt dann ueber den Hard-Override-Pfad rot — der Score muss numerisch
ebenfalls tief ausfallen, sonst sieht der User Widersprueche im UI ("alles
rot, aber wind_safety=8/10").

**Bei `safety_status = conditional`**: typischerweise mindestens ein Rating
im Bereich 3-6, andere koennen im 7-8-Bereich liegen (z.B. Foehn-Vorsicht bei
sonst ruhigem Wetter).

**Volle Breite nutzen** — wenn der LLM-Run vorher bei "5-7 clustern" stehen
geblieben ist, ist das ein Bug. Differenziere bewusst zwischen 6, 7, 8.
