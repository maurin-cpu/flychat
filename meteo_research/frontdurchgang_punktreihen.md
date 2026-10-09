# Frontdurchgang in Punkt-Zeitreihen — Literatur und Folgerungen

Stand 09.10.2026. Anlass: `detect_frontsignatur` hat die Kaltfront vom
08.10.2026 verworfen. Laut SwissMetNet war sie eindeutig: Zürich und Bern
hatten das Druckminimum um 08 h, danach stieg der Druck um rund 11 hPa, es
fielen 16–23 mm Regen. Seit Einführung (~18.09.) hat der Detektor an keinem
Fokustag eine Front erkannt.

Kennzeichnung: **[L]** = Zahl aus der Literatur · **[Q]** = Literatur, nur
qualitativ · **[F]** = Faustregel/Praxis · **[A]** = eigene Ableitung,
nicht belegt.

## 1. Fronttypen und ihre Signatur

| Fronttyp | Druck | Wind (Boden / 850–700 hPa) | Temperatur / Taupunkt / θe | Niederschlag |
|---|---|---|---|---|
| Kaltfront, klassisch | Fall, V-Trog, rascher Anstieg. Oklahoma: Median +1.5 hPa [L]. Starke Fronten: ≥3 hPa und ≥7 K in 2–3 h [L] (Shafer & Steenburgh 2008). Alpenrand (GFE87): 1.8 hPa in 4 min [L] (Hoinka & Volkert 1992) | Rechtsdrehung SW→W/NW. Windsprung und Trog oft vor dem Temperatursturz [L] (Schultz 2005) | T, Td und θe fallen. Alpenrand: θe −9 K in <1 h [L] | an der Front, danach Aufklaren |
| Anafront | Knick weich | 700-hPa-Front ca. 300 km hinter der Bodenfront [L] (Pacey et al. 2023), also 4–8 h später [A] | Abkühlung in der Höhe verzögert | lang, hinter der Bodenfront |
| Katafront / Split-Front / Höhenkaltfront | Bodentrog schwach | Höhenfront läuft voraus [Q]. Am Boden nur Windsprung [F] | Abkühlung nur in 1500–3000 m [F] | vor der Bodenfront, konvektiv |
| Warmfront | langsamer Fall über 12–24 h [F] | schwache Rechtsdrehung SE→SW | T, Td und θe steigen | Landregen vor der Front |
| Okklusion | Trog, Knick schwach | Rechtsdrehung | am Boden kaum Gegensatz, in der Höhe schon [Q] | gemischt |
| Sekundärkaltfront | zweiter, kleinerer Knick | weiterer Dreh, böig | T850 sinkt weiter | Schauer 100–500 km hinter der Front [F] |
| Maskierte Front | Anstieg und Dreh vorhanden | normal | am Boden keine Abkühlung (Inversion, Föhn). In GFE87 bei 2 von 4 Fronten [L] | Herbst und Winter |

## 2. Alpen

- Die Bodenfront wird am Nordrand gebremst, die Front in der Höhe zieht
  weiter [Q] (Hoinka et al. 1990). Boden- und 700-hPa-Signal liegen deshalb
  Stunden auseinander.
- Der Drucksprung ist 20–60 km nördlich des Alpenrands am stärksten, etwa
  3 hPa/h, inneralpin schwächer [L] (Freytag 1990).
- Präfrontaler Föhn erzeugt einen breiten Druckfall vor der Front [F]; im
  Föhngebiet fällt kein Niederschlag [L].
- Tessin (Kurz 1999) [L]: Der Druck fällt vor der Front, weil sich im Süden
  ein Tief bildet. Die Front zeigt sich als Taupunktsturz (Locarno 11 → −2 °C,
  T sogar +1 K) plus Nordwind. Danach kommt Nordföhn, Faustregel ab
  Lugano − Zürich < −4 hPa [F].
- Wallis/Graubünden: keine spezifische Literatur gefunden; analog Inntal
  schwächere Sprünge, Kanalisierung unterdrückt den Bodenwinddreh [F].

## 3. Objektive Kriterien aus der Literatur

| Methode | Kriterium | Fenster |
|---|---|---|
| Schemm et al. 2016 (COSMO, CH) | θe 700 hPa, Gradient > 6 K/100 km. 700 hPa „um Orographie zu vermeiden“ [L] | Gitter |
| Rüdisühli et al. 2020 | θe 850 hPa, Schwelle saisonal (Winter 4, Sommer 8 K/100 km). Front an den Alpen zurückgehalten und teils nicht erkannt [L] | Gitter |
| Simmonds et al. 2012 (punktweise) | 10-m-Wind dreht von SW- in NW-Quadrant, Nord-Süd-Komponente ändert sich > 2 m/s [L] | 6 h |
| Lesage & Krueger (Stationen) | Punktsumme aus T-Fall und Druckanstieg. Beides zu verlangen verpasst Fronten, weil die zwei nur schwach korrelieren [L] | Spitze in 4–6 h |
| Shafer & Steenburgh 2008 | ≥7 K in 2–3 h, ≥3 hPa — nur starke Fronten [L] | 2–3 h |
| Windsprung | ≥45° (ASOS). Präfrontale Sprünge bis 24 h vorher, bei bis zu 60 % der Fronten im Lee der Rockies [L] (Schultz 2005) | bis 24 h |

## 4. Folgerungen für unseren Detektor

1. Zeitfenster entkoppeln: Drehung und Abkühlung innerhalb von ~±12 h um das
   Druckminimum zulassen, nicht ±3 h [A].
2. Druck mehrskalig: Anstieg ≥3–4 hPa in 12 h statt ≥1.2 hPa in 3 h. Keine
   Pflicht „Fall direkt vor dem Minimum“ [A, kalibrieren].
3. Thermik der Luftmasse als Hauptkriterium: T bzw. θe auf 850/700 hPa fällt
   über 6–12 h. Das Vorzeichen grenzt Warmfronten aus.
4. Wind nach Simmonds: Quadrantenwechsel SW→NW auf 850/700 hPa.
5. Regen nur bestätigend, nie Pflicht (Katafront, Föhn).
6. Tessin eigene Logik: Druckdifferenz Nord−Süd kippt, Taupunkt fällt,
   Nordwind. Temperatur darf steigen.
7. Erst pro Region erkennen, dann über die Zone abstimmen. Der Median über die
   Regionen glättet zeitversetzte Durchgänge weg.
8. Gegen SwissMetNet prüfen und pro Fall protokollieren, welche Bedingung
   gescheitert ist.

## 5. Abgleich mit unserem Fall 08.10. (ICON-D2-Rückblick, Alpennordhang)

Druckminimum 08 h, danach +13 hPa bis 20 h. 700-hPa-Wind 225° → 349° über
13 h. T850 9.9 → 3.8 °C über den Tag. Regen ab 07 h. Mit den Folgerungen
1–3 wäre die Front erkannt worden. Verworfen wurde sie an der Pflicht
„≥0.3 hPa Fall in den 3 h vor dem Minimum“: Der Fall betrug −0.2 hPa, weil
der Druck langsam über die ganze Nacht gefallen war.

## Datenlücke

Feuchte auf Druckflächen (für θe 850/700) holen wir heute nicht ab. Es gibt
nur T, Wind und Geopotential. Am Boden ist der Taupunkt aus T2m und RH2m
berechenbar.

## Quellen

Shafer & Steenburgh 2008 (MWR) · Hoinka & Volkert 1992 (DLR elib 31589) ·
Hoinka et al. 1990 (DLR elib 53402) · Schultz 2005 (prefrontal troughs) ·
Pacey et al. 2023 (NHESS 23, 3703) · Schemm et al. 2015/2016 ·
Rüdisühli et al. 2020 (WCD 1, 675) · Rudeva & Simmonds 2015 ·
Lesage & Krueger (Utah) · Kurz 1999 (KIT, Cyclogenesis-Alps) · EUMeTrain
SatManu (Kaltfront, Okklusion, Front Modification) · Steenburgh, Vorlesung
Front-Mountain Interactions · DHV-Magazin Bodendruck/Fronten · Sansom &
Catto 2024 (GMD 17, 6137). Nicht im Volltext gelesen: Egger & Hoinka 1992,
Jenkner et al. 2010, Sinclair (Helsinki).

## 6. Warmfront-Prüfung gegen SwissMetNet (09.10.2026)

**Basis.** Alle Tage vom 28.07. bis 18.09., an denen die DWD-Prognose
morgens eine Warmfront oder Okklusion für eine Zone nannte.

**Modell.** Die Zeichen kommen aus `detect_frontsignatur` auf dem
ICON-D2-Rückblick. Gelesen werden sie mit `front_zeichen_passend(typ="warm")`.

**Messung.** Was als „Warmluft angekommen“ zählt:

- Erwärmung an der Bergstation (Napf/Pilatus, Montana, Cimetta, Davos/Samedan)
  um mindestens 3 K gegenüber derselben Stunde am Vortag,
- **oder** Druckfall im Tal von mindestens 4 hPa in 12 h.

**Ergebnis.** Ausgewertet wurden 32 Zonen-Tage mit reiner Warmfront oder
Okklusion. Tage, an denen der DWD zugleich eine Kaltfront nannte, sind
ausgenommen.

| | Anzahl | Davon richtig |
|---|---|---|
| Warmluft gemessen | 16 | 12 Zeichen sichtbar (75 %) |
| Keine Warmluft gemessen | 16 | 11 ohne Zeichen |

- **„Deutliche Zeichen“:** 5 von 5 durch die Messung bestätigt.
- **Fehlsignale:** 3 Fälle mit falscher Erwärmung (25.08. Tessin, 25.08.
  Wallis, 29.08. Graubünden). Alle drei waren nur „schwach“. Dazu kommen
  2 Fälle, die nur wegen Regen „schwach“ wurden; der Regen war real.
- **Verpasst:** 4 Fälle (02.08. Wallis, 11.08. Alpennordhang, 26.08. Tessin,
  29.08. Tessin). Am 24.08. lag die Modell-T850 im Tessin und im Wallis in
  der falschen Richtung. Der Druckfall hat den Fall dort trotzdem getragen.
- **DWD-Warmfronten sind oft nicht angekommen.** Bei der Hälfte der genannten
  Warmfronten maß keine Station Erwärmung oder Druckfall. „Keine Zeichen“ ist
  dann die richtige Aussage.
- **Schwachstelle:** Tessin. 2 der 4 verpassten Fälle liegen dort.

**Grenze der Prüfung.** Die Bergstationen sind nur ein Ersatz für 850 hPa:
Sonne am Gipfel erwärmt mit. Die Schwellen bleiben deshalb unverändert.
