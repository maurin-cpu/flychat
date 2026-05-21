# Rating-Farbkonzept — Single Source of Truth

**Stand:** 2026-05-17 (Palette **v3.2 "Royal Premium"** final — Sky → Lime → Green-500 → Violet Top)
**Status:** AKTIV — bei jeder Aenderung der Rating-Farben MUSS jeder Touchpoint unten synchron angepasst werden.

---

## 1. Zweck

Das Rating-Farbkonzept ordnet jeder Kombination aus `safety_band` (safe / conditional / not_safe) und `experience_rating` (1–5) **einen eindeutigen Farbton** zu. Dieser Farbton wird **systemweit** verwendet — auf Karten, in Pillen, Spot-Backgrounds, Glyphen, Mini-Maps und Legenden — damit der Pilot dieselbe Region/Spot/Tag-Kombination ueberall sofort wiedererkennt.

Aenderungen am Konzept brechen die Konsistenz, wenn nicht alle Touchpoints angepasst werden. Diese Doku ist die einzige autoritative Liste der Touchpoints.

---

## 2. Aktuelle Palette (v3.2 "Royal Premium" final, Mai 2026)

| Band | Rating | Label | Fill (Hex) | Border (Hex) | Text |
|------|--------|-------|------------|--------------|------|
| safe | 1 | Abgleiter | `#e0f2fe` (**Sky-100**, blue thermal) | `#38bdf8` | dunkel `#075985` |
| safe | 2 | Kurzer Thermikflug | `#bae6fd` (**Sky-200**, klarer Himmel) | `#0ea5e9` | dunkel `#075985` |
| safe | 3 | Solider Thermiktag | `#BEF264` (**Lime-300**, warmer Start) | `#65a30d` | dunkel `#3f6212` |
| safe | 4 | Starker Thermiktag | `#22c55e` (**Green-500**, klassisches Safety-Green) | `#15803d` | **weiss** |
| safe | 5 | XC-Tag / Klassiker | `#a78bfa` (**Violet-400**, Royal Premium) | `#6d28d9` | **weiss** |
| conditional | 1 | Abgleiter | `#fef08a` (Pale-Yellow) | `#ca8a04` | dunkel `#713f12` |
| conditional | 2 | Schwacher Thermiktag | `#facc15` (Gold) | `#a16207` | dunkel `#713f12` |
| conditional | 3 | Solider Thermiktag | `#f97316` (Orange) | `#9a3412` | weiss |
| conditional | 4 | Starker Thermiktag | `#c2410c` (Burnt) | `#7c2d12` | weiss |
| conditional | 5 | XC-Tag | `#7c2d12` (Brown) | `#431407` | weiss |
| not_safe | — | Nicht fliegbar | `#ef4444` (Red) | `#991b1b` | weiss |
| no_data | — | Keine Daten | `#9ca3af` (Cool-Gray) | `#6b7280` | dunkel |

**Prinzip — "Royal Premium" Tier-Hierarchie (final v3.2):**
- **Sky-Blue** (Rating 1+2 safe): signalisiert "blue thermal day" (Pilot-Mental-Modell: blauer Himmel ohne Cumulus = keine Thermik). Cool, ruhig, "still air".
- **Aktive Thermik** (Rating 3-4 safe): Lime (warmes Yellow-Gruen, "erste Sonne, Thermik startet") → **Green-500** (klassisches Safety-Green, saturiert, "starke organisierte Thermik"). Lime → satter Green-Sprung = Pilot sieht sofort "es geht aktiv".
- **Royal Violet** (Rating 5 safe): Premium-Top fuer XC-Tag/Klassiker. Wie Gaming-Tiers (Common→Rare→Epic→**Legendary**). Pilot scrollt durch Gleitcast → Violet-Spots = sofort "DER Tag".
- **Code-Identifier `violet` matched wieder visuell** (v3 stellte v1-Intent her). Premium = Violet, semantisch konsistent.
- **Thermik-Alignment** durchgehend: Meteogramm-Kacheln folgen derselben Skala (`meteogram.js:thermClimbColor`) + Chat-Charts (`chat-charts.js:thermClimbColor`).
- **Conditional bleibt Yellow→Orange→Brown**: Warnsignal-Spektrum klar getrennt.
- **Text-Kontrast:** Rating 1-3 = dunkler Text auf hellem Bg, Rating 4 (Green-500) + Rating 5 (Violet) = weisser Text auf saturierten Bgs, conditional 3+ = weisser Text auf Orange/Burnt.

**Story:** Pilot-Tagesverlauf vom blauen leeren Himmel (1+2 = "noch nichts da") ueber den ersten warmen Lime-Sonnenstrahl (3 = "Solider Thermiktag") zum saturierten Safety-Green der starken organisierten Thermik (4 = "klassischer guter Flugtag") bis zum Legendary Violet (5 = "Wolkenbasis, XC, magisch").

**Naming-Konsistenz (v3.2):** Der Band-Name `violet` matched wieder visuell — Premium-Tier IST Violet. Damit ist die historische Naming-Inkonsistenz aus v2 (`violet` Code = Cyan visuell) aufgeloest.

**Alpha-Regeln (Pillen + Spot-Bg):**
- Helle Bgs (Rating 1+2): alpha 0.55 — atmen lassen
- Dunkle Bgs (Rating 3+, weisser Text): alpha 0.78 — Kontrast halten
- Spot-Bg: viel niedriger (0.07 + rating*0.13) — sehr subtil, da grosse Flaeche
- Spot-Border-Left: 0.35 + rating*0.55

---

## 3. Touchpoints — wo wird die Palette gerendert?

| # | Komponente | Datei | Funktion / Stelle | Verwendet |
|---|------------|-------|-------------------|-----------|
| 1a | **Region-Polygon Fill+Border** (Karte regionen.html) | `static/js/region-map.js:111-141` | `getRatingTint(band, rating)` + `getRatingBorder` | Fill + Border-Weight + Border-Color |
| 1b | **Region-Polygon-Label** (Zahl-Pille im Polygon-Centroid) | `static/js/region-map.js:270-330` | `buildRegionLabel()` Per-Rating ink+ring | Pille-Ring-Farbe + Text-Farbe der Rating-Zahl |
| 2 | **Spot-Marker** (Hauptkarte map.html) | `static/js/map.js:159-178` | `getRatingTint(band, rating)` | Marker-Fill + Stroke |
| 3 | **Glyph-Kreis** (Spot-Header im Gleitcast, Marker-Inneres) | `static/js/shared-glyph.js:28-58` | `ratingTintFor(visBand, rating)` | Kreis-Fill + Stroke + Text-Farbe |
| 4 | **Region-Pill** (Gleitcast Region-Header) | `static/js/briefing.js:1206-1244` | `regionPillSpec(meta)` | Pill-Bg + Border + Text |
| 5 | **Spot-Score-Pill** (Gleitcast Spot-Header) | `static/js/briefing.js:1322-1334` | `regionPillSpec()` reused | Pill-Bg + Border + Text |
| 6 | **Spot-Background** (Gleitcast Spot-Container) | `static/js/briefing.js:1363-1375` | `regionPillSpec()` reused + Alpha-Skala | Bg-Tint + Border-Left |
| 7 | **Mini-Map Marker** (aufgeklappter Spot in Gleitcast) | `static/js/briefing.js:1882-1900` | `bfSafetyRatingStyle()` → ruft `regionPillSpec()` | Marker-Fill + Stroke + Glow |
| 8 | **Rating-Info-Overlay** (Legenden-Modal) | `static/js/rating-info.js:16-34` | `_ratingTint(band, rating)` | Glyph-Beispiele im Overlay |
| 9 | **Thermik-Kacheln** (Meteogramm im Gleitcast + Detail) | `static/js/meteogram.js:137-150` | `thermClimbColor(rate)` | Zellen-Fill nach climb_rate |
| 10 | **Wetterlage-Block** (Gleitcast Top-Pille) | `static/css/briefing.css:125-140` | `.bf-wetterlage` Border-Left + Bg-Gradient | Cyan-Accent (Premium-Farbe) |
| 11 | **Spot-Assessment-Sektionen** (aufgeklappte Spot-Details) | `static/css/briefing.css:2202-2207` | `.bf-assessment--safety/fly/xc` | Border-Left-Akzent pro Sektion |
| 12 | **Spot/Region-Detail-Overlay** (Click auf Marker/Polygon) | `static/js/analysis-view.js:67-110` | `ratingTintSpec(band, rating)` + `buildGlyph()` + `renderHero()` | Hero-Container Bg + Border, Glyph-Fill, Rating-Pill |
| 13 | **Chat-Charts Thermik-Kacheln** (KI-Berater-Visualisierungen) | `static/js/chat-charts.js:59-67, 374-375` | `thermClimbColor(rate)` + Legend-Array | Thermik-Zellen + Legenden-Swatches im Chat |

**Anker-Funktion = `regionPillSpec` in `briefing.js`** — liefert `{ label, hex, border, text, darkBg }` und wird von Touchpoints 4–7 direkt importiert. Touchpoints 1–3 + 8 haben eigene parallele Implementationen, die bei jeder Aenderung **identisch** angepasst werden muessen.

> ⚠ **KRITISCH — Thermik-Kacheln (Touchpoints 9 + 13):**
> Beide Renderer rendern Climb-Rate-Zellen mit `thermClimbColor(rate)`. Die 5 Schwellen (`<1.0`, `<1.5`, `<2.0`, `<2.5`, `>=2.5`) entsprechen 1:1 den Rating-Tiers 1-5 — d.h. **die Thermik-Kachel-Farben MUESSEN exakt mit den Rating-Tints uebereinstimmen**, sonst sieht eine Region in der Pille z.B. "Lime / Rating 3" und im Meteogramm gleichzeitig "Yellow / Rating 2" — visuelle Inkonsistenz, Vertrauen weg.
>
> **Diese werden oft vergessen**, weil sie in eigenen Files (`meteogram.js` + `chat-charts.js`) leben, nicht in der Anker-Funktion. Bei JEDER Palette-Aenderung beide Stellen mit Such-Pattern `grep -n "thermClimbColor" static/js/` checken.

**Touchpoints 10+11 (Wetterlage + Assessments)** sind **kategoriale Akzente** (nicht rating-driven). Sie nutzen feste Farben aus der Palette als Brand-Konsistenz (Stand v3.2):
- Wetterlage = Violet `#6d28d9` (Premium-Akzent, da wichtigster Info-Block)
- Assessment Safety = Rot `#ef4444` (Gefahr-Signal, unabhaengig von Rating)
- Assessment Flug = Lime `#BEF264` (Rating-3-Farbe — "Solider Thermiktag")
- Assessment Streckenflug = Violet `#a78bfa` (Rating-5-Premium — XC ist Premium-Achse)

---

## 4. Sync-Protokoll bei Palette-Aenderungen

Wenn eine Hex-Farbe oder eine Mapping-Regel (z.B. "Rating 5 → Cyan") geaendert wird, **MUESSEN alle 13 Touchpoints** im selben Commit aktualisiert werden:

**JS-Anchor-Files (Rating-driven):**
1. `region-map.js:getRatingTint` + `getRatingBorder` + `mapRegionStyle('violet')` + **`buildRegionLabel`** (Zahl-Pille im Polygon-Centroid mit per-Rating ring+ink)
2. `map.js:getRatingTint` + `mapSafetyBandToStyle('violet')` + Premium-Override + Text-Kontrast
3. `shared-glyph.js:ratingTintFor` + `styleFor('violet')` + Text-Kontrast-Logik
4. `briefing.js:regionPillSpec` (Anker — von 5+6+7 reused)
5. `rating-info.js:_ratingTint` + palette + Text-Kontrast
6. `meteogram.js:thermClimbColor` (Thermik-Kacheln im Meteogramm-Render)
7. `analysis-view.js:ratingTintSpec` + `buildGlyph` + `renderHero` (Spot/Region-Detail-Overlay)
8. `chat-charts.js:thermClimbColor` + Legend-Array (Thermik-Kacheln im KI-Chat)

**CSS-Akzent-Files (kategorial, nicht rating-driven):**
9. `briefing.css:.bf-wetterlage` Border-Left + Bg-Gradient + Icon-Farbe
10. `briefing.css:.bf-assessment--safety/fly/xc` Border-Left-Akzente

### Verifikations-Checklist (nach jedem Palette-Change abklicken)

Hard-Reload (Ctrl+Shift+R) auf jeder Route. Pro Punkt **eine konkrete Region oder Spot mit bekanntem Rating** waehlen und Farbe gegen Palette-Tabelle in §2 abgleichen.

| # | Route | Aktion | Was pruefen |
|---|-------|--------|-------------|
| 1 | `/` | Karte anschauen | Spot-Marker (alle Rating-Stufen pro safety-band) zeigen die korrekten Hex-Werte |
| 2 | `/` | Marker anklicken | Detail-Overlay: Hero-Container Bg + Border + Glyph-Kreis + Rating-Pill |
| 3 | `/regionen` | Karte anschauen | Region-Polygone (Fill + Border-Weight + Border-Color) UND Zahl-Pille im Polygon-Centroid (Ring + Ink) |
| 4 | `/regionen` | Polygon anklicken | Detail-Overlay analog zu #2 |
| 5 | `/briefing` | Oben anschauen | Wetterlage-Block hat Violet-Accent (Border-Left + Icon + Bg-Gradient) |
| 6 | `/briefing` | Region-Header anschauen | Region-Pill rechts vom Namen (alle Stufen) |
| 7 | `/briefing` | Spot-Zeile anschauen | Spot-Bg (subtil) + Spot-Score-Pill + Glyph-Kreis |
| 8 | `/briefing` | Spot aufklappen | Mini-Map-Marker korrekt eingefaerbt |
| **9** | `/briefing` | Spot aufklappen | **⚠ Meteogramm-Thermik-Kacheln: Hex-Werte pro climb_rate-Stufe gegen §2 Palette pruefen — oft vergessen!** |
| 10 | `/briefing` | Spot aufklappen | Assessment-Sektionen Border-Left: safety=rot, fly=Lime, xc=Violet |
| 11 | Karte | Info-Button (i) klicken | Rating-Info-Overlay zeigt korrekte Glyph-Beispiele fuer alle 5 Stufen |
| **12** | Chat (KI-Berater) | Thermal-Timeline-Chart triggern | **⚠ Chat-Charts Thermik-Kacheln + Legend-Swatches: Hex-Werte pruefen — separates File `chat-charts.js`, oft vergessen!** |
| 13 | `/briefing` mit Mobile-Viewport | Pill-Breite + Truncation pruefen | Pills passen, Name nicht abgeschnitten |

**Wenn nur eine Stelle vergessen wird**, sehen Nutzer dieselbe Region in zwei verschiedenen Farben → Vertrauen ist sofort weg.

---

## 5. Noch NICHT migriert (Stand 2026-05-17)

- Email-Briefing (`email_service.py`) — verwendet noch alte 3-Tier-Klassen (gray/green/violet). Bei naechster Palette-Migration mit anpassen.
- Streckenflug-Pille (falls separat gerendert) — Streckenflug ist eigene Achse, ggf. eigenes Konzept-Doku.
- Eventuell weitere Stellen die `--color-fly-*` CSS-Variablen lesen (Suche: `grep -rn "color-fly" static/css/`). Bei kompletter Migration auch CSS-Vars in `:root` aktualisieren.

---

## 6. Historie der Palette-Versionen

### v3.2 (Mai 2026) — Royal Premium final — AKTUELL

**Migration durchgefuehrt** am 2026-05-17.

**Motivation:** Premium-Tier-Hierarchie mit Violet-400 als Top + Green-500 fuer Rating 4 als saturiertes Safety-Green. Sky/Sky/Lime/Green-500/Violet ergibt klare visuelle Progression vom blauen Himmel ohne Thermik (1+2) ueber Lime (3) und Safety-Green (4) zum Legendary Violet (5).

**Versuch v4 (Complementary Twilight)** wurde nach Test verworfen — User: "vorhin wars besser" (v3.2 war besser als v4). v3.2 wiederhergestellt.

**Migriert:** 13 Touchpoints inkl. Meteogramm + Chat-Charts. Text-Kontrast-Logik in shared-glyph.js, map.js, rating-info.js, analysis-view.js: "green Rating 4 = weisser Text".

### v4 (Mai 2026) — Complementary Twilight — uebergangen
Violet-Pastell → Lime → Mint-Green → Cyan mit Komplementaer-Pop bei 2→3. Konzeptionell stark, aber User: "vorhin (v3.2) wars besser". Zurueckgerollt.

### v3.1 (Mai 2026) — Royal Premium refined (Teal-300) — uebergangen
Teal-300 fuer Rating 4 — User: "zu blau, mehr gruen". Verworfen.

### v3 (Mai 2026) — Royal Premium (Mint-Green + Cyan) — uebergangen

**Migration durchgefuehrt** am 2026-05-17.

**Motivation:** v2.x-Versuche (Pastell-Mint → Stone-Gray → Pink) fuer Rating 1+2 lieferten keinen befriedigenden visuellen Pop wie das urspruengliche Yellow-Grün. Pink wurde explizit verworfen. User-Entscheid: **Full-Redesign der gesamten Palette** mit "Royal Premium"-Konzept — Cool-Sky → Mint-Green → Cyan → Violet.

**Loesung:** Gaming-Tier-Hierarchie (Common → Rare → Epic → **Legendary**). Premium-Tier-Top wird wieder **Violet** (wie v1, aber jetzt komplett durchgezogen). Rating 1+2 = Sky-Blue ("blue thermal day" Pilot-Metapher = keine Cumulus = keine Thermik).

**Zusaetzlich:** Code-Identifier `violet` matched visuell wieder — semantische Inkonsistenz aus v2 aufgeloest. Wetterlage-Akzent + xc-Assessment-Akzent wechseln auf Violet (Premium-Konsistenz). fly-Assessment-Akzent wechselt auf Mint-Green (Rating-3-Farbe).

**Thermik-Kacheln** ebenfalls migriert: <1.0 → Sky-100, <1.5 → Sky-300, <2.0 → Mint-Green, <2.5 → Cyan, ≥2.5 → Violet.

### v2.2 (Mai 2026) — Pink — uebergangen
Versuch mit Pink-100/200 fuer Rating 1+2. Pop war OK aber User-Feedback: "Pink gefaellt mir nicht". Verworfen zugunsten v3.

### v2.1 (Mai 2026) — Stone-Gray — uebergangen
Stone-Gray fuer Rating 1+2 kollidierte semantisch mit `no_data` (auch grau). Verworfen.

### v2 (Mai 2026) — Pastell-Mint — uebergangen
Pastell-Mint fuer Rating 1+2 wirkte zu positiv ("kleines bisschen gruen"), nicht "kritisch schwach". Verworfen.

### v2 (Mai 2026) — Thermik-aligned / Option C — uebergangen

Erste Migration: Thermik-Kacheln und Rating-Palette angeglichen (Lime/Mint-Green/Cyan fuer Rating 3-5). Rating 1+2 in Pastell-Mint/Mint (Cool/Mint-Familie). Wurde durch v2.1 ersetzt, weil Pastell-Mint zu positiv wirkte und das "schwach/kritisch"-Signal verlor.

### v1 (vor Mai 2026) — Hue-Shift Green→Forest+Violet

Frueheres Konzept: green-Band lief von Lime (`#d9f99d`) ueber Bright-Green (`#84cc16`) zu Emerald (`#15803d`) und Forest-Dark (`#064e3b`), rating 5 = Violet (`#8b5cf6`). Hue-Shift quer durch verwandte Farben statt Lightness-Variation. Wurde durch v2 ersetzt fuer bessere Konsistenz mit Meteogramm.

---

## 7. Sync-Pflicht-Eintrag fuer MEMORY.md

Bei Aufnahme dieses Konzepts in `memory/MEMORY.md` folgenden Eintrag erstellen:

```
- [Rating-Farbkonzept — 8 Touchpoints synchron halten](rating_farbkonzept.md) — Aenderung an einer Stelle ohne die anderen = sofortige Inkonsistenz auf Karten/Pills/Bg. Source of Truth: docs/RATING_FARBKONZEPT.md
```
