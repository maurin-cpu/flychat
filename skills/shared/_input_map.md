═══════════════════════════════════════════════
INPUT-KARTE — WIE LIEST DU DEN DATENBLOCK?
═══════════════════════════════════════════════

Der User-Block liefert dir drei Zonen: **Stunden-Zeilen**, **Drucklevel-Werte** und den **TAGESPROFIL-Block** am Ende. Lerne diese zuerst — danach kannst du die Regeln anwenden.

═══════════════════════════════════════════════
ZWEI TAG-KATEGORIEN (KATEGORISCH GETRENNT!)
═══════════════════════════════════════════════

Jeder Tag in eckigen Klammern gehoert zu **genau einer** dieser zwei Kategorien:

**KATEGORIE 1 — STARTBARKEITS-FILTER** (Spot only)
- `[WIND-OK]` — Stunde ist Start-**Kandidat**.
- `[WIND-WRONG]` — Stunde ist **kein** Start-Kandidat. Wird **IGNORIERT**.

`[WIND-WRONG]` ist KEIN Hazard, KEINE Warnung, KEIN Sicherheitssignal. Es ist ein **Filter**. Aber: wenn der Filter den ganzen Tag wegfiltert, gibt es keinen Start — und genau **das** ist dann der Grund fuer `not_safe`.

Deshalb gibt es zwei Faelle, je nach Start-Fenster-Laenge:

**FALL A — Ausreichendes Start-Fenster vorhanden** (`Laengstes Fenster ≥ {{cfg.CLEAN_WINDOW_MIN_HOURS}}h`):
- `[WIND-WRONG]`-Stunden werden **ignoriert** wie Stunden ausserhalb des Flugfensters.
- Kommen **NIEMALS** in `caution_notes` oder `no_go_reasons`.
- Fuehren **NIEMALS** zu `conditional` oder `not_safe`.
- Zwischen zwei sauberen Fenstern teilen sie das Fenster auf, **machen aber keines der Teile gefaehrlich**.
- Ein Richtungsdreher im Tagesverlauf (auch >90°) ist **kein Status-Downgrade** — nur Anmerkung in `wind_summary`.

**SPRACH-VERBOT in Fall A** (PFLICHT, weil Status hier `safe` oder `conditional` ist):
- Niemals als "Gefahr", "Hauptgefahr", "Risiko", "Warnung", "kritisch", "ungünstig" framen.
- Niemals als Begründung für den safe/conditional-Status nennen.
- Auch nicht als "die einzige Gefahr ist die falsche Windrichtung" oder "Hauptgefahren beschränken sich auf eine Stunde mit falscher Windrichtung" schreiben — das ist die verbotene Framing-Falle.
- Wenn ueberhaupt erwaehnen, dann **rein faktisch ohne Risiko-Wortschatz**: "10:00 nicht startbar (Windrichtung), Start ab 11:00".

**FALL B — Kein ausreichendes Start-Fenster** (`Laengstes Fenster < {{cfg.CLEAN_WINDOW_MIN_HOURS}}h`, ggf. 0):
- Status = **`not_safe`** (deterministisch, Code erzwingt das).
- `[WIND-WRONG]` IST jetzt die **legitime Begruendung** — kein Hazard, aber das Fehlen einer startbaren Stunde **ist** der Grund.
- Gehoert in `no_go_reasons` und `summary` als faktischer Eintrag.
- Sprache: **kein Risiko-Wortschatz** ("Gefahr", "kritisch", "stürmisch"), sondern **Fakt**: kein Start moeglich.
- Erlaubte Formulierungen:
  - `no_go_reasons: ["Windrichtung: Ganztaegig ausserhalb des erlaubten Sektors"]`
  - `no_go_reasons: ["Start-Fenster: Nur Xh mit Windrichtung im erlaubten Sektor (Minimum {{cfg.CLEAN_WINDOW_MIN_HOURS}}h)"]`
  - `summary: "Nur Xh mit passender Windrichtung (<Sektor>) — kein ausreichendes Start-Fenster."`
  - `summary: "Windrichtung liegt den ganzen Tag ausserhalb des erlaubten Sektors. Kein fliegbares Fenster."`
- VERBOTEN bleibt: WIND-WRONG als "Gefahr" bezeichnen, "Risiko" suggerieren, dramatisches Wording. Es ist nuechtern: kein passender Wind = kein Start.

**Bei alten Datenbloecken**: Wenn die Hauptgefahren-Zeile im Datenblock noch `WIND-WRONG Xh` enthaelt (Cache vor STARTBARKEIT-Refactor), **ignoriere diesen Histogramm-Eintrag** als Hazard — er ist veraltetes Format. Im aktuellen Datenblock erscheint `[WIND-WRONG]` **nur** im STARTBARKEIT-Block, **niemals** in `Hauptgefahren am Tag:`.

**KATEGORIE 2 — HAZARD-TAGS** (gelten fuer Kandidaten-Stunden)
Alle anderen Tags. Diese koennen Status druecken, in `caution_notes`/`no_go_reasons` landen und Sub-Ratings beeinflussen. Liste folgt unten.

─────────────────────────────────
A) STUNDEN-ZEILEN (Bodendaten + Tags)
─────────────────────────────────

Pro Stunde bekommst du eine Zeile mit Bodenwind, Bewoelkung, Niederschlag, CAPE, Wolkenbasis — und eine Liste von **Tags** in eckigen Klammern. Im Spot-Kontext enthaelt die Zeile zusaetzlich Boeen (Turbulenzrisiko). Im Region-Kontext gibt es **keine Boeen-Werte** — nur Windstaerke.

**Harte No-Go-Tags = DANGER-Level** (Stunde wird UNFLIEGBAR, gehoert NIEMALS ins safe_window):
- `[RAIN-WARN]` — Niederschlag ≥ 0.05 mm/h
- `[WIND-DANGER]` — Bodenwind > {{cfg.WIND_DANGER_KMH}} km/h
- `[ALOFT-WIND-DANGER]` — Hoehenwind in Flugschicht > {{cfg.WIND_DANGER_KMH}} km/h (Auto-NoGo-Trigger ab {{cfg.WIND_TREND_NOTSAFE_HOURS}}h/Tag bei DURCHGEHEND_DANGER-Trend)
- `[GUST-DANGER]` — Bodenboeen > {{cfg.GUST_DANGER_KMH}} km/h *(nur Spots)*
- `[ALOFT-GUST-DANGER]` — Turbulenz in Flugschicht > {{cfg.GUST_DANGER_KMH}} km/h *(nur Spots)*
- `[THUNDERSTORM]` — Modell sagt Gewitter (weather_code 95/96/99)
- `[CAPE-DANGER]` — CAPE > {{cfg.CAPE_DANGER_JKG}} J/kg ODER CAPE + Regen aktiv
- `[OVERCAST-DANGER]` — Dichte Wolkendecke nahe Flughoehe

**Weiche Vorsichts-Tags = WARN-Level** (Stunde wird SPORTLICH, bleibt fliegbar fuer erfahrene Piloten, Status mind. conditional):
- `[WIND-WARN]` — Bodenwind {{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h
- `[ALOFT-WIND-WARN]` — Hoehenwind in Flugschicht {{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h
- `[GUST-WARN]` — Bodenboeen erhoeht (WARN-Level) *(nur Spots)*
- `[ALOFT-GUST-WARN]` — Turbulenz in der Flugschicht erhoeht (WARN-Level) *(nur Spots)*
- `[CAPE-WARN]` — CAPE erhoeht (WARN-Level) ohne Trigger

**Richtungs-Tags (Spot-Modus) — siehe oben "ZWEI TAG-KATEGORIEN":**
- `[WIND-OK]` — Windrichtung liegt im erlaubten Spot-Sektor (inkl. 10° Buffer) → Start-Kandidat.
- `[WIND-WRONG]` — Windrichtung ausserhalb des Spot-Sektors → Filter, **kein Hazard** (Details siehe oben).

**Region-Modus:** Regionen haben keinen Sektor und keine Boeen, nur Wind-Staerke auf Referenzhoehe. Tags sind dieselben wie bei Spots:
- Kein Tag (Wind < {{cfg.WIND_WARN_KMH}} km/h) → RUHIG
- `[WIND-WARN]` — Wind {{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h → SPORTLICH
- `[WIND-DANGER]` — Wind > {{cfg.WIND_DANGER_KMH}} km/h → UNFLIEGBAR

**Stunden-Klassifikation** (siehe KERNREGEL in `_hazards_*.md`) — **zwei unabhaengige Achsen**:

*Achse 1 — Flug-Gefahr (betrifft Pilot in der Luft):*
- `RUHIG` = KEINE Tags = komfortabel.
- `SPORTLICH` = ≥1 WARN-Tag, KEIN DANGER = fliegbar erfahren.
- `UNFLIEGBAR` = ≥1 DANGER-Tag (RAIN-WARN, WIND-DANGER, ALOFT-WIND-DANGER, GUST-DANGER, ALOFT-GUST-DANGER, THUNDERSTORM, CAPE-DANGER, OVERCAST-DANGER). `[WIND-WRONG]` ist Filter, kein DANGER.

*Achse 2 — Start-Moeglichkeit (betrifft nur Startplatz):*
- `STARTBAR` = `[WIND-OK]` (Spot) oder Region nicht `[WIND-DANGER]`.
- `NICHT-STARTBAR` = `[WIND-WRONG]` (Spot) ODER `[WIND-DANGER]` (Region — Wind zu stark).

*Kombinierter Begriff:*
- **Saubere Stunde** = STARTBAR UND nicht UNFLIEGBAR (keine DANGER-Tags). Das ist die einzige Stundenart, in der ein Pilot sicher starten kann.
- `safe_window` = zusammenhaengender Block sauberer Stunden.

**Thermik-Qualitaets-Tags** (gelten NUR fuer Teil 2 Fliegbarkeit, NIE fuer Sicherheit):
- `[SHEAR-DEGRADED]` / `[SHEAR-UNUSABLE]` — Windscherung: Wind dreht/beschleunigt mit Hoehe, Blase wird gekippt (Spot + Region).
- `[THERMAL-TORN-DEGRADED]` / `[THERMAL-TORN-UNUSABLE]` — Buoyancy/Shear-Ratio schlecht: Auftrieb zu schwach gegenueber Scherung, Blase zerrissen (Spot + Region).
- `[THERMAL-ROUGH-DEGRADED]` / `[THERMAL-ROUGH-UNUSABLE]` — ruppige Thermik durch Boeigkeit (Gust-Factor) *(nur Spots — braucht Boeen)*.
- `[THERMAL-WIND-DEGRADED]` / `[THERMAL-WIND-UNUSABLE]` — mittlerer Grundwind durch die Mischungsschicht zu stark, Blase organisiert sich nicht (Spot + Region). Quelle: BL-Mean-Wind gegen zone-abhaengige Schwelle (Research Abschnitt 3.1).

─────────────────────────────────
B) DRUCKLEVEL-WERTE (Flugschicht-Zeile)
─────────────────────────────────

Format: `pressure(altitude_m)MARKER: wind/boeen km/h aus dir°`

**Marker verstehen:**
- `*` = **Flugbereich** (Spot-Hoehe bis Thermik+1000m, inkl. Lid-Zone) — HIER feuern die [ALOFT-*]-Tags. Trend-Bewertung ({{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h = WARN, > {{cfg.WIND_DANGER_KMH}} km/h = DANGER) gilt voll.
- `~` = **Buffer-Zone** (500m ueber dem Flugbereich) — KEINE harten Tags, aber wenn dort Boeen > 50 km/h: Hinweis in `caution_notes` ("scharfer Hoehensturm direkt ueber Thermikspitze"). Wenn Buffer ruhiger als Flugbereich: Entwarnung.
- **Kein Marker** = nur 850/700 hPa als Foehn-Anker. Fuer direkte Sicherheit irrelevant ausser als Foehn-Indikator.

─────────────────────────────────
C) TAGESPROFIL-Block (am Ende des Datenblocks)
─────────────────────────────────

Hier hat das System bereits alles gezaehlt und geflagged:

- `Verhaeltnis sauber/gesamt: X/Yh = Z%` — Anteil sauberer Stunden (RUHIG + SPORTLICH) im Flugfenster
- `Hauptgefahren am Tag: GUST-DANGER 4h, ALOFT-DANGER 2h, ...` — Histogramm der Gefahren (Regionen: ohne GUST-* Eintraege)
- `→ PRODUKTIVE-THERMIK: Nh` — produktive Thermikstunden (Climb ≥{{cfg.PRODUCTIVE_CLIMB_MIN}} + tief <{{cfg.PRODUCTIVE_LOW_CLOUD_MAX}}% + mittel <{{cfg.PRODUCTIVE_MID_CLOUD_MAX}}% + kein ROUGH-UNUSABLE + kein WIND-UNUSABLE). Regionen: ROUGH-UNUSABLE-Kriterium faellt weg (keine Boeen), aber WIND-UNUSABLE ist Pflicht-Filter.
- `→ BOEEN-FLOOR: MINDEST-STATUS = 'conditional'` oder `'not_safe'` — vom System **erzwungener** Mindeststatus (nicht verhandelbar!) *(nur Spots)*
- `→ ACHTUNG Verhaeltnis < 35%: ...` — optionaler Warnhinweis
- `THERMIK-QUALITAET-Block`: Zaehler fuer SHEAR/TORN/ROUGH-UNUSABLE-Stunden + TQ-Ratio pro Stunde (Regionen: kein ROUGH)
- **Trend-Labels (falls vorhanden):** AUFKLAERUNG / ZUNEHMEND / EINGEKESSELT / DURCHGEHEND (WARN/DANGER) / VEREINZELT / STABIL — vollstaendige Definitionen siehe TREND-VOKABULAR in `_hazards_*.md`. Wende sie pro Gefahrenblock an (Regen, Wind, Boeen, CAPE, Wolken). Foehn ist ausgenommen (severity-pauschal, kein Trend).
- **Eigene Trend-Zeilen:** Direkt nach TAGESPROFIL koennen `NIEDERSCHLAG-TREND`, `GUST-TREND` (nur Spots) und `WIND-TREND` stehen. `WIND-TREND` umfasst Bodenwind UND Hoehenwind summiert (gleiche Schwellen WARN/DANGER), `GUST-TREND` umfasst Boden- und Hoehenboeen summiert. Sie liefern dir das **Muster** (z.B. AUFKLAERUNG, ZUNEHMEND, DURCHGEHEND_DANGER) und die **Fakten** (Stunden, Zeitpunkte). Sie sind PFLICHT-Input fuer deinen Status. Den Status leitest du aus dem Muster ab (Mapping siehe `_hazards_*.md` Block 4 fuer Wind, Block 3 fuer Boeen, TREND-VOKABULAR fuer den Rest) — nicht aus einem mitgelieferten Satz, denn die Trend-Zeile enthaelt **keine fertigen Handlungs-Saetze** zum Abschreiben.

**Deine Pflicht:** Diese Werte lesen, nicht selber berechnen. Wenn BOEEN-FLOOR steht, ist das verbindlich. Wenn "Verhaeltnis < 35%" steht, MUSS das in `caution_notes` oder `no_go_reasons`.
