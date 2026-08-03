# validation/ — alle Validierungen unter einem Dach

Hier wird geprüft, ob unsere Vorhersagen stimmen. **Eine Domäne = ein
Unterordner**, alle nach derselben Bauart. Dieser Ordner ist der **Beleg-Ort** —
Pläne liegen wie üblich in `docs/pläne/`, fertige Verfahren in `docs/`.

| Domäne | Richter (Wahrheit) | Füllung | seit |
|---|---|---|---|
| [`xcontest/`](xcontest/README.md) | XContest-Tageswertung (Mensch kuratiert) | manuell | 05/2026 |
| [`fronten/`](fronten/README.md) | spätere DWD-Handanalyse derselben Gültigkeitszeit | automatisch | 07/2026 |
| [`gewitter/`](gewitter/README.md) | SwissMetNet-Stationsmessungen (MeteoSchweiz OGD) | automatisch | 08/2026 |

Kandidaten für weitere Domänen (Pläne existieren): Thermik
(`PLAN_binaerer_thermiktag.md`), OGN-Flugaktivität (`PLAN_ogn_validation.md`),
Wind/Böen.

## Die Bauart — was jede Domäne enthält

```
validation/<domäne>/
├─ README.md        Zweck + GRENZEN des Richters (Pflicht: was die Wahrheit
│                   NICHT sagen kann — z. B. Stationsnetz-Lücken)
├─ SCHEMA.md        Dateiformate des Ordners
├─ PATTERNS.md      menschliche Befunde, kuratiert (der Ertrag des Ganzen)
├─ AUTO_REPORT.md   maschinell erzeugter Tagesstand — nie von Hand editieren
└─ <daten>          Domänen-spezifisch (messwerte/, urteile/, observations.csv …)
```

## Die drei gemeinsamen Regeln

1. **Prognosen werden zentral eingefroren**, nicht pro Domäne:
   `data/weather_archive/YYYY-MM-DD.json` (täglich via
   `scripts/snapshot_weather.py`). Eine Domäne liest den Freeze, sie
   dupliziert ihn nie. Was dort fehlt, kann rückwirkend nicht validiert
   werden — fehlende Felder darum dort ergänzen, nicht lokal sammeln.
2. **Urteile haben ein gemeinsames Schema** (`scripts/validation_common.py`):
   `Datum · Objekt (Region/Spot/Zone) · vorhergesagt · eingetreten · Urteil
   (treffer | verpasst | fehlalarm | still) · Zeitfenster`. Damit sind
   AUTO_REPORTs über Domänen hinweg vergleichbar.
3. **Modell gegen Modell ist keine Validierung.** Richter ist immer eine
   Beobachtung (Messung, Handanalyse, echte Flüge). Lehre vom 02./03.08.:
   XC Therm als Massstab führte zu Fehlschlüssen, die die SwissMetNet-Messung
   am selben Tag umdrehte.

## Takt

Der Scheduler ruft die automatischen Domänen **morgens nach dem ersten
Wetterlauf** für den **Vortag** auf — failure-tolerant, eine ausgefallene
Validierung stoppt nie den Wetterlauf. Jedes Tages-Skript ist idempotent und
kann Lücken nachholen (`--backfill`).

## Geschichte

Bis 03.08.2026 lagen `xcontest_validation/` und `fronten_validation/` im
Repo-Root; mit der dritten Domäne (Gewitter) wurden sie hierher gezogen und
die Bauart als Konvention festgeschrieben.
