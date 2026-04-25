# Höhenwind-Halluzinations-Problem

**Analysiert: 2026-04-24**

## Symptom

Die LLM produziert Höhenwind-Warnungen in `caution_notes` / `summary`, obwohl der zugehörige Tag (`[ALOFT-WARN]` / `[ALOFT-DANGER]`) im Datenblock **nicht** gesetzt ist. Das Problem tritt in mehreren Regionen parallel auf — ist also strukturell, nicht Einzelfall.

## Belegte Fälle (24.04.2026)

### 1. Mittelland Ost
- **Display**: „kraeftiger Hoehenwind 11-12h: Wind in der Flugschicht 20-30 km/h, sportlich."
- **Echte Daten** (`data/wetterdaten.json` → `_regions.mittelland_ost.pressure_level_data`):
  - 11h PL in Flugbereich: max 16 km/h (900 hPa)
  - 12h PL in Flugbereich: max 15 km/h (850 hPa)
  - Bodenwind: 4–6 km/h, alle Stunden `[WIND-CALM]`
- **Kontext-Block** (generiert via `_build_single_region_context` → Datei `mo_ctx.txt`): enthält **kein** Wort „ALOFT", „Hoehenwind", „20-30", „kraeftig".
- **Fehler**: Reine Halluzination ohne jeden Trigger.

### 2. Oberwallis / Goms (elev_ref 2200 m)
- **Display**: „HOEHENWIND: Zunehmend, Pilot muss vor Eskalation landen, 13–14h."
- **Echte Daten**:
  - 700 hPa (3114 m, im Flugbereich): 7.5 → 10 km/h über den Tag
  - 600 hPa (4338 m, **außerhalb** Flugbereich): 22.6 → 10 km/h **abnehmend**
  - Kein Level in Flugbereich > 20 km/h
- **Fehler**: Kein ALOFT-Tag → trotzdem Template-Satz „Zunehmend / vor Eskalation landen".

### 3. Chur / Mittelbünden (Südbünden, elev_ref 1700 m)
- **Display**: „kraeftiger Hoehenwind 13:00: 20-30 km/h, sportlich." + „Zunehmender Höhenwind nach 12:00, Pilot muss vor Eskalation landen."
- **Echte Daten**:
  - 600 hPa (4330 m): 30.6 (10h) → 25.4 (13h) → 22.2 (17h) — **abnehmend**
  - 700 hPa (3111 m): 12.4 (10h) → 11.9 (13h) → 8.8 (17h) — **abnehmend**
  - Wind ist am **Morgen am stärksten**, nicht nach 12:00
- **Fehler**: Trend-Richtung vollständig umgekehrt.

## Ursache

### 1. Skill-Templates leaken Schwellen-Bänder wortwörtlich in den System-Prompt

**`skills/shared/_input_map.md:25`**
```
[ALOFT-WARN] — Flugschicht-Wind 20-30 km/h (sportlich, noch fliegbar)
```

**`skills/shared/_hazard_blocks.md:207`**
```
[ALOFT-WARN] → Vorsicht, sportlich (20-30 km/h).
```

**`engine/_common.py:958-961` (`_format_aloft_trend_text`, Pattern DURCHGEHEND_WARN)**
```python
f"HOEHENWIND-TREND: DURCHGEHEND (WARN-Level) — Hoehenwind in {ac} von {tc}h "
f"bei {warn_kmh:.0f}-{danger_kmh:.0f} km/h, laengstes ruhiges Fenster {calm_gap}h. "
f"→ maximal conditional, nicht not_safe. Sportlich in caution_notes erwaehnen."
```

**`engine/_common.py:992-998` (Pattern ZUNEHMEND)**
```python
f"HOEHENWIND-TREND: ZUNEHMEND — Ruhig morgens ({calm_gap}h, bis {calm_end}), "
f"danach {ac}h Hoehenwind ({dc}h > {danger_kmh:.0f} km/h). Pilot muss vor Eskalation landen. "
```

Die Formulierungen „20-30 km/h", „sportlich", „zunehmend", „vor Eskalation landen" sind fertige Satz-Bausteine, die die LLM als idiomatische Ausdrucksweise merkt und reproduziert — auch wenn der zugehörige Tag im aktuellen Datenblock nie gesetzt wurde.

### 2. Keine Post-Validierung in `engine/analyzers.py`

Es existieren nur harte Overrides für DANGER-Tags (WIND-STRONG, ALOFT-DANGER bei ≥ N Stunden). Für WARN-Tags und Trend-Texte in `caution_notes` / `summary` gibt es **keinen einzigen Guard**, der prüft, ob das Thema tatsächlich im Tag-Set vorkommt.

### 3. LLM-Standardverhalten: Templates als „Autovervollständigung"

Immer wenn die LLM „etwas Umsichtiges" in `caution_notes` schreiben will, greift sie in den Template-Topf des System-Prompts. Das passiert nicht-deterministisch — ein früherer Lauf für Mittelland Ost am 24.04. hatte korrekt `caution_notes: []` (siehe `data/region_analyses.json:7483`), der 18:07-Lauf erfand die Höhenwind-Warnung.

## Datenspur / Beweis

- **Stored Analyse** (älterer Lauf, korrekt): `data/region_analyses.json` → `mittelland_ost["2026-04-24"].safety.caution_notes == []`
- **Display** (späterer 18:07-Lauf, halluziniert): Screenshot vom User. Peak 2.2 m/s (stored: 2.0) bestätigt dass es ein NEUER Lauf mit anderem Output ist.
- **Generierter Kontext**: `mo_ctx.txt` (5861 chars) — 0 Matches für ALOFT / Hoehenwind / 20-30 / kraeftig.
- **Rohdaten PL-Winde** Mittelland Ost + Oberwallis/Goms + Chur/Mittelbünden: siehe Messungen oben.

## Fix-Vorschlag (strukturell, zweistufig)

### Stufe 1 — Post-Check (sofort umsetzbar, hoher ROI)

In `engine/analyzers.py` nach jedem Region- und Spot-LLM-Call:

```python
CAUTION_KEYWORD_REQUIREMENTS = {
    ("hoehenwind", "höhenwind", "flugschicht-wind"): ["ALOFT-WARN", "ALOFT-DANGER"],
    ("boe", "böe", "turbulenz"): ["GUST-WARN", "GUST-DANGER", "ALOFT-GUST-WARN", "ALOFT-GUST-DANGER"],
    ("scherung", "shear"): ["SHEAR-UNUSABLE", "SHEAR-DEGRADED"],
    ("zunehmend", "eskalation"): None,  # erfordert aloft_trend == ZUNEHMEND
}
```

Pro `caution_notes`-Zeile: wenn Keyword enthalten, aber kein zugehöriger Tag im `tag_counts` → Zeile löschen + Warn-Log. Gleich für `summary` (Halluzinations-Satz durch neutrales ersetzen oder entfernen).

### Stufe 2 — Skill-Härtung (nachgelagert)

1. Zahlen-Bänder (`20-30 km/h`) aus Tag-Definitionen in `_input_map.md` und `_hazard_blocks.md` **entfernen**. Nur Tag-Name + qualitative Bedeutung. Die km/h-Schwelle gehört in die Doku, nicht in den System-Prompt.
2. Template-Phrasen in `_format_aloft_trend_text` kürzen: nur nüchterne Fakten („Trend: abnehmend", „Peak: Xh"), keine Handlungsanweisungen („Pilot muss vor Eskalation landen") — die bedienen die LLM als fertige Satz-Schablonen.
3. Neue strikte Regel in `_core_principles.md`: *„caution_notes DÜRFEN NUR Themen nennen, zu denen mindestens ein entsprechender Tag im Datenblock steht. Tag-Name suchen, dann formulieren — nicht umgekehrt."*

### Messbarer Effekt

Nach Stufe 1 sollte im Log gezählt werden, wie oft die LLM halluziniert. Das liefert die Datenbasis für Stufe 2.

## Priorität
Hoch — das Problem untergräbt das Vertrauen in die Flug-Empfehlungen. Piloten treffen Start-/Landeentscheidungen auf Basis dieser caution_notes. Trend-Umkehr (Südbünden: „zunehmend" statt „abnehmend") ist sicherheitsrelevant.
