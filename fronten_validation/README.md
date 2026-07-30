# Fronten-Validierung

Erkenntnisspeicher für die Frontenvorhersage aus den DWD-Karten. Aufgebaut wie
`xcontest_validation/`, mit einem bewussten Unterschied: **hier füllt sich die
Datenbasis automatisch.** Bei XContest trägt ein Mensch Flüge ein, dort liegt
der Wert in der Kuratierung. Hier sammeln Skripte, der Mensch schreibt nur die
Befunde in `PATTERNS.md`.

Der Plan mit Verfahren, Messungen und Entscheidungen liegt wie üblich in
`docs/pläne/PLAN_fronten_darstellung.md`. Dieser Ordner ist der Beleg-, nicht
der Planungsort.

## Worum es geht

Wir lesen Fronten aus den DWD-Karten aus (handanalysiert, siehe Plan §1f) und
leiten daraus ab, **wann** eine Front eine unserer vier Flugwetter-Zonen quert.
Die Frage dieses Ordners: **Stimmt das?**

Geprüft wird nicht Linie gegen Linie, sondern **was wir gesagt haben** gegen
**was eingetreten ist**. Der Schiedsrichter ist die spätere Handanalyse
derselben Gültigkeitszeit — dieselbe Quelle, aber die Ist-Lage statt der
Vorhersage.

## Was hier liegt

Die Trennlinie läuft zwischen **Hand** und **Maschine**, nicht zwischen wichtig
und unwichtig. Was ein Mensch geschrieben hat, liegt im Git. Was ein Lauf
erzeugt, gehört dem Server und wird geholt, nie gepusht.

| Datei | Inhalt | in Git? |
|---|---|---|
| `PATTERNS.md` | numerierte Befunde `F-001`, `F-002` … eigener Namensraum, damit keine Verwechslung mit den XContest-`I-0xx` entsteht | **ja** |
| `SCHEMA.md` | Spaltendefinition von `observations.csv` | **ja** |
| `handurteile.csv` | **von Hand gefällte Urteile.** Der Validator legt sie bei jedem Lauf über die Maschinenzeilen; jedes nicht leere Feld gewinnt, leere bleiben maschinell | **ja** |
| `<datum>_*.md` | Notizen **ereignisbezogen**, nicht täglich — es gibt frontfreie Wochen | **ja** |
| `observations.csv` | eine Zeile pro vorhergesagtem Frontdurchgang + was eingetreten ist. Schema in `SCHEMA.md` | nein |
| `AUTO_REPORT.md` | **erzeugt, nicht von Hand pflegen** — Urteilsbilanz, Systematik von `delta_h`, Lauf-Jitter, verpasste Fronten. Wird bei jedem Lauf neu geschrieben | nein |
| `aussagen/` | unsere Aussage-Schnappschüsse je Lauf und Kalendertag, unverändert. Der Beweis, **was wir wann gesagt haben** | nein |

Ein Urteil gehört deshalb **immer** nach `handurteile.csv` und nie direkt in
`observations.csv` — die wird beim nächsten Lauf überschrieben.

## Was in `data/dwd_fronten_archiv/` liegt

| | Grösse/Tag | in Git? |
|---|---|---|
| Analysekarte PNG | ~5 MB je Termin | **nein** — 150–300 MB/Monat |
| Vorhersagekarten PNG | 5 × ~214 KB | **nein** |
| Ausgelesene Linien (GeoJSON) | ~131 KB | **nein** |
| DWD-Bulletins, Aussage-Schnappschüsse | ~10 KB | **nein** |

**Nichts davon liegt im Git** — behandelt wie `data/wetterdaten.json`. Bis zum
29.07.2026 waren die Linien versioniert, weil der Abholvorgang als
Cloud-Routine ohne bleibenden Datenträger lief. Seit der Hetzner-Server sammelt
(siehe *Betrieb*), gibt es einen Datenträger, und der Umweg über Git entfällt.
Geholt wird mit `scripts/sync_from_server.ps1` (Roh-PNGs nur mit
`-MitKarten`), Einzelheiten in `scripts/SYNC_README.md`.

## Betrieb

```bash
python scripts/archive_dwd_fronten.py        # holt Karten, Bulletins, Aussagen —
                                             # traegt ein UND beurteilt gleich mit
```

Der Volllauf haengt drei Schritte hintereinander: einsammeln
(`archive_dwd_fronten.py`), eintragen (`build_fronten_observations.py`),
beurteilen (`validate_fronten.py`). So wird jede Front von selbst zum Testfall,
ohne dass jemand daran denken muss.

**Ausfall-Alarm.** Am Ende jedes ableitenden Laufs entscheidet
`scripts/fronten_alarm.py`, ob eine Warnmail an `config.OPS_ALERT_EMAIL`
(`info@wingcast.ch`) noetig ist — Quelle weg, Layout geaendert oder null
Abschnitte auf der ganzen Karte. Hoechstens eine Mail pro Lauf, keine
Wiederholung vor 7 Tagen, Entwarnung wenn es wieder laeuft. Der Zustand liegt
in `data/dwd_fronten_archiv/alarm_zustand.json` auf dem Server.

Dass der Alarm trägt, ist belegt: am 28.07.2026 um 02:04 UTC blockierte ein
Proxy den Cloud-Lauf (`Tunnel connection failed: 403`), der Zustand sprang
korrekt auf `quelle_weg` und blieb dort, bis die Kette wieder lief.

```bash
python scripts/fronten_alarm.py --zustand    # laeuft gerade ein Alarm?
python scripts/fronten_alarm.py --selftest   # Zustandsmaschine pruefen
python scripts/fronten_alarm.py --testmail   # Versandweg pruefen
```

Läuft **4× täglich auf dem Hetzner-Server**, im Scheduler-Thread des
`wingcast`-Dienstes (`scheduler.py`, `FRONTEN_STUNDEN` = 02/08/14/20 Uhr). Kein
cron, kein zweiter Prozess: der Thread läuft ohnehin schon für Briefings und
Monats-Accuracy, der Fronten-Slot ist dort ein dritter Event-Typ. Reissleine
ohne Deploy: `WINGCAST_FRONTEN=0`.

Warum 6 h Abstand: Der DWD hält Open Data nur rund **zwei Tage** vor, und die
farbige Handanalyse gibt es **nur als `LATEST`** — alle 12 h überschrieben, die
datierten Zwillinge sind schwarz-weiss und unbrauchbar. Ein verpasster Termin
ist endgültig weg. Bei 6 h Abstand fällt kein 12-h-Termin durch, auch wenn ein
Lauf scheitert.

**Vorher, bis 30.07.2026:** eine Cloud-Routine (alles ausser PNGs, committete
auf `main`) plus eine Windows-Aufgabe (`--nur rohkarten`). Aufgegeben, weil die
Cloud ab dem 28.07. durch einen Proxy nicht mehr an den DWD kam und die
Windows-Aufgabe nur bei eingeschaltetem Rechner läuft. Der Server hat beide
Nachteile nicht.

**Selbstheilung.** Sind die Rohkarten da, die Ableitung aber ausgefallen, holt
`--nur nachziehen` die fehlenden GeoJSON aus den archivierten PNGs — auch wenn
der Lauf im DWD-Listing längst weg ist. Läuft im Volllauf automatisch mit. Der
Fall ist real: der 28.07.2026 wurde genau so gerettet.

```bash
python scripts/archive_dwd_fronten.py                   # Volllauf (wie der Server)
python scripts/archive_dwd_fronten.py --nur nachziehen  # nur fehlende GeoJSON retten
python scripts/archive_dwd_fronten.py --nur rohkarten   # nur PNGs, nichts abgeleitet
```

Zwei Eigenheiten der Quelle, die das Abholintervall bestimmen: die *datierten*
Analysekarten sind schwarz-weiss und damit nutzlos — farbig ist nur die jeweils
aktuelle. Und `dwdc` erscheint alle 12 h (00/12 UTC), `dwdna` alle 6 h. Wer
einen Termin verpasst, bekommt ihn nicht zurück.

**Kein Schnappschuss ohne neue Karten.** Ein Lauf schreibt eine Aussage nur,
wenn sich die Eingangskarten seit der letzten geändert haben
(`quelle_fingerprint` im Schnappschuss). Ohne diese Sperre erzeugt jeder
Leerlauf eine weitere Kopie derselben Messung — und die Validierung führte
jede Kopie als eigene Beobachtung. Gemessen am 30.07.2026: aus 3 Messungen
wurden 10 Zeilen.

## Reproduzieren

```bash
python scripts/experiment_dwd_fronten_extraktion.py --profil vorhersage \
       --lauf 2026072600 --alle-steps --overlay      # Linien + Kontrollbild
python scripts/experiment_fronten_zeitachse.py --lauf 2026072600   # Aussagen
python scripts/experiment_fronten_zeitachse.py --selftest          # Zeitrechnung
python scripts/validate_fronten.py --probelauf                     # Urteile, ohne zu schreiben
python scripts/validate_fronten.py --selftest                      # Urteilslogik
```

## Die zwei Regeln, die hier gelten

1. **Ein Verfahren, das nur „nichts gefunden" liefern kann, ist nicht
   geprüft — und eines, das plausible Zahlen liefert, ist es auch nicht.**
   Erst die Gegenprobe an einer unabhängigen Grösse trennt beides. Der
   Fehlalarm F-001 sah vollkommen überzeugend aus.
2. **Keine Schwelle von Hand setzen.** Wie im ganzen Projekt: jede Schwelle
   gegen Belege kalibrieren. Wo das noch nicht möglich war (Querabstand
   100 km, Zonenanteil 10 %), steht die Begründung im Code und die Schwelle
   auf der Prüfliste.
