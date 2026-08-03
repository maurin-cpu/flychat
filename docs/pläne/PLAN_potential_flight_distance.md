# Plan: Potential Flight Distance (PFD) — XC-Potenzial in km

**Stand:** 2026-07-04 · **Status:** Recherche abgeschlossen (Web + Code), **Umsetzung nicht gestartet** · **Neuer Code:** `scripts/potential_flight_distance.py` (Phase 1), später `engine/pfd.py` · **Ground Truth:** `validation/xcontest/observations.csv` (Spalte `best_km`, ~1460 Zeilen)

**Wiederaufnahme (HIER starten):**
1. Diese Datei lesen — Formeln und Parameter sind aus der Web-Recherche 2026-07-04 belegt (Quellen am Ende), die Code-Anknüpfpunkte wurden am selben Tag verifiziert.
2. Eiserne Regel (wie im Thermikmodell-Plan): **jede Parameterwahl gegen `validation/xcontest/observations.csv` kalibrieren**, nie Konstanten isoliert drehen.
3. Reihenfolge: Phase 1 (Standalone-Skript) → Phase 2 (Kalibrierung) → Phase 3 (Integration). Phase 1+2 sind unabhängig von der Analyse-Pipeline und risikofrei.
4. Abhängigkeit beachten: Die Steigraten-Kette wird lt. `PLAN_thermikmodell_optimierung.md` (P1) evtl. auf subtraktiv umgestellt — die PFD nutzt `climb_rate` als Input. Nach P1-Umsetzung **Rekalibrierung der PFD nötig** (nur `c_region`/`pilot_factor` neu fitten, Formeln bleiben).

---

## Worum geht es?

Heute liefert das System nur **qualitative** XC-Aussagen: `xc_potential` (high/moderate/low), `streckenflug.rating` (1–5) und km-Klassen als Prosa in den LLM-Skills (`skills/shared/de/04_flyability/…`: „Hausrunde ~20km", „XC 30–100km"). Es gibt **keinen berechneten km-Wert**. Ziel: ein Python-Skript, das pro Tag und Spot/Region eine **potenzielle Flugdistanz in km** berechnet — dieselbe Größe, die XC Therm und burnair als „PFD" ausgeben.

Alle Bausteine existieren bereits:

| Baustein | Quelle im Code |
|---|---|
| Steigrate pro Stunde (`climb_rate`), Thermik-Top (`max_height`), Basis (`lcl`) | `thermik_calculator.py` → `compute_daily_thermals()`, archiviert in `data/weather_archive/*.json` → `hourly_flight` |
| Arbeitshöhe über Start (`working_height_agl_m`), produktive Stunden (`productive_thermal_h`), `sustained_peak_mps` | `engine/weather_context.py:1508 ff.`, persistiert als `_rating_inputs` (`engine/analyzers.py:2117`) |
| Höhenwind / BL-Wind, B/S-Ratio | `engine/weather_context.py`: `_calculate_bl_mean_wind` (Z.1017), `_calculate_bs_ratio` (Z.1002) |
| Spot-Geometrie (lat/lon, elevation, Startrichtung) | `data/fluggebiete_dhv.csv` via `spots.py` |
| **Echte geflogene km (Ground Truth)** | `validation/xcontest/observations.csv`: `best_km` + alle `wx_*`-Features + `our_*`-Ratings |

---

## Recherche-Ergebnis: Wie rechnen die anderen?

### Stand der Technik (Kurzfassung)

- **XC Therm / burnair (Regtherm, von Känel/Liechti)** — das Referenzprodukt. Rechnet die PFD in **30-Minuten-Intervallen** über das Thermikfenster. Ein Intervall trägt nur km bei, wenn zwei **Gates** erfüllt sind: **Arbeitshöhe ≥ 900 m** und **integriertes Steigen ≥ 0,8 m/s** (Eigensinken bereits abgezogen). Wind an der Basis reduziert die PFD (Return-Task: Hin- und Rückschenkel), **Gleitschirm-Cap bei ~30 km/h Wind** (darüber 0 km). Pilotenlevel = simpler Prozentfaktor. Explizit NICHT drin: Föhn, Talwind, Niederschlag — burnair warnt selbst, die PFD sei nur ein grober Tagesgüte-Index neben der separaten Fliegbarkeits-Ampel.
- **RASP/DrJack** — liefert keinen km-Wert, aber die Bausteine: w*, **Hcrit** (Höhe, wo Steigen unter ~1,15 m/s fällt = „nutzbare Kurbelhöhe", Pendant zu unserer Arbeitshöhe) und **B/S-Ratio** (≤ 5 → Thermik vom Wind zerrissen/unbrauchbar → Kill-Kriterium).
- **XCSkies „XC Potential"** — Komposit-Ampel aus B/S, BL-Wind, Thermikstärke, Mindest-Arbeitshöhe; kein km-Wert.
- **SkySight „XC Speed"** — MacCready-basiert, gerätespezifisch (inkl. PG), proprietär.
- **Paraglidable (Meler)** — reines ML (NN auf GFS-Leveldaten, trainiert auf >1 Mio. XContest-Flüge), liefert Scores `flyability`/`crossability`, keinen km-Wert. Wichtige Lehre: modelliert explizit den **Wochentag-/Saison-Bias** der Pilotenpopulation.
- **Verifikationsliteratur (ALPTHERM, Liechti 2007, Hindman 2007):** Reine MacCready-PFD streut **±15–37 %** (Wolkenstraßen → Unterschätzung, Fronten → Überschätzung). Und: Korrelation prognostiziertes ↔ echtes Steigen nur **r = 0,41**, aber **erreichte Höhe r = 0,88** → **die Arbeitshöhe ist der verlässlichste Prädiktor**, nicht der Steigwert. Konsequenz: km als Bandbreite/Klasse ausgeben, nicht als Punktwert.

### Das Rechenmodell (Steig-/Gleit-Zyklus, MacCready-vereinfacht)

Pro Zeitintervall die erzielbare Reisegeschwindigkeit aus Eigenfahrt, effektiver Gleitzahl und effektivem Steigen:

```
V_xc = (V_glide · L_eff · w_eff) / (L_eff · w_eff + V_glide)      [Eigenfahrt ohne Wind]
```

Herleitung: Zyklus mit Höhenband Δh → Gleitstrecke L_eff·Δh, Gleitzeit L_eff·Δh/V_glide, Kurbelzeit Δh/w_eff; Δh kürzt sich. Die Arbeitshöhe wirkt daher **nicht direkt** auf V_xc, sondern über die Gates (und real über geringere Suchverluste — deshalb ist sie trotzdem der beste Prädiktor, s. o.).

**Gleitschirm-Parameter (EN-B, aus der Recherche):**

| Parameter | Startwert | Bedeutung |
|---|---|---|
| `V_glide` | 10,5 m/s (38 km/h) | Trimmspeed |
| `L_eff` | 6,5 | effektive Gleitzahl inkl. Such-/Zentrierverluste (still air 8–9) |
| `w_eff` | `climb_rate` des Intervalls | unser Wert ist bereits „erzielbares Steigen" (Kalibrier-Anker kk7: 1,3 m/s Mittel) |
| Plausi-Check | w_eff=1,5 → V_xc ≈ 20 km/h | deckt sich mit XContest-Realität |

**Wind** (BL-Mittelwind `u` des Intervalls):

```
oneway:  V_ground = V_xc + u                      # freie Strecke, voller Versatz-Bonus
return:  V_ground = V_xc · (1 − (u/V_xc)²)        # Dreieck/Retour; u ≥ V_xc → 0
cap:     u > 30 km/h → Intervall = 0 km           # XC-Therm-Gleitschirmregel
```

Default-Ausgabe: **Return-Modus** (konservativ, entspricht burnair); oneway optional als zweiter Wert.

**Tagesdistanz:**

```python
PFD_km = pilot_factor * c_region * sum(
    V_ground(t) * dt
    for t in flugstunden                     # weather_archive: hourly_flight 08:00–...
    if working_height_agl(t) >= H_GATE       # Start: 900 m (XC Therm); ggf. auf AGL-Bänder der Skills mappen
    and climb_rate(t)        >= W_GATE       # Start: 0.8 m/s
    and wind_bl(t)           <= 30 km/h
    and bs_ratio(t)          >  BS_KILL      # Start: 5 (RASP); optionales Kill-Kriterium
)
# pilot_factor: 1.0 = Top-Pilot (kalibriert auf best_km = Tagesbester!), Ausgabe zusätzlich
#               als "guter Hobbypilot" ≈ 0.5 (XC-Therm-Pilotenlevel-Logik)
# c_region:     Regionsfaktor aus Phase 2 (Median-Ratio echte km / Roh-PFD)
```

Plausibilisierung: 6 h über den Gates × 25 km/h ≈ 150 km (Alpen-Hammertag); 3 h × 15 km/h ≈ 45 km (Normaltag).

### Entschiedener Ansatz: Hybrid (Physik + Regionskalibrierung)

- **Physikalischer Kern** (oben) — interpretierbar, funktioniert ab Tag 1 ohne Trainingsdaten, identisch zur XC-Therm-Methodik.
- **Ein multiplikativer Kalibrierfaktor `c_region`** aus `observations.csv`: Median-Ratio `best_km / PFD_roh` über alle Tage einer Region mit Flügen. Robust ab ~20–30 Tagen pro Region. Fängt genau die ±15–37 %-Systematik ab (Wolkenstraßen-Routen, Talwind-Autobahnen, Geländekanalisation), die das reine Zyklusmodell nicht kennt.
- **Kein ML in diesem Plan.** Der Gradient-Boosting-Layer ist im Thermikmodell-Plan (Langfrist-Abschnitt) bereits vorgesehen und erst nach dessen P1/P3 sinnvoll (sonst lernt das ML die Steigraten-Bugs mit). Die PFD liefert dafür später ein sauberes physikalisches Basis-Feature.

---

## Umsetzung

### Phase 1 — Standalone-Skript `scripts/potential_flight_distance.py` (Kern)

Bewusst als Skript ohne Pipeline-Anbindung, damit Berechnung + Kalibrierung ohne Prod-Risiko iterierbar sind (gleiche Philosophie wie `debug_scripts/topout_vs_percentile.py`).

1. **Input:** `data/weather_archive/<datum>.json` (hat pro Spot/Region alle `hourly_flight`-Stunden mit `climb_rate`, `max_height`, `lcl`, Wind, plus Spot-Metadaten) — für Live-Betrieb später `data/wetterdaten.json`, gleiche Struktur.
2. **Pro Intervall ableiten:** `working_height_agl = max(0, min(max_height, lcl) − elevation_m)`; BL-Wind (falls im Archiv nicht direkt vorhanden: aus `wind_speed_10m` + Gust-Heuristik, sauberer: Berechnung aus `engine/weather_context.py::_calculate_bl_mean_wind` importieren/extrahieren).
3. **Gates + V_xc + Windformel** wie oben; Summe über Flugstunden (dt = 1 h, Archiv ist stündlich — feiner als 30 min geht mit unseren Daten nicht, ist für die Genauigkeitsklasse egal).
4. **Output:** JSON/CSV pro Spot und Region: `pfd_km_return`, `pfd_km_oneway`, `pfd_km_hobby` (×0,5), `gate_hours` (wie viele Stunden trugen bei), `limiting_gate` (welches Gate hat am meisten Stunden gekillt — direkt als `limiting_factor`-Erklärung verwendbar).
5. **Konstanten in ein `PFD_PARAMS`-Dict** am Dateikopf (später `config.py`), damit Phase 2 sie fitten kann.
6. CLI: `python scripts/potential_flight_distance.py --date 2026-07-01 [--spot X | --region Y]`.

**Aufwand:** klein (ein Nachmittag). Kein Risiko, kein Prod-Kontakt.

### Phase 2 — Kalibrierung gegen XContest (die eigentliche Arbeit)

1. **Backfill:** Skript über alle Tage laufen lassen, für die `weather_archive` UND `observations.csv`-Einträge existieren; Join über (date, spot/region).
2. **Auswertung** (neues Skript `scripts/pfd_calibration.py` oder Notebook):
   - Scatter + Korrelation `PFD_roh` vs. `best_km` (Erwartung aus Literatur: r deutlich über dem Steigraten-r von 0,41, weil Arbeitshöhe dominiert).
   - `c_region` = Median(`best_km` / `PFD_roh`) pro Region (nur Tage mit Flügen ≥ 10 km, sonst dominiert „niemand ist geflogen/Wochentag-Bias" — Paraglidable-Lehre: `best_km` misst auch Pilotenaktivität, nicht nur Wetter. Deshalb NICHT auf Null-Tage fitten).
   - Gates prüfen: bringt H_GATE 900 m auf unsere AGL-Verteilung die beste Trennung fliegbar/XC? Ggf. gegen die bestehenden Skill-AGL-Bänder (<400/400–800/800–1500/≥1500) stellen.
   - Fehlerband bestimmen → daraus die **Ausgabe-Bandbreite** (z. B. ±30 %) und die Klassengrenzen ableiten, konsistent mit den bestehenden Prosa-Klassen (Hausrunde / 10–30 / 30–100 / >100 km).
3. **Abnahmekriterium:** kalibrierte PFD klassifiziert die `observations.csv`-Tage besser in die km-Klassen als das heutige `streckenflug.rating` allein (Confusion-Matrix beider Ansätze vergleichen).

**Aufwand:** mittel — Kern der Arbeit, analog Topout-Kalibrier-Session.

### Phase 3 — Integration (erst nach erfolgreicher Phase 2)

1. Berechnung nach `engine/pfd.py` verschieben, Aufruf in `engine/weather_context.py::_build_single_spot_context` neben den bestehenden Aggregaten; Ergebnis in `_rating_inputs` aufnehmen (`pfd_km`, `pfd_band`, `limiting_gate`).
2. **LLM-Kontext:** PFD als Zahl+Bandbreite in den Kontext-Block geben, damit die km-Prosa der Skills auf einer berechneten Größe statt auf Faustregeln beruht. Achtung Parroting-Lehre (Fix d35dbe4): als echten Kontext-Block mit Template-Hinweis, nicht als Few-Shot-Zahl.
3. API/Anzeige: Feld in `web.py` (neben `xc_rating`), Ausgabe **als Klasse/Bandbreite**, nie als Punktwert („~40–70 km möglich").
4. Nach Deploy: `sudo systemctl restart wingcast` (Lehre aus not_safe-Fix — Engine läuft in-process).

**Aufwand:** klein–mittel; erst starten, wenn Phase 2 das Abnahmekriterium erfüllt.

---

## Bewusst NICHT in diesem Plan

- **Föhn/Talwind/Niederschlag in der PFD** — macht das Vorbild (Regtherm) auch nicht; unsere Fliegbarkeits-Ampel (decision_engine) killt solche Tage bereits vorher. PFD nur für Tage rechnen/anzeigen, die fliegbar sind.
- **Routen-/Geländegeometrie** (Skyways, Startrichtung × Windrichtung) — zweite Ausbaustufe, erst wenn die skalare PFD validiert ist.
- **ML-Distanzmodell** — siehe Thermikmodell-Plan, Langfrist-Abschnitt; blockiert durch dessen P1/P3.

---

## Umsetzungs-Checkliste

| # | Punkt | Aufwand | Risiko | Braucht Kalibrierung |
|---|-------|---------|--------|----------------------|
| 1 | Phase 1: `scripts/potential_flight_distance.py` | klein | keins | nein (Literatur-Startwerte) |
| 2 | Phase 2: Backfill + `c_region`-Fit + Gate-Check | mittel | keins | **ja (Kern der Arbeit)** |
| 3 | Phase 2: Abnahme vs. `streckenflug.rating` | klein | keins | — |
| 4 | Phase 3: `engine/pfd.py` + `_rating_inputs` | klein–mittel | klein | nein |
| 5 | Phase 3: LLM-Kontext + web.py + Restart | klein | klein (Parroting beachten) | nein |
| 6 | Nach Thermik-P1: `c_region`/Gates rekalibrieren | klein | — | ja |

---

## Quellen (Recherche 2026-07-04)

- XC Therm FAQ (PFD-Definition, Gates 900 m / 0,8 m/s, 30-km/h-Cap, Pilotenlevel): https://xctherm.com/de/fragen · Regtherm: https://xctherm.com/en/regtherm
- burnair PFD-Wert (nur Integralsteigen + Basiswind, Return-Dreieck; Warnung „grober Index"): https://help.burnair.cloud/hc/de/articles/21153410206749
- Rechenkern-Rekonstruktion (Steig-/Gleit-Zyklus): https://www.gleitschirmdrachenforum.de/forum/gleitschirm-und-drachen-forum/wetter/936735
- RASP/DrJack (w*, Hcrit ~1,15 m/s, B/S-Ratio ≤ 5 = unbrauchbar): http://www.drjack.info/rasp/info/parameters.html
- XCSkies XC-Potential-Komposit: https://docs.xcskies.com/home/documentation/xc-skies-layers
- ALPTHERM-Verifikation (±15–37 % Fehler; Steigen r=0,41 vs. Höhe r=0,88): https://streckenflug.at/download/Bac_Richter_final.pdf (Richter-Trummer, Uni Innsbruck 2011)
- Paraglidable (ML auf XContest, Populations-Bias): https://github.com/AntoineMeler/Paraglidable
- MacCready/Speed-to-fly-Grundlagen: https://en.wikipedia.org/wiki/Speed_to_fly · Reichmann, „Cross-Country Soaring"
- SkySight XC Speed (PG-Modus): https://skysight.io/ · thermal.kk7 (Routen-Prior, 2. Ausbaustufe): https://thermal.kk7.ch/
