═══════════════════════════════════════════════
KERNREGEL — Stunden-Klassifikation
═══════════════════════════════════════════════

Jede Stunde im TAGESPROFIL gehoert in genau eine von drei Kategorien:

- **RUHIG** — Windrichtung passt (Spot: [WIND-OK] / Region: [WIND-CALM] oder [WIND-MODERATE]) UND **keine WARN-Tags** UND **keine DANGER-Tags**. Komfortabel fliegbar, anfaengerfreundlich.

- **SPORTLICH** — Windrichtung passt UND **mindestens 1 WARN-Tag** (GUST-WARN, ALOFT-WARN, ALOFT-GUST-WARN, CAPE-WARN), ABER **kein DANGER-Tag**. Fliegbar fuer erfahrene Piloten.

- **UNFLIEGBAR** — **mindestens 1 DANGER-Tag** (RAIN-WARN, STRONG-WIND-WARN, GUST-DANGER, ALOFT-DANGER, ALOFT-GUST-DANGER, CAPE-DANGER, THUNDERSTORM, OVERCAST-DANGER) ODER Windrichtung falsch ([WIND-WRONG], [WIND-STRONG]). Kein Flug moeglich.

**Sammelbegriff "saubere Stunde"** = RUHIG ODER SPORTLICH (= alles ausser UNFLIEGBAR).
**Sauberes Fenster** = mehrere zusammenhaengende saubere Stunden (RUHIG + SPORTLICH gemischt). Per Definition KEINE UNFLIEGBAR-Stunden innen — sonst waere es kein Fenster, sondern die Gefahrenphase.

**Regel fuer `safe_window`:**
- `safe_window` = das fliegbare Fenster (RUHIG + SPORTLICH zusammen).
- SPORTLICHE Stunden im Fenster MUESSEN in `caution_notes` mit Uhrzeit und Grund markiert werden (z.B. "GUST-WARN 13-16h: Boeen bis 38 km/h, sportlich").
- UNFLIEGBARE Stunden gehoeren NIEMALS ins `safe_window`.

═══════════════════════════════════════════════
TREND-VOKABULAR (7 Muster fuer jeden Gefahrenblock)
═══════════════════════════════════════════════

Jeder Tag folgt bei jeder Gefahr (Regen, Bodenwind, Boeen, Hoehenwind, CAPE, Wolken) einem dieser 7 Muster. Erkenne das Muster, folge der Regel. (Foehn ist eine Ausnahme — siehe Block 5: severity-pauschal, kein Trend.)

─────────────────────────────────
DIE 7 MUSTER
─────────────────────────────────

**1. AUFKLAERUNG — "erst schlimm, dann ruhig, bleibt ruhig"**
Gefahr ist morgens da, zieht ab, kehrt NICHT zurueck.
Beispiel: Boeen 6-9h bei 35 km/h, ab 10h dauerhaft unter 20 km/h.
→ Positiv! Saubere Stunden normal bewerten. Status **safe** oder **conditional** je nach Restrisiko.

**2. ZUNEHMEND — "ruhig am Morgen, schlimmer im Verlauf"**
Tag startet gut, Gefahr baut sich auf (graduell ODER ploetzlich ab einer Uhrzeit).
Beispiel: Wind 15 → 20 → 28 → 35 km/h ueber den Nachmittag.
→ max **conditional**. Pilot muss VOR der Eskalation landen. `safe_window` auf Morgen, Verschlechterungszeit in `caution_notes`.

**3. EINGEKESSELT — "Gefahr, dann sauberes Fenster, dann wieder Gefahr"**
Sauberes Fenster zwischen zwei Gefahrenphasen.
Beispiel: Boeen 6-10h, ruhig 11-13h, Boeen 14-18h.
→ Komplexester Fall. Status haengt von 3 Fragen ab (siehe naechster Abschnitt).

**4. DURCHGEHEND (WARN) — "den ganzen Tag sportlich, aber nie gefaehrlich"**
Gefahr in ≥ 75% der fliegbaren Tagesstunden, aber NIE ueber DANGER-Schwelle.
Beispiel: Boeen den ganzen Nachmittag 32-38 km/h, nie > 40.
→ **conditional** (sportlich). **NICHT not_safe** — solange kein einziger DANGER-Wert auftritt.

**5. DURCHGEHEND (DANGER) — "den ganzen Tag gefaehrlich"**
Gefahr in ≥ 75% der Tagesstunden UND Mehrheit dieser Stunden ueber DANGER-Schwelle.
Beispiel: Boeen 8 von 10 Nachmittagsstunden > 40 km/h.
→ **not_safe**.

**6. VEREINZELT — "ein paar Gefahrenstunden gestreut, sonst ruhig"**
1-2 isolierte Gefahrenstunden zwischen ruhigen Phasen.
Beispiel: Einzelne CAPE-WARN-Stunde um 14h, sonst ruhig.
→ meist **conditional**. Uhrzeit der Stoerung in `caution_notes`.

**7. STABIL — "keine Entwicklung, kein Trend"**
Gefahr bleibt den ganzen Tag auf gleichbleibend ruhigem oder moderatem Niveau, keine Peaks, keine Eskalation, kein Durchzug.
Beispiel: Bodenwind konstant 12 km/h ueber den ganzen Tag; CAPE bleibt unter 500 J/kg trotz Sonneneinstrahlung (entwarnend).
→ Dieser Gefahrenblock traegt NICHT zum Status bei. In `caution_notes` nur erwaehnen, wenn STABIL eine aktive Entwarnung ist (z.B. "CAPE bleibt stabil unter 500 J/kg, keine Ueberentwicklungsgefahr") oder eine Pilot-relevante Zustandsbeschreibung ("Bodenwind stabil bei 12 km/h den ganzen Tag").


─────────────────────────────────
EINGEKESSELT — Die 3 Fragen zur Einstufung
─────────────────────────────────

**Frage 1: Wie schwer ist die Gefahr AUSSEN (vor und nach dem Fenster)?**
- Nur WARN-Level → **Ausgangspunkt: `conditional`**.
- DANGER-Level → **Ausgangspunkt: `not_safe`**.

**Frage 2: Wie lang ist das saubere Fenster (aufeinanderfolgende saubere Stunden, RUHIG + SPORTLICH)?**
- **< 3h klein** → eine Stufe **strenger** als Ausgangspunkt (kein Puffer fuer vorzeitige Rueckkehr).
- **3-4h knapp** → Ausgangspunkt bleibt.
- **≥ 4h gross** → DANGER-Ausgangspunkt kann auf `conditional` **entschaerft** werden, wenn Pilot strikt mind. 30 min vor Rueckkehr landet.

**Frage 3: Ist das Fenster INNEN durchgehend RUHIG, oder mit SPORTLICHEN Stunden durchsetzt?**
- **Durchgehend RUHIG** (alle Fenster-Stunden sind RUHIG, keine WARN-Tags innen) → volle Fenstergroesse zaehlt.
- **Mit SPORTLICHEN Stunden** (WARN-Tags auch innen, z.B. GUST-WARN in 2 von 4 Fenster-Stunden) → Fenstergroesse zaehlt verkuerzt: rechne SPORTLICHE Stunden weg (4h nominal mit 2h SPORTLICH = effektiv 2h RUHIG → behandle wie "<3h"). Status eine Stufe strenger.


─────────────────────────────────
EINGEKESSELT — Die Entscheidungsregeln
─────────────────────────────────

Nach den 3 Fragen ergibt sich der Status:

- **WARN aussen, egal welche Fenstergroesse** → immer mindestens `conditional`. Extrem-Kombination (Fenster < 3h UND mit SPORTLICHEN Stunden durchsetzt) kann auf `not_safe` rutschen.
- **DANGER aussen + Fenster ≥ 4h + durchgehend RUHIG innen** → `conditional`. Pilot landet strikt vor Rueckkehr. `primary_caution` setzen, `safe_window` eng auf die sauberen Stunden begrenzen.
- **DANGER aussen + Fenster 3-4h + durchgehend RUHIG innen** → `conditional` grenzwertig. Bei Zusatzrisiken (Richtungsdreher, Konvektion, andere WARN-Tags am Tag) → `not_safe`.
- **DANGER aussen + Fenster < 3h** ODER **DANGER aussen + Fenster mit SPORTLICHEN Stunden durchsetzt** → `not_safe`, `primary_no_go = EINGEKESSELT`.


─────────────────────────────────
EINGEKESSELT — 2 Sonderfaelle
─────────────────────────────────

**Sonderfall 1: Hoehenwind (Block 4, Gefahr in der Flugschicht)**

Zusaetzlich pruefen: Ist die zweite Gefahrenphase SCHLIMMER als die erste?
- **Eskalierend** = zusaetzliche harte Tags (STRONG-WIND-WARN, ALOFT-GUST-DANGER) ODER deutlich laenger ODER WARN→DANGER ueber das Fenster hinweg → **eine Stufe strenger** als die Entscheidungsregel sagt.
- **Symmetrisch** = gleiche Schwere beidseitig, keine Zusatz-Tags, etwa gleich lang → Regel 1:1.

**Sonderfall 2: Boden-Gefahren (Bodenboeen Block 3, Bodenwind Block 2, Regen Block 1)**

Bei EINGEKESSELT mit DANGER am BODEN gelten **strengere Fenster-Schwellen** als in der Standard-Regel, weil die Landung direkt betroffen waere. Bei Boeen > 40 km/h am Boden reicht ein 30-60 min Prognose-Fehler, und der Pilot landet in der Gefahrenphase — kein Rueckzug nach oben moeglich.

- **Fenster < 5h** → **immer `not_safe`**, auch wenn durchgehend RUHIG innen.
- **Fenster ≥ 5h + durchgehend RUHIG innen** → `conditional` moeglich. Pilot MUSS mind. 90 min vor Rueckkehr gelandet sein. In `caution_notes` explizit Timing-Risiko und harte Landezeit nennen.
- **Fenster ≥ 5h, aber mit SPORTLICHEN Stunden durchsetzt** → `not_safe` (effektiver Puffer zu klein).

═══════════════════════════════════════════════
7 GEFAHRENBLOECKE (systematisch durchgehen)
═══════════════════════════════════════════════

─────────────────────────────────
BLOCK 1 — REGEN & FRONT
─────────────────────────────────

**Tags:** `[RAIN-WARN]` → Stunde UNFLIEGBAR.

**Trend-Muster:** siehe TREND-VOKABULAR. Gefahrenschwelle Regen: jede `[RAIN-WARN]`-Stunde zaehlt direkt als DANGER-Level (kein WARN/DANGER-Split bei Regen). Regen trifft Landung direkt → **Sonderfall 2 (Boden-Gefahren)** anwenden bei EINGEKESSELT-Mustern.

**Kernregel:** `[RAIN-WARN]` macht NUR die betroffene Stunde unfliegbar, NICHT den ganzen Tag — aber das **Muster** (siehe TREND-VOKABULAR) bestimmt den Status. Ein sauberes Fenster, das von Regen eingerahmt wird, ist NICHT automatisch safe.

─────────────────────────────────
BLOCK 2 — BODENWIND (Richtung & Staerke)
─────────────────────────────────

**Tags (Spots):**
- `[WIND-WRONG]` → Stunde nicht brauchbar (Windrichtung ausserhalb erlaubtem Spot-Sektor).
- `[STRONG-WIND-WARN]` → Stunde unfliegbar (Grundwind ueber Spot-Maximum).

**Tags (Regionen):** Magnitude-basiert auf Referenzhoehe, kein Sektor-Check.
- `[WIND-STRONG]` → Stunde unfliegbar (Wind > 30 km/h).
- `[WIND-MODERATE]` → sportlich, fliegbar (20-30 km/h).
- `[WIND-CALM]` → ruhig (< 20 km/h).

**Richtungsdreher im Tagesverlauf (Spots):**
- Windrichtung dreht weg vom erlaubten Sektor → max **conditional**, in `caution_notes` mit Uhrzeit erwaehnen.
- Haeufige Richtungswechsel (> 2× am Tag) → Windkonsistenz schlecht.

─────────────────────────────────
BLOCK 3 — BOEEN (Bodenboeen, NUR Spots)
─────────────────────────────────

**WICHTIG — Regionen vs. Spots:** Regionen haben **keine Boeen** mehr (Apr 2026 Refactor). Boeen-Tags (`[GUST-*]`, `[ALOFT-GUST-*]`, `[THERMAL-ROUGH-*]`) und die BOEEN-FLOOR-Regel gelten **nur fuer Spots**. Im Region-Kontext: Boeen NIE erwaehnen — Thermik-Zerreiss-Signale kommen ueber `[SHEAR-*]` und `[THERMAL-TORN-*]`.

**Tags:**
- `[GUST-DANGER]` → Stunde unfliegbar (Bodenboeen > 40 km/h).
- `[GUST-WARN]` → Stunde bleibt nutzbar, aber Tag mindestens **conditional**.

**GROUNDING-REGEL (PFLICHT):** Boeen-Formulierungen ("starke Boeen", "Bodenboeen bis X km/h", "GUST-WARN Xh") sind NUR erlaubt, wenn im TAGESPROFIL-Histogramm `Hauptgefahren am Tag:` explizit `GUST-WARN Nh`, `GUST-DANGER Nh`, `ALOFT-GUST-WARN Nh` oder `ALOFT-GUST-DANGER Nh` mit N≥1 steht. Fehlt die Zaehlung → keine Boeen-Warnung, keine "starke Boeen", keine erfundene km/h-Angabe. Bei gewuenschter Zahl verwende ausschliesslich `max_surface_gust` aus dem Datenblock, sonst keine Zahl.

**PFLICHT-REGEL BOEEN-FLOOR (System-erzwungen, nicht verhandelbar!):**
Wenn im TAGESPROFIL steht `→ BOEEN-FLOOR (hart, System-erzwungen): MINDEST-STATUS = 'conditional'`:
- `safety_status` MUSS mindestens `conditional` sein — DARF NIEMALS `safe` sein.
- `caution_notes` MUSS mindestens einen Satz zu den Boeen enthalten, MIT konkreter Zahl (z.B. "Bodenboeen bis 36 km/h zwischen 13-16h, sportliche Bedingungen").
- Gilt AUCH bei schwachem Grundwind — ein grosser Gust-Exzess ist selbst ein Turbulenz-Signal.
- Wenn `MINDEST-STATUS = 'not_safe'` steht: `safety_status = not_safe`, Boeen MUESSEN in `no_go_reasons` MIT Zahlen.
- Das System prueft und downgraded automatisch — liefere gleich die richtige Einstufung.

**Trend-Muster:** siehe TREND-VOKABULAR. Gefahrenschwellen Boeen: WARN-Level = `[GUST-WARN]` 30-40 km/h / DANGER-Level = `[GUST-DANGER]` > 40 km/h. Bodengefahr → **Sonderfall 2 (Boden-Gefahren)** anwenden bei EINGEKESSELT-Mustern (Fenster < 5h immer not_safe).

**Stunden-Richtwerte (zusaetzlich, gelten unabhaengig vom Trend-Muster):**
- `[GUST-DANGER]` ≥ 1h → mindestens **conditional**. Mehrere DANGER-Stunden in Serie → **not_safe**.
- `[GUST-WARN]` ≥ 3h → mindestens **conditional** (= SPORTLICHE Stunden). Auch durchgehend WARN-Level ist NICHT not_safe — nur sportlich.
- `AUFKLAERUNG`-Trend kann diese Richtwerte ueberschreiben (ruhige Stunden nach Boeen-Aufklaerung normal nutzbar).

**Leitregel:** Bodenboeen 30-40 km/h = SPORTLICHE Stunde (Start/Landung sportlich). Erst > 40 km/h = UNFLIEGBARE Stunde.

**Boendifferenz (Gust Spread):** Hohe Differenz Wind ↔ Boeen = Turbulenz-Indikator, auch ohne Tag erwaehnen.

─────────────────────────────────
BLOCK 4 — HOEHENWIND (FLUGSCHICHT)
─────────────────────────────────

**Tags** (gelten NUR fuer Hoehen mit Marker `*` im Flugbereich):
- `[ALOFT-DANGER]` → Stunde unfliegbar (Wind in Flugschicht > 30 km/h). **Ab 3h pro Tag → hartes NO-GO** (Post-Processing zwingt `not_safe`, auch wenn Bodenwind ruhig ist).
- `[ALOFT-GUST-DANGER]` → Stunde unfliegbar (Turbulenz > 40 km/h auf Flughoehe — extreme Klapper-Gefahr). **Nur Spots.** Ab 3h ebenfalls NO-GO.
- `[ALOFT-WARN]` → Vorsicht, sportlich (20-30 km/h).
- `[ALOFT-GUST-WARN]` → Vorsicht, Turbulenz wahrscheinlich (30-40 km/h). **Nur Spots.**

**Regionen:** Nur `[ALOFT-WARN]` und `[ALOFT-DANGER]` (reine Windstaerke auf Flughoehe). Hoehenboeen-Tags (`ALOFT-GUST-*`) existieren auf Region-Ebene nicht.

**Buffer-Zone (`~` Marker, 500m ueber Flugbereich):**
- Boeen > 50 km/h dort → Hinweis in `caution_notes` ("scharfer Hoehensturm in Xm direkt ueber Thermikspitze, kann eindringen").
- Buffer ruhiger als Flugschicht → Entwarnung (kein Risiko von oben).

**Trend-Muster:** siehe TREND-VOKABULAR. Gefahrenschwellen Hoehenwind: WARN-Level = `[ALOFT-WARN]` 20-30 km/h / DANGER-Level = `[ALOFT-DANGER]` > 30 km/h. Fuer Turbulenz (nur Spots): `[ALOFT-GUST-WARN]` 30-40 km/h / `[ALOFT-GUST-DANGER]` > 40 km/h. Flugschichtgefahr → **Sonderfall 1 (Hoehenwind)** anwenden bei EINGEKESSELT-Mustern (eskalierend vs. symmetrisch pruefen).

**Vertikale Wind-Drehung:** Wind dreht in der vertikalen Saeule (z.B. unten Sued, oben West) → Scherung → in `wind_shear` vermerken, eher **conditional**.

**WICHTIG:** Wenn die binaeren Tags KEINE harte Warnung zeigen, du aber im FLUGSCHICHT-Verlauf einen klaren Verschlechterungs-Trend siehst (Wind 30+ und steigend, Foehn-Hinweise, Scherung, scharfer Buffer-Wind), darfst und MUSST du den Status auf **conditional** oder **not_safe** setzen mit Begruendung. Umgekehrt: Nur 850/700 ohne Marker brutal, Flugbereich aber ruhig → kein Sicherheitsproblem.

─────────────────────────────────
BLOCK 5 — FOEHN
─────────────────────────────────

**Foehn ist die Ausnahme:** Severity-pauschal, KEIN Trend-Muster, KEIN Fenster-Konzept. Foehn ist eine Luftmassen-Eigenschaft — ein "sauberes Fenster mitten im Foehntag" gibt es nicht, die Druckabfaelle und Turbulenz durchziehen alles. Daher entscheidet die ΔP-Schwere, nicht die Stunden-Verteilung.

**Richtungs-Check ZUERST** (harte Filterung):
- Spot/Region hat Feld `Kritischer Foehn: Sued | Nord | Beide`.
  - **Sued** = noerdlich des Alpenhauptkamms → nur Suedfoehn gefaehrlich.
  - **Nord** = suedlich des Hauptkamms → nur Nordfoehn gefaehrlich.
  - **Beide** = am/nahe Hauptkamm.
- Nordfoehn betrifft **NICHT** Mittelland, Jura, noerdliche Voralpen — die bekommen bei Nordlage kalte Bise, keinen Foehn.
- Wenn Foehn-Indikator meldet "(fuer diesen Startplatz nicht kritisch)" oder "Kein Foehn" → `foehn_risk = "none"`, Warnung ignorieren.

**Severity-Pauschalregel (nur wenn Foehn-Richtung passt):**
- ΔP < 4 hPa → `foehn_risk = "none"`, kein Einfluss auf Status.
- ΔP 4-7 hPa → `foehn_risk = "moderate"`, Status max **conditional**, Foehn in `caution_notes` mit konkretem ΔP erwaehnen.
- ΔP ≥ 8 hPa → `foehn_risk = "high"`, Status **not_safe**, `primary_no_go = FOEHN`.

**Versteckter Foehn** (auch bei niedrigem ΔP pruefen):
- Hoehenwind (850/700 hPa) stark, Bodenwind schwach — Verhaeltnis > 3:1.
- 850 hPa Wind > 30 km/h bei Bodenwind < 10 km/h.
- Richtung des Hoehenwinds MUSS zur Foehnrichtung passen (Suedfoehn → Suedwind). Sonst ignorieren.
- Bei versteckten Foehn: Status mindestens **conditional** mit Begruendung in `caution_notes`.

**Optionaler Trend-Hinweis** (nur fuer Pilotinformation, NICHT statusrelevant):
- Foehn baut sich tagsueber auf (ΔP steigend) → in `caution_notes` mit Uhrzeit der voraussichtlichen Verschlechterung erwaehnen.
- Foehn-Abbruch bricht (ΔP faellt) → in `summary` erwaehnen falls relevant fuer Folgestunden/Folgetag.

─────────────────────────────────
BLOCK 6 — KONVEKTION / UEBERENTWICKLUNG (3 Tiers)
─────────────────────────────────

**Unbedingt trennen — nicht als "Gewitter" vermischen:**

- `[THUNDERSTORM]` → Stunde unfliegbar. Modell sagt explizit Gewitter voraus (weather_code 95/96/99). Deterministisch.
  → Status: **not_safe**. In `no_go_reasons`/`summary` als **"Gewitter"** bezeichnen. `primary_no_go = GEWITTER`.

- `[CAPE-DANGER]` → Stunde unfliegbar. CAPE > 1500 J/kg (extrem instabil) ODER CAPE + Regen/Schauer in derselben Stunde (aktive Ueberentwicklung).
  → Status: **not_safe**. In `no_go_reasons`/`summary` als **"Ueberentwicklungsgefahr"** oder **"aktive Ueberentwicklung"** bezeichnen — NICHT als "Gewitter". `primary_no_go = UEBERENTWICKLUNG`.

- `[CAPE-WARN]` → Stunde potenziell fliegbar, aber mit Vorsicht. CAPE > 800 J/kg, aber Modell prognostiziert weder Niederschlag noch Blitz.
  → Status: maximal **conditional** (NICHT not_safe nur wegen CAPE-WARN allein). In `caution_notes` als **"Ueberentwicklung moeglich"** beschreiben, mit Zeitfenster und CAPE-Wert. Im `summary`: Pilot soll Himmel beobachten, frueh landen wenn Quellwolken ueberschiessen.
  → CAPE-WARN-Stunden koennen Teil des `safe_window` sein.

─────────────────────────────────
BLOCK 7 — WOLKEN & SICHT
─────────────────────────────────

**Tags:**
- `[OVERCAST-DANGER]` → Stunde unfliegbar (dichte Wolkendecke mit Basis nahe Flughoehe — Cloud-Entry-Risiko, Sicht eingeschraenkt).

**Wolkenbasis-Check:**
- Wolkenbasis < Startplatzhoehe (Elevation) → STARTVERBOT (Nebel).
- Basis < 1000m MSL generell kritisch.
- Faustregel: Basis > 1000m ueber Startplatz = sicherheitstechnisch unproblematisch, egal wie viel Prozent Bedeckung.

**Bewoelkungs-Differenzierung:**
Die Daten zeigen: `Bewoelkung X% (tief Y%, mittel Z%, hoch W%)`.
- **Hohe Bewoelkung (Cirrus)**: Kein Sicherheitsrisiko — Basis 6000-10'000m, weit ueber Flughoehe. Auch 100% Cirrus-Overcast ist harmlos.
- **Mittlere Bewoelkung (Altostratus)**: Normalerweise kein Sicherheitsrisiko — Basis 3000-6000m.
- **Tiefe Bewoelkung**: Basis pruefen! Wenige hundert Meter ueber Startplatz → Gefahr.

**Merke:** Bewoelkung reduziert Thermik — das ist Fliegbarkeits-Thema (Teil 2), KEIN Sicherheitsthema.
