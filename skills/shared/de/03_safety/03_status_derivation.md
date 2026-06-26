═══════════════════════════════════════════════
TAGES-OVERRIDE (nach Gefahrenbloecken)
═══════════════════════════════════════════════

**Du rechnest NICHTS.** System liefert alle Zahlen im TAGESPROFIL.

─────────────────────────────────
OVERRIDE A — 35%-REGEL
─────────────────────────────────

Lies `Verhaeltnis sauber/gesamt: X/Yh = Z%` (sauber = RUHIG + SPORTLICH):
- **Z < 35**: Tag ueberwiegend gefaehrlich. Auch bei 4h-Fenster → max **conditional**, eher **not_safe** falls eingekesselt.
- **Z 35-60**: Mischtag. `safe` moeglich wenn Fenster durchgehend RUHIG UND nicht eingekesselt.
- **Z > 60**: Normalfall.

**Pflicht:** Bei `→ ACHTUNG Verhaeltnis < 35%` MUSS in `caution_notes` oder `no_go_reasons` reflektiert werden.

EINGEKESSELT + Wind-Trend in TREND-VOKABULAR (`_hazards_*.md`). OVERRIDE B (WIND-DIRECTION) ist entfallen — Start-Fenster-Regel in Block 2 ersetzt sie.

═══════════════════════════════════════════════
STATUS-ABLEITUNG (finaler Schritt Teil 1)
═══════════════════════════════════════════════

1. Lies `Laengstes Fenster: Xh` aus FENSTER-INFO. Verbindlich.
2. Pro Gefahrenblock: Trend-Muster bestimmen, EINGEKESSELT-Sonderfaelle pruefen.
3. OVERRIDE A (35%) anwenden.
4. Status nach Start-Fenster-Regel:
   - **safe**: Fenster ≥{{cfg.CLEAN_WINDOW_MIN_HOURS}}h UND Verhaeltnis ≥60% UND kein EINGEKESSELT-Sonderfall UND kein Foehn-Verbot UND Fenster mehrheitlich RUHIG.
   - **conditional**: Fenster ≥{{cfg.CLEAN_WINDOW_MIN_HOURS}}h, aber Fenster mehrheitlich SPORTLICH ODER Verhaeltnis 35-60% ODER EINGEKESSELT-WARN ODER aktiver WARN-Tag (GUST-WARN, ALOFT-WARN, CAPE-WARN, BOEEN-FLOOR=conditional, Foehn ΔP 4-7). **NIE `conditional` allein wegen kurzer Fenstergroesse** — < {{cfg.CLEAN_WINDOW_MIN_HOURS}}h ist immer `not_safe`.
   - **not_safe**: Fenster < {{cfg.CLEAN_WINDOW_MIN_HOURS}}h ODER Verhaeltnis <35% mit EINGEKESSELT ODER EINGEKESSELT-DANGER ODER Foehn/Gewitter dominiert.

═══════════════════════════════════════════════
BEGRUENDUNGS-PRINZIP FUER SATZ 1 IN `summary`
═══════════════════════════════════════════════

Ableitung sagt **welcher Status**. Begruendung sagt **womit du Satz 1 fuellst** — selbst formuliert in Pilotensprache, mit konkreten Zahlen. Kein Schema, keine Platzhalter.

**Prinzip pro Status:**

- **`not_safe`** → nenne die **dominierende Gefahr** (passt zu `primary_no_go`) mit Wert + Uhrzeit.
  - *Beispiel (nicht abschreiben):* "Nicht sicher wegen Foehn-Durchbruch ΔP 8.4 hPa Sued ab 11 Uhr — Druckgradient klar ueber Verbots-Schwelle."

- **`conditional`** → nenne **den Faktor der den Tag von `safe` heruntergezogen hat**. Genau ein Ableitungs-Punkt hat gegriffen — diesen mit Zahlen nennen.
  - **NIEMALS** das Fenster, ruhige Stunden oder fehlende Gefahren als Begruendung — Fenster ist Voraussetzung dass Tag ueberhaupt nicht `not_safe` ist.
  - *Beispiel:* "Bedingt sicher wegen kraeftiger Boeen 28-34 km/h ab 13 Uhr — ruhige Stunden bleiben in der Minderheit."

- **`safe`** → nenne **die Konstellation die den Tag entspannt macht**. Schau auf hoechste Safety-Sub-Ratings — das erzaehlt was den Tag traegt. Konkret in Pilotensprache.
  - **NIEMALS** "Tag wird als sicher eingestuft" (nichtssagend), "weil keine Probleme" (negativ), Audit-Sprache, oder blosse Fenster-Existenz. KEIN Thermik/Streckenflug-Inhalt — gehoert in Flyability.
  - *Beispiel:* "Sauberer Westwind 8-12 km/h durchgehend in passender Richtung, Hoehenwind moderat um 22 km/h auf 2500m — fliegerisch ruhige Konstellation."

Beispiele sind Inspiration, kein Pflicht-Schema. Wichtig ist das **Was** (begrenzender Faktor / dominierende Gefahr / tragende Konstellation), nicht das **Wie**.
