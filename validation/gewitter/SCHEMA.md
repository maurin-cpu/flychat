# Dateiformate — validation/gewitter/

Alle Zeiten **lokal** (Europe/Zurich). Quelle der Messwerte: MeteoSchweiz OGD
SwissMetNet, **Zehnminutendateien** (`ogd-smn_<abbr>_t_recent.csv`, UTC → beim
Einlesen nach lokal verschoben). Bewusst nicht die Stundenwerte: die
Stunden-Aggregation verwässert die Signatur — beide reale Gewitter vom 02.08.
fielen auf Stundenbasis unter die Schwellen.

## messwerte/YYYY-MM-DD.json

```jsonc
{
  "_meta": { "tag": "2026-08-02", "stationen": 144,
             "quelle": "MeteoSchweiz OGD SMN, Zehnminutenwerte", "signatur": "..." },
  "stationen": {
    "alt": {                       // Stations-Kürzel (klein)
      "name": "Altdorf", "elev": 438, "region": "Zentralschweizer Voralpen",
      "stunden": { "21:50": [rain_mm, gust_kmh, temp_c, sonne_min, druck_hpa], ... }
    }
  },
  "regionen": {
    "Zentralschweizer Voralpen": {
      // Signatur auf gleitenden 30-min-Fenstern; Zeit = Fensterende.
      // Ein Eintrag je Station (der stärkste Treffer des Tages),
      // Rangfolge gewitter > schauer > ausfluss.
      "gewitter":  [["21:50", "alt", regen_mm_30min, boeensprung_kmh, temp_delta_k], ...],
      "schauer":   [["15:10", "elm", regen_mm_30min], ...],
      // ausfluss = konvektive Kaltluft OHNE Regen (Böensprung + Temperatur-
      // sturz + Druckanstieg, Schwellen der Böenfront-Analyse 30.07.).
      // KEIN Gewitter-Beweis (dieselbe Signatur erzeugte die trockene Front
      // vom 30.07.) — markiert den blinden Fleck der Gewitter-Signatur,
      // wird nur gespeichert, nie angezeigt, ändert kein Urteil.
      "ausfluss":  [["17:40", "pil", boeensprung_kmh, temp_delta_k, druck_delta_hpa], ...],
      "sonne_1218_pct": 60        // Median über die Stationen, null = keine Daten
    }
  }
}
```

## urteile/YYYY-MM-DD.json

Ein Eintrag je Region × Fenster (`flug` = 10–18 Uhr, `abend` = 18–24 Uhr):

```jsonc
{
  "_meta": { "tag": "2026-08-02", "prognose_quelle": "data/weather_archive/2026-08-02.json" },
  "urteile": [
    {
      "region": "Zentralschweizer Voralpen",
      "fenster": "flug",
      "gemessen":  ["21:50"],                     // leere Liste = nichts gemessen
      "schauer":   [],
      "sonne_1218_pct": 60,
      "schwelle_40": { "angezeigt": ["15:00","16:00"], "urteil": "verpasst", "dt_h": null },
      "schwelle_50": { ... },                     // 40 = Live-Schwelle; 50/60 zur Eichung
      "schwelle_60": { ... }
    }
  ]
}
```

`angezeigt` wird aus dem eingefrorenen Snapshot mit der **aktuellen**
Anzeige-Regel nachgerechnet (dieselbe Funktion wie die App:
`convection.thunder_anchor_ok` — eine Quelle der Wahrheit). Das
Scoreboard eicht also die heutige Regel; welche das war, steht in
`_meta.regel`. Ändert sich die Regel, wird das Scoreboard aus den
Urteils-Rohdaten neu gerechnet (`rebuild_scoreboard` ist idempotent).

## scoreboard.json

Laufende Summen seit 31.07., je Fenster und je Schwellen-Variante — die
Varianten werden aus den gespeicherten Roh-Prozenten **parallel** gerechnet:

```jsonc
{
  "_meta": { "von": "2026-07-31", "bis": "2026-08-02", "regeln": "anker=regen-pflicht (03.08.)" },
  "flug": {
    "schwelle_40": { "treffer": 2, "verpasst": 1, "fehlalarm": 4, "still": 80 },
    "schwelle_50": { ... },
    "schwelle_60": { ... }
  },
  "abend": { ... }
}
```

## Nicht hier

- **Eingefrorene Prognosen** → zentral in `data/weather_archive/` (Regel 1,
  `validation/README.md`).
- **Überentwicklungs-Urteile** → kommen mit der weichen Stufe dazu (Schauer +
  Sonnenanteil sind in den Messwerten schon erfasst).
