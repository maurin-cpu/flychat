"""Ortsname des Piloten → Startplatz. Nie raten, nie einen Nachbarn unterschieben.

Der Chat bekam bis 26.10.2026 nur exakt → Gross/Klein → "Anfrage steckt im
Namen", erster Treffer gewinnt. Was daran scheiterte (validation/chat/BEFUNDE.md):

- "Charmey" ist in den Daten, heisst dort aber `Vounetz-1620`. Nicht gefunden,
  das Modell nahm stattdessen Gastlosen und antwortete selbstsicher dazu.
- "Mijoux Col de la Faucille" ist in den Daten (`Mijoux`, Gebiet Col de la
  Faucille). Nicht gefunden, weil die ganze Anfrage im Namen stecken musste.
- "Le Cernil" heisst in den Daten `Corgemont`.
- Mehrdeutige Teilstrings ("Montoz") lieferten still den ersten Treffer.

Dieses Modul sucht deshalb in mehreren Schluesseln je Startplatz (Name, Name
ohne Hoehenzahl, Klammerteile, Fluggebiet, Alias aus data/spot_aliases.csv),
meldet Mehrdeutigkeit als Kandidatenliste und gibt bei einem Fehlschlag nichts
zurueck. Was dann passiert (naechste Startplaetze per Geocoding), entscheidet
der Aufrufer — dieses Modul spricht nicht mit dem Netz.
"""
from __future__ import annotations

import csv
import difflib
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

ALIAS_PATH = Path(__file__).resolve().parent.parent / "data" / "spot_aliases.csv"

# Rang der Schluesselart: kleiner = staerker. Ein Treffer im Namen schlaegt
# einen Treffer im Fluggebiet ("Weissenstein" ist Name UND Gebiet).
_RANG = {"name": 0, "alias": 1, "teil": 2, "gebiet": 3}

# Fuellwoerter, die beim wortweisen Vergleich nichts unterscheiden.
_FUELL = {
    "le", "la", "les", "l", "de", "du", "des", "d", "der", "die", "das", "am",
    "im", "bei", "ob", "near", "close", "to", "the", "di", "del", "della",
    "startplatz", "start", "decollage", "launch", "site",
}

_MIN_TEILSTRING = 4     # kuerzere Schluessel ("Rigi" ok, "Ob" nicht) nicht als Teilstring
_FUZZY_SCHWELLE = 0.86  # Tippfehler ("Gastlossen") ja, fremde Namen nein


def norm(s: str) -> str:
    """Kleinbuchstaben, ohne Akzente, Umlaut-Digraphen gefaltet, nur a-z0-9.

    "Büelen" und "Bueelen" ergeben dasselbe, ebenso "St. Cergue" und
    "Saint-Cergue". Wird auf Anfrage UND Schluessel angewendet, deshalb darf
    die Faltung grob sein.
    """
    s = (s or "").lower().replace("ß", "ss")
    # Digraphen VOR dem Akzent-Abbau falten: "bueelen" → "buelen", und erst
    # danach wird aus "büelen" ebenfalls "buelen". Umgekehrt wuerde das ü-e
    # von "Büelen" selbst zum Digraphen.
    s = re.sub(r"([aou])e", r"\1", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(st|ste|sankt|san)\b", "saint", s)
    return re.sub(r"\s+", " ", s).strip()


def _ohne_hoehe(s: str) -> str:
    """'vounetz 1620' → 'vounetz'."""
    return re.sub(r"\s*\b\d{3,4}\b\s*", " ", s).strip()


def _woerter(s: str) -> set[str]:
    return {w for w in s.split() if w not in _FUELL and not w.isdigit()}


@dataclass
class Ergebnis:
    spot: dict | None = None
    kandidaten: list[dict] = field(default_factory=list)
    art: str = ""           # name | alias | teil | gebiet | teilstring | woerter | tippfehler
    schluessel: str = ""    # der Schluessel, der getroffen hat (fuer die Rueckmeldung)

    @property
    def eindeutig(self) -> bool:
        return self.spot is not None


def lade_aliasse(path: Path = ALIAS_PATH) -> list[tuple[str, str]]:
    """(alias, site_name) aus data/spot_aliases.csv. Fehlt die Datei: leer."""
    if not path.exists():
        return []
    paare = []
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            a, s = (row.get("alias") or "").strip(), (row.get("site_name") or "").strip()
            if a and s:
                paare.append((a, s))
    return paare


class SpotResolver:
    def __init__(self, spots: list[dict], aliasse: list[tuple[str, str]] | None = None):
        self.spots = spots
        self._nach_name = {s.get("name"): s for s in spots}
        # schluessel → [(rang, art, spot)]
        self._index: dict[str, list[tuple[int, str, dict]]] = {}
        for s in spots:
            name = s.get("name") or ""
            self._add(norm(name), "name", s)
            self._add(_ohne_hoehe(norm(name)), "name", s)
            # Klammerteile: "Baldern (Uetliberg)", "La Barillette (or:Les Burnes Gelées)"
            for teil in re.findall(r"\(([^)]*)\)", name):
                for stueck in re.split(r"\bor\s*:|/|,", teil):
                    self._add(norm(stueck), "teil", s)
            vor_klammer = name.split("(")[0]
            if vor_klammer != name:
                self._add(_ohne_hoehe(norm(vor_klammer)), "name", s)
            # "Büelen / Bueelen" → beide Haelften
            for stueck in re.split(r"\s+[/-]\s+", name):
                if stueck != name:
                    self._add(_ohne_hoehe(norm(stueck)), "teil", s)
            if s.get("fluggebiet"):
                self._add(norm(s["fluggebiet"]), "gebiet", s)
        for alias, site in (aliasse if aliasse is not None else lade_aliasse()):
            spot = self._nach_name.get(site)
            if spot is None:
                logger.warning("spot_aliases.csv: '%s' zeigt auf unbekannten Startplatz '%s'", alias, site)
                continue
            self._add(norm(alias), "alias", spot)

    def _add(self, key: str, art: str, spot: dict) -> None:
        if not key:
            return
        eintraege = self._index.setdefault(key, [])
        if not any(e[2] is spot and e[0] <= _RANG[art] for e in eintraege):
            eintraege.append((_RANG[art], art, spot))

    @staticmethod
    def _auswahl(treffer: list[tuple[int, str, dict, str]]) -> Ergebnis | None:
        """Bester Rang gewinnt; ein Startplatz → Treffer, mehrere → Kandidaten."""
        if not treffer:
            return None
        bester = min(t[0] for t in treffer)
        oben = [t for t in treffer if t[0] == bester]
        spots: list[dict] = []
        for t in oben:
            if not any(t[2] is s for s in spots):
                spots.append(t[2])
        if len(spots) == 1:
            return Ergebnis(spot=spots[0], art=oben[0][1], schluessel=oben[0][3])
        return Ergebnis(kandidaten=spots[:15], art=oben[0][1], schluessel=oben[0][3])

    def aufloesen(self, query: str) -> Ergebnis:
        q = (query or "").strip()
        if not q:
            return Ergebnis()
        if q in self._nach_name:
            return Ergebnis(spot=self._nach_name[q], art="name", schluessel=q)
        qn = norm(q)
        if not qn:
            return Ergebnis()

        # 1 · Schluessel exakt (mit und ohne Hoehenzahl)
        for kandidat in (qn, _ohne_hoehe(qn)):
            hit = self._auswahl([(r, a, s, kandidat) for r, a, s in self._index.get(kandidat, [])])
            if hit:
                return hit

        # 2a · Die Anfrage enthaelt einen ganzen Schluessel: "Mijoux Col de la
        #      Faucille" enthaelt den Namen "mijoux" und das Gebiet "col de la
        #      faucille". Der Name schlaegt das Gebiet.
        treffer = [
            (r, a, s, key)
            for key, eintraege in self._index.items()
            if len(key) >= _MIN_TEILSTRING and re.search(rf"\b{re.escape(key)}\b", qn)
            for r, a, s in eintraege
        ]
        hit = self._auswahl(treffer)
        if hit:
            hit.art = "teilstring" if hit.art != "alias" else hit.art
            return hit

        # 2b · Die Anfrage ist ein Bruchstueck eines Schluessels: "Möntschele"
        #      steckt in "möntschelealp". Hier zaehlen alle Arten gleich, sonst
        #      waehlt "Grenchen" still "Grenchenberg Nord" und verschweigt Buetzen
        #      (Gebiet "Grenchenberg Bützen").
        if len(qn) >= _MIN_TEILSTRING:
            treffer = [
                (0, a, s, key)
                for key, eintraege in self._index.items() if qn in key
                for _r, a, s in eintraege
            ]
            hit = self._auswahl(treffer)
            if hit:
                hit.art = "teilstring"
                return hit

        # 3 · Wortweise: alle bedeutungstragenden Woerter der Anfrage im Schluessel
        qw = _woerter(qn)
        if qw:
            treffer = [(r, a, s, key) for key, eintraege in self._index.items()
                       if qw <= _woerter(key) for r, a, s in eintraege]
            hit = self._auswahl(treffer)
            if hit:
                hit.art = "woerter"
                return hit

        # 4 · Tippfehler
        nahe = difflib.get_close_matches(qn, list(self._index), n=5, cutoff=_FUZZY_SCHWELLE)
        if nahe:
            treffer = [(r, a, s, nahe[0]) for r, a, s in self._index[nahe[0]]]
            hit = self._auswahl(treffer)
            if hit:
                hit.art = "tippfehler"
                return hit
        return Ergebnis()
