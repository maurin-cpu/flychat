# XContest-Validierung — Wiederkehrende Muster

Akkumulierter Issue-Tracker über alle analysierten XContest-Tage.
Jeder Issue zählt Tage, an denen er beobachtet wurde — sobald Muster
konsistent auftauchen, lohnt sich ein Kalibrierungs-Eingriff.

**Status-Werte**: `offen` / `in-untersuchung` / `gefixt` / `nicht-reproduzierbar`

> ⚠ **Migrations-Bruch 2026-05-22** — Spot-Quelle (DHV → PGE, 487 → 495 Spots),
> Wind-Sektor-Modell (Text → 8 Binär-Spalten, neuer `/`-disjoint-Separator) und
> Skill-Eingangs-Format (Bemerkungen vor-klassifiziert in `Flug`/`Sicherheit`)
> wurden umgestellt. Siehe `2026-05-22.md` (Migrations-Marker). Issue-Tageszähler
> ab diesem Datum **nicht direkt mit Pre-Migration-Tagen mergen** — viele
> Pre-Migration-Findings (insb. I-006 Sektor-Drift, I-009 Mapping) können
> durch die neue Datenbasis aufgelöst sein, müssen aber Tag-zu-Tag re-validiert
> werden. 71/488 PGE-Spotnamen matchen alte DHV-Schlüssel direkt; der Rest
> braucht coordinate-based Mapping.

---

## I-001 — not_safe False-Positives bei Voralpen/Jura/Walliser Spots

**Erstmals**: 2026-05-17
**Tage beobachtet (Pre-Migration)**: 4 (17.05, 19.05, 20.05, 21.05)
**Tage beobachtet (Post-Migration ≥22.05)**: 1 (24.05)
**Status**: in-untersuchung (Trigger identifiziert, Sub-Issues separieren) — **Top-Refactor-Prio**

**Betroffene Spots (24.05.)** — Wallis-Festival mit 295 PG-Eintraegen (Tagessieger 295km Riederalp/Aeschbach):
- **Verbier-Trio** (Ruinettes S-SW-W + Croix-de-Coeur SO-S-SW): 6 Launches, **153 km MARET** (Wind 307° NW, beide Varianten ausserhalb)
- **Niesen** (SW Sektor): **130 km JOHNSTON** (Wind 62° NE)
- **Grand Chamossaire** (S-SW-W): 3 Launches, **101 km RUDAZ** (no_go=`Ueberentwicklungsgefahr CAPE >1500`, NEU)
- **Haldigrat** (SW): **9 Launches, 61 km BOHREN** (Wind 62° NE — Single-Sided-Sektor)
- **Cimetta** (S-SW): 4 Launches, **56 km BOSCACCI** (Wind 168° **IM Sektor**, nur Block-Filter → I-007)
- **Niederhorn** (SO-S): **7 Launches, 43 km HINNI** (Wind 71° NE, klassischer NE-Tag-Klassiker)
- **Montlinger Schwamm** (N-NO): 2 Launches, 43 km MARTY (Wind 25° NE **IM Sektor** → I-007)
- **Hinterrugg/Jaman/Stockberg** je 2× und kleinere 1×-Eintraege bis 26 km

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

**Betroffene Spots (21.05.)** — MASSIVER Tag mit 240 PG-Eintraegen (Tagessieger 168km Ebenalp):
- **Obere Wengi** (11 Launches inkl. **97km Haenni**, Andres 87, Bürgi 71, Leu 71, Baumann 65, Hasler 63, Liechti 60, Fassbind 48, Schilling 47)
- **Scheidegg + Alp Scheidegg** (4 Launches inkl. **113km Erne** Tag-Topflug fuer den Spot — beide Varianten not_safe)
- **Niesen** (5 Launches inkl. 78km Kaempfer — Wind 72°E bei Gust 17 km/h schwach)
- **St. Anton** (1× 85km — Wind 36°NE ausserhalb SO-S)
- **Brunnihuette** (**12 Launches!** inkl. 59km Frommenwiler — Wind 350°N total ausserhalb W-SW; vermutlich N/NE-Variante fehlt in DB)
- **Rotenfluespitz** (**7 Launches** inkl. 46km Walder — Wind 35°NE ausserhalb WNW-WSW)
- **Niederhorn** (2 Launches inkl. 49km Hinni — Wind 57°NE)
- **Weissenstein** (44km Saliba — Wind 72°E exakter Repeat 17.05)
- **Haldi** (43km Bohren — Wind 282°W knapp ausserhalb SSW-WSW)
- **Kronberg 1** (5 Launches inkl. 43km — **Sektor NW-NO + Wind 42°NE EXAKT im Sektor, nur Block-Filter blockiert!**)
- **Le Suchet** (4 Launches inkl. 38km Rod — Wind 70°E ausserhalb NNO-N)
- **Montoz** (37km Veya — Wind 97°E)
- **Hohwacht** (5 Launches — Wind 71°E ausserhalb NNW-NNO)
- **Jaman** (2 Launches inkl. 29km — Wind 24°NNE)
- **Burst** (24km — Block-Filter)
- **Buelen** (Wind 56°NE EXAKT in NO-SO Sektor — **2. Tag in Folge** Filter-Bug-Verdacht)
- viele kleinere Hops (Pilatus Kulm, Niederbauen, Kerenzerberg, Fronalpstock, Vilan, Rorschach, Vounetse, Sonchaux, Stockhorn, Amisbuehl)

**Betroffene Spots (19.05.)** — Tag mit 84 XContest-Top-Eintraegen, Tagessieger 170 km:
- Monte Tamaro (4 Launches, 46 km — Wind 82° nur 8° vor O-SO bei Gust 18 km/h)
- Trans (4 Launches, 38 km — Block-Filter + Sektor)
- Amisbühl oben+unten (5 Launches, 30 km — Wind 198° 18° vor SSO-SO + Block-Filter)
- Brunnihütte (2 Launches, 29 km — Block-Filter + Sektor)
- Altwisstock (1 Flug, 25 km — Wind 268° 21° ausserhalb SSW-WSW)
- Büelen (4 Launches, 19 km — Wind 56° EXAKT in NO-SO! Filter-Bug-Verdacht)
- Rotenfluespitz (2 Launches, 17 km — Wind 266° EXAKT in WNW-WSW, nur Block-Filter)
- Niederhorn (1 Flug, 6 km — Block-Filter, borderline)
- Hasenmatt (1 Flug, 3 km Abend — borderline, Gust 36 + precip 9.7mm)
- Luegibrüggli (1 Flug, 3 km — Wind 194° 8° vor SSW-SSO)
- Haldigrat 1+2 (1 Flug, 12 km — Wording-Bug I-011)
- Bellalui (Crans-Mon-Mapping — Sektor "NO-W" sollte 253° W einschliessen)

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

## I-002 — Spot-XC-Rating systematisch zu konservativ an Top-XC-Tagen

**Erstmals**: 2026-05-17
**Tage beobachtet**: 3 (17.05, 19.05, 21.05)
**Status**: offen — Architektur-Frage, kein klarer Pipeline-Bug

**Frühere (falsche) Annahme**: "Region-Kontext fehlt fuer Top-Spots, dadurch Rating auf
Default 1". Beim Code-Check und Daten-Vergleich (19.05/21.05) hat sich gezeigt: diese
Annahme war zu eng. Region-Lookup (Polygon via `find_region_for_point`) funktioniert
sauber, Region-Analyse ist im Snapshot vorhanden, und das tatsaechliche xc-Rating ist
nicht "Default 1" sondern 2-3 (passend zur Skill-Regel bei Spot-exp 2-4).

### Was tatsaechlich passiert

**Architektur (laut `skills/shared/04_flyability/05_streckenflug.md`)**:
- Spot-XC-Rating ist AND-verknuepft mit Region: `Rating 4 = Spot ∈ {4,5} UND Region ∈ {4,5}`,
  `Rating 5 = Spot=5 UND Region=5`
- Hartcap in `engine/analyzers.py:1968`: `Spot exp <= 2 → streckenflug max 2`
- Region kann xc nur **kappen** (region_wind_aloft, weak_regional_thermals), nicht **boosten**

**Diskrepanz Region-Aggregat vs. Spot-Aggregat (19.05 Tessin Zentral)**:

| Ebene | climb-peak | XC-Tag | Bewertung |
|---|---|---|---|
| Region (CVT+Edge Aggregat) | **2.7 m/s**, XC-Potenzial hoch | exp=**5** |
| Spot Cimetta (1616m) | 2.3 m/s, top 2496m (=AGL 880m) | exp=**3**, xc=**2** lim=ceiling_low |
| Spot Mornera (1382m) | 2.4 m/s, top 2628m (=AGL 1246m) | exp=**4**, xc=**3** lim=region_context_missing* |

(*lim=region_context_missing ist hier LLM-Halluzination — Region-Block war im Prompt da,
LLM hat den Limiter inkonsistent gewaehlt; betrifft das **Label**, nicht den **Wert** xc=3.)

→ Die Region-Bewertung exp=5 ist **inhaltlich richtig** (peak 2.7, ph 10, Region-Tags
"XC hoch", real 162km Cimetta + 104km Mornera geflogen). Aber das Spot-Meteogramm
sieht systematisch konservativer aus als die Region-Aggregate, weil:
- Spot-Punkt nutzt **einen** Koordinatensatz → individuelle, lokale Wolkenbasis/Thermik
- Region nutzt **7 Referenzpunkte** (4 Edge + 3 CVT-Innen) → glattere XC-Realitaet
- Pilot startet am Spot, fliegt aber in den Region-Raum → reale XC nutzt
  Region-Aggregate, nicht Spot-Punkt

Bei Spot-exp ≤ 3 kappt die AND-Regel + der Hartcap dann xc auf 2-3, obwohl die Region
exp=5 hergibt → die Region kann den Spot nicht heben.

### Beispiele (korrigierte Lesart)

**17.05.** Fiescheralp (175km Tagessieger, xc=1): Damals noch
`streckenflug_limiting_factor=region_context_missing` und Default 1 — das war damals
echter Pipeline-Lookup-Fehler ODER LLM-Halluzination, müsste mit dem Snapshot
verifiziert werden. Heutiger Stand: Pipeline funktioniert, also wahrscheinlich
LLM-Inkonsistenz bei der Limiter-Wahl.

**19.05.**
- Fanas 1 (Tagessieger 170km): Spot exp=2 → Hartcap kappt xc auf 2.
  Warum exp=2? Climb 2.4 + ph 10 sind eigentlich solide, aber Gust 35 + Wind 229° am
  Sektor-Rand SSW-WSW koennten Safety-Score reduziert haben → Spot-Rating konservativ.
  Region Praettigau exp=4 hilft nicht wegen Hartcap.
- Mornera (104km): Spot exp=4, Region exp=5 → laut Regel xc=4 moeglich, bekam aber
  xc=3 mit (vermutlich falschem) Label `region_context_missing`. Das ist die einzige
  Stelle, wo das Label-Verhalten echtes Fehlerbild produziert.
- Cimetta (162km): Spot exp=3 + AGL 880m → ceiling_low + AND-Regel mit Region 5
  ergibt xc=2-3. Inhaltlich konsistent zur Skill-Regel, aber im Praxistest underrated.

**21.05.** Ebenalp 1 (168km Tagessieger): Spot exp=4, Region Alpstein exp=4 → laut Regel
xc=3-4 moeglich; bekam xc=3 mit lim=ceiling_low. Konsistent.

### Was hier eigentlich das Problem ist

**Nicht** "Region fehlt" (gibt sie meist nicht), **nicht** "Pipeline kaputt" (ist sie nicht).
**Sondern**: das Konzept "Spot-XC-Rating = AND(Spot, Region)" misst implizit "wie gut ist
der Spot **als XC-Start** lokal" — nicht "wie weit kommt ein Pilot ab hier". Real-Fluege
nutzen die Region-Bedingungen, daher driftet xc-Rating vs. Real-Performance vor allem an
Tagen, wo der Spot lokal "moderat" aussieht aber die Region traegt.

### Mögliche Richtungen (kein direkter Fix-Vorschlag, eher Entwurf)

1. **Status quo akzeptieren** — XC-Rating misst lokale Spot-XC-Qualitaet, nicht
   Pilotenperformance. Region-Rating separat kommunizieren.
2. **Regel umdrehen** — wenn Region exp=5 + ruhig + Spot-safety=safe, darf Spot-xc dem
   Region-Rating folgen, auch wenn Spot-exp 1 Stufe niedriger ist.
3. **Spot-Aggregate erweitern** — `max_thermal_height` ueber Spot+Region-Aggregat statt
   nur Spot-Punkt; reflektiert XC-Reichweite besser.
4. **Label-Sauberkeit** — Skill-Regel praezisieren, dass `region_context_missing` nur
   bei tatsaechlich "nicht verfuegbar"-Text gesetzt wird (kein Catch-all-Fallback).

**Naechste Schritte**:
- Mit User klaeren: welche Richtung passt zum Produktziel?
- Bis dahin: I-002 als **Konzept-Diskussion** behandeln, nicht als "Bug zum Fixen".

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
**Tage beobachtet (Pre-Migration)**: 5 (17.05, 18.05, 19.05, 20.05, 21.05)
**Tage beobachtet (Post-Migration ≥22.05)**: 1 (24.05). Wiederkehrer:
- **Saas-Fee** 2 Tage in Folge (19.05 142km, 21.05 132km) — Pre-Migration
- **Riederalp** Pre-Migration 2 Tage (19.05, 21.05) — **Post-Migration jetzt in PGE als `Riederalp- Greicheralp` aufgeloest!** safe/5
- **Grindelwald** Pre-Migration 2 Tage — **Post-Migration jetzt als `Grindelwald - First` aufgeloest!** 24.05 11 Launches CONFIRM
- **Galgenen** Pre-Migration 2 Tage — **Post-Migration als `Gschwand - Galgenen` aufgeloest!** 24.05 4 Launches CONFIRM
- **Mentschelen** Pre-Migration als coverage_gap — **Post-Migration als `Möntschelealp` aufgeloest!** 24.05 17 Launches CONFIRM (Mass-Mapping-Fix)
- **Tussweid** 3 Tage in Folge (18.05/19.05/20.05) — Pre-Migration; Status post-Migration unklar
- **Burgfeldstand** 2 Tage (20.05, 21.05) — Post-Migration in PGE als `Burgfeldstand` aufgeloest, 24.05 1× 24km CONFIRM
- **Gornergrat** 2 Tage (18.05, 21.05) — Pre-Migration
- **Moosfluh** NEU (24.05) — 2× 253km, **HOECHSTE PRIO** (HG-Top-Tier, direkt neben Riederalp, fehlt in PGE)
- **Walalp** NEU (24.05) — 9 Launches 56km Mike Wicki
**Status**: offen — **PGE-Migration hat etliche alte gaps aufgeloest (Riederalp, Grindelwald, Galgenen, Mentschelen, Burgfeldstand)**, dafuer neue gaps freigelegt (Moosfluh ist die haerteste).

**Fehlende Spots 24.05.** — 18 Eintraege (davon 9 ≥30 km bedeutsam):
- **Moosfluh** (2× **253.35 km** Pattou) — HOECHSTE PRIO Goms
- **Walalp** (**9 Launches** 56 km) — Stoos/Morschach?
- **Torrentalp** (1× 69 km) — Wallis Leukerbad NEU
- **Visperterminen** (1× 45 km) — Wallis Visp Heido
- **Laubbärgli** (1× 43 km) — BO Maennlichen/Wengen NEU
- **Sembrancher** (1× 41 km) — Unterwallis Catogne NEU
- **Lauihöchi** (1× 38 km) — ZS Voralpen?
- **National Park** (1× 30 km) — Engadin S-charl/Lischana NEU
- **Cabane des Audannes** (1× 28 km) — Wallis Conthey NEU
- Kleinere: **Rotmoos 3× 12 km** (NEU, wiederkehrendes Pattern beobachten), Leissigbächli, Planachaux, Leiggern, Sarn Alp, Gantrisch, Heruhubil, Schönboden, UNKNOWN 2×

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

**Fehlende Spots 21.05.** — 29 Coverage-Eintraege an einem 240-Launches-Tag:
- **Saas-Fee** (132km, 2. Tag) — HOECHSTE Prio
- **Niederwil…** (3 Launches, 111km Von niederhaeusern) — NEW HIGH-PRIO; XContest-Truncate
- **Riederalp** (4 Launches, 110km Strahm, 2. Tag) — HOCHPRIO
- **Leysin** (80km CHUN) — NEW HIGH-PRIO Waadtland
- **Grindelwald** (**9 Launches**, 59km Jaggy) — wiederkehrend, jetzt klare Coverage-Luecke Berner Oberland
- **Galgenen** (8 Launches, 35km) — wiederkehrend Mittelland Ost
- **Boettstein** (45km Huppert) — Mittelland AG, neu
- **Euthal** (38km), **Muerren** (32km), **Tschenten** (17km), **Sarner Alp** (20km),
  **Torgon** (22km), **Burgfeldstand** (17km, 2. Tag), **Gornergrat** (10km, 2. Tag),
  **Walalp** (19km), **Schoenboden** (17km), **Grandvillard** (26km), **Chrienseregg** (11km),
  **Les prelayes** (15km), **Le Cernil** (13km), **Bolberg** (5km), **Vacheresse** (6km),
  **Cret du Midi** (9km), **Vogelberg** (5km), **Ausserberg** (6km), **Winteregg** (7km),
  **Ruetiberg** (3km), **Chörnlisegg** (16km), **Wpt001** (20km Hans Huggler — unknown name).

**Fehlende Spots 19.05.** — 12 neue Eintraege bei sehr aktivem Tag:
- **Saas-Fee** (1 Flug, 141.84 km, O. Prochazka CZ — **HOCHPRIO**, Top-3 Tagesleistung)
- **Madone** (1 Flug, 110.08 km, E. Sartoris — **HOCHPRIO**, Tessin Nord)
- **Loeita** (1 Flug, 73.12 km, P. Rothenbuehler — **HOCHPRIO**, Mittelland?)
- **Ämsigen** (1 Flug, 64.07 km, L. Zumbuehl — HOCHPRIO, Engelberg)
- **Tussweid (3. Tag in Folge!)** (1 Flug, **57.65 km** Roeleveld — **HOECHSTE PRIO**, echter
  Strecken-Flug nach zwei Tagen Hops)
- **Riederalp** (1 Flug, 36 km, S. Bucher — Aletsch/Wallis, MID)
- **tuffarolas** (1 Flug, 27 km, C. Roner — Surselva/Tujetsch, MID)
- **Gulmen** (3 Launches, 19 km Top, A. Schlegel — Toggenburg, MID)
- L'etoile (18 km, Westschweiz/Vallee de Joux?, MID)
- Lüsis (16 km, Glarnerland, MID)
- Schafberg (5 km Hop, LOW)
- H&F Fäsil (7 km Hop, LOW)

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
**Tage beobachtet (Pre-Migration)**: 4 (17.05, 19.05, 20.05, 21.05)
**Tage beobachtet (Post-Migration ≥22.05)**: 1 (24.05) — auch nach Migration weiterhin Top-FP-Treiber
**Status**: offen — am 21.05 (NE-Wind-Tag) **fast jedes False-Positive auf diesem Issue**; am 24.05 ebenfalls dominant

**Beobachtungen 24.05.** (Sektor-Drift):
- **Haldigrat (SW) bei Wind 62° NE — 9 Launches/61 km BOHREN** — HG-Spot mit Single-Sided-Sektor; real O-Hang nutzbar
- **Niederhorn (SO-S) bei Wind 71° NE — 7 Launches/43 km HINNI** — Klassiker, NE-Wind-Tage immer falsch
- **Verbier (alle DB-Varianten S-SW-W bzw SO-S-SW) bei Wind 307° NW — 6 Launches/153 km MARET** — 3. Variante fehlt komplett
- **Niesen (SW) bei Wind 62° NE — 1×/130 km JOHNSTON** — Niesen hat real auch Ost/NE-Variante
- **Jaman (SW-W-NW) bei Wind 29° NE — 2×/24 km** — Repeat 21.05
- **Hinterrugg (SO-S-SW/NW-N disjoint) bei Wind 52° NE — 2×/26 km** — zwischen disjoint Sektoren
- **Stockhorn/Brienzer Rothorn/Mostelegg/Stockberg** je 1× bei NE-Wind ausserhalb der jeweiligen S/SW-Sektoren

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
| **Monte Tamaro (19.05)** | O-SO (90-135°) | **82° ONO bei 18 km/h Gust** | 4 Launches, 46 km — Borderline + I-008 |
| **Amisbühl o/u (19.05)** | SSO-SO (157-180°) | **198° SSW** | 5 Launches, 30 km |
| **Brunnihütte (19.05)** | W-SW (202-270°) | **320° NW** | 2 Launches, 29 km |
| **Altwisstock (19.05)** | SSW-WSW (202-247°) | **268° W** | 1 Flug, 25 km |
| **Büelen (19.05)** | NO-SO (45-135°) | **56° NE — EXAKT IM SEKTOR** | 4 Launches, 19 km — Filter-Bug-Verdacht |
| **Rotenfluespitz (19.05)** | WNW-WSW (247-292°) | **266° W — EXAKT IM SEKTOR** | 2 Launches, 17 km — nur Block-Filter |
| **Luegibrüggli (19.05)** | SSW-SSO (180-202°) | **194° SSW** | 1 Flug, 3 km |
| **Bellalui (19.05)** | NO-W (breit, 45-270°) | **253° W — sollte INNERHALB sein** | Sektor-Parser-Bug-Verdacht |
| **Obere Wengi (21.05)** | SSW-SSO (158-202°) | **107° E** | **11 Launches**, 97 km Haenni |
| **Scheidegg (21.05)** | NNO-NO (22-45°) | **64° NE — knapp ausserhalb** | 4 Launches, 113 km Erne |
| **Niesen (21.05)** | SSW-SSO (158-202°) | **72° E bei Gust 17 km/h** | 5 Launches, 78 km — I-008 ueberlagert |
| **St. Anton (21.05)** | SO-S (135-180°) | **36° NE** | 1× 85 km |
| **Brunnihuette (21.05)** | W-SW (202-270°) | **350° N** | **12 Launches**, 59 km — Variante fehlt |
| **Rotenfluespitz (21.05)** | WNW-WSW (247-292°) | **35° NE** | 7 Launches, 46 km Walder |
| **Le Suchet (21.05)** | NNO-N (22-0°) | **70° E** | 4 Launches, 38 km |
| **Niederhorn (21.05)** | SSW-SSO (158-202°) | **57° NE** | 2 Launches, 49 km Hinni |
| **Jaman (21.05)** | W-NW (270-337°) | **24° NNE** | 2 Launches, 29 km |
| **Hohwacht (21.05)** | NNW-NNO (337-22°) | **71° E** | 5 Launches, 12 km Top |
| **Bellalui (21.05)** | NO-W (45-270° via N) | **1° N** | **conditional, status korrekt** — Parser greift heute |

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
**Tage beobachtet (Pre-Migration)**: 4 (17.05, 19.05, 20.05, 21.05)
**Tage beobachtet (Post-Migration ≥22.05)**: 1 (24.05)
**Status**: offen — am 21.05 besonders auffaellig: **Kronberg 1 hat Wind 42°NE EXAKT
im NW-NO Sektor, scheitert NUR am Block-Filter ("Nur 2h sauber"). 5 Launches/43km zeigen
Spot war fliegbar.** Ebenso Burst, Fiescheralp, Niederbauen, Kerenzerberg, Seebodenalp,
Fronalpstock, Obere Wengi am 21.05 nur durch Block-Filter blockiert.

**Beobachtungen 24.05.** (Wind IM Sektor, nur Block-Filter blockt):
- **Cimetta (S-SW) Wind 168° S EXAKT** — 4 Launches/56 km BOSCACCI; no_go "Nur 1h sauber, kein zsh. Block"
- **Montlinger Schwamm (N-NO) Wind 25° NE EXAKT** — 2 Launches/43 km MARTY; gleicher no_go-Text
- **Crans-Mon Cry d'Er (SO) Wind 14° N knapp ausserhalb**, aber no_go ist Block-Filter ("Nur 1h sauber"), nicht Sektor → ueberlagert mit I-006

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
**Tage beobachtet (Pre-Migration)**: 4 (17.05, 19.05, 20.05, 21.05)
**Tage beobachtet (Post-Migration ≥22.05)**: 1 (24.05)
**Status**: offen — 21.05 Niesen: dir 72°E bei **Gust 17 km/h** (sehr schwach!) trotzdem
not_safe; 5 Launches inkl. 78km Strecke. Bei <20 km/h Gust ist Sektor fliegerisch fast
egal. Pilatus Kulm 22 km/h Gust analog.

**Beobachtungen 24.05.**:
- **Niesen** wiederholt: Wind 62° NE bei Gust **30 km/h**, Sektor SW → 130 km JOHNSTON (Schwelle hier hoeher als 21.05, aber Sektor-Misfit dominierte)
- **Grand Chamossaire** Wind 302° NW bei Gust 17 km/h, Sektor W am Rand — 101 km RUDAZ; Gust 17 ist genau die Schwelle, ab der Sektor irrelevant wird

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
**Tage beobachtet (Pre-Migration)**: 4 (17.05, 19.05, 20.05, 21.05)
**Tage beobachtet (Post-Migration ≥22.05)**: 1 (24.05) — **PGE-Migration loest etliche, schafft aber neue**
**Status**: offen — am 21.05 grosser Multi-Variante-Erfolg (Ebenalp 1 von 3, Crans-Mon
3 Varianten korrekt aufgeloest, Verbier → Ruinettes, Tritt → Ufem Tritt analog vorhin).
**ABER**: Brunnihütte (12 Launches an `not_safe`-W-SW-Spot bei N-Wind) signalisiert, dass
der Brunni-Spot real einen N/NE-Hang als Alternative haben muss, der in DB fehlt.
Bellalui-Sektor-Parser hat heute funktioniert (1°N → in NO-W).

**Mapping-Drift Post-PGE (24.05)**:
- **Aufgeloest** (waren coverage_gap Pre-Migration, jetzt PGE-gemappt): Riederalp → `Riederalp- Greicheralp`, Grindelwald → `Grindelwald - First`, Mentschelen → `Möntschelealp` (**Mass-Confirm 17×**), Galgenen → `Gschwand - Galgenen`, Brunni → `Engelberg - Brunni - Schonegg`, Burgfeldstand → `Burgfeldstand`
- **Naming-Drift** (XContest-Name ≠ PGE-Name): Amisbühl → `Amisbuehl` (ohne Umlaut), Prodchamm → `Prodkamm`, Les Pètis → `Les Pétis`, Grand Chamossaire → `Le Chamossaire-1980`, Crans-Montana → 3 Varianten (Cry d Er, Bella Lui, Aminona)
- **Verbier-Variante-Loch (NEU)**: beide DB-Varianten (Ruinettes S-SW-W + Croix-de-Coeur SO-S-SW) decken NW-Wind nicht ab — bei 6 Piloten/153 km MARET fehlt 3. Variante
- **Brunni-Schonegg-Frage**: Sektor SO-S-SW-W bei Wind 354° N — `conditional` Status passt zur Realitaet (10 Launches/56 km), aber Sektor "logisch" ausserhalb. Hypothese: PGE-Schonegg-Variante hat real N-Anbindung am Grat
- **Sub-Issue Stockberg ≠ Chörnlisegg**: mein Fuzzy-Match war forsch — Chörnlisegg liegt Hundwil/Appenzell, Stockberg ist Toggenburg. 1× 20 km Eintrag im Borderline-Bereich

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
**Tage beobachtet**: 2 (18.05, 20.05) — am 19.05 nicht ausgeloest (Forecast-Regen
mit 1-10mm geringer als am 18./20.05)
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

## I-011 — Wording-/Logic-Bug "Nur Xh sauber, kein zusammenhaengender Block >= 3h"

**Erstmals**: 2026-05-19
**Tage beobachtet**: 2 (19.05 Haldigrat, 21.05 Niederbauen)
**Status**: offen — Wording-Inkonsistenz, evtl. nur Text-Bug. Pattern konsistent: 3 saubere
Stunden verteilt, kein zusammenhaengender 3h-Block. Text korrigieren auf "3 Einzelstunden
verteilt, kein zusammenhaengender 3h-Block" oder gleichwertig.

**Beobachtung**: Auf Haldigrat 1 + 2 (19.05) lautet das no_go:
> "Start-Fenster: Nur **3h** sauber, kein zusammenhaengender **Block >= 3h**"

Das widerspricht sich logisch: wenn 3 saubere Stunden existieren und der gesuchte Block
3h lang sein soll, ist die Anforderung exakt erfuellt — ausser die 3h sind nicht
zusammenhaengend. In dem Fall sollte der Text klar sagen "3 Einzelstunden verteilt,
kein 3h-Block" (oder die Anforderung in der CLEAN_WINDOW_MIN_HOURS-Berechnung anpassen).

**Vermutete Ursachen**:
- Format-String in `_prefilter_not_safe` baut Text aus `wind_ok_count` (3) und
  `CLEAN_WINDOW_MIN_HOURS`-Logik zusammen — die Variable wird im Text irrefuehrend ohne
  "kontinuierlich"/"verteilt"-Hinweis verwendet
- Oder der Block-Check ist tatsaechlich strenger als 3h (z.B. 4h Mindestblock) und der
  Text holt sich die falsche Konstante

**Naechste Schritte**:
- Code-Pfad `_prefilter_not_safe` finden: wo wird der "Nur Xh sauber" String gebaut?
- Pruefen, ob die Schwelle und der angezeigte Wert (`>= 3h`) konsistent sind
- Falls Block-Schwelle = 3h und 3 saubere Stunden existieren: warum greift es trotzdem?
  → vermutlich Lueckenbedingung (z.B. 1h Lücke darin)
- Text anpassen: "Nur Xh sauber, davon keine 3h-Block-Kontinuitaet" oder analog

---

## I-012 — CAPE-Filter zu konservativ an Top-Thermik-Tagen

**Erstmals**: 2026-05-24
**Tage beobachtet**: 1 (24.05)
**Status**: offen — Erstbefund, weitere Tage abwarten bevor Hypothese

**Beobachtung 24.05.**:
- **Grand Chamossaire** (`Le Chamossaire-1980`, Waadtl. Alpen): no_go = "Ueberentwicklungsgefahr: CAPE >1500 J/kg oder CAPE+Regen aktiv" → status=not_safe
- Real: **3 Piloten, 101 km RUDAZ + 41 km Boran + 38 km Jeremie DR**
- Wind 302° NW knapp ausserhalb S-SW-W Sektor (am Rand), aber das war NICHT der Block-Grund — der CAPE-Filter dominierte
- Tag war ein Wallis-Festival ohne Gewitter-Vorfaelle (CAPE max im Snapshot bei vielen Wallis-Spots 100-300 J/kg, sehr ruhig)

**Vermutete Ursache**:
- CAPE-Threshold im Pre-Filter scheint absolut auf 1500 J/kg gesetzt zu sein, ohne Kontext (Tageszeit, LI, Wind-Shear)
- An Top-Thermik-Tagen mit hoher CAPE aber stabilem LI / fehlendem Trigger → keine Ueberentwicklung
- Filter feuert wohl unabhaengig von der Wahrscheinlichkeit der Aktivierung

**Naechste Schritte**:
- 1-2 weitere Tage mit Grand-Chamossaire-Daten abwarten, ob Pattern reproduzierbar
- CAPE-Cutoff im Code finden (vermutlich `engine/decision_engine.py` oder `_prefilter_not_safe`)
- Konditional gegen LI/Shear/Tagesschnitt CIN pruefen statt absolutes CAPE

---

## Auswertungs-Roadmap

- Nach jeder neuen Analyse: hier Tage-Zähler hochschreiben
- Bei ≥3 Tagen für einen Issue: Cause-Hypothese im Code prüfen
- Bei ≥5 Tagen: Fix planen
- Issues, die nur 1× auftraten, nach 30 Tagen ggf. archivieren
