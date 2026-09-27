# Was Piloten den Chat wirklich fragen — Fazit

> **Grundlage:** die acht echten registrierten Nutzer (`user_07`, `10`, `16`, `18`, `20`,
> `21`, `24`, `25`) plus `anon_30`, die längste Sitzung im Datensatz.
> **Bewusst ausgeschlossen:** `user_01` ist das Konto des Betreibers (`mutschgito@hotmail.com`,
> in `data/subscribers.db` verifiziert), und die übrigen 33 anonymen Verläufe aus der
> Demo-Phase enthalten teils eigene Testchats und sind als Nutzersignal unbrauchbar.
> **Stand:** Verläufe vom Server geholt am 27.09.2026, 15:20 — jüngste Nutzeraktivität
> 26.09. 08:36, am 27.09. wurde nicht gechattet. Gespräche gitignored, siehe
> [README](README.md). Diese Datei enthält keine personenbezogenen Inhalte.

---

## Das Fazit in drei Sätzen

Der Chat wird nicht als Suchmaschine benutzt, sondern als Gutachter für einen Platz, den
der Pilot längst gewählt hat. Genau dafür ist er am schwächsten: Er findet die genannten
Orte oft nicht, antwortet fast immer in der falschen Sprache, und im schlimmsten Fall gibt
er ein falsches Nein oder eine Ausrede für einen Fehler, der von selbst nie verschwindet.
**Wer den Chat ernsthaft benutzt hat, ist danach nicht wiedergekommen — beide aktivsten
Nutzer nicht.**

---

## 1 · Die Eingabe ist ein Ortsname, keine Frage

Was die Nutzer wirklich getippt haben:

`Tomorrow flying in interlaken` · `Möntschele` · `18:00 in le Cernil?` · `Jura Thal (so)` ·
`will it fly in la bosse, close to givrins today?` · `stce que ça vol à Vercorin aujourd'hui?` ·
`Et brandlen` · `Typische Landeplätze im Engadin`

Ein Ort, manchmal eine Uhrzeit, fertig. Die Voranalyse-Erzählung („wir bewerten jedes
Gebiet, damit du nicht suchen musst") beschreibt nicht, wofür der Chat überwiegend benutzt
wird. Der Chat ist der Ort, an dem eine bereits getroffene Wahl geprüft wird.

**Eine Ausnahme, und sie ist neu (25.09.):** `user_16` fragte „Where to go tomorrow for a
chill morning flight, **maximum 1h30 away from Grenchen**?" — das ist eine echte
Wohin-Frage, und zwar über Fahrzeit, nicht über Region. Genau diese Frage scheiterte am
Werkzeug (§7). Die frühere Fassung dieses Befunds sagte „niemand hat gefragt, wohin er
gehen soll"; das gilt nicht mehr.

Zwei der Nutzer haben ausschliesslich einen vorgefertigten Vorschlag angetippt
(Meteogramm, Föhnlage) und nie selbst etwas geschrieben. Die Chips erzeugen einen Einstieg,
aber kein Gespräch.

## 2 · Die App antwortet in der falschen Sprache

| | Fragen |
|---|---|
| nicht auf Englisch gestellt | 21 |
| davon in der Fragesprache beantwortet | 4 |

Die 4 richtigen Antworten sind alle derselbe Nutzer (`user_20`) — und erst **nachdem** er
ausdrücklich „Auf Deutsch?" nachgeschoben hatte. Seine erste deutsche Frage bekam eine
englische Antwort. **Auf Französisch gestellte Fragen: 16, französische Antworten: 0.**
`anon_30` hat elf Fragen auf Französisch gestellt und elf englische Antworten bekommen,
ohne dass sich etwas änderte. Das ist kein Einzelfall, sondern der Normalfall.

Es passt zum Marketing-Befund: Ein Drittel der Kampagnenbesucher war französischsprachig.
Die Sprachfrage zieht sich vom Ad über die Landingpage bis in den Chat.

## 3 · Der Spot-Resolver ist die grösste Baustelle

9 Ortsnamen liefen ins Leere (`00-FEHLSCHLAEGE.md`), betroffen ist der aktivste Nutzer.
Vier Ursachen, die man nicht vermischen darf:

| Ursache | Beispiele | Was zu tun ist |
|---|---|---|
| **Echte Lücke** — fehlt in den 494 | Charmey, La Berra, Gros Perré, Grimmialp, Bünzen | aufnehmen oder Lücke offen benennen |
| **Ausland** — ausserhalb des Datensatzes | Grand Bornand (FR), Mijoux Col de la Faucille (FR) | Landesgrenze sauber benennen |
| **Alias fehlt** — da, heisst lokal anders | „Le Cernil" steht als **Corgémont** in der Liste | Alias-Tabelle für lokale Namen |
| **Resolver-Fehler** — da, wird nicht gefunden | Balmberg steht in `fluggebiete_pge.csv` | Suchlogik prüfen |

Geprüft gegen `data/fluggebiete_pge.csv`, 494 Zeilen.

**Achtung, die Beweislage ist geschrumpft:** Die Zeilen zu Alias und Resolver-Fehler
stammen aus einem Jura-Gespräch von `user_16` vom 21.09. (7 Fragen, 7 nicht gefundene
Namen: Balmberg, Cernier, Cernil, Le Cernil, Passwang, Roggenflue, Wasserfallen). Dieses
Gespräch **existiert auf dem Server nicht mehr** — die Verlaufsdatei wurde am 25.09. von
einem neuen Chat überschrieben. Der Befund bleibt gültig, der Rohbeleg dafür ist weg
(siehe „Datenverlust" unten). Deshalb steht die Fallzahl heute bei 9 statt 16.

Vollständigkeit wird von Piloten **erwartet**, sie ist kein Verkaufsargument. Deshalb wiegt
eine Lücke doppelt: Wer nach Charmey fragt und nichts bekommt, schliesst nicht „dieser Spot
fehlt", sondern „die App kennt meine Gegend nicht".

## 4 · Der schwerste Fall: selbstsicher am falschen Ort

`user_07` fragte nach **La Bosse bei Givrins** im Waadtländer Jura. Der Resolver suchte
Charmey, Gros Perré und La Berra, alle drei in den Freiburger Voralpen rund 60 km entfernt,
fand nichts davon, und die Antwort handelte dann ausführlich von **Gastlosen** — mit
Windwerten, Basishöhe und einer Empfehlung.

Das ist keine Datenlücke, sondern eine falsche Ortsauflösung, verpackt in eine Antwort, die
richtig klingt. Für eine Anwendung, die über Fliegen oder Nichtfliegen mitentscheidet, ist
das der schwerwiegendste Befund dieses Ordners.

## 5 · Das falsche Nein, dreimal widerlegt

`anon_30`, elf Fragen, 6. September, auf Französisch. Der Verlauf ist eine Lehrstunde:

1. Der Pilot fragt nach Büelen. Die App antwortet mit einem regionalen **Nein**.
2. Dreimal stellt er klar, dass er **keinen Streckenflug** will, nur starten und landen.
   Die App bleibt beim Nein, jetzt mit anderer Begründung.
3. Er widerspricht mit Fakten: keine Gewitterzellen am Morgen bei Wolfenschiessen.
   → *„You're right about the thunderstorms — and the forecast agrees with you."*
4. Er liefert die Starthöhe nach: Büelen liegt auf 1100 m.
   → *„Good point — let me pull the actual launch-height data instead of quoting the region reference."*
5. Er zitiert die Windwerte von der FSVL-Seite.
   → *„The model actually agrees with you: 5–10 km/h, comfortably in the allowed sector between 07:00 and 09:00."*

**Am Ende war der Tag fliegbar.** Die App hatte dreimal Nein gesagt und dreimal nachgegeben,
nachdem der Pilot die Arbeit selbst gemacht hatte. Sie hatte auf Regionsebene geurteilt statt
auf Startplatzebene, und die Absicht des Piloten ignoriert.

Ein falsches Nein ist für dieses Produkt so teuer wie ein falsches Ja. Das falsche Ja kostet
Vertrauen nach einem schlechten Flug, das falsche Nein kostet den Nutzer sofort. Er hat sich
nie registriert.

## 6 · Die Standardannahme ist Streckenflug

Mehrere Antworten argumentieren über XC-Potenzial, Arbeitshöhe und Steigwerte, obwohl
niemand danach gefragt hat. Der einfache Fall, starten, eine Runde fliegen, landen, ist der
häufigere, und er braucht andere Kriterien: ruhiger Startwind, stabile Luft, sicherer Platz.

Drei Nutzer mussten aktiv dagegen anreden, inzwischen auch registrierte:

- `anon_30` dreimal, auf Französisch (§5).
- `user_16` (25.09.): *„I don't want thermals, a little sled ride is fine."* Die Antwort
  danach war richtig (Startwind statt Thermik, Chasseral vor Weissenstein wegen
  Rotorgefahr bei West) — aber der Pilot musste sie erzwingen.
- `user_20`, auf Deutsch: *„Fokus auf Talwind. Kein Fokus auf Thermik."*

Damit ist das der zweithäufigste Korrekturgrund nach der Sprache.

## 7 · Die Reichweiten-Suche ist dauerhaft kaputt — gemeldet als „vorübergehend"

Der Fall `user_16` vom 25.09., die einzige echte Wohin-Frage im Datensatz:

> „Where to go tomorrow for a chill morning flight, **maximum 1h30** away from Grenchen?"

Die App antwortete: *„the routing service … is currently down … Give it a few minutes and
I'll re-run it; just say **try again**."* Der Pilot sagte „The word". Zweiter Versuch:
derselbe Fehler. Dritter Versuch: derselbe Fehler. **Ende des Gesprächs, der Nutzer ist
nicht wiedergekommen.**

Der Dienst war nie ausgefallen. Nachgemessen am 27.09.2026:

| Angefragte Fahrzeit | Antwort des öffentlichen Valhalla |
|---|---|
| 60 Minuten | 200 — Polygon kommt |
| 61 Minuten | 400 — `Exceeded max time: 60` |
| 90 Minuten (der Fall) | 400 — `Exceeded max time: 60` |

Der öffentliche Endpunkt (`valhalla1.openstreetmap.de`, FOSSGIS) deckelt Isochronen hart
bei **60 Minuten**. Unser Code lässt 1–360 Minuten zu (`routing.py`, `isochrone()`) und
übersetzt jeden HTTP-Fehler in „Dienst nicht erreichbar, bitte in ein paar Minuten erneut
versuchen". Ergebnis: Ein fester Grenzwert wird dem Nutzer als vorübergehende Störung
verkauft, und jedes „try again" muss scheitern. Derselbe Fehler steht auch in einem Verlauf
vom 26.07. — er ist seit mindestens zwei Monaten drin und trifft jede Anfrage über einer
Stunde.

Zu reparieren sind drei getrennte Dinge: die Anfrage bei 60 Minuten deckeln (oder in
mehrere Ringe zerlegen), den Grenzwert dem Nutzer ehrlich nennen statt ihn als Ausfall zu
tarnen, und „try again" nur dort anbieten, wo ein erneuter Versuch überhaupt helfen kann.

**Beim Reparieren kam eine vierte Grenze zum Vorschein, die nirgends dokumentiert ist.**
Der naheliegende Ausweg — statt einer Fläche die Fahrzeit zu jedem Startplatz berechnen —
scheitert für rund **60 % unserer Startplätze**: Der Dienst liefert dort `time: null`,
ohne Fehlermeldung. Nicht wegen der Entfernung, sondern wegen der Anbindung ans
Straßennetz: Rinderalp liegt 63 km weg, und eine einzelne Routenabfrage zum selben Punkt
antwortet sauber mit 155 Minuten / 110 km. Die Startplatz-Koordinaten liegen am Berg,
nicht an der Strasse.

Konsequenz für den Bau (umgesetzt 27.09., `docs/pläne/PLAN_routing_eigene_instanz.md`):
Bis 60 Minuten bleibt die **Fläche** der Filter, weil sie per Punkt-in-Polygon arbeitet
und keine Strassenanbindung braucht — sie erfasst alle Gebiete. Die **Fahrzeit** kommt als
Zahl beim Spot dazu, wo sie zu haben ist. Darüber trägt die Fahrzeit allein, und die
Antwort sagt ausdrücklich, dass die Liste unvollständig ist. Für die Vorgabe „mindestens
4 Stunden" reicht der Gratis-Dienst auf keinem Weg; das braucht eine eigene Instanz.

## 8 · Was gut funktioniert

Das gehört zum Bild. Wo die App den Ort kennt, sind die Antworten stark: Sie nennt Rating,
Zeitfenster, Basishöhe, Windschichtung und die Einschränkung dazu, und sie sagt offen, wenn
Daten fehlen („the model run doesn't cover that far out — honestly, I can't tell you
anything reliable about Sunday"). Ein Nutzer fragte ausdrücklich nach der **Begründung**
(„explain why tomorrow will not be flyable in Saint-Cergue") und bekam sie. Das ist das
Decision-Support-Versprechen, und es wird eingelöst, sobald der Ort getroffen ist.

Drei Punkte, die sich im neuen Material bestätigt haben:

- **Der Ein-Wort-Fall geht.** `user_25` (26.09.) tippte nur `Möntschele` und bekam ohne
  Rückfrage ein vollständiges Urteil zu Möntschelealp — Safety, Fenster, Rating, plus den
  Hinweis, dass der Start über Stunden fast windstill ist. Genau das war die Forderung.
- **Sie erfindet nichts.** Im Routing-Fehler (§7) weigerte sie sich ausdrücklich, Fahrzeiten
  aus Luftlinien zu schätzen. Die Ehrlichkeit ist richtig — nur die Diagnose war falsch.
- **Startplatz-Bemerkungen wirken.** Bei Weissenstein zog sie die hinterlegte Notiz „West
  oder NE → Rotoren, Röti nehmen" heran und empfahl deshalb Chasseral für den frühen Morgen.

---

## Was daraus folgt

1. **Spot-Resolver zuerst.** In dieser Reihenfolge: Alias-Tabelle für lokale Namen, dann die
   Suchlogik (Balmberg-Fall), dann die echten Datenlücken. Alles andere ist nachrangig.
2. **Nie einen fremden Ort unterschieben.** Wenn der Resolver den Ort nicht findet, muss die
   Antwort das sagen und die nächstgelegenen bewerteten Plätze mit Distanz anbieten. Auf
   keinen Fall über einen 60 km entfernten Platz referieren, als wäre es derselbe.
3. **In der Sprache der Frage antworten.** 17 von 21 falsch, auf Französisch 16 von 16, ist
   ein Systemfehler, kein Detail.
4. **Die 60-Minuten-Grenze im Routing einhalten und benennen** — und keinen festen
   Grenzwert als vorübergehenden Ausfall tarnen (§7). Billigster Fix im ganzen Dokument.
5. **Auf Startplatzebene urteilen, nicht auf Regionsebene**, sobald ein Startplatz genannt ist.
6. **Absicht nicht raten.** „Nur starten und landen" ist der häufigere Fall als Streckenflug;
   inzwischen mussten drei Nutzer aktiv dagegen anreden.
7. **Den Ein-Wort-Fall als Hauptfall behalten.** Er funktioniert (`Möntschele`) — das ist die
   Referenz, an der die übrigen Eingaben gemessen werden sollten.

## Datenverlust — eine Lehre fürs Verfahren

`data/history/<session>.json` ist der **laufende** Chatspeicher, kein Archiv: Ein neuer Chat
desselben Nutzers überschreibt die Datei. So ist das Jura-Gespräch von `user_16` vom 21.09.
zwischen zwei Auswertungsläufen verschwunden (7 Fragen, 7 Resolver-Fehlschläge). Im
täglichen Backup `~/flychat-backup/` liegen Chatverläufe nicht. Das ist derselbe Fehler wie
bei der Böenfront vom 30.07.: **rollende Dateien sofort einfrieren.**

Konkret: `konversationen/` beim Holen nicht überschreiben, sondern datiert ablegen, damit
ein späterer Lauf einen früheren Befund noch belegen kann.

## Wiederholen

```bash
scp deploy@178.105.39.152:~/flychat/data/history/*.json validation/chat/konversationen/
python validation/chat/aufbereiten.py
```
