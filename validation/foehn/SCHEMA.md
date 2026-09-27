# validation/foehn — Schema

## messwerte/<ABK>_foehnindex_2024-.csv

Reduzierter Auszug der SwissMetNet-OGD-Dateien
(`ogd-smn_<abk>_t_historical_2020-2029.csv` + `…_t_recent.csv`), Trenner `;`.

| Spalte | Bedeutung |
|---|---|
| station | Stationskürzel (ALT, CHU, …) |
| reference_timestamp | `dd.mm.yyyy HH:MM`, **UTC**, Zehnminutentakt |
| wcc006s0 | Föhnindex: 0 kein Föhn · 1 Föhnmischluft · 2 Föhn · leer = fehlt |
| dkl010z0 | Windrichtung 10 min (°) |
| fkl010z0 | Windgeschwindigkeit 10-min-Mittel (m/s) |
| fkl010z1 | Böenspitze 1 s (m/s) |
| tre200s0 | Lufttemperatur 2 m (°C) |
| ure200s0 | relative Feuchte (%) |
| prestas0 | Stationsdruck (hPa) |

Neu beschaffen: siehe Download-Block in der Session-Historie bzw.
`scripts/backtest_foehn.py` (Docstring); Kürzel in der URL klein geschrieben.

## modell/<seite>_best_match_2024-2026.json

Rohantwort von `https://historical-forecast-api.open-meteo.com/v1/forecast`
für Zürich (47.37, 8.55) bzw. Lugano (46.0, 8.96), `timezone=UTC`, stündlich:
`pressure_msl, relative_humidity_2m, wind_speed_10m, wind_gusts_10m,
wind_speed_700hPa, wind_direction_700hPa, surface_pressure, temperature_2m`.

## scoreboard.json

```
{ "period_utc": [von, bis],
  "stations": [ { station, name, region, side,
                  hours_evaluated, foehn_hours, misch_hours,
                  pod_pct, miss_hours, false_alarm_hours, far_pct, misch_warned_pct,
                  foehn_days, warn_days, day_pod_pct, day_far_pct,
                  dp_foehn_p10/p50/p90, dp_none_p50/p90/p99,
                  foehn_hours_dp_below_4_pct, foehn_hours_dp_below_2_pct } ],
  "dp_sweep": { ABK: [ {thr, pod_pct, far_pct, fa_hours} … ] } }
```

Definitionen: Stunde = Föhn bei ≥ 3 von 6 Zehnminutenwerten Index 2;
Mischluft bei ≥ 3/6 Index ≥ 1 ohne Föhn. Nur Flugfenster
(`config.FLIGHT_HOURS_START/END`, lokal). Warnung = `level ∈ {caution,
danger}` mit `kritischer_foehn` der Station (Süd oder Nord). POD =
Treffer/Föhnstunden, FAR = Fehlalarm/(Fehlalarm+Treffer). Föhntag = ≥ 1
Föhnstunde im Flugfenster; Warntag = ≥ 1 Warnstunde.
