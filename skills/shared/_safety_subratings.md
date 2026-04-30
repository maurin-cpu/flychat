═══════════════════════════════════════════════
SAFETY-SUB-RATINGS (5 Einzelbewertungen, 1-10)
═══════════════════════════════════════════════

Analog zu den Fliegbarkeits-Sub-Ratings (thermal/window/wind/xc) vergibst du
auch fuer die **Sicherheit** Einzel-Ratings — fuenf an der Zahl: Wind, Boeen,
Hoehenwind, Foehn, Wetter (Niederschlag/Gewitter/CAPE/Sicht).

Das System aggregiert nach dem **Weakest-Link-Prinzip** — der **niedrigste**
der 5 Werte bestimmt den Safety-Score (0-100). Sicherheit ist asymmetrisch:
ein perfekter Wind kompensiert kein Gewitter-Risiko. Ein einzelner kritischer
Aspekt darf nicht durch gute Bewertungen anderer Aspekte verdeckt werden.

Formal: `safety_rating = min(wind, gust, aloft, foehn, weather)` × 1, dann
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

─────────────────────────────────
wind_safety_rating (1-10) — Bodenwind / Mittelwind
─────────────────────────────────

Bewertet Mittelwind und Anstroemrichtung am Startplatz waehrend der
produktiven Stunden. **Trend eingerechnet.**

**Spot-Bemerkung lesen**: Default-Idealbereich ist {{cfg.WIND_IDEAL_MIN_KMH}}-{{cfg.WIND_IDEAL_MAX_KMH}} km/h fuer Thermik-Spots. Soaring-Spots wie z.B. Balderen brauchen einen MINDESTWIND (oft ab 15 km/h) — die Spot-Bemerkung im Prompt-Kontext nennt diese Anforderung explizit. Beruecksichtige sie aktiv: bei Soaring-Spot mit Mindestwind 15 km/h ist 8 km/h zu wenig (Rating < 5), aber bei einem Thermik-Spot ist 8 km/h ideal.

| Wert | Bedeutung                                                                |
|------|--------------------------------------------------------------------------|
| 9-10 | Wind im idealen Bereich des Spots ({{cfg.WIND_IDEAL_MIN_KMH}}-{{cfg.WIND_IDEAL_MAX_KMH}} km/h Default, oder Spot-Bemerkung), stabil ueber den Tag |
| 7-8  | Etwas ueber/unter Idealbereich, ggf. {{cfg.WIND_WARN_KMH}}+ km/h, kontrollierbar, Trend stabil |
| 5-6  | Grenzwertig: ueber {{cfg.WIND_WARN_KMH}} km/h ODER unter Spot-Mindestwind ODER schraege Richtung — ODER Aufbau-Trend zur Schwelle |
| 3-4  | Zu stark ({{cfg.WIND_DANGER_KMH}}+ km/h) ODER deutlich falsche Richtung ODER starke Verschlechterung am Nachmittag |
| 1-2  | Stuermisch, Wind-OK=0 oder kompletter Wind-Aufbau ueber den Tag          |

─────────────────────────────────
gust_safety_rating (1-10) — Boenfaktor / Boen-Spitzen
─────────────────────────────────

Bewertet Boenfaktor + absolute Boen-Spitzen waehrend produktiver Stunden.
**Trend eingerechnet.**

| Wert | Bedeutung                                                                |
|------|--------------------------------------------------------------------------|
| 9-10 | Ruhig, Boenfaktor < 1.3, keine Spitzen ueber 25 km/h, stabil             |
| 7-8  | Spuerbare Boeen, Boenfaktor 1.3-1.5, Spitzen unter {{cfg.GUST_WARN_KMH}} km/h, Trend stabil |
| 5-6  | Aktiv, Boenfaktor 1.5-1.7, einzelne Spitzen ab {{cfg.GUST_WARN_KMH}} km/h, ODER Boen-Aufbau |
| 3-4  | Boenfaktor 1.7-2.0 oder Spitzen zwischen {{cfg.GUST_WARN_KMH}}-{{cfg.GUST_DANGER_KMH}} km/h |
| 1-2  | Extreme Boeen, Boenfaktor > 2.0, Spitzen ueber {{cfg.GUST_DANGER_KMH}} km/h, oder GUST-DANGER-Tags |

─────────────────────────────────
aloft_safety_rating (1-10) — Hoehenwind FL050-100
─────────────────────────────────

Bewertet Hoehenwind in 700-850 hPa. Hoher Hoehenwind kann Foehn-Anriss
anzeigen, auch wenn bodennah noch ruhig. **Trend eingerechnet.**

| Wert | Bedeutung                                                                |
|------|--------------------------------------------------------------------------|
| 9-10 | Schwacher Hoehenwind, keine Aloft-Tags, stabil                           |
| 7-8  | Moderat, ALOFT-WARN-Tags moeglich aber kein ALOFT-CONDITIONAL/NOT-SAFE   |
| 5-6  | Erhoeht: ALOFT-CONDITIONAL-Tags vorhanden ODER Aufbau-Trend              |
| 3-4  | Stark: einzelne ALOFT-DANGER-Tags, Foehn-Anriss-Risiko                   |
| 1-2  | Hoehensturm: ALOFT-NOT-SAFE oder mehrere ALOFT-DANGER-Tags               |

─────────────────────────────────
foehn_safety_rating (1-10) — Foehn-Risiko, synoptisch
─────────────────────────────────

Bewertet das synoptische Foehn-Risiko anhand Druckgefaelle, Anstroemung und
Trigger-Kombination. **Aufbau/Abklingen eingerechnet** — ein Foehn der ab
Mittag durchbricht zaehlt anders als ein Foehn der schon am Vortag wieder
abflaut.

Foehn-Hard-Decisions (caution/danger) werden zusaetzlich von der Decision-
Engine deterministisch gesetzt — dieses Rating ist die GRADIENT-Beurteilung
zwischen den Stufen.

**Hinweis**: Bei `foehn_risk=danger` setzt die Decision-Engine automatisch
`safety_status=not_safe` ueber den Hard-Override. Dein Rating beeinflusst dann
ohnehin nichts mehr. Bei `foehn_risk=moderate` ist dein Rating wichtig — es
unterscheidet "leicht moderat" von "schon fast danger".

| Wert | Bedeutung                                                                |
|------|--------------------------------------------------------------------------|
| 9-10 | Keine Foehn-Lage, kein Druckgefaelle, kein Trigger                       |
| 7-8  | Schwacher Hinweis, Druckgefaelle vorhanden aber irrelevante Anstroemung  |
| 5-6  | Foehn-Vorsicht (foehn_risk=moderate, schwaecheres Ende) ODER Aufbau erkennbar |
| 3-4  | Foehn-Vorsicht mit Trigger (foehn_risk=moderate, am oberen Ende)         |
| 1-2  | Akuter Foehn-Durchbruch (foehn_risk=high) oder klar bevorstehend         |

─────────────────────────────────
weather_safety_rating (1-10) — Niederschlag / Gewitter / CAPE / Sicht
─────────────────────────────────

Bewertet alle "nicht-Wind"-Wetter-Hazards: Niederschlag, Gewitter, CAPE/
Ueberentwicklung, Sicht beim Start/Landung. **Trend eingerechnet** — z.B.
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

| Wert | Bedeutung                                                                |
|------|--------------------------------------------------------------------------|
| 9-10 | Keine Niederschlags-/Gewitter-Anzeichen, klare Sicht am Boden            |
| 7-8  | Kein CAPE-WARN, kein Niederschlag, Sicht beim Start/Landung gegeben      |
| 5-6  | CAPE-WARN vorhanden (Ueberentwicklung moeglich) ODER kurze Schauer ausserhalb produktiver Stunden |
| 3-4  | CAPE-WARN mit Aufbau-Trend ODER lokale Schauer im produktiven Fenster ODER Wolken-Basis kommt nahe an Startplatzhoehe |
| 1-2  | Vor Hard-Override-Schwelle: CAPE knapp unter DANGER, Wolken-Basis auf/unter Startplatzhoehe (Cloud-Entry / kein Visual Reference), Regen kurz vor RAIN-WARN |

─────────────────────────────────
NUTZUNGS-REGELN
─────────────────────────────────

**Volle Breite nutzen**: Jedes Sub-Rating unabhaengig bewerten. Differenziere
zwischen Spots/Regionen — gleicher Tag, verschiedene Bewertungen.

**Pflicht**: Vergib alle 5 Safety-Sub-Ratings als ganze Zahlen 1-10.

**Bei `safety_status = not_safe`** (egal welcher Trigger — Wind, Foehn,
Gewitter, Regen, CAPE, OVERCAST): alle 5 auf `1` setzen. Die Decision-Engine
erzwingt dann ueber den Hard-Override-Pfad rot — der Score muss numerisch
ebenfalls tief ausfallen, sonst sieht der User Widersprueche im UI ("alles
rot, aber wind_safety=8/10").

**Bei `safety_status = conditional`**: typischerweise mindestens ein Rating
im Bereich 3-6, andere koennen im 7-8-Bereich liegen (z.B. Foehn-Vorsicht bei
sonst ruhigem Wetter).
