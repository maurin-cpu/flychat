# Flight Day Evaluation — Pilotensprache und mentales Modell

**Status:** Recherche-Synthese aus Pilotenforen, Magazinen, Schulungstexten
**Zweck:** Grundlage fuer LLM-Skill-Templates zur Rating-Vergabe (`skills/shared/04_flyability/`)
**Scope:** NUR Flyability / Streckenpotenzial / Erlebnis — NICHT Sicherheit.

---

## 1. Kernerkenntnis

Erfahrene Gleitschirmpiloten bewerten einen Flugtag **nicht ueber numerische
Schwellen**, sondern ueber ein **Mental-Modell aus drei Achsen**:

1. **Was macht die Luft?** (traegt / blubbert / Nullschieber / sprudelt / steht zerrissen)
2. **Was machen die Wolken?** (bauen auf / passen / fallen zusammen / Wolkenstrasse / blauer Tag)
3. **Was geht?** (Abgleiter / Hausrunde / Hausstrecke / Klassiker / Hammer / Sauwetter)

Die emotionale Skala ist **binaer + Gradient**: schnelles "geil!" oder
"Sauwetter", dazwischen liegt eine fein abgestufte Mittelregion, die fast nur
ueber Phrasen funktioniert ("anstaendig", "ehrlich", "kann man fliegen",
"hat mehr versprochen als gehalten").

---

## 2. Die 6-stufige Pilotensprache-Skala

Aus realen Pilotenkommentaren rekonstruiert. Jede Stufe hat ein Wort-Set, eine
emotionale Tonalitaet, und ein Aktions-Aequivalent.

### Rating 1 — Abgleiter
- **O-Ton:** "Schoener Abgleiter halt." / "Sled ride." / "Sonnenuntergangsflug."
- **Luft:** ruhig, kein Steigen, glatt
- **Aktion:** topouten unmoeglich, Flugzeit = Hoehe / Sinken
- **Charakter:** Genussflug bei ruhiger Luft, Frust bei Wind

### Rating 2 — Kurzer Thermikflug / Bummel
- **O-Ton:** "Hat geblubbert aber nicht getragen." / "Kuhfurz." / "Nullschieber."
  / "Es hat nichts gerissen." / "Hat mehr versprochen."
- **Luft:** kurze Blasen, keine durchgehenden Baerte, schwach
- **Aktion:** 30-60min mal was, dann zufrieden runter
- **Charakter:** Soaring-Tag, sporadisches Blubbern, kein voller Tag

### Rating 3 — Solider Thermikflug / Hausrunde
- **O-Ton:** "Anstaendiger Tag." / "Hat schoen getragen." / "Solide Hausrunde."
  / "Schoener Flugtag, organisiert."
- **Luft:** ehrliches Tragen, mehrere Stunden produktiv, Baerte nachgespeist
- **Aktion:** Hausrunde faellt, 2-3 h Airtime, vielleicht 20 km lokal
- **Charakter:** *Der typische Schweizer Flugtag.* Cumulus zyklisch aber Basis
  nicht euphorisch, keine XC-Ambition.

### Rating 4 — Starker Thermikflug / kleiner XC-Tag
- **O-Ton:** "Heute ging was — 50er war drin." / "Gut getragen." / "Schoene
  Werte." / "Hausstrecke faellt locker." / "Mit Laecheln runter."
- **Luft:** sauber getragen, organisiert, 4-5 h konsistent
- **Aktion:** Lokal-XC bis ~50 km, Hausstrecke geht locker
- **Charakter:** XC-Light, verlaesslich, Spotwahl noch wichtig

### Rating 5 — XC-Tag / Klassiker
- **O-Ton:** "Klassiker ging." / "Linie war da." / "100er ging." / "Bedingungen
  passten ueberall." / "Basis kam schoen auf." / "Heute war Strecke moeglich."
- **Luft:** 5-6 h produktiv, hohe Steigwerte, organisiert
- **Aktion:** 50-150 km Streckenflug, Konvergenz oder Wolkenstrasse sichtbar
- **Charakter:** Der **klassische Streckentag** einer Region (z.B. Fiesch-Chur).
  Wind, Lage und Saison passen.

### Rating 6 — Hammertag / Epic / Lager Day
- **O-Ton:** "Absoluter Hammer." / "Sowas erlebt man selten." / "Alle waren
  oben." / "Auf Kante genaeht." / "Drueckt durch alle Inversionen." / "Geil!"
- **Luft:** explosive Steigwerte, oft praefrontal/konvergent/postfrontal-magic
- **Aktion:** 200+ km moeglich, mehrere 300er regional, Basis ungewoehnlich hoch
- **Charakter:** Tag des Jahres. CH-Saison: 5-15× pro Saison.

---

## 3. Drei Hammer-Marker

Aus Pilotenberichten zum 13.8.2003, Mai 2025 Fiesch, Mont-Blanc-Days etc.
**Ein Klassiker (Rating 6) hat alle drei Marker:**

1. **"Es ging ueberall"** — flaechige Produktivitaet ueber die Region, nicht
   nur ein isolierter Hotspot. "30 Fluege ueber 200 km vom Wallberg bis Fiesch."
2. **"Basis weit ueber Standard"** — fuer die Region. Mittelland 2800m+,
   Wallis 4500m+. Siehe `cloudbase_terrain_tiers.md`.
3. **"Auf Kante genaeht"** — Bedingungen am Limit, aber haltbar.
   Praefrontal-Boomers, konvergente Linien, postfrontale Klarheit.

Fehlt einer der drei Marker → Rating maximal 5.

---

## 4. Tagestypen-Taxonomie

| Typ | Charakter | Rating |
|---|---|---|
| **Abgleiter / Sled ride** | Glatter Sinkflug, kein Steigen | 1 |
| **Hangsoaring-Tag** | Wind passt zum Hang, keine Thermik | 1 (Thermik-Skala) |
| **Uebungstag / Magic Air** | Ruhige Thermik, abends, anfaengerfreundlich | 2-3 |
| **Hausrundentag / Bummeltag** | 1-3 h lokal, kein XC | 2-3 |
| **Solider Thermiktag** | 3-5 h, 30-80 km lokal | 3-4 |
| **XC-Tag / Streckentag** | 5-6 h, 100-150 km, Konvergenz/Wolkenstrasse | 5 |
| **Klassiker** | Region-typische Standardstrecke (z.B. 125km Fiesch-Chur) | 5-6 |
| **Hammertag / Epic** | 200+ km, ueberall, auf Kante | 6 |
| **Konvergenztag** | Wolkenstrassen, "thermals more concentrated" | 5-6 |
| **Pre-frontal "full contact"** | Stark, scharf, turbulent | 5-6 oder 1 (zu rough) |
| **Sauwetter** | Nicht fliegbar (Regen/OD/Sturm) | 1 |

---

## 5. Wie Piloten mental abwaegen — die Faktoren

### Erstrangig (in jedem Pilotenkommentar)

1. **Wolkenbasis-Hoehe ueber Krete** — "Basis muss ueber Krete kommen."
2. **Steigwerte (integriert)** — Pilotenskala aus Forenberichten:
   - 0,8 m/s = schwach (Kuhfurz)
   - 1,5 m/s = solide (anstaendig)
   - 2-3 m/s = ausgezeichnet (geil)
   - 3-4 m/s+ = Hammer (boomt)
3. **Tageslaenge / Thermikfenster** — Wann startet's, wann macht's zu?
4. **Wolkenbild** — Cumulus zyklisch und regelmaessig spacing vs. Fetzen.

### Zweitrangig

5. **Stabilitaet / Lapse Rate**
6. **Streckenpotenzial / Grosswetterlage**
7. **Spotwahl** (Exposition zur Sonne, Talwind-Schutz)

### Drittrangig (Verfeinerung)

8. **Luftfeuchtigkeit** — "humid = weich, sanft" / "dry = scharf, punchy"
9. **Tageszeit-Profil** — frueh sanft, mittags ruppig, abends weich
10. **Tagesverfall** — Cirren? Cap? OD? Halten die Bedingungen?

---

## 6. Mindest-Voraussetzungen in Pilotensprache (keine Zahlen)

**Fuer einen Thermiktag (Rating ≥ 3):**
- "Es muss tragen, nicht nur kurz blubbern." — kontinuierliche Baerte, keine Einzelblasen
- "Cumulus zyklisch und regelmaessig" — keine Fetzen, klare Konturen
- "Talwind spaet und sanft" — nicht zu frueh den Hang ueberlaufen
- "Sonne kommt auf den Hang" — Exposition passt zum Tagesgang

**Fuer einen XC-Tag (Rating ≥ 5):**
- "Basis muss ueber Krete kommen"
- "Wolkenstrasse zu sehen" oder "Konvergenz auf der Karte"
- "Genug Zeitfenster" — frueher Einstieg, spaeter Cap
- "Kein zu frueher Tagesverfall" — keine Cirren-Daempfung, kein OD

**Fuer einen Hammertag (Rating 6):**
- Alle drei Hammer-Marker (siehe Sektion 3)
- "Drueckt durch Inversionen" — Boomer-faehig
- "Postfrontale oder konvergente Grosswetterlage"

---

## 7. Region-Lupe

**Die gleiche Zahl bedeutet je nach Terrain etwas anderes.** Siehe
`cloudbase_terrain_tiers.md` fuer Basis-MSL pro Tier mit Quellen.

**Tagestyp-Charakteristika pro Tier:**

| Tier | Tagesbeginn typisch | Dominante Faktoren |
|---|---|---|
| **Mittelland** | 10-11 Uhr | Triggerpunkte, Bart-Drift, Wind als Verbuendeter |
| **Jura** | 11-12 Uhr | Frontale Konvergenzen, Mittellandquerung als Standardroute |
| **Voralpen** | 11-13 Uhr | Talwinde wichtig, Mittel-Basis, Hausrunden als Standardtag |
| **Alpen** | 12-13 Uhr | Hotspots stationaer, Suedlage = Klassiker, Wind aus Norden = nicht fliegbar |
| **Hochalpin (Wallis/Engadin)** | 12-14 Uhr | Spaet aber hoch, Gletscherabwinde gefaehrlich, Lange Talsysteme |

**Wichtig:** Spaeter Tagesbeginn (12-13 Uhr) ist im Hochalpinen **Normalitaet,
kein Mangel**. Im Mittelland waere er ein Spaetstart-Signal.

---

## 8. Pilot-Vokabular-Bank (LLM-Anker)

### Positive Skala
"geil", "Hammer", "Klassiker ging", "Linie war da", "alles drueckt durch",
"Basis kam schoen auf", "verlaesslich", "organisiert", "hat sauber getragen",
"schoene Werte", "sprudelnd", "Magic Air", "weich und gleichmaessig",
"Konvergenz war zu sehen", "Wolkenstrasse", "Lager day"

### Mittel-Skala
"anstaendig", "ehrlich", "solide", "schoene Hausrunde", "kann man fliegen",
"ging schon", "war ok", "hat mehr versprochen", "kurzer Thermikflug",
"Bummeltag"

### Negativ-Skala
"Kuhfurz", "Nullschieber", "blubbert nur", "hat nichts gerissen", "abgesoffen",
"zerrissen", "kein Tag", "Sauwetter", "soup-sky", "thick and slow", "stable",
"musst jeden Furz mitnehmen", "Parawaiting", "ueberentwickelt", "es zog zu"

### Spezielle Phaenomene
"Bart", "Schlauch", "Kamin", "Blase", "Boomer", "Wolkenstrasse", "Cumulusbasis",
"Krete", "Talwind", "Bisen", "Gletscherwind", "Konvergenz", "Inversion",
"Isothermie", "Cap", "blauer Tag", "OD" (Overdevelopment), "Blumenkohl-Wolken",
"Fetzen", "punchy", "ratty", "smooth"

---

## 9. Faustregeln (aus Pilotenforen)

- **"Bleibe da, wo es steigt!"** (Paraworld) — Kernprinzip Thermik
- **"Die Tasse muss auf den Unterteller passen"** (Burnair) — Thermikkreis an Bart-Groesse
- **"Nur was du siehst, existiert."** (WeGlide) — Pilot fliegt visuell
- **"Hammertage sind immer auf Kante genaeht"** — die besten Tage sind anspruchsvoll
- **"Erfolgreich heisst: jeden Schlauch des Tages bis ganz zur Basis ausdrehen"** (Paraworld)
- **"If the lift becomes widespread, easy, or more energetic than what you've
  been used to, slow down and look around"** (Flybubble) — Hammer-Erkennung

---

## 10. Lager-Sky vs. Soup-Sky (Cross Country Magazine)

Englischsprachiges Mental-Modell, sehr klar:

- **Lager-Sky** = Top-Tag: "High pressure has just moved in over a cold, dry
  and quite unstable air mass. The air is dry and light and thermals travel
  through it easily just like those bubbles of air in your glass of beer.
  Ripping climbs and can race on in search of the next strong thermal to
  cloudbase."

- **Soup-Sky** = schwacher Tag: "Warm moist stable air with a low lapse rate
  trapped under the inversion. The air is thick and soup like and thermals
  can't move through it well. You have to stick with anything just to stay
  in the air."

→ Direkter LLM-Anker: lese die RATING-INPUTS als "Lager-Sky"-Hinweise (klare
Konturen, organisierte Baerte, hohe Basis) oder "Soup-Sky"-Hinweise (zerrissen,
schwach, gedeckelt).

---

## 11. Anwendung im Gleitcast-Rating

Diese Erkenntnisse fliessen in folgende Skill-Templates ein:

- `skills/shared/04_flyability/04_flight_subratings_region.md` — Region-Rating
- `skills/shared/04_flyability/04_flight_subratings_spot.md` — Spot-Rating

Konkret:
- **Kategorien-Tabelle** mit O-Toenen pro Stufe
- **Region-Lupe-Block** mit Tier-spezifischen Erwartungen
- **Drei Hammer-Marker** als Rating-6-Voraussetzung
- **Schluesselfrage** "Was geht? Welche Aktion beschreibt den Tag?"
- **Pilot-Vokabular-Bank** als optionaler Match-Anker

Numerische Floors (Peak ≥ 2.0 + 4h → Rating 4, Peak ≥ 2.5 + 6h + Cu sauber
→ Rating 5) bleiben als Sicherheitsnetz gegen systematische Pessimismus-Drift
des LLM (siehe `data/labeled_examples.jsonl` — 10 von 30 Korrekturen
"zu pessimistisch", konzentriert im Hochalpinen).

---

## Quellen

Pilotenforen und Magazine:
- gleitschirmdrachenforum.de (DE/AT/CH Forum)
- paragliding-forum.com (international)
- knackwurstflieger.blogspot.com (Pilotensprache-Lexikon)
- xcmag.com (Cross Country Magazine — "Lager skies", "soup skies")
- flybubble.com (UK XC-Coaching)
- paranauten.com (CH Pilotenberichte)
- adnubes.info (CH Wetter/Saison-Analyse)
- burnair.ch (CH Wetter-Forecasts, Thermik-Tipps)
- paraworld.ch (CH Schulung)
- chilloutparagliding.com (BEO XC-Berichte)

Wissenschaftlich/Lehrtext:
- DHV-Info Magazine
- WeGlide-Magazine
- SkyNomad.com (Flatland vs Alpine)
- NOVA Team Blog ("Flatland Magic in Finland")

Vollstaendige URLs siehe Recherche-Transkript vom 2026-05-15.
