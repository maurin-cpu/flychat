# validation/foehn — Befunde (kuratiert)

Stand 27.09.2026 · Backtest 2024-01-01 – 2026-09-26 (1000 Tage, Flugfenster
06–18 Uhr lokal), Prüfling = Produktivlogik `evaluate_foehn`, Wahrheit =
MeteoSchweiz-Föhnindex an 16 Stationen. Zahlen aus `AUTO_REPORT.md`.

## P-1 · Die Warnung sieht praktisch jeden Föhn in den grossen Nordföhntälern

Altdorf 94 %, Vaduz 93 %, Engelberg 95 %, Glarus 99.5 %, Meiringen 93 % der
Föhnstunden am Talboden fallen in eine Warnstunde (caution oder danger).
Tagesebene: 90–98 % der Föhntage sind Warntage. Verpasste Stunden liegen
ausnahmslos bei Δp < 4 hPa. **Für Reuss, Rheintal, Glarus, Haslital ist die
nationale Druckdifferenz als Detektor ausreichend.**

## P-2 · … aber sie warnt viel zu oft: 60–85 % der Warnstunden ohne Föhn am Boden

Fehlalarmrate (Anteil der Warnstunden ohne Föhn am Boden): Altdorf 60 %,
Vaduz 61 %, Meiringen 76 %, Engelberg 79 %, Glarus 84 %, Sion 89 %.
Südföhn-Warnung an 189 von 1000 Tagen — Altdorf hat an 87 Tagen Föhn.
Kein Δp-Schwellenwert löst das: bei ≥ 5 hPa sinkt Altdorf auf 82 % Treffer
bei immer noch 46 % Fehlalarm, bei ≥ 8 hPa auf 44 % Treffer.
Vorbehalt: „ohne Föhn am Boden" ≠ „ohne Föhn" — ein Teil dieser Stunden ist
Föhn über dem Kaltluftsee, der am Startplatz durchaus weht (README, Grenze 1).
Aber: in 62 % der Altdorfer Fehlalarmstunden weht der 700-hPa-Wind über
Zürich **nicht** aus dem Südsektor 135–225° — das sind keine Föhnlagen, das
ist ein Druckgradient bei West- oder anderer Strömung. Ein Kammwind-Sektor
90–270° als UND-Bedingung senkt die Fehlalarme in Altdorf von 760 auf
650 Stunden bei 2 Punkten weniger Trefferquote — ein kleiner, kostenloser Gewinn,
keine Lösung.

## P-3 · Inneralpin (Andeer, Davos, Visp) verpasst die Warnung jede zweite Föhnstunde

Andeer 50 %, Visp 56 %, Davos 61 % Trefferquote. Grund ist messbar: dort
tritt Föhn bei kleiner nationaler Druckdifferenz auf — Andeer 52 % der
Föhnstunden mit Δp < 4 hPa (24 % sogar < 2), Visp 45 %, Davos 42 %. Der
Median-Δp während Föhn liegt in Andeer bei 3.8 hPa, in Visp bei 4.3 —
also AN der Schwelle, nicht darüber. Andeer hat 260 Föhntage in 1000 —
mehr als jede andere Station. **Hier kann Lugano−Zürich prinzipiell nicht
helfen; nur ein lokaler Massstab (Talpunkt/Kammpunkt) kann diese
Föhnstunden sehen.** Das ist der eigentliche Anwendungsfall für den
Modell-Föhnindex pro Tal (Option 2 der Recherche).

## P-4 · Chur/Bad Ragaz/Elm liegen dazwischen — und haben viel Mischluft

Trefferquote 72–80 %, 20–29 % der Föhnstunden bei Δp < 4. Chur zählt
513 Mischluft-Stunden gegen 839 Föhnstunden (Kaltluft aus Schanfigg,
Domleschg). Bad Ragaz häufiger als Chur (881 vs. 839 h) — deckt sich mit
der Klimatologie (Talverzweigung). Elm (958 m) hat 765 Föhnstunden gegen
211 in Glarus (517 m) — der Höheneffekt der Literatur ist im Index 1:1
sichtbar; Elm ist die bessere Wahrheit für Glarner Startplätze.

## P-5 · Die Nordföhn-Warnung ist chronisch: 36 % aller Tage

Nordföhn-Warnung (Δp Zürich−Lugano ≥ 4 oder Kammwind N/NE ≥ 54 km/h) an
357 von 1000 Tagen, 25 % aller Flugstunden, 98 % davon allein durch Δp.
Piotta hat tatsächlich an 303 Tagen Föhn (Leventina ist eine Föhnmaschine:
1756 Föhnstunden), Magadino nur an 96 — dort 81 % Fehlalarm.
**Folge für Regionen mit `kritischer_foehn = Beide`** (Wallis, Bünden, Berner
Alpen, Lötschental — 9 der 29 Regionen): Süd ∪ Nord = Föhn-caution an
**533 von 1000 Tagen (53 %)**, in der Flugsaison April–September an 47 %
der Tage; `danger` an 155 Tagen (15 %). Eine Warnung, die jeden zweiten
Tag steht, ist keine Warnung. Das ist der grösste Einzelbefund dieses
Backtests und betrifft direkt das Region-Safety-Cap und die Briefing-Zeile
`Foehn=<low|mod|high>`.

## P-6 · Der 700-hPa-Kammwind über Zürich trägt fast nichts bei

Von 1275 Südföhn-Warnstunden sind 1140 Δp-only, 77 nur Kammwind, 58 beide.
Als UND-Bedingung (≥ 30 km/h) halbiert er die Trefferquote in Altdorf
(93 → 53 %): der Modellwind auf 700 hPa **über Zürich** ist kein Kammwind.
Wer einen Kammwind will, muss ihn am Kamm abfragen (Gütsch-Äquivalent).

## P-7 · Jahresgang bestätigt die Klimatologie

Föhnstunden Altdorf im Flugfenster: Maximum Feb–Apr 2024 (45/85/61 h),
Juli/Dezember nahe null. Die Warnstunden folgen dem Muster, liegen aber in
jedem Monat 1.5–4× darüber; Januar 2025: 100 Warnstunden bei 33 Föhnstunden.

## P-8 · Umgesetzt 27.09.2026: Südhalbkreis-Bedingung — Wirkung klein

Produktivlogik neu: Δp ≥ 4 **und** 700-hPa-Wind 90–270°. Backtest
vorher → nachher (Vorher-Stand in `AUTO_REPORT_vorher_2026-09-27.md`):
Altdorf Fehlalarm-h 760 → 727, Treffer 94.4 → 92.6 %; Vaduz 736 → 701,
93.0 → 91.6 %; Chur 439 → 410, 72.2 → 71.0 %; Südwarntage 189 → 184.
Der in P-2 geschätzte Gewinn (760 → 650) galt für eine reine Δp∧Sektor-Regel;
in der Produktivlogik bleibt der separate Kammwind-Trigger, und die meisten
Fehlalarme mit „falscher" Richtung liegen im Südwest-Rand (225–270°), der im
Halbkreis enthalten ist. Fazit: physikalisch richtig, aber kein Hebel — das
Fehlalarm-Problem ist strukturell (Föhn oben vs. am Boden) und nur lokal lösbar.

Entscheid User 27.09.: Nordföhn-Schwelle bleibt bei 4 hPa (konservativ);
die 36 % Warntage werden in Kauf genommen.

## Was daraus folgt (Vorschlag, nicht umgesetzt)

1. Sofort und billig: Kammwind-Sektor 90–270° als UND-Bedingung zum Δp
   (P-2) und die Nordföhn-Schwelle gegen Piotta/Magadino neu kalibrieren
   (P-5) — beides mit diesem Backtest messbar, bevor es live geht.
2. Die `Beide`-Regionen einzeln prüfen: welche brauchen die Nordwarnung
   wirklich (Leventina ja, Wallis?) — aus den Stationen ableitbar.
3. Der Modell-Föhnindex pro Tal ist dort nötig, wo die nationale Zahl blind
   ist: inneralpin (P-3). In Reuss/Rheintal löst er dagegen das
   Fehlalarm-Problem (P-2) — Föhn oben vs. am Boden.
4. `docs/FOEHN.md` anlegen; die Δp-Eingaben (nicht nur `foehn_risk`) in den
   Tages-Snapshot aufnehmen, sonst bleibt der Backtest auf die
   Rekonstruktion angewiesen.
