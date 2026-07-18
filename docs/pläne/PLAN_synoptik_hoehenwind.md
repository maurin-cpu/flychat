# Plan: Synoptik-Wind auf echten 700-hPa-Wind umstellen + H/T-Artefakt-Filter

**Status:** UMGESETZT 2026-07-18 (Phasen 1–5). Recherche-validiert (Deep-Research
2026-07-17, `meteo_research/synoptik_hoehenwind_partikel_research.md`).
Real-Validierung bestanden: Alpen-Wind jetzt WSW (261°, vorher fälschlich SE ~132°),
Zentren 101→74 (27 Artefakte gefiltert), SPEED_STOPS an realer Verteilung kalibriert
(Median 30 / P90 55 / P99 78 km/h). Tests 250 passed (3 e2e-Playwright-Errors
vorbestehend). Browser-Check /synoptik + /briefing-Embed: 0 Konsolenfehler.
Commit + Push noch offen.
**Erstellt:** 2026-07-17
**Branch:** `main` (Single-Branch-Workflow)
**Voraussetzung:** Der Wind-Partikel-Layer selbst (synoptic-wind.js, synoptic-embed.js,
Toggle, Legende) ist als uncommittete Arbeit bereits im Working Tree — dieser Plan ÄNDERT
dessen Windquelle, er baut ihn nicht neu.

**Wiederaufnahme (HIER starten):**
1. Diese Datei + `meteo_research/synoptik_hoehenwind_partikel_research.md` lesen —
   **alle Konzept-Entscheidungen sind getroffen** (D1–D6 unten), NICHT neu aufrollen.
2. Reihenfolge: Phase 1 (Fetch) → Phase 2 (JS-Feld) → Phase 3 (Zentren-Filter) →
   Phase 4 (Labels) → Phase 5 (Tests/Validierung). Phase 1+3 sind Python, 2+4 JS —
   Phase 3 kann vor Phase 2 gezogen werden, braucht aber das Cache-Format aus Phase 1.
3. Verifizieren gegen laufenden Dev-Server: **PORT=5001** nutzen (Port-5000-Doppel-Bind,
   siehe Memory).

**Kurz-Summary der Lösung:**
Der Partikel-Layer zeigt statt geostrophisch aus MSLP gerechnetem Wind (über den Alpen
nachweislich falsch, im Extrem richtungs-invertiert) den **echten 700-hPa-Modellwind**, der im
selben gechunkten Open-Meteo-Fetch wie `pressure_msl` mitgeholt und als u/v-Felder im
Grid-Cache abgelegt wird. Die H/T-Zentren-Erkennung bekommt zwei zusätzliche Filter gegen
flache Hitzetief-/Reduktions-Artefakte: **orographisches Masking** (Literatur-Standard IMILAST)
und **Zirkulations-Check** gegen das 700-hPa-Feld (fängt vom groben Grid versetzte Artefakte —
das reale Burgund-Badge vom 17.07. lag unter 1000 m und wäre vom Masking allein nicht gefiltert
worden). Legende/Hint labeln das Niveau explizit („Höhenwind 700 hPa ~3000 m"). Damit zeigen
Synoptik-Karte, Wetterlage-Callout (nutzt bereits `wind_700`) und Regionen-Höhenwind dieselbe
Strömung, und die Partikel zirkulieren garantiert korrekt um jedes angezeigte H/T-Badge.

---

## Entscheidungen (final — nicht neu aufrollen)

- **D1 — Niveau: 700 hPa.** Begründung: 850 hPa liegt teils IM Alpengelände; DWD bescheinigt
  FL100 hohe synoptische Aussagekraft; Gleitschirm-Flughöhenband 500–4000 m; **interne
  Konsistenz** mit `synoptic_context.wind_700` (Wetterlage/Bise) und Regionen-Höhenwind.
  ECMWF-Präzedenz (850 fürs Overlay) bewusst nicht übernommen.
- **D2 — Speicherformat: u/v in m/s** (1 Nachkommastelle) je Timestep im Grid-Cache
  (`winds: {ts: {u: [...], v: [...]}}`), Konvertierung aus Open-Meteo speed/direction beim
  Fetch. u/v statt speed/dir, weil das JS bilinear interpoliert — Winkel-Interpolation über
  die 360°-Naht wäre fehleranfällig. Cache wächst um ca. 2×828×20×~6 Bytes ≈ 200 KB (kompakt).
- **D3 — Doppelfilter für Zentren:** (a) orographisches Masking: Kandidat verworfen, wenn
  Zellen-Elevation > `SYNOPTIC_GRID_CENTER_MAX_ELEV_M = 1000` (IMILAST-Bandbreite 1000–1500;
  konservativ 1000, da Grid grob). Elevation kommt **gratis** im Open-Meteo-Payload
  (`elevation` je Location) → einmal als `elevations: [..828]` im Cache ablegen.
  (b) Zirkulations-Check: mittlere Tangentialkomponente des 700-hPa-Winds auf dem
  Fensterrand-Ring (`CENTER_WINDOW_CELLS`, wie der Gradient-Check); Tief braucht zyklonale,
  Hoch antizyklonale Tangentialkomponente ≥ `SYNOPTIC_GRID_CENTER_MIN_TANGENTIAL_MS = 2.0`.
  Bestehende Gradient-Schwelle (2.0 hPa) bleibt unverändert.
- **D4 — Fallback alter Cache ohne `winds`:** Partikel-Layer bleibt deaktiviert (Button
  disabled), KEIN Rückfall auf Geostrophie — lieber kein Wind als falscher Wind.
  `computeField()` (Geostrophie) wird ersatzlos entfernt.
- **D5 — Farbskala neu kalibrieren:** realer 700-hPa-Wind ist stärker als der gedämpfte
  Geostrophie-Output (VMAX-Cap 36 m/s entfällt bzw. steigt auf 60 m/s als reiner
  Ausreißer-Schutz). SPEED_STOPS nach Fetch an der realen Verteilung über alle Timesteps
  ausrichten (Median/P90/P99 einmal messen, analog bisheriger Kalibrierung im Kommentar).
- **D6 — Labeling (i18n):** `js.syn.legend_wind` → „Höhenwind 700 hPa (km/h)" / EN
  „Wind at 700 hPa (km/h)"; `js.syn.wind_hint` → „Höhenströmung in ~3000 m (700 hPa) — nicht
  der Bodenwind" / EN sinngemäß. `js.syn.embed_sub` bleibt („Bodendruck & Windströmung" →
  prüfen, ob „Höhenströmung" besser). Diese Keys existieren bereits (i18n.py ~Z. 871–878).

## Bewusste Trade-offs (dokumentiert, kein Handlungsbedarf)

- Partikel kreuzen lokal Isobaren (baroklin, v. a. Alpen) — fachlich korrekt, etablierte
  Profi-Praxis (ECMWF MSLP+Wind-Kombikarte). Kein „Fix" nötig.
- Echte, aber flache Boden-Hitzetiefs werden nicht mehr gebadged — für die Piloten-Zielgruppe
  gewollt (nur steuernde, durchgehende Systeme zählen für die übergeordnete Lage).
- Fetch-Payload wächst ~3× (3 hourly-Variablen statt 1) bei gleicher Call-Zahl — akzeptiert.

---

## Phase 1 — Fetch: 700-hPa-Wind + Elevation in den Grid-Cache (`engine/synoptic_grid.py`)

Touch-Points (Zeilennummern Stand 2026-07-17):

1. `fetch_grid_pressure()` Z. 102–177 — umbenennen bleibt aus (API stabil halten), aber:
   - Z. 124 `"hourly": "pressure_msl"` → `"pressure_msl,wind_speed_700hPa,wind_direction_700hPa"`.
   - Parse-Schleife Z. 161–169: zusätzlich `wind_speed_700hPa` (km/h) + `wind_direction_700hPa`
     (Grad, meteorologisch = woher) je Timestep einsammeln und in u/v (m/s) konvertieren:
     `u = -speed/3.6 * sin(dir·π/180)`, `v = -speed/3.6 * cos(dir·π/180)`, `round(x, 1)`;
     fehlende Werte → `None` (JS-`fillNulls` existiert bereits).
   - `loc.get("elevation")` je Location einsammeln (Reihenfolge = Punkt-Reihenfolge).
   - Return erweitert: `{"timesteps", "values", "winds": {ts: {"u": [...], "v": [...]}},
     "elevations": [...]}`.
2. `refresh_synoptic_grid()` Z. 331–345 — `winds` + `elevations` ins `result` übernehmen
   (Cache-Format-Erweiterung ist rückwärtskompatibel: alte Leser ignorieren neue Keys).
3. Kein neuer Endpoint nötig: `web.py` liefert den Cache bereits als Ganzes aus (prüfen, ob
   der Endpoint Felder whitelistet — falls ja, `winds`/`elevations` ergänzen).

## Phase 2 — JS: echtes Feld statt Geostrophie (`static/js/synoptic-wind.js`)

1. `computeField()` (Z. 144–176) + Physik-Konstanten RHO/OMEGA/F_MIN_LAT entfernen.
   Ersatz `buildField(meta, winds_ts)`: `fillNulls` auf u und v anwenden, `smooth3x3`
   BEIBEHALTEN (Grid-Rauschen glätten, eine Iteration), Float32Array u/v bauen.
   VMAX-Cap: 60 m/s reiner Ausreißer-Schutz (D5).
2. `setGrid`/`setTimestep` (Z. 464–476): Felder aus `grid.winds[ts]` lazy bauen; **kein
   `grid.winds` → Layer nicht aktivierbar** (D4): `setTimestep` no-op, Karte meldet dem
   Aufrufer via Rückgabe/Flag, dass der Button disabled bleibt.
3. Header-Kommentar (Z. 1–21) umschreiben: nicht mehr „geostrophisch abgeleitet", sondern
   „echter 700-hPa-Modellwind aus dem Grid-Cache".
4. `SPEED_STOPS`/`SPEED_MAX_KMH` (Z. 51–57) nach Messung der realen Verteilung anpassen (D5).
5. Sampling/Rendering (bilinear, Partikel-Loop, Arrows, Trail-Fade) bleibt UNVERÄNDERT —
   die Pipeline ist quellenagnostisch.
6. `static/js/synoptic-embed.js`: nutzt `WingcastWind` — erbt alles; nur prüfen, dass es bei
   fehlendem `winds` sauber ohne Windlayer rendert (Isobaren/Badges weiter zeigen).

## Phase 3 — H/T-Zentren-Filter (`engine/synoptic_grid.py` + `config.py`)

1. `config.py` (~Z. 501 ff.): `SYNOPTIC_GRID_CENTER_MAX_ELEV_M = 1000`,
   `SYNOPTIC_GRID_CENTER_MIN_TANGENTIAL_MS = 2.0`.
2. `find_grid_pressure_centers()` Z. 203–275: Signatur um `winds_ts=None, elevations=None`
   erweitern (beide optional → Tests/alte Aufrufer brechen nicht):
   - **Masking:** nach dem Gradient-Check (Z. 255): `elevations[j*nx+i] > MAX_ELEV_M` → skip.
   - **Zirkulations-Check:** auf dem Fensterrand-Ring (Zellen mit Chebyshev-Distanz
     `radius`, wie ring_acc Z. 248): Tangential-Einheitsvektor zur Zentrums-Richtung
     (CCW: `t = (-dy_norm, dx_norm)` in Meter-Koordinaten, cos(lat)-korrigiert), mittleres
     `u·t_x + v·t_y` über den Ring. Tief: Mittel ≥ +2.0 m/s, Hoch: ≤ −2.0 m/s, sonst skip.
     `None`-Windwerte am Ring überspringen; < 4 gültige Ring-Samples → Check nicht anwendbar
     → Kandidat NUR über Masking/Gradient beurteilen (kein Silent-Kill bei Datenlücken).
   - `decided_by` um Filter-Info ergänzen (z. B. `"circulation_ok"` /
     verworfen wird nicht ausgegeben) — Debugbarkeit im Audit (`data/synoptic_audit`).
3. `refresh_synoptic_grid()` Z. 331–334: `find_grid_pressure_centers(meta, vals,
   winds_ts=fetched["winds"].get(ts), elevations=fetched["elevations"])`.

## Phase 4 — Labels/i18n

1. `i18n.py` (~Z. 871–878): Texte gemäß D6 anpassen (Keys existieren).
2. `static/js/synoptic-map.js` Z. 894–899: Kommentar + `wind_hint`-Einbau bleiben, Text kommt
   aus i18n; Kommentar von „geostrophischer Wind" auf 700 hPa umschreiben.
3. Legende `windLegendHtml()` (synoptic-map.js Z. 761 ff.): nutzt `legend_wind` — nur i18n.

## Phase 5 — Tests + Validierung

1. `tests/test_synoptic_grid.py` erweitern:
   - u/v-Konvertierung: dir=270° (Westwind) → u>0, v≈0; dir=0° (Nordwind) → v<0.
   - Zirkulations-Check: synthetisches zyklonales u/v-Feld um ein Tief → Kandidat überlebt;
     uniformes Westwind-Feld → Tief-Kandidat verworfen; Wind-Feld `None` → Kandidat bleibt
     (Fallback-Regel).
   - Masking: Kandidat auf Zelle mit elevation 1500 → verworfen; 400 → bleibt.
   - Cache-Roundtrip mit `winds`/`elevations`.
2. **Real-Validierung** (einmalig nach erstem Fetch, Skript oder REPL):
   - Feld bei 46.8N/8.2E sampeln und gegen Open-Meteo-Punktabfrage 700 hPa vergleichen
     (muss per Konstruktion ≈ übereinstimmen; Abweichung nur durch Grid-Interpolation).
   - Zentren-Vergleich alt/neu über alle Timesteps loggen: erwartet werden verworfene flache
     Sommer-Badges (Referenzfall: Tief 47.5N/5.0E, 17.07., grad 2.6) bei unveränderten tiefen
     Systemen (Referenz: Tief 55N/40E, Hoch 60N/-2E vom 13.07.).
   - Verteilungs-Messung für D5 (Median/P90/P99 der km/h über alle Timesteps) → SPEED_STOPS.
3. **Browser-Check** (PORT=5001): `/synoptik` Toggle + Legende + Hint; `/briefing` Mini-Karte;
   `prefers-reduced-motion`-Pfeile; alter Cache ohne `winds` → Button disabled, keine Errors.
4. Bestehende Tests grün; danach Commit zusammen mit der offenen Partikel-Layer-Arbeit
   (die Basis ist ja noch uncommittet) — sinnvoll als zwei Commits: (1) Partikel-Layer wie
   im Working Tree, (2) dieser Umbau. Doku-Sync: `docs/DECISIONS.md` + `SYSTEM_CHANGES.md`.

## Risiken / Stolpersteine

- **Open-Meteo-Feldnamen:** `wind_speed_700hPa`/`wind_direction_700hPa` liefern km/h bzw.
  Grad-woher (in `data/wetterdaten.json` `pressure_level_data` bereits so im Einsatz) —
  Einheit beim Konvertieren nicht doppelt teilen.
- **Multi-Location-Payload:** `elevation` steht pro Location-Objekt auf Top-Level (nicht in
  `hourly`) — beim Chunk-Parsing an der richtigen Stelle greifen.
- **`_target_timesteps` droppt Timesteps ohne MSLP** (Z. 171–176) — `winds` MUSS dieselben
  Keys behalten (gleiche Drop-Logik anwenden), sonst KeyError im JS/Zentren-Aufruf.
- **Tangential-Geometrie:** dx in Metern braucht cos(lat)-Faktor, sonst ist die
  Tangentialrichtung bei hohen Breiten verzerrt (gleiches Muster wie `dxM` in der alten
  `computeField`, Z. 159 — Code als Referenz nutzen, bevor er gelöscht wird).
- Der Zirkulations-Check ist KEIN publizierter Standard (Research 3.4) — Schwelle 2.0 m/s ist
  Erstschätzung; nach Real-Validierung ggf. justieren, bevor echte schwache Systeme sterben.
