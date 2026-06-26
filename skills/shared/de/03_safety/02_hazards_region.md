═══════════════════════════════════════════════
KERNREGEL — Stunden-Klassifikation
═══════════════════════════════════════════════

Jede Stunde:
- **RUHIG** — keine WARN/DANGER-Tags
- **SPORTLICH** — ≥1 WARN-Tag (WIND, ALOFT-WIND, CAPE), kein DANGER
- **UNFLIEGBAR** — ≥1 DANGER-Tag (RAIN-WARN, WIND/ALOFT-WIND-DANGER, CAPE-DANGER, THUNDERSTORM, OVERCAST-DANGER)

**Region hat keinen Sektor** → STARTBAR gegeben, solange `[WIND-DANGER]` nicht greift.

**"Saubere Stunde"** = nicht UNFLIEGBAR. **"Sauberes Fenster"** = mehrere zusammenhaengende saubere Stunden.

**`safe_window`:**
- = fliegbare Stunden (RUHIG + SPORTLICH).
- SPORTLICHE Stunden MUESSEN in `caution_notes` mit Uhrzeit + Grund stehen.
- UNFLIEGBARE Stunden NIEMALS ins `safe_window`.

═══════════════════════════════════════════════
TREND-VOKABULAR (7 Muster)
═══════════════════════════════════════════════

Jeder Gefahrenblock (Regen, Wind, Hoehenwind, CAPE, Wolken) folgt einem dieser Muster. Foehn = Ausnahme (severity-pauschal, Block 4).

1. **AUFKLAERUNG** — Gefahr morgens, zieht ab → saubere Stunden normal, **safe**/**conditional**.
2. **ZUNEHMEND** — startet ruhig, baut sich auf → max **conditional**, `safe_window` auf Morgen.
3. **EINGEKESSELT** — sauberes Fenster zwischen zwei Gefahrenphasen → siehe naechster Abschnitt.
4. **DURCHGEHEND (WARN)** — ≥75% WARN, kein DANGER → **conditional** (sportlich).
5. **DURCHGEHEND (DANGER)** — ≥75% DANGER → **not_safe**.
6. **VEREINZELT** — isolierte Gefahrenstunden → meist **conditional**, Uhrzeit in `caution_notes`.
7. **STABIL** — gleichbleibend ruhig → kein Status-Effekt. Nur in `caution_notes` wenn aktive Entwarnung oder beschreibend.

─────────────────────────────────
EINGEKESSELT — 3 Fragen
─────────────────────────────────

**Frage 1 — Schwere AUSSEN:** WARN → Ausgangspunkt `conditional`. DANGER → `not_safe`.

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

**Sonderfall 2 — Boden-Gefahren (Bodenwind, Regen):** Strengere Schwellen.
- **<5h** → immer `not_safe`, auch RUHIG innen.
- **≥5h + RUHIG innen** → `conditional` moeglich (≥90 min vor Rueckkehr landen).
- **≥5h + SPORTLICH durchsetzt** → `not_safe`.

═══════════════════════════════════════════════
GEFAHRENBLOECKE (Region: 6 Bloecke, KEIN Boeen)
═══════════════════════════════════════════════

─────────────────────────────────
BLOCK 1 — REGEN & FRONT
─────────────────────────────────

`[RAIN-WARN]` → Stunde UNFLIEGBAR (zaehlt als DANGER). Trifft Landung → **Sonderfall 2** bei EINGEKESSELT.

Sauberes Fenster zwischen Regenphasen ist NICHT automatisch safe — Trend-Muster bestimmt Status.

─────────────────────────────────
BLOCK 2 — BODENWIND (Staerke, kein Sektor)
─────────────────────────────────

**Tags:**
- Kein Tag (< {{cfg.WIND_WARN_KMH}} km/h) → ruhig
- `[WIND-WARN]` → sportlich ({{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h)
- `[WIND-DANGER]` → unfliegbar (> {{cfg.WIND_DANGER_KMH}} km/h)

**Trend:** Bodenwind + Hoehenwind teilen `WIND-TREND` (gleiche Schwellen). Mapping siehe Block 3.

System liefert Zahlen — nicht selbst nachzaehlen.

─────────────────────────────────
BLOCK 3 — HOEHENWIND (FLUGSCHICHT)
─────────────────────────────────

**Tags** (nur fuer Hoehen mit Marker `*` im Flugbereich):
- `[ALOFT-WIND-DANGER]` → unfliegbar. **Ab {{cfg.WIND_TREND_NOTSAFE_HOURS}}h/Tag (oder Bodenwind > {{cfg.WIND_DANGER_KMH}} km/h ≥{{cfg.WIND_TREND_NOTSAFE_HOURS}}h) → hartes NO-GO** (Post-Processing zwingt `not_safe`). AUSSER `WIND-TREND` zeigt AUFKLAERUNG/VEREINZELT/EINGEKESSELT_KNAPP mit Fenster ≥{{cfg.WIND_TREND_NOTSAFE_HOURS}}h → max `conditional`.
- `[ALOFT-WIND-WARN]` → sportlich.

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

**Bei klarem Verschlechterungs-Trend ohne harte Tags** (Wind 30+ und steigend, Foehn-Hinweise): du MUSST auf `conditional`/`not_safe` setzen mit Begruendung. Umgekehrt: 850/700 brutal aber Flugbereich ruhig → kein Sicherheitsproblem.

─────────────────────────────────
BLOCK 4 — FOEHN
─────────────────────────────────

**Ausnahme:** Severity-pauschal, KEIN Trend, KEIN Fenster-Konzept. Foehn ist Luftmassen-Eigenschaft.

**Richtungs-Check ZUERST** (siehe `_region_context.md`):
- Region hat `Kritischer Foehn: Sued | Nord | Beide`.
- Wenn Richtung nicht passt: `foehn_risk = "none"`, ignorieren.

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
BLOCK 5 — KONVEKTION / UEBERENTWICKLUNG
─────────────────────────────────

**Strikt trennen — nicht als "Gewitter" vermischen:**

- `[THUNDERSTORM]` → Modell prognostiziert Gewitter (weather_code 95/96/99).
  - Im Flugfenster ({{cfg.FLIGHT_HOURS_START}}-{{cfg.FLIGHT_HOURS_END}}h) → `not_safe`, `primary_no_go = GEWITTER`.
  - Am/nach Fenster-Ende + saubere Stunden davor → max `conditional`, `safe_window` auf ruhigen Vormittag, Gewitter in `caution_notes`. KEIN `not_safe` allein wegen Abend-Gewitter.
  - In `summary` als **"Gewitter"** mit Uhrzeit.

- `[CAPE-DANGER]` → unfliegbar. CAPE > {{cfg.CAPE_DANGER_JKG}} J/kg ODER CAPE + Regen aktiv.
  → `not_safe`, **"Ueberentwicklungsgefahr"** — NICHT "Gewitter". `primary_no_go = UEBERENTWICKLUNG`.

- `[CAPE-WARN]` → CAPE > {{cfg.CAPE_WARN_JKG}} J/kg ohne Niederschlag/Blitz.
  → max `conditional` (NICHT `not_safe` allein). `caution_notes`: "Ueberentwicklung moeglich" mit Zeit + CAPE-Wert. CAPE-WARN-Stunden koennen ins `safe_window`.

─────────────────────────────────
BLOCK 6 — WOLKEN & SICHT
─────────────────────────────────

- `[OVERCAST-DANGER]` → unfliegbar (dichte Decke nahe Flughoehe).

**Wolkenbasis:** < 1000m MSL kritisch. Faustregel: Basis hoch genug ueber Region-Ref = unproblematisch.

**Bewoelkungs-Differenzierung:**
- **Hoch (Cirrus)**: kein Sicherheitsrisiko (Basis 6000-10'000m).
- **Mittel (Altostratus)**: i.d.R. kein Sicherheitsrisiko (Basis 3000-6000m).
- **Tief**: Basis pruefen!

Bewoelkung reduziert Thermik → Fliegbarkeits-Thema (Teil 2), KEIN Sicherheitsthema.
