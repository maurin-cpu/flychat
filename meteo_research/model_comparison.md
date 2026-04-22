# Umfassender Vergleich von Wettermodellen für das Gleitschirmfliegen

Diese Forschungsarbeit analysiert, welche Wettermodelle in der Gleitschirmfliegerei (insbesondere für Thermik- und Streckenflugprognosen) als Standard gelten, wie sich Modelle wie ICON-D2, ICON-CH1 und AROME unterscheiden und was die beste Wahl für das *Gleitcast*-Projekt ist.

---

## 1. Die Hauptakteure (Modelle) im Überblick

Für Gleitschirmflieger ist die räumliche Auflösung eines Modells entscheidend, da Thermik, Talwinde und Leeeffekte extrem lokal auftreten.

### AROME (Météo-France)
*   **Auflösung:** 1.3 km bis 2.5 km
*   **Abdeckung:** Fokus auf Frankreich und angrenzende Alpen-/Europa-Teile.
*   **Stärken:** Extrem gut in der Vorhersage lokaler Windsysteme und thermischer Entwicklungen in komplexem Gelände. Gilt in den französischen Alpen als absoluter "Goldstandard".
*   **Zeitraum:** Kurzfristmodell (bis ca. 48 Stunden).

### ICON-D2 (Deutscher Wetterdienst - DWD)
*   **Auflösung:** ~2.2 km
*   **Abdeckung:** Mitteleuropa (DACH-Region).
*   **Stärken:** Industriestandard für den deutschsprachigen Alpenraum. Hervorragend kalibriert auf bodennahe Winde, Wolkenbildung (Konvektion) und Niederschlag. Extrem hohe Assimilationsrate von Live-Daten (Radar/Flugzeuge).
*   **Zeitraum:** Kurzfristmodell (bis 48 Stunden).

### ICON-CH1 / ICON-CH2 (MeteoSchweiz)
*   **Auflösung:** ~1.0 km (CH1) / ~2.1 km (CH2)
*   **Abdeckung:** Schweiz und direkter Alpenbogen.
*   **Stärken:** Weltweit führende mikro-topografische Auflösung (1 km). Perfekt, um Talwindsysteme, Venturi-Effekte an Pässen und exakte Föhndurchbrüche in sehr engen Alpentälern zu berechnen.
*   **Zeitraum:** Bis zu 5 Tage Vorhersage.

### Globale Modelle (ECMWF, GFS, ICON-Global)
*   **Auflösung:** ~9 km (ECMWF) bis 13 km (GFS).
*   **Einsatz:** Zu grob für verlässliche lokale Thermik- und Windprognosen am Startplatz. Werden von Piloten nur für die grobe synoptische Wetterlage (Grosswetterlage) und Langfristplanung (Tage 3 bis 14) genutzt.

---

## 2. Warum nutzen Burnair und XC Therm das ICON-D2 (und ICON-EU)?

Führende Plattformen für Gleitschirmflieger nutzen tief im Maschinenraum primär Modelle des DWD (ICON-D2 und das etwas gröbere ICON-EU mit 7km Auflösung), oft bereichert durch eigene Algorithmen (z. B. "Recterm" bei XC Therm oder das "wachende Auge" bei Burnair).

**Warum wird oft das 2.2 km (ICON-D2) dem 1.0 km (ICON-CH1) vorgezogen?**

1.  **Das Problem der "Über-Auflösung" (Hyperformulierung):**
    Bei einer extremen Auflösung von 1 km (ICON-CH1) versucht das Modell, winzige geographische Features zu berechnen. Dies führt bei der Simulation von Feuchtigkeit in den bodennahen Schichten häufig dazu, dass das Modell Nässe/Wolken in kleinen Tälern "einsperrt". Das Resultat ist ein **Over-Forecasting von Low-Clouds (Hochnebel)**. Das Modell löst den Nebel/die Wolken viel langsamer auf, als es in der Realität passiert (genau dieses Problem haben wir am 12.03. für den Balderen gesehen, wo ICON-CH1 80% Wolken zeigte, während Burnair/SRF längst Sonne prognostizierten).
    
2.  **Optimierung auf Konvektion (Thermik):**
    Das ICON-D2 Modell ist durch den DWD über Jahre extrem stark auf die Kurzfrist-Konvektion (Quellwolken, Thermik, Gewitterzellen) optimiert worden. Die 2.2 km Gitterboxen "glätten" Mikrostörungen leicht aus (Smoothing), was für das *Makrophänomen Thermik/Streckenflugwetter* paradoyxerweise oft ein stabileres und verlässlicheres Vorhersagebild liefert als die "nervöse" 1-km-Berechnung.

3.  **Assimilation & Vorlauf:**
    Der DWD assimiliert für das ICON-D2 unfassbar viele Live-Daten in hoher Frequenz. XC Therm und Burnair profitieren davon, dass das Modell alle 3 Stunden einen sehr detaillierten Kurzfristblick in die Zukunft wirft.

---

## 3. Schlussfolgerungen und Empfehlung für Gleitcast

Aktuell nutzt *Gleitcast* das `meteoswiss_icon_ch1` via Open-Meteo. 

**Erkenntnisse für unsere Architektur:**
1. Für dedizierte Analysen von Talwind-Engpässen oder komplexem Föhn (z.B. Reusstal) ist ICON-CH1 unschlagbar.
2. Für die **Thermikberechnung** (Einstrahlung, Labilität, Wolkenbasis) sowie die **Allgemeinbewölkung** (Sonne vs. Hochnebel) ist das ICON-CH1 oft "zu pessimistisch" und hält zu lange an Restfeuchte fest.
3. Der Branchenstandard für Apps, die Flieger durch den Tag navigieren, ist **ICON-D2** (oft ergänzt durch AROME im Westen).

### Empfehlung für die Umsetzung

Wir sollten die Kern-Wetterdatenbeschaffung in Gleitcast auf **ICON-D2** umstellen.

**Begründung:** 
Das Ziel von Gleitcast ist es, dem Piloten verlässliche Aussagen über Thermik, Wolken und grundsätzliche Fliegbarkeit zu geben. Das ICON-D2 Modell ist dafür erwiesenermaßen der "Sweet Spot" aus hoher Auflösung (2.2 km) und physikalischer Stabilität (weniger "Fehlalarme" bei Restbewölkung). Open-Meteo bietet `icon_d2` als vollwertige API-Alternative an. 

**(Optionaler Zusatz:)** 
Sollten wir später feststellen, dass wir für Föhn-Warnungen an spezifischen Spots (z.B. Brunnihütte) doch die 1km-Genauigkeit brauchen, könnten wir in Zukunft ein "Hybrid-System" bauen: ICON-D2 für Strahlung/Thermik/Wolken und ICON-CH1 *nur* für den Bodenwind. Für den ersten Schritt empfehle ich jedoch einen klaren Wechsel auf ICON-D2, um das "Balderen-Problem" (und ähnliche) sofort zu lösen und eine Datenkonsistenz mit beliebten Tools wie Burnair zu erreichen.
