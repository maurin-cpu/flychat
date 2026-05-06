# Override-Konzept

Gleitcast verwendet ein **zweistufiges Analyseprinzip**: Das LLM produziert eine
initiale Einschätzung, die Decision-Engine korrigiert und ergänzt sie deterministisch.
Overrides sind die Mechanismen dieser Korrekturen.

## Architektur-Überblick

```
Wetterdaten (Cache)
       │
       ▼
  _prefilter_not_safe          ← Pre-Filter: klare Not-Safe-Fälle VOR dem LLM
       │
       ▼ (falls nicht gefiltert)
    LLM-Analyse                ← Produziert safety_status, Sub-Ratings, Prosa
       │
       ▼
  Safety-Decisions             ← Überschreiben safety_status / caution_notes
  (WindOk0, Aloft, Gust,
   Foehn, SubRatingFloor …)
       │
       ▼
  Flyability-Decisions         ← Überschreiben flyability_tier
  (MechDanger, LowReward,
   Upgrade, RegionGate …)
       │
       ▼
  IsConditional                ← Housekeeping: is_conditional aus safety_status
       │
       ▼
  Foehn-Strip                  ← Bereinigt Prosa bei irrelevantem Foehn
       │
       ▼
  Finales Resultat
```

## Eskalations-Prinzip

Overrides **eskalieren grundsätzlich** (safe → conditional → not_safe).
Einzige Ausnahme: **OverclaimRelax** demotiert (not_safe → conditional),
wenn LLM übertrieben hat.

---

## Pre-Filter

Läuft **vor dem LLM**. Wenn ein klarer Not-Safe-Fall erkannt wird, wird das
LLM gar nicht aufgerufen — das Resultat wird direkt gebaut.

| Name | Trigger | Resultat |
|---|---|---|
| `_prefilter_not_safe` — kein Fenster | `active_window_start = None` (kein zusammenhängender Block ≥ min. Stunden) | `not_safe` |
| `_prefilter_not_safe` — kein Wind-OK | Alle Stunden mit harten Warnungen belegt | `not_safe` |
| `_prefilter_not_safe` — ganztag Regen | `rain_cnt >= total_hours - 2 AND rain_cnt >= 4` | `not_safe` |
| `_prefilter_not_safe` — ganztag Gewitter | `thunderstorm_h >= total_hours - 2 AND thunderstorm_h >= 4` | `not_safe` |

---

## Safety-Decisions (Post-LLM, Safety-Phase)

Reihenfolge entspricht der Ausführungsreihenfolge in `analyzers.py`.

### Spot-Decisions

| Name | Tracking-Tag | Trigger | Effekt | Richtung |
|---|---|---|---|---|
| `decide_wind_ok_zero` | `WindOk0` | `wind_ok_count == 0` | `safety_status = not_safe` | ↑ |
| `decide_aloft_not_safe` | `AloftNotSafe(Xh)` | `aloft_danger_hours ≥ NOTSAFE_THRESHOLD` ODER Pattern `DURCHGEHEND_DANGER` ODER `EINGEKESSELT` mit Calm-Gap < Threshold | `safety_status = not_safe` | ↑ |
| `decide_aloft_conditional` | `AloftConditional(Xh)` | `aloft_danger_hours ≥ COND_THRESHOLD` UND `safety_status == safe` | `safety_status = conditional` | ↑ |
| `decide_gust_floor` | `GustFloor` | `gust_warn_hours + aloft_gust_warn_hours ≥ THRESHOLD` UND `safety_status == safe` | `safety_status = conditional` | ↑ |
| `decide_overclaim_relax` | `OverclaimRelax(Xh)` | `safety_status == not_safe` UND `hard_warning_hours == 0` UND `clean_hours ≥ 4` | `safety_status = conditional` | ↓ (einziger Demote) |
| `decide_flyability_mech_danger` | `FlyabilityMechDanger` | `rough_pct > 50` | `safety_status = conditional` + `flyability_tier = gray` | ↑ (cross-cutting) |
| `_apply_foehn_decision` — FoehnDanger | `FoehnDanger(ΔP)` | `foehn_risk = danger` (deterministisch aus ΔP) | `safety_status = not_safe` | ↑ |
| `_apply_foehn_decision` — FoehnCaution | `FoehnCaution(ΔP)` | `foehn_risk = moderate` UND `safety_status == safe` | `safety_status = conditional` | ↑ |
| `_apply_subs_status_floor` | `SubRatingFloor` | `min(8 Sub-Ratings) ≤ 2` ODER `≤ 3` | `≤ 2 → not_safe`, `≤ 3 → conditional` | ↑ |
| `decide_is_conditional` | `IsConditional` | `safety_status == conditional` UND `is_conditional == False` | `is_conditional = True` | Housekeeping |

### Region-Decisions (zusätzlich)

| Name | Tracking-Tag | Trigger | Effekt | Richtung |
|---|---|---|---|---|
| `decide_wind_strong_majority` | `WindStrongMajority(X)` | `calm == 0 AND strong > moderate` | `safety_status = not_safe` | ↑ |

---

## Flyability-Decisions (Post-LLM, Flyability-Phase)

| Name | Tracking-Tag | Trigger | Effekt | Richtung |
|---|---|---|---|---|
| `decide_flyability_low_reward` | `FlyabilityLowReward` | Peak < 0.3 m/s ODER productive_h < Threshold | `flyability_tier = gray` | ↓ |
| `decide_flyability_mech_danger` | `FlyabilityMechDanger` | `rough_pct > 50` | `flyability_tier = gray` + `safety_status = conditional` | ↓ + ↑ |
| `decide_flyability_upgrade` | `FlyabilityUpgrade` | Starke Thermik + ausreichend productive_h | `flyability_tier = green/violet` | ↑ |
| `decide_flyability_region_gate` | `FlyabilityRegionGate` | Region-Analyse schlechter als Spot | Bremst Tier nach unten | ↓ |

---

## Was Overrides NICHT überschreiben

- **Prosa-Felder** (`summary`, `wind_summary`, `wind_shear`): bleiben immer LLM-Text.
  Ausnahme: Foehn-Strip bereinigt aktiv foehn-bezogene Formulierungen bei
  irrelevantem Foehn.
- **Niederschlag / Gewitter / CAPE / Sicht** (Teiltag): kein deterministischer
  Override — werden vom LLM via Sub-Ratings bewertet, SubRatingFloor konvertiert.

## Tracking

Jede feuernde Decision schreibt einen Tag in `result["_decisions_applied"]`,
z.B. `["FoehnCaution(4.5)", "GustFloor", "SubRatingFloor"]`. Sichtbar in der
Analyse-Detailansicht und den Logs.

## Schwellenwerte

Alle Schwellen sind in `config.py` definiert:

| Konstante | Bedeutung |
|---|---|
| `WIND_TREND_NOTSAFE_HOURS` | Stunden Aloft-Danger → not_safe |
| `WIND_TREND_CONDITIONAL_HOURS` | Stunden Aloft-Danger → conditional |
| `WIND_DANGER_KMH` | Boden-/Hoehenwind-Gefahr-Schwelle |
| `GUST_DANGER_KMH` | Boeen-Gefahr-Schwelle |
| `CAPE_WARN_JKG` | CAPE-Warn-Schwelle (800 J/kg) |
| `CAPE_DANGER_JKG` | CAPE-Danger-Schwelle (1500 J/kg) |
