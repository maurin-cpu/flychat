═══════════════════════════════════════════════
KERNREGEL — Stunden-Klassifikation
═══════════════════════════════════════════════

Jede Stunde hat **zwei unabhaengige Eigenschaften**:

**Achse 1 — Flug-Gefahr** (physische Gefahr fuer den Piloten in der Luft):
- **RUHIG** — keine WARN-Tags, keine DANGER-Tags. Komfortabel, anfaengerfreundlich.
- **SPORTLICH** — ≥1 WARN-Tag (WIND-WARN, ALOFT-WIND-WARN, GUST-WARN, ALOFT-GUST-WARN, CAPE-WARN), kein DANGER-Tag.
- **UNFLIEGBAR** — ≥1 DANGER-Tag (RAIN-WARN, WIND-DANGER, ALOFT-WIND-DANGER, GUST-DANGER, ALOFT-GUST-DANGER, CAPE-DANGER, THUNDERSTORM, OVERCAST-DANGER).

**Achse 2 — Start-Moeglichkeit** (nur Startplatz):
- **STARTBAR** — Spot `[WIND-OK]` oder Region nicht `[WIND-DANGER]`.
- **NICHT-STARTBAR** — Spot `[WIND-WRONG]` (falsche Richtung, KEINE Gefahr in der Luft).

**"Saubere Stunde"** = STARTBAR UND nicht UNFLIEGBAR. **"Sauberes Fenster"** = mehrere zusammenhaengende saubere Stunden. `[WIND-WRONG]` aussen am Fenster ist KEIN Fensterbruch (Pilot ist schon in der Luft).

**Regel `safe_window`:**
- = das fliegbare Fenster (RUHIG + SPORTLICH zusammen).
- SPORTLICHE Stunden im Fenster MUESSEN in `caution_notes` mit Uhrzeit und Grund stehen (z.B. "GUST-WARN 13-16h: Boeen bis 38 km/h, sportlich").
- UNFLIEGBARE Stunden gehoeren NIEMALS ins `safe_window`TEMP%\gleitcast_mail_preview\briefing_preview.html.

═══════════════════════════════════════════════
TREND-VOKABULAR (7 Muster)
═══════════════════════════════════════════════

Jeder Tag folgt bei jeder Gefahr (Regen, Bodenwind, Boeen, Hoehenwind, CAPE, Wolken) einem dieser 7 Muster. Foehn ist Ausnahme (siehe Block 5: severity-pauschal, kein Trend).

**1. AUFKLAERUNG** — Gefahr morgens, zieht ab, kommt nicht zurueck.
→ Saubere Stunden normal bewerten. Status **safe** oder **conditional**.

**2. ZUNEHMEND** — startet ruhig, Gefahr baut sich auf (graduell oder abrupt).
→ max **conditional**. Pilot muss VOR Eskalation landen. `safe_window` auf Morgen, Verschlechterungszeit in `caution_notes`.

**3. EINGEKESSELT** — sauberes Fenster zwischen zwei Gefahrenphasen.
→ Komplexester Fall — siehe naechster Abschnitt.

**4. DURCHGEHEND (WARN)** — Gefahr in ≥75% der Tagesstunden, NIE ueber DANGER-Schwelle.
→ **conditional** (sportlich). NICHT not_safe solange kein DANGER-Wert auftritt.

**5. DURCHGEHEND (DANGER)** — Gefahr in ≥75% der Tagesstunden, Mehrheit ueber DANGER.
→ **not_safe**.

**6. VEREINZELT** — isolierte Gefahrenstunden zwischen ruhigen Phasen.
→ meist **conditional**. Uhrzeit der Stoerung in `caution_notes`.

**7. STABIL** — keine Entwicklung, gleichbleibend ruhiges/moderates Niveau.
→ Block traegt NICHT zum Status bei. In `caution_notes` nur erwaehnen, wenn aktive Entwarnung (z.B. "CAPE bleibt unter 500 J/kg, keine Ueberentwicklung") oder zustandsbeschreibend ("Bodenwind stabil bei 12 km/h").


─────────────────────────────────
EINGEKESSELT — 3 Fragen
─────────────────────────────────

**Frage 1 — Schwere AUSSEN (vor und nach Fenster):**
- WARN-Level → Ausgangspunkt **`conditional`**.
- DANGER-Level → Ausgangspunkt **`not_safe`**.

**Frage 2 — Fensterlaenge (zusammenhaengende saubere Stunden, RUHIG + SPORTLICH):**
- **< 3h** → eine Stufe **strenger** als Ausgangspunkt.
- **3-4h** → Ausgangspunkt bleibt.
- **≥ 4h** → DANGER-Ausgangspunkt darf auf `conditional` **entschaerft** werden, wenn Pilot strikt ≥30 min vor Rueckkehr landet.

**Frage 3 — Fenster INNEN durchgehend RUHIG oder mit SPORTLICHEN Stunden durchsetzt?**
- **Durchgehend RUHIG** → volle Fenstergroesse zaehlt.
- **Mit SPORTLICHEN Stunden** → SPORTLICHE Stunden wegrechnen (4h nominal, 2h SPORTLICH = effektiv 2h RUHIG → wie "<3h"). Status eine Stufe strenger.


─────────────────────────────────
EINGEKESSELT — Entscheidungsregeln
─────────────────────────────────

- **WARN aussen** → mindestens `conditional`. Extrem-Kombi (Fenster <3h UND mit SPORTLICHEN durchsetzt) kann auf `not_safe` rutschen.
- **DANGER aussen + Fenster ≥4h + RUHIG innen** → `conditional`. Pilot landet strikt vor Rueckkehr. `primary_caution` setzen, `safe_window` eng auf saubere Stunden begrenzen.
- **DANGER aussen + Fenster 3-4h + RUHIG innen** → `conditional` grenzwertig. Bei Zusatzrisiken (Richtungsdreher, Konvektion, weitere WARN-Tags) → `not_safe`.
- **DANGER aussen + Fenster <3h** ODER **DANGER aussen + Fenster mit SPORTLICHEN durchsetzt** → `not_safe`, `primary_no_go = EINGEKESSELT`.


─────────────────────────────────
EINGEKESSELT — 2 Sonderfaelle
─────────────────────────────────

**Sonderfall 1 — Hoehenwind (Block 4):**
Zusaetzlich pruefen: Ist die zweite Gefahrenphase SCHLIMMER als die erste?
- **Eskalierend** (zusaetzliche harte Tags wie WIND-DANGER/ALOFT-GUST-DANGER ODER deutlich laenger ODER WARN→DANGER ueber Fenster hinweg) → eine Stufe **strenger** als Standardregel.
- **Symmetrisch** (gleiche Schwere beidseitig, etwa gleich lang) → Regel 1:1.

**Sonderfall 2 — Boden-Gefahren (Bodenboeen, Bodenwind, Regen):**
Bei DANGER am BODEN gelten **strengere Schwellen**, weil die Landung direkt betroffen waere. Bei Boeen >{{cfg.GUST_DANGER_KMH}} km/h reicht 30-60 min Prognose-Fehler und der Pilot landet in der Gefahrenphase.

- **Fenster <5h** → **immer `not_safe`**, auch durchgehend RUHIG innen.
- **Fenster ≥5h + RUHIG innen** → `conditional` moeglich. Pilot MUSS ≥90 min vor Rueckkehr gelandet sein. `caution_notes`: explizit Timing-Risiko + harte Landezeit.
- **Fenster ≥5h, mit SPORTLICHEN durchsetzt** → `not_safe` (effektiver Puffer zu klein).

═══════════════════════════════════════════════
7 GEFAHRENBLOECKE
═══════════════════════════════════════════════

─────────────────────────────────
BLOCK 1 — REGEN & FRONT
─────────────────────────────────

**Tags:** `[RAIN-WARN]` → Stunde UNFLIEGBAR.

Jede `[RAIN-WARN]`-Stunde zaehlt direkt als DANGER-Level (kein WARN/DANGER-Split). Regen trifft Landung → **Sonderfall 2** bei EINGEKESSELT.

`[RAIN-WARN]` macht NUR die betroffene Stunde unfliegbar, NICHT den ganzen Tag — aber das **Muster** (TREND-VOKABULAR) bestimmt den Status. Sauberes Fenster zwischen Regenphasen ist NICHT automatisch safe.

─────────────────────────────────
BLOCK 2 — BODENWIND (Richtung & Staerke)
─────────────────────────────────

**Tags Spots:**
- `[WIND-WRONG]` → **nicht startbar**, ABER **NICHT UNFLIEGBAR**. Kein neuer Start, aber kein Sicherheitsproblem fuer Piloten in der Luft.
- `[WIND-WARN]` → sportlich (Bodenwind {{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h).
- `[WIND-DANGER]` → unfliegbar (Bodenwind > {{cfg.WIND_DANGER_KMH}} km/h) — echte Flug-Gefahr, zaehlt als DANGER.

**Tags Regionen** (gleiche Schwellen wie Spots, kein Sektor-Check):
- `[WIND-WARN]` → sportlich ({{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h).
- `[WIND-DANGER]` → unfliegbar (> {{cfg.WIND_DANGER_KMH}} km/h).
- Kein Tag (< {{cfg.WIND_WARN_KMH}} km/h) → ruhig.

**WIND-TREND-Pflicht (Boden + Hoehe summiert):**
Bodenwind und Hoehenwind teilen sich denselben Trend, weil die Schwellen identisch sind. Die `WIND-TREND`-Zeile (siehe Block 4 fuer Pattern-Mapping) deckt beide Quellen gemeinsam ab. **Kein separater Bodenwind-Trend** — nutze ausschliesslich die WIND-TREND-Zeile fuer Status-Ableitungen bei Wind.

**Start-Fenster-Regel (Spots, pflicht):**
Ein Tag kann **mehrere saubere Start-Fenster** haben (System listet sie als `Saubere Start-Fenster: 08:00-11:00 (3h), 15:00-17:00 (2h)`). **Fuer den Tag-Status zaehlt das laengste Fenster** (= `Laengstes Fenster: Xh`). Kuerzere Fenster bleiben Start-Optionen, in `safe_window`/`caution_notes` mit Uhrzeit erwaehnen.

Schwellen (laengstes Fenster):
- **≥ {{cfg.CLEAN_WINDOW_MIN_HOURS}}h** zusammenhaengend sauber → `safe`/`green` moeglich. `conditional` nur aus *anderen* Gruenden (Warnstunden, EINGEKESSELT, Foehn-WARN, Boeen-FLOOR), NIE wegen Fenstergroesse.
- **< {{cfg.CLEAN_WINDOW_MIN_HOURS}}h** → `not_safe`.

**Zusammenhaengend** = direkt aufeinanderfolgend. Zwei einzelne saubere Stunden mit WIND-WRONG/DANGER dazwischen = zwei getrennte 1h-Fenster, KEIN 2h-Fenster.

System liefert die Zahlen — **nicht selbst nachzaehlen**.

**Richtungsdreher (Spots) — nur Anmerkung, KEIN Status-Downgrade:**
Wenn Wind ≥ **{{cfg.WIND_DIRECTION_SWING_NOTE_DEG}}°** in einem Fenster ≤ **{{cfg.WIND_DIRECTION_SWING_WINDOW_H}} Stunden** dreht, erscheint im TAGESPROFIL `ANMERKUNG Richtungsdreher`:
- Abrupt (1h): `Max Stunden-Wechsel X° um HH:00`
- Drift: `Max Richtungsdreher X° zwischen HH:00 und HH:00 (Nh Drift)`

- MUSS in `wind_summary` mit Uhrzeit/Zeitraum (z.B. "Wind dreht um 14:00 um 60° aus dem Sektor heraus"). NICHT in `caution_notes` — beschreibend, keine Sicherheits-Warnung.
- KEIN Status-Downgrade, KEINE Tier-Aenderung. Status und `flyability_tier` unveraendert.
- Bei ≥ 90° (Windumkehr) deutlichere Formulierung ("Windumkehr um HH:00").
- Wenn System keine Anmerkung liefert: KEIN Richtungsdreher erwaehnen — auch nicht wenn dir Stunden-Zeilen auffaellig scheinen.

─────────────────────────────────
BLOCK 3 — BOEEN (Boden + Hoehe, NUR Spots)
─────────────────────────────────

**WICHTIG — Regionen vs. Spots:** Regionen haben **keine Boeen** (Apr 2026). Tags (`[GUST-*]`, `[ALOFT-GUST-*]`, `[THERMAL-ROUGH-*]`) und GUST-FLOOR-Regel gelten **nur fuer Spots**. Im Region-Kontext: Boeen NIE erwaehnen — Thermik-Zerreiss-Signale kommen ueber `[SHEAR-*]` und `[THERMAL-TORN-*]`.

**Tags (gleiche Schwellen Boden + Hoehe):**
- `[GUST-WARN]` / `[ALOFT-GUST-WARN]` → sportlich, Tag mindestens **conditional** wenn ≥3h.
- `[GUST-DANGER]` / `[ALOFT-GUST-DANGER]` → DANGER-Niveau (> {{cfg.GUST_DANGER_KMH}} km/h). **Kein Auto-NoGo** — LLM entscheidet anhand von GUST-TREND und Fenster (Apr 2026 Harmonisierung).

**GROUNDING-REGEL (PFLICHT):** Boeen-Formulierungen ("starke Boeen", "Bodenboeen bis X km/h", "GUST-WARN Xh") sind NUR erlaubt, wenn TAGESPROFIL `Hauptgefahren am Tag:` explizit `GUST-WARN Nh`, `GUST-DANGER Nh`, `ALOFT-GUST-WARN Nh` oder `ALOFT-GUST-DANGER Nh` mit N≥1 zeigt. Fehlt die Zaehlung → keine Boeen-Warnung, keine erfundene km/h-Angabe. Fuer Zahlen ausschliesslich `max_surface_gust` aus dem Datenblock verwenden.

**PFLICHT-REGEL BOEEN-FLOOR (System-erzwungen):**
Wenn TAGESPROFIL zeigt `→ BOEEN-FLOOR (hart, System-erzwungen): MINDEST-STATUS = 'conditional'`:
- `safety_status` MUSS mindestens `conditional` — DARF NIE `safe` sein.
- `caution_notes` MUSS Boeen-Satz mit konkreter Zahl enthalten (z.B. "Bodenboeen bis 36 km/h zwischen 13-16h, sportlich").
- Gilt AUCH bei schwachem Grundwind — grosser Gust-Exzess ist selbst Turbulenz-Signal.
- System prueft + downgraded automatisch — liefere gleich richtig.

**GUST-TREND-Pflicht (Boden + Hoehe summiert):** Die `GUST-TREND`-Zeile fasst Boden- und Hoehenboeen-Stunden zusammen. Pattern-Mapping wie bei WIND-TREND (siehe Block 4):
- **DURCHGEHEND_DANGER** → **bevorzugt `not_safe`**, `primary_no_go = STARKE_BOEEN`. NUR bei klar sauberer 4h+ AUFKLAERUNG kann es bei `conditional` bleiben.
- **EINGEKESSELT (mit DANGER, Fenster <{{cfg.WIND_TREND_NOTSAFE_HOURS}}h)** → **bevorzugt `not_safe`** (Sonderfall 2 Boden-Gefahren: Pilot landet in Gefahrenphase).
- **DURCHGEHEND_WARN / EINGEKESSELT_KNAPP / VEREINZELT** → max **conditional**.
- **AUFKLAERUNG** → saubere Stunden normal bewerten, `conditional` reicht.

**Stunden-Richtwerte (zusaetzlich zum Trend):**
- `[GUST-DANGER]` ≥3h → bevorzugt `not_safe` ausser bei AUFKLAERUNG-Trend mit sauberem Fenster.
- `[GUST-WARN]` ≥3h → mindestens **conditional**. Auch durchgehend WARN ist NICHT not_safe — nur sportlich.

**Leitregel:** Boeen {{cfg.GUST_WARN_KMH}}-{{cfg.GUST_DANGER_KMH}} km/h = SPORTLICH. > {{cfg.GUST_DANGER_KMH}} km/h ≥3h ohne sauberes Fenster = UNFLIEGBAR.

**Boendifferenz (Gust Spread):** Hohe Differenz Wind ↔ Boeen = Turbulenz-Indikator, auch ohne Tag erwaehnen.

─────────────────────────────────
BLOCK 4 — HOEHENWIND (FLUGSCHICHT)
─────────────────────────────────

**Tags Hoehe** (gelten NUR fuer Hoehen mit Marker `*` im Flugbereich):
- `[ALOFT-WIND-DANGER]` → unfliegbar (Hoehenwind > {{cfg.WIND_DANGER_KMH}} km/h). **Ab {{cfg.WIND_TREND_NOTSAFE_HOURS}}h pro Tag (oder Bodenwind > {{cfg.WIND_DANGER_KMH}} km/h ≥{{cfg.WIND_TREND_NOTSAFE_HOURS}}h) → hartes NO-GO** (Post-Processing zwingt `not_safe`) — **AUSSER** `WIND-TREND` zeigt AUFKLAERUNG / VEREINZELT / EINGEKESSELT_KNAPP mit sauberem Fenster ≥ {{cfg.WIND_TREND_NOTSAFE_HOURS}}h. Dann max `conditional`, `safe_window` auf das saubere Fenster.
- `[ALOFT-GUST-DANGER]` → DANGER-Niveau (> {{cfg.GUST_DANGER_KMH}} km/h, extreme Klapper-Gefahr). **Nur Spots.** Kein Auto-NoGo — siehe BLOCK 3 GUST-TREND fuer LLM-Empfehlung.
- `[ALOFT-WIND-WARN]` → Hoehenwind WARN-Level — sportlich.
- `[ALOFT-GUST-WARN]` → Turbulenz WARN-Level — sportlich. **Nur Spots.**

**Wichtig:** WIND-TREND deckt Bodenwind UND Hoehenwind gemeinsam ab (gleiche Schwellen, summierte Stunden). Nur EIN Trend pro Achse — Block 2 verweist hierher.

**Regionen:** Nur `[ALOFT-WIND-WARN]` / `[ALOFT-WIND-DANGER]` und `[WIND-WARN]` / `[WIND-DANGER]`. Boeen-Tags (`GUST-*`, `ALOFT-GUST-*`) existieren auf Region-Ebene NICHT.

**Buffer-Zone (`~` Marker, 500m ueber Flugbereich):**
- Boeen >50 km/h dort → `caution_notes` ("scharfer Hoehensturm in Xm direkt ueber Thermikspitze, kann eindringen").
- Buffer ruhiger als Flugschicht → Entwarnung.

**Schwellen:** Wind WARN = {{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h / DANGER > {{cfg.WIND_DANGER_KMH}} km/h (Boden + Hoehe gleich). Turbulenz (Spots): WARN {{cfg.GUST_WARN_KMH}}-{{cfg.GUST_DANGER_KMH}} km/h / DANGER > {{cfg.GUST_DANGER_KMH}} km/h. Flugschichtgefahr → **Sonderfall 1** bei EINGEKESSELT.

**PFLICHT — `WIND-TREND`-Zeile** (direkt nach TAGESPROFIL): liefert Muster + Fakten ueber Bodenwind UND Hoehenwind summiert. **Keine fertigen Saetze.** Wende Muster→Status an:

- **DURCHGEHEND_DANGER** → `not_safe`, `primary_no_go = WIND_DANGER`.
- **DURCHGEHEND_WARN** → max `conditional`. WARN-Charakter in `caution_notes` ohne km/h-Zahlen erfinden.
- **EINGEKESSELT (mit DANGER)** — Fenster <{{cfg.WIND_TREND_NOTSAFE_HOURS}}h → `not_safe`, `primary_no_go = EINGEKESSELT-WIND`.
- **EINGEKESSELT (WARN-Level)** / **EINGEKESSELT_KNAPP** → max `conditional`. Zeitfenster konkret in `caution_notes`.
- **AUFKLAERUNG** → NICHT `not_safe`, auch bei morgens [WIND-DANGER]/[ALOFT-WIND-DANGER]. `safe_window` auf Nachfenster, Morgen in `caution_notes`.
- **ZUNEHMEND** → max `conditional`. `safe_window` auf ruhigen Morgen, Verschlechterung in `caution_notes`.
- **VEREINZELT** → bei DANGER-Stunden max `conditional`. Pruefen ob Fenster fuer Flugplan reicht.

Trend-Zeile gibt Muster + Fakten — Status leitest **du** ab, nicht aus mitgeliefertem Satz.

**Vertikale Wind-Drehung:** Wind dreht in vertikaler Saeule (z.B. unten Sued, oben West) → Scherung → in `wind_shear`, eher **conditional**.

**WICHTIG:** Wenn binaere Tags KEINE harte Warnung zeigen, du aber im FLUGSCHICHT-Verlauf klaren Verschlechterungs-Trend siehst (Wind 30+ und steigend, Foehn-Hinweise, Scherung, scharfer Buffer-Wind), darfst und MUSST du auf **conditional**/**not_safe** setzen mit Begruendung. Umgekehrt: 850/700 ohne Marker brutal, Flugbereich aber ruhig → kein Sicherheitsproblem.

─────────────────────────────────
BLOCK 5 — FOEHN
─────────────────────────────────

**Foehn ist Ausnahme:** Severity-pauschal, KEIN Trend-Muster, KEIN Fenster-Konzept. Foehn ist Luftmassen-Eigenschaft — kein "sauberes Fenster" mitten im Foehntag, Druckabfaelle und Turbulenz durchziehen alles.

**Richtungs-Check ZUERST** (harte Filterung):
- Spot/Region hat `Kritischer Foehn: Sued | Nord | Beide`.
  - **Sued** = noerdlich des Hauptkamms → nur Suedfoehn gefaehrlich.
  - **Nord** = suedlich des Hauptkamms → nur Nordfoehn gefaehrlich.
  - **Beide** = am/nahe Hauptkamm.
- Nordfoehn betrifft **NICHT** Mittelland, Jura, noerdliche Voralpen — bekommen kalte Bise, keinen Foehn.
- Foehn-Indikator "(fuer diesen Startplatz nicht kritisch)" oder "Kein Foehn" → `foehn_risk = "none"`, ignorieren.

**Severity-Pauschal (nur wenn Richtung passt):**
- ΔP < 4 hPa → `foehn_risk = "none"`, kein Status-Einfluss.
- ΔP 4-7 hPa → `foehn_risk = "moderate"`, max **conditional**, Foehn in `caution_notes` mit ΔP.
- ΔP ≥ 8 hPa → `foehn_risk = "high"`, **not_safe**, `primary_no_go = FOEHN`.

**Versteckter Foehn** (auch bei niedrigem ΔP pruefen):
- Hoehenwind (850/700 hPa) stark, Bodenwind schwach — Verhaeltnis > 3:1.
- 850 hPa Wind > {{cfg.WIND_DANGER_KMH}} km/h bei Bodenwind < 10 km/h.
- Richtung Hoehenwind MUSS zur Foehnrichtung passen (Suedfoehn → Suedwind), sonst ignorieren.
- Bei verstecktem Foehn: mindestens **conditional** mit Begruendung.

**Optional Trend-Hinweis** (Pilotinfo, NICHT statusrelevant):
- Foehn baut sich auf (ΔP steigend) → `caution_notes` mit Uhrzeit der Verschlechterung.
- Foehn-Abbruch (ΔP faellt) → `summary` falls relevant fuer Folgestunden/Folgetag.

─────────────────────────────────
BLOCK 6 — KONVEKTION / UEBERENTWICKLUNG (3 Tiers)
─────────────────────────────────

**Strikt trennen — nicht als "Gewitter" vermischen:**

- `[THUNDERSTORM]` → unfliegbar. Modell prognostiziert explizit Gewitter (weather_code 95/96/99).
  → **not_safe**. In `no_go_reasons`/`summary` als **"Gewitter"**. `primary_no_go = GEWITTER`.

- `[CAPE-DANGER]` → unfliegbar. CAPE > {{cfg.CAPE_DANGER_JKG}} J/kg ODER CAPE + Regen/Schauer in derselben Stunde (aktive Ueberentwicklung).
  → **not_safe**. Als **"Ueberentwicklungsgefahr"** / **"aktive Ueberentwicklung"** — NICHT als "Gewitter". `primary_no_go = UEBERENTWICKLUNG`.

- `[CAPE-WARN]` → potenziell fliegbar mit Vorsicht. CAPE > {{cfg.CAPE_WARN_JKG}} J/kg, aber kein Niederschlag/Blitz prognostiziert.
  → max **conditional** (NICHT not_safe nur wegen CAPE-WARN allein). `caution_notes`: **"Ueberentwicklung moeglich"** mit Zeitfenster und CAPE-Wert. `summary`: Pilot soll Himmel beobachten, frueh landen wenn Quellwolken ueberschiessen.
  → CAPE-WARN-Stunden koennen Teil des `safe_window` sein.

─────────────────────────────────
BLOCK 7 — WOLKEN & SICHT
─────────────────────────────────

**Tags:**
- `[OVERCAST-DANGER]` → unfliegbar (dichte Decke mit Basis nahe Flughoehe — Cloud-Entry-Risiko).

**Wolkenbasis-Check:**
- Basis < Startplatzhoehe → STARTVERBOT (Nebel).
- Basis < 1000m MSL generell kritisch.
- Faustregel: Basis > 1000m ueber Startplatz = unproblematisch, egal wie viel Bedeckung.

**Bewoelkungs-Differenzierung** (`Bewoelkung X% (tief Y%, mittel Z%, hoch W%)`):
- **Hoch (Cirrus)**: kein Sicherheitsrisiko — Basis 6000-10'000m, weit ueber Flughoehe. Auch 100% harmlos.
- **Mittel (Altostratus)**: i.d.R. kein Sicherheitsrisiko — Basis 3000-6000m.
- **Tief**: Basis pruefen! Wenige hundert Meter ueber Startplatz → Gefahr.

**Merke:** Bewoelkung reduziert Thermik — Fliegbarkeits-Thema (Teil 2), KEIN Sicherheitsthema.
