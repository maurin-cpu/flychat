# Analytics: Messung der Spot- und Regionsansicht

**Stand:** 2026-11-08 · Gilt für die App (`app.wingcast.ch`), Seiten `/briefing`
und Karte mit Spot-Fenster. Die Mail-Events (`briefing_sent`, `briefing_opened`,
`briefing_clicked`) sendet der Server, siehe `docs/BRIEFING.md`.

## Warum

Die Spot- und Regionsansicht wird umgebaut: vom KI-Fliesstext zu Fakten-Chips
mit kurzem KI-Satz. Damit wir vorher und nachher vergleichen können, misst die
App seit 08.11.2026, welche Teile gesehen, aufgeklappt und wie lange offen sind.

**Grenze:** wenige Konten (Herbst 2026: rund 15 aktiv in 28 Tagen) und starke
Saison. Verglichen werden Anteile je Besuch, keine absoluten Zahlen. Die
Messung zeigt, ob etwas schlechter wird. Ob die neue Ansicht *besser
verstanden* wird, klärt der Test mit Piloten (Marketing-Repo,
`2-ausfuehrung/interviews/`).

## Version der Ansicht

Jedes App-Event trägt die Super-Property **`ui_spots`** aus
`config.UI_SPOTS_VERSION` (Umgebungsvariable `UI_SPOTS_VERSION`), gesetzt in
`templates/base.html` per `posthog.register`.

| Wert | Ansicht |
|---|---|
| `text_v1` | KI-Fliesstext (bis zum Umbau) |
| `chips_v2` | Fakten-Chips mit kurzem KI-Satz (beim Umbau setzen) |

## Events

Gesendet über `window.wcTrack` (No-op ohne PostHog, Admin wird nie gemessen).
Keine Personendaten in den Eigenschaften; Spotname und Region-id sind erlaubt.

### Briefing-Seite (`static/js/briefing.js`, `view: "briefing"`)

Alle tragen zusätzlich `day_idx` (gewählter Tag, 0 = heute).

| Event | Eigenschaften | Wann |
|---|---|---|
| `bf_region_toggled` | `region_id`, `open` | Region auf- oder zugeklappt |
| `bf_regions_bulk_toggled` | `open` | „Alle auf/zu" |
| `bf_spot_toggled` | `spot`, `region_id`, `band`, `rating`, `open` | Spot-Zeile auf- oder zugeklappt |
| `bf_assessment_toggled` | `kind` (`safety`/`fly`), `spot`, `region_id`, `band`, `rating`, `open` | KI-Text „Sicherheit" / „Flug" im Spot |
| `bf_chain_toggled` | `block` (lage, fronts, foehn, wind, stability, thermik, sonne, modelle), `open`, `source` (`click`/`alert`) | Block der Analyse-Kette; `alert` = über eine Warnkachel geöffnet |
| `bf_numbers_toggled` | `open` | „Zahlen einblenden" im Meteogramm |
| `block_seen` | `block` (`alerts`/`chain`/`regions`), `ms_visible` | einmal pro Seitenaufruf beim Verlassen, nur ab 1 s Sichtdauer |

### Spot-Fenster in der Karte (`static/js/map.js`, `view: "spots"`)

Alle tragen `spot` und `date`.

| Event | Eigenschaften | Wann |
|---|---|---|
| `spot_opened` | `source` (`marker`/`url`/`other`), `band` | Spot-Fenster geöffnet |
| `spot_closed` | `ms_open`, `reason` (`close`/`switch`/`hidden`/`pagehide`) | genau einmal je Öffnen |
| `spot_view_switched` | `to` (`meteo`/`daten`) | Umschalten Meteogramm ⇄ Daten (nur echte Klicks) |
| `spot_day_switched` | `day_idx` | Tag im Fenster gewechselt |
| `spot_aside_toggled` | `open` | Analyse-Spalte auf/zu (Handy) |
| `spot_insight_toggled` | `kind` (`safety`/`fly`), `open` | KI-Text im Analyse-Bereich auf/zu |

### Sichtbarkeit (`static/js/ux-tracking.js`)

`wcTrackVisible(el, props)` misst die Sichtdauer eines Blocks. Sichtbar heisst:
die Hälfte des Blocks ist im Bild **oder** der Block füllt die Hälfte des
Bildschirms (für lange Blöcke auf dem Handy). Die Zeit läuft nur bei sichtbarem
Tab. Gesendet wird einmal pro Seitenaufruf beim Verbergen des Tabs oder
Verlassen der Seite, per `sendBeacon`.

## Auswertung

- **Dashboard** in PostHog: „Spots & Regionen: Text vs. Chips", angelegt vom
  Skript `3-betrieb/scripts/posthog_dashboard_spots_regionen.py` im
  Marketing-Repo. Jede Kachel ist nach `ui_spots` aufgeteilt.
- **Bericht:** `3-betrieb/scripts/posthog_spots_regionen.py` im Marketing-Repo,
  schreibt nach `1-planung/analysen/`.

## Beim Umbau beachten

1. `UI_SPOTS_VERSION` auf `chips_v2` setzen (Server-Umgebung oder `config.py`).
2. Die Events oben weiter senden, auch wenn sich das Markup ändert. Neue
   Elemente (z. B. Chips) bekommen eigene Events, alte Namen nicht umdeuten.
3. Diese Tabelle nachführen.
