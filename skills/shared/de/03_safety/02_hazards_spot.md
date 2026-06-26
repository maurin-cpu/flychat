═══════════════════════════════════════════════
KERNREGEL — Stunden-Klassifikation
═══════════════════════════════════════════════

Jede Stunde:
- **RUHIG** — keine WARN/DANGER-Tags
- **SPORTLICH** — ≥1 WARN-Tag (WIND/ALOFT-WIND/GUST/ALOFT-GUST/CAPE), kein DANGER
- **UNFLIEGBAR** — ≥1 DANGER-Tag (RAIN-WARN, WIND/ALOFT-WIND/GUST/ALOFT-GUST-DANGER, CAPE-DANGER, THUNDERSTORM, OVERCAST-DANGER)

**Tagesfenster-Schicht** (siehe `_tagesfenster.md`): Der Datenblock enthaelt nur Stunden ab Tagesbeginn. Sicherheit nur **innerhalb** des aktiven Tages bewerten.

**"Saubere Stunde" (Safety)** = nicht UNFLIEGBAR. `[WIND-WRONG]` spielt hier keine Rolle.
**"Sauberes Fenster"** = zusammenhaengende saubere Stunden im aktiven Tag.

**`safe_window`:**
- = fliegbare Stunden (RUHIG + SPORTLICH), unabhaengig von Windrichtung.
- SPORTLICHE Stunden MUESSEN in `caution_notes` mit Uhrzeit + Grund stehen.
- UNFLIEGBARE Stunden NIEMALS ins `safe_window`. `[WIND-WRONG]` unterbricht das Fenster NICHT.

═══════════════════════════════════════════════
TREND-VOKABULAR (7 Muster)
═══════════════════════════════════════════════

Jeder Gefahrenblock (Regen, Wind, Boeen, Hoehenwind, CAPE, Wolken) folgt einem dieser Muster. Foehn = Ausnahme (severity-pauschal, Block 5).

1. **AUFKLAERUNG** — Gefahr morgens, zieht ab → saubere Stunden normal bewerten, **safe**/**conditional**.
2. **ZUNEHMEND** — startet ruhig, baut sich auf → max **conditional**, `safe_window` auf Morgen.
3. **EINGEKESSELT** — sauberes Fenster zwischen zwei Gefahrenphasen → siehe naechster Abschnitt.
4. **DURCHGEHEND (WARN)** — ≥75% WARN, kein DANGER → **conditional** (sportlich).
5. **DURCHGEHEND (DANGER)** — ≥75% DANGER → **not_safe**.
6. **VEREINZELT** — isolierte Gefahrenstunden → meist **conditional**, Uhrzeit in `caution_notes`.
7. **STABIL** — gleichbleibend ruhig → kein Status-Effekt. Nur in `caution_notes` wenn aktive Entwarnung oder beschreibend.

─────────────────────────────────
EINGEKESSELT — 3 Fragen
─────────────────────────────────

**Frage 1 — Schwere AUSSEN:** WARN-Level → Ausgangspunkt `conditional`. DANGER → `not_safe`.

**Frage 2 — Fensterlaenge (RUHIG + SPORTLICH zusammenhaengend):**
- **< 3h** → eine Stufe strenger
- **3-4h** → Ausgangspunkt bleibt
- **≥ 4h** → DANGER-Ausgangspunkt darf auf `conditional` (Pilot landet ≥30 min vor Rueckkehr)

**Frage 3 — Fenster INNEN:** Durchgehend RUHIG → volle Groesse zaehlt. Mit SPORTLICHEN durchsetzt → effektive Groesse rechnen (4h, 2h SPORTLICH = effektiv 2h), Stufe strenger.

─────────────────────────────────
EINGEKESSELT — Entscheidungen + Sonderfaelle
─────────────────────────────────

- **WARN aussen** → mind. `conditional`. Extrem-Kombi (<3h UND SPORTLICH durchsetzt) → `not_safe`.
- **DANGER aussen + ≥4h + RUHIG innen** → `conditional`, Pilot landet vor Rueckkehr.
- **DANGER aussen + 3-4h + RUHIG innen** → `conditional` grenzwertig. Mit Zusatzrisiken → `not_safe`.
- **DANGER aussen + <3h** ODER **DANGER aussen + SPORTLICH durchsetzt** → `not_safe`, `primary_no_go = EINGEKESSELT`.

**Sonderfall 1 — Hoehenwind:** Zweite Gefahrenphase schlimmer als erste (eskalierend) → eine Stufe strenger. Symmetrisch → Regel 1:1.

**Sonderfall 2 — Boden-Gefahren (Bodenboeen, Bodenwind, Regen):** Strengere Schwellen, da Landung direkt betroffen.
- **<5h** → immer `not_safe`, auch RUHIG innen.
- **≥5h + RUHIG innen** → `conditional` moeglich (≥90 min vor Rueckkehr landen).
- **≥5h + SPORTLICH durchsetzt** → `not_safe`.

═══════════════════════════════════════════════
7 GEFAHRENBLOECKE
═══════════════════════════════════════════════

─────────────────────────────────
BLOCK 1 — REGEN & FRONT
─────────────────────────────────

`[RAIN-WARN]` → Stunde UNFLIEGBAR (zaehlt direkt als DANGER, kein WARN-Split). Trifft Landung → **Sonderfall 2** bei EINGEKESSELT.

Sauberes Fenster zwischen Regenphasen ist NICHT automatisch safe — Trend-Muster bestimmt Status.

─────────────────────────────────
BLOCK 2 — BODENWIND
─────────────────────────────────

**Tags (Spots + Regionen):**
- Kein Tag (< {{cfg.WIND_WARN_KMH}} km/h) → ruhig
- `[WIND-WARN]` → sportlich ({{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h)
- `[WIND-DANGER]` → unfliegbar (> {{cfg.WIND_DANGER_KMH}} km/h, echte Flug-Gefahr)

Filter-Tags `[WIND-OK]`/`[WIND-WRONG]` separat in `_tagesfenster.md` — KEINE Hazards.

**Trend:** Bodenwind + Hoehenwind teilen die `WIND-TREND`-Zeile (gleiche Schwellen). Kein separater Bodenwind-Trend. Mapping siehe Block 4.

**Sicherheits-Fenster-Regel (pflicht):** Ein Tag kann mehrere Fenster haben. **Tag-Status zaehlt das laengste** (`Laengstes Fenster: Xh` im TAGESPROFIL).
- **≥ {{cfg.CLEAN_WINDOW_MIN_HOURS}}h** zusammenhaengend sauber → `safe`/`conditional` moeglich.
- **< {{cfg.CLEAN_WINDOW_MIN_HOURS}}h** → `not_safe`.

"Zusammenhaengend" = direkt aufeinanderfolgend. DANGER-Stunde dazwischen trennt das Fenster (`[WIND-WRONG]` trennt NICHT). System liefert Zahlen — nicht selbst nachzaehlen.

─────────────────────────────────
BLOCK 3 — BOEEN (Boden + Hoehe, nur Spots)
─────────────────────────────────

**Tags (gleiche Schwellen):**
- `[GUST-WARN]`/`[ALOFT-GUST-WARN]` → sportlich. Tag mind. `conditional` wenn ≥3h.
- `[GUST-DANGER]`/`[ALOFT-GUST-DANGER]` → DANGER-Niveau (> {{cfg.GUST_DANGER_KMH}} km/h). Kein Auto-NoGo — LLM entscheidet nach Trend + Fenster.

**GROUNDING (PFLICHT):** Boeen-Formulierungen NUR erlaubt wenn TAGESPROFIL `Hauptgefahren am Tag:` explizit `GUST-WARN/DANGER Nh` oder `ALOFT-GUST-WARN/DANGER Nh` mit N≥1 zeigt. Sonst keine km/h-Angaben erfinden — nutze `max_surface_gust` aus Datenblock.

**BOEEN-FLOOR (System-erzwungen):** Wenn `→ BOEEN-FLOOR (hart, System-erzwungen): MINDEST-STATUS = 'conditional'`:
- `safety_status` MUSS mind. `conditional` (nie `safe`).
- `caution_notes` MUSS Boeen-Satz mit konkreter Zahl enthalten.
- Gilt auch bei schwachem Grundwind (grosser Gust-Exzess = Turbulenz-Signal).

**GUST-TREND-Mapping** (Boden + Hoehe summiert):
- **DURCHGEHEND_DANGER** → bevorzugt `not_safe`, `primary_no_go = STARKE_BOEEN`. Nur bei klar sauberer 4h+ AUFKLAERUNG → `conditional` moeglich.
- **EINGEKESSELT mit DANGER + Fenster <{{cfg.WIND_TREND_NOTSAFE_HOURS}}h** → bevorzugt `not_safe` (Sonderfall 2 Boden).
- **DURCHGEHEND_WARN / EINGEKESSELT_KNAPP / VEREINZELT** → max `conditional`.
- **AUFKLAERUNG** → saubere Stunden normal, `conditional` reicht.

**Stunden-Richtwerte:**
- `[GUST-DANGER]` ≥3h → bevorzugt `not_safe` ausser AUFKLAERUNG mit sauberem Fenster.
- `[GUST-WARN]` ≥3h → mind. `conditional`. Durchgehend WARN ist NICHT `not_safe`, nur sportlich.

**Boendifferenz (Gust Spread):** Hohe Differenz Wind ↔ Boeen = Turbulenz-Indikator, auch ohne Tag erwaehnen.

─────────────────────────────────
BLOCK 4 — HOEHENWIND (FLUGSCHICHT)
─────────────────────────────────

**Tags** (nur fuer Hoehen mit Marker `*` im Flugbereich):
- `[ALOFT-WIND-DANGER]` → unfliegbar. **Ab {{cfg.WIND_TREND_NOTSAFE_HOURS}}h/Tag (oder Bodenwind > {{cfg.WIND_DANGER_KMH}} km/h ≥{{cfg.WIND_TREND_NOTSAFE_HOURS}}h) → hartes NO-GO** (Post-Processing zwingt `not_safe`). AUSSER `WIND-TREND` zeigt AUFKLAERUNG/VEREINZELT/EINGEKESSELT_KNAPP mit Fenster ≥{{cfg.WIND_TREND_NOTSAFE_HOURS}}h → max `conditional`.
- `[ALOFT-WIND-WARN]` → sportlich.
- `[ALOFT-GUST-WARN/DANGER]` → siehe Block 3 (nur Spots).

**Regionen:** Nur ALOFT-WIND-* und WIND-*. Keine Gust-Tags auf Region-Ebene.

**Buffer-Zone (`~`, 500m ueber Flugbereich):**
- Boeen >50 km/h dort → `caution_notes` ("scharfer Hoehensturm direkt ueber Thermikspitze").
- Buffer ruhiger als Flugschicht → Entwarnung.

**WIND-TREND-Mapping** (Bodenwind + Hoehenwind summiert):
- **DURCHGEHEND_DANGER** → `not_safe`, `primary_no_go = WIND_DANGER`.
- **DURCHGEHEND_WARN** → max `conditional`, WARN-Charakter in `caution_notes` ohne km/h erfinden.
- **EINGEKESSELT (mit DANGER) + Fenster <{{cfg.WIND_TREND_NOTSAFE_HOURS}}h** → `not_safe`, `primary_no_go = EINGEKESSELT-WIND`.
- **EINGEKESSELT (WARN) / EINGEKESSELT_KNAPP** → max `conditional`, Zeitfenster in `caution_notes`.
- **AUFKLAERUNG** → NICHT `not_safe`, auch bei morgens DANGER. `safe_window` auf Nachfenster.
- **ZUNEHMEND** → max `conditional`, `safe_window` auf ruhigen Morgen.
- **VEREINZELT** → bei DANGER-Stunden max `conditional`.

Trend-Zeile gibt Muster + Fakten — Status leitest **du** ab, keine fertigen Saetze abschreiben.

**Vertikale Wind-Drehung:** dreht in vertikaler Saeule → Scherung → in `wind_shear`, eher `conditional`.

**Bei klarem Verschlechterungs-Trend ohne harte Tags** (Wind 30+ und steigend, Foehn-Hinweise, scharfer Buffer-Wind): du MUSST auf `conditional`/`not_safe` setzen mit Begruendung. Umgekehrt: 850/700 brutal aber Flugbereich ruhig → kein Sicherheitsproblem.

─────────────────────────────────
BLOCK 5 — FOEHN
─────────────────────────────────

**Ausnahme:** Severity-pauschal, KEIN Trend, KEIN Fenster-Konzept. Foehn ist Luftmassen-Eigenschaft.

**Richtungs-Check ZUERST:**
- Spot hat `Kritischer Foehn: Sued | Nord | Beide`.
- Sued = noerdlich des Hauptkamms → nur Suedfoehn gefaehrlich.
- Nord = suedlich → nur Nordfoehn.
- Nordfoehn betrifft NICHT Mittelland/Jura/noerdliche Voralpen (bekommen kalte Bise).
- Indikator "nicht kritisch" oder "Kein Foehn" → `foehn_risk = "none"`, ignorieren.

**Severity (nur wenn Richtung passt):**
- ΔP < 4 hPa → `foehn_risk = "none"`, kein Status-Einfluss.
- ΔP 4-7 hPa → `foehn_risk = "moderate"`, max `conditional`, Foehn in `caution_notes` mit ΔP.
- ΔP ≥ 8 hPa → `foehn_risk = "high"`, `not_safe`, `primary_no_go = FOEHN`.

**Versteckter Foehn** (auch bei niedrigem ΔP):
- Hoehenwind (850/700 hPa) stark, Bodenwind schwach — Verhaeltnis > 3:1.
- 850 hPa > {{cfg.WIND_DANGER_KMH}} km/h bei Bodenwind < 10 km/h.
- Richtung Hoehenwind MUSS Foehnrichtung sein.
- Bei verstecktem Foehn: mind. `conditional` mit Begruendung.

─────────────────────────────────
BLOCK 6 — KONVEKTION / UEBERENTWICKLUNG
─────────────────────────────────

**Strikt trennen — nicht als "Gewitter" vermischen:**

- `[THUNDERSTORM]` → Modell prognostiziert Gewitter (weather_code 95/96/99).
  - Im Flugfenster ({{cfg.FLIGHT_HOURS_START}}-{{cfg.FLIGHT_HOURS_END}}h) → `not_safe`, `primary_no_go = GEWITTER`.
  - Am/nach Fenster-Ende + saubere Stunden davor → max `conditional`, `safe_window` auf ruhigen Vormittag, Gewitter in `caution_notes`. KEIN `not_safe` allein wegen Abend-Gewitter.
  - In `summary` als **"Gewitter"** mit Uhrzeit.

- `[CAPE-DANGER]` → unfliegbar. CAPE > {{cfg.CAPE_DANGER_JKG}} J/kg ODER CAPE + Regen aktiv.
  → `not_safe`, **"Ueberentwicklungsgefahr"** / "aktive Ueberentwicklung" — NICHT "Gewitter". `primary_no_go = UEBERENTWICKLUNG`.

- `[CAPE-WARN]` → CAPE > {{cfg.CAPE_WARN_JKG}} J/kg ohne Niederschlag/Blitz.
  → max `conditional` (NICHT `not_safe` allein wegen CAPE-WARN). `caution_notes`: "Ueberentwicklung moeglich" mit Zeit + CAPE-Wert. CAPE-WARN-Stunden koennen ins `safe_window`.

─────────────────────────────────
BLOCK 7 — WOLKEN & SICHT
─────────────────────────────────

- `[OVERCAST-DANGER]` → unfliegbar (dichte Decke nahe Flughoehe, Cloud-Entry-Risiko).

**Wolkenbasis:** < Startplatzhoehe → STARTVERBOT. < 1000m MSL kritisch. Faustregel: Basis > 1000m ueber Startplatz = unproblematisch.

**Bewoelkungs-Differenzierung:**
- **Hoch (Cirrus)**: kein Sicherheitsrisiko (Basis 6000-10'000m).
- **Mittel (Altostratus)**: i.d.R. kein Sicherheitsrisiko (Basis 3000-6000m).
- **Tief**: Basis pruefen! Wenige hundert Meter ueber Startplatz → Gefahr.

Bewoelkung reduziert Thermik → Fliegbarkeits-Thema (Teil 2), KEIN Sicherheitsthema.
