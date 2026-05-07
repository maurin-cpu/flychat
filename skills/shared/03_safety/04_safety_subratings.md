═══════════════════════════════════════════════
SAFETY-SUB-RATINGS (5 Einzelbewertungen, 1-10)
═══════════════════════════════════════════════

Analog zu den Fliegbarkeits-Sub-Ratings vergibst du auch fuer die **Sicherheit**
Einzel-Ratings — acht an der Zahl: Wind, Boeen, Hoehenwind, Foehn,
Niederschlag, Gewitter, Konvektion, Sicht.

Das System aggregiert nach dem **Weakest-Link-Prinzip** — der **niedrigste**
der 8 Werte bestimmt den Safety-Score (0-100). Sicherheit ist asymmetrisch:
ein perfekter Wind kompensiert kein Gewitter-Risiko. Ein einzelner kritischer
Aspekt darf nicht durch gute Bewertungen anderer Aspekte verdeckt werden.

Formal: `safety_rating = min(wind, gust, aloft, foehn, rain, thunderstorm, cape, visibility)`,
dann `safety_score = safety_rating × 10`.

**Override-Architektur:**
Foehn (`foehn_risk=danger`) und Hoehenwind (`ALOFT-NOT-SAFE`) werden von der
Decision-Engine deterministisch ueberschrieben. Alle anderen Hazards —
insbesondere Niederschlag, Gewitter, CAPE und Sicht — bewertest du selbst.
SubRatingFloor konvertiert automatisch: rating <= 2 → `not_safe`,
rating <= 3 → `conditional`.

**Trend einrechnen — PFLICHT:**
Jedes Sub-Rating ist **vorausschauend**. Bewerte den schlechtesten plausiblen
Zustand waehrend der produktiven Stunden inklusive Trend. Ein Tag mit anfangs
ruhigem Wind, der ab 14h auf 35 km/h zunimmt, bekommt ein niedrigeres Rating
als ein Tag mit konstant 18 km/h — auch wenn der Snapshot um 11h gleich
aussieht. Trend-Vokabular (zunehmend / Aufklaerung / eingekesselt / stabil)
gehoert in `wind_summary` und `summary` als Prosa.

**Skala 1-10 — drei Anker, der Rest ist deine Interpretation:**
- **1** = akut gefaehrlich
- **5** = grenzwertig, spuerbares Risiko
- **10** = unauffaellig, alles klar

Werte 2-4, 6-9 sind Zwischenstufen — entscheide nach Kontext wie nahe der
Tag am jeweiligen Anker liegt. **Nutze die volle Breite** — differenziere
bewusst zwischen 6, 7, 8.

─────────────────────────────────
wind_safety_rating (1-10) — Bodenwind / Mittelwind
─────────────────────────────────

Was bewertet wird: Mittelwind / Wind-Staerke am Startplatz waehrend der
produktiven Stunden, inklusive Trend. **Anstroemrichtung NICHT bewerten** —
Richtung ist Startbarkeit (Tagesfenster), nicht Sicherheit. Falscher Sektor
oder ein Winddreher ist KEIN Sicherheitsthema und darf nie als Grund fuer
`conditional` oder `not_safe` angefuehrt werden.

**VERBOTEN**: `wind_safety_rating <= 5` wegen `[WIND-WRONG]`-Stunden oder Winddrehung — wenn die Windstaerke selbst im grünen Bereich ist, ist das Minimum **7**. Beispiel falsch: "dreht ab 14h aus Sektor → Rating 3". Beispiel richtig: "dreht ab 14h aus Sektor, Staerke 8-12 km/h stabil → Rating 8, Drehung geht in wind_summary".

**Spot-Bemerkung lesen**: Default-Idealbereich ist {{cfg.WIND_IDEAL_MIN_KMH}}-{{cfg.WIND_IDEAL_MAX_KMH}} km/h fuer Thermik-Spots. Soaring-Spots wie z.B. Balderen brauchen einen MINDESTWIND (oft ab 15 km/h) — die Spot-Bemerkung im Prompt-Kontext nennt diese Anforderung explizit. Beruecksichtige sie aktiv.

Anker:
  1  — Stuermisch ({{cfg.WIND_DANGER_KMH}}+ km/h), kompletter Wind-Aufbau ueber den Tag
  5  — Grenzwertig: ueber {{cfg.WIND_WARN_KMH}} km/h ODER unter Spot-Mindestwind ODER Aufbau-Trend
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
`safety_status=not_safe`. Bei `foehn_risk=moderate` ist dein Rating wichtig
— es unterscheidet "leicht moderat" von "schon fast danger".

Anker:
  1  — Akuter Foehn-Durchbruch (foehn_risk=high) oder klar bevorstehend
  5  — Foehn-Vorsicht (foehn_risk=moderate) ODER Aufbau erkennbar
  10 — Keine Foehn-Lage, kein Druckgefaelle, kein Trigger

─────────────────────────────────
rain_safety_rating (1-10) — Niederschlag
─────────────────────────────────

Was bewertet wird: Niederschlag waehrend der Flugstunden. Zeitlicher Verlauf
und Trend aus dem NIEDERSCHLAG-TREND-Block ablesen. Kein Engine-Override —
du bewertest selbst. SubRatingFloor: rating <= 2 → not_safe, <= 3 → conditional.

Anker:
  1  — Eingekesselt: Regen vor UND nach dem Trockenfenster — Regen kehrt
       zurueck. Trockenfenster < 3h immer 1, Trockenfenster >= 4h → 1-2
  5  — Spaetreegen: beginnt nach Fenstermitte, Pilot kann noch sicher landen
       ODER Aufklaerung: Regen endet kurz vor Fensterbeginn
  10 — Kein Niederschlag, trockener Tag

─────────────────────────────────
thunderstorm_safety_rating (1-10) — Gewitter
─────────────────────────────────

Was bewertet wird: Modell-Gewitterprognose im Tagesverlauf. Ablesen aus dem
SICHERHEITS-VERLAUF. Ein Tag mit Gewitter erreicht hoechstens Rating 4 —
Gewitter sind nie mit `safe` vereinbar.

Anker:
  1  — Gewitter aufbauend waehrend Fenster ODER innerhalb Fenster ODER
       Eingekesselt (Gewitter kehrt zurueck)
  4  — Nur Abend (deutlich nach Fenster, kein Aufbau-Trend erkennbar)
       ODER Aufklaerung (Gewitter endet klar vor Fensterbeginn)
  10 — Keine Gewitteranzeichen im Datenblock

─────────────────────────────────
cape_safety_rating (1-10) — Konvektionsenergie / Ueberentwicklung
─────────────────────────────────

Was bewertet wird: CAPE-Werte im Tagesverlauf. Schwellen: 800 J/kg =
erhoehtes Potenzial, 1500 J/kg = extreme Instabilitaet.

Anker:
  1  — CAPE > 1500 J/kg aufbauend ODER waehrend Flugfenster aktiv
  5  — CAPE 800-1500 J/kg mit aktivem Niederschlag (Ueberentwicklung)
       ODER CAPE > 1500 J/kg mit Aufklaerung klar vor Fenster
  10 — CAPE unter 800 J/kg, kein Konvektionspotenzial

─────────────────────────────────
visibility_safety_rating (1-10) — Sicht / Wolkenbasis
─────────────────────────────────

Was bewertet wird: Wolkenbasis auf oder unter Startplatzhoehe
(Cloud-Entry-Risiko). Mittlere und hohe Wolken sind kein Sicherheitsthema —
nur Basis auf/unter Startplatz gefaehrdet Sicht beim Start und Landen.

Anker:
  1  — Basis stabil auf/unter Startplatz ODER sinkend waehrend Fenster
  5  — Basis hebt, Aufklaerung laeuft — Startfenster verzoegert sich
  10 — Wolkenbasis klar ueber Startplatz, keine Sichteinschraenkung

─────────────────────────────────
NUTZUNGS-REGELN
─────────────────────────────────

**Pflicht**: Vergib alle 8 Safety-Sub-Ratings als ganze Zahlen 1-10.

**`hazard_notes` ZUERST ausfuellen — vor den Ratings, vor der Prosa**: Fuelle alle 8 Felder in `hazard_notes` mit je einem konkreten Satz. Das ist dein strukturiertes Nachdenken: du wirst gezwungen, jeden Hazard explizit zu begruenden, bevor du die Ratings vergibst und die Prosa schreibst. Beispiele:
- `"wind": "ZUNEHMEND — morgens 12 km/h, ab 14h auf 40 km/h, WIND-DANGER 14-17h."` → wind_safety_rating 2
- `"wind": "STABIL — 15-20 km/h ganztags, kein Aufbau."` → wind_safety_rating 8
- `"foehn": "AUFBAUEND — Delta-P 4.2→7.8 hPa Sued bis 14h, 850 hPa 38 km/h Sued bestaetigt."` → foehn_safety_rating 2
- `"foehn": "KEIN-FOEHN — Delta-P unter 2 hPa, kein synoptischer Trigger."` → foehn_safety_rating 10
- `"rain": "AUFKLAERUNG — Regen 08-09h, ab 10h trocken, Fenster unbeeintraecht."` → rain_safety_rating 8
- `"rain": "EINGEKESSELT — Regen 07-09h und wieder 16-18h, Trockenfenster 7h."` → rain_safety_rating 3
- `"rain": "KEIN-REGEN — trockener Tag."` → rain_safety_rating 10
- `"thunderstorm": "KEIN-GEWITTER — keine Modell-Prognose, CAPE unter 300 J/kg."` → thunderstorm_safety_rating 10
- `"thunderstorm": "NUR-ABEND — Prognose erst ab 19h, deutlich nach Fensterabschluss."` → thunderstorm_safety_rating 6
- `"cape": "AUFBAUEND — CAPE 1200 J/kg 14-16h bei aktivem Niederschlag, Ueberentwicklung."` → cape_safety_rating 3
- `"cape": "KEIN-AUFBAU — CAPE unter 400 J/kg ganztags."` → cape_safety_rating 10
VERBOTEN: generische Platzhalter-Saetze wie "unauffaellig" ohne Datenbezug, oder leere Strings.

**Bei `safety_status = not_safe`** (egal welcher Trigger — Wind, Foehn,
Gewitter, Regen, CAPE, OVERCAST): alle 5 auf `1` setzen. Der Score muss
numerisch tief ausfallen, sonst entstehen Widersprueche im UI
("alles rot, aber wind_safety=8/10").

**Bei `safety_status = conditional`**: typischerweise mindestens ein Rating
im Bereich 3-6, andere koennen im 7-8-Bereich liegen (z.B. Foehn-Vorsicht bei
sonst ruhigem Wetter).

**Volle Breite nutzen** — wenn der LLM-Run vorher bei "5-7 clustern" stehen
geblieben ist, ist das ein Bug. Differenziere bewusst zwischen 6, 7, 8.

─────────────────────────────────
KONSISTENZ-PFLICHT (HART)
─────────────────────────────────

`safety_status`, die 5 Sub-Ratings UND der Prosa-Text (`summary`,
`wind_summary`, `wind_shear`) MUESSEN ein konsistentes Bild ergeben. Die
Engine pruefte dies und korrigiert Verstoesse (`SubRatingFloor`-Decision) —
Korrekturen werden in der Telemetrie sichtbar gemacht und gelten als Bug.

**Regel 1** — Sub-Ratings binden den Status:
  - Wenn `min(subs) <= 2`  → `safety_status` MUSS `not_safe` sein
  - Wenn `min(subs) <= 3`  → `safety_status` MUSS mindestens `conditional` sein
  - Bei `safety_status = safe` MUESSEN ALLE 5 Sub-Ratings >= 4 sein

**Regel 2** — Prosa muss zum Status passen. Der **erste Satz** der Begruendung
folgt dem Begruendungs-Prinzip aus `03_status_derivation.md` (Abschnitt
"Begruendungs-Prinzip fuer Satz 1"). Dort stehen die Status-Fragen, die
verbotenen Begruendungs-Linien und je ein Beispiel zur Orientierung.

**Konsequenz fuer dich**: Bevor du den Output finalisierst, lies deine
Sub-Ratings. Falls eines <=3 ist, korrigiere `safety_status` UND die Prosa,
SO dass beides zusammenpasst. Es ist NICHT zulaessig, ein niedriges
Sub-Rating zu vergeben und gleichzeitig `safety_status = safe` + "sicherer
Tag"-Prosa zu schreiben.
