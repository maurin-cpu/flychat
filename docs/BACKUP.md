# Backup der Server-Daten

**Entscheid 03.08.2026:** Die server-lokalen Daten (Snapshots, Validierung,
DWD-Archiv, Live-Wetterstand) werden täglich gesichert — **nicht** nach Git.
Begründung: ~11 MB/Tag wachsen in Git unbegrenzt und sind nie wieder
löschbar; und zwei Vorfälle in einer Woche (rollendes Prognosefenster
31.07., Deploy-Stash frass 8 Snapshot-Tage, 23.07. endgültig verloren)
haben gezeigt, dass eine einzige Server-Kopie nicht reicht.

**Aktuelle Stufe (Übergangslösung, Entscheid 03.08.):** lokaler Ordner
`/home/deploy/flychat-backup/` neben dem Projektordner. Schützt vor
Deploy-/Skript-Unfällen (die bisherige reale Verlustursache), **nicht** vor
einem Plattenausfall. **Zielstufe:** Hetzner Storage Box — der Wechsel ist
später nur `echo 'u…@u….your-storagebox.de' > ~/.storagebox`, das Skript
schaltet dann selbst um.

## Struktur im Backup

```
flychat-backup/
├─ weather_archive/       tägliche Prognose-Freezes (Validierungs-Grundlage)
├─ validation/            Messwerte, Urteile, Scoreboards aller Domänen
├─ dwd_fronten_archiv/    Frontenkarten-Rohdaten + Aussagen
└─ wetterdaten/           letzter Live-Stand (wetterdaten.json + Analysen)
```

Das Backup ist **additiv** — `scripts/backup_daily.sh` löscht nie etwas im
Backup. Ein lokaler Datenverlust pflanzt sich damit nicht fort.

## Betrieb

Cron auf dem Server (täglich 07:30, nach dem Morgen-Lauf):

```
30 7 * * * /home/deploy/flychat/scripts/backup_daily.sh >> /home/deploy/backup.log 2>&1
```

## Später: Umstieg auf die Storage Box

1. **Storage Box bestellen** (Hetzner Console → Storage Boxes → kleinste
   Stufe reicht auf Jahre). Bei den Box-Einstellungen **SSH-Support
   aktivieren**. Ergebnis: Adresse `u######@u######.your-storagebox.de`.
2. **Server-Schlüssel hinterlegen:** `~/.ssh/id_ed25519.pub` des Servers
   (existiert seit 03.08.) im Hetzner-Panel der Box als SSH-Key eintragen.
3. **Umschalten:** `echo 'u######@u######.your-storagebox.de' > ~/.storagebox`
4. **Testlauf:** `~/flychat/scripts/backup_daily.sh` — danach den lokalen
   `~/flychat-backup/` einmalig auf die Box nachschieben und löschen.

## Wiederherstellung

Einzelne Tage/Ordner zurückholen (Box → Server), Beispiel:

```bash
rsync -az -e "ssh -p 23" \
  "$(cat ~/.storagebox):flychat-backup/weather_archive/2026-08-02.json" \
  ~/flychat/data/weather_archive/
```

## Grenzen

- Die Box hält **eine** Kopie je Datei (kein Versionsverlauf). Da die
  Tagesdateien unveränderlich sind, reicht das; nur `wetterdaten/` wird
  täglich überschrieben.
- Das Backup läuft auf dem Server — stirbt der Server *vor* 07:30, fehlt
  der jüngste Tag. Verkraftbar: der Freeze desselben Morgens wäre ohnehin
  das einzige Opfer.
