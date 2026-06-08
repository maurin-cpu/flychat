# Wingcast MVP -- Feature-Definition (revidiert)

**Produkt:** Wingcast -- KI/LLM-Gleitschirm-Wetter-App
**Zielgruppe:** Gleitschirmpiloten
**Erstellt:** 2026-03-06
**Revidiert:** 2026-03-06 -- Abgleich mit Datenlage, Kostenrealität und Chat-Architektur (LlamaIndex)

---

## Technische Datenlage (Stand heute)

> **WICHTIG:** Diese Realität formt das gesamte MVP-Versprechen.

### Was wir haben (gut):
- **Open-Meteo-Daten:** Wind (Boden + Höhe), Temperatur, Niederschlag, Bewölkung, Luftdruck, Luftfeuchtigkeit -- professionelle Qualität, dieselben Datenquellen wie kommerzielle Apps
- **Wettermodelle via Open-Meteo:** ECMWF, GFS, ICON, u.a. -- zuverlässig und aktuell

### Was wir haben (limitiert):
- **Thermikprognose:** Eigenentwicklung, noch nicht ausgereift -- beeinflusst die Qualität der KI-Analyse bei thermikbezogenen Aussagen
- **Keine proprietären Thermikdaten:** Kein Zugang zu KK7 (Burnair), kein eigenes konvektionsauflösendes Modell (Meteo-Parapente)

### Was unsere Daten WIRKLICH gut können

| Frage | Zuverlässig beantwortbar? | Datenquelle |
|---|---|---|
| "Ist heute überhaupt fliegbar?" | **Ja** -- Wind, Regen, Gewitter filtern klar | Open-Meteo |
| "Ist Spot X gerade sicher?" | **Ja** -- Windstärke, Böen, Windrichtung vs. Hang | Open-Meteo |
| "Welche Spots fallen heute raus?" | **Ja** -- Zu viel Wind, falsche Richtung, Regen | Open-Meteo |
| "Wie ist die allgemeine Wetterlage?" | **Ja** -- Druckverteilung, Fronten, Strömung | Open-Meteo + LLM |
| "Was für ein Spread herrscht?" | **Ja** -- Temperaturprofil als Thermik-Indikator | Open-Meteo |
| "Brauneck oder Wallberg -- wo ist der Wind besser?" | **Ja** -- Wind pro Spot vergleichbar | Open-Meteo |
| "Welcher Spot hat das BESTE Thermik-Potenzial?" | **Nein** -- Eigenentwicklung zu ungenau | Limitiert |
| "Wie hoch wird die Basis?" | **Nein** -- Braucht konvektionsauflösendes Modell | Limitiert |
| "Um wie viel Uhr löst die Thermik aus?" | **Nein** -- Zu komplex ohne gute Daten | Limitiert |

### Konsequenz für das MVP:

**Wir können zuverlässig AUSSCHLIESSEN (negativ filtern), aber nicht zuverlässig mit numerischer Präzision RANKEN.**

Ein Spot-Ranking mit Scores (88/100 vs. 74/100) suggeriert eine Differenzierungsfähigkeit, die wir bei Thermik nicht haben. Zwei Spots mit identischem Wind/Regen/Wolken hätten identische Scores -- aber in der Realität komplett unterschiedliches Flugpotenzial. Ein erfahrener Pilot erkennt das sofort und verliert das Vertrauen.

**Deshalb: Chat statt Ranking. Qualitative Beratung statt falsche Präzision.**

---

## MVP-Architektur: Chat + LlamaIndex

### Warum Chat statt Ranking-Dashboard

| Kriterium | Ranking-Screen | Chat + LlamaIndex |
|---|---|---|
| **Passt zur Datenlage** | Nein -- Scores brauchen Thermik für ehrliche Differenzierung | **Ja** -- Chat antwortet nuanciert: "Wind passt, Thermik unsicher" |
| **Passt zu Pain #1 (FOMO)** | Ja, wenn Score stimmt | **Ja** -- "Heute sieht es gut aus, 3 Spots haben passenden Wind" |
| **Passt zu Pain #2 (Info-Overload)** | Ja | **Ja** -- 1 Frage statt 7 Webseiten |
| **Passt zu Pain #3 (Expertise-Lücke)** | Schwach -- Score erklärt wenig | **Stark** -- natürliche Sprache, Rückfragen möglich |
| **Passt zum USP (natürliche Sprache)** | Schwach -- generierte Textbausteine | **Stark** -- echte LLM-Konversation |
| **Kosten** | Batch-Job teuer oder Templates ohne KI-Gefühl | **Günstig** -- nur pay per query |
| **Ehrlichkeit bei Grenzen** | Score von 88 suggeriert Präzision die wir nicht haben | **Natürlich** -- "Wind passt, bei Thermik bin ich unsicher" |
| **Flexibilität** | Zeigt nur was wir vorprogrammiert haben | **Unbegrenzt** -- jede Frage möglich |

### So funktioniert die Architektur

```
┌─────────────────────────────────────────────────────┐
│  DATEN-LAYER (läuft im Hintergrund, kein LLM)       │
│                                                      │
│  Open-Meteo API ──→ Wetterdaten holen (alle 6h)     │
│  für alle Spots     Wind, Temp, Regen, Wolken, Böen  │
│                         ↓                            │
│                  LlamaIndex Vektor-Store              │
│                  ┌──────────────────────┐            │
│                  │ Brauneck:            │            │
│                  │  Exposition: SW      │            │
│                  │  Starthöhe: 1500m    │            │
│                  │  Wind: SW 14 km/h    │            │
│                  │  Böen: 20 km/h       │            │
│                  │  Regen: 5%           │            │
│                  │  Wolken: 20%         │            │
│                  │  Spread: 8°C         │            │
│                  ├──────────────────────┤            │
│                  │ Wallberg: ...        │            │
│                  ├──────────────────────┤            │
│                  │ Blomberg: ...        │            │
│                  └──────────────────────┘            │
│                                                      │
│  Kosten: 0 EUR (Open-Meteo = gratis)                 │
└──────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────┐
│  CHAT-LAYER (nur wenn Pilot fragt)                    │
│                                                      │
│  Pilot stellt Frage                                  │
│       ↓                                              │
│  LlamaIndex: Retrieval der relevanten Spot-Daten     │
│       ↓                                              │
│  System Prompt + Spot-Daten → LLM                    │
│       ↓                                              │
│  Natürlichsprachliche Antwort an Pilot               │
│                                                      │
│  Kosten: ~$0.002-0.01 pro Frage                     │
└──────────────────────────────────────────────────────┘
```

### Kostenrechnung

| Szenario | Fragen/Tag | Kosten/Monat |
|---|---|---|
| **10 Beta-Tester** (je 2 Fragen an Flugtagen) | ~8-10 | **~$1-3** |
| **100 Nutzer** | ~80-100 | **~$5-30** |
| **500 Nutzer** | ~400-500 | **~$25-150** |

---

## Das Kern-Feature: Chat-basierter Flugwetter-Berater

### Was der Chat KANN (starke Daten)

**Allgemeine Wetterlage erklären:**
```
Pilot: "Wie wird's heute?"
Wingcast: "Schwache Südwestlage über den Nordalpen. Trocken
bis 16 Uhr, dann einzelne Schauer im Inntal möglich.
Wind in Gipfelhöhe 12-18 km/h aus SW. Bewölkung nimmt
ab Mittag leicht zu. Grundsätzlich ein fliegbarer Tag."
```

**Spots vergleichen (Wind, Sicherheit):**
```
Pilot: "Brauneck oder Wallberg?"
Wingcast: "Windtechnisch sind beide gut -- SW passt zu
beiden Hangexpositionen. Am Wallberg werden Böen bis
25 km/h ab 14 Uhr vorhergesagt, am Brauneck bleibt
es ruhiger (Böen max 20 km/h). Wenn du den ganzen Tag
fliegen willst, ist Brauneck die sicherere Wahl."
```

**Spots negativ filtern:**
```
Pilot: "Wo kann ich heute fliegen?"
Wingcast: "Von deinen 12 Spots fallen heute 5 raus:
Hochries und Kampenwand haben Nordwind (falsche Richtung),
Spitzingsee hat Regen ab Mittag, Tegernsee-Ost und
Hirschberg haben Böen über 30 km/h. Die restlichen 7
haben passenden Wind und sind trocken."
```

**Sicherheitshinweise:**
```
Pilot: "Ist der Wind am Wallberg sicher für einen B-Schirm?"
Wingcast: "Aktuell 16 km/h mit Böen bis 20 -- das ist OK
für B-Schirme. Ab 14 Uhr steigen die Böen auf bis zu
25 km/h -- dann wird's grenzwertig. Ich würde vormittags
starten und den Wind im Auge behalten."
```

**Morgen/Übermorgen einschätzen:**
```
Pilot: "Wird morgen besser als heute?"
Wingcast: "Morgen dreht der Wind auf West und wird stärker
(20-25 km/h). Weniger Spots haben passende Exposition.
Heute ist der bessere Tag -- wenn du kannst, nutze ihn."
```

### Was der Chat EHRLICH SAGT (schwache Daten)

**Thermik:**
```
Pilot: "Wie wird die Thermik heute?"
Wingcast: "Der Spread liegt bei 8°C, das deutet auf
moderate Thermik-Potenziale hin -- aber das ist eine
grobe Einschätzung. Für eine zuverlässige Thermik-
Prognose empfehle ich, zusätzlich Meteo-Parapente
zu checken -- die haben das beste Modell dafür."
```

**Basishöhe:**
```
Pilot: "Wie hoch wird die Basis?"
Wingcast: "Basierend auf der Luftfeuchtigkeit schätze ich
die Kondensationshöhe auf ca. 2.200-2.500m -- aber das
ist eine Berechnung, keine Messung. Die tatsächliche
Basis hängt stark von der Thermik-Entwicklung ab."
```

**XC-Potenzial:**
```
Pilot: "Ist heute ein XC-Tag?"
Wingcast: "Wind und Wetter passen grundsätzlich -- wenig
Regen, moderate Windstärke, überwiegend sonnig. Ob es
für XC reicht, hängt von der Thermik ab, und da bin ich
noch nicht zuverlässig genug. Der Spread sieht aber
vielversprechend aus."
```

### Warum die Ehrlichkeit funktioniert

1. **Piloten wissen selbst**, dass Thermik schwer vorhersagbar ist. Eine KI die das zugibt, ist glaubwürdiger als eine die so tut als wüsste sie alles.
2. **Pratfall Effect:** Eine kleine Schwäche eingestehen ("Thermik kann ich nicht sicher") macht die Stärken glaubwürdiger ("Wind und Sicherheit kann ich zuverlässig").
3. **Komplementäre Positionierung:** "Check Meteo-Parapente für Thermik" ist kein Versagen -- es ist Beratung auf Augenhöhe. Piloten vertrauen einem Berater, der auch sagt "das frag besser jemand anderen".
4. **Strategischer Vorteil:** Wenn die Thermikdaten besser werden (V2/V3), wird der Chat automatisch besser -- ohne Architekturänderung. Die Ehrlichkeit heute wird zur sichtbaren Verbesserung morgen.

---

## Onboarding (einmalig)

**Was es tut:**
- Pilot gibt seine Heimatregion an (z.B. "Bayerische Voralpen")
- System kennt die Startplätze mit Koordinaten und Hangexposition
- Optional: Pilot markiert Favoriten

**MVP-Scope:**
- 1 Region zum Start (z.B. Bayerische Voralpen)
- 10-15 vorkonfigurierte Startplätze
- Beim Telegram Bot: `/start` → Region wählen → fertig

---

## Plattform-Entscheidung

### Prototyp (Woche 1-2): Telegram Bot

**Warum Telegram:**
- Kein Frontend nötig, kein Hosting, kein App Store
- Piloten können den Bot in bestehende Gleitschirm-Gruppen einladen
- Viraler Effekt: Andere in der Gruppe sehen die Antworten
- Kommandos einfach: `/heute`, `/vergleich Brauneck Wallberg`, oder Freitext
- Schnellste Validierung möglich

**Beispiel-Interaktion:**
```
Pilot:  /heute
Wingcast: Bayerische Voralpen, 6. März 2026:

Schwache SW-Lage, trocken bis 16 Uhr. Wind in
Gipfelhöhe 12-18 km/h. 7 von 12 Spots haben
passenden Wind. Ausgeschlossen: Hochries (Nordwind),
Kampenwand (Nordwind), Spitzingsee (Regen ab 12h),
Tegernsee-Ost (Böen 32 km/h), Hirschberg (Böen 30 km/h).

Willst du zwei Spots vergleichen?

Pilot:  Brauneck oder Blomberg?
Wingcast: Brauneck ist heute die bessere Wahl:
- Wind SW 14 km/h (passt perfekt zur Exposition)
- Böen max 20 km/h (sicher)
- Bewölkung 20% bis 15 Uhr

Blomberg hat ähnlichen Wind, aber zunehmende
Bewölkung ab Mittag (50%+), was Sonneneinstrahlung
und damit Flugpotenzial reduziert.

Thermik-Einschätzung: Spread bei 8°C deutet auf
moderate Thermik hin -- das ist aber eine Schätzung.
```

### MVP (Woche 3-4): Simple Web-Chat

- Responsive Web App mit Chat-Interface
- Selbe Backend-Logik wie Telegram Bot
- Teilbar per Link (kein App-Download nötig)
- Telegram Bot läuft parallel weiter

---

## RADIKAL GESTRICHEN: Was NICHT im MVP ist

| Feature | Warum gestrichen | Wann kommt es? |
|---|---|---|
| **Numerischer Spot-Score (0-100)** | Suggeriert Präzision die wir bei Thermik nicht haben. Qualitative Beratung ist ehrlicher und vertrauenswürdiger. | V2 -- wenn Thermikdaten besser werden, kann ein Score sinnvoll werden |
| **Ranking-Dashboard** | Erfordert zuverlässige Differenzierung zwischen Spots. Chat ist flexibler und ehrlicher bei Datenlücken. | V2 -- als optionale Übersicht zusätzlich zum Chat |
| **Morning Briefing (vorgeneriert)** | Chat beantwortet dieselbe Frage on-demand. Kein Batch-Processing nötig. | V2 -- als Push-Notification "Morgen wird ein guter Tag" |
| **Push-Alerts** | Erfordert Backend-Scheduling. MVP funktioniert on-demand. | V2 |
| **Pilot-Profil (Level, Schirm)** | Nice-to-have. Chat kann trotzdem fragen "Was fliegst du für einen Schirm?" | V2 |
| **Flughistorie** | Null Impact auf Kern-Entscheidung "Wo fliege ich heute?" | V3 |
| **Social Sharing** | Braucht kritische Masse. Telegram-Gruppen sind besserer viraler Kanal. | V3 |
| **Multi-Region** | Qualität vor Quantität. 1 Region perfekt. | V2 -- Region für Region |
| **XC-Routenvorschläge** | Erfordert zuverlässige Thermikdaten die wir nicht haben. | V3 |
| **Präzise Thermik-Aussagen** | Eigenentwicklung zu ungenau. Lieber ehrlich als falsch. | V2/V3 -- wenn Daten besser werden |
| **Ampel-System / Confidence Score** | Im Chat ersetzt durch natürliche Ehrlichkeit ("das ist eine Schätzung"). Kein extra UI-Element nötig. | V2 -- für Ranking-View |

---

## MVP auf einen Blick

```
┌─────────────────────────────────────────────────────┐
│          WINGCAST MVP (revidiert)                      │
│          "ChatGPT für Flugwetter"                    │
│                                                     │
│  Kern-Feature:                                      │
│  └── Chat-basierter Flugwetter-Berater              │
│      ├── Allgemeine Wetterlage erklären             │
│      ├── Wind-Check pro Spot (sicher/unsicher)      │
│      ├── Spots mit schlechten Bedingungen filtern   │
│      ├── Zwei Spots vergleichen (Wind, Wetter)      │
│      ├── Sicherheitshinweise geben                  │
│      ├── Wetter für morgen einschätzen              │
│      └── Ehrlich bei Thermik-Grenzen sein           │
│                                                     │
│  Onboarding:                                        │
│  └── Region wählen (1 Region, 10-15 Spots)          │
│                                                     │
│  Plattform:                                         │
│  ├── Prototyp: Telegram Bot (Woche 1-2)             │
│  └── MVP: Web-Chat (Woche 3-4)                     │
│                                                     │
│  Daten: Open-Meteo (ECMWF, ICON, GFS)              │
│  Backend: LlamaIndex + LLM (pay per query)          │
│  Kosten: ~$1-5/Monat bei 10-50 Testern             │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## Warum dieser MVP perfekt vermarktbar ist

### 1. Ein-Satz-Pitch
> **"Frag Wingcast, wo du heute fliegen sollst -- in natürlicher Sprache, ehrlich und in 30 Sekunden."**

### 2. Headline-Formulas

| Framework | Headline |
|---|---|
| **Outcome without Pain** | "Versteh das Flugwetter -- ohne 7 Webseiten zu checken" |
| **Never [pain] again** | "Fahr nie wieder zum falschen Startplatz" |
| **The [adj] [category] for [audience]** | "Der smarteste Flugwetter-Berater für Gleitschirmpiloten" |
| **Finally, [category] that [benefit]** | "Endlich eine Wetter-App, die dir antwortet statt Daten zu zeigen" |
| **Question highlighting pain** | "Keine Lust mehr, morgens 7 Webseiten zu checken?" |
| **[Feature] for [audience] to [outcome]** | "Ein KI-Berater für Gleitschirmpiloten, um in 30 Sekunden zu entscheiden" |

### 3. "How It Works" für Landing Page
1. **Frag Wingcast** -- "Wo soll ich heute fliegen?" oder jede andere Flugwetter-Frage
2. **Bekomm eine ehrliche Antwort** -- Basierend auf aktuellen Wetterdaten, in natürlicher Sprache
3. **Entscheide und fahr los** -- In 30 Sekunden statt 45 Minuten

### 4. Pre-Launch Marketing-Ideen

| Marketing-Idea | Anwendung auf Wingcast MVP |
|---|---|
| **#15 Engineering as Marketing** | Telegram Bot als dauerhaft kostenloses Tool in Piloten-Gruppen |
| **#79 Early-Access Referrals** | "Lad den Bot in deine Fluggruppe ein" = viraler Verbreitungsweg |
| **#6 Proprietary Data Content** | Wöchentliches "Flugwetter-Briefing" per E-Mail an Warteliste |
| **#93 Viral Loop** | Bot antwortet in Telegram-Gruppen = alle sehen die Qualität |
| **#38 Reddit Marketing** | Authentisch in r/paragliding + DHV-Forum posten |
| **#35 Community Marketing** | Bot direkt in Gleitschirm-Telegram/WhatsApp-Gruppen einladen |
| **#139 Customer Language** | "Wo fliegst du heute?" statt "KI-gestützte meteorologische Analyse" |

### 5. Vermarktbare Differenzierung (vs. Wettbewerb)

```
Was andere zeigen:          Was Wingcast macht:
─────────────────           ──────────────────
Windgramm                → "SW 15 km/h, passt zum Brauneck"
Thermik-Karte            → "Spread bei 8°C, Thermik möglich
                            aber unsicher -- check auch
                            Meteo-Parapente"
Flyability: 78%          → "7 von 12 Spots haben heute
  (ohne Erklärung)          passenden Wind, 5 fallen raus"
5 Wetter-Layer           → Eine Frage, eine Antwort
7 verschiedene Apps      → 1 Chat, 30 Sekunden
Daten ohne Kontext       → "Böen bis 25 km/h -- grenzwertig
                            für B-Schirme ab 14 Uhr"
```

---

## Zusammenfassung: Der revidierte MVP

1. **Chat statt Dashboard** -- Qualitative Beratung statt numerische Scores mit falscher Präzision
2. **Ehrlich bei Grenzen** -- "Wind kann ich, Thermik ist eine Schätzung" schafft mehr Vertrauen als eine Black-Box
3. **LlamaIndex + LLM** -- Pay per Query, kostet $1-5/Monat bei Prototyp-Nutzerzahl
4. **Telegram Bot zuerst** -- Schnellste Validierung, viraler Effekt in Piloten-Gruppen, kein Frontend nötig
5. **10-15 Spots, 1 Region** -- Klein starten, Qualität validieren, dann skalieren

> **Der MVP ist kein Score-Generator. Er ist ein ehrlicher Berater, der sagt was er weiß -- und zugibt was er nicht weiß.**

---

## Feature-Roadmap: MVP → V2 → V3

```
MVP (Prototyp) -- "Ehrlicher Flugwetter-Berater"
├── Chat via Telegram Bot → Web-Chat
├── LlamaIndex + LLM (Open-Meteo-Daten)
├── 1 Region, 10-15 Spots
├── Stärke: Wind, Regen, Wolken, Böen, Sicherheit
├── Schwäche (ehrlich kommuniziert): Thermik
└── Kosten: $1-5/Monat

V2 (Post-Validierung, ~3 Monate) -- "Wird schlauer"
├── Thermikdaten verbessern (besseres Modell oder externe Daten)
├── Spot-Ranking als optionale Übersicht (erst wenn Daten es hergeben)
├── Push-Alerts ("Morgen wird ein guter Tag")
├── Pilot-Profil (Level, Schirm-Klasse für kontextuelle Antworten)
├── +2-3 weitere Regionen
└── Web-App mit Chat + optionalem Dashboard

V3 (Wachstum, ~6-9 Monate) -- "Voller KI-Co-Pilot"
├── Professionelle Thermikdaten (KK7, eigenes Modell, o.ä.)
├── Zuverlässiges numerisches Ranking (erst jetzt sinnvoll)
├── XC-Potenzial & Routenvorschläge
├── Social Features ("Heute am Brauneck, wer kommt?")
├── Flughistorie (lernender Algorithmus)
├── Multi-Region (Alpen, Pyrenäen, Dolomiten...)
└── Native App (iOS/Android)
```

### Thermik-Strategie: Von "geschätzt" zu "zuverlässig"

| Phase | Thermik-Status | Im Produkt | Marketing |
|---|---|---|---|
| **MVP** | Eigenentwicklung, limitiert | "Spread deutet auf X hin, aber unsicher" | Ehrlichkeit als Trust-Builder |
| **V2** | Verbessertes Modell oder externe Daten | Genauere Aussagen, weniger Disclaimer | "Jetzt mit besserer Thermik-Analyse" |
| **V3** | Professionelle Daten (KK7 o.ä.) | Volle Integration, numerische Scores möglich | "Vollständige XC-Analyse" |

**Strategische Optionen für bessere Thermikdaten:**
1. Eigenes Modell iterativ verbessern (Feedback-Loop mit Piloten)
2. Zugang zu KK7-Daten verhandeln (Lizenz)
3. Open-Source-Thermik-Modelle evaluieren
4. Community-Daten: Piloten melden reale Thermik-Bedingungen zurück → Trainingsdaten

---

## Nächste Schritte

| Schritt | Was | Zeitrahmen |
|---|---|---|
| 1 | Spot-Datenbank erstellen (10-15 Spots: Koordinaten, Exposition, Starthöhe) | 1-2 Tage |
| 2 | Open-Meteo API anbinden + LlamaIndex-Pipeline bauen | 2-3 Tage |
| 3 | System Prompt entwickeln (Flugwetter-Experte, ehrlich bei Grenzen) | 1 Tag |
| 4 | Telegram Bot aufsetzen | 1-2 Tage |
| 5 | Mit 5-10 Piloten testen: Stimmen die Antworten? Was fehlt? | 1-2 Wochen |
| 6 | Learnings auswerten → V2 priorisieren | Nach Test-Phase |
