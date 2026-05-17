# Arbeitshoehe (working_height_agl) — Schwellenwerte fuer Tag-Charakter

**Status:** Recherche-Synthese aus Pilotenliteratur (xcmag, Burnair, CH-Berichte)
**Zweck:** Quantitative Grundlage fuer AGL-Schwellen im Spot- und Region-Rating
**Scope:** Median nutzbare Steighoehe ueber Startplatz als Charakter-Indikator
(lokal vs. XC vs. Klassiker), NICHT als Staerke-Indikator

---

## 1. Wichtige Einschraenkung vorweg

Es existiert **keine offizielle SHV-/DHV-Tabelle** mit AGL-Schwellen fuer
XC-Tauglichkeit. Die unten genannten Werte stammen aus:

- **xcmag** (Cross Country Magazine) — Bob Drury "Golden Rules" mit
  konkreten Hoehenangaben (2000ft = 650m als "Decision Point").
- **burnair.ch** — Schule-Artikel "Dein erster 50km Streckenflug" mit
  AGL-Range "marginal" bis "nicht besonders hoch".
- **paraworld.ch / chilloutparagliding** — qualitativ.
- **Erfahrungsabgleich** mit CH-Spot-Tagen (Balderen/Mittelland-Beispiele).

Belastbar **sind**: die 450m / 650m / 1300m / 1700m Stuetzpunkte.
**Inferenz** (nicht direkt zitiert) sind die Bandgrenzen 400 / 800 / 1500 / 2000.

---

## 2. Quellen-Tabelle mit konkreten Zahlen

| Quelle | AGL-Wert | Originalzitat / Bedeutung |
|---|---|---|
| xcmag, Drury — Golden Rules | **450m** (1500ft) | "Low down, thermals are rough... at about 1500 ft you ought to be rewarded with a smoother, more pleasant climb." → Komfort-Schwelle |
| xcmag, Drury — Golden Rules | **650m** (2000ft) | "When you start getting below 2000 ft (650m) agl, start looking for thermal sources or soarable ridges." → Decision Point |
| xcmag, Drury — Golden Rules | "a few hundred ft" | "desperate XC fliers will work anything" → Survival/Bailout |
| burnair.ch — Erster 50km | **1300m** | "Basis 1300m AGL als marginal" → fuer 50km XC knapp |
| burnair.ch — Erster 50km | **1700m** | "1700m als nicht besonders hoch" → ok fuer 50km, nicht XC-Standard |
| xcmag — Damien de Baenst 193km | Basis 2000m / "1000m unter dem normalerweise Noetigen" | impliziert Standard-Hammertag-Basis ~3000m → ~1500-2500m AGL je nach Spot |
| Swiss Airspace G/E | 600m AGL | Regulatorischer Decken-Wert, **kein** XC-Indikator |

---

## 3. Abgeleitete AGL-Baender (Synthese)

| AGL-Band | Pilotengefuehl | Konsequenz fuer Tag-Charakter |
|---|---|---|
| **< 400m** | "Bailout-Modus, raue Thermik, Hike-Back-Risiko" | sehr tief gedeckelt, keine Hausrunde sicher |
| **400 - 800m** | Hausrundentag, Soaring + kurze Thermikkreise, Decision-Point-Naehe | Lokal-Flug ok, kein XC-Anspruch |
| **800 - 1500m** | "Lokal-XC offen, 30-80km drin" | echtes Streckenfliegen wird moeglich |
| **1500 - 2000m** | "XC-Gelaende offen, 50-100km" | substanzieller XC-Tag, Burnair "nicht besonders hoch" als obere Grenze |
| **> 2000m** | "Klassiker-Territorium, 100km+" | Big-Day-Standard (~3000m Basis) |

**Begruendung der Grenzen:**

- **400m** statt 600m: 450m ist die Drury-Komfortschwelle. Darunter "raue
  Thermik" — also genau die "tief-gedeckelt"-Definition. 600m war zu
  großzuegig und schloss Hausrundentage faelschlich aus.
- **800m** statt 1200m: Drury's 650m Decision-Point ist die Untergrenze
  fuer aktives Suchen — sobald man drueber bleibt (800m+), ist Lokal-XC
  realistisch. 1200m war zu hoch fuer den Lokal-XC-Einstieg.
- **1500m** statt unverändert: Burnair-marginal liegt bei 1300m fuer 50km.
  Bei 1500m ist man komfortabel im XC-Gelaende — runde Schwelle.
- **2000m** unverändert: Burnair "nicht besonders hoch" → drueber faengt
  echtes Klassiker-Potential an. Big-Day-Inferenz ~1500-2500m AGL passt.

---

## 4. Tier-Relativitaet (Wichtig!)

Diese AGL-Schwellen gelten fuer **Mittelland/Voralpen**. In Hochalpin-Regionen
sind sie systematisch zu streng:

| Tier | Spot-Hoehe typisch | Basis Standard (MSL) | AGL Standard |
|---|---|---|---|
| Mittelland | 600-900m | 1700m | ~1000m |
| Jura | 900-1300m | 2000m | ~800m |
| Voralpen | 1200-1700m | 2300m | ~800m |
| Alpen | 1500-2200m | 2800m | ~800-1200m |
| Hochalpin | 1800-2400m | 3500m | **~1400m** = Standard, nicht "lokal"! |

**Konsequenz:** Hochalpin-Spot mit 1400m AGL ist ein **normaler**
Sommertag — nicht "Lokal-XC". Die Rating-Skills muessen das
qualitativ adressieren ("AGL tier-relativ lesen"). Eine harte
tier-abhaengige Schwellen-Tabelle wurde verworfen, weil die Anzahl
Sonderfaelle das LLM-Urteil schwaecht.

---

## 5. Was Recherche NICHT belastbar ergab

- **Konkrete Schwellen aus SHV/DHV-Lehrbuch**: nicht gefunden, vermutlich
  bewusst nicht standardisiert (Pilotenurteil-Kultur).
- **Burnair PFD-Werte als AGL-Mapping**: PFD ist Multi-Parameter, keine
  AGL-Ableitung publiziert.
- **xcontest-Statistiken zu Basis vs. Streckenlaenge**: existieren als
  Datensatz, aber nicht oeffentlich auf-bereitet.

---

## 6. Anwendung in Skills

### Spot-Rating (`04_flight_subratings_spot.md`)

```
- < 400m AGL    — sehr tief gedeckelt, Hausrunde nur mit Glueck
- 400-800m AGL  — Hausrundentag, Soaring + kurze Kreise
- 800-1500m AGL — Lokal-XC offen (30-80km drin)
- > 1500m AGL   — echtes XC-Gelaende, ab 2000m Klassiker-Territorium
```

### Region-Rating (`04_flight_subratings_region.md`)

Identische Schwellen, aber: Region-Werte sind hoeher (regionaler Median
vs. Spot-Bergstart). Falls Region 1500m AGL Median hat → tatsaechlich
"XC-Gelaende offen" auch fuer durchschnittlich tieferen Spot der Region.

### Wichtig (gilt fuer beide)

- Schwellen **nicht** als harte Cut-offs anwenden — Pilotenurteil zaehlt.
- Tier-Relativitaet im Text erwaehnen ("Hochalpin 1400m AGL = Standard").
- AGL beeinflusst v.a. `streckenflug.rating`, nicht primaer
  `experience_rating` (Peak setzt den Rahmen).

---

## 7. Quellenliste

- [xcmag — The golden rules (Drury)](https://xcmag.com/news/mirror-mirror/)
- [xcmag — Cloudbase: All you need to know](https://xcmag.com/fly-better/paragliding-techniques-paramotoring-skills/cloudbase-all-you-need-to-know/)
- [burnair — Dein erster 50km Streckenflug](https://www.burnair.ch/2022/04/25/dein-erster-50-km-streckenflug-in-der-schweiz/)
- [paraworld.ch — XC Routes for Beginners](https://www.paraworld.ch/en/news-facts/school/xc-routes-for-beginners/)
- [paragliding24.ch — Swiss Airspace](https://paragliding24.ch/en/blogs/blog/swiss-airspace-classes-overview-and-rules)
- Querverweis: `meteo_research/cloudbase_terrain_tiers.md` (Basis-MSL pro Tier)
