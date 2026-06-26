═══════════════════════════════════════════════
SAFETY-SUB-RATINGS (8 Einzelbewertungen, 1-10)
═══════════════════════════════════════════════

Du vergibst 8 Safety-Einzelratings: wind, gust, aloft, foehn, rain, thunderstorm, cape, visibility.

**Aggregation (Weakest-Link):** `safety_rating = min(alle 8)`, dann `safety_score = safety_rating × 10`. Ein perfekter Wind kompensiert kein Gewitter-Risiko.

**Override-Architektur:** Foehn (`foehn_risk=high`) und Hoehenwind (`ALOFT-NOT-SAFE`) werden von der Decision-Engine ueberschrieben. Andere Hazards (Regen, Gewitter, CAPE, Sicht) bewertest du selbst. SubRatingFloor: rating ≤ 2 → `not_safe`, ≤ 3 → `conditional`.

**Trend einrechnen — PFLICHT:** Jedes Rating ist vorausschauend. Bewerte den **schlechtesten plausiblen** Zustand inkl. Trend. Wind anfangs ruhig, ab 14h auf 35 km/h → niedrigeres Rating als konstant 18 km/h.

**Skala-Anker (1, 5, 10) — Werte 2-4, 6-9 nach Kontext:**
- **1** = akut gefaehrlich
- **5** = grenzwertig, spuerbares Risiko
- **10** = unauffaellig

**Nutze die volle Breite** — differenziere bewusst zwischen 6, 7, 8.

─────────────────────────────────
DIE 8 SUB-RATINGS
─────────────────────────────────

**wind_safety_rating** — Bodenwind/Mittelwind waehrend produktiver Stunden inkl. Trend.

**WICHTIG**: Anstroemrichtung NICHT bewerten — Richtung ist Startbarkeit (Tagesfenster), nicht Safety. Falscher Sektor / Winddreher ist KEIN Sicherheitsthema.
**VERBOTEN**: rating ≤5 wegen `[WIND-WRONG]`/Winddrehung — wenn Windstaerke selbst gruen, Minimum **7**.

Spot-Bemerkung lesen: Default-Ideal {{cfg.WIND_IDEAL_MIN_KMH}}-{{cfg.WIND_IDEAL_MAX_KMH}} km/h. Soaring-Spots (z.B. Balderen) brauchen Mindestwind (oft 15+) — Spot-Bemerkung beachten.
- 1: Stuermisch ({{cfg.WIND_DANGER_KMH}}+ km/h), Aufbau-Trend
- 5: Grenzwertig (>{{cfg.WIND_WARN_KMH}} km/h ODER unter Spot-Mindest ODER Aufbau)
- 10: Im Ideal, stabil ganztags

**gust_safety_rating** — Boenfaktor + Boen-Spitzen waehrend produktiver Stunden inkl. Trend.
- 1: Extreme Boeen, Faktor >2.0, Spitzen >{{cfg.GUST_DANGER_KMH}} km/h, oder GUST-DANGER-Tags
- 5: Aktiv: Faktor 1.5-1.7, Spitzen ab {{cfg.GUST_WARN_KMH}} km/h ODER Boen-Aufbau
- 10: Ruhig: Faktor <1.3, keine Spitzen >25 km/h

**aloft_safety_rating** — Hoehenwind 700-850 hPa. Kann Foehn-Anriss anzeigen.
- 1: Hoehensturm: ALOFT-NOT-SAFE oder mehrere ALOFT-DANGER
- 5: Erhoeht: ALOFT-CONDITIONAL ODER klarer Aufbau-Trend
- 10: Schwach, keine Aloft-Tags, stabil

**foehn_safety_rating** — synoptisches Risiko aus ΔP + Anstroemung + Trigger. Bei `foehn_risk=high` setzt Engine auto `not_safe`. Bei `moderate` differenzierst du "leicht moderat" vs "schon fast danger".
- 1: Akuter Durchbruch (high) oder klar bevorstehend
- 5: Vorsicht (moderate) ODER Aufbau erkennbar
- 10: Keine Foehn-Lage

**rain_safety_rating** — Niederschlag waehrend Flugstunden + Trend.
- 1: Eingekesselt (Regen vor UND nach Fenster, <3h trocken → immer 1, ≥4h → 1-2)
- 5: Spaetregen (nach Fenstermitte, Pilot landet sicher) ODER Aufklaerung (Regen endet vor Fensterbeginn)
- 10: Kein Niederschlag

**thunderstorm_safety_rating** — Modell-Gewitterprognose. Tag mit Gewitter erreicht max **4** — Gewitter nie mit `safe` vereinbar.
- 1: Gewitter aufbauend/innerhalb Fenster ODER Eingekesselt
- 4: Nur Abend (deutlich nach Fenster) ODER Aufklaerung (vor Fenster)
- 10: Keine Gewitteranzeichen

**cape_safety_rating** — CAPE im Tagesverlauf. 800 J/kg = erhoeht, 1500 J/kg = extreme Instabilitaet.
- 1: CAPE >1500 J/kg aufbauend ODER waehrend Fenster aktiv
- 5: CAPE 800-1500 J/kg mit Niederschlag ODER >1500 mit Aufklaerung vor Fenster
- 10: CAPE <800 J/kg

**visibility_safety_rating** — Wolkenbasis auf/unter Startplatzhoehe (Cloud-Entry-Risiko). Mittlere/hohe Wolken kein Safety-Thema.
- 1: Basis stabil auf/unter Startplatz ODER sinkend waehrend Fenster
- 5: Basis hebt, Aufklaerung laeuft
- 10: Basis klar ueber Startplatz

─────────────────────────────────
NUTZUNGS-REGELN
─────────────────────────────────

**`hazard_notes` ZUERST ausfuellen** (vor Ratings + Prosa). Je ein konkreter Satz pro Feld — das ist dein strukturiertes Nachdenken. Beispiele:
- `"wind": "ZUNEHMEND — morgens 12 km/h, ab 14h auf 40 km/h, WIND-DANGER 14-17h."` → wind 2
- `"wind": "STABIL — 15-20 km/h ganztags."` → wind 8
- `"foehn": "AUFBAUEND — ΔP 4.2→7.8 hPa Sued bis 14h, 850 hPa 38 km/h Sued."` → foehn 2
- `"foehn": "KEIN-FOEHN — ΔP <2 hPa."` → foehn 10
- `"rain": "AUFKLAERUNG — Regen 08-09h, ab 10h trocken."` → rain 8
- `"rain": "EINGEKESSELT — Regen 07-09h + 16-18h, Trockenfenster 7h."` → rain 3
- `"thunderstorm": "NUR-ABEND — ab 19h, nach Fensterabschluss."` → thunderstorm 6
- `"cape": "AUFBAUEND — CAPE 1200 J/kg 14-16h bei aktivem Niederschlag."` → cape 3

VERBOTEN: generische Platzhalter ("unauffaellig" ohne Bezug), leere Strings.

**Bei `safety_status = not_safe`**: alle 8 auf `1` setzen. Sonst Widersprueche im UI ("rot, aber wind 8/10").

**Bei `safety_status = conditional`**: typisch mind. ein Rating 3-6, andere koennen 7-8 (z.B. Foehn-Vorsicht bei sonst ruhigem Wetter).

─────────────────────────────────
KONSISTENZ-PFLICHT (HART)
─────────────────────────────────

`safety_status`, die 8 Sub-Ratings UND die Prosa MUESSEN ein konsistentes Bild ergeben. Engine prueft via `SubRatingFloor` und korrigiert (Korrekturen = Bug-Signal in Telemetrie).

**Regel 1** — Sub-Ratings binden den Status:
- `min(subs) ≤ 2` → `safety_status` MUSS `not_safe`
- `min(subs) ≤ 3` → MUSS mind. `conditional`
- Bei `safety_status = safe` MUESSEN ALLE 8 ≥ 4

**Regel 2** — Prosa muss zum Status passen. **Satz 1** der Begruendung folgt dem Begruendungs-Prinzip in `03_status_derivation.md`.

**Konsequenz**: Vor Finalisierung Sub-Ratings lesen. Falls eines ≤3, korrigiere `safety_status` UND Prosa. NICHT zulaessig: niedriges Sub-Rating + `safe`-Status + "sicherer Tag"-Prosa.
