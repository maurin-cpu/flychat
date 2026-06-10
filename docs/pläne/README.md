# Pläne (noch nicht umgesetzt)

Dieser Ordner enthält **approved/entworfene Pläne, deren Implementierung noch nicht
(oder noch nicht messbar) begonnen wurde**. Sobald ein Plan im Code umgesetzt ist,
wandert das Dokument zurück nach `docs/` und wird dort zur beschreibenden Doku
umgeschrieben.

| Plan | Status (geprüft gegen Code, Mai 2026) |
|---|---|
| [`PLAN_safety_region_cap.md`](PLAN_safety_region_cap.md) | **Nicht begonnen.** Keine Telemetrie/Caution-/Eskalations-Logik in `engine/analyzers.py`, kein `scripts/extract_safety_mismatch_telemetry.py`. `region_result` wird nur in der Flyability genutzt, nicht im Safety-Post-Processing. |
| [`PLAN_startrichtung_faecher.md`](PLAN_startrichtung_faecher.md) | **Nicht begonnen.** `scripts/build_pge_csv.py` kollabiert die Sektoren weiterhin auf 0/1, `windrichtung_optimal` existiert nirgends. |
| [`PLAN_code_analyse_2026-06.md`](PLAN_code_analyse_2026-06.md) | **In Arbeit** (erstellt 2026-06-10, Paket 3 am 10.06. abends im Code/Live-Daten verifiziert — inkl. Korrektur: Vorfilter funktioniert, nur Telemetrie-Zähler kaputt; 7 statt 2 ungeschützte Endpoints). Code noch unverändert; Umsetzung startet mit Paket 3, Reihenfolge im Abschnitt „Stand der Umsetzung". |

## Verwandte, aber **umgesetzte** Themen (liegen in `docs/`)

- `docs/METEOGRAM_OVERDEVELOPMENT.md` — CAPE-Symbol im Meteogramm: Code live, nur
  Nutzer-Abnahme + UX-Entscheid offen.
- `docs/THERMIK_TERRAIN_KALIBRIERUNG.md` — 5-Zonen-System: vollständig produktiv.
- `docs/FEW_SHOT_PIPELINE.md` — Schritt 1+2 live, nur Eval-Suite (Schritt 3) offen.
- `docs/TQ_TORN_FLYABILITY.md` — TORN (Scherung zerreißt Thermik) → Fliegbarkeit:
  10m-Anker-Fix + Binär-Gate auf `productive_thermal_h` + TORN-Prosa-Pflicht, umgesetzt
  2026-06-04 (war `TQ_RATING_PLAN.md`). Offen: Replay über mehr Wetterlagen.
