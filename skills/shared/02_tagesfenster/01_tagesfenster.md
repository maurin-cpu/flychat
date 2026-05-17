═══════════════════════════════════════════════
TAGESFENSTER — bereits vom System bestimmt
═══════════════════════════════════════════════

Der Datenblock enthaelt nur Stunden ab dem **Tagesbeginn** — der Zeitpunkt ab dem ein qualifizierendes Start-Fenster (≥ {{cfg.CLEAN_WINDOW_MIN_HOURS}}h zusammenhaengend sauber) beginnt. Header `═══ TAGESFENSTER ═══` mit `Tag aktiv ab HH:00` ist **autoritativ**.

──────────────────────────────────
WAS HEISST "TAGESBEGINN"?
──────────────────────────────────

Code hat geprueft: erstes Fenster sauberer Stunden (Spot: WIND-OK ohne DANGER. Region: kein DANGER) der Laenge ≥ {{cfg.CLEAN_WINDOW_MIN_HOURS}}h → dessen Start-Stunde = Tagesbeginn. Kein Fenster → Tag bereits als `not_safe` ausgefiltert, siehst du nicht.

Stunden vor Tagesbeginn wurden weggelassen (Bodenwind ausserhalb Sektor oder harte Warnungen aktiv). Header nennt Grund.

──────────────────────────────────
DEINE AUFGABE: FENSTER-NARRATIVE
──────────────────────────────────

1. **WIE VIELE FENSTER?**
   - 1 langes: normal beschreiben.
   - 2+ mit DANGER-Pause: fragmentiert in `summary` benennen ("zwei nutzbare Fenster, dazwischen Schauer/Gewitter").

2. **WIE LANG?**
   - ≥ 4h: Tagesflug, normale Bewertung.
   - 2-3h: in `caution_notes` ("nur Xh fliegbar").
   - < {{cfg.CLEAN_WINDOW_MIN_HOURS}}h: kommt nicht zu dir — Pre-Filter hat schon `not_safe` gesetzt.

3. **WIND-DREHER NACH TAGESBEGINN?**
   - `[WIND-WRONG]` nach Tagesbeginn = Bodenwind dreht im Tagesverlauf, Pilot ist bereits in der Luft. KEIN Hazard, KEIN Status-Effekt.
   - Wenn Dreh >2h Lande-Aspekte beruehrt: optional in `caution_notes` als nuechterner Lande-Hinweis ("Rueckkehr-Wind ab HH:00 ungueltig"), keine Risiko-Sprache.

──────────────────────────────────
WAS DU NICHT MACHST
──────────────────────────────────

- Tagesbeginn nicht infrage stellen — Code hat deterministisch bestimmt.
- Stunden vor Tagesbeginn nicht ergaenzen/rekonstruieren/beklagen.
- `not_safe` nicht aus Fenster-Laenge ableiten — Code hat Mindestbedingung geprueft.
- `[WIND-WRONG]` im aktiven Tag NIE als "Gefahr"/"Risiko"/"Warnung" framen.

──────────────────────────────────
BEISPIELE
──────────────────────────────────

**Fall 1 — durchgehend lang:** `Tag aktiv ab 11:00`, Stunden 11-17 sauber.
→ `summary`: "Sechs Stunden zusammenhaengendes Flugfenster zwischen 11 und 17 Uhr."

**Fall 2 — zwei Fenster mit Pause:** `Tag aktiv ab 10:00`, 10-12 sauber, 13-14 [RAIN-WARN], 15-17 sauber.
→ `summary`: "Zwei Fenster: 10-12 Uhr und 15-17 Uhr, dazwischen Schauer-Phase."

**Fall 3 — Wind dreht im aktiven Tag (Spot):** `Tag aktiv ab 11:00`, 11-14 [WIND-OK], 15-17 [WIND-WRONG].
→ `summary`: "Vier Stunden Start-Fenster bis 15 Uhr, danach dreht der Bodenwind."
→ Optional `caution_notes`: "Rueckkehr-Wind ab 15 Uhr ausserhalb Sektor — Lande-Optionen pruefen."
→ `safety_status` bleibt unbeeinflusst.
