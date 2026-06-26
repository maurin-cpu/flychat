# Wingcast -- Produktkonzept & Core Offer

**Produkt:** Wingcast -- KI/LLM-Gleitschirm-Wetter-App zur Gebietsfindung und Flugplanung
**Zielgruppe:** Gleitschirmpiloten
**Erstellt:** 2026-03-06
**Methodik:** Copywriting-Frameworks, Launch-Strategy, Pricing-Strategy + bisherige Pain-Point- & Wettbewerbsanalyse

---

## Die Produktvision in einem Satz

> **Wingcast ist der KI-Co-Pilot, der Gleitschirmpiloten in 30 Sekunden sagt, wo sie heute fliegen sollen -- und erklärt warum.**

---

## Das Problem (aus Pilotensicht)

*"Es ist Samstagmorgen, 6:30 Uhr. Ich weiß, dass heute ein guter Flugtag sein könnte. Ich öffne Windy, Meteo-Parapente, Burnair, checke zwei Webcams, schaue ins Windgramm, vergleiche drei Gebiete... 45 Minuten später bin ich unsicherer als vorher. Mein Kumpel ruft an: 'Wo fahren wir hin?' Ich sage: 'Keine Ahnung.' Er fährt ohne mich."*

**Das ist der Moment, den Wingcast eliminiert.**

---

## Die 3 MVP-Kern-Features

### Feature 1: "Morning Briefing" -- Dein persönliches Flugwetter in Textform
**Das Feature, das alles verändert.**

**Was es tut:**
Jeden Morgen (oder on-demand) liefert Wingcast eine natürlichsprachliche Zusammenfassung der Flugbedingungen -- zugeschnitten auf den Standort, das Können und die Präferenzen des Piloten.

**Beispiel-Output:**
> *"Heute ist ein guter XC-Tag in den Nordalpen. Schwache Südwestlage, trockene Luft, Thermikauslöse ab ca. 11:30 Uhr. Basis steigt bis 15 Uhr auf ~2.400m. Vorsicht: Ab 16 Uhr Überentwicklung im Inntal möglich. Windgeschwindigkeit in Gipfelhöhe 15-20 km/h SW -- akzeptabel für B-Schirme und höher."*

**Warum kein Wettbewerber das hat:**
- Windy zeigt Karten -- keine Texte
- Meteo-Parapente zeigt Windgramme -- keine Interpretation
- Paraglidable zeigt einen Score -- keine Erklärung
- Burnair zeigt Thermikzonen -- kein persönliches Briefing

**Psychologischer Hebel:**
- Senkt die Aktivierungsenergie massiv (kein Lesen von 7 Webseiten)
- Adressiert die Expertise-Lücke (auch Anfänger verstehen natürliche Sprache)
- Reduziert Entscheidungsparalyse (Paradox of Choice)

**Jobs to Be Done:**
> *"Hilf mir zu verstehen, ob heute ein guter Tag zum Fliegen ist -- ohne dass ich Meteorologe sein muss."*

---

### Feature 2: "Spot Ranking" -- Automatisches Gebiets-Ranking
**Das Feature, das die FOMO tötet.**

**Was es tut:**
Wingcast vergleicht alle relevanten Fluggebiete im Umkreis und rankt sie nach Flugqualität -- mit einer klaren Nr. 1-Empfehlung und transparenter Begründung.

**Beispiel-Output:**
> *1. Brauneck (92/100) -- "Beste Hangexposition für die heutige SW-Lage. Talwind unterstützt Thermik ab Mittag. 3 von 4 Modellen stimmen überein."*
>
> *2. Wallberg (78/100) -- "Gut, aber Lee-Gefahr ab 14 Uhr bei zunehmendem Wind. Nur für erfahrene Piloten."*
>
> *3. Tegernsee-Ost (65/100) -- "Abschattung durch Bewölkung am Nachmittag. Eher kurze Flüge möglich."*

**Warum kein Wettbewerber das hat:**
- Burnair zeigt Thermikdaten pro Gebiet -- vergleicht aber nicht ZWISCHEN Gebieten
- Paraglidable zeigt Flyability pro Region -- nicht pro Startplatz
- Windy/Meteo-Parapente haben kein Ranking-Konzept

**Psychologischer Hebel:**
- Loss Aversion: "Verpasse nie wieder das beste Gebiet"
- Opportunity Cost: Eliminiert die Fahrt zum falschen Berg
- Scarcity: An einem guten Tag das BESTE Gebiet erwischen

**Jobs to Be Done:**
> *"Sag mir einfach, wo ich heute hinfahren soll."*

---

### Feature 3: "Confidence Score" -- Transparente KI-Vertrauensbewertung
**Das Feature, das Vertrauen aufbaut.**

**Was es tut:**
Jede Empfehlung kommt mit einem Konfidenz-Level und einer Erklärung, worauf die Einschätzung basiert. Der Pilot sieht nicht nur WAS die KI empfiehlt, sondern WIE sicher sie sich ist und WARUM.

**Beispiel-Output:**
> *Konfidenz: 85% (hoch)*
> *"3 von 4 Wettermodellen (ECMWF, ICON, AROME) stimmen bei Wind und Thermik überein. GFS weicht bei der Wolkenprognose ab. Die Modellübereinstimmung ist heute ungewöhnlich hoch."*
>
> *Konfidenz: 55% (unsicher)*
> *"Die Modelle divergieren stark bei der Föhn-Prognose. ECMWF sagt Föhndurchbruch ab 13 Uhr, ICON nicht. Empfehlung: Morgens fliegen, früh am Landeplatz sein."*

**Warum kein Wettbewerber das hat:**
- Paraglidable: Score ohne Erklärung (Black Box)
- Alle anderen: Keine aggregierte Modell-Bewertung
- Kein Tool sagt "Heute bin ich mir unsicher"

**Psychologischer Hebel:**
- Regret Aversion: Piloten trauen einer KI mehr, die ihre Unsicherheit kommuniziert
- Authority Bias: Referenz auf bekannte Modelle (ECMWF, GFS) schafft Glaubwürdigkeit
- Sicherheitsbedürfnis: Das wichtigste emotionale Bedürfnis nach FOMO

**Jobs to Be Done:**
> *"Gib mir nicht nur eine Empfehlung -- gib mir genug Info, damit ich mich sicher fühle, ihr zu folgen."*

---

## Feature-Übersicht: MVP vs. Zukunft

```
┌──────────────────────────────────────────────────────────────┐
│                    MVP (Launch)                               │
│                                                              │
│  1. Morning Briefing    -- Text-Zusammenfassung              │
│  2. Spot Ranking        -- Gebiets-Vergleich & Empfehlung    │
│  3. Confidence Score    -- Transparenz & Vertrauen           │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│                    V2 (Post-Launch)                           │
│                                                              │
│  4. Chat-Interface      -- "Wie wird's am Brauneck um 14h?" │
│  5. Push-Alerts         -- "Morgen wird ein 90+ Tag!"        │
│  6. Pilot-Profil        -- Schirm, Level, Heimatgebiet       │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│                    V3 (Wachstum)                              │
│                                                              │
│  7. Flughistorie        -- Lernender Algorithmus             │
│  8. Social Sharing      -- "Heute am Brauneck, wer kommt?"  │
│  9. Multi-Region        -- Alpen, Pyrenäen, Dolomiten...     │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## Die Produkt-Erfahrung (User Flow MVP)

```
Schritt 1: Öffne die App
           ↓
Schritt 2: Sieh dein Morning Briefing
           "Heute guter XC-Tag, Basis bis 2.400m, SW 15 km/h"
           ↓
Schritt 3: Sieh das Spot Ranking
           "#1 Brauneck (92/100) -- beste Wahl für heute"
           ↓
Schritt 4: Lies den Confidence Score
           "85% sicher -- 3/4 Modelle stimmen überein"
           ↓
Schritt 5: Entscheide & fahre los
           (30 Sekunden statt 45 Minuten)
```

**How It Works (für Landing Page):**
1. **Öffne Wingcast** -- Dein persönliches Briefing wartet bereits
2. **Sieh, wo es heute am besten ist** -- KI rankt alle Gebiete für dich
3. **Vertrau der Empfehlung** -- Transparente Begründung und Konfidenz-Level

---

## Offer-Stack: Warum es ein No-Brainer ist

### Der Wert-Vergleich (Mental Accounting)

| Was Piloten heute investieren | Was Wingcast spart |
|---|---|
| 45 Min. Wetteranalyse pro Flugtag | **30 Sekunden** |
| 7 verschiedene Webseiten/Apps | **1 App** |
| 1-3h Fahrt zum falschen Gebiet (~30 EUR Sprit) | **Immer das richtige Gebiet** |
| 5-10 verpasste Flugtage pro Saison (FOMO) | **Keinen Tag verpassen** |
| EUR 129 Burnair + EUR 36 Meteo-Parapente + EUR 25 Windy = **EUR 190/Jahr** | **Eine App statt drei** |

### Framing (weniger als ein Kaffee)

> *"Weniger als ein Latte pro Monat -- oder der Sprit für eine Fahrt zum falschen Startplatz."*

### Risiko-Umkehr

- **14 Tage kostenlos testen** -- Voller Zugang, keine Kreditkarte
- **Keine Bindung** -- Monatlich kündbar
- **Geld-zurück-Garantie** -- "Wenn Wingcast dir nicht mindestens einen besseren Flugtag bringt, bekommst du dein Geld zurück."

---

## Vorgeschlagene Tier-Struktur (Good-Better-Best)

```
┌────────────────┬──────────────────┬──────────────────┬──────────────────┐
│                │ Free             │ Pilot            │ XC Pro           │
│                │ EUR 0            │ EUR 4,99/Monat   │ EUR 9,99/Monat   │
├────────────────┼──────────────────┼──────────────────┼──────────────────┤
│ Morning        │ 1x pro Tag       │ Unlimitiert      │ Unlimitiert      │
│ Briefing       │ (Basis-Region)   │ (alle Regionen)  │ + Chat-Interface │
├────────────────┼──────────────────┼──────────────────┼──────────────────┤
│ Spot Ranking   │ Top 3 Gebiete    │ Alle Gebiete     │ Alle Gebiete     │
│                │                  │ im Umkreis       │ + Routenvorschlag│
├────────────────┼──────────────────┼──────────────────┼──────────────────┤
│ Confidence     │ Einfach          │ Detailliert mit  │ Detailliert +    │
│ Score          │ (Hoch/Mittel/    │ Modell-Breakdown │ historischer     │
│                │  Niedrig)        │                  │ Trefferquote     │
├────────────────┼──────────────────┼──────────────────┼──────────────────┤
│ Push-Alerts    │ --               │ "Morgen wird gut"│ Personalisiert   │
├────────────────┼──────────────────┼──────────────────┼──────────────────┤
│ Vorhersage-    │ Heute            │ 3 Tage           │ 7 Tage           │
│ horizont       │                  │                  │                  │
└────────────────┴──────────────────┴──────────────────┴──────────────────┘
```

**Warum Free Tier wichtig ist:**
- Endowment Effect: Piloten "besitzen" die App und wollen nicht mehr zurück
- Foot-in-the-Door: Kleines Commitment (Download) führt zu größerem (Abo)
- Network Effects: Mehr Nutzer = mehr Daten = bessere KI

---

## Waitlist-Strategie

### Headline für Landing Page:

> **Verpasse nie wieder den besten Flugtag.**
> *Wingcast sagt dir in 30 Sekunden, wo du heute fliegen sollst -- mit KI-gestützter Wetteranalyse.*

### Waitlist-Mechanik (Scarcity + Mimetic Desire):

1. **"Trag dich ein -- die ersten 500 Piloten fliegen kostenlos."** (Scarcity)
2. **Fortschrittsanzeige:** "387/500 Plätze vergeben" (Goal-Gradient + Urgency)
3. **Priority Queue:** "Teile Wingcast mit einem Fliegerkollegen und springe 50 Plätze nach vorne" (Referral + Bandwagon)
4. **Preview-Content:** Wöchentliches "KI-Flugwetter-Briefing" per E-Mail an die Warteliste (Reciprocity + Mere Exposure)

### Waitlist-CTA:

> **[Platz sichern -- kostenloser Early Access]**
> *Kein Spam. Nur eine Nachricht, wenn Wingcast startet.*

---

## Zusammenfassung: Warum Piloten sich sofort eintragen

| Psychologischer Trigger | Wie Wingcast ihn nutzt |
|---|---|
| **Loss Aversion** | "Verpasse nie wieder den besten Flugtag" |
| **Scarcity** | "Erste 500 Piloten kostenlos" |
| **Activation Energy** | "30 Sekunden statt 45 Minuten" |
| **Social Proof** | "387 Piloten auf der Warteliste" |
| **Reciprocity** | Kostenloses Weekly Briefing vor Launch |
| **FOMO** | "Andere Piloten nutzen es schon" |
| **Endowment Effect** | Free Tier lässt sie "besitzen" |
| **Authority** | "Basiert auf ECMWF, GFS, ICON, AROME" |
