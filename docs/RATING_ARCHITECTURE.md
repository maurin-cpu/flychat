# Rating-Architektur (v2.1)

**Status:** aktiv ab Refactor 2026-05-17. Reduktion auf 1–5 Skala (vorher v2.0 mit 1–6, klassiker als eigene Stufe).
**Prinzip:** Eine Quelle pro Konzept. Keine Doppelungen. Keine verwaisten Felder. FE leitet Darstellung selbst ab.

---

## Achsen-Übersicht

Drei orthogonale Achsen pro Spot/Region/Tag:

| Achse | Kanonisches Feld | Werte | Sichtbar im UI als |
|---|---|---|---|
| **Sicherheit** | `safety.safety_status` | `safe` \| `conditional` \| `not_safe` | Pill + Marker-Farbe (green/amber/red), FE-gemappt |
| **Fliegbarkeit** | `experience_rating` | `1`–`5` | Zahl + Tier-Farbe (gray/green/violet), FE-gemappt |
| **Streckenflug** (nur Spot) | `streckenflug.rating` | `1`–`5` | Zahl + Limit-Hinweis |

Plus orthogonal: `foehn_risk` (`none` \| `moderate` \| `high`) — kann Sicherheit eskalieren.

---

## Datenstruktur Spot

```json
{
  "spot": "Name",
  "date": "YYYY-MM-DD",
  "safety": {
    "safety_status": "safe",
    "foehn_risk": "none",
    "safe_window": "10:00-15:00",
    "safety_rating": 8.0,
    "wind_safety_rating": 8,
    "gust_safety_rating": 7,
    "aloft_safety_rating": 9,
    "foehn_safety_rating": 10,
    "rain_safety_rating": 10,
    "thunderstorm_safety_rating": 10,
    "cape_safety_rating": 10,
    "visibility_safety_rating": 9,
    "summary": "Prosa-Zusammenfassung",
    "caution_notes": ["..."],
    "no_go_reasons": []
  },
  "experience_rating": 4,
  "is_conditional": false,
  "streckenflug": {
    "rating": 3,
    "limiting_factor": "Basis bleibt unter 2500m"
  },
  "primary_no_go": null,
  "primary_caution": "Gust-Faktor erhöht",
  "primary_reducer": null,
  "primary_booster": "Solide Mittagsthermik",
  "summary": "Prosa über den Tag",
  "recommendation": "Einschätzung-Prosa"
}
```

## Datenstruktur Region

Wie Spot, **aber**:
- Kein `streckenflug{}`-Block.
- Kein `gust_safety_rating` (Region hat keine spot-spezifischen Bodendaten).
- Fehlende Felder fehlen **ganz** — kein `null` (LLM-Halluzinations-Schutz).

```json
{
  "region": "Name",
  "date": "YYYY-MM-DD",
  "safety": {
    "safety_status": "safe",
    "foehn_risk": "none",
    "safe_window": "10:00-15:00",
    "safety_rating": 7.0,
    "wind_safety_rating": 7,
    "aloft_safety_rating": 8,
    "foehn_safety_rating": 10,
    "rain_safety_rating": 9,
    "thunderstorm_safety_rating": 10,
    "cape_safety_rating": 10,
    "visibility_safety_rating": 8,
    "summary": "...",
    "caution_notes": [],
    "no_go_reasons": []
  },
  "experience_rating": 4,
  "is_conditional": false,
  "primary_caution": "...",
  "primary_booster": "...",
  "summary": "...",
  "recommendation": "..."
}
```

---

## experience_rating (1–5)

**Skala** — 1:1 mit Pilot-Kategorien (internes LLM-Reasoning):

| Wert | Kategorie | Beschreibung |
|---|---|---|
| 1 | `abgleiter` | Keine Thermik, nur Sinkrate-Flug |
| 2 | `kurzer_thermikflug` | Suchtag-Zwischenstufe: 1–2h mit Glück, sonst Abgleiter |
| 3 | `solider_thermikflug` | Mehrere Stunden Thermik möglich (typischer CH-Sommertag) |
| 4 | `starker_thermikflug` | Hohe Steigwerte, lokal-XC möglich (Peak 2.0–2.5, LLM-Urteil) |
| 5 | `xc_tag` | Strecken-Tag (Peak ≥ 2.5, 50–150km+). **"Klassiker-Tag"** ist eine Prosa-Auszeichnung in Rating 5 wenn alle 3 Hammertag-Marker erfüllt sind — kein eigenes Rating. |

**Tier-Farbe (FE-Mapping, keine Strukturfeld-Persistierung):**

```
1, 2 → gray   (Bronze #B08D57)
3, 4 → green
5 → violet
```

Bei `safety_status == "not_safe"`: `experience_rating = 1` (keine Belohnung wenn nicht sicher).

**Harte Schranken** (pilotenkalibriert Mai 2026 — Variante A, in `skills/shared/04_flyability/04_flight_subratings_*.md`):

Nur 3 universelle Regeln, alles andere ist LLM-Pilotenurteil:

| Bedingung | Konsequenz |
|---|---|
| `sustained_peak < 1.0` | Rating maximal **1** (Abgleiter ist Abgleiter) |
| `sustained_peak < 2.5` | Rating maximal **4** (Peak 2.5 m/s ist die XC-Tag-Schwelle) |
| `sustained_peak ≥ 2.5` UND `prod_h_strict ≥ 6h` UND `cloud_structure ∉ {overcast, overdevelopment}` | Rating mindestens **5** (echte XC-Substanz) |

Frühere AGL-/Tier-Booster wurden verworfen (Mai 2026, "Wack-a-Mole-Spirale").
Innerhalb der Schranken entscheidet das LLM anhand Peak/prod_h/working_height/cloud_structure
und Pilot-Vignetten — siehe `skills/shared/04_flyability/04_flight_subratings_spot.md`
Sektion "Wie du die Werte gegeneinander abwaegst".

---

## streckenflug.rating (1–5)

**Nur Spot.** Bewertet **Spot + Region kombiniert** für XC-Potenzial.

| Wert | Bedeutung |
|---|---|
| 1 | Nichts fliegbar / Abgleiter-Niveau |
| 2 | Lokal fliegbar, kein Wegfliegen |
| 3 | Kurzes Wegfliegen (Talquerung, ~10–30km) |
| 4 | Weit (~30–100km XC) |
| 5 | Klassiker (>100km, Top-XC-Tag) |

Kann sich **stark** von `experience_rating` unterscheiden (z.B. perfekter Hangtag am Spot aber Region zeigt schwache Thermik → `experience_rating=4`, `streckenflug.rating=2`).

`limiting_factor`: kurzer String, was XC bremst (z.B. "Region-Thermik schwach", "Basis bleibt tief", "Föhn aufgefrischt"). Optional.

---

## safety_status

| Wert | FE-Farbe | Bedeutung |
|---|---|---|
| `safe` | green | Fliegen ohne erhebliche Einschränkungen möglich |
| `conditional` | amber | Bedingt fliegbar, Vorsicht / Erfahrung nötig |
| `not_safe` | red | Nicht fliegen |

FE-Mapping (1 Zeile JS):
```js
const color = {safe:'green', conditional:'amber', not_safe:'red'}[status] || 'no_data';
```

**Aggregation** aus 8 (Spot) bzw. 7 (Region) Sub-Ratings via **Weakest-Link MIN** zu `safety_rating` (0–10). Decision-Engine wendet danach deterministische Overrides an (Föhn, Aloft, Gust). Details: `docs/DECISIONS.md`.

---

## Datenfluss

```
LLM produziert (Skill-Output):
   - safety.safety_status + 7-8 Sub-Ratings + Prosa
   - experience_rating (1-5)
   - streckenflug{rating, limiting_factor}    [nur Spot, 1-5]
   - is_conditional, primary_*, summary, recommendation
        ↓
Decision-Engine (deterministisch, engine/decision_engine.py):
   - compute_safety_rating() = Weakest-Link MIN
   - apply_foehn_decision() — kann Status eskalieren
   - apply_aloft_decision, apply_gust_decision, ...
   - decide_is_conditional() — final-Override
        ↓
Cache (data/spot_analyses.json, data/region_analyses.json)
        ↓
FE liest, mappt Farben selbst (kein safety_band, kein flyability_tier persistiert)
```

---

## Was bewusst entfernt wurde

Im Vergleich zu v1.5:

| Entferntes Feld | Grund |
|---|---|
| `flight_category` (Output-Feld) | Pilot-Kategorien sind nur LLM-internes Reasoning, kein Output |
| `flyability_tier` (Strukturfeld) | Farbe wird FE-seitig aus `experience_rating` gemappt |
| `safety_band` | Farbe wird FE-seitig aus `safety_status` gemappt |
| `fly_status` | Dublette zu `flyability_tier` |
| `rating` (mehrdeutig) | Wurde durch `experience_rating` ersetzt, klar definiert |
| `experience_score` (0–100) | Verwaist seit v1.5, nicht mehr berechnet |
| `experience_stars` (0–5) | Verwaist seit v1.5, nicht mehr berechnet |
| `thermal_rating`, `window_rating`, `xc_rating`, `altitude_rating`, `wind_rating` | Verwaiste Sub-Rating-Inits, nie befüllt |
| `streckenflug.tier` | Doppelte Aussage zu `streckenflug.rating` |
| `conditional_reason` | Init, nie befüllt — Reason steht in `caution_notes` |
| `comfort_index` | Texture-Wert, nicht mehr verwendet |

---

## Sync-Pflicht bei Änderungen

Wenn ein neues Strukturfeld eingeführt oder ein bestehendes geändert wird:

1. **Backend** — `engine/_common.py`, `engine/decision_engine.py`, `engine/analyzers.py`
2. **Skills** — `skills/shared/03_safety/*`, `skills/shared/04_flyability/*`, kombi-Skills
3. **Frontend** — `static/js/analysis-view.js`, `region-map.js`, `briefing.js`, `shared-glyph.js`
4. **Tests** — `tests/test_decision_engine.py`, `score_regression.py` Reverse-Parser
5. **Diese Doku** — `docs/RATING_ARCHITECTURE.md` aktualisieren
6. **Memory** — `memory/MEMORY.md` Index ggf. anpassen

---

## Migration v1.5 → v2.0

Big-Bang-Migration, durchgeführt 2026-05-12:
- Skills komplett überarbeitet (neue Output-Schemas, 6 Thermik-Kategorien als Reasoning-Hilfe)
- Backend: alle entfernten Felder weg
- FE: Farb-Mapping selbst
- Cache (`spot_analyses.json` + `region_analyses.json`) komplett gelöscht und neu berechnet

Keine externen Consumer betroffen.

---

## Migration v2.0 → v2.1

Durchgeführt 2026-05-17:
- Skala reduziert von 1–6 auf 1–5 (Klassiker als Prosa-Auszeichnung statt eigenes Rating 6).
- Rating-Kalibrierung "Variante A": AGL-/Tier-Booster verworfen, ersetzt durch 3 universelle
  Peak-Schranken (`< 1.0 → max 1`, `< 2.5 → max 4`, `≥ 2.5 + 6h + saubere Wolken → min 5`).
  Begründung: Booster-Mechanik führte zu "Wack-a-Mole"-Spirale bei Edge-Cases.
- AGL-Schwellen in Skills auf belegte Pilot-Stützpunkte gehoben (Drury/xcmag, Burnair):
  `< 400m / 400–800m / 800–1500m / 1500–2000m / > 2000m`.
  Doku: `meteo_research/working_height_agl_thresholds.md`.
