# Decisions Reference

Diese Datei dokumentiert **alle deterministischen Strukturentscheidungen**, die das System
am Analyse-Result trifft. Es gibt drei Schichten:

1. **Pre-Filter** (vor LLM-Call): kann den LLM-Call ueberspringen.
2. **Decision-Engine** (nach LLM-Call, autoritativ): setzt Strukturfelder unabhaengig
   davon, was das LLM produziert hat. Single source of truth.
3. **UI-Backstops**: rendern bestimmte Risiken auch dann, wenn das LLM die Note
   weggelassen hat.

> **Sync-Pflicht (an Claude):** Bei jeder Aenderung an `engine/decision_engine.py`,
> `engine/analyzers.py` (Decision-Aufrufe), `engine/weather_context.py`
> (Cache-Befuellung, Foehn-Strip) oder den UI-Backstops in
> `static/js/region-map.js`/`meteogram.js`/`briefing.js`:
> - Neue Decision/Pre-Filter/UI-Backstop → Tabellenzeile in der passenden Sektion
>   ergaenzen.
> - Geaenderter Trigger oder Effekt → Tabelle aktualisieren, Datum in
>   *Letzte Aktualisierung* nachziehen, Changelog-Eintrag.
> - Entfernter Code → Zeile loeschen, Changelog notieren.
> Suchhilfen: `grep -n "decide_" engine/decision_engine.py`,
> `grep -n "_decisions_applied\|_apply_foehn_decision" engine/analyzers.py`,
> `_prefilter_not_safe`.

Letzte Aktualisierung: 2026-05-17 (RATING_ARCHITECTURE v2.1: experience_rating 1–5, streckenflug.rating 1–5, Klassiker = Prosa-Auszeichnung in Rating 5, kein eigenes Rating mehr. FE leitet Farben aus safety_status + experience_rating ab — kein safety_band, flyability_tier, fly_status, flight_category mehr als Strukturfelder.)

---

## Architektur-Pattern: Stage-Inversion

Das System trennt Strukturentscheidungen (Status, Risk, Tier, Listen-Eintraege)
deterministisch von der Prosa-Erzeugung:

```
Wetterdaten → LLM (produziert Strukturfelder + Prosa)
            → Decision-Engine ueberschreibt Strukturfelder autoritativ
            → Foehn-Strip bereinigt Prosa-Felder bei irrelevanter Foehn-Richtung
            → Resultat
```

Das LLM darf alle Felder weiter setzen, aber alle deterministisch ableitbaren
Felder (Status, foehn_risk, flyability_tier, kanonische Notes) werden danach
ueberschrieben. Der Effekt: LLM-Compliance-Bugs koennen die Sicherheits-Bewertung
nicht mehr verfaelschen.

**Tracking:** Jede gefeuerte Decision schreibt einen Eintrag in
`result["_decisions_applied"]` (z.B. `["FoehnCaution(4.5)", "GustFloor"]`).
Beim Debuggen sieht man genau, welche Korrekturen gegenueber dem LLM-Output
passiert sind.

---

## 1. Pre-Filter (vor LLM-Call)

`_prefilter_not_safe(spot, date_str)` in `engine/analyzers.py`. Liefert direkt ein
fertiges `not_safe`-Result und spart den LLM-Call. Wirkt **nur fuer Spots**, nicht
fuer Regionen.

| Trigger                                                                 | Ergebnis  | Source                          |
| ----------------------------------------------------------------------- | --------- | ------------------------------- |
| `wind_ok_count == 0` ganztaegig (Windrichtung immer ausserhalb Sektor)  | not_safe  | `_prefilter_not_safe` Regel 1   |
| `0 < wind_ok_count < CLEAN_WINDOW_MIN_HOURS` (Start-Fenster zu kurz)    | not_safe  | `_prefilter_not_safe` Regel 2   |
| Regen in mind. `total_hours - 2` Stunden UND mind. 4h                   | not_safe  | `_prefilter_not_safe` Regel 3a  |
| THUNDERSTORM in mind. `total_hours - 2` Stunden UND mind. 4h            | not_safe  | `_prefilter_not_safe` Regel 3b  |

---

## 2. Decision-Engine — Foehn

`engine/decision_engine.py`: `compute_foehn_decision()` + `apply_foehn_decision()`.

Quelle: `_ctx_foehn_cache[name|date]`, befuellt via
`_format_foehn_info(cache_key=…)` in `weather_context.py` aus `evaluate_foehn()`.

| Cache-Level                         | Decision-Effekt                                                                                | Tracking-Tag           |
| ----------------------------------- | ---------------------------------------------------------------------------------------------- | ---------------------- |
| `none` (kein Foehn ODER irrelevante Richtung) | `foehn_risk=none`, LLM-Foehn-Eintraege in caution_notes/no_go_reasons werden gestrichen, sonst kein Eingriff | (kein Tag)             |
| `caution` (ΔP 4-7, relevante Richtung) | `foehn_risk=moderate`, Status mind. `conditional`, kanonische `caution_notes`-Eintragung      | `FoehnCaution(ΔP)`     |
| `danger` (ΔP ≥ 8, relevante Richtung) | `foehn_risk=high`, Status `not_safe`, `safe_window=keins`, `primary_no_go=FOEHN`, kanonische `no_go_reason` | `FoehnDanger(ΔP)`      |

> **Richtungs-Filter** (kritisch != aktiv): wird bereits in `_format_foehn_info()`
> abgefangen — der Cache liefert dann `level="none"`, sodass die Decision-Engine
> nichts triggert.

### Foehn-Strip (Prosa-Saeuberung)

Ergaenzend zur Decision-Engine wirkt `_strip_irrelevant_foehn()` in
`weather_context.py` ausschliesslich auf die Freitext-Felder
`summary`/`wind_summary`/`wind_shear`. Saetze mit Foehn-Keywords werden
entfernt, wenn die Foehn-Richtung fuer den Standort irrelevant ist (verhindert,
dass das LLM einen Foehn-Hinweis im Fliesstext leakt, obwohl die Strukturfelder
korrekt geleert sind).

---

## 3. Decision-Engine — Spot Safety

Reihenfolge in `_post_process_safety_spot`:

1. `decide_wind_ok_zero`
2. `decide_aloft_not_safe`
3. `decide_aloft_conditional`
4. `decide_gust_floor`
5. `decide_overclaim_relax`
6. `_apply_foehn_decision` (Sektion 2)

| Decision                          | Trigger                                                                                       | Effekt                                                              | Tracking-Tag                  |
| --------------------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- | ----------------------------- |
| `decide_wind_ok_zero`             | `wind_ok_count == 0` und Status != not_safe                                                   | `not_safe`, `safe_window=keins`, no_go_reason "Windrichtung"        | `WindOk0`                     |
| `decide_aloft_not_safe`           | `aloft_danger_hours >= WIND_TREND_NOTSAFE_HOURS` ODER aloft-Pattern `DURCHGEHEND_DANGER` ODER `EINGEKESSELT` mit zu kleinem Calm-Gap | `not_safe`, `primary_no_go=ALOFT_DANGER`, no_go_reason | `AloftNotSafe(Nh)`           |
| `decide_aloft_conditional`        | `aloft_danger_hours >= WIND_TREND_CONDITIONAL_HOURS` ODER `aloft_gust_danger_hours >= cond_thresh`, Status = safe | `conditional`, caution_note "Gefahr in der Hoehe …"  | `AloftConditional(Nh)`        |
| `decide_gust_floor`               | `gust_warn_hours + aloft_gust_warn_hours >= WIND_TREND_NOTSAFE_HOURS` ODER analog DANGER, Status = safe | `conditional`, caution_note mit Boeen-Details                       | `GustFloor`                   |
| `decide_overclaim_relax`          | Status = not_safe, `hard_warning_hours == 0`, `clean_hours_count >= 4`                       | **DEMOTIERT** zu `conditional`, no_go_reasons geleert, caution_note "Auto-Korrektur" | `OverclaimRelax(Nh)`          |

`decide_overclaim_relax` ist die einzige Decision, die den Status NICHT verschaerft,
sondern entspannt. Sie hilft, wenn das LLM zu vorsichtig war und keine harten
Warnungen vorliegen.

---

## 4. Decision-Engine — Region Safety

Reihenfolge in `_post_process_safety_region`:

1. `decide_wind_strong_majority` (region-spezifisch)
2. `decide_aloft_not_safe`
3. `decide_aloft_conditional`
4. `_apply_foehn_decision`

| Decision                          | Trigger                                                                                       | Effekt                                                              | Tracking-Tag                  |
| --------------------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- | ----------------------------- |
| `decide_wind_strong_majority`     | `calm == 0`, `strong > moderate`, Status in (safe, conditional)                                | `not_safe`, no_go_reason "Durchgehend starker Wind"                | `WindStrongMajority(N)`       |
| `decide_aloft_not_safe`           | wie Spot                                                                                       | wie Spot                                                            | wie Spot                      |
| `decide_aloft_conditional`        | wie Spot                                                                                       | wie Spot                                                            | wie Spot                      |

Region hat **keine** GustFloor- und keine OverclaimRelax-Decision (Region-Resultate
werden anders aggregiert; diese Decisions sind spot-spezifisch).

---

## 5. Decision-Engine — Flyability (RATING_CONCEPT v1.5)

Aufruf in `_post_process_flyability_spot` (Spot) und `_post_process_flyability_region` (Region).

**Architektur-Wechsel ggue. v1.4:** Es gibt **keine Flyability-Tier-Decisions
mehr**. `experience_rating` (1-10) und `flyability_tier` werden direkt vom LLM
gesetzt — der Code rechnet nichts mehr nach, aggregiert nichts mehr aus
Sub-Achsen, ueberschreibt das Tier nicht mehr durch Reward-Korrekturen.

Entfernt mit v1.5:
- `decide_flyability_low_reward` (Telemetrie + gray-Signal bei schwacher Thermik)
- `decide_flyability_upgrade` (Text-Felder bei gray-trotz-guter-Daten)
- `decide_flyability_region_gate` (Spot-violet ohne Region-Konsens)
- `compute_legacy_flyability_tier` (Tier-Ableitung aus safety_band + stars)

Geblieben (Safety-Decision in der Safety-Pipe, Sektion 3):
- `decide_flyability_mech_danger` — eskaliert `safety_status` `safe`→`conditional`
  bei `rough_pct > 50%` und ergaenzt `caution_notes`. Beruehrt Tier NICHT direkt
  (LLM bekommt rough-Warnung im Kontext und urteilt selbst).

**Einziges Code-Override fuer Tier/Rating:** Safety-Gate. Wenn
`safety_band == "red"` ODER `safety_status == "not_safe"`:
- `flyability_tier` → `""`
- `experience_rating` → `0`
- `experience_score` → `0`

Das gilt als Sicherheits-Hardcap und nicht als Reward-Korrektur — die KI darf
keinen Flugtag aus Qualitaetssicht behaupten, wenn die Safety-Pipeline rot ist.

Die Spot-Flyability hat zusaetzlich einen `not_safe` → leeres Flyability Schritt am
Anfang (`_post_process_flyability_spot`): Wenn die Safety-Phase `not_safe` lieferte,
werden `fly_status`, `flyability_tier` und `streckenflug` direkt geleert; keine
LLM-Anfrage fuer diese Felder.

---

## 5a. Decision-Engine — Compute-Funktionen (2-Achsen-Architektur)

Diese Funktionen werden am Ende der Flyability-Pipeline aufgerufen. Sie sind
**ableitende View-Funktionen** ohne LLM-Override-Eigenschaft — sie berechnen
neue Cache-Felder aus den Sub-Ratings + Decisions.

| Funktion                          | Quelle                                                                                                                | Ergebnis-Feld                                                | Logik (kurz)                                                                                                                  |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `_compute_safety_rating`          | LLM-Sub-Ratings wind/gust/aloft/foehn/rain/thunderstorm/cape/visibility                                                | `safety_rating` (1–10)                                       | **Weakest-Link**: `min(...)` — Sicherheit ist asymmetrisch, kein Mitteln.                                                     |
| `_compute_safety_score`           | `safety_rating × 10`                                                                                                  | `safety_score` (0–100)                                       | Skalierung.                                                                                                                   |
| `compute_safety_band`             | `safety_status` + `_decisions_applied` + `safety_score`                                                                | `safety_band` (green/amber/red)                              | Hard-Overrides (FoehnDanger/AloftNotSafe/THUNDERSTORM/RAIN-WARN/CAPE-DANGER → red; FoehnCaution/GustFloor/AloftConditional → amber) haben Vorrang vor Score (<40 → amber, sonst green). |
| `compute_comfort_index`           | `tq.rough_danger_h / thermal_hours_total`                                                                              | `comfort_index` (0–100) — Texture-Wert                       | `100 - rough_pct`. Beeinflusst NICHT das Rating, nur Spot-Panel-Anzeige.                                                      |

Hinweis (v1.5): `_compute_rating_from_subratings`, `_compute_experience_score`,
`_compute_experience_stars`, `_compute_experience_rating` und
`compute_legacy_flyability_tier` wurden entfernt. `experience_rating` (1-10)
und `flyability_tier` kommen direkt vom LLM. `experience_score = experience_rating × 10`
ist eine reine Unit-Conversion fuer UI-Compat und kein Aggregations-Schritt.

---

## 6. UI-Backstops

Selbst wenn Decision-Engine + LLM korrekt zusammenarbeiten, rendern die UI-Komponenten
zusaetzlich ein Foehn-Badge, falls `foehn_risk != none` und keine Foehn-Erwaehnung in
`caution_notes`/`no_go_reasons` steht — als letzte Sicherung.

| Datei                         | Logik                                                                                       |
| ----------------------------- | ------------------------------------------------------------------------------------------- |
| `static/js/region-map.js`     | `foehn_risk != none` AND keine Foehn-Erwaehnung in den Listen → eigenes Alert-Badge        |
| `static/js/meteogram.js`      | Identische Logik (Spot-Overlay)                                                             |
| `static/js/briefing.js:912`   | Bestehender Pfad: rendert `Foehn: <level>`-Zeile aus `safety.foehn_risk`                   |

Die JS-Seite haelt eine eigene Keyword-Liste fuer Foehn-Erkennung. Bei Aenderungen
an `engine/decision_engine.FOEHN_KEYWORDS` muss die JS-Logik in beiden Dateien
mitgezogen werden.

---

## 7. Caches

Alle Caches werden in `chat_engine.py` initialisiert und in
`_post_process_*_safety/_flyability` gelesen. Sie werden zu Beginn jedes
Analyse-Laufs in `analyzers.py` geleert.

| Cache                  | Init                          | Befuellung (engine/weather_context.py)                    | Genutzt von                                                   |
| ---------------------- | ----------------------------- | --------------------------------------------------------- | ------------------------------------------------------------- |
| `_ctx_gust_cache`      | `chat_engine.py` Konstruktor  | Spot/Region Context-Build                                 | Pre-Filter, alle Wind/Aloft/Boeen-Decisions, Overclaim        |
| `_ctx_tq_cache`        | `chat_engine.py` Konstruktor  | Spot/Region Context-Build                                 | Flyability-Decisions (Downgrade + Upgrade)                    |
| `_ctx_foehn_cache`     | `chat_engine.py` Konstruktor  | `_format_foehn_info(cache_key=…)`                         | Foehn-Decision (apply_foehn_decision)                         |

---

## Wie eine neue Decision hinzufuegen

1. Funktion `decide_xxx(result, ctx, label) -> Optional[str]` in
   `engine/decision_engine.py` definieren. Mutiert `result` in-place, liefert
   Tracking-Tag oder `None`.
2. Bei Bedarf neuen Cache in `chat_engine.py` initialisieren und in
   `engine/weather_context.py` befuellen.
3. Aufruf in der passenden `_post_process_*` Methode in `engine/analyzers.py`
   einreihen — Reihenfolge bedenken (status-modifizierende Decisions zuerst).
4. Tag in `result.setdefault("_decisions_applied", []).append(tag)` mitschreiben.
5. Mindestens 2 Unit-Tests in `tests/test_decision_engine.py` (Trigger feuert,
   Trigger feuert nicht).
6. Tabellenzeile in dieser Datei ergaenzen + Changelog.

---

## Changelog

- **2026-04-28** — **Vollstaendige Stage-Inversion-Migration**:
  - Alle 9 verbleibenden Overrides aus `analyzers.py` (Wind-OK=0, Aloft-NotSafe,
    Aloft-Conditional, Gust-Floor, Overclaim, Wind-Strong-Mehrheit,
    Flyability-Downgrade, Flyability-Upgrade, Region-Gate) in die Decision-Engine
    migriert.
  - `_post_process_safety_spot/region` und `_post_process_flyability_spot/region`
    sind jetzt Decision-Pipes statt Override-Bloecken.
  - Datei umbenannt von `SAFETY_OVERRIDES.md` zu `DECISIONS.md`.
  - Tests: 32 Unit-Tests in `tests/test_decision_engine.py`.
- **2026-04-28 (frueher Eintrag)** — Stage-Inversion-PoC fuer Foehn:
  `engine/decision_engine.py` mit `compute_foehn_decision` + `apply_foehn_decision`,
  `_apply_foehn_override` durch `_apply_foehn_decision` ersetzt,
  `result["_decisions_applied"]` als Tracking-Feld eingefuehrt.
