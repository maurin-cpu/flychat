# -*- coding: utf-8 -*-
"""Täglicher Gewitter-Abgleich: Warnung (eingefrorener Lauf) gegen Messung (SMN).

Läuft morgens für den VORTAG (Scheduler) oder per Hand:
    python scripts/validate_gewitter_daily.py                  # gestern
    python scripts/validate_gewitter_daily.py --date 2026-08-02
    python scripts/validate_gewitter_daily.py --backfill 2026-07-31 2026-08-02

Je Tag entstehen:
    validation/gewitter/messwerte/YYYY-MM-DD.json   (SMN, archiviert)
    validation/gewitter/urteile/YYYY-MM-DD.json     (Prognose × Messung)
und daraus fortgeschrieben:
    validation/gewitter/scoreboard.json             (alle Schwellen parallel)
    validation/gewitter/AUTO_REPORT.md

Prognose-Quelle ist der zentrale Freeze `data/weather_archive/YYYY-MM-DD.json`
(Regel 1 in validation/README.md). Fehlt er für einen Tag, wird der Tag mit
Warnung übersprungen — es gibt nichts Ehrliches nachzurechnen.

Die Warnstunden werden mit der AKTUELLEN Anzeige-Regel nachgerechnet
(`ensemble_thunder.is_ensemble_storm_hour` — dieselbe Funktion wie die App,
eine Quelle der Wahrheit). Das Scoreboard eicht also die heutige Regel;
welche Regel galt, steht je Urteil im `_meta.regel`.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config                                        # noqa: E402
from ensemble_thunder import thunder_anchor_ok        # noqa: E402
from scripts import validation_common as vc           # noqa: E402

DOM = vc.ROOT / "validation" / "gewitter"
ARCHIVE = vc.ROOT / "data" / "weather_archive"

REGEL = "ensemble>=SCHWELLE% je Stunde + Anker Regen-Pflicht (03.08.2026)"
SCHWELLEN = (40, 50, 60)          # 40 = Live-Schwelle, Rest fuer die Eichung
FENSTER = {"flug": (10, 18), "abend": (18, 24)}


def _load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _dump_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def build_messwerte(day: datetime.date, stations: list[dict]) -> dict | None:
    """SMN-Stundenwerte + Regions-Ereignisse fuer einen Tag holen/ableiten."""
    out_path = DOM / "messwerte" / f"{day.isoformat()}.json"
    cached = _load_json(out_path)
    if cached:
        return cached
    stunden_by_station, meta_by_abbr = {}, {}
    for i, s in enumerate(stations, 1):
        stunden = vc.smn_station_day(s["abbr"], day)
        if stunden:
            stunden_by_station[s["abbr"]] = stunden
            meta_by_abbr[s["abbr"]] = s
        if i % 40 == 0:
            print(f"  SMN {i}/{len(stations)} ...", flush=True)
    if not stunden_by_station:
        return None
    regionen = vc.region_events(stunden_by_station, meta_by_abbr)
    doc = {
        "_meta": {"tag": day.isoformat(), "stationen": len(stunden_by_station),
                  "quelle": "MeteoSchweiz OGD SMN, Zehnminutenwerte (t_recent)",
                  "signatur": f"gewitter: regen>={vc.STORM_RAIN_MM30}mm/30min & "
                              f"(boee>={vc.STORM_GUST_JUMP_KMH}km/h | "
                              f"dT<={vc.STORM_TEMP_DROP_K}K je 30min); "
                              f"schauer: regen>={vc.SHOWER_RAIN_MM30}mm/30min; "
                              f"ausfluss (ohne Regen): boee>={vc.OUTFLOW_GUST_JUMP_KMH}"
                              f"km/h & dT<={vc.OUTFLOW_TEMP_DROP_K}K & "
                              f"dP>=+{vc.OUTFLOW_PRES_RISE_HPA}hPa"},
        "stationen": {a: {**meta_by_abbr[a],
                          "stunden": {str(h): v for h, v in st.items()}}
                      for a, st in stunden_by_station.items()},
        "regionen": regionen,
    }
    _dump_json(out_path, doc)
    return doc


def warn_hours_from_snapshot(region_snap: dict, schwelle: int) -> list[str]:
    """Blitz-Stunden einer Region aus dem eingefrorenen Lauf nachrechnen —
    stündlicher Member-Anteil >= schwelle UND Anker, wie in der App."""
    ens = region_snap.get("thunder_ensemble") or {}
    shares = ens.get("hourly_share_pct") or {}
    hourly = region_snap.get("hourly_flight") or {}
    out = []
    for hh, share in sorted(shares.items()):
        if not isinstance(share, (int, float)) or share < schwelle:
            continue
        if thunder_anchor_ok(hourly.get(hh) or {}):
            out.append(hh)
    return out


def validate_day(day: datetime.date, stations: list[dict]) -> dict | None:
    snap = _load_json(ARCHIVE / f"{day.isoformat()}.json")
    if not snap or not snap.get("regions"):
        print(f"  !! kein Prognose-Freeze fuer {day} ({ARCHIVE}) — Tag uebersprungen")
        return None
    mess = build_messwerte(day, stations)
    if not mess:
        print(f"  !! keine SMN-Daten fuer {day} — Tag uebersprungen")
        return None

    urteile = []
    for rid, rsnap in snap["regions"].items():
        rname = rsnap.get("region_name") or rid
        ereignisse = mess["regionen"].get(rname) or {}
        warn = {s: warn_hours_from_snapshot(rsnap, s) for s in SCHWELLEN}
        for fname, (h0, h1) in FENSTER.items():
            gemessen = [e[0] for e in ereignisse.get("gewitter", [])
                        if h0 <= int(str(e[0])[:2]) < h1]
            eintrag = {"region": rname, "fenster": fname,
                       "gemessen": sorted(gemessen),
                       "schauer": sorted(e[0] for e in ereignisse.get("schauer", [])
                                         if h0 <= int(str(e[0])[:2]) < h1),
                       # Nur gespeichert, nie angezeigt, aendert kein Urteil:
                       # Kaltluft-Ausfluss ohne Regen = moeglicher blinder
                       # Fleck der Gewitter-Signatur (validation_common).
                       "ausfluss": sorted(e[0] for e in ereignisse.get("ausfluss", [])
                                          if h0 <= int(str(e[0])[:2]) < h1),
                       "sonne_1218_pct": ereignisse.get("sonne_1218_pct")}
            for s in SCHWELLEN:
                w = [hh for hh in warn[s] if h0 <= int(hh[:2]) < h1]
                urteil, dt = vc.judge(w, gemessen)
                eintrag[f"schwelle_{s}"] = {"angezeigt": w, "urteil": urteil,
                                            "dt_h": dt}
            urteile.append(eintrag)

    doc = {"_meta": {"tag": day.isoformat(), "regel": REGEL,
                     "prognose_quelle": f"data/weather_archive/{day.isoformat()}.json"},
           "urteile": urteile}
    _dump_json(DOM / "urteile" / f"{day.isoformat()}.json", doc)
    return doc


def rebuild_scoreboard() -> dict:
    """Scoreboard komplett aus den Urteils-Dateien neu rechnen (idempotent)."""
    board = {"_meta": {"regel": REGEL, "tage": 0, "von": None, "bis": None}}
    for f in (("flug",), ("abend",)):
        board[f[0]] = {f"schwelle_{s}": dict.fromkeys(vc.VERDICTS, 0)
                       for s in SCHWELLEN}
    files = sorted((DOM / "urteile").glob("*.json"))
    for p in files:
        doc = _load_json(p)
        if not doc:
            continue
        board["_meta"]["tage"] += 1
        board["_meta"]["von"] = board["_meta"]["von"] or doc["_meta"]["tag"]
        board["_meta"]["bis"] = doc["_meta"]["tag"]
        for u in doc["urteile"]:
            for s in SCHWELLEN:
                v = u.get(f"schwelle_{s}")
                if v:
                    board[u["fenster"]][f"schwelle_{s}"][v["urteil"]] += 1
    _dump_json(DOM / "scoreboard.json", board)
    return board


def write_report(board: dict) -> None:
    m = board["_meta"]
    lines = [
        "# AUTO-REPORT — Gewitter-Validierung",
        "",
        "> Maschinell erzeugt von `scripts/validate_gewitter_daily.py` — nicht",
        "> von Hand editieren. Grenzen des Richters: `README.md`.",
        "",
        f"**Stand:** {m['von']} bis {m['bis']} · {m['tage']} Tage · Regel: {m['regel']}",
        "",
    ]
    for fname, label in (("flug", "Flugzeit 10–18 Uhr"),
                         ("abend", "Abend 18–24 Uhr")):
        lines += [f"## {label}", "",
                  "| Schwelle | Treffer | Verpasst | Fehlalarm | still | erkannt | Fehlalarmquote |",
                  "|---|---|---|---|---|---|---|"]
        for s in SCHWELLEN:
            c = board[fname][f"schwelle_{s}"]
            hit, miss, fa = c["treffer"], c["verpasst"], c["fehlalarm"]
            pod = f"{100 * hit / (hit + miss):.0f} %" if hit + miss else "—"
            far = f"{100 * fa / (hit + fa):.0f} %" if hit + fa else "—"
            live = " ← live" if s == config.ENSEMBLE_THUNDER_METEOGRAM_PCT else ""
            lines.append(f"| {s} %{live} | {hit} | {miss} | {fa} | {c['still']} "
                         f"| {pod} | {far} |")
        lines.append("")
    lines += ["*Gewitter sind selten (Saison-Basisrate ~5 % der Regionstage im",
              "Flugfenster) — belastbare Quoten brauchen mehrere Wochen.*", ""]
    (DOM / "AUTO_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (Default: gestern)")
    ap.add_argument("--backfill", nargs=2, metavar=("VON", "BIS"),
                    help="Datumsbereich nachholen")
    args = ap.parse_args()

    if args.backfill:
        d0 = datetime.date.fromisoformat(args.backfill[0])
        d1 = datetime.date.fromisoformat(args.backfill[1])
        days = [d0 + datetime.timedelta(days=i) for i in range((d1 - d0).days + 1)]
    else:
        days = [datetime.date.fromisoformat(args.date) if args.date
                else datetime.date.today() - datetime.timedelta(days=1)]

    print(f"Gewitter-Validierung: {len(days)} Tag(e)")
    stations = vc.smn_stations_by_region()
    print(f"  {len(stations)} SMN-Stationen mit Region")
    done = 0
    for day in days:
        print(f"== {day} ==", flush=True)
        if validate_day(day, stations):
            done += 1
    if done:
        board = rebuild_scoreboard()
        write_report(board)
        print(f"Scoreboard: {board['_meta']['tage']} Tage · Report aktualisiert")
    return 0 if done or not days else 1


if __name__ == "__main__":
    raise SystemExit(main())
