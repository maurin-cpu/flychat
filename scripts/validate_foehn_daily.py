# -*- coding: utf-8 -*-
"""Täglicher Föhn-Abgleich: Föhn-Block des Briefings (eingefrorene Talwerte) gegen
den amtlichen MeteoSchweiz-Föhnindex an den Föhn-Talstationen.

Läuft morgens (Scheduler) oder per Hand:
    python scripts/validate_foehn_daily.py                     # letzter komplett
                                                               # publizierter Tag
    python scripts/validate_foehn_daily.py --date 2026-10-12
    python scripts/validate_foehn_daily.py --backfill 2026-10-04 2026-10-12

DATENARM (User 14.10.2026): keine Rohmessungen archivieren. Je Tag entsteht nur
    validation/foehn/urteile/YYYY-MM-DD.json   (~5 KB: Vorhersage × Föhnstunden je Tal)
und daraus fortgeschrieben
    validation/foehn/scoreboard_daily.json
    validation/foehn/AUTO_REPORT_DAILY.md
Die Stationswerte werden je Lauf per HTTP-Range nur vom Dateiende geholt und
nach dem Zählen verworfen.

Prognose-Quelle ist der zentrale Freeze `data/weather_archive/YYYY-MM-DD.json`
→ `foehn_tal` (seit 04.10.2026, Regel 1 in validation/README.md). Die Merkmale
werden mit der AKTUELLEN Regel nachgerechnet (`foehn_indicators.evaluate_talpunkt`
+ `foehn_talpunkte.sektor_fuer` — dieselben Funktionen wie das Briefing).

Urteil je Tal, zwei Stufen:
    voll  = Briefing zeigt alle drei Merkmale (Richtung, Wind, trockene Luft)
    warn  = Briefing zeigt alle drei ODER Föhnrichtung + trockene Luft
    Wahrheit: Föhnindex 2 in >= TAL_MIN_HOURS Flugstunden (Stunde = Index 2 in
    >= 3 von 6 Zehnminuten). Mischluft (Index 1) wird getrennt gezählt und weder
    als Treffer noch als Fehlalarm gewertet (validation/foehn/README.md, Grenze 4).
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config                                          # noqa: E402
from foehn_indicators import TAL_MIN_HOURS, evaluate_talpunkt   # noqa: E402
from foehn_talpunkte import sektor_fuer                # noqa: E402
from scripts import validation_common as vc            # noqa: E402
from scripts.validate_gewitter_daily import letzter_vollstaendiger_tag  # noqa: E402

DOM = vc.ROOT / "validation" / "foehn"
URTEILE = DOM / "urteile"
import os  # noqa: E402
ARCHIVE = Path(os.environ.get("FOEHN_VAL_ARCHIVE") or vc.ROOT / "data" / "weather_archive")
REGEL = ("Talmerkmale je Tal: gemessener Sektor (14.10.2026) + Wind >=20/Böe >=30 + Feuchte <=60 "
         "(voll); Richtung + trocken + Wind >=16/Böe >=22 (warn); >= 2 Flugstunden")
_KEYS = ("wind_speed_10m", "wind_gusts_10m", "wind_direction_10m", "relative_humidity_2m")


def _stationsindex(abbr: str, day: datetime.date) -> dict[int, list[str]] | None:
    """Föhnindex-Zehnminutenwerte je lokaler Stunde des Tages, oder None."""
    url = f"{vc.SMN_BASE}/{abbr}/ogd-smn_{abbr}_t_recent.csv"
    try:
        head = vc._fetch(url, {"Range": "bytes=0-3000"}).decode("utf-8", "replace")
        header = head.split("\n")[0].strip().split(";")
        tail = vc._fetch(url, {"Range": f"bytes=-{vc._TAIL_BYTES}"}).decode("utf-8", "replace")
    except Exception:
        return None
    if "wcc006s0" not in header:
        return None
    out: dict[int, list[str]] = {}
    for ln in tail.split("\n")[1:]:
        if ln.count(";") != len(header) - 1:
            continue
        r = dict(zip(header, ln.strip().split(";")))
        ts = r.get("reference_timestamp", "")
        try:
            u = datetime.datetime(int(ts[6:10]), int(ts[3:5]), int(ts[0:2]), int(ts[11:13]), int(ts[14:16]),
                                  tzinfo=datetime.timezone.utc)
        except (ValueError, IndexError):
            continue
        loc = u.astimezone(vc._TZ)
        if loc.date() == day:
            out.setdefault(loc.hour, []).append(r.get("wcc006s0", ""))
    return out or None


def _wahrheit(index_by_hour: dict[int, list[str]]) -> dict:
    """Föhn-/Mischluftstunden im Flugfenster (Stunde = >= 3 von 6 Zehnminuten)."""
    h0, h1 = config.FLIGHT_HOURS_START, config.FLIGHT_HOURS_END
    foehn = [h for h in range(h0, h1) if sum(v == "2" for v in index_by_hour.get(h, [])) >= 3]
    misch = [h for h in range(h0, h1) if h not in foehn
             and sum(v in ("1", "2") for v in index_by_hour.get(h, [])) >= 3]
    werte = sum(len(index_by_hour.get(h, [])) for h in range(h0, h1))
    return {"foehn_std": foehn, "misch_std": misch, "werte": werte}


def _vorhersage(punkt: dict, pid: str) -> dict:
    """Talmerkmale aus den eingefrorenen Stundenwerten, mit der HEUTIGEN Regel."""
    meta, hours = punkt.get("meta") or {}, punkt.get("hours") or {}
    keys = sorted(hours)
    hourly = {k: [] for k in _KEYS}
    for hhmm in keys:
        v = hours[hhmm]
        hourly["wind_speed_10m"].append(v.get("wind_kmh"))
        hourly["wind_gusts_10m"].append(v.get("gust_kmh"))
        hourly["wind_direction_10m"].append(v.get("dir_deg"))
        hourly["relative_humidity_2m"].append(v.get("rh"))
    r = evaluate_talpunkt(hourly, list(range(len(keys))), meta.get("foehn_typ", ""),
                          sektor=sektor_fuer(pid, meta))
    stufe = ("merkmale" if r.get("bestaetigt") else "richtung_trocken" if r.get("dir_dry")
             else "ruhig" if r.get("has_data") else "nicht_pruefbar")
    return {"stufe": stufe, "stunden_merkmale": r.get("hours", 0), "stunden_warn": r.get("dir_dry_hours", 0)}


def _urteil(vorhergesagt: bool, w: dict) -> str:
    if len(w["foehn_std"]) >= TAL_MIN_HOURS:
        return "treffer" if vorhergesagt else "verpasst"
    if len(w["misch_std"]) >= TAL_MIN_HOURS:
        return "mischluft"
    return "fehlalarm" if vorhergesagt else "still"


def validate_day(day: datetime.date) -> bool:
    p = ARCHIVE / f"{day.isoformat()}.json"
    snap = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    tal = (snap or {}).get("foehn_tal") or {}
    punkte = tal.get("punkte") or {}
    if not punkte:
        print(f"[foehn] {day}: kein foehn_tal im Freeze — übersprungen")
        return False
    taeler = {}
    for pid, punkt in punkte.items():
        meta = punkt.get("meta") or {}
        abbr = (meta.get("station_abbr") or "").lower()
        vh = _vorhersage(punkt, pid)
        e = {"tal": meta.get("tal", pid), "station": abbr or None, "foehn_typ": meta.get("foehn_typ"), **vh}
        idx = _stationsindex(abbr, day) if abbr else None
        if not idx:
            e["urteil_voll"] = e["urteil_warn"] = "keine_messung"
        else:
            w = _wahrheit(idx)
            e.update(w)
            e["urteil_voll"] = _urteil(vh["stufe"] == "merkmale", w)
            e["urteil_warn"] = _urteil(vh["stufe"] in ("merkmale", "richtung_trocken"), w)
        taeler[pid] = e
    URTEILE.mkdir(parents=True, exist_ok=True)
    (URTEILE / f"{day.isoformat()}.json").write_text(json.dumps(
        {"_meta": {"datum": day.isoformat(), "regel": REGEL, "modell": tal.get("model"),
                   "erstellt": datetime.datetime.now().isoformat(timespec="seconds")},
         "taeler": taeler}, ensure_ascii=False, indent=1), encoding="utf-8")
    n_ok = sum(1 for e in taeler.values() if e["urteil_voll"] != "keine_messung")
    print(f"[foehn] {day}: {n_ok}/{len(taeler)} Täler mit Messung")
    return n_ok > 0


def rebuild_scoreboard() -> dict:
    sb = {"tage": [], "stufen": {s: {} for s in ("voll", "warn")}, "verpasst": []}
    for f in sorted(URTEILE.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        day = d["_meta"]["datum"]
        sb["tage"].append(day)
        for pid, e in d["taeler"].items():
            for s in ("voll", "warn"):
                u = e.get(f"urteil_{s}")
                row = sb["stufen"][s].setdefault(e["tal"], {})
                row[u] = row.get(u, 0) + 1
            if e.get("urteil_warn") == "verpasst":
                sb["verpasst"].append({"datum": day, "tal": e["tal"], "foehn_std": e.get("foehn_std"),
                                       "vorhersage": e.get("stufe")})
    (DOM / "scoreboard_daily.json").write_text(json.dumps(sb, ensure_ascii=False, indent=1), encoding="utf-8")
    return sb


def write_report(sb: dict) -> None:
    def tot(s, u):
        return sum(r.get(u, 0) for r in sb["stufen"][s].values())
    lines = ["# Föhn-Validierung täglich — AUTO_REPORT (nicht von Hand editieren)", "",
             f"Tage: {len(sb['tage'])} ({sb['tage'][0] if sb['tage'] else '–'} bis {sb['tage'][-1] if sb['tage'] else '–'}) · "
             f"Regel: {REGEL}", "",
             "Wahrheit: MeteoSchweiz-Föhnindex am Talboden. „Fehlalarm“ heisst: kein Föhn **am Talboden** "
             "im Flugfenster — Föhn über einem Kaltluftsee zählt dort nicht (README, Grenze 1).", "",
             "| Stufe | Treffer | verpasst | Fehlalarm | still | Mischluft | keine Messung |",
             "|---|---|---|---|---|---|---|"]
    for s, name in (("voll", "alle drei Merkmale"), ("warn", "Merkmale oder Richtung+trocken")):
        lines.append(f"| {name} | {tot(s, 'treffer')} | {tot(s, 'verpasst')} | {tot(s, 'fehlalarm')} | "
                     f"{tot(s, 'still')} | {tot(s, 'mischluft')} | {tot(s, 'keine_messung')} |")
    lines += ["", "## Verpasst (Stufe warn) — Föhn am Talboden, Briefing ohne Merkmal", ""]
    if sb["verpasst"]:
        lines += ["| Datum | Tal | Föhnstunden | Briefing |", "|---|---|---|---|"]
        lines += [f"| {v['datum']} | {v['tal']} | {', '.join(str(h) for h in v['foehn_std'] or [])} | {v['vorhersage']} |"
                  for v in sb["verpasst"][-30:]]
    else:
        lines.append("keine")
    lines += ["", "## Je Tal (Stufe warn)", "", "| Tal | Treffer | verpasst | Fehlalarm | still | Mischluft |",
              "|---|---|---|---|---|---|"]
    for tal, r in sorted(sb["stufen"]["warn"].items()):
        lines.append(f"| {tal} | {r.get('treffer', 0)} | {r.get('verpasst', 0)} | {r.get('fehlalarm', 0)} | "
                     f"{r.get('still', 0)} | {r.get('mischluft', 0)} |")
    (DOM / "AUTO_REPORT_DAILY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--backfill", nargs=2)
    a = ap.parse_args()
    if a.backfill:
        d0, d1 = (datetime.date.fromisoformat(x) for x in a.backfill)
        days = [d0 + datetime.timedelta(days=k) for k in range((d1 - d0).days + 1)]
    elif a.date:
        days = [datetime.date.fromisoformat(a.date)]
    else:
        days = [letzter_vollstaendiger_tag(datetime.datetime.now())]
    for d in days:
        validate_day(d)
    write_report(rebuild_scoreboard())
    return 0


if __name__ == "__main__":
    sys.exit(main())
