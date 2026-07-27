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

## Was hier liegt (versioniert)

| Datei | Inhalt |
|---|---|
| `observations.csv` | eine Zeile pro vorhergesagtem Frontdurchgang + was eingetreten ist. Schema in `SCHEMA.md` |
| `PATTERNS.md` | numerierte Befunde `F-001`, `F-002` … eigener Namensraum, damit keine Verwechslung mit den XContest-`I-0xx` entsteht |
| `SCHEMA.md` | Spaltendefinition von `observations.csv` |
| `aussagen/` | unsere Aussage-Schnappschüsse je Lauf und Kalendertag, unverändert. Der Beweis, **was wir wann gesagt haben** |
| `<datum>_*.md` | Notizen **ereignisbezogen**, nicht täglich — es gibt frontfreie Wochen |

## Was in `data/dwd_fronten_archiv/` liegt

| | Grösse/Tag | in Git? |
|---|---|---|
| Analysekarte PNG | ~5 MB je Termin | **nein** — 150–300 MB/Monat |
| Vorhersagekarten PNG | 5 × ~214 KB | **nein** |
| Ausgelesene Linien (GeoJSON) | ~131 KB | **ja**, ~50 MB/Jahr |
| DWD-Bulletins, Aussage-Schnappschüsse | ~10 KB | **ja** |

**Warum die Linien doch versioniert sind** (ursprünglich anders geplant): Der
Abholvorgang läuft auch als Cloud-Routine, und die hat keinen bleibenden
Datenträger — was sie nicht committet, ist nach dem Lauf weg. Da der DWD die
Karten nach ~2 Tagen löscht, wären die Linien damit unwiederbringlich verloren.
Sie sind der eigentliche Extrakt; die Rohkarten sind nur für eine *verbesserte*
Extraktion nötig und bleiben deshalb auf der lokalen Platte.

## Betrieb

```bash
python scripts/archive_dwd_fronten.py        # holt Karten, Bulletins, Aussagen
```

Läuft **4× täglich** (04, 08, 14, 20 Uhr lokal) an zwei Orten, mit **getrennten
Zuständigkeiten** — sonst erzeugen beide dieselben versionierten Dateien und
jeder `git pull` kollidiert mit den lokalen Doppeln:

| | holt | committet |
|---|---|---|
| **Cloud-Routine** (`trig_019kkXYvCvVromo9XhXEGmYy`, cron `0 2,6,12,18 * * *` UTC) | alles **ausser** den PNGs | ja, direkt auf `main` |
| **Lokal** (Aufgabe `Flychat-DWD-Frontenarchiv`, `--nur rohkarten`) | **nur** die PNG-Rohkarten | nein, die sind gitignored |

Die Cloud läuft zuverlässig, hat aber keinen bleibenden Datenträger. Der lokale
Lauf hat einen, läuft aber nur bei eingeschaltetem Rechner — deshalb bekommt er
genau das, was verzichtbar ist: die Rohkarten für eine spätere, verbesserte
Bilderkennung.

```bash
python scripts/archive_dwd_fronten.py                  # Volllauf (wie Cloud)
python scripts/archive_dwd_fronten.py --nur rohkarten  # nur PNGs (wie lokal)
```

Zwei Eigenheiten der Quelle, die das Abholintervall bestimmen: die *datierten*
Analysekarten sind schwarz-weiss und damit nutzlos — farbig ist nur die jeweils
aktuelle. Und `dwdc` erscheint alle 12 h (00/12 UTC), `dwdna` alle 6 h. Wer
einen Termin verpasst, bekommt ihn nicht zurück.

## Reproduzieren

```bash
python scripts/experiment_dwd_fronten_extraktion.py --profil vorhersage \
       --lauf 2026072600 --alle-steps --overlay      # Linien + Kontrollbild
python scripts/experiment_fronten_zeitachse.py --lauf 2026072600   # Aussagen
python scripts/experiment_fronten_zeitachse.py --selftest          # Zeitrechnung
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
