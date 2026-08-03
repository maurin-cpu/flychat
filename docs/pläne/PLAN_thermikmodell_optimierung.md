# Plan: Thermikmodell-Optimierung (Review Juli 2026)

**Stand:** 2026-07-03 · **Status:** Review abgeschlossen (2026-07-02, Code-Analyse + Literatur-Recherche), **Umsetzung nicht gestartet** · **Betroffener Code:** `thermik_calculator.py`, `config.py`, `fetch_weather.py`, `docs/THERMIK_MODELL.md`

**Wiederaufnahme (HIER starten):**
1. Diese Datei lesen — die Befunde sind verifiziert (Code-Zeilen am 2026-07-03 gegengeprüft), Prioritäten sind entschieden.
2. Eiserne Regel für ALLE Parameter-Änderungen: **immer gegen `validation/xcontest/` kalibrieren** (Topout-P75-Methode wie in `validation/xcontest/TOPOUT_STICHPROBE.md` + `debug_scripts/topout_vs_percentile.py`). Nie einen Parameter isoliert drehen — sonst Whack-a-Mole.
3. Empfohlene Reihenfolge: erst P2 (schnelle, risikofreie Aufräumer), dann P1 (größter Hebel, braucht Kalibrier-Session), dann P3 (nur gemeinsam kalibrierbar), P4 nach Bedarf.
4. Nach jedem Engine-Fix: `sudo systemctl restart wingcast` — die Analyse-Pipeline läuft in-process, Fixes werden sonst nicht wirksam (Lehre aus dem not_safe-Fix 02b7646).

---

## Worum geht es?

Das Thermikmodell (Deardorff-w*, Parcel-Aufstieg mit Entrainment, Climb-Faktoren) wurde systematisch gegen den Stand der Technik (RASP/BLIPMAP, Young 1988, Romps & Charn, ALPTHERM, kk7-Statistiken) geprüft. Ergebnis in einem Satz:

> **Die Architektur ist solide und literaturkonform — aber die Steigraten-Kette überschätzt schwache Tage systematisch, vier kleine Bugs/Leichen kosten Vertrauen und CPU, und zwei Parcel-Parameter kompensieren sich gegenseitig, statt einzeln richtig zu sein.**

Was als **korrekt bestätigt** wurde, steht am Ende — das wird NICHT angefasst.

---

## P1 — Steigraten-Kette: multiplikativ → subtraktiv (größter Hebel)

**Befund:** Die gemeldete Steigrate entsteht heute als Kette von Multiplikatoren:

```
climb = w* × 1.45 (Kern-Skalierung)          thermik_calculator.py:1330-1332
             × climb_factor 0.60–0.85 (Saison)   config.py:517-522, Anwendung ~1344
             × terrain 0.95–1.15                 config.py:658 ff.
      ≈ 0.9–1.4 · w*
```

Die Literatur rechnet anders: Kern-Steigen ≈ **0.56 · w*** (Young 1988), und RASP zieht davon **subtraktiv** das Eigensinken ab (Steigen ≈ 0.5–0.6·w* − ~1.0–1.1 m/s; RASP nutzt Hcrit 225 ft/min als Nutzbarkeitsschwelle). Der Unterschied ist kein Skalierungsdetail:

- **Multiplikativ:** halber w* → halbes Steigen. Ein schwacher Tag (w* = 1.5 m/s) liefert immer noch ~1.5–2 m/s Anzeige.
- **Subtraktiv:** halber w* → Steigen bricht überproportional ein (0.56 × 1.5 − 1.0 ≈ −0.2 m/s → nicht kurbelbar). Genau das entspricht der Realität an schwachen Tagen.

**Kalibrier-Anker** (aus der Recherche, nicht verlieren):
- kk7 misst **1.3 m/s mittleres PG-Steigen** über alle Flüge.
- `observations.csv`: Median `climb_max` = **2.5 m/s**.
- Eine publizierte Regression Forecast-w* ↔ Tracklog-Steigen existiert **nicht** — das ist eine echte Lücke, die wir mit eigenen Daten füllen können (und müssen).

**Was anpassen:**
1. Subtraktives Schema als Alternative implementieren (hinter Config-Schalter, analog `FORECAST_DAYS`-Muster): `climb = a·w* − sink`, Startwerte a=0.56, sink=1.05 m/s, Untergrenze 0.
2. Beide Schemata gegen IGC/XContest-Steigwerte laufen lassen (Topout-P75-Analogie: Steigraten-Perzentile pro Tag/Region aus Tracklogs vs. Forecast).
3. `a` und `sink` aus der Regression fitten, dann entscheiden, ob das multiplikative Schema ersetzt wird.

**Aufwand:** Implementierung klein; die Arbeit ist die Kalibrier-Session.

---

## P2 — Bugs und tote Pfade (schnell, risikofrei)

### 2.1 `surface_sensible_heat_flux` wird nie angefragt
`fetch_weather.py` fragt die Variable bei Open-Meteo **nicht** an → `H` läuft **immer** über den Strahlungs-Fallback. Folge: `h_is_estimated` (thermik_calculator.py:684) bleibt strukturell `False`, obwohl H faktisch immer geschätzt ist — das Diagnostik-Feld lügt, und die Warnung „Kein sensibler Wärmefluss verfügbar" (~Zeile 745) kann nie feuern.
**Entscheid nötig:** Entweder (a) Variable bei der API mitanfragen (prüfen, ob icon_seamless sie liefert und was sie taugt) oder (b) den Primärpfad ehrlich entfernen und `h_is_estimated` korrekt setzen. Option (b) ist der sichere Default.

### 2.2 Verworfener `calculate_thermal_profile()`-Aufruf
`fetch_weather.py:787` ruft `calculate_thermal_profile()` auf und **verwirft das Ergebnis** — die echte Pipeline läuft über `compute_daily_thermals`. Reiner CPU-Verbrauch ohne Effekt. **→ Aufruf löschen.**

### 2.3 DWD-Updraft-Blending: Kommentar sagt aus, Config sagt an
Code-Kommentar behauptet „default deaktiviert", aber `config.py:532` setzt `use_dwd_updraft_blending: True` (mit `dwd_updraft_scale: 2.0`) — das Blending ist **live** und kann Climb nur erhöhen. **Entscheid nötig:** bewusst an (dann Kommentar fixen und in die P1-Kalibrierung einbeziehen) oder aus (dann Config auf False). Nicht stillschweigend lassen.

### 2.4 Doku-Drift `docs/THERMIK_MODELL.md`
Beschreibt vier Dinge, die es nicht mehr gibt bzw. anders sind: entfernter Vigor, entfernte CIN-Bremse (Commit 3dba99a), harter H-Schwellenwert (jetzt Ramp), alte LCL-Faustformel (jetzt Bolton), climb_factor 0.5–0.85 (jetzt 0.60–0.85). **→ Nach Abschluss von P1–P3 in einem Zug aktualisieren**, nicht vorher (sonst zweimal Arbeit).

---

## P3 — Parcel-Methode: doppelt großzügig (nur GEMEINSAM kalibrieren)

**Befund A — Gratis-Toleranz:** Der Paketaufstieg lässt Schichten mit ΔT ∈ (−0.5, 0) K passieren (thermik_calculator.py:916 „Labile Schicht (mit 0.5K Trägheit)"), **ohne** dass sie Overshoot-Budget kosten — und das Overshoot-Budget (Penetrative Convection, Z. 848 ff.) kommt obendrauf. Zwei Großzügigkeiten für dasselbe physikalische Phänomen.

**Befund B — Entrainment zu niedrig:** μ = 0.00012–0.00022/m (config.py:646-650, terrainabhängig) liegt laut Literatur Faktor 2–4 unter realistischen Werten für Thermikblasen mit R≈500 m (0.0005–0.0008/m, Romps & Charn). Vermutlich kompensiert das die GFS-Basis-Caps — d. h. zwei falsche Werte ergeben zusammen brauchbare Basen.

**Was anpassen:**
1. Toleranz-Schichten Budget kosten lassen (oder Toleranz auf ~−0.2 K senken).
2. μ anheben Richtung Literaturwerte.
3. **Beides zusammen** gegen die Topout-Daten kalibrieren (`TOPOUT_STICHPROBE.md`-Methode). Einzeln gedreht verschiebt sich nur die Kompensation — die Basen kippen dann systematisch zu tief oder zu hoch.

---

## P4 — Kleinere Physik (nach Bedarf)

1. **LCL-Höhenbezug inkonsistent:** T2m stammt vom Tal-Gitterpunkt, die LCL-AGL wird aber auf Spot-Elevation addiert (~Z. 820). Passt zum Befund „5–7 von 16 unmöglichen Basen" in der Topout-Stichprobe. Fix: Bezugshöhe konsistent machen.
2. **Fixer SALR 0.006, keine virtuelle Temperatur, ρ fix 1.1:** w* dadurch ~7 % zu tief auf 3000 m. Kleiner, sauberer Genauigkeitsgewinn.
3. **ALPTHERM-Volumeneffekt** (Hypsometrie pro Region) als physikalisch sauberere Alternative zu den pauschalen Terrain-Multiplikatoren — größerer Umbau, nur angehen, wenn P1/P3 die Terrain-Faktoren ohnehin infrage stellen.

---

## Langfristig: ML-Korrekturlayer

Gradient Boosting auf den Physik-Output, trainiert auf XContest-Labels — die Daten existieren bereits (`labeled_examples.jsonl`, `observations.csv`). Das ist das, was Skysight/Paraglidable produktseitig machen; publiziert hat es niemand. Erst sinnvoll, wenn P1/P3 durch sind (sonst lernt das ML die Bugs mit).

---

## Als korrekt bestätigt — NICHT anfassen

- **Encroachment mit Tennekes-Closure** (1+2A, A=0.2)
- **Bolton-LCL** (~20 m Fehler, völlig ausreichend)
- **Terrainzonen-abhängiger GFS-Cap** (hard/soft/sanity — literaturkonform, Goger 2024)
- **Triple-Constraint-Architektur** insgesamt
- **Deardorff-w* als Primärweg** (Parcel-w* nur als Fallback) — RASP-Standard

---

## Umsetzungs-Checkliste

| # | Punkt | Aufwand | Risiko | Braucht Kalibrierung |
|---|-------|---------|--------|----------------------|
| 1 | P2.2 toten Aufruf löschen | Minuten | keins | nein |
| 2 | P2.1 h_is_estimated ehrlich machen | klein | keins | nein |
| 3 | P2.3 DWD-Blending-Entscheid | Entscheid | klein | bei „an": mit P1 |
| 4 | P1 subtraktives Schema + Fit | mittel | mittel | **ja (Kern der Arbeit)** |
| 5 | P3 Toleranz + μ gemeinsam | klein–mittel | mittel | **ja, nur gemeinsam** |
| 6 | P4.1 LCL-Höhenbezug | klein | klein | Stichprobe reicht |
| 7 | P2.4 Doku aktualisieren | klein | keins | nein (am Schluss) |

**Quellen des Reviews:** Session 2026-07-02 (Memory `thermikmodell-review-2026-07`), Literatur: Young 1988, RASP/BLIPMAP-Doku (Hcrit), Romps & Charn (Entrainment), Goger 2024 (alpine PBL), kk7-Steigstatistik, ALPTHERM (Olofsson/OLC).
