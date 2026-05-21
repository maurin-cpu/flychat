# XContest-Validierung — Wiederkehrende Muster

Akkumulierter Issue-Tracker über alle analysierten XContest-Tage.
Jeder Issue zählt Tage, an denen er beobachtet wurde — sobald Muster
konsistent auftauchen, lohnt sich ein Kalibrierungs-Eingriff.

**Status-Werte**: `offen` / `in-untersuchung` / `gefixt` / `nicht-reproduzierbar`

---

## I-001 — not_safe False-Positives bei Voralpen/Jura/Walliser Spots

**Erstmals**: 2026-05-17
**Tage beobachtet**: 2 (17.05, 20.05)
**Status**: in-untersuchung (Trigger identifiziert, Sub-Issues separieren)

**Betroffene Spots (17.05.)**:
- Weissenstein (6 Flüge, bester 107 km)
- Obere Wengi / Niederhorn (6 Flüge, bester 107 km)
- Mont Raimeux Nord/Süd (1 Flug, 106 km)
- Wispile 1/2 (1 Flug, 75 km)
- Amisbühl oben (2 Flüge, 69 km)
- Mäggisseren (1 Flug, 63 km)
- Buochserhorn (1 Flug, 51 km)
- Scheidegg + Alp Scheidegg (3 Flüge, bis 47 km)
- Le Suchet (2 Flüge, bis 46 km)
- Brunnihütte (1 Flug, 45 km)

**Betroffene Spots (20.05.)**:
- Ramslauen (1 Flug, 4.15 km — Block-Filter)
- St. Cergue (1 Flug, 8.14 km — Sektor zu eng)
- Cry d'Er / Aminona (1 Flug 9.60 km, gemeldet als "Crans-Mon..." — Sektor + Mapping)
- Jeizinen (1 Flug, 2.81 km morgens — Sektor + Wind-Staerke ignoriert)

### Trigger identifiziert (Code-Pfad: `engine/analyzers.py:128-219`, `_prefilter_not_safe`)

**Es ist NICHT die Decision-Engine** — `_decisions_applied` ist leer für alle
diese Spots. Der Filter ist ein **Pre-Filter** vor der Decision-Engine.

Zwei Pre-Filter-Pfade triggern (je nach Spot):

**Pfad A: "Windrichtung: Ganztaegig ausserhalb des erlaubten Sektors"**
(Trigger: `wind_ok == 0`, betrifft Weissenstein, Mont Raimeux Nord,
Buochserhorn, Scheidegg, Le Suchet, Brunnihütte, Wispile 2)

**Pfad B: "Start-Fenster: Nur Xh sauber, kein zusammenhaengender Block >= 3h"**
(Trigger: `active_window_start is None` trotz `wind_ok > 0`, betrifft
Niederhorn, Mont Raimeux Süd, Wispile 1, Amisbühl oben, Mäggisseren,
Alp Scheidegg)

→ Schwelle `CLEAN_WINDOW_MIN_HOURS = 2` in `config.py:605` — eigentlich nur
2h, aber Logging-Text sagt fälschlich "3h".

### Sub-Issues (aus Wind-Daten 17.05.)

→ siehe **I-006**, **I-007**, **I-008**, **I-009** unten.

---

## I-002 — Streckenflug-Rater fällt auf Default 1 bei `region_context_missing`

**Erstmals**: 2026-05-17
**Tage beobachtet**: 1
**Status**: offen (vermutlich Bug)

**Betroffene Spots**:
- Fiescheralp (Tagessieger 175 km — xc=1)
- Obere Wengi (107 km — xc=1)
- Mauborget (65 km — xc=1)
- Rotenfluespitz (52 km — xc=1)

**Beobachtung**: `streckenflug.limiting_factor` = `region_context_missing` →
Rating wird nicht inhaltlich vergeben, sondern fällt auf 1 zurück. Dieser
Fallback hat den Effekt, dass real exzellente XC-Spots als nicht-streckentauglich
markiert werden.

**Vermutete Ursachen**:
- Region-Context wird beim Spot-Rating-Build nicht gefunden (Mapping-Fehler?)
- Region-Analyse läuft zeitlich nach der Spot-Analyse, Context noch nicht da?
- Code-Pfad in `engine/analyzers.py` oder Decision-Engine

**Nächste Schritte**:
- Code-Pfad für `region_context_missing` finden
- Klären: ist der Fallback "default 1" gewollt oder ein Bug?

---

## I-003 — Jura-Regionen systematisch zu tief gerated (Region-Ebene)

**Erstmals**: 2026-05-17
**Tage beobachtet**: 1
**Status**: offen

**Betroffene Regionen**:
- Jura Zentral (exp=2 bei 9 Top-Flügen inkl. 107 km)
- Jura West (exp=2 bei 5 Top-Flügen inkl. 65 km)

**Kontext**: Laut Memory `rating_region_calibration_mai2026` wurden Booster
bewusst verworfen ("Wack-a-Mole-Spirale"). Resultat: bei Thermik-Peak <2.5 m/s
mit hoher XC-Substanz greift kein Floor → Rating bleibt 3 (oder darunter),
obwohl real 100+ km möglich.

**Vermutete Ursachen**:
- Floor "XC-Substanz → min 5" greift nicht (nicht definiert? Bedingungen
  nicht erfüllt? Bug?)
- LLM-Urteil im Jura konservativ, weil "Mittel-Höhe + flach" mit niedrigem
  Peak assoziiert

**Nächste Schritte**:
- Prüfen welche Region-Floors heute getriggert wurden (`_decisions_applied`)
- Falls "XC-Substanz → min 5" Floor existiert: warum hat er nicht gefeuert?

---

## I-004 — Oberwallis/Goms: Föhn-Caution dämpft Rating an Top-XC-Tag

**Erstmals**: 2026-05-17
**Tage beobachtet**: 1
**Status**: offen

**Beobachtung**: Tagessieger 175 km ab Fiesch, Region rated conditional/exp=3.
`_decisions_applied`: `FoehnCaution(4.2)`.

**Vermutete Ursache**: FoehnCaution-Decision feuert auch in Konstellationen,
in denen Föhn fliegerisch keine Rolle spielt (z.B. mässige Wind-Stärke trotz
Süd-Komponente). Möglicher Tuning-Bedarf in der FoehnCaution-Schwelle.

**Nächste Schritte**:
- Höhenwind- und Bodenwind-Profile von Fiesch heute extrahieren
- Mit den Pilotentracks (XContest IGC) cross-checken: hat Föhn die Flüge
  irgendwo limitiert?

---

## I-005 — Coverage-Gaps: produktive Spots nicht in unserer DB

**Erstmals**: 2026-05-17
**Tage beobachtet**: 3 (17.05, 18.05, 20.05) — Tussweid wiederholt 18.05+20.05
**Status**: offen

**Fehlende Spots (Top-100-Flug-Generatoren) 17.05.**:
- Grindelwald, Riederalp, Albagno, Bözingenberg, Carì, Turren, Verbier,
  Ämsigen, Laubbärgli, Anzère, Crans-Montana, Hinterrugg (Toggenburg),
  Tschenten, Mäggisseren — zusammen ~30 Top-100-Flüge an 1 Tag.

**Fehlende Spots 18.05.**:
- Tussweid (1 Flug, Ostschweiz/Toggenburg)
- Gornergrat (1 Flug, Zermatt-Hochalpin)

**Fehlende Spots 20.05.**:
- **Burgfeldstand** (1 Flug, 14.04 km von C. Boo — hochpriorisiert, Niederhorn-Massiv)
- **National** (1 Flug, 12.75 km von A. Eberhardt — Name unklar, IGC-Mapping nötig)
- Crans-Montana (Multi-Sektor-Variante mit W/NW fehlt — Bellalui ist NO-W aber XContest-Pilot bezeichnete Spot anders)
- Le pont (1 Flug, 3.76 km, Vallee de Joux)
- Blapbach (1 Flug, 3.71 km, Emmental — niedrige Prio)
- **Tussweid (wiederholt vom 18.05)** — Pattern: gleicher Pilot, kleiner Spot, fehlt durchgehend

**Vermutete Ursachen**:
- Spots in `fluggebiete_complete.csv` fehlen
- Spots existieren unter abweichendem Namen (z.B. "Niederhorn" für
  Obere Wengi) — Mapping-Tabelle nötig

**Nächste Schritte**:
- Liste mit den 14 fehlenden Spots in `data/fluggebiete_complete.csv` ergänzen
  (sofern relevant für unseren Scope)
- Alias-Tabelle Spotname-XContest → Spotname-DB

---

---

## I-006 — Sektor-Definition in `fluggebiete_complete.csv` zu eng

**Erstmals**: 2026-05-17
**Tage beobachtet**: 2 (17.05, 20.05)
**Status**: offen — heute jedes False-Positive auf diesem Issue

**Beobachtung**: Mehrere Spots haben in der CSV nur **eine** Hauptstart-Richtung,
real aber mehrere brauchbare Sektoren oder einen breiteren Wind-Sektor als
angegeben.

**Beispiele (Wind heute vs. CSV-Sektor)**:

| Spot | CSV-Sektor | Real-Wind 09-17h | Pilot-Realität |
|---|---|---|---|
| Weissenstein | S-SO (135-180°) | SSW-SW (195-235°) | 6 Flüge ab dort, 107 km |
| Brunnihütte | W-SW (270-202°) | WNW-NW (296-321°) | 1 Flug, 45 km |
| Mont Raimeux Nord | N-NO (0-45°) | NNW dominant (340-350°) | 1 Flug Raimeux, 106 km |
| St. Cergue (20.05) | SO-S (135-180°) | W (285°) | 1 Flug 8.14 km, 56 min |
| Cry d'Er / Aminona (20.05) | SSW-SSO (≈150-195°) | NW (308-349°) | 1 Flug 9.60 km — eher von W-Hang |
| Jeizinen (20.05) | SO-S (135-180°) | W (268°) morgens | 1 Flug 2.81 km, 09 min |

→ CSV-Sektoren wurden vermutlich konservativ aus dem Hauptstart definiert, nicht
aus dem realen Fenster, in dem ein erfahrener Pilot starten würde. Plus: viele
Spots haben mehrere Startwiesen mit unterschiedlichen Expositionen, die DB
führt aber nur eine Variante.

**Nächste Schritte**:
- Liste Spots mit häufigen "Windrichtung ausserhalb"-NoGo-Trigger
- Manueller Review der Top-20 problematischsten gegen reale Spot-Beschreibungen
  (z.B. burnair, paragliding-mapping.com)
- Sektoren entweder verbreitern oder Spots mit Multi-Sektor-Charakter
  als mehrere Einträge pflegen

---

## I-007 — `CLEAN_WINDOW_MIN_HOURS = 2` blockt 1-Stunden-Starts

**Erstmals**: 2026-05-17
**Tage beobachtet**: 2 (17.05, 20.05 — Ramslauen-Mechanismus identisch)
**Status**: offen

**Beobachtung**: Schwelle "zusammenhängender Block ≥ 2h" sperrt Spots aus,
deren passendes Wind-Fenster real nur 1-2h dauert. Locals starten aber
nachweislich in solchen Fenstern (Streckenflug 60+ km möglich).

**Beispiele 17.05.**:
- Mäggisseren: 10h einzige passende Stunde (SO), danach Ostwind →
  1 Flug 63 km gestartet
- Mont Raimeux Süd: 08-09h passend (SSO/S), danach West →
  1 Flug 106 km gestartet
- Amisbühl oben: 11h passend (166°), 12-13h knapp drüber (178-182°) →
  2 Flüge mit 69 km
- Wispile 1: 10-11h passend (98-69°/ONO) → fällt durch 2h-Minimum aus,
  obwohl genau im Sektor

**Mögliche Fixes** (Trade-offs zu durchdenken):
- Schwelle auf 1h reduzieren → mehr Spots als "fliegbar" gerated, weniger
  False-Positives, aber auch mehr Risiko-Spots durchgelassen
- Schwelle abhängig vom Spot-Typ machen (Streckenflug-Spot vs. Soaring-only)
- Sektorpuffer ±10° (Toleranz an Sektor-Rändern) statt fixer Block-Anforderung

**Nächste Schritte**:
- Statistik: wie viele Spots fielen pro Tag durch 2h-Filter über mehrere Tage?
- Korrelation zu XContest-Aktivität: feuert der Filter überproportional an
  Tagen, an denen real geflogen wurde?

---

## I-008 — Pre-Filter ignoriert Wind-Stärke

**Erstmals**: 2026-05-17
**Tage beobachtet**: 2 (17.05, 20.05)
**Status**: offen

**Beobachtung**: Sektor-Filter prüft nur Richtung, nicht Stärke. Bei
**sehr schwachem Wind** (z.B. Mont Raimeux Nord 1-7 km/h bei 13h) ist die
Richtung fliegerisch fast egal — Thermik dominiert. Trotzdem schiesst der
Filter den Spot auf not_safe.

**Beispiel**: Mont Raimeux Nord, 13:00 — Wind 124° aus SO bei 1.3 km/h.
Sektor wäre N-NO. Real: bei 1.3 km/h startet niemand "gegen den Wind", man
nimmt was die Thermik gibt.

**Beispiel 20.05.**: Jeizinen, 08:39 — Frueh-Hop. Tagespeak-Gust spaeter 76 km/h,
aber morgens vermutlich lokales Bergwind-System (Talwind noch nicht eingesetzt).
Sektor-Filter pruefte nur die dominante Tagesrichtung 268° (W) — die spezifische
Morgenstunde wurde nicht differenziert betrachtet. 9-min-Flug bestaetigt, dass
das Morgen-Fenster real andere Bedingungen hatte als der Tages-Aggregat sagt.

**Möglicher Fix**: Wenn Wind < z.B. 5 km/h, Sektor-Check skippen (oder
Schwelle auf "Sektor irrelevant").

**Nächste Schritte**:
- In `_prefilter_not_safe` oder dem upstream `wind_ok_count`-Berechner prüfen,
  ob es eine Mindest-Wind-Schwelle gibt unterhalb derer "ok" als default
  gesetzt werden sollte
- Lokale Pilot-Praxis-Check: bei welcher Bodenwind-Stärke wird Sektor wieder
  weniger relevant?

---

## I-009 — Spot-Mapping XContest-Bezeichnung → DB-Bezeichnung

**Erstmals**: 2026-05-17
**Tage beobachtet**: 2 (17.05, 20.05)
**Status**: offen

**Beobachtung**: XContest verwendet andere Spot-Namen als unsere DB. Wenn das
Mapping falsch ist, wird der Vergleich falsch.

**Konkrete Verwechslungen**:
- "Obere Wengi" (XContest) → von uns gemappt auf "Niederhorn" — vermutlich
  falsch. Obere Wengi liegt am SW-Hang vom Niederhorn-Massiv, ist aber
  vermutlich ein eigener Spot mit anderer Exposition. CSV listet nur
  "Niederhorn" mit SSW-SSO-Sektor — der reale Niederhorn-Süd-Start. Obere
  Wengi ist möglicherweise S-SW-orientiert.
- "Mont Raimeux" (XContest) → bei uns als "Mont Raimeux Nord" und "Mont
  Raimeux Süd" — XContest unterscheidet nicht, wir schon. Welcher der
  beiden wurde geflogen?
- **20.05.** "Crans-Mon..." (XContest) → Cry d'Er + Aminona (beide SSW-SSO,
  not_safe bei NW-Wind), aber Bellalui (NO-W, conditional) am gleichen Massiv
  passt zur tatsächlichen Strömung. Plausibel: Pilot startete an einem nicht-DB-
  gelisteten Launch der Crans-Montana-Bergstation oder von Bellalui-Hang.
- **20.05.** "Burgfelds..." → XContest-Truncate. Vermutlich Burgfeldstand
  (Niederhorn-Massiv, Berner Voralpen). Nicht in DB. **Hochpriorisiert**
  (14 km Strecke).
- **20.05.** "National" (Andreas Eberhardt) → unklarer Name. IGC-Trackpoint
  laden zum Identifizieren.

**Nächste Schritte**:
- Bei zukünftigen XContest-Auszügen Alias-Tabelle führen
- Klären: ist "Obere Wengi" tatsächlich Niederhorn oder eigener Spot?
  → Spot in DB ergänzen falls Lücke

---

## I-010 — Tages-Niederschlags-Aggregat blockiert Morgen-Fenster

**Erstmals**: 2026-05-18
**Tage beobachtet**: 2 (18.05, 20.05)
**Status**: offen

**Beobachtung**: `precip_sum_mm` summiert den gesamten Tag — wenn der Hauptregen
nachmittags/abends fällt, blockiert die Aggregation faelschlich das trockene
Morgen-Fenster. Spots werden auf `not_safe` gesetzt, obwohl Piloten morgens
real geflogen sind.

**Beispiele**:

| Spot | precip_sum (Tag) | Real-Flug | Regen-Zeitpunkt |
|---|---|---|---|
| Braunwald (18.05) | 23.0 mm | 19.14 km, Start 09:51 | Hauptmenge nachmittags |
| Ramslauen (20.05) | 11.9 mm | 4.15 km, Start 13:08 | RAIN-Stop-Tag laut Tags ab 15-18h |

**Mögliche Fixes**:
- `precip_sum_mm` ersetzen durch `precip_flight_window_mm` (08-20h Summe) oder
  noch enger 3h-Fenster um den Flug-Zeitpunkt
- Pre-Filter zusätzlich pro-Stunde-Block-Check: gibt es 2-3h ohne Regen + im Sektor?
- Decision-Engine könnte Regen als zeit-gebunden ausweisen ("Regen ab 15h",
  nicht "Tages-Niederschlag 12mm")

**Nächste Schritte**:
- Prüfen, ob `precip_sum_mm` aktuell in den Pre-Filter eingeht (vs. nur
  hourly precipitation pro Stunde)
- Hourly-Regen-Werte für Braunwald 18.05 und Ramslauen 20.05 aus Snapshot
  extrahieren und gegen Real-Start-Zeit prüfen

---

## Auswertungs-Roadmap

- Nach jeder neuen Analyse: hier Tage-Zähler hochschreiben
- Bei ≥3 Tagen für einen Issue: Cause-Hypothese im Code prüfen
- Bei ≥5 Tagen: Fix planen
- Issues, die nur 1× auftraten, nach 30 Tagen ggf. archivieren
