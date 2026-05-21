# Regionale Referenzpunkte — Liste

Vollständige Liste der **7 empfohlenen Referenzpunkte pro Region** (29 Regionen).
Die meteorologische Logik dahinter (Aggregation, Platzierungsregeln, 5 Funktionen)
steht in `docs/REFPOINT_KONZEPT.md`.

## Zweck dieses Dokuments

Pro Region sind unten 7 konkrete Referenzpunkte mit Koordinaten und **Funktion**
gelistet. Jeder Punkt liegt garantiert innerhalb des Region-Polygons (validiert
gegen `data/regionen_polygone_mapped.geojson`).

**Punkt-Funktionen** (heuristisch nach Position im Polygon):

- **Flughöhe-S** — südlichster Punkt, deckt Hauptthermik-Konvektion ab
- **Edge-S** — südliche Polygon-Kante (Föhn-Lee bei S-Föhn-Regionen)
- **Edge-N (Schatten)** — nördliche Polygon-Kante (N-Exposition, Blue-Hole-Detektor)
- **Edge-O / Edge-W** — östliche/westliche Polygon-Kanten (Edge-Effekte, Talwind)
- **Innen-Sample** — interior-Punkt (>25 % von Bounding-Box-Kante entfernt) für Wolkenlücken

Die meteorologischen Funktionen werden bei der Daten-Aggregation nicht explizit
genutzt — sie helfen, die geographische Abdeckung intuitiv zu verstehen.

Basis: 7 Punkte pro Region aus `data/regionen_referenzpunkte.geojson` (4 Legacy-Edge-
Anker + 3 CVT-Innen-Punkte), bei vorhandenem validierten S-Anker (siehe S_ANCHORS-
Dict in `scripts/_write_refpoint_liste.py`) wird der südlichste auto-gen Punkt durch
den S-Anker ersetzt, sofern dieser innerhalb des Polygons liegt.

---

## Region-Index

| # | Region | Terrain | Föhn | S-Anker |
|---|---|---|---|---|
| 1 | [seeland_emmental](#1-seeland_emmental) | mittelland | Süd | ✓ |
| 2 | [mittelland_west](#2-mittelland_west) | mittelland | Süd | auto |
| 3 | [mittelland_ost](#3-mittelland_ost) | mittelland | Süd | auto |
| 4 | [genferseeregion](#4-genferseeregion) | mittelland | Süd | ✓ |
| 5 | [jura_ost](#5-jura_ost) | jura | Süd | auto |
| 6 | [jura_west](#6-jura_west) | jura | Süd | ✓ |
| 7 | [jura_zentral](#7-jura_zentral) | jura | Süd | ✓ |
| 8 | [mittelland_zentral](#8-mittelland_zentral) | voralpen | Süd | ✓ |
| 9 | [glarnerland_walensee](#9-glarnerland_walensee) | alpen | Süd | ✓ |
| 10 | [schwarzsee_gantrisch](#10-schwarzsee_gantrisch) | voralpen | Süd | ✓ |
| 11 | [rheintal](#11-rheintal) | voralpen | Süd | auto |
| 12 | [bodenseeraum](#12-bodenseeraum) | mittelland | Süd | ✓ |
| 13 | [waadtlaender_alpen](#13-waadtlaender_alpen) | alpen | Süd | ✓ |
| 14 | [alpstein](#14-alpstein) | alpen | Süd | ✓ |
| 15 | [tessin_zentral](#15-tessin_zentral) | alpen | Nord | ✓ |
| 16 | [praettigau_davos](#16-praettigau_davos) | alpen | Beide | ✓ |
| 17 | [berner_oberland](#17-berner_oberland) | hochalpin | Süd | auto |
| 18 | [zentralschweizer_voralpen](#18-zentralschweizer_voralpen) | alpen | Süd | ✓ |
| 19 | [berner_voralpen](#19-berner_voralpen) | alpen | Beide | ✓ |
| 20 | [freiburger_voralpen](#20-freiburger_voralpen) | voralpen | Süd | ✓ |
| 21 | [mattertal_saastal](#21-mattertal_saastal) | hochalpin | Beide | ✓ |
| 22 | [tessin_nord](#22-tessin_nord) | hochalpin | Nord | ✓ |
| 23 | [zentralwallis](#23-zentralwallis) | hochalpin | Beide | ✓ |
| 24 | [engadin_unter](#24-engadin_unter) | hochalpin | Beide | ✓ |
| 25 | [unterwallis](#25-unterwallis) | hochalpin | Beide | ✓ |
| 26 | [oberwallis_goms](#26-oberwallis_goms) | hochalpin | Beide | ✓ |
| 27 | [surselva](#27-surselva) | hochalpin | Beide | ✓ |
| 28 | [zentrales_mittelland](#28-zentrales_mittelland) | mittelland | Süd | auto |
| 29 | [engadin_ober](#29-engadin_ober) | hochalpin | Beide | ✓ |

> `S-Anker ✓` = validierter Pflicht-S-Anker eingesetzt (liegt innerhalb Polygon).
> `S-Anker auto` = validierter S-Anker liegt AUSSERHALB Polygon, südlichster auto-gen
> Punkt wird als Fallback verwendet (siehe Spalte 'Begründung' in der Region-Tabelle).

---

## 1. seeland_emmental
**Region**: Seeland / Emmental · **Terrain**: mittelland · **Ref-Höhe**: 600 m · **Föhn**: Süd

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-O | 47.3556, 7.9168 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Bölchen, 9 km O) |
| 2 | Flughöhe-S | 46.9700, 7.4900 | Bantiger S-Hang |
| 3 | Edge-N (Schatten) | 47.2340, 7.5910 | 4.6 km SSO von Stierenberg (Stierenberg) |
| 4 | Edge-O | 47.1124, 7.8082 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Chutz, 22 km SSO) |
| 5 | Edge-O | 47.2046, 7.7987 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Schwengimatt, 13 km SO) |
| 6 | Innen-Sample | 47.0698, 7.4138 | Polygon-Innern, kein Spot < 8 km (nächster: Décollage Ost, 15 km SO) |
| 7 | Edge-W | 47.1400, 7.5651 | westliche Polygon-Kante, kein Spot < 8 km (nächster: Weissenstein, 13 km SSO) |

## 2. mittelland_west
**Region**: Mittelland West · **Terrain**: mittelland · **Ref-Höhe**: 700 m · **Föhn**: Süd

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-O | 46.9008, 7.3792 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Pfeiffe, 18 km N) |
| 2 | Edge-W | 46.6785, 6.5352 | westliche Polygon-Kante, kein Spot < 8 km (nächster: Le Suchet, 12 km SSO) |
| 3 | Edge-N (Schatten) | 46.9749, 6.8969 | nördliche Polygon-Kante (N-Exposition), kein Spot < 8 km (nächster: Tete de Ran, 9 km SSO) |
| 4 | Flughöhe-S (auto) | 46.5303, 6.7763 | S-Anker 'Belpberg-S' ausserhalb Polygon — 11.3 km von Les Pleiades 1 |
| 5 | Innen-Sample | 46.8512, 6.9286 | Polygon-Innern, kein Spot < 8 km (nächster: La Roche, 16 km OSO) |
| 6 | Innen-Sample | 46.7287, 6.7375 | Polygon-Innern, kein Spot < 8 km (nächster: Mauborget, 17 km SO) |
| 7 | Innen-Sample | 46.9065, 7.0981 | Polygon-Innern, kein Spot < 8 km (nächster: Chaumont, 19 km SSO) |

## 3. mittelland_ost
**Region**: Mittelland Ost · **Terrain**: mittelland · **Ref-Höhe**: 730 m · **Föhn**: Süd

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-W | 47.4064, 8.6045 | westliche Polygon-Kante, kein Spot < 8 km (nächster: Balderen, 12 km NO) |
| 2 | Edge-O | 47.2759, 8.8510 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Hirzli, 20 km NW) |
| 3 | Edge-W | 47.4266, 8.4841 | westliche Polygon-Kante, kein Spot < 8 km (nächster: Balderen, 12 km N) |
| 4 | Flughöhe-S (auto) | 47.1602, 8.6635 | S-Anker 'Albishorn-S' ausserhalb Polygon — 13.6 km von Oberrieden Start-Landeplatz |
| 5 | Edge-W | 47.3087, 8.5100 | nahe **Balderen** (Uetliberg, 730 m, 1.7 km SSO) |
| 6 | Innen-Sample | 47.3187, 8.6538 | Polygon-Innern, kein Spot < 8 km (nächster: Oberrieden Start-Landeplatz, 8 km NO) |
| 7 | Edge-O | 47.1623, 9.0811 | 6.4 km ONO von Hirzli (Hirzli) |

## 4. genferseeregion
**Region**: Genferseeregion · **Terrain**: mittelland · **Ref-Höhe**: 800 m · **Föhn**: Süd

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Flughöhe-S | 46.4900, 6.8500 | Mont-Pèlerin-S |
| 2 | Edge-O | 46.5108, 6.8027 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Les Pleiades 1, 9 km WNW) |
| 3 | Edge-N (Schatten) | 46.4285, 6.2993 | nördliche Polygon-Kante (N-Exposition), kein Spot < 8 km (nächster: St. Cergue, 10 km O) |
| 4 | Edge-N (Schatten) | 46.5931, 6.5510 | nördliche Polygon-Kante (N-Exposition), kein Spot < 8 km (nächster: Dent de Vaulion, 18 km OSO) |
| 5 | Innen-Sample | 46.5011, 6.5103 | Polygon-Innern, kein Spot < 8 km (nächster: Dent de Vaulion, 24 km SSO) |
| 6 | Edge-W | 46.2553, 6.1458 | westliche Polygon-Kante, kein Spot < 8 km (nächster: La Barilette, 19 km S) |
| 7 | Edge-W | 46.3775, 6.3291 | westliche Polygon-Kante, kein Spot < 8 km (nächster: St. Cergue, 14 km OSO) |

## 5. jura_ost
**Region**: Jura Ost · **Terrain**: jura · **Ref-Höhe**: 900 m · **Föhn**: Süd

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-O | 47.4661, 7.9678 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Bölchen, 17 km NO) |
| 2 | Flughöhe-S (auto) | 47.3066, 6.9828 | S-Anker 'Wasserflue-S' ausserhalb Polygon — 18.0 km von Boecourt |
| 3 | Edge-W | 47.4661, 7.4049 | westliche Polygon-Kante, kein Spot < 8 km (nächster: Boecourt, 19 km NO) |
| 4 | Edge-O | 47.3704, 7.6864 | nahe **Hohwacht** (Hohwacht, 1041 m, 1.2 km SO) |
| 5 | Edge-O | 47.4363, 7.8125 | 7.9 km N von Bölchen (Bölchen) |
| 6 | Edge-W | 47.4137, 7.1224 | westliche Polygon-Kante, kein Spot < 8 km (nächster: Boecourt, 8 km NW) |
| 7 | Edge-O | 47.4126, 7.4939 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Hohwacht, 14 km WNW) |

## 6. jura_west
**Region**: Jura West · **Terrain**: jura · **Ref-Höhe**: 1200 m · **Föhn**: Süd

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-O | 47.1112, 7.0433 | nahe **Chasseral Süd** (Chasseral Süd, 1518 m, 1.7 km S) |
| 2 | Edge-W | 46.8960, 6.2186 | westliche Polygon-Kante, kein Spot < 8 km (nächster: Mont des Cerfs, 22 km WNW) |
| 3 | Edge-N (Schatten) | 47.1112, 6.5720 | nördliche Polygon-Kante (N-Exposition), kein Spot < 8 km (nächster: Tete de Ran, 22 km WNW) |
| 4 | Flughöhe-S | 46.8540, 6.6120 | Mauborget — nahe Mauborget (Mauborget, 1176 m) |
| 5 | Innen-Sample | 46.9969, 6.6448 | Polygon-Innern, kein Spot < 8 km (nächster: La Roche, 11 km NW) |
| 6 | Innen-Sample | 46.9183, 6.4456 | Polygon-Innern, kein Spot < 8 km (nächster: La Robella, 9 km WNW) |
| 7 | Edge-O | 47.0963, 6.8507 | 4.7 km N von Tete de Ran (Tete de Ran) |

## 7. jura_zentral
**Region**: Jura Zentral · **Terrain**: jura · **Ref-Höhe**: 1280 m · **Föhn**: Süd

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-O | 47.3577, 7.7073 | 4.3 km O von Passwang (Passwang) |
| 2 | Edge-W | 47.2490, 7.0058 | westliche Polygon-Kante, kein Spot < 8 km (nächster: Corgémont, 13 km NW) |
| 3 | Edge-O | 47.2128, 7.4067 | nahe **Grenchenberg Bützen** (Grenchenberg Bützen, 1260 m, 1.6 km SO) |
| 4 | Flughöhe-S | 47.2510, 7.5100 | Weissenstein — nahe Weissenstein (Weissenstein, 1233 m) |
| 5 | Innen-Sample | 47.2249, 7.1343 | 5.7 km N von Corgémont (Corgémont) |
| 6 | Innen-Sample | 47.2548, 7.2714 | 4.7 km NW von Montagne de Sorvillier (Montagne de Sorvillier) |
| 7 | Edge-O | 47.2906, 7.4228 | nahe **Mont Raimeux Süd** (Mont Raimeux Süd, 1232 m, 1.0 km S) |

## 8. mittelland_zentral
**Region**: Mittelland Zentral · **Terrain**: voralpen · **Ref-Höhe**: 1400 m · **Föhn**: Süd

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Flughöhe-S | 47.0480, 8.4600 | Rigi-Staffelhöhe S — nahe Rigi Staffelhöhe (S) (Rigi, 1544 m) |
| 2 | Edge-O | 47.1582, 8.8999 | 2.1 km O von Gschwänd (Gschwänd) |
| 3 | Edge-W | 47.0694, 8.3694 | 6.7 km W von Seebodenalp (Rigi) |
| 4 | Edge-O | 47.0250, 8.6346 | 3.7 km SSW von Egelstock (Egelstock) |
| 5 | Edge-O | 47.1063, 8.7607 | nahe **Rotmoos** (Hummel, 1045 m, 1.1 km WNW) |
| 6 | Edge-W | 46.9787, 8.0242 | 5.1 km NNW von Farneren 1 (Farneren) |
| 7 | Edge-O | 47.0831, 8.5370 | 3.1 km W von Wildspitz (Wildspitz) |

## 9. glarnerland_walensee
**Region**: Glarnerland / Walensee · **Terrain**: alpen · **Ref-Höhe**: 1300 m · **Föhn**: Süd

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Flughöhe-S | 47.1000, 9.3000 | Flumserberg-S |
| 2 | Edge-O | 47.0939, 9.3912 | 2.4 km WNW von Palfries 1 (Palfries) |
| 3 | Edge-W | 47.0939, 9.0361 | 3.1 km OSO von Bärensolspitz (Bärensolspitz) |
| 4 | Edge-S | 46.9114, 9.1781 | 2.3 km OSO von Elm 1 (Elm) |
| 5 | Innen-Sample | 47.0315, 9.2831 | 4.8 km SSO von Maschgenkamm (Maschgenkamm) |
| 6 | Innen-Sample | 46.9734, 9.0225 | nahe **Bodenberg** (Bodenberg, 1226 m, 0.1 km W) |
| 7 | Innen-Sample | 47.0193, 9.1440 | 6.2 km NNW von Wissenberg (Wissenberg) |

## 10. schwarzsee_gantrisch
**Region**: Schwarzsee / Gantrisch · **Terrain**: voralpen · **Ref-Höhe**: 1500 m · **Föhn**: Süd

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-O | 46.8730, 7.4068 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Pfeiffe, 15 km N) |
| 2 | Flughöhe-S | 46.6770, 7.2610 | Schwyberg — nahe Schwyberg (Schwyberg, 1613 m) |
| 3 | Edge-S | 46.6067, 7.1825 | 2.7 km SW von Vounetse (Vounetse) |
| 4 | Edge-W | 46.7132, 6.9582 | westliche Polygon-Kante, kein Spot < 8 km (nächster: La Vudalla, 19 km NNW) |
| 5 | Innen-Sample | 46.6280, 6.9873 | Polygon-Innern, kein Spot < 8 km (nächster: La Vudalla, 10 km NNW) |
| 6 | Innen-Sample | 46.6753, 7.1354 | 7.7 km NW von Vounetse (Vounetse) |
| 7 | Innen-Sample | 46.7523, 7.3034 | 3.1 km NW von Phyffe (Phyffe) |

## 11. rheintal
**Region**: Ostschweiz · **Terrain**: voralpen · **Ref-Höhe**: 1500 m · **Föhn**: Süd

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-N (Schatten) | 47.5361, 9.7541 | nördliche Polygon-Kante (N-Exposition), kein Spot < 8 km (nächster: Hüsli Berneck, 17 km NO) |
| 2 | Flughöhe-S (auto) | 46.8213, 9.4307 | S-Anker 'Säntis SW-Flanke' ausserhalb Polygon — nahe Feldis 1 (Feldis, 1441 m) |
| 3 | Edge-W | 47.2297, 9.3768 | 8.0 km NNW von Studnerberg (Studnerberg) |
| 4 | Edge-O | 47.2297, 9.6463 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Triesen, 13 km NNO) |
| 5 | Innen-Sample | 47.3767, 9.6409 | 6.8 km SSO von Hüsli Berneck (Hüsli Berneck) |
| 6 | Edge-W | 47.1920, 9.5222 | 7.1 km NNW von Triesen (Triesen) |
| 7 | Innen-Sample | 46.9316, 9.4968 | 4.8 km NNO von Calandasiten (Calandasiten) |

## 12. bodenseeraum
**Region**: Bodenseeraum · **Terrain**: mittelland · **Ref-Höhe**: 600 m · **Föhn**: Süd

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-O | 47.5980, 9.6448 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Hamenberg - Rudolfingen, 73 km O) |
| 2 | Edge-W | 47.4727, 8.5480 | westliche Polygon-Kante, kein Spot < 8 km (nächster: Hamenberg - Rudolfingen, 21 km SSW) |
| 3 | Edge-N (Schatten) | 47.8486, 9.0181 | nördliche Polygon-Kante (N-Exposition), kein Spot < 8 km (nächster: Opfertshofen, 28 km ONO) |
| 4 | Flughöhe-S | 47.6440, 8.6710 | Hamenberg — nahe Hamenberg - Rudolfingen (Hamenberg - Rudolfingen, 485 m) |
| 5 | Innen-Sample | 47.6438, 9.0316 | Polygon-Innern, kein Spot < 8 km (nächster: Hamenberg - Rudolfingen, 27 km O) |
| 6 | Innen-Sample | 47.6447, 8.7575 | 6.5 km O von Hamenberg - Rudolfingen (Hamenberg - Rudolfingen) |
| 7 | Innen-Sample | 47.5731, 9.3137 | Polygon-Innern, kein Spot < 8 km (nächster: Hamenberg - Rudolfingen, 49 km O) |

## 13. waadtlaender_alpen
**Region**: Waadtländer Alpen · **Terrain**: alpen · **Ref-Höhe**: 1600 m · **Föhn**: Süd

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-W | 46.4098, 6.7524 | westliche Polygon-Kante, kein Spot < 8 km (nächster: Chalavonaire, 9 km WNW) |
| 2 | Flughöhe-S | 46.3220, 7.0680 | Roc d'Orsay (Leysin) — nahe Roc Orsay (Roc Orsay, 1881 m) |
| 3 | Edge-O | 46.3542, 7.1963 | 2.5 km S von Isenau (Isenau) |
| 4 | Edge-W | 46.1873, 6.8158 | nahe **Les Crosets 2** (Les Crosets, 2266 m, 0.4 km S) |
| 5 | Innen-Sample | 46.2830, 6.9570 | 5.3 km WSW von En Curnaux (En Curnaux) |
| 6 | Innen-Sample | 46.3737, 6.8952 | 3.2 km ONO von Chalavonaire (Chalavornaire) |
| 7 | Innen-Sample | 46.2714, 7.0358 | 2.8 km NNW von Les Vernays (Les Verneys) |

## 14. alpstein
**Region**: Alpstein / Ostschweiz · **Terrain**: alpen · **Ref-Höhe**: 1640 m · **Föhn**: Süd

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-W | 47.4560, 8.7911 | westliche Polygon-Kante, kein Spot < 8 km (nächster: Alp Scheidegg, 20 km NW) |
| 2 | Edge-O | 47.3176, 9.4649 | 3.5 km WNW von Motlinger Schwamm (Motlinger Schwamm) |
| 3 | Edge-S | 47.1791, 9.0799 | 1.2 km SSO von Hüsliberg (Hüsliberg, 1005 m) — südliche Toggenburg-Kante |
| 4 | Edge-N (Schatten) | 47.4099, 9.0799 | nördliche Polygon-Kante (N-Exposition), kein Spot < 8 km (nächster: Alp Scheidegg, 16 km NO) |
| 5 | Flughöhe-S | 47.2910, 9.3290 | Kronberg-S — nahe Kronberg 2 (Kronberg, 1649 m) — ersetzte auto-gen 47.2977/9.3260 wegen 2-km-Kollision |
| 6 | Edge-W | 47.3566, 8.9854 | 6.6 km NNO von Alp Scheidegg (Alp Scheidegg) |
| 7 | Innen-Sample | 47.2791, 9.1616 | 7.6 km SW von Hochhamm (Hochhamm) |

## 15. tessin_zentral
**Region**: Tessin Zentral · **Terrain**: alpen · **Ref-Höhe**: 1650 m · **Föhn**: Nord

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-W | 46.1683, 8.4782 | westliche Polygon-Kante, kein Spot < 8 km (nächster: Cimetta, 24 km W) |
| 2 | Edge-O | 46.4633, 9.2423 | östliche Polygon-Kante, kein Spot < 8 km (nächster: St. Maria, 23 km NNO) |
| 3 | Flughöhe-S | 46.2000, 8.7880 | Cimetta — nahe Cimetta (Cimetta, 1616 m) |
| 4 | Edge-N (Schatten) | 46.3650, 8.8057 | nördliche Polygon-Kante (N-Exposition), kein Spot < 8 km (nächster: Cimetta, 18 km N) |
| 5 | Edge-O | 46.2469, 9.0542 | nahe **Parusciana** (Parusciana, 1249 m, 0.6 km N) |
| 6 | Edge-W | 46.2134, 8.6665 | westliche Polygon-Kante, kein Spot < 8 km (nächster: Cimetta, 9 km W) |
| 7 | Innen-Sample | 46.2345, 8.8395 | 5.5 km NO von Cimetta (Cimetta) |

## 16. praettigau_davos
**Region**: Prättigau - Davos · **Terrain**: alpen · **Ref-Höhe**: 1700 m · **Föhn**: Beide

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-O | 46.8629, 10.0579 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Gotschnagrat 2, 16 km O) |
| 2 | Edge-W | 47.0249, 9.5896 | 7.7 km WNW von Fanas 2 (Fanas) |
| 3 | Flughöhe-S | 46.8050, 9.8170 | Schatzalp (Davos) — nahe Schatzalp (Schatzalp, 1973 m) |
| 4 | Edge-N (Schatten) | 46.9709, 9.8572 | 3.3 km OSO von Bärgli (Bärgli) |
| 5 | Innen-Sample | 46.8113, 9.8597 | 2.7 km OSO von Parsenn 3 (Parsenn) |
| 6 | Innen-Sample | 46.9369, 9.7371 | 3.0 km SSO von Stelserberg (Stelserberg) |
| 7 | Innen-Sample | 46.8501, 9.7405 | 4.3 km WNW von Parsenn 2 (Parsenn) |

## 17. berner_oberland
**Region**: Berner Oberland · **Terrain**: hochalpin · **Ref-Höhe**: 1800 m · **Föhn**: Süd

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-O | 47.0777, 7.9379 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Marbachegg 1, 27 km N) |
| 2 | Flughöhe-S (auto) | 46.7734, 7.4727 | S-Anker 'Männlichen-S-Flanke' ausserhalb Polygon — 13.7 km von Falkenflue |
| 3 | Edge-S | 46.7734, 7.8050 | südliche Polygon-Kante, kein Spot < 8 km (nächster: Marbachegg 2, 10 km SW) |
| 4 | Edge-N (Schatten) | 47.0168, 7.6056 | nördliche Polygon-Kante (N-Exposition), kein Spot < 8 km (nächster: Falkenflue, 22 km N) |
| 5 | Innen-Sample | 46.8280, 7.6955 | 4.5 km O von Falkenflue (Falkenflue) |
| 6 | Innen-Sample | 46.8664, 7.5923 | 5.8 km NW von Falkenflue (Falkenflue) |
| 7 | Innen-Sample | 46.9512, 7.7630 | Polygon-Innern, kein Spot < 8 km (nächster: Marbachegg 1, 17 km NW) |

## 18. zentralschweizer_voralpen
**Region**: Zentralschweizer Voralpen · **Terrain**: alpen · **Ref-Höhe**: 1860 m · **Föhn**: Süd

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-W | 46.8299, 7.9749 | 5.2 km W von Hagleren (Hagleren) |
| 2 | Edge-O | 47.0290, 8.8844 | 5.5 km ONO von Steinhüttli (Hoch-Ybrig) |
| 3 | Flughöhe-S | 46.9650, 8.6400 | Stoos Fronalpstock — nahe Südstartplatz (Fronalpstock / Stoos, 1860 m) |
| 4 | Edge-W | 46.9626, 8.3647 | 3.8 km NNO von Stanserhorn 2 (Stanserhorn) |
| 5 | Edge-O | 46.8357, 8.5432 | 4.5 km W von Brüsti 2 (Brüsti) |
| 6 | Edge-W | 46.8774, 8.2900 | nahe **Linderenalp** (Linderenalp, 1541 m, 0.9 km NW) |
| 7 | Innen-Sample | 46.8870, 8.7004 | 2.2 km W von Ratzi (Ratzi) |

## 19. berner_voralpen
**Region**: Berner Voralpen · **Terrain**: alpen · **Ref-Höhe**: 1800 m · **Föhn**: Beide

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-O | 46.7602, 8.4048 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Planplatten 2, 12 km ONO) |
| 2 | Edge-W | 46.6302, 7.7952 | 6.9 km S von Luegibrüggli (Interlaken) |
| 3 | Flughöhe-S | 46.7110, 7.7780 | Niederhorn — nahe Niederhorn (Interlaken, 1953 m) |
| 4 | Edge-N (Schatten) | 46.7602, 8.0565 | 2.4 km SSW von Hofstetter Gummen (Hofstetter Gummen) |
| 5 | Innen-Sample | 46.6683, 8.0805 | 2.3 km ONO von First (Grindelwald) |
| 6 | Innen-Sample | 46.6612, 7.9127 | nahe **Schynige Platte 1** (Schynige Platte, 1750 m, 0.8 km ONO) |
| 7 | Innen-Sample | 46.6561, 8.2494 | Polygon-Innern, kein Spot < 8 km (nächster: Planplatten 1, 9 km S) |

## 20. freiburger_voralpen
**Region**: Freiburger Voralpen · **Terrain**: voralpen · **Ref-Höhe**: 1500 m · **Föhn**: Süd

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-W | 46.4157, 7.0307 | 4.4 km OSO von Rochers de Naye 1 (Rochers de Naye) |
| 2 | Edge-O | 46.6045, 7.7930 | 7.2 km ONO von Ramslauen (Ramslauen) |
| 3 | Edge-N (Schatten) | 46.6517, 7.3574 | 3.3 km OSO von Hohmattli 1 (Hohmattli) |
| 4 | Flughöhe-S | 46.6930, 7.5380 | Stockhorn — nahe Stockhorn 1 (Stockhorn, 2082 m) |
| 5 | Edge-O | 46.5509, 7.6139 | 4.1 km S von Mäggisseren (Mäggisseren) |
| 6 | Edge-W | 46.4793, 7.2293 | 2.8 km NO von La Videmanette 1 (Videmanette) |
| 7 | Innen-Sample | 46.5469, 7.4214 | 2.0 km SO von Danielsweid (Danielsweid) |

## 21. mattertal_saastal
**Region**: Mattertal / Saastal · **Terrain**: hochalpin · **Ref-Höhe**: 2000 m · **Föhn**: Beide

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Flughöhe-S | 46.1510, 7.5860 | Col de Sorebois — nahe Col de Sorebois 2 (Col de Sorebois, 2882 m) |
| 2 | Edge-O | 46.1745, 7.9890 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Seetalhorn 2, 10 km O) |
| 3 | Edge-S | 45.9606, 7.6806 | 4.1 km SSW von Schwarzsee (Schwarzsee) |
| 4 | Edge-W | 46.0889, 7.4751 | 4.9 km SW von Evolene (Evolene) |
| 5 | Innen-Sample | 46.0957, 7.8564 | Polygon-Innern, kein Spot < 8 km (nächster: Seetalhorn, 9 km S) |
| 6 | Edge-W | 46.0191, 7.4178 | westliche Polygon-Kante, kein Spot < 8 km (nächster: Evolene, 14 km SSW) |
| 7 | Innen-Sample | 46.0705, 7.6750 | Polygon-Innern, kein Spot < 8 km (nächster: Schwarzsee, 9 km NNW) |

## 22. tessin_nord
**Region**: Tessin Nord · **Terrain**: hochalpin · **Ref-Höhe**: 2000 m · **Föhn**: Nord

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Flughöhe-S | 46.5090, 8.8180 | Cari — nahe Cari 3 (Cari, 2145 m) |
| 2 | Edge-O | 46.4444, 9.1221 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Malvaglia, 10 km ONO) |
| 3 | Edge-N (Schatten) | 46.5333, 8.7283 | 7.3 km WNW von Cari 3 (Cari) |
| 4 | Edge-W | 46.4889, 8.4329 | westliche Polygon-Kante, kein Spot < 8 km (nächster: Cari 3, 30 km W) |
| 5 | Edge-O | 46.4557, 8.9418 | 5.2 km SSO von Gorda (Gorda) |
| 6 | Innen-Sample | 46.4249, 8.5907 | Polygon-Innern, kein Spot < 8 km (nächster: Cari 1, 19 km WSW) |
| 7 | Edge-N (Schatten) | 46.4792, 8.7577 | 5.3 km WSW von Cari 1 (Cari) |

## 23. zentralwallis
**Region**: Zentralwallis · **Terrain**: hochalpin · **Ref-Höhe**: 2100 m · **Föhn**: Beide

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Flughöhe-S | 46.4110, 7.7710 | Laucheralp — nahe Laucheralp (Laucheralp, 1981 m) |
| 2 | Edge-O | 46.5269, 8.1762 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Laucheralp, 34 km ONO) |
| 3 | Edge-S | 46.4106, 7.9793 | südliche Polygon-Kante, kein Spot < 8 km (nächster: Laucheralp, 16 km O) |
| 4 | Edge-W | 46.4571, 7.8480 | 7.8 km NO von Laucheralp (Laucheralp) |
| 5 | Edge-O | 46.4988, 8.0534 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Laucheralp, 24 km ONO) |
| 6 | Edge-W | 46.4291, 7.8314 | 5.1 km ONO von Laucheralp (Laucheralp) |
| 7 | Edge-O | 46.4610, 7.9627 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Laucheralp, 16 km ONO) |

## 24. engadin_unter
**Region**: Engadin Unter · **Terrain**: hochalpin · **Ref-Höhe**: 2100 m · **Föhn**: Beide

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-W | 46.4977, 9.0761 | westliche Polygon-Kante, kein Spot < 8 km (nächster: Präzer Alp 2, 35 km SW) |
| 2 | Edge-O | 46.6642, 9.8250 | 5.6 km NO von Alp Darlux (Alp Darlux) |
| 3 | Flughöhe-S | 46.6240, 9.7800 | Alp Darlux — nahe Alp Darlux (Alp Darlux, 2283 m) |
| 4 | Edge-N (Schatten) | 46.7197, 9.3971 | 2.6 km SSO von Präzer Alp 1 (Präzer Alp) |
| 5 | Edge-O | 46.6206, 9.6348 | 6.9 km ONO von Somtgant 2 (Somtgant) |
| 6 | Innen-Sample | 46.6376, 9.4628 | Polygon-Innern, kein Spot < 8 km (nächster: Piz Martegnas 1, 8 km NW) |
| 7 | Innen-Sample | 46.5130, 9.5258 | 7.1 km S von Piz Martegnas 3 (Piz Martegnas) |

## 25. unterwallis
**Region**: Unterwallis · **Terrain**: hochalpin · **Ref-Höhe**: 2200 m · **Föhn**: Beide

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-W | 46.0443, 6.9266 | westliche Polygon-Kante, kein Spot < 8 km (nächster: La Breya, 14 km WNW) |
| 2 | Edge-O | 46.3349, 7.7541 | nahe **Jeizinen** (Jeizinen, 1637 m, 1.9 km ONO) |
| 3 | Edge-N (Schatten) | 46.3349, 7.2812 | nördliche Polygon-Kante (N-Exposition), kein Spot < 8 km (nächster: Pas de Maimbre 2, 8 km WNW) |
| 4 | Flughöhe-S | 46.1220, 7.2330 | Croix de Coeur (Verbier) — nahe Croix de Coeur 1 (Croix de Coeur, 2194 m) |
| 5 | Innen-Sample | 46.2461, 7.4204 | 7.7 km W von Vercorin 3 (Vercorin) |
| 6 | Edge-W | 46.2054, 7.2786 | 4.8 km N von Haute-Nendaz (Haute-Nendaz) |
| 7 | Innen-Sample | 46.2798, 7.5749 | 5.4 km NO von Vercorin 3 (Vercorin) |

## 26. oberwallis_goms
**Region**: Oberwallis / Goms · **Terrain**: hochalpin · **Ref-Höhe**: 2200 m · **Föhn**: Beide

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-O | 46.6255, 8.4408 | 4.2 km NW von Tätsch (Tätsch) |
| 2 | Flughöhe-S | 46.4160, 8.1060 | Fiescheralp — nahe Fiescheralp (Fiescheralp, 2238 m) |
| 3 | Edge-O | 46.3441, 8.1837 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Galfera, 10 km SO) |
| 4 | Edge-O | 46.4566, 8.3551 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Ulrichen, 8 km SO) |
| 5 | Edge-O | 46.4040, 8.1785 | 4.2 km SSO von Mutti (Mutti) |
| 6 | Innen-Sample | 46.3112, 7.9339 | 7.4 km SSW von Sommer (Belalp) |
| 7 | Innen-Sample | 46.3342, 8.0362 | nahe **Ried** (Ried, 1488 m, 0.8 km NNW) |

## 27. surselva
**Region**: Surselva · **Terrain**: hochalpin · **Ref-Höhe**: 2200 m · **Föhn**: Beide

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-W | 46.5854, 8.6627 | westliche Polygon-Kante, kein Spot < 8 km (nächster: Cugieri 1, 15 km SW) |
| 2 | Edge-O | 46.8906, 9.3363 | 5.5 km ONO von Cassons 2 (Cassons) |
| 3 | Flughöhe-S | 46.7420, 9.1580 | Piz Mundaun — nahe Piz Mundaun (Piz Mundaun, 2053 m) |
| 4 | Edge-W | 46.7888, 8.9514 | 4.2 km NW von Schlans (Schlans) |
| 5 | Innen-Sample | 46.7565, 9.2307 | 4.3 km SSO von Ladir (Ladir) |
| 6 | Innen-Sample | 46.6811, 8.8554 | 4.6 km SO von Caischavedra (Caischavedra) |
| 7 | Innen-Sample | 46.6926, 9.0914 | 4.6 km SW von Stein (Stein) |

## 28. zentrales_mittelland
**Region**: Zentrales Mittelland · **Terrain**: mittelland · **Ref-Höhe**: 600 m · **Föhn**: Süd

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-N (Schatten) | 47.7103, 8.5267 | nördliche Polygon-Kante (N-Exposition), kein Spot < 8 km (nächster: Herlisberg, 61 km NNO) |
| 2 | Flughöhe-S (auto) | 47.0755, 7.9806 | S-Anker 'Bantiger-S' ausserhalb Polygon — 23.4 km von Herlisberg |
| 3 | Edge-O | 47.1662, 8.6177 | östliche Polygon-Kante, kein Spot < 8 km (nächster: Herlisberg, 29 km O) |
| 4 | Edge-W | 47.5289, 8.0716 | westliche Polygon-Kante, kein Spot < 8 km (nächster: Herlisberg, 39 km NNW) |
| 5 | Innen-Sample | 47.2449, 8.1667 | 7.2 km NW von Herlisberg (Herlisberg) |
| 6 | Innen-Sample | 47.3340, 8.2849 | Polygon-Innern, kein Spot < 8 km (nächster: Herlisberg, 16 km NNO) |
| 7 | Innen-Sample | 47.4973, 8.2764 | Polygon-Innern, kein Spot < 8 km (nächster: Herlisberg, 33 km N) |

## 29. engadin_ober
**Region**: Engadin Ober · **Terrain**: hochalpin · **Ref-Höhe**: 2450 m · **Föhn**: Beide

| # | Funktion | Lat, Lon | Begründung |
|---|---|---|---|
| 1 | Edge-W | 46.5011, 9.7124 | 5.9 km W von Piz Nair (Piz Nair) |
| 2 | Edge-O | 46.6308, 10.2544 | östliche Polygon-Kante, kein Spot < 8 km (nächster: La Punt, 27 km O) |
| 3 | Edge-N (Schatten) | 46.7605, 9.9834 | nördliche Polygon-Kante (N-Exposition), kein Spot < 8 km (nächster: La Punt, 20 km NNO) |
| 4 | Flughöhe-S | 46.5210, 9.9020 | Muottas Muragl — nahe Muottas Muragl (Muottas Muragl, 2240 m) |
| 5 | Innen-Sample | 46.6243, 10.0564 | Polygon-Innern, kein Spot < 8 km (nächster: La Punt, 12 km ONO) |
| 6 | Innen-Sample | 46.4876, 9.9017 | nahe **Alp Languard 1** (Alp Languard, 2307 m, 1.6 km W) |
| 7 | Innen-Sample | 46.5371, 10.0240 | Polygon-Innern, kein Spot < 8 km (nächster: Muottas Muragl, 9 km O) |

---

## Sicherheits-Checks

- **Alle 203 Punkte (29 × 7) liegen innerhalb ihres Region-Polygons.** Validiert
  via `scripts/_check_refpoints_in_polygon.py` gegen
  `data/regionen_polygone_mapped.geojson`.
- **S-Anker-Status**: 23 von 29 Regionen haben den validierten S-Anker einsetzbar
  (liegt im Polygon). 6 Regionen haben den S-Anker ausserhalb — dort wird als
  Fallback der südlichste auto-gen Punkt als Flughöhe-S markiert. Das sind:
  - `mittelland_west` — Empfehlung 'Belpberg-S' liegt 7.5 km ausserhalb
  - `mittelland_ost` — Empfehlung 'Albishorn-S' liegt 1.6 km ausserhalb
  - `jura_ost` — Empfehlung 'Wasserflue-S' liegt 4.4 km ausserhalb
  - `rheintal` — Empfehlung 'Säntis SW-Flanke' liegt 3.1 km ausserhalb
  - `berner_oberland` — Empfehlung 'Männlichen-S-Flanke' liegt 15.7 km ausserhalb
  - `zentrales_mittelland` — Empfehlung 'Bantiger-S' liegt 52.5 km ausserhalb

  Für diese Regionen müsste entweder das Polygon erweitert oder ein neuer S-Anker
  INNERHALB des Polygons gesucht werden (z. B. via Karte auf `/admin/reference-points`).

---

## KONZEPT-Konformität — Audit-Ergebnis

Gegen die Checkliste in `docs/REFPOINT_KONZEPT.md` (`Checkliste pro Region` +
`Anti-Patterns`) wurden 5 offline prüfbare Kriterien validiert. Stand bei
letzter Generierung:

| Kriterium | Status |
|---|---|
| Mindest-Abstand 2 km zwischen allen 7 Punkten (ICON-D2-Auflösung) | **29/29 ✓** (nach alpstein-Fix) |
| Mindestens 1 Flughöhe-S-Punkt im Set | **29/29 ✓** (6 davon auto-Fallback, siehe oben) |
| Föhn-Lee-Anker für Regionen mit `kritischer_foehn` ≠ leer | **29/29 ✓** |
| Keine Duplikat-Positionen | **29/29 ✓** |
| Mindestens 1 Spot < 5 km von irgendeinem Punkt (Flugschul-Anker) | **28/29** — `mittelland_west` hat keinen Spot < 9.4 km (Region ohne Startplätze in `fluggebiete_complete.csv`) |

**Nicht prüfbar ohne DEM/Aspekt-Daten** (4 weitere Kriterien aus dem KONZEPT):

- Höhenspanne ≥ 800 m zwischen höchstem und tiefstem Punkt
- Aspekt-Verteilung (≥ 2 verschiedene Expositionen pro Region)
- Echter Talboden- und Kamm-Punkt vorhanden (braucht Elevation)
- Punkt nicht auf grosser Wasserfläche (braucht Land-Cover-Daten)

Diese 4 Kriterien wären über einen lokalen DEM (z. B. SwissALTI3D oder SRTM)
bzw. eine Reverse-Geocoding-API prüfbar. Aktuell nicht implementiert.

> **Konsequenz für die LISTE**: die Funktions-Labels (Edge-N/O/S/W,
> Innen-Sample, Flughöhe-S) sind **strukturelle Polygon-Positions-Heuristiken**,
> nicht garantierte meteorologische Funktionen. Ein "Edge-S" ist garantiert am
> Süd-Rand des Polygons — ob er auf einem Talboden, einer S-Flanke oder einem
> Kamm liegt, hängt von der lokalen Topographie ab und ist ohne DEM nicht
> automatisch verifizierbar. Für 100 % KONZEPT-Konformität müssten die Punkte
> manuell auf der Karte überprüft und ggf. via `/admin/reference-points`
> verschoben werden.

---

## Copy-Paste: nur Koordinaten (`lat, lon`)

Pro Region 7 Zeilen `lat, lon` — direkt in Admin-UI `/admin/reference-points`
Bulk-Paste-Textarea einfügbar.

### seeland_emmental
```
47.3556, 7.9168
46.9700, 7.4900
47.2340, 7.5910
47.1124, 7.8082
47.2046, 7.7987
47.0698, 7.4138
47.1400, 7.5651
```

### mittelland_west
```
46.9008, 7.3792
46.6785, 6.5352
46.9749, 6.8969
46.5303, 6.7763
46.8512, 6.9286
46.7287, 6.7375
46.9065, 7.0981
```

### mittelland_ost
```
47.4064, 8.6045
47.2759, 8.8510
47.4266, 8.4841
47.1602, 8.6635
47.3087, 8.5100
47.3187, 8.6538
47.1623, 9.0811
```

### genferseeregion
```
46.4900, 6.8500
46.5108, 6.8027
46.4285, 6.2993
46.5931, 6.5510
46.5011, 6.5103
46.2553, 6.1458
46.3775, 6.3291
```

### jura_ost
```
47.4661, 7.9678
47.3066, 6.9828
47.4661, 7.4049
47.3704, 7.6864
47.4363, 7.8125
47.4137, 7.1224
47.4126, 7.4939
```

### jura_west
```
47.1112, 7.0433
46.8960, 6.2186
47.1112, 6.5720
46.8540, 6.6120
46.9969, 6.6448
46.9183, 6.4456
47.0963, 6.8507
```

### jura_zentral
```
47.3577, 7.7073
47.2490, 7.0058
47.2128, 7.4067
47.2510, 7.5100
47.2249, 7.1343
47.2548, 7.2714
47.2906, 7.4228
```

### mittelland_zentral
```
47.0480, 8.4600
47.1582, 8.8999
47.0694, 8.3694
47.0250, 8.6346
47.1063, 8.7607
46.9787, 8.0242
47.0831, 8.5370
```

### glarnerland_walensee
```
47.1000, 9.3000
47.0939, 9.3912
47.0939, 9.0361
46.9114, 9.1781
47.0315, 9.2831
46.9734, 9.0225
47.0193, 9.1440
```

### schwarzsee_gantrisch
```
46.8730, 7.4068
46.6770, 7.2610
46.6067, 7.1825
46.7132, 6.9582
46.6280, 6.9873
46.6753, 7.1354
46.7523, 7.3034
```

### rheintal
```
47.5361, 9.7541
46.8213, 9.4307
47.2297, 9.3768
47.2297, 9.6463
47.3767, 9.6409
47.1920, 9.5222
46.9316, 9.4968
```

### bodenseeraum
```
47.5980, 9.6448
47.4727, 8.5480
47.8486, 9.0181
47.6440, 8.6710
47.6438, 9.0316
47.6447, 8.7575
47.5731, 9.3137
```

### waadtlaender_alpen
```
46.4098, 6.7524
46.3220, 7.0680
46.3542, 7.1963
46.1873, 6.8158
46.2830, 6.9570
46.3737, 6.8952
46.2714, 7.0358
```

### alpstein
```
47.4560, 8.7911
47.3176, 9.4649
47.1791, 9.0799
47.4099, 9.0799
47.2910, 9.3290
47.3566, 8.9854
47.2791, 9.1616
```

### tessin_zentral
```
46.1683, 8.4782
46.4633, 9.2423
46.2000, 8.7880
46.3650, 8.8057
46.2469, 9.0542
46.2134, 8.6665
46.2345, 8.8395
```

### praettigau_davos
```
46.8629, 10.0579
47.0249, 9.5896
46.8050, 9.8170
46.9709, 9.8572
46.8113, 9.8597
46.9369, 9.7371
46.8501, 9.7405
```

### berner_oberland
```
47.0777, 7.9379
46.7734, 7.4727
46.7734, 7.8050
47.0168, 7.6056
46.8280, 7.6955
46.8664, 7.5923
46.9512, 7.7630
```

### zentralschweizer_voralpen
```
46.8299, 7.9749
47.0290, 8.8844
46.9650, 8.6400
46.9626, 8.3647
46.8357, 8.5432
46.8774, 8.2900
46.8870, 8.7004
```

### berner_voralpen
```
46.7602, 8.4048
46.6302, 7.7952
46.7110, 7.7780
46.7602, 8.0565
46.6683, 8.0805
46.6612, 7.9127
46.6561, 8.2494
```

### freiburger_voralpen
```
46.4157, 7.0307
46.6045, 7.7930
46.6517, 7.3574
46.6930, 7.5380
46.5509, 7.6139
46.4793, 7.2293
46.5469, 7.4214
```

### mattertal_saastal
```
46.1510, 7.5860
46.1745, 7.9890
45.9606, 7.6806
46.0889, 7.4751
46.0957, 7.8564
46.0191, 7.4178
46.0705, 7.6750
```

### tessin_nord
```
46.5090, 8.8180
46.4444, 9.1221
46.5333, 8.7283
46.4889, 8.4329
46.4557, 8.9418
46.4249, 8.5907
46.4792, 8.7577
```

### zentralwallis
```
46.4110, 7.7710
46.5269, 8.1762
46.4106, 7.9793
46.4571, 7.8480
46.4988, 8.0534
46.4291, 7.8314
46.4610, 7.9627
```

### engadin_unter
```
46.4977, 9.0761
46.6642, 9.8250
46.6240, 9.7800
46.7197, 9.3971
46.6206, 9.6348
46.6376, 9.4628
46.5130, 9.5258
```

### unterwallis
```
46.0443, 6.9266
46.3349, 7.7541
46.3349, 7.2812
46.1220, 7.2330
46.2461, 7.4204
46.2054, 7.2786
46.2798, 7.5749
```

### oberwallis_goms
```
46.6255, 8.4408
46.4160, 8.1060
46.3441, 8.1837
46.4566, 8.3551
46.4040, 8.1785
46.3112, 7.9339
46.3342, 8.0362
```

### surselva
```
46.5854, 8.6627
46.8906, 9.3363
46.7420, 9.1580
46.7888, 8.9514
46.7565, 9.2307
46.6811, 8.8554
46.6926, 9.0914
```

### zentrales_mittelland
```
47.7103, 8.5267
47.0755, 7.9806
47.1662, 8.6177
47.5289, 8.0716
47.2449, 8.1667
47.3340, 8.2849
47.4973, 8.2764
```

### engadin_ober
```
46.5011, 9.7124
46.6308, 10.2544
46.7605, 9.9834
46.5210, 9.9020
46.6243, 10.0564
46.4876, 9.9017
46.5371, 10.0240
```

---

## Copy-Paste-Block für `MANUAL_REFERENCE_POINTS`

```python
MANUAL_REFERENCE_POINTS = {
    "seeland_emmental": [
        [47.3556, 7.9168],   # Edge-O
        [46.9700, 7.4900],   # Flughöhe-S
        [47.2340, 7.5910],   # Edge-N (Schatten)
        [47.1124, 7.8082],   # Edge-O
        [47.2046, 7.7987],   # Edge-O
        [47.0698, 7.4138],   # Innen-Sample
        [47.1400, 7.5651],   # Edge-W
    ],
    "mittelland_west": [
        [46.9008, 7.3792],   # Edge-O
        [46.6785, 6.5352],   # Edge-W
        [46.9749, 6.8969],   # Edge-N (Schatten)
        [46.5303, 6.7763],   # Flughöhe-S (auto)
        [46.8512, 6.9286],   # Innen-Sample
        [46.7287, 6.7375],   # Innen-Sample
        [46.9065, 7.0981],   # Innen-Sample
    ],
    "mittelland_ost": [
        [47.4064, 8.6045],   # Edge-W
        [47.2759, 8.8510],   # Edge-O
        [47.4266, 8.4841],   # Edge-W
        [47.1602, 8.6635],   # Flughöhe-S (auto)
        [47.3087, 8.5100],   # Edge-W
        [47.3187, 8.6538],   # Innen-Sample
        [47.1623, 9.0811],   # Edge-O
    ],
    "genferseeregion": [
        [46.4900, 6.8500],   # Flughöhe-S
        [46.5108, 6.8027],   # Edge-O
        [46.4285, 6.2993],   # Edge-N (Schatten)
        [46.5931, 6.5510],   # Edge-N (Schatten)
        [46.5011, 6.5103],   # Innen-Sample
        [46.2553, 6.1458],   # Edge-W
        [46.3775, 6.3291],   # Edge-W
    ],
    "jura_ost": [
        [47.4661, 7.9678],   # Edge-O
        [47.3066, 6.9828],   # Flughöhe-S (auto)
        [47.4661, 7.4049],   # Edge-W
        [47.3704, 7.6864],   # Edge-O
        [47.4363, 7.8125],   # Edge-O
        [47.4137, 7.1224],   # Edge-W
        [47.4126, 7.4939],   # Edge-O
    ],
    "jura_west": [
        [47.1112, 7.0433],   # Edge-O
        [46.8960, 6.2186],   # Edge-W
        [47.1112, 6.5720],   # Edge-N (Schatten)
        [46.8540, 6.6120],   # Flughöhe-S
        [46.9969, 6.6448],   # Innen-Sample
        [46.9183, 6.4456],   # Innen-Sample
        [47.0963, 6.8507],   # Edge-O
    ],
    "jura_zentral": [
        [47.3577, 7.7073],   # Edge-O
        [47.2490, 7.0058],   # Edge-W
        [47.2128, 7.4067],   # Edge-O
        [47.2510, 7.5100],   # Flughöhe-S
        [47.2249, 7.1343],   # Innen-Sample
        [47.2548, 7.2714],   # Innen-Sample
        [47.2906, 7.4228],   # Edge-O
    ],
    "mittelland_zentral": [
        [47.0480, 8.4600],   # Flughöhe-S
        [47.1582, 8.8999],   # Edge-O
        [47.0694, 8.3694],   # Edge-W
        [47.0250, 8.6346],   # Edge-O
        [47.1063, 8.7607],   # Edge-O
        [46.9787, 8.0242],   # Edge-W
        [47.0831, 8.5370],   # Edge-O
    ],
    "glarnerland_walensee": [
        [47.1000, 9.3000],   # Flughöhe-S
        [47.0939, 9.3912],   # Edge-O
        [47.0939, 9.0361],   # Edge-W
        [46.9114, 9.1781],   # Edge-S
        [47.0315, 9.2831],   # Innen-Sample
        [46.9734, 9.0225],   # Innen-Sample
        [47.0193, 9.1440],   # Innen-Sample
    ],
    "schwarzsee_gantrisch": [
        [46.8730, 7.4068],   # Edge-O
        [46.6770, 7.2610],   # Flughöhe-S
        [46.6067, 7.1825],   # Edge-S
        [46.7132, 6.9582],   # Edge-W
        [46.6280, 6.9873],   # Innen-Sample
        [46.6753, 7.1354],   # Innen-Sample
        [46.7523, 7.3034],   # Innen-Sample
    ],
    "rheintal": [
        [47.5361, 9.7541],   # Edge-N (Schatten)
        [46.8213, 9.4307],   # Flughöhe-S (auto)
        [47.2297, 9.3768],   # Edge-W
        [47.2297, 9.6463],   # Edge-O
        [47.3767, 9.6409],   # Innen-Sample
        [47.1920, 9.5222],   # Edge-W
        [46.9316, 9.4968],   # Innen-Sample
    ],
    "bodenseeraum": [
        [47.5980, 9.6448],   # Edge-O
        [47.4727, 8.5480],   # Edge-W
        [47.8486, 9.0181],   # Edge-N (Schatten)
        [47.6440, 8.6710],   # Flughöhe-S
        [47.6438, 9.0316],   # Innen-Sample
        [47.6447, 8.7575],   # Innen-Sample
        [47.5731, 9.3137],   # Innen-Sample
    ],
    "waadtlaender_alpen": [
        [46.4098, 6.7524],   # Edge-W
        [46.3220, 7.0680],   # Flughöhe-S
        [46.3542, 7.1963],   # Edge-O
        [46.1873, 6.8158],   # Edge-W
        [46.2830, 6.9570],   # Innen-Sample
        [46.3737, 6.8952],   # Innen-Sample
        [46.2714, 7.0358],   # Innen-Sample
    ],
    "alpstein": [
        [47.4560, 8.7911],   # Edge-W
        [47.3176, 9.4649],   # Edge-O
        [47.1791, 9.0799],   # Edge-S
        [47.4099, 9.0799],   # Edge-N (Schatten)
        [47.2910, 9.3290],   # Flughöhe-S (Kronberg-S)
        [47.3566, 8.9854],   # Edge-W
        [47.2791, 9.1616],   # Innen-Sample
    ],
    "tessin_zentral": [
        [46.1683, 8.4782],   # Edge-W
        [46.4633, 9.2423],   # Edge-O
        [46.2000, 8.7880],   # Flughöhe-S
        [46.3650, 8.8057],   # Edge-N (Schatten)
        [46.2469, 9.0542],   # Edge-O
        [46.2134, 8.6665],   # Edge-W
        [46.2345, 8.8395],   # Innen-Sample
    ],
    "praettigau_davos": [
        [46.8629, 10.0579],   # Edge-O
        [47.0249, 9.5896],   # Edge-W
        [46.8050, 9.8170],   # Flughöhe-S
        [46.9709, 9.8572],   # Edge-N (Schatten)
        [46.8113, 9.8597],   # Innen-Sample
        [46.9369, 9.7371],   # Innen-Sample
        [46.8501, 9.7405],   # Innen-Sample
    ],
    "berner_oberland": [
        [47.0777, 7.9379],   # Edge-O
        [46.7734, 7.4727],   # Flughöhe-S (auto)
        [46.7734, 7.8050],   # Edge-S
        [47.0168, 7.6056],   # Edge-N (Schatten)
        [46.8280, 7.6955],   # Innen-Sample
        [46.8664, 7.5923],   # Innen-Sample
        [46.9512, 7.7630],   # Innen-Sample
    ],
    "zentralschweizer_voralpen": [
        [46.8299, 7.9749],   # Edge-W
        [47.0290, 8.8844],   # Edge-O
        [46.9650, 8.6400],   # Flughöhe-S
        [46.9626, 8.3647],   # Edge-W
        [46.8357, 8.5432],   # Edge-O
        [46.8774, 8.2900],   # Edge-W
        [46.8870, 8.7004],   # Innen-Sample
    ],
    "berner_voralpen": [
        [46.7602, 8.4048],   # Edge-O
        [46.6302, 7.7952],   # Edge-W
        [46.7110, 7.7780],   # Flughöhe-S
        [46.7602, 8.0565],   # Edge-N (Schatten)
        [46.6683, 8.0805],   # Innen-Sample
        [46.6612, 7.9127],   # Innen-Sample
        [46.6561, 8.2494],   # Innen-Sample
    ],
    "freiburger_voralpen": [
        [46.4157, 7.0307],   # Edge-W
        [46.6045, 7.7930],   # Edge-O
        [46.6517, 7.3574],   # Edge-N (Schatten)
        [46.6930, 7.5380],   # Flughöhe-S
        [46.5509, 7.6139],   # Edge-O
        [46.4793, 7.2293],   # Edge-W
        [46.5469, 7.4214],   # Innen-Sample
    ],
    "mattertal_saastal": [
        [46.1510, 7.5860],   # Flughöhe-S
        [46.1745, 7.9890],   # Edge-O
        [45.9606, 7.6806],   # Edge-S
        [46.0889, 7.4751],   # Edge-W
        [46.0957, 7.8564],   # Innen-Sample
        [46.0191, 7.4178],   # Edge-W
        [46.0705, 7.6750],   # Innen-Sample
    ],
    "tessin_nord": [
        [46.5090, 8.8180],   # Flughöhe-S
        [46.4444, 9.1221],   # Edge-O
        [46.5333, 8.7283],   # Edge-N (Schatten)
        [46.4889, 8.4329],   # Edge-W
        [46.4557, 8.9418],   # Edge-O
        [46.4249, 8.5907],   # Innen-Sample
        [46.4792, 8.7577],   # Edge-N (Schatten)
    ],
    "zentralwallis": [
        [46.4110, 7.7710],   # Flughöhe-S
        [46.5269, 8.1762],   # Edge-O
        [46.4106, 7.9793],   # Edge-S
        [46.4571, 7.8480],   # Edge-W
        [46.4988, 8.0534],   # Edge-O
        [46.4291, 7.8314],   # Edge-W
        [46.4610, 7.9627],   # Edge-O
    ],
    "engadin_unter": [
        [46.4977, 9.0761],   # Edge-W
        [46.6642, 9.8250],   # Edge-O
        [46.6240, 9.7800],   # Flughöhe-S
        [46.7197, 9.3971],   # Edge-N (Schatten)
        [46.6206, 9.6348],   # Edge-O
        [46.6376, 9.4628],   # Innen-Sample
        [46.5130, 9.5258],   # Innen-Sample
    ],
    "unterwallis": [
        [46.0443, 6.9266],   # Edge-W
        [46.3349, 7.7541],   # Edge-O
        [46.3349, 7.2812],   # Edge-N (Schatten)
        [46.1220, 7.2330],   # Flughöhe-S
        [46.2461, 7.4204],   # Innen-Sample
        [46.2054, 7.2786],   # Edge-W
        [46.2798, 7.5749],   # Innen-Sample
    ],
    "oberwallis_goms": [
        [46.6255, 8.4408],   # Edge-O
        [46.4160, 8.1060],   # Flughöhe-S
        [46.3441, 8.1837],   # Edge-O
        [46.4566, 8.3551],   # Edge-O
        [46.4040, 8.1785],   # Edge-O
        [46.3112, 7.9339],   # Innen-Sample
        [46.3342, 8.0362],   # Innen-Sample
    ],
    "surselva": [
        [46.5854, 8.6627],   # Edge-W
        [46.8906, 9.3363],   # Edge-O
        [46.7420, 9.1580],   # Flughöhe-S
        [46.7888, 8.9514],   # Edge-W
        [46.7565, 9.2307],   # Innen-Sample
        [46.6811, 8.8554],   # Innen-Sample
        [46.6926, 9.0914],   # Innen-Sample
    ],
    "zentrales_mittelland": [
        [47.7103, 8.5267],   # Edge-N (Schatten)
        [47.0755, 7.9806],   # Flughöhe-S (auto)
        [47.1662, 8.6177],   # Edge-O
        [47.5289, 8.0716],   # Edge-W
        [47.2449, 8.1667],   # Innen-Sample
        [47.3340, 8.2849],   # Innen-Sample
        [47.4973, 8.2764],   # Innen-Sample
    ],
    "engadin_ober": [
        [46.5011, 9.7124],   # Edge-W
        [46.6308, 10.2544],   # Edge-O
        [46.7605, 9.9834],   # Edge-N (Schatten)
        [46.5210, 9.9020],   # Flughöhe-S
        [46.6243, 10.0564],   # Innen-Sample
        [46.4876, 9.9017],   # Innen-Sample
        [46.5371, 10.0240],   # Innen-Sample
    ],
}
```

---

## Verwendung dieser Liste

1. Den Copy-Paste-Block oben als komplettes `MANUAL_REFERENCE_POINTS`-Dict in
   `scripts/create_regionen_geojson.py` einsetzen — oder pro Region die 7 Zeilen
   `lat, lon` im Admin-UI `/admin/reference-points` per Bulk-Paste übernehmen.
2. Bei Script-Pfad: `python scripts/create_regionen_geojson.py` ausführen.
3. Flask neu starten (Cache-Invalidierung in `source_area._load_regions()`).
4. Verifikation auf `/regionen`-Karte (`SHOW_REFERENCE_POINTS`-Toggle).

> **Hinweis**: Aktuelle Liste basiert auf den 7 produktiv genutzten auto-
> generierten Punkten (4 Edge + 3 CVT) plus eingesetztem validierten S-Anker wo
> möglich. Manuelle Verschiebungen über das Admin-UI sind jederzeit möglich.