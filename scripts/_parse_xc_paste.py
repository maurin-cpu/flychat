"""Einmal-Parser: XContest-Tageswertung (Copy-Paste) -> _raw/YYYY-MM-DD.tsv.

Liest alle validation/xcontest/_raw/_paste_*.txt, ankert auf die Zeit-Zeile
'DD.MM.YY HH:MM=UTC+02:00' und nimmt die folgenden 3 nicht-leeren Zeilen als
Pilot / Launch / Stats. Ländercode (2 Großbuchstaben) wird von Pilot+Launch
entfernt. Schreibt pro Tag eine TSV im Format launch\tkm\tstart\tairtime\tpilot.
"""
from __future__ import annotations
import re, glob
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "validation/xcontest" / "_raw"

TIME_RE = re.compile(r"^\s*(\d{2})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})=UTC")
STATS_RE = re.compile(r"([\d]+\.[\d]+)\s*km.*?(\d+)\s*:\s*(\d+)\s*h")


def strip_cc(s: str) -> str:
    s = s.strip()
    # führender 2-Buchstaben-Ländercode (z.B. CH, HU, KR) entfernen
    if len(s) >= 2 and s[:2].isalpha() and s[:2].isupper():
        return s[2:].strip()
    return s


def parse_file(path: Path, by_date: dict):
    lines = path.read_text(encoding="utf-8").splitlines()
    i = 0
    n = len(lines)
    while i < n:
        m = TIME_RE.match(lines[i])
        if not m:
            i += 1
            continue
        dd, mm, yy, hh, mi = m.groups()
        date = f"20{yy}-{mm}-{dd}"
        start = f"{hh}:{mi}"
        # nächste 3 nicht-leeren Zeilen
        fields = []
        j = i + 1
        while j < n and len(fields) < 3:
            if lines[j].strip():
                fields.append(lines[j])
            j += 1
        if len(fields) < 3:
            i = j
            continue
        pilot_raw, launch_raw, stats_raw = fields
        sm = STATS_RE.search(stats_raw)
        if not sm:
            # Stats-Zeile nicht gefunden -> Datensatz überspringen
            i = j
            continue
        km, ah, am = sm.groups()
        pilot = strip_cc(pilot_raw)
        launch = strip_cc(launch_raw)
        airtime = f"{int(ah)}:{am}"
        by_date[date].append((launch, km, start, airtime, pilot))
        i = j


def main():
    by_date = defaultdict(list)
    paste_files = sorted(glob.glob(str(RAW / "_paste_*.txt")))
    if not paste_files:
        print("Keine _paste_*.txt gefunden.")
        return
    for pf in paste_files:
        parse_file(Path(pf), by_date)
    for date in sorted(by_date):
        flights = by_date[date]
        out = RAW / f"{date}.tsv"
        with open(out, "w", encoding="utf-8") as f:
            for launch, km, start, airtime, pilot in flights:
                f.write(f"{launch}\t{km}\t{start}\t{airtime}\t{pilot}\n")
        print(f"{date}: {len(flights)} Flüge -> {out.name}")


if __name__ == "__main__":
    main()
