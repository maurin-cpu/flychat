═══════════════════════════════════════════════
KERNREGEL — Stunden-Klassifikation
═══════════════════════════════════════════════

Jede Stunde hat **zwei unabhaengige Eigenschaften**:

**Achse 1 — Flug-Gefahr** (physische Gefahr fuer den Piloten in der Luft):
- **RUHIG** — keine WARN-Tags, keine DANGER-Tags. Komfortabel, anfaengerfreundlich.
- **SPORTLICH** — ≥1 WARN-Tag (WIND-WARN, ALOFT-WIND-WARN, CAPE-WARN), kein DANGER-Tag.
- **UNFLIEGBAR** — ≥1 DANGER-Tag (RAIN-WARN, WIND-DANGER, ALOFT-WIND-DANGER, CAPE-DANGER, THUNDERSTORM, OVERCAST-DANGER).

**Achse 2 — Start-Moeglichkeit** (Region: nicht relevant):
- Region hat keinen Sektor → **STARTBAR** ist gegeben, solange `[WIND-DANGER]` nicht greift.

**"Saubere Stunde"** = nicht UNFLIEGBAR. **"Sauberes Fenster"** = mehrere zusammenhaengende saubere Stunden.

**Regel `safe_window`:**
- = das fliegbare Fenster (RUHIG + SPORTLICH zusammen).
- SPORTLICHE Stunden im Fenster MUESSEN in `caution_notes` mit Uhrzeit und Grund stehen (z.B. "WIND-WARN 13-16h: Hoehenwind 32 km/h, sportlich").
- UNFLIEGBARE Stunden gehoeren NIEMALS ins `safe_window`.

═══════════════════════════════════════════════
TREND-VOKABULAR (7 Muster)
═══════════════════════════════════════════════

Jeder Tag folgt bei jeder Gefahr (Regen, Wind, Hoehenwind, CAPE, Wolken) einem dieser 7 Muster. Foehn ist Ausnahme (siehe Block 5: severity-pauschal, kein Trend).

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
→ Block traegt NICHT zum Status bei. In `caution_notes` nur erwaehnen, wenn aktive Entwarnung (z.B. "CAPE bleibt unter 500 J/kg, keine Ueberentwicklung") oder zustandsbeschreibend ("Wind stabil bei 18 km/h auf Referenzhoehe").


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
- **DANGER aussen + Fenster 3-4h + RUHIG innen** → `conditional` grenzwertig. Bei Zusatzrisiken (Konvektion, weitere WARN-Tags) → `not_safe`.
- **DANGER aussen + Fenster <3h** ODER **DANGER aussen + Fenster mit SPORTLICHEN durchsetzt** → `not_safe`, `primary_no_go = EINGEKESSELT`.


─────────────────────────────────
EINGEKESSELT — 2 Sonderfaelle
─────────────────────────────────

**Sonderfall 1 — Hoehenwind (Block 4):**
Zusaetzlich pruefen: Ist die zweite Gefahrenphase SCHLIMMER als die erste?
- **Eskalierend** (zusaetzliche harte Tags wie ALOFT-WIND-DANGER ODER deutlich laenger ODER WARN→DANGER ueber Fenster hinweg) → eine Stufe **strenger** als Standardregel.
- **Symmetrisch** (gleiche Schwere beidseitig, etwa gleich lang) → Regel 1:1.

**Sonderfall 2 — Boden-Gefahren (Bodenwind, Regen):**
Bei DANGER am BODEN gelten **strengere Schwellen**, weil die Landung direkt betroffen waere.

- **Fenster <5h** → **immer `not_safe`**, auch durchgehend RUHIG innen.
- **Fenster ≥5h + RUHIG innen** → `conditional` moeglich. Pilot MUSS ≥90 min vor Rueckkehr gelandet sein. `caution_notes`: explizit Timing-Risiko + harte Landezeit.
- **Fenster ≥5h, mit SPORTLICHEN durchsetzt** → `not_safe` (effektiver Puffer zu klein).

═══════════════════════════════════════════════
GEFAHRENBLOECKE (Region: 6 Bloecke, kein Boeen)
═══════════════════════════════════════════════

─────────────────────────────────
BLOCK 1 — REGEN & FRONT
─────────────────────────────────

**Tags:** `[RAIN-WARN]` → Stunde UNFLIEGBAR.

Jede `[RAIN-WARN]`-Stunde zaehlt direkt als DANGER-Level (kein WARN/DANGER-Split). Regen trifft Landung → **Sonderfall 2** bei EINGEKESSELT.

`[RAIN-WARN]` macht NUR die betroffene Stunde unfliegbar, NICHT den ganzen Tag — aber das **Muster** (TREND-VOKABULAR) bestimmt den Status. Sauberes Fenster zwischen Regenphasen ist NICHT automatisch safe.

─────────────────────────────────
BLOCK 2 — BODENWIND (Staerke, kein Sektor)
─────────────────────────────────

**Tags:**
- `[WIND-WARN]` → sportlich ({{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h).
- `[WIND-DANGER]` → unfliegbar (> {{cfg.WIND_DANGER_KMH}} km/h).
- Kein Tag (< {{cfg.WIND_WARN_KMH}} km/h) → ruhig.

**WIND-TREND-Pflicht (Boden + Hoehe summiert):**
Bodenwind und Hoehenwind teilen sich denselben Trend, weil die Schwellen identisch sind. Die `WIND-TREND`-Zeile (siehe Block 4 fuer Pattern-Mapping) deckt beide Quellen gemeinsam ab. **Kein separater Bodenwind-Trend** — nutze ausschliesslich die WIND-TREND-Zeile fuer Status-Ableitungen bei Wind.

System liefert die Zahlen — **nicht selbst nachzaehlen**.

─────────────────────────────────
BLOCK 3 — HOEHENWIND (FLUGSCHICHT)
─────────────────────────────────

**Tags Hoehe** (gelten NUR fuer Hoehen mit Marker `*` im Flugbereich):
- `[ALOFT-WIND-DANGER]` → unfliegbar (Hoehenwind > {{cfg.WIND_DANGER_KMH}} km/h). **Ab {{cfg.WIND_TREND_NOTSAFE_HOURS}}h pro Tag (oder Bodenwind > {{cfg.WIND_DANGER_KMH}} km/h ≥{{cfg.WIND_TREND_NOTSAFE_HOURS}}h) → hartes NO-GO** (Post-Processing zwingt `not_safe`) — **AUSSER** `WIND-TREND` zeigt AUFKLAERUNG / VEREINZELT / EINGEKESSELT_KNAPP mit sauberem Fenster ≥ {{cfg.WIND_TREND_NOTSAFE_HOURS}}h. Dann max `conditional`, `safe_window` auf das saubere Fenster.
- `[ALOFT-WIND-WARN]` → Hoehenwind WARN-Level — sportlich.

**Wichtig:** WIND-TREND deckt Bodenwind UND Hoehenwind gemeinsam ab (gleiche Schwellen, summierte Stunden).

**Schwellen:** Wind WARN = {{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h / DANGER > {{cfg.WIND_DANGER_KMH}} km/h (Boden + Hoehe gleich). Flugschichtgefahr → **Sonderfall 1** bei EINGEKESSELT.

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

**WICHTIG:** Wenn binaere Tags KEINE harte Warnung zeigen, du aber im FLUGSCHICHT-Verlauf klaren Verschlechterungs-Trend siehst (Wind 30+ und steigend, Foehn-Hinweise, Scherung), darfst und MUSST du auf **conditional**/**not_safe** setzen mit Begruendung. Umgekehrt: 850/700 ohne Marker brutal, Flugbereich aber ruhig → kein Sicherheitsproblem.

─────────────────────────────────
BLOCK 4 — FOEHN
─────────────────────────────────

**Foehn ist Ausnahme:** Severity-pauschal, KEIN Trend-Muster, KEIN Fenster-Konzept. Foehn ist Luftmassen-Eigenschaft — kein "sauberes Fenster" mitten im Foehntag, Druckabfaelle und Turbulenz durchziehen alles.

**Richtungs-Check ZUERST** (harte Filterung, siehe `_region_context.md`):
- Region hat `Kritischer Foehn: Sued | Nord | Beide`.
- Wenn Richtung nicht passt: `foehn_risk = "none"`, ignorieren.

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
BLOCK 5 — KONVEKTION / UEBERENTWICKLUNG (3 Tiers)
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
BLOCK 6 — WOLKEN & SICHT
─────────────────────────────────

**Tags:**
- `[OVERCAST-DANGER]` → unfliegbar (dichte Decke mit Basis nahe Flughoehe — Cloud-Entry-Risiko).

**Wolkenbasis-Check:**
- Basis < 1000m MSL generell kritisch.
- Faustregel: Basis hoch genug ueber Region-Referenzhoehe = unproblematisch, egal wie viel Bedeckung.

**Bewoelkungs-Differenzierung** (`Bewoelkung X% (tief Y%, mittel Z%, hoch W%)`):
- **Hoch (Cirrus)**: kein Sicherheitsrisiko — Basis 6000-10'000m, weit ueber Flughoehe. Auch 100% harmlos.
- **Mittel (Altostratus)**: i.d.R. kein Sicherheitsrisiko — Basis 3000-6000m.
- **Tief**: Basis pruefen!

**Merke:** Bewoelkung reduziert Thermik — Fliegbarkeits-Thema (Teil 2), KEIN Sicherheitsthema.
