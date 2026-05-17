# Wetterlagen-Pilotenwissen Schweiz — meteorologisches Hintergrundwissen

**Status:** Recherche-Synthese (Mai 2026)
**Zweck:** Wissensbasis fuer den LLM in der Wochenanalyse, damit detektierte
Wetterlagen (aus `engine/synoptic_context.py`) fundiert und halluzinationssicher
interpretiert werden koennen.
**Wichtig:** Dieses Dokument *erfindet keine Lagen* — es liefert nur das
"Was-bedeutet-das"-Wissen zu den Strukturfeldern, die deterministisch erkannt
wurden. Konkrete Zahlen (hPa, °C, km/h) bleiben aus Halluzinations-Gruenden
weitgehend verbal ("typisch deutlich ueber 1020 hPa", "stuermisch").

---

## 1. Hochdruck ueber der Schweiz

### Physik
Hochdruckgebiete (Antizyklonen) sind Bereiche, in denen die Luft grossraeumig
**absinkt (Subsidenz)**. Absinkende Luft erwaermt sich trockenadiabatisch um
ca. 1 K pro 100 m, ihre relative Feuchte sinkt — Wolken loesen sich auf, neue
koennen sich kaum bilden. Auf dem Boden divergiert die Luft, der Wind weht
**im Uhrzeigersinn** (Nordhalbkugel) um das Druckmaximum
([MeteoSchweiz — Subsidenz](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/subsidence.html);
[StudySmarter — Antizyklon](https://www.studysmarter.de/schule/geographie/klimatologie/antizyklon/)).

Man unterscheidet:
- **Dynamische / warme Hochs** (z.B. Azorenhoch) — subtropische Zellen, Teil des
  globalen Hochdruckguertels, warm bis in die Hoehe.
- **Thermische / kalte Hochs** (z.B. Sibirienhoch im Winter) — flache Bodenhochs
  ueber stark ausstrahlenden Landflaechen, in der Hoehe oft schon Tief.
- **Kontinentale Hochs** ueber Mitteleuropa — saisonal sehr unterschiedlich.

### Sommer- vs. Winter-Hochdruck — der entscheidende Unterschied fuer Piloten
- **Sommer**: Hochdruck heisst lange Sonneneinstrahlung, hohe Boden­temperaturen,
  starke Konvektion. Die Mischungs­schicht waechst tagsueber kraeftig (1500-3000+ m).
  Das sind die klassischen XC-Tage — bis es zu heiss wird (Hitzewelle, Saharaluft)
  und die Konvektion gestoert oder die Sicht durch Dunst stark reduziert ist.
- **Winter**: Hochdruck = **Inversionswetter**. Wenig Sonne, lange Naechte, der
  Boden kuehlt durch Ausstrahlung stark aus. Die kalte Luft sammelt sich am
  Talboden, darueber liegt waermere Luft. Ergebnis: persistenter **Hochnebel**
  im Mittelland, brilliante Sicht oberhalb
  ([Wikipedia — Hochnebel in der Schweiz](https://de.wikipedia.org/wiki/Hochnebel_in_der_Schweiz);
  [MeteoSchweiz — Hochnebelobergrenze](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2025/02/wie-verhaelt-sich-die-obergrenze-des-hochnebels.html)).

### Inversion im Detail
Bei einer Inversion kehrt sich der normale Temperaturgradient um: statt
mit zunehmender Hoehe abzunehmen, **nimmt die Temperatur kurzfristig zu**
([MeteoSchweiz — Inversion](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/inversion.html);
[MeteoNews — Inversion](https://meteonews.ch/de/News/N15772/Inversion---verkehrte-Temperaturwelt)).
Die warme Schicht wirkt wie ein Deckel: Vertikalaustausch und Mischung werden
unterdrueckt, Feuchtigkeit, Aerosole und Schadstoffe sammeln sich darunter
("Wintersmog"). Die Hochnebelobergrenze ist meist scharf, oft zwischen 700 und
1500 m, mit Tagesgang (mittags etwas hoeher) und Lageabhaengigkeit.

### Hochdruckbruecke und Omega-Lage
Eine **Hochdruckbruecke** verbindet zwei Hochs ueber den Kontinent hinweg —
oft Azorenhoch mit einem osteuropaeischen Hoch. Ueber Mitteleuropa entsteht
dadurch ein stabiler Hochdruck­streifen. Die **Omega-Lage** ist die stabilste
Variante: ein zentrales Hoch wird west- und ostseitig von zwei Tiefs flankiert,
die Stroemung in der Hoehe zeichnet einen Omega-Buchstaben (Ω)
([Wikipedia — Omegalage](https://de.wikipedia.org/wiki/Omegalage);
[MeteoSchweiz — Blockierte Hochdrucklage](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2023/02/blockierte-hochdrucklage-in-sicht.html);
[Unwetterzentrale — Omega-Lage](https://www.unwetterzentrale.de/uwz/365.html)).
Solche "Blocking-Patterns" lenken Atlantik-Tiefs nach Norden und Sueden um,
Mitteleuropa bleibt ueber Tage bis Wochen trocken. Im Sommer Hitze­wellen
und Duerre, im Winter strenge Kaelte oder Hochnebel-Dauerlagen.

### Pilot-Implikationen
- **Sommer-Hochdruck**: oft optimal, aber Vorsicht bei Hitze-Hochs — Konvektion
  kann zu hoch werden (Inversion bremst Cumulus-Top), Dunst (Pollen, Staub)
  reduziert Sicht, am Nachmittag drohen "trockene" Auf­winde mit grossen Boen.
- **Winter-Hochdruck**: unter der Inversion fluglos (Nebel), darueber traumhaft
  klar — Startplaetze ueber der Nebelobergrenze (Voralpen-Suedhaenge, Alpen) sind
  gefragt. Tipp: Hochnebelobergrenze checken, dann gezielt darueber starten.
- **Sub-Phaenomene**: Strahlungsnebel in Taelern, Bodenfrost in Senken, Foehn-Blocking
  (ein staerker werdendes Hoch im Osten kann den Suedfoehn abwuergen).

### Regionale Unterschiede bei Hochdruck
- **Mittelland**: Klassisches Nebelopfer — die "Mittelland-Badewanne" zwischen
  Jura und Alpen
  ([MeteoSchweiz — Plateau fog hole](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/fog/swiss-plateau-fog-hole.html)).
- **Wallis und Engadin**: Inneralpine Becken haben oft eigene flachere Inversionen
  und Strahlungsnebel an Talboden, aber kein flaechiger Mittellandhochnebel — auf
  Spots ab ~1200-1500 m oft strahlend.
- **Tessin**: Bei Hochdruck mit Nordlage selten betroffen, Suedseite oft sonnig
  und durch Bergketten geschuetzt.
- **Alpen / Hochalpen**: meist ueber dem Nebel, viel Strahlung, aber im Winter
  thermisch tot.

---

## 2. Tiefdruck ueber der Schweiz

### Physik
Tiefdruckgebiete (Zyklonen) entstehen entlang der **Polarfront** — der
Frontalzone zwischen tropischer Warmluft und polarer Kaltluft im Bereich
45-60° N
([Spektrum — Polarfront](https://www.spektrum.de/lexikon/geographie/polarfront/6105)).
Die Frontalzone ist barokline (Temperatur­gradient quer zur Stroemung): kleine
Stoerungen wachsen zu **baroklinen Wellen**, aus denen sich innerhalb weniger
Tage Zyklonen entwickeln
([Spektrum — Barokline Wellen](https://www.spektrum.de/lexikon/geographie/barokline-wellen/723);
[Wikipedia — Zyklogenese](https://de.wikipedia.org/wiki/Zyklogenese)).
Im Zentrum steigt die Luft auf, expandiert, kuehlt ab, kondensiert — Wolken
und Niederschlag. Der Wind weht gegen den Uhrzeigersinn um das Tief.

### Typen relevant fuer die Schweiz
- **Atlantik-Tief**: Klassiker. Tief zieht von Island/Britischen Inseln ueber
  Nordsee/Mitteleuropa. Bringt Westlagen-Wetter mit Fronten­durchgaengen.
- **Genua-Tief / Mittelmeertief**: Tiefdruckzentrum im Genua-Golf
  ([Wikipedia — Mittelmeertief](https://de.wikipedia.org/wiki/Mittelmeertief)).
  Sehr unterschiedliche Auspraegungen — kann lokale Schauer im Tessin bringen
  oder, wenn es Richtung Mitteleuropa zieht, eine Vb-Lage ausloesen (siehe 8).
- **Skandinavien-Tief**: Tiefdruck im Norden, Hochdruck im Sueden — generiert
  oft Bise (siehe 6) oder NW-Stau (Suedwest- und Westlagen werden um das Tief
  herum nach NW gedreht).
- **Kontinentale Hitzetiefs**: Sommer, ueber stark erwaermten Landflaechen
  (Iberien, Nordafrika). Flach, kein Frontensystem — eher Marker als Wetter­macher.

### Frontensysteme — was sie konkret fuer Piloten heissen
- **Warmfront**: Warmluft gleitet langsam ueber kalte Luft, Aufgleitwolken
  (Cirren > Altostratus > Nimbostratus), Schichtniederschlag oft 6-12 h vor
  Frontpassage einsetzend
  ([MeteoSchweiz — Lehrbuch-Warmfront](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2022/12/lehrbuch-warmfront.html)).
  Fuer Piloten: Frueh­morgens-Cirren, dann Hochnebel-aehnliche Decke, am Boden
  warm und schwuel, Wind dreht von SE auf SW. Fliegerisch oft schwach, Sicht
  schlecht. **Kann fliegbar sein** in der Warmfront-Vorderseite mit guten Steigwerten
  in der Restkonvektion vor dem Aufgleiten.
- **Kaltfront**: Kaltluft schiebt sich keilfoermig unter Warmluft, hebt diese
  abrupt. Cumulus congestus, Cumulonimbus, Schauer und Gewitter, dann rasche
  Aufklarung. Wind dreht von SW auf NW, Boen koennen heftig sein. Fuer Piloten:
  praefrontal oft noch fliegbar mit grossen Steigwerten, aber Front-Annaeherung
  rechtzeitig erkennen (Cumulonimbus am Westhorizont, Druckfall, Boen).
- **Okklusion**: Kaltfront holt die langsamere Warmfront ein
  ([SRF — Fronten](https://www.srf.ch/meteo/meteo-stories/wetterwissen-eine-front-kommt-selten-allein)).
  Warmsektor wird vom Boden weg­gehoben. Mischform von Warm- und Kalt­front­merkmalen,
  oft schwer einzuschaetzen, viel Bewoelkung, manchmal Niederschlag mit Schauer­charakter.

**Trog vs. Rinne**: Beides sind tief­druck­geneigte Strukturen in der Hoehe.
Ein **Trog** ist eine V-foermige Tieferausstuelpung in der Hoehen­stroemung
(meist 500 hPa), oft mit Front am Boden gekoppelt. Eine **Rinne** ist mehr ein
laenglicher Bodentief­druck­streifen ohne ausgepraegte Hoehen­front. Operativ
relevanter ist der Trog: Trog-Vorderseite = warm, aufsteigend, gewitter­anfaellig;
Trog-Rueckseite = kalt, postfrontal, schauerig.

### Pilot-Implikationen
- **Praefrontal warm** (Trog-Vorderseite vor Kaltfront): oft die besten XC-Tage —
  warme Luftmasse, gute Konvergenz, hohe Basis. Aber Front-Timing kritisch.
- **Postfrontal kalt**: Tag 1 nach Kaltfront-Durchzug oft labil mit schoenen
  Cumuli, mittlere bis hohe Basis, aber Schauer­anfaelligkeit. Tag 2 oft am
  besten ("Sonniges Rueckseiten­wetter").
- **Tiefdruck-Zentrum direkt ueber CH**: bewoelkt, regnerisch, kaum fliegbar.
- **Schwache Tiefdrucklage** (flacher Druck): kaum Wind, viel Bewoelkung,
  oft schwache Thermik wegen fehlender Einstrahlung.

---

## 3. Alpenkamm-Einfluss

### Stau-Effekt physikalisch
Stroemt feuchte Luft gegen ein Gebirge, **muss sie aufsteigen**. Beim Aufstieg
kuehlt sie sich ab (zunaechst trocken­adiabatisch 1 K/100 m, nach Erreichen
der Sättigung feucht­adiabatisch ca. 0.5-0.6 K/100 m). Die Feuchte kondensiert,
es bilden sich Stau­wolken, oft starker Niederschlag
([Wikipedia — Stau (Meteorologie)](https://de.wikipedia.org/wiki/Stau_(Meteorologie));
[MeteoSchweiz — Nordstau](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/northern-orographic-effect.html)).
Im Lee sinkt die Luft wieder, erwaermt sich (trockenadiabatisch, weil schon
ausgeregnet), Wolken loesen sich auf — der **Foehneffekt**.

### Welche Anstroemung verursacht welchen Stau in CH
- **West-/NW-Stroemung** → **Nordstau Alpen** (Berner Oberland, Glarner­land,
  Toggenburg, Saentis, Voralpen-Nordhang). Linthtal und Glarus sind klassische
  Hotspots.
- **N-Stroemung** → ebenfalls Nordstau, oft kombiniert mit kalter Luftmasse.
- **Sued-/SE-Stroemung** → **Suedstau Alpensued­seite** (Tessin,
  Suedbuenden, suedliches Wallis Simplon-Region). Klassisches Vb-Pattern.
- **NE-Stroemung (Bise)** → kein klassischer Stau, weil die Bise im Mittelland
  bleibt; eher trocken-kalt.

### Wo verlaeuft der Alpenhauptkamm
Der Alpenhauptkamm trennt das Einzugsgebiet von Mittelmeer und Nordsee/Atlantik.
In der Schweiz verlaeuft er grob ueber: Mont Blanc - Grand Combin - Matterhorn -
Monte Rosa - Furka - Gotthard - Bernina - Bernina-Pass
([Snowplaza — Alpenhauptkamm](https://www.snowplaza.de/weblog/alpenhauptkamm-welche-ist-die-nord-und-suedseite-der-alpen/)).
Bei Suedstroemung sind die Suedhaenge dieser Kette Luv, bei Nord­stroemung Lee.
Die Schweizer Alpennord­seite (Berner Alpen, Glarner Alpen) bildet einen zweiten,
oft wirkungs­volleren Wall — er liegt direkt im Anstroemungs­weg von NW-Westlagen.

### Sekundaere Kaemme
- **Jura**: erste Stau­schwelle bei reiner Westlage, oft moderater Stau­regen
  noch ueber dem Mittelland (klassisches "Westwind-Schauerwetter" am Jurasuedfuss).
- **Voralpen**: 2. Stau­linie nach Jura, "Voralpen­regen" — fuer NW-Stau zentral.

### Tal-Berg-Wind-Systeme (Alpenpumpe)
Bei schwachen synoptischen Gradient­winden uebernehmen thermisch getriebene
Talwinde. Tags: Sonne erwaermt Hange/Berggipfel staerker als die Talluft,
Luft steigt am Hang auf, im Tal stroemt Luft als **Talwind** aus dem Vorland
nach. Nachts umgekehrt: Hangabwind / **Bergwind**
([Wikipedia — Berg-/Talwind](https://de.wikipedia.org/wiki/Berg-_und_Talwind-Zirkulation);
[MeteoSchweiz — Talwinde](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2024/08/talwinde-oder-warum-es-in-den-alpen-auch-an-ruhigen-tagen-windig-ist.html);
[SRF — Berg- und Talwind](https://www.srf.ch/meteo/meteo-stories/windzirkulation-in-den-alpen-wie-entstehen-berg-und-talwind)).

Die **Alpenpumpe** ist die grossraeumige Ausweitung dieses Prinzips: Im Sommer
heizen sich die Alpen tagsueber so stark auf, dass ueber dem Alpen­kamm Luft
aufsteigt und im Mittelland nachstroemt — schwacher Nordwind im Mittelland am
Nachmittag bei ansonsten gradient­armer Lage
([windinfo.eu — Alpines Pumpen](https://www.windinfo.eu/alpines-pumpen/)).

### Konvergenzlinien und Spezialwolken
- **Konvergenz**: zwei Luftstroeme treffen aufeinander, Aufwind. In den Alpen
  klassisch wo Talwinde an Paesse stroemen und sich treffen — "Brünig-Hexe",
  "Grimselschlange". Fuer XC-Piloten Gold wert, oft mit ausgepraegten Wolken­strassen.
- **Hangaufwind / Soaring**: dynamischer Aufwind durch Wind, der gegen einen
  Hang stroemt. Geht auch ohne Sonne. Klassisches Jura-Soaring bei Westwind.
- **Wolkenstrasse**: Reihen von Cumuli entlang der vorherrschenden Wind­richtung,
  oft Hinweis auf strukturierte Konvektion und gute XC-Linien.
- **Cap-Wolke** (Wolkenhaube): Lentikular­wolke direkt ueber dem Berg­gipfel,
  Indiz fuer starke Hoehen­winde und potenzielle Lee-Wellen.
- **Lenticularis / Foehnfisch**: linsenfoermige, stationaere Wolken — entstehen
  an Lee-Wellen­bergen oberhalb des Kammes
  ([Wikipedia — Lenticularis](https://de.wikipedia.org/wiki/Lenticularis);
  [DMG — Lenticularis](https://www.dmg-ev.de/2020/04/19/lenticularis/)).
  Ein **klares Foehnzeichen**, oft mit starker Turbulenz unter den Wellen­bergen.
- **Rotorwolke**: walzen­foermige Wolke im Lee unter Lee-Wellen­bergen, kennzeichnet
  eine starke horizontale Wirbel­zone — **fuer Piloten extrem gefaehrlich**, in
  jedem Fall meiden
  ([DMG — Rotorwolken](https://www.dmg-ev.de/2000/03/08/rotorwolken/)).

### Wetterscheide
Der Alpenhauptkamm ist die wichtigste meteorologische **Wetterscheide** Europas.
Beispiele:
- NW-Lage: am Saentis 200 mm Regen, im Tessin sonnig.
- Suedstau: in Locarno 100 mm in 6 h, in Zuerich blauer Himmel.

---

## 4. Suedfoehn — meteorologische Spezialitaeten

### Druckkonstellation
**Tief im Westen (Britische Inseln/Westfrankreich) + Hoch im Osten
(Mitteleuropa/Balkan)** → resultierende Stroemung quert die Alpen von Sued
nach Nord. Im Lee (Alpen­nordseite) entsteht Foehn
([MeteoSchweiz — Foehn](https://www.meteoswiss.admin.ch/home/climate/the-climate-of-switzerland/specialties-of-the-swiss-climate/foehn.html);
[Wikipedia/DWD — Foehn](https://dwd.de/DE/service/lexikon/begriffe/F/Foehn.html);
[Schweizer Sturmforum — Foehndiagramm](https://sturmforum.ch/viewtopic.php?t=6668)).

Operative Druckdifferenz-Faustregel (Lugano − Zuerich oder Lugano − Kloten):
Foehn dringt typisch ab etwa **+4 hPa** in die Alpentaeler vor, mit **+8 hPa
oder mehr** kann er das Vorland erreichen (Erfahrungswerte aus
[Rheintalmeteo](https://www.rheintalmeteo.ch/prognosen/foehnprognose),
[MeteoSchweiz — starker Foehn](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2023/10/starker-foehn-in-den-alpentaelern.html)).
Diese Werte sind nicht hart, sondern lagen­spezifisch.

### Vorfoehn vs. echter Foehn
- **Vorfoehn**: Suedwind setzt in der Hoehe ein, der eigentliche Lee-Effekt
  am Boden ist noch nicht durch (Talinversion blockiert). Spuerbar als
  hoehere Bewoelkung, Warmlufthebung, Drucksenkung in den Foehntaelern.
- **Echter Foehn / Foehndurchbruch**: warme Luft erreicht den Boden, Inversion
  ist weg, Temperatur springt sprunghaft, Sicht extrem klar, Suedwind boeig.
  Klassisches "Foehn-Knie" im Tages­temperatur­gang.

### Foehnmauer
**Cumulus- und Stratus-Wand am Alpenkamm Suedseite** — sichtbar von Norden als
"Mauer" entlang der Berge. Wird durch das Stauen der feuchten Suedluft am
Kamm verursacht; in der Mauer regnet es typisch im Tessin/Suedwallis, ueber
und hinter dem Kamm reisst die Bewoelkung auf
([DHV — Stau und Foehn](https://www.dhv.de/media/jahre/2024/07_wetter/Wetterwissen/DHVmagazin_Artikel/F%C3%B6hn/6_2011_172_stau_und_foehn.pdf)).

### Trockenheit und Waerme im Lee
Weil die abgesunkene Luft ihre Feuchte im Luv abgeladen hat, ist sie im Lee
**warm und trocken** — Tempera­tur­spruenge von 10-15 K innert Stunden sind
moeglich, Luftfeuchte stuerzt unter 30%. Klassische "Foehntag"-Atmosphaere mit
brillianter Fernsicht, "Foehnfischen" am Himmel, klarem Hochdruck-Charakter
suedlich des Foehnabbruchs.

### Foehnsturm
Wenn der Druck­gradient sehr stark wird, druecken die Hoehenwinde so massiv,
dass am Boden orkanartige Boen entstehen
([Windsurfing Urnersee — Foehnsturm](https://windsurfing-urnersee.ch/wissen/foehnsturm)).
In Foehntaelern (Reuss, Rhein, Linth, Hasli) sind Spitzenboen 90-120+ km/h
moeglich, lokal gelegentlich noch mehr — die exakten Werte schwanken stark
nach Tal-Topographie und Druckdifferenz
([MeteoSchweiz — starker Foehn](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2023/10/starker-foehn-in-den-alpentaelern.html)).

### Foehnpausen und Foehnabbruch
- **Foehnpause**: kurzzeitige Unterbrechung — Inversion baut sich neu auf,
  Wind schlaeft ein, oft naechtlich. Foehn kann sich am Morgen reaktivieren.
- **Foehnabbruch**: definitive Beendigung, meist durch Kaltfront aus Westen
  oder Druckausgleich. Oft mit Boen und Wetterumschwung verbunden.

### Foehnwellen / Foehn-Lenticularis
Die Stroemung ueber dem Alpenkamm erzeugt **stehende Schwerewellen** in der
Lee. An ihren Wellen­bergen kondensieren Lenticularis-Wolken, in den Wellen­taelern
faellt die Luft turbulent ab. Lenticularis sichtbar ueber den Alpen sind ein
sicheres Zeichen fuer Hoehenfoehn und potenzielle Turbulenz im Lee.

### Foehntaeler Schweiz
- **Klassisch (oest. nach west.)**: Rheintal (St. Galler/Liechtensteiner Rheintal),
  Seeztal/Walensee, oberes Linthtal (Glarus), Reusstal (Urnerboden, Altdorf),
  Haslital/Brienzersee-Ostufer, Aaretal Berner Oberland, Engelbergertal, Sernftal.
- Die berühmten Foehnsee-Phaenomene: **Walensee-Foehn**, **Brienzersee-Foehn**,
  **Urnersee-Foehn** — der Foehn beschleunigt durch das Tal und faechert ueber
  dem See auf, mit teils dramatischen Wellen und Boen.

### Pilot-Implikationen Suedfoehn
- **Tessin/Suedwallis (Luv)**: Stauregen, Schlechtwetter, nicht fliegbar.
- **Foehntaeler im Lee**: gefaehrlich. Starke Boen, klare Luft taeuscht Sicherheit
  vor — auch bei "schoen aussehendem" Wetter fliegen erfahrene Piloten nicht.
- **Foehngeschuetzte Spots** (im Foehn­schatten, z.B. westliches Mittelland,
  Jura, Genfersee-Region): koennen profitieren — klare Sicht, schwacher Wind,
  oft gute Thermik. Aber Vorsicht: Foehndurchbruch kann sich auch nach Westen
  ausdehnen.
- **Klassische XC-Linie bei Suedfoehn**: nicht moeglich auf Nordseite — Sicht
  schoen, aber Turbulenz/Wind zu stark.

---

## 5. Nordfoehn — meteorologische Spezialitaeten

### Spiegelbild zum Suedfoehn
**Hoch im Norden + Tief im Sueden** → Nordstroemung quert die Alpen, im Lee
(Alpensued­seite = Tessin und Suedbuenden) entsteht **Nordfoehn**
([MeteoSchweiz — Winde Alpen Teil 2](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2023/02/winde-der-alpen-und-europas-teil-2.html);
[blueNews — Nordfoehn Tessin](https://www.bluewin.ch/de/news/schweiz/im-tessin-weht-ein-starker-wind-erreicht-bis-zu-80-kmh-2161566.html)).
Seltener als Suedfoehn (klimatologisch ca. 1/3 so haeufig — Erfahrungs­wert,
nicht exakt belegt), aber kann ebenso heftig sein.

### Betroffene Regionen
- **Tessin**: Mendrisiotto (Suedtessin), Magadinoebene (zwischen Locarno
  und Bellinzona) — klassische Nordfoehn-Zonen. Foehnsturm hier nicht selten
  mit 80-100+ km/h Boen.
- **Suedbuenden / Engadin**: Eigene Foehndynamik, oft als **Malojawind**
  bezeichnet (siehe unten).

### Maloja-Wind
Der **Malojawind** ist ein thermisch und/oder synoptisch getriebener Wind, der
vom Bergell durch den Maloja-Pass ins Engadin stroemt
([MeteoSchweiz — Engadin Skimarathon](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2025/03/wetter-engadin-skimarathon.html);
[MeteoNews — Maloja](https://meteonews.ch/de/Wetter/G2659779/Maloja)).
An sonnigen Tagen mit schwachem Gradient stark thermisch getrieben (Talwind
durch den Pass), bei Nordstroemung verstaerkt durch Foehneffekt. Tagsueber
SW-Wind im Oberengadin, der ab spaetem Vormittag einsetzt und am Nachmittag
seinen Hoehepunkt erreicht.

### Tramontana
Die **Tramontana** ist ein klassischer Nordwind, der vom Po-Ebenen-Tessin
gegen die Liguria stroemt. In der Schweiz weniger relevant als italienisch
benannter Wind, im Tessin teilweise synonym fuer Nord-Foehn-aehnliche Lagen
verwendet (begriffliche Unschaerfe, anekdotisch).

### Pilot-Implikationen Nordfoehn
- **Nordseite (Luv)**: NW-Stau, regnerisch, Vorsicht.
- **Tessin/Suedbuenden (Lee)**: schoen, aber boeig — fuer Piloten gefaehrlich
  wie Suedfoehn fuer Norden.
- **Maloja-Wind**: im Engadin Standard bei Schoenwetter, Piloten kennen ihn
  und planen Talwind ein. Im starken Nordfoehn wird er ueberlagert mit
  unberechenbaren Turbulenzen — dann Vorsicht.

### Saison
Nordfoehn ist tendenziell ein Phaenomen der Uebergangs­jahres­zeiten und des
Winters (Hochdruck noerdlich der Alpen + Tiefdruck Mittelmeer ist im Winter
typisch).

---

## 6. Bise — meteorologische Spezialitaeten

### Druckkonstellation
**Hoch ueber Nord-/Nordosteuropa + Tief ueber Mittelmeer/Mittelmeer­raum**
→ resultierende Stroemung aus NE ueber Mittel­europa
([MeteoSchweiz — Bise](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/bise.html);
[Wikipedia — Bise](https://en.wikipedia.org/wiki/Bise);
[swissinfo — Bise](https://www.swissinfo.ch/ger/ungewohnliche-schweiz/die-bise-ein-einzigartiges-schweizer-wetterph%C3%A4nomen/88834058)).
Im CH-Mittelland wird die Stroemung durch die "Duese" Jura/Alpen kanalisiert
und beschleunigt.

### Klimatologie
Bise tritt v.a. **im Winter und Vorfruehling** auf, wenn Sibirien- und
Skandinavien­hochs persistieren. Im Sommer seltener (anekdotisch ca.
20-30 Bisentage pro Jahr im Mittel — Quelle nicht abschliessend belegt;
exakte Zahlen schwanken jaehrlich stark).

### Regionale Wirkung
- **Genfersee**: staerkste Wirkung, weil die Duese hier am engsten zusammen­laeuft
  und der See offen liegt. Mittlere Bisenwinde 50 km/h, Boen 80+ km/h sind hier
  haeufig
  ([MeteoNews — Bise](https://meteonews.ch/de/News/N15011/Die-Bise_-ein-Schweizer-Spezialwind);
  [SRF — fiese Bise](https://www.srf.ch/meteo/meteo-stories/wind-im-mittelland-die-fiese-bise)).
- **Bodensee**: Ostende ebenfalls bisenexponiert.
- **Mittelland-Hauptachse**: von Bodensee Richtung Genfersee zieht die Bise
  durch — Plateau Vaud, Berner und Solothurner Mittelland.
- **Alpen­vorland**: weniger, durch Voralpenketten teilweise geschuetzt.

### Bisenkluft / Bisenlucke
Am Genfersee bildet sich oft eine markante **Bisenkluft** (Bisenlucke): eine
scharfe Linie zwischen kalter, klarer Bisenluft im NE und warmer, oft hoch­nebliger
Luft im SW. Optisch oft sichtbar als eine Wolkenkante quer ueber den See.
Wo genau die Grenze verlaeuft, ist tagesabhaengig und nicht streng definiert
(anekdotisch wichtige Marke fuer regionale Bewoelkungs­vorhersage).

### Schwarze vs. Weisse Bise
- **Schwarze Bise**: starker Wind mit aufgerissener, klarer Luft (kaltklare
  Hochdruck-Bise) — die "klassische" Bise.
- **Weisse Bise**: Bise mit Bewoelkung und Hochnebel — wenn der Druckgradient
  schwaecher und/oder die Luftmasse feuchter ist. Mittelland bleibt grau,
  Sicht schlecht, am Boden trotzdem windig.
(Die Abgrenzung wird in Pilotenkreisen teils unterschiedlich gehandhabt;
Begriffe sind nicht streng meteorologisch definiert.)

### Hoehen­bise vs. Bodenbise
- **Bodenbise**: typischer Wind im Mittelland, NE-getrieben.
- **Hoehenbise**: NE-Stroemung in der Hoehe ohne starken Bodendurchgriff —
  z.B. bei flachem Bodendruckgradient. Fuer Piloten relevant: Hoehe windig,
  Boden nicht — Soaring mit kraeftigem Wind in 1500-2500 m moeglich, am
  Start jedoch ruhig.

### Pilot-Implikationen
- **Mittelland-Spots**: bei Bise grossteils unsoarbar bzw. unfliegbar
  (zu starker NE-Wind, oft Hochnebel).
- **Jura-Ostflanken**: bei Bise klassischer Soaring-Hotspot (NE-Wind drueckt
  gegen die Jurakaette von Osten) — Crete du Vent, Chasseral-Region,
  Vue-des-Alpes.
- **Voralpen-Ostflanken**: ebenso, klassisch Gantrisch-Region, Gurnigel —
  Bisenflieger.ch sammelt solche Spots
  ([biseflueger.ch](https://biseflueger.ch/gantrischregion.html)).
- **Alpennordhang**: oft im Lee der Voralpen, ruhig — Wallis und Berner
  Oberland-Sued bleiben oft bisenfrei.
- **Sicht**: bei Schwarzer Bise spektakulaer klar (Mittelmeer-Sicht bis
  zu den Alpen), bei Weisser Bise mies.

### Bisenhochnebel
Spezialform des Hochnebels, der bei Bisenlage entsteht — der NE-Wind drueckt
feuchte Luft gegen den Jura, dort Stau-Hochnebel mit oft scharfer Westgrenze.
Foer Piloten: westlich der Bisenkluft fluglos, oestlich davon oft fliegbar.

---

## 7. Westlage / Westwetter

### Klimatologische Dominanz
Die Schweiz liegt in der **Westwind­drift**: Atlantik-Tiefs ziehen mit ihren
Frontensystemen quer ueber Mittel­europa. Westlagen sind die haeufigste
CH-Wetterlage (klimatologisch >40% der Tage im Jahr — Erfahrungs­wert; exakte
Zahl variiert nach Klassifikations­schema)
([MeteoSchweiz — Westerly winds](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/westerly-winds.html)).

### Warmsektor und Fronten­zyklus
Eine klassische Frontalwellen­zyklone hat:
1. **Warmfront im Osten** → Aufgleitwolken voraus, langsamer Regen, dann Front­durchgang.
2. **Warmsektor zwischen den Fronten** → warm, schwuel, oft Stratocumulus,
   teils Aufklarung.
3. **Kaltfront im Westen** → Schauer, Gewitter, dann rascher Frontdurchgang.
4. **Postfrontale Kaltluft** → labile NW-Stroemung mit Konvektion.

### Postfrontale Lage / NW-Lage
Nach Frontdurchgang dreht die Stroemung auf NW, oft mit weiterhin labiler
Kaltluft. Konvektive Cumuli mit teils kraeftigen Schauern, dann zunehmende
Aufklarung. Tag 1-2 nach Front oft sehr fluggebiets­abhaengig:
- Alpennordseite: NW-Stau, Schauer, schwer fliegbar.
- Wallis / Tessin: Foehngeschuetzt, oft sonnig — Pilot-Klassiker zum Ausweichen.

### Sommer vs. Winter Westwetter
- **Sommer**: Konvektion ist stark, Kaltfront­durchgaenge oft mit Gewittern.
  Postfrontale Tage haben oft Top-Konvektion mit hoher Basis.
- **Winter**: Fronten bringen Niederschlag, Schnee in hohen Lagen, Regen in
  Niederungen. Postfrontale Tage oft windig, kalt, klar — fluglos aus
  Temperatur­gruenden, aber sichtbar wegen Foehndurchbruch.

### Pilot-Implikationen
- **Warmsektor**: oft bewoelkt, mittelmaessig fliegbar.
- **Kaltfront-Vorderseite**: praefrontale Konvektion kann legendaer sein
  (lange XC-Tage moeglich), aber Front-Anflug rechtzeitig erkennen.
- **Postfrontal**: NW-Stau-anfaellig, Schauerlinien aus den Voralpen.
  Wallis/Tessin gehen oft.
- **Zwischen­hochs**: 1-2 Tage Westhoch / Zwischenhoch zwischen zwei Fronten —
  oft die besten Flugtage einer Woche.

---

## 8. Vb-Lage / Genua-Tief — die "Wetter­katastrophen"-Lage

### Entstehung
Die **Vb-Zugbahn** (gesprochen "Vau-bee") wurde 1891 von Wilhelm van Bebber
klassifiziert
([DWD — Vb-Wetterlage](https://www.dwd.de/DE/service/lexikon/begriffe/V/Vb-Wetterlage.html);
[Wikipedia — Mittelmeertief](https://de.wikipedia.org/wiki/Mittelmeertief);
[MeteoNews — Vb](https://meteonews.ch/de/News/N14151/Was-ist-ein-Vb-Tief)).

Klassischer Ablauf:
1. Kaltlufttropfen oder Trog zieht von Westen nach Sueden ueber Frankreich/Iberien.
2. Im Genua-Golf trifft die Kaltluft auf warme, sehr feuchte Mittelmeerluft.
3. Es entsteht eine **Genua-Zyklogenese** — schnelle, intensive Tiefdruck­entwicklung.
4. Das neugebildete Tief zieht **nach Nordosten ueber Norditalien Richtung
   Polen/Tschechien** — die "Vb-Bahn".

### Warum so verheerend fuer die Alpennordseite
Das Vb-Tief wandert im Uhrzeigersinn — auf seiner **Nordwest-Flanke** (von
CH aus gesehen: Tief ist im SE-O) stroemt warme, extrem feuchte Mittelmeer­luft
**von Suedosten gegen die Alpennordseite an**. Das ist die einzige Konstellation,
bei der die Alpennordseite richtig Suedostluft kriegt — die staut sich dann
massiv. Tagelange Dauerniederschlaege moeglich
([meteozentrale — Vb-Tief](https://meteozentrale.de/so-zieht-das-vb-tief-mit-heftigen-regen-und-schneefaellen-ueber-diese-regionen/);
[WetterKontor — Vb](https://www.wetterkontor.de/de/lexikon/vb-wetterlage.html)).
Hauptsaechlich betroffen sind Berner Oberland, Glarner Land, Liechtenstein,
Voralberg sowie das Tessin (aus anderem Grund: Luv der ersten Front).

### Saison
Vb-Lagen sind v.a. im **Spaetsommer und Herbst** typisch (Mittelmeer
extrem warm, Polarluft schon kraeftig). Im Mai/Juni gelegentlich, dann oft
mit Schneefall in hoeheren Lagen ("Schafskaelte" begleitend, anekdotisch).
Historische Beispiele in CH-Hochwasserchronik (z.B. August 2005, August 2002)
sind allgemein dokumentiert — exakte Zuschreibung jeweils zu Vb erfordert
synoptische Pruefung, daher hier ohne Detailangabe.

### Pilot-Implikationen
- **Generell**: Vb-Lagen sind **Wochen-Killer**. Mehrere Tage Dauer­regen, kein
  Spielraum fuer Fluege.
- **Tessin**: kann auf der Vor- oder Hinterseite gelegentlich aufreissen,
  oft aber selbst im Stau (S-Suedost-Anstroemung).
- **Wallis und Engadin**: koennen in Vb-Lagen teilweise geschuetzt sein
  (Lage suedlich oder oestlich des Hauptstaus) — aber nicht verlasslich.
- **Postvb**: Nach Vb-Durchgang oft 1-2 Tage spektakulaeres Aufklaren mit
  brilliantester Sicht ("nach dem Sturm").

---

## 9. Uebergangslagen

### Trog-Vorderseite vs. Trog-Rueckseite
- **Trog-Vorderseite**: Suedwest-Stroemung in der Hoehe, **Warmluft­advektion**,
  Aufgleiten, Bewoelkungs­zunahme, Konvergenz, gewitter­anfaellig im Sommer.
- **Trog-Rueckseite**: Nordwest-Stroemung, **Kaltluft­advektion**, Labilisierung,
  konvektive Schauer, oft sonnige Wechsel ("Aprilwetter").

### Kaltlufttropfen / Cut-off-Tief
Ein **Kaltlufttropfen** ist ein in der Hoehe abgeschnuertes Hoehentief, am
Boden oft kaum sichtbar
([menschenswetter — Kaltlufttropfen](https://www.menschenswetter.at/editorial_articles/show/1435/kaltlufttropffen-und-cut-off-tief);
[DWD — Kaltlufttropfen](https://www.dwd.de/DE/service/lexikon/begriffe/K/Kaltlufttropfen_pdf.pdf);
[windinfo — Kaltlufttropfen](https://www.windinfo.eu/kaltlufttropfen-der-schoenwetterverderber/)).
Sehr **schwer vorhersagbar**, kann tagelang an Ort verharren, dann ploetzlich
ziehen. Bringt im Sommer oft Ueberentwicklung (Schauer, Gewitter mit hoher CAPE)
ohne offensichtlichen Antrieb am Boden — heim­tueckisch fuer Piloten.

### Cut-off-Tief
Wenn ein Trog so weit nach Sueden ausgreift, dass er von der Hoehen­westdrift
abgeschnitten wird, entsteht ein **Cut-off**. Aehnlich Kaltlufttropfen, aber
oft groesser und langlebiger. Stationaer ueber Wochen moeglich.

### Warmluftadvektion / Kaltluftadvektion
- **Warmluftadvektion (WLA)**: Warmluft wird in eine Region eingestroemt,
  oft mit Aufgleiten und Hochnebel-Abbau. Pilot­spezifisch: WLA mit Suedwind
  in der Hoehe kann eine winterliche Hochnebel­decke "wegfraesen" — danach
  ploetzlich blauer Himmel.
- **Kaltluftadvektion (KLA)**: Kaltluft stroemt ein, labilisiert die Schichtung,
  Konvektion verstaerkt. Klassisch Polarluft­vorstoss mit Schauern.

### Zonalisierung vs. Meridionalisierung
- **Zonal** = West­winddrift entlang der Breitenkreise, schnelle, oft milde
  Fronten­zyklen.
- **Meridional** = Stroemung mit grossen Nord-Sued-Auslenkungen (Troege und
  Ruecken). Polarluft­vorstoesse weit nach Sueden moeglich, Hitze­ausbrueche
  nach Norden. "Blockierte" Lagen sind extrem meridional.

### Subtropische Hochs
- **Azorenhoch**: dynamisches Hoch ueber dem Subtropenatlantik, das im Sommer
  weit nach Norden ausgreifen kann und Mittel­europa stabilen Schoenwetter­einfluss
  bringt. Im Winter eher zurueckgezogen, dann Atlantik­tiefs freie Bahn.
- **Mittelmeer-Hoch**: meist Auslaeufer des Azorenhochs ueber das Mittelmeer,
  pragmatisch im Sommer typisch.

---

## 10. CH-spezifische Mikroklimata

### Tessin (Insubrien)
Mediterrane Praegung: warme Sommer, milde Winter, hohe Sonnenstunden, eigene
Konvektions­dynamik mit teils heftigen Gewittern aus der feuchten Suedluft
([MeteoSchweiz — Kraeftiges Gewitter im Tessin](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2023/05/kraeftiges-gewitter-im-tessin.html);
[meinklimaplan.ch](https://meinklimaplan.ch/romandie/das-klima-in-der-schweiz.html);
[planet-wissen — Tessin](https://www.planet-wissen.de/kultur/mitteleuropa/tessin/index.html)).
Bei Westlage von den Alpen geschuetzt — Wallis und Tessin sind die "Wetter­oasen"
bei NW-Stau-Lagen.

### Wallis
Inneralpines Trockental, **eines der trockensten Taeler Europas**
([SAC — Foehn/Westwind/Bise](https://www.sac-cas.ch/de/die-alpen/foehn-westwind-bise-und-co-der-wind-das-himmlische-kind-17548/);
[valais.ch](https://www.valais.ch/en/information/facts-and-figures);
[1815.ch — Walliser Wind](https://www.1815.ch/news/wallis/aktuell/stetig-blaest-der-wind-durchs-tal/)).
Lee-Lage bei Westlage (Berner Alpen schirmen ab) und Suedlage (Walliser Alpen
schirmen ab). Eigene Foehnsysteme (Lokalfoehn am Rhonetal). Talwinde sehr ausgepraegt
durch geringe Reibung im breiten Tal. Klima nahezu mediterran in der Talsohle.

### Engadin
Hochalpines Tal (1500-1800 m Talboden), inversions­anfaellig (Talnebel im Winter
sehr kalt), eigene Strahlungs­klimatologie. Maloja-Wind als Standard-Talwind.
Bei suedlicher Anstroemung leicht im Stau, bei nord­licher im Foehn.

### Mittelland
Talnebel-Hauptzone (siehe 1). Hauptachse fuer Bise. Konvektionspotenzial im
Sommer durch ausgepraegte Heating-Cycle, allerdings mit recht tiefer Basis
(starke Boden­feuchte). Mittelland-Konvergenz im Sommer: Konvergenzlinie zwischen
Jura-Talwind und Alpen­pumpe — anekdotisch wichtige Trigger­zone fuer Gewitter
und XC-Konvergenzen, aber nicht streng dokumentiert (Erfahrungs­wissen).

### Jura
Kurze, langgezogene Bergkette parallel zur Hauptwind­richtung — bei Westlage
**Frontalzone und Hangsoaring-Mekka**. Klassische Westwind-Soaring-Spots:
Chasseral, Crete du Vent, Vue-des-Alpes, La Doele, Mont Tendre. Bei Bise:
Ost­flanken-Soaring.

### Berner Oberland
Klassisch suedfoehn­anfaellig (Aaretal, Brienzersee, Haslital). Bei NW-Lage stark
nordstau­betroffen (Eiger-Nordwand-Wand bekommt Niederschlag, Lauterbrunnental
gestaut). Vielfaeltigste Lagen­dynamik der CH.

### Glarnerland / Linthtal
Klassischer Nordstau-Hotspot. Bei NW-Lage groesste Niederschlags­mengen der CH.

### Hochalpen
Strahlungs­dominiert, Schnee-Albedo (im Winter wenig Aufheizung der Boden­schicht),
eigene Konvektion ueber Gletschern (anekdotisch oft "Gletscherwind" — Hang­abwind
ueber Eis tagsueber). Im Sommer hohe, oft trockene Konvektion mit grosser Basis.

---

## 11. Saisonale Besonderheiten

### Fruehling (Maerz - Mai)
- Polarluft­vorstoesse noch haeufig, Konvektion baut sich auf, aber Mischungs­schichten
  sind tagsueber schnell hoch (Sonne hoch, Boden trocken).
- **Schneefall noch moeglich** bis weit ins Mittelland, Schneefall­grenze
  variabel.
- **Mai-Wintereinbrueche** ("Schafskaelte", Eisheilige um den 11.-15. Mai) sind
  klimatologisch dokumentiert (aber Datum nicht jedes Jahr passend).
- Klassische Foehnzeit (April/Mai sind nebst Oktober/November Foehn-Hochsaison —
  Druckkonstellation Tief Westen + Hoch Osten typisch).
- Bise-Wahrscheinlichkeit nimmt ab.

### Sommer (Juni - August)
- **Hitzewellen** moeglich (Saharaluft­vorstoesse, Omega-Lagen).
- **Schwergewitter** insbesondere am Alpennordrand, Voralpen, Jura, Tessin.
- **Vb-Lagen** mit grossem Hochwasser­risiko.
- Lange Tage, gute Konvektion. Talwinde tagesperiodisch stark.
- **Alpenpumpe** maximal aktiv.
- Sommer-Westlagen: Frontdurchgaenge mit kraeftiger Konvektion.

### Herbst (September - November)
- **Goldener Oktober**: stabile Hochdruck­lagen, klare Luft, Foehn-Hochsaison.
- Erste Hochnebel­tage (ab Mitte September).
- Vb-Lagen weiter moeglich.
- Konvektion nimmt ab (kuerzere Tage), aber dynamische Lagen koennen XC-traegliche
  Tage bringen.

### Winter (Dezember - Februar)
- **Hochnebel-Dauerlagen** im Mittelland (oft 5-10+ Tage am Stueck).
- **Bise-Hochsaison**.
- **Sued-Stroemung mit Schneefall** auf Alpennordseite (Vb oder einfaches
  Suedstau).
- Tagesgang sehr schwach, kaum Konvektion. Hangsoaring bleibt fliegbar bei
  passender Lage.

---

## 12. Massgebende Phaenomene fuer Piloten

### Hochnebelobergrenze
**Variabel** ueber den Tag (mittags ca. 100-200 m hoeher als am Morgen) und
ueber die Saison
([MeteoSchweiz — Hochnebelobergrenze](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2025/02/wie-verhaelt-sich-die-obergrenze-des-hochnebels.html)).
Typisch zwischen 700 und 1500 m im Winter. Wichtig zu kennen, weil Start­plaetze
**oberhalb** der Hochnebel­obergrenze gewaehlt werden sollten — sonst kein Sicht­flug.

### Mittelland-Stagnation
Bei Hochdruck mit Wind­schwaeche sammelt sich Luft (und Aerosole, Schadstoffe)
im "Becken" Mittelland — schlechte Sicht, oft Hochnebel, Inversionswetter
([MeteoSchweiz — Plateau fog hole](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/fog/swiss-plateau-fog-hole.html)).

### Konvergenzlinien
- **Mittelland-Konvergenz im Sommer**: Jura-Talwind trifft Alpen­pumpe — wo,
  ist tagesabhaengig, oft ueber Mittelland-Mitte. Trigger fuer Gewitter und
  XC-Auf­winde.
- **Tal-Pass-Konvergenzen**: zwei Talwind­strome treffen sich an einem Pass
  (Grimsel-, Bruenig-, Maloja-Pass).

### Talwinde namentlich
- **Joran**: Fallwind am Jurasuedfuss, oft bei Westlage mit Inversion, dann
  faellt kaelt-feuchte Luft aus dem Jura ins Mittelland und erzeugt SE-Wind
  am Neuenburger- und Bielersee
  ([Wikipedia — Joran](https://de.wikipedia.org/wiki/Joran);
  [SRF — Joran](https://www.srf.ch/meteo/meteo-news/joran-fallwind-am-jurasuedfuss-mit-ueberraschenden-gesichtern);
  [swisswetter — Joran](https://www.swisswetter.ch/Wissen/der-joran-ein-missbrauchter-name-fuer-einen-wind.html)).
- **Brisa del Mar / Vento del Lago**: thermisch getriebener Wind ueber Lago
  Maggiore und Luganersee.
- **Foehn-Familie**: Suedfoehn, Nordfoehn, Maloja-Wind, Lokalfoehn (Vispertal, etc.).
- **Brienzersee-Foehn, Walensee-Foehn, Urnersee-Foehn**: Foehn­varianten in
  spezifischen Seenlagen.

### Alpenpumpe
Tagesperiodische Konvergenz von der Mittellandluft Richtung Alpenkamm — schwacher
Nordwind im Mittelland am Nachmittag bei sonst gradient­armer Lage. Indikator
fuer gute Alpenthermik
([windinfo — Alpines Pumpen](https://www.windinfo.eu/alpines-pumpen/);
[SRF — Alpines Pumpen](https://www.srf.ch/meteo/meteo-stories/berg-und-talwind-das-taegliche-auf-und-ab-des-windes-in-den-alpen)).

### Stratusgrenze
Die Grenze zwischen Hochnebel und freiem Himmel. Im Winter oft scharf, mit
Sichthorizontwechsel innert weniger 100 Hoehenmeter.

### Cumulus-Stationaritaet und Tagesgang
Cumuli bilden sich typisch ab Mitte Vormittag (Sommer 09-10 Uhr lokal,
abhaengig von der Sonnenstellung und Inversion), erreichen Maximum am
spaeten Nachmittag (15-17 Uhr), loesen sich abends mit Einbruch der
Inversion auf. **Cumulus­stationaritaet** = Cumuli bleiben an einem Ort
"haengen" — typisch ueber Bergspitzen mit konstanter Thermik­quelle.

### Cap-, Lenticularis-, Rotorwolken
Drei stufige Foehn-Indikatoren (siehe 3 und 4).

### Gletscherwind
Hang­abwind ueber Gletschern auch tagsueber (Gletscher kuehlt boden­nahe Luft) —
anekdotisch wichtig fuer Hochalpen-Spots wie Aletsch, Jungfraujoch-Region.

---

## Kompakte Quellenliste

### MeteoSchweiz (offiziell)
- [Subsidenz](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/subsidence.html)
- [Inversion](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/inversion.html)
- [Swiss Plateau fog hole](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/fog/swiss-plateau-fog-hole.html)
- [Northern orographic effect (Nordstau)](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/northern-orographic-effect.html)
- [Bise](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/bise.html)
- [Westerly winds](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/westerly-winds.html)
- [Foehn](https://www.meteoswiss.admin.ch/home/climate/the-climate-of-switzerland/specialties-of-the-swiss-climate/foehn.html)
- [Valley and mountain winds](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/valley-and-mountain-winds.html)
- [Wind allgemein](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/wind.html)

### MeteoSchweiz-Blog (Beispiel-Eintraege)
- [Hochnebelobergrenze](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2025/02/wie-verhaelt-sich-die-obergrenze-des-hochnebels.html)
- [Blockierte Hochdrucklage](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2023/02/blockierte-hochdrucklage-in-sicht.html)
- [Starker Foehn in Alpentaelern](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2023/10/starker-foehn-in-den-alpentaelern.html)
- [Foehn in den Alpen](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2024/03/foehn-in-den-alpen.html)
- [Lehrbuch-Warmfront](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2022/12/lehrbuch-warmfront.html)
- [Winde der Alpen Teil 2](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2023/02/winde-der-alpen-und-europas-teil-2.html)
- [Talwinde](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2024/08/talwinde-oder-warum-es-in-den-alpen-auch-an-ruhigen-tagen-windig-ist.html)
- [Wenn die Bise weht](https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2026/04/wenn-die-bise-weht.html)

### Wikipedia DE
- [Foehn / Foehntheorie via DWD](https://dwd.de/DE/service/lexikon/begriffe/F/Foehn.html)
- [Bise (en)](https://en.wikipedia.org/wiki/Bise)
- [Mittelmeertief / Vb](https://de.wikipedia.org/wiki/Mittelmeertief)
- [Hochnebel in der Schweiz](https://de.wikipedia.org/wiki/Hochnebel_in_der_Schweiz)
- [Stau (Meteorologie)](https://de.wikipedia.org/wiki/Stau_(Meteorologie))
- [Berg- und Talwind-Zirkulation](https://de.wikipedia.org/wiki/Berg-_und_Talwind-Zirkulation)
- [Omegalage](https://de.wikipedia.org/wiki/Omegalage)
- [Lenticularis](https://de.wikipedia.org/wiki/Lenticularis)
- [Joran](https://de.wikipedia.org/wiki/Joran)
- [Sibirienhoch](https://de.wikipedia.org/wiki/Sibirienhoch)
- [Zyklogenese](https://de.wikipedia.org/wiki/Zyklogenese)

### DWD Glossar / Lexikon
- [Vb-Wetterlage](https://www.dwd.de/DE/service/lexikon/begriffe/V/Vb-Wetterlage.html)
- [Kaltlufttropfen](https://www.dwd.de/DE/service/lexikon/begriffe/K/Kaltlufttropfen_pdf.pdf)
- [Warmfront](https://www.dwd.de/DE/service/lexikon/Functions/glossar.html?lv3=103046)
- [Baroklinitaet](https://www.dwd.de/DE/service/lexikon/Functions/glossar.html?lv3=100376)
- [Luv-Lee-Effekt](https://www.dwd.de/DE/service/lexikon/Functions/glossar.html?lv3=101634)

### Pilotinfos / DHV / Spezialisten
- [DHV — Stau und Foehn](https://www.dhv.de/media/jahre/2024/07_wetter/Wetterwissen/DHVmagazin_Artikel/F%C3%B6hn/6_2011_172_stau_und_foehn.pdf)
- [DHV — Talwinde](https://www.dhv.de/media/jahre/2024/07_wetter/Wetterwissen/DHVmagazin_Artikel/Wind/10_2015_192_talwind.pdf)
- [SAC — Foehn/Westwind/Bise](https://www.sac-cas.ch/de/die-alpen/foehn-westwind-bise-und-co-der-wind-das-himmlische-kind-17548/)
- [windinfo — Alpines Pumpen](https://www.windinfo.eu/alpines-pumpen/)
- [windinfo — Kaltlufttropfen](https://www.windinfo.eu/kaltlufttropfen-der-schoenwetterverderber/)
- [Rheintalmeteo — Foehnprognose](https://www.rheintalmeteo.ch/prognosen/foehnprognose)
- [biseflueger.ch — Gantrisch-Region](https://biseflueger.ch/gantrischregion.html)
- [paraworld — XC-Routes](https://www.paraworld.ch/en/news-facts/school/xc-routes-in-spring/)
- [flieger.news — Foehn und Bise](https://www.flieger.news/foehn-und-bise-schweizer-wetterphaenomene/)

### Medien / Erklaer­artikel
- [SRF Meteo — Berg- und Talwind](https://www.srf.ch/meteo/meteo-stories/windzirkulation-in-den-alpen-wie-entstehen-berg-und-talwind)
- [SRF Meteo — Fiese Bise](https://www.srf.ch/meteo/meteo-stories/wind-im-mittelland-die-fiese-bise)
- [SRF Meteo — Eine Front kommt selten allein](https://www.srf.ch/meteo/meteo-stories/wetterwissen-eine-front-kommt-selten-allein)
- [SRF Meteo — Joran](https://www.srf.ch/meteo/meteo-news/joran-fallwind-am-jurasuedfuss-mit-ueberraschenden-gesichtern)
- [SRF Meteo — Alpines Pumpen](https://www.srf.ch/meteo/meteo-stories/berg-und-talwind-das-taegliche-auf-und-ab-des-windes-in-den-alpen)
- [MeteoNews — Vb-Tief](https://meteonews.ch/de/News/N14151/Was-ist-ein-Vb-Tief)
- [MeteoNews — Bise](https://meteonews.ch/de/News/N15011/Die-Bise_-ein-Schweizer-Spezialwind)
- [MeteoNews — Inversion](https://meteonews.ch/de/News/N15772/Inversion---verkehrte-Temperaturwelt)
- [swissinfo — Bise](https://www.swissinfo.ch/ger/ungewohnliche-schweiz/die-bise-ein-einzigartiges-schweizer-wetterph%C3%A4nomen/88834058)
- [Spektrum — Polarfront](https://www.spektrum.de/lexikon/geographie/polarfront/6105)
- [Spektrum — Barokline Wellen](https://www.spektrum.de/lexikon/geographie/barokline-wellen/723)
- [DMG — Lenticularis](https://www.dmg-ev.de/2020/04/19/lenticularis/)
- [DMG — Rotorwolken](https://www.dmg-ev.de/2000/03/08/rotorwolken/)
- [Unwetterzentrale — Omega-Lage](https://www.unwetterzentrale.de/uwz/365.html)

---

## Verwendungs­hinweise fuer den LLM (Halluzinations-Schutz)

1. **Niemals Lagen erfinden** — dieses Dokument liefert *Interpretation*,
   nicht *Detektion*. Welche Lage vorliegt, kommt deterministisch aus
   `engine/synoptic_context.py`.
2. **Keine erfundenen Zahlen** — die exakten hPa-Differenzen, Boengeschwindigkeiten
   etc. sind hier bewusst weich gehalten ("typisch ueber 1020 hPa", "stuermisch").
3. **Begriffliche Unschaerfen markieren** — wo das Wissen anekdotisch ist
   (z.B. exakte Bisenkluft, exakte Maloja-Wind-Abgrenzung), ist das im Text
   gekennzeichnet.
4. **Regionale Aussagen nur auf detektierte Region anwenden** — nicht "die Bise
   trifft das Genfersee-Gebiet" formulieren, wenn die Detektion keinen
   Genferseebezug hat.
5. **Saison-Hinweise nur bei plausiblem Datum verwenden** — Schafskaelte nur
   nahe Mai, Foehn-Hochsaison nur im Fruehling/Herbst.
