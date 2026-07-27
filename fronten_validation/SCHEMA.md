# Schema — `observations.csv`

Eine Zeile = **ein von uns vorhergesagter Frontdurchgang** durch eine Zone,
plus das, was eingetreten ist. Zeilen entstehen automatisch aus den
Aussage-Schnappschüssen (`aussagen/`); die Verifikations-Spalten füllt der
Abgleich gegen die spätere Handanalyse, das Urteil kann ein Mensch überschreiben.

Leer bedeutet **nicht geprüft**, nicht „kein Befund". Wichtig für jede
Auswertung: nur Zeilen mit gefülltem `verdict` zählen.

## Vorhersage-Seite (aus unserer Ableitung)

| Spalte | Bedeutung |
|---|---|
| `lauf` | Modelllauf, `YYYYMMDDHHMM` (bisher immer 00 UTC) |
| `stand` | Kalendertag, an dem wir die Aussage getroffen haben (`YYYYMMDD`). Zusammen mit `lauf` eindeutig — dieselbe Zielzeit wird an mehreren Tagen neu beurteilt, das ist der **Lauf-Jitter** |
| `zone` | `alpennordhang`, `wallis`, `tessin`, `graubuenden_engadin` |
| `typ` | `kalt`, `warm`, `okklusion`, `trog` |
| `art` | `quert` (≥ 10 % der Zonen-Spots betroffen) oder `streift` (darunter) |
| `median_utc` | Durchgang am mittleren betroffenen Spot |
| `fenster_von_utc`, `fenster_bis_utc` | 10-/90-Perzentil über die Spots = Zeit, die die Front für die Zone braucht |
| `spots_betroffen`, `spots_zone`, `anteil` | Betroffenheit; `anteil` entscheidet über `art` |
| `seitlich_km` | Abstand der Front quer zur Zugrichtung beim Passieren. Gross = eher Streifschuss |
| `stuetzweite_h` | Abstand der beiden Stützpunkte (12 oder 24 h). Die Interpolations-Unschärfe ist die Hälfte davon |
| `randwert` | `1` = Zeitpunkt liegt in den äussersten 10 % des Stützintervalls; der wahre Durchgang kann **davor** liegen, also ausserhalb des Betrachtungsfensters |
| `vorlauf_h` | Vorlaufzeit der Karte, aus der die Aussage stammt — die Trennlinie zwischen „morgen" und „übermorgen" |

## Verifikations-Seite (aus der späteren Ist-Lage)

Gefüllt von `scripts/validate_fronten.py` (Plan §6 Schritt 5). Alles, was der
Automat schreibt, trägt in `notes` das Präfix **`auto:`** — Zeilen ohne dieses
Präfix sind Handurteile und werden **nie** überschrieben.

| Spalte | Bedeutung |
|---|---|
| `ana_gueltig_utc` | Handanalyse(n), gegen die verglichen wurde — als Paar `von/bis` der beiden Stützpunkte, zwischen denen der Ist-Durchgang liegt |
| `ana_front_da` | `1` = zur erwarteten Zeit lag eine Front des Typs in/an der Zone, `0` = keine |
| `ana_median_utc` | aus den Analysen abgeleiteter tatsächlicher Durchgang, falls bestimmbar |
| `delta_h` | `ana_median_utc − median_utc` in Stunden. **Negativ = wir waren zu spät, positiv = zu früh.** Das Vorzeichen ist die Kernzahl: eine systematische Schieflage zeigt sich hier |
| `bulletin` | Kurzzitat aus dem `SXDL31`-Klartext des DWD-Meteorologen zur Lage — der unabhängige semantische Gegencheck |
| `verdict` | `getroffen` / `zu_frueh` / `zu_spaet` / `keine_front` / `verpasst` / `unklar` |
| `finding_type` | Verweis auf `PATTERNS.md`, z. B. `F-001` |
| `notes` | Freitext |

## Urteils-Konventionen

- `getroffen`: Front war da, `|delta_h|` ≤ **Toleranz**. Innerhalb der
  ausgewiesenen Unschärfe zu liegen ist der Anspruch — nicht die Punktlandung.
- `zu_frueh` / `zu_spaet`: Front war da, aber ausserhalb der Toleranz.
- `keine_front`: wir sagten einen Durchgang an, die Ist-Lage zeigt keinen.
  Der teuerste Fehler — er erzeugt eine Warnung ohne Anlass. Wird **nur**
  vergeben, wenn die Analysen den ganzen Suchraum (±24 h) abdecken; sonst
  bleibt die Zeile leer, weil ein Nicht-Fund ohne Abdeckung keine Information
  ist, sondern eine Lücke.
- `verpasst`: **nicht** aus unseren Zeilen erzeugbar, weil hier nur
  Vorhersagen stehen. Solche Fälle kommen aus dem Gegenlauf über die Analysen
  und werden mit leerer Vorhersage-Seite eingetragen — aber nur für Zeitpunkte,
  die ein Aussage-Schnappschuss überhaupt abgedeckt hat. Was vor dem
  Archivbeginn lag, ist keine verpasste Front, sondern eine Zeit ohne Betrieb.
- `unklar`: Stützpunkte reichen nicht (`randwert = 1` **und** kein Ist-Durchgang
  gefunden, Front am Kartenrand, Typwechsel entlang der Linie).

**Die Toleranz** ist die halbe Stützweite der Vorhersage **plus** die halbe der
Analyse-Kette — in der Regel 6 h + 6 h = 12 h. Der Zusatz ist keine Grosszügigkeit
gegen uns selbst: der Schiedsrichter erscheint nur alle 12 h und ist damit selbst
unscharf. Eine engere Toleranz würde eine Genauigkeit behaupten, die die
Ist-Seite nicht hat. Wer strenger urteilen will, überschreibt `verdict` von Hand
— das gilt dann als Handurteil und bleibt stehen.

Der Suchradius um eine Ansage beträgt **±24 h**: darüber hinaus ist es nicht
mehr dasselbe Ereignis, sondern die nächste Front.

## Die 0-Front-Regel

Analog zur 0-Launch-Regel bei XContest: **„keine Front gemeldet" ist an
stabilen Hochdrucklagen die richtige Antwort, kein Versagen.** Frontfreie Tage
erzeugen deshalb gar keine Zeile. Jede Trefferquote aus dieser Tabelle gilt nur
für Tage, an denen wir etwas behauptet haben — sie ist keine Aussage darüber,
wie oft wir eine Front übersehen. Dafür braucht es den Gegenlauf über die
Analysen (`verpasst`).
