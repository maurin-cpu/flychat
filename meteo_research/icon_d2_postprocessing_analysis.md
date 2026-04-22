# Detaillierte Analyse: ICON-D2 Post-Processing & Die "Ghost Cloud" Problematik

Die meteorologische Vorhersage für den Flugsport basiert heute stark auf dem hochauflösenden **ICON-D2** Modell (2,2 km) des Deutschen Wetterdienstes (DWD). Es gibt jedoch fundamentale Unterschiede darin, wie generische Wetter-APIs (wie Open-Meteo) und spezialisierte Flugwetterservices (wie XC Therm und Burnair) diese Rohdaten aufbereiten.

Diese Diskrepanz äußert sich oft darin, dass Open-Meteo an thermisch guten Nachmittagen weiterhin dichte Schichtbewölkung oder Hochnebel anzeigt (z.B. am Balderen), während die Flugwetterdienste blauen Himmel oder leicht gebrochene Quellbewölkung (Cumuli) prognostizieren.

## 1. Die Wurzel des Problems: Relative Feuchte vs. Echte Wolken

**Das Open-Meteo "Ghost Cloud" Artefakt:**
Generische Wetter-APIs berechnen die Bewölkung trên Druckniveaus häufig durch einfache **Schwellenwert-Algorithmen der relativen Feuchtigkeit (RH)**. Übersteigt die relative Feuchte in einem Rasterpunkt ca. 85 %, geht der Algorithmus von Bewölkung aus. 

In der Realität (besonders in Alpentälern oder bei nächtlichen Inversionen) simuliert ICON-D2 oft korrekterweise hohe Feuchtigkeit in Bodennähe. Open-Meteo wandelt diese Feuchtigkeits-Blase fälschlicherweise in eine dichte, tiefe Wolkenschicht (100% `Low Cloud Cover`) um, obwohl der Himmel längst aufgerissen ist. Diese nicht existierenden "Geisterwolken" ruinieren die Streckenflugprognose.

## 2. Wie Profi-Dienste (XC Therm / Burnair) die Daten veredeln

Anbieter wie XC Therm und Burnair übernehmen die rohen RH- oder `CLCL` (Low Cloud Cover) Werte nicht blind, sondern nutzen fortschrittliches Post-Processing:

### A. Modifizierte GRIB2-Parameter (`CLCT_MOD` und `CLDEPTH`)
Statt generischer Abfragen nutzen Flugwetter-Apps spezifische DWD-Variablen:
*   **`CLCT_MOD` (Modified Cloud Cover):** Dieser Parameter ist eine optimierte Variante der Gesamtbewölkung, die Artefakte herausrechnet und visuell eher dem entspricht, was der Pilot vom Boden aus sieht.
*   **`CLDEPTH` (Cloud Depth):** Die vertikale Wolkenmächtigkeit. Ein harmloses morgendliches Nebelfeld hat eine geringe Mächtigkeit und wird bei Thermik rasch aufgelöst, während Open-Meteo es ohne Tiefenprüfung den ganzen Tag als "100% Low Cloud" mitschleift.

### B. Thermodynamische Konvektionsmodelle (Regtherm)
XC Therm nutzt das physikalische Konvektionsmodell *Regtherm*. Es nimmt das vertikale Temperatur- und Feuchteprofil des ICON-D2 und rechnet die Thermikaktivität komplett neu. Regtherm simuliert den adiabatischen Aufstieg (ca. 1°C/100m Abkühlung) von Luftpaketen.
*   **Schatten-Feedback:** Das Modell berechnet Cumulo-Bewölkung (Basis und Mächtigkeit) dynamisch aus der aufsteigenden Luft.
*   Ist die Thermik stark, durchmischt (Entrainment) das Modell die Grundschicht, bricht tiefe Inversionen auf und "brennt" statische Hochnebel/Ghost-Clouds weg. Die rohe Feuchtigkeitsangabe des Basismodells verliert an Relevanz.

### C. Topographische Segmentierung ("Homogene Regionen" & 120m Raster)
*   **XC Therm (Regionen):** Die Welt wird nicht in starre 2,2-km-Gitterpunkte eingeteilt, sondern in über 1.300 homogene, topographische Regionen (z.B. "Östliches Mittelland"). Das mittelt extreme Feuchtigkeits-Cluster (wie jene über Seebecken) heraus, die bei einer exakten GPS-Punktabfrage die Prognose verfälschen würden.
*   **Burnair (120m Intersektion):** Burnair verschneidet das 2,2-km-Modell mit einem 120-Meter-Geländeraster. Nur so kann erkannt werden, ob eine berechnete Wolkenbasis wirklich *im Gelände hängt* oder weit darüber liegt.

### D. Bias-Korrektur (MOSMIX)
Spezialisierte Dienste nutzen oft statistisch veredelte Daten (z.B. *MOSMIX* vom DWD), um systematische Bias-Fehler von Modellen (wie das ständige Überschätzen von Wolken in Tal X) durch historische Stationsdaten auszugleichen.

---

## 3. Strategie für Gleitcast: Der "Smart Burn-Off" Workaround

In Gleitcast beziehen wir unsere Daten von der Open-Meteo API. Um das "Ghost-Cloud"-Problem zu beheben und uns qualitativ an XC Therm/Burnair anzugleichen, implementieren wir ein künstliches Post-Processing in Python (Datei: `fetch_weather.py`), welches zwei Konzepte nachstellt:

1.  **Topographische Glättung (Regional Averaging):** Anstatt einen einzigen GPS-Punkt abzufragen (der für den Balderen genau über dem feuchten Zürichsee im Gitter liegen kann), rufen wir ein 3-Punkte-Raster im Umkreis ab und bilden den Mittelwert der Wolkendichte.
2.  **Inversionsbruch & Thermik-Filter:** Wir überprüfen die thermische Komponente über `thermik_calculator.py` und den GFS-Parameter `boundary_layer_height` (Grenzschichthöhe). Wenn:
    *   Starke Thermik herrscht (`climb_rate > 1.0 m/s`) **und**
    *   Die Modellgrenzschicht stark ansteigt (`boundary_layer_height > 1000m`),
    ...dann wissen wir physikalisch, dass die Inversion zerrissen ist. Eventuell noch vorhandene "Low Clouds" (häufig Ghost Clouds) werden algorithmisch proportional auf Null reduziert.
