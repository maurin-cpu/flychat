# Synoptik-Beduerfnisse Schweizer Gleitschirmpiloten

**Status:** Recherche-Synthese (Web + Foren + CH-Wetterservices)
**Datum:** Mai 2026
**Zweck:** Grundlage fuer Architektur und Skill-Design des Wetterlage-Blocks
  (siehe `docs/WETTERLAGE.md`)
**Scope:** Welche grossraeumigen Wetter-Aspekte muss ein 5-Tages-Cast einem
  CH-Pilot liefern — und welche darf er nicht erfinden?

---

## 1. Kernerkenntnis

**Erfahrene CH-Piloten lesen Synoptik top-down**, NICHT von der Karte oder
500-hPa-Geopotential aus. Der typische Pilot-Workflow (z.B. Gleitschirmschule
Thun [swissgliders.ch](https://swissgliders.ch/de/wetter/)):

1. **Bodendruckkarte / Isobaren** — *"Wo ist das Tief, wo das Hoch?"*
2. **Stroemungsrichtung** ("Westwind", "Bise/NO", "Foehn") — qualitativ, nicht in Grad
3. **Frontenpassage** ja/nein und ungefaehres Timing
4. **Niederschlag-Verteilung und Charakter** (Stau Nord/Sued, Schauer vs. Dauerregen)
5. **Hoehenwind / Kammwind** (700/850 hPa) — nur bei Foehn-Verdacht oder starkem Wind
6. **Schneefallgrenze / Nullgrad** — relevant Maerz-Mai + Okt-Nov, Wallis/Hochalpen

500-hPa-Karten, Vorticity, Geopotential-Linien werden von der Mehrheit der
Piloten **nicht aktiv gelesen** — nur Forenfreaks und Hardcore-XC-Piloten.

Burnair selbst formuliert ihre Wochenprognose in **alltagstauglicher Sprache**,
trotz dass intern aus "ueber 40 Faktoren" aggregiert
([burnair.ch](https://www.burnair.ch/meteoservice/)).

---

## 2. CH-spezifische Stroemungslagen mit Pilotensprache

| Lage | Pilotensprache | Was sie fuer CH-Piloten bedeutet |
|---|---|---|
| **Westlage** | "Westwetter", "Atlantik bringt was", "wechselhaft" | Haeufigste CH-Lage. Wechsel Warm-/Kaltluft, Fronten, oft fliegbar in Wellen. |
| **Bise / Bisenlage** | "Bise zieht durch", "Bisenfeger", "klar und kalt" | Hoch NO-Europa + Tief Mittelmeer → NE-Wind. Mittelland windgepeitscht, Voralpen-Ostflanken (Gurnigel/Gantrisch) gehen, Berner Oberland-Nord teilweise OK ([biseflueger.ch](https://biseflueger.ch/gantrischregion.html)). |
| **Suedfoehn** | "Foehn liegt an", "es foehnt", "Foehnsturm im Anrollen" | Druck S > N. Nordalpen-Lee gesperrt, Tessin/Wallis-Sued Luv (oft Regen). Klassiker. |
| **Nordfoehn** | "Nordfoehn", "Maloja-Wind" (Engadin), "Tramontana" (Tessin) | Druck N > S. Tessin und Suedbuenden Lee, Nordalpen Luv mit Stau. Seltener, aber heftig. |
| **Nordwestlage** | "NW-Stroemung", "Rueckseiten-Wetter" | Postfrontal nach Westlage. Stau an Alpennordseite (Berner Oberland, Glarnerland) — Pilot weicht ins Wallis aus (Lee). ([meteoswiss.ch NW-Lage](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/northwesterly-situation.html)) |
| **Genua-Tief / Vb-Lage** | "Genua-Tief sitzt da", "es kommt von hinten (NE)" | Mittelmeertief, oft 2-3 Tage Dauerregen Alpennordseite + Tessin. Wochen-Killer. ([meteonews.ch Vb](https://meteonews.ch/de/News/N14151/Was-ist-ein-Vb-Tief), [NZZ](https://www.nzz.ch/articleD31CG-ld.357173)) |
| **Hochdruck / Omega / Bruecke** | "Hoch sitzt fest", "stabil", "Inversion drueckt" | Im Winter inversionsgeplagt (Hochnebel Mittelland), im Sommer Top-XC-Tage. |
| **Kaltlufttropfen / Cut-off** | "Kaltlufttropfen", "Cut-off" (selten genannt) | Unscharf vorhersagbar, oft konvektiv → Vorsicht Ueberentwicklung. |

**Pilotensprache-Faustregel:** Konkrete Phaenomene werden benannt
(Bise, Foehn, Westwind), abstrakte synoptische Begriffe (Trog, Ruecken,
Geopotential) werden gemieden ausser im Forum-Geek-Kontext.

---

## 3. Sprache und Tonalitaet

CH-Piloten kommunizieren (aus [Knackwurstflieger-Lexikon](http://knackwurstflieger.blogspot.com/2012/10/kleines-worterbuch.html),
adnubes, paranauten, paraworld):

- **Pragmatisch + landschaftsorientiert**: "Talwind", "Luv", "Lee",
  "Hangaufwind", "Sonnenseite" — NICHT "Konvergenzlinie"
- **Wetter-relativ in Stroemungsrichtungen**: "aus West", "Nordostwind" —
  Grad-Angaben nur fuer Spot-Windrichtung am Start
- **Konsequenzorientiert**: nicht *"Trog ueber Westeuropa"* → sondern
  *"Kaltfront-Durchgang Mittwoch, danach NW-Wetter, Stau am Alpennordhang"*
- **Konservativ beim Foehn**: SHV/FSVL-Linie ist explizit
  *"Wer sicher unterwegs sein will, muss sich mit den Meteo-Gefahren
  auseinandersetzen"* ([shv-fsvl.ch](https://www.shv-fsvl.ch/en/fluggebiete-sicherheit/safety/translate-to-englisch-sicherheit/translate-to-englisch-meteo/))

### Verstaendliche Begriffe (ohne Erklaerung)
Westlage, Bise, Foehn (Sued/Nord), Hochdruck, Tiefdruck, Front, Kaltfront,
Warmfront, Stau, Lee, Luv, Schneefallgrenze, Konvergenz (XC-Piloten),
Inversion, Genua-Tief, Vb-Lage.

### Zu fachlich (sollten vermieden werden)
500-hPa-Geopotential, Vorticity, Trogachse, Rueckenamplitude, Isohypse,
Jet-Stream-Maximum, Positive Vorticity Advection.

### Beispielsaetze die funktionieren

MeteoNews-Stil ([Quelle](https://meteonews.ch/de/Allgemeine_Lage/K33/Europa)):
- *"Westlich der Britischen Inseln entwickelt sich ein ausgepraegtes Tiefdruckgebiet.
  Eine okkludierende Front sorgt dort fuer ein Band aus Schauern."*

Pilotenversion (besser):
- *"Ein Tief vor Irland schiebt Mittwoch eine Kaltfront ueber die Schweiz —
  mit ihr Schauer, danach klart's auf NW-Wind auf."*

---

## 4. Zeithorizont und Konfidenz

| Tag | Pilotenverhalten | Konfidenzlevel im Cast |
|---|---|---|
| Tag 1-2 | konkret planen (Spot, Uhrzeit, Schirmwahl) | high |
| Tag 3 | Tendenz, Lage-Wechsel pruefen | medium |
| Tag 4-5 | nur "bleibt das Hoch oder kippt's?" — Urlaubsplanung | low |

**Schluesselregel:** Ueber 3 Tage hinaus interessiert nicht *"wird's am
Niederhorn fliegbar?"* sondern *"bleibt die Lage stabil?"* Konfidenz-Decay
explizit im Cast kommunizieren ("Tendenz", "duerfte" statt definitiver
Aussagen).

---

## 5. Fallstricke / No-Gos

Was Piloten frustriert oder in die Irre fuehrt:

1. **Erfundene Frontnamen oder Front-Zeitpunkte** wenn das Modell-Ensemble streut.
   *SHV-Doktrin: Eingestaendnis von Unsicherheit ist serioeser.*
2. **Foehn pauschalisieren** — Foehn-Richtung muss zur Region passen
   (Suedfoehn ≠ Nordfoehn-betroffen).
3. **"Schoenes Wetter" ohne Lage-Kontext** — Hochdruck kann inversionsgeplagt
   (Wintersmog Mittelland) oder top XC sein, je nach Saison + Feuchte.
4. **Mittelland und Alpen in einen Topf** — bei NW-Stau sperrt Alpennord,
   Wallis ist Lee und fliegbar. Pauschalsaetze "ganze Schweiz" verlieren
   Glaubwuerdigkeit.
5. **Synoptik-Etiketten ohne Daten-Backing** — "Trogvorderseite" sagen,
   wenn das Modell nur diffus tief zeigt = Erfindung. Sicherheits-Risiko +
   Vertrauensverlust.
6. **Niederschlag als "es regnet" abhandeln** — Piloten brauchen Charakter
   (konvektiv/stratiform), Tageszeit, Verteilung Nord/Sued. *"Schauer am
   Nachmittag"* ist nuetzlicher als *"15mm/Tag"*.
7. **Schneefallgrenze ignorieren im Fruehjahr/Herbst** — Wallis/Hochalpen-Piloten
   brauchen das (kein Start auf Schnee, Thermik anders, Lawinen). Im Fruehling
   typisch 1800-2500m ([sac-cas.ch](https://www.sac-cas.ch/de/die-alpen/typische-schnee-und-witterungsverhaeltnisse-im-herbst-in-den-alpen-10921/)).

---

## 6. Niederschlag-Charakterisierung

Piloten wollen wissen (in Reihenfolge der Wichtigkeit):

1. **Trocken oder nass** (binaer als Filter)
2. **Tageszeit** (Vormittag fliegbar trotz Schauer-Risiko nachmittags?)
3. **Raeumliche Verteilung** (Alpennord Stau, Wallis trocken? Tessin Sonne,
   Nordalpen Regen?)
4. **Charakter**: Schauer/Gewitter (lokal, planbar) vs. Dauerregen (Tag verloren)
   vs. Stau (regional sperrend)
5. **Intensitaet** in mm/Tag — aber kalibriert (5mm Nachmittag = sportlich;
   30mm = Tag streichen)
6. **Konvektiv vs. stratiform** — NICHT so benennen, sondern *"einzelne
   Gewitter"* vs. *"flaechendeckend bedeckt mit Regen"*

Bei **Vb-Lage** explizit nennen — Piloten erkennen den Begriff wieder.

---

## 7. Regional-Differenzierung CH (DER Mehrwert)

CH-Geografie zwingt regional differenzierte Aussagen. Das ist der wahre
Mehrwert gegenueber generischen DACH-Casts:

| Region | Bei Westlage | Bei Bise | Bei Suedfoehn | Bei NW-Stau |
|---|---|---|---|---|
| **Mittelland** | wechselhaft, Wind | windig/kalt, im Lee OK (Gurnigel) | meist OK, hoch oben S-Wind | Wolkenbasis tief |
| **Jura** | Westwind kanalisiert | NE-Wind, oft fliegbar Ostflanke | wenig betroffen | Wolken, oft fliegbar Sued |
| **Voralpen Nord** | Stau-Risiko, Foehn-Lee | OK im Lee, Nordhaenge gesperrt | **gesperrt** (Foehn-Lee) | **Stau, oft Tag-Killer** |
| **Berner Oberland** | wechselhaft, viel Wind | meist OK, NE-Seite betroffen | **gesperrt** (Haslital, Grimsel) | **Stau** |
| **Wallis** | von W abgeschirmt, oft fliegbar | wenig betroffen | Luvseite (Stau) oder thermisch destabilisiert | **Lee — oft Top-Tag** |
| **Tessin** | abgeschirmt, eigene Dynamik | nicht betroffen | **Luvseite, oft Regen** | **Lee oder Stau Nordtessin** |
| **Hochalpen** | Wind & Wolken | Wind, kalt | exponiert, Foehn massiv | Stau, Schnee, schwierig |

**Essenz:** Die Schweiz ist meteorologisch 4-5 verschiedene Laender. Westwind
im Wallis ≠ Westwind im Tessin ≠ Westwind im Mittelland.

---

## 8. Konsequenzen fuer den Wetterlage-Block

### MUSS drin sein

1. **Lage-Label in Pilotensprache** (Westlage, Bisenlage, Suedfoehnlage,
   Vb-Tief, Hochdrucklage, Uebergangslage) — deterministisch ableiten, keine
   Phantom-Etiketten.
2. **5-Tages-Stroemungstrend pro Tag**: 1-3 Worte Richtung + Druckcharakter.
3. **Foehn-Hinweis wenn aktiv** mit **Richtung (Sued/Nord) und betroffenen
   Regionen** — niemals pauschal.
4. **Bise-Hinweis wenn aktiv** mit Staerkequalifizierung schwach/mittel/stark.
5. **Niederschlag qualitativ Nord vs. Sued der Alpen getrennt** (trocken /
   Schauer / Stau / Gewitter).
6. **Schneefallgrenze** im saisonalen Fenster (Maerz-Mai, Okt-Nov).
7. **Konfidenz-Decay** Tag 1-2 high, Tag 3 medium, Tag 4-5 low — Sprachhaerte
   passt sich an.
8. **Regionale Differenzierung** wenn die Lage es verlangt (bei Foehn/Stau
   muessen Nord/Sued/Wallis explizit auseinander).

### Nice-to-have
- Vergleich zur Vorwoche / Saisonal-Kontext (*"Erste richtige Westlage des
  Jahres"*)
- Trend-Pfeil 6-7 Tage als Outlook
- Hinweis auf typische saisonale Phaenomene (Fruehjahrsthermik destabilisiert
  flachen Foehn; Hochnebel im Winter bei Bise)

### Weglassen / vermeiden
- 500-hPa-Karten, Geopotential-Linien, Vorticity als Begriffe
- Frontentyp-Etiketten ohne eindeutiges Daten-Backing
- Stundengenaue Frontankunft ueber Tag 2 hinaus
- Pauschal-Aussagen "Schweiz schoen"
- Burnair-/MeteoSchweiz-Copy-Style (zu nuechtern, kein klares Lage-Label)

---

## 9. Was der erfahrene CH-Pilot vermisst (wenn falsch gebaut)

- Block sagt nur *"Westlage"*, aber nicht *"fuer Mittelland heisst das X,
  fuer Wallis Y"* → fuehlt sich generisch an.
- Foehn wird genannt, aber **Richtung (Sued/Nord) und Regionen** fehlen →
  unbrauchbar.
- Niederschlag nur als Zahl (15mm), nicht als **Charakter** (Schauer vs. Stau)
  → muss Pilot selbst interpretieren.
- **5 Tage gleich detailliert** behauptet → Vertrauensverlust bei Tag-5-Fehler.

## Was ihn als ueberfluessig / zu fachlich nervt

- Geopotential-Werte in gpdm.
- Synoptische Diagnose-Etiketten ohne Konsequenz fuer den Flug
  ("Positive Vorticity Advection vor dem Trog").
- Wiederholung dessen, was der Tagescast schon sagt — der Wochenblock
  muss *Lage* sein, nicht Spotdetail.

---

## 10. Anwendung in Wingcast

Direkter Bezug zu Entscheidungen in `engine/synoptic_context.py`:

| Erkenntnis | Implementiert als |
|---|---|
| Top-down: Druck → Stroemung → Phaenomene | `decide_pressure_influence` → `decide_flow_overhead` → `decide_bise/vb_lage/foehn` |
| Lage-Label in Pilotensprache | `decide_lage_label` (Hierarchie Foehn > Vb > Bise > Stroemung > Druck) |
| Konfidenz-Decay | `decide_confidence_per_day` (high/medium/low) |
| Foehn pro Richtung + Region | `decide_foehn_summary` (Quelle `foehn_indicators.py`) |
| Niederschlag Nord/Sued der Alpen | `decide_precip_pattern_nord_sued` (Spot-Klassifikation per Lat/Lon) |
| Schneefallgrenze saisonal | `decide_schneefallgrenze` (nur Maerz-Mai + Okt-Nov) |
| Keine fachlichen Etiketten ohne Backing | Skill-Whitelist + Post-Filter in `engine/synoptic_llm.py` |

---

## Quellen

CH-Pilotenservices und Schulen:
- [burnair.ch Meteoservice](https://www.burnair.ch/meteoservice/) — Marktfuehrer, sehr pragmatische Sprache
- [Swissgliders Wetter](https://swissgliders.ch/de/wetter/) — empfohlener Workflow Top-down
- [Paraworld – Backwards weather](https://www.paraworld.ch/en/news-facts/weather/backwards-weather-where-to-fly/) — Regionalempfehlung pro Lage
- [adnubes Flugberichte](https://adnubes.info/de/category/flugberichte-gebiete/) — Pilotenblog-Sprachstil
- [Chill Out Paragliding Meteo](http://chilloutparagliding.com/infos/news-reports/category/meteo/) — Berner Oberland XC

CH-Wettersysteme:
- [Wetteralarm – Bise/Foehn/Westwind](https://wetteralarm.ch/blog/windarten.html)
- [MeteoNews Allgemeine Lage](https://meteonews.ch/de/Allgemeine_Lage/K33/Europa) — CH-Synoptik-Prosa-Standard
- [MeteoSchweiz NW-Lage](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/northwesterly-situation.html)
- [MeteoSchweiz Bise-Blog](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2026/04/wenn-die-bise-weht.html)
- [MeteoNews Vb-Tief](https://meteonews.ch/de/News/N14151/Was-ist-ein-Vb-Tief)
- [NZZ – Das verflixte Genua-Tief](https://www.nzz.ch/articleD31CG-ld.357173)
- [Rheintalmeteo Foehnprognose](https://www.rheintalmeteo.ch/prognosen/foehnprognose)
- [Biseflueger Gantrischregion](https://biseflueger.ch/gantrischregion.html)
- [SAC – Herbst-Witterung Alpen](https://www.sac-cas.ch/de/die-alpen/typische-schnee-und-witterungsverhaeltnisse-im-herbst-in-den-alpen-10921/)

Pilotensprache + Lexika:
- [Knackwurstflieger Woerterbuch](http://knackwurstflieger.blogspot.com/2012/10/kleines-worterbuch.html)

Verbandshaltung + Sicherheit:
- [SHV/FSVL Meteo](https://www.shv-fsvl.ch/en/fluggebiete-sicherheit/safety/translate-to-englisch-sicherheit/translate-to-englisch-meteo/)

Interne Files mit Bezug zum Thema:
- `skills/foehn_chat_knowledge.md` — Foehn-Doktrin (Sprache, Schwellen, Regionalisierung)
- `marktresearch/produktkonzept-core-offer.md` — Briefing-Stil-Vorgaben
- `meteo_research/flight_day_evaluation.md` — Pilotensprache fuer Tagesbewertung (komplementaer)
