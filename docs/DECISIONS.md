# Safety- und Flyability-Overrides

Diese Datei dokumentiert **alle deterministischen Korrekturen**, die an den Roh-Ergebnissen
des LLM (oder vor dem LLM-Call) angewendet werden. Sie sind Backstops gegen
LLM-Compliance-Fehler und Halluzinationen — wenn die Wetterdaten objektiv eine andere
Bewertung verlangen als das LLM produziert hat, werden Status, Begruendungen und
Risiko-Felder hier nachjustiert.

> **Sync-Pflicht (an Claude):** Bei jeder Aenderung in `engine/analyzers.py`,
> `engine/weather_context.py` oder `chat_engine.py` an Logik, die `safety_status`,
> `fly_status`/`flyability_tier`, `foehn_risk` oder `*_notes/*_reasons`-Listen
> nachtraeglich modifiziert, **MUSS dieses Dokument aktualisiert werden**:
> - Neuen Override → Zeile in der passenden Tabelle ergaenzen.
> - Geaenderter Trigger/Effekt → Spalte aktualisieren, ggf. „Stand"-Zeile bei
>   *Letzte Aktualisierung* nachziehen.
> - Entfernter Override → Zeile loeschen, Aenderung kurz im Changelog notieren.
> Suchhilfe: `grep -n "Override" engine/analyzers.py` und `_strip_irrelevant_foehn`
> in `engine/weather_context.py`. Pre-Filter siehe `_prefilter_not_safe`.

Letzte Aktualisierung: 2026-04-28 (Foehn-Override + Summary-Sanitierung + UI-Foehn-Badge)

---

## 1. Pre-Filter (vor LLM-Call)

`_prefilter_not_safe(spot, date_str)` in `engine/analyzers.py`. Liefert direkt ein
fertiges `not_safe`-Result und spart den LLM-Call. Wirkt **nur fuer Spots**, nicht
fuer Regionen.

| Trigger                                                                 | Ergebnis  | Source                          |
| ----------------------------------------------------------------------- | --------- | ------------------------------- |
| `wind_ok_count == 0` ganztaegig (Windrichtung immer ausserhalb Sektor)  | not_safe  | `analyzers.py:101` Regel 1      |
| `0 < wind_ok_count < CLEAN_WINDOW_MIN_HOURS` (Start-Fenster zu kurz)    | not_safe  | `analyzers.py:101` Regel 2      |
| Regen in mind. `total_hours - 2` Stunden UND mind. 4h                   | not_safe  | `analyzers.py:101` Regel 3a     |
| THUNDERSTORM in mind. `total_hours - 2` Stunden UND mind. 4h            | not_safe  | `analyzers.py:101` Regel 3b     |

---

## 2. Safety-Overrides — Spot

`_post_process_safety_spot(result, spot, date_str)` in `engine/analyzers.py`.
Reihenfolge: hartes Wind-OK → ALOFT → Boeen-Floor → Overclaim → Foehn → Strip.

| #  | Override                       | Trigger                                                                                       | Effekt                                                              | Source                                  |
| -- | ------------------------------ | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- | --------------------------------------- |
| S1 | Wind-OK=0                      | `wind_ok_count == 0` und LLM != not_safe                                                      | → `not_safe`, `safe_window=keins`, no_go_reason "Windrichtung"      | `analyzers.py` Wind-OK-Block            |
| S2 | Aloft-Wind-NoGo                | `aloft_danger_hours >= WIND_TREND_NOTSAFE_HOURS` ODER aloft-Pattern `DURCHGEHEND_DANGER`/`EINGEKESSELT` mit zu kleinem Calm-Gap | → `not_safe`, `primary_no_go=ALOFT_DANGER`, no_go_reason            | `analyzers.py` Aloft-Block (NoGo-Pfad)  |
| S3 | Aloft-Danger → conditional     | `aloft_danger_hours >= WIND_TREND_CONDITIONAL_HOURS` ODER `aloft_gust_danger_hours >= cond_thresh`, LLM = safe | → `conditional`, caution_note "Gefahr in der Hoehe …"               | `analyzers.py` Aloft-Block (Cond-Pfad)  |
| S4 | Boeen-Floor                    | `gust_warn_hours + aloft_gust_warn_hours >= WIND_TREND_NOTSAFE_HOURS` ODER analoges fuer DANGER, LLM = safe | → `conditional`, caution_note mit max. Boeenwert                    | `analyzers.py` Boeen-Floor-Block        |
| S5 | Overclaim-Ceiling              | LLM = not_safe, `hard_warning_hours == 0`, `clean_hours_count >= 4`                           | → `conditional`, no_go_reasons geleert, caution_note "Auto-Korrektur" | `analyzers.py` Overclaim-Block         |
| S6 | Foehn-Vorsicht                 | `evaluate_foehn().level == "caution"` (ΔP 4-7 hPa, Richtung passt), LLM = safe                 | → `conditional`, `foehn_risk=moderate` falls bisher none, caution_note "Foehn-Vorsicht" | `analyzers.py` `_apply_foehn_override` |
| S7 | Foehn-Gefahr                   | `evaluate_foehn().level == "danger"` (ΔP ≥ 8 hPa), LLM != not_safe                             | → `not_safe`, `foehn_risk=high`, `primary_no_go=FOEHN`, no_go_reason | `analyzers.py` `_apply_foehn_override` |
| S8 | Foehn-Strip irrelevant         | Aktive Foehn-Richtung != `kritischer_foehn` des Spots                                          | `foehn_risk=none`, Foehn-Eintraege aus caution_notes/no_go_reasons UND aus `summary`/`wind_summary`/`wind_shear` entfernt | `weather_context.py` `_strip_irrelevant_foehn` |

---

## 3. Safety-Overrides — Region

`_post_process_safety_region(result, region, date_str)` in `engine/analyzers.py`.

| #  | Override                       | Trigger                                                                                       | Effekt                                                              | Source                                  |
| -- | ------------------------------ | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- | --------------------------------------- |
| R1 | Wind-Strong-Mehrheit           | `calm == 0`, `strong > moderate`, LLM in (safe, conditional)                                   | → `not_safe`, no_go_reason "Durchgehend starker Wind"               | `analyzers.py` Region Wind-Block        |
| R2 | Aloft-Danger NoGo              | analog S2                                                                                     | → `not_safe`                                                        | `analyzers.py` Region Aloft (NoGo-Pfad) |
| R3 | Aloft-Danger conditional       | analog S3                                                                                     | → `conditional`, caution_note                                       | `analyzers.py` Region Aloft (Cond-Pfad) |
| R4 | Foehn-Vorsicht                 | analog S6                                                                                     | → `conditional`, `foehn_risk=moderate`, caution_note                | `analyzers.py` `_apply_foehn_override` |
| R5 | Foehn-Gefahr                   | analog S7                                                                                     | → `not_safe`, `foehn_risk=high`, no_go_reason                       | `analyzers.py` `_apply_foehn_override` |
| R6 | Foehn-Strip irrelevant         | analog S8                                                                                     | analog S8                                                           | `weather_context.py` `_strip_irrelevant_foehn` |

---

## 4. Flyability-Overrides — Spot

`_post_process_flyability_spot(result, spot, date_str, region_result)` in `engine/analyzers.py`.

| #  | Override                       | Trigger                                                                                       | Effekt                                                              | Source                                |
| -- | ------------------------------ | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- | ------------------------------------- |
| F1 | not_safe → leeres Flyability   | `safety_status == not_safe`                                                                   | `fly_status=""`, leeres `streckenflug`-Dict, rating per `_compute_rating_from_subratings(..., "not_safe")` | `analyzers.py` Anfang Post-Process    |
| F2 | Downgrade keine Thermik        | tier in (green, violet) UND (`thermal_hours_total == 0` ODER `peak_climb_proxy < 0.3`)        | tier → `gray`                                                       | `analyzers.py` Flyability-Downgrade   |
| F3 | Downgrade ROUGH-UNUSABLE>50%   | tier in (green, violet) UND `rough_danger_h / thermal_hours_total > 50%`                       | tier → `gray`                                                       | `analyzers.py` Flyability-Downgrade   |
| F4 | Downgrade prod_h zu wenig      | tier in (green, violet) UND `productive_thermal_h < PRODUCTIVE_HOURS_DOWNGRADE`                | tier → `gray`                                                       | `analyzers.py` Flyability-Downgrade   |
| F5 | gray → green Upgrade           | tier == gray UND `productive_thermal_h >= PRODUCTIVE_HOURS_FOR_GREEN` UND `rough_pct < 50`     | tier → `green`, `peak_climb_rate`, `flight_type`, `recommendation` ueberschrieben | `analyzers.py` gray→green-Block      |
| F6 | Region-Gate violet → green     | Spot-tier = violet UND `region_result.flyability_tier != violet`                              | tier → `green`                                                      | `analyzers.py` Region-Gating-Block    |

> Cache-Quellen: `_ctx_tq_cache[name|date]` enthaelt `thermal_hours_total`, `rough_danger_h`,
> `peak_climb_proxy`, `productive_thermal_h`. Schwellen in `config.py`
> (`PRODUCTIVE_HOURS_DOWNGRADE`, `PRODUCTIVE_HOURS_FOR_GREEN`).

---

## 5. Flyability-Overrides — Region

`_post_process_flyability_region(result, region, date_str)` in `engine/analyzers.py`.

| #  | Override                       | Trigger                                                                                       | Effekt                                                              | Source                                |
| -- | ------------------------------ | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- | ------------------------------------- |
| FR1 | not_safe → leeres Flyability  | analog F1                                                                                     | analog F1                                                           | `analyzers.py` Region-Flyability-Anfang |
| FR2 | Downgrade keine Thermik       | analog F2                                                                                     | analog F2                                                           | `analyzers.py` Region-Flyability-Downgrade |
| FR3 | Downgrade ROUGH-UNUSABLE>50%  | analog F3                                                                                     | analog F3                                                           | `analyzers.py` Region-Flyability-Downgrade |
| FR4 | Downgrade prod_h zu wenig     | analog F4                                                                                     | analog F4                                                           | `analyzers.py` Region-Flyability-Downgrade |
| FR5 | gray → green Upgrade          | analog F5                                                                                     | analog F5 (kein Streckenflug-Block, da Region keine Spots auflistet) | `analyzers.py` Region-Flyability gray→green |

---

## 6. UI-Sicherheits-Backstops

Selbst wenn das LLM `foehn_risk` korrekt setzt, das LLM aber keinen Eintrag in
`caution_notes`/`no_go_reasons` schreibt, rendern Spot- und Region-Overlay
trotzdem ein Foehn-Badge:

| Datei                         | Logik                                                                                       |
| ----------------------------- | ------------------------------------------------------------------------------------------- |
| `static/js/region-map.js`     | `foehn_risk != none` UND keine Foehn-Erwaehnung in `caution_notes/no_go_reasons` → eigenes Alert-Badge (`Foehn-Vorsicht`/`Foehn-Gefahr`) |
| `static/js/meteogram.js`      | Identische Logik (Spot-Overlay)                                                             |
| `static/js/briefing.js:912`   | Bestehender Pfad: `safety.foehn_risk` rendert eigene Warn-Zeile                             |

---

## 7. Caches

| Cache                        | Init                          | Befuellung                                                | Genutzt von                                                |
| ---------------------------- | ----------------------------- | --------------------------------------------------------- | ---------------------------------------------------------- |
| `_ctx_gust_cache`            | `chat_engine.py` Konstruktor  | `weather_context.py` (Spot/Region Context-Build)          | Pre-Filter, Wind-OK/Aloft/Boeen-Floor/Overclaim-Overrides  |
| `_ctx_tq_cache`              | `chat_engine.py` Konstruktor  | `weather_context.py` (Spot/Region Context-Build)          | Flyability-Downgrades + gray→green Upgrade                 |
| `_ctx_foehn_cache`           | `chat_engine.py` Konstruktor  | `weather_context.py` `_format_foehn_info(cache_key=…)`    | Foehn-Override (Spot/Region Safety-Phase)                  |

Alle drei werden in `analyzers.py` zu Beginn jedes Analyse-Laufs geleert
(`_ctx_*_cache.clear()`), damit Daten aus alten Spots/Tagen nicht durchsickern.

---

## Changelog

- **2026-04-28** — Foehn-Override (S6/S7/R4/R5) hinzugefuegt; `_strip_irrelevant_foehn`
  bereinigt jetzt auch `summary`/`wind_summary`/`wind_shear` (S8/R6); UI-Backstop
  in `region-map.js` und `meteogram.js` ergaenzt.
