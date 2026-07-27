"""Erzeugt observations.csv-Zeilen aus der Starkflug-Tabelle + weather_archive.

Konvention siehe xcontest_validation/README.md + SCHEMA.md: eine Zeile pro
Spot+Tag, XContest-Seite aus dem Paste, `our_*` aus
weather_archive[day].spots[spot].analysis, `wx_*` aus daily_aggregates.

Quelle der XContest-Seite hier: _raw/strong_flights_*.tsv (pro Tag+Startplatz der
beste Gleitschirmflug ab 60 km). Daraus folgen zwei dokumentierte Luecken
gegenueber handgepflegten Zeilen:
  * `launches` bleibt leer — die Tabelle haelt pro Startplatz nur den besten Flug,
    nicht die Flugzahl.
  * `top_start_time` bleibt leer (nicht erfasst), `top_airtime` ist gesetzt.

`finding_type` wird konservativ automatisch gesetzt:
  coverage_gap            Startplatz nicht in unserer DB
  false_positive_notsafe  our_status == not_safe, real geflogen
  underrated_region       Region lag im unteren Drittel unseres Steigen-Rankings
  confirm                 sonst
Jede Zeile tragt in `notes` den Vermerk `auto_from_strong_flights`, damit
handgepflegte und generierte Zeilen unterscheidbar bleiben.

Aufruf:
  python scripts/build_observations_from_strong.py            # Vorschau (stdout)
  python scripts/build_observations_from_strong.py --append    # an observations.csv anhaengen
"""
from __future__ import annotations

import argparse
import csv
import glob
import importlib.util
import json
import shutil
import statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "data" / "weather_archive"
VAL = ROOT / "xcontest_validation"
OBS = VAL / "observations.csv"

_spec = importlib.util.spec_from_file_location("v", ROOT / "scripts" / "validate_climb_onesided.py")
V = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V)


def spot_index_full():
    """normalisierter Spotname -> echter Spotname (jüngster Archivtag)."""
    files = sorted(glob.glob(str(ARCHIVE / "*.json")))
    spots = json.load(open(files[-1], encoding="utf-8"))["spots"]
    return {V.norm(n): n for n in spots}


def match_spot(launch: str, sidx) -> str | None:
    key = V.norm(launch)
    if not key or key == "?" or key in V.AMBIGUOUS:
        return None
    for alias, target in V.ALIASES.items():
        if key.startswith(alias) and V.norm(target) in sidx:
            return sidx[V.norm(target)]
    if key in sidx:
        return sidx[key]
    for pred in (lambda k: k.startswith(key), lambda k: key.startswith(k) and len(k) >= 5):
        cands = {v for k, v in sidx.items() if pred(k)}
        if len(cands) == 1:
            return cands.pop()
    return None


def pipe(v):
    if not v:
        return ""
    if isinstance(v, (list, tuple)):
        return "|".join(str(x) for x in v)
    return str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--append", action="store_true", help="an observations.csv anhaengen")
    args = ap.parse_args()

    sidx = spot_index_full()
    header = next(csv.reader(open(OBS, encoding="utf-8", errors="replace")))
    out_rows, stats = [], defaultdict(int)

    for path in sorted(glob.glob(str(VAL / "_raw" / "strong_flights_*.tsv"))):
        for r in csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"):
            day, launch = r["date"], r["launch"]
            af = ARCHIVE / f"{day}.json"
            if not af.exists():
                stats["kein_archiv"] += 1
                continue
            arch = json.load(open(af, encoding="utf-8"))["spots"]
            spot = match_spot(launch, sidx)
            row = {k: "" for k in header}
            row.update(date=day, spot=spot or launch, best_km=r["km"],
                       top_airtime=r.get("airtime", ""))

            if spot is None or spot not in arch:
                row["finding_type"] = "coverage_gap"
                row["notes"] = (f"auto_from_strong_flights; Startplatz '{launch}' nicht in "
                                f"fluggebiete_dhv.csv oder mehrdeutig")
                stats["coverage_gap"] += 1
                out_rows.append(row)
                continue

            v = arch[spot]
            da, an = v["daily_aggregates"], (v.get("analysis") or {})
            row["region"] = v.get("analyse_region") or ""
            for src, dst in (("climb_rate_max_ms", "wx_climb_rate_max_ms"),
                             ("max_thermal_height_max_m", "wx_max_thermal_height_m"),
                             ("blh_max_m", "wx_blh_max_m"),
                             ("wind_gust_max_kmh", "wx_wind_gust_max_kmh"),
                             ("wind_dir_dominant_deg", "wx_wind_dir_dominant_deg"),
                             ("t2m_max", "wx_t2m_max"), ("precip_sum_mm", "wx_precip_sum_mm"),
                             ("cloud_low_mean_pct", "wx_cloud_low_mean_pct"),
                             ("cape_max", "wx_cape_max"),
                             ("lifted_index_min", "wx_lifted_index_min"),
                             ("productive_thermal_h", "wx_productive_thermal_h")):
                if da.get(src) is not None:
                    row[dst] = da[src]

            note = ["auto_from_strong_flights"]
            if an:
                row["our_safety_rating"] = an.get("rating", "")
                row["our_experience_rating"] = an.get("experience_rating", "")
                row["our_xc_rating"] = an.get("experience_rating", "")
                row["our_status"] = an.get("status", "")
                row["our_streckenflug_tier"] = an.get("streckenflug_tier", "")
                row["our_streckenflug_limiting_factor"] = an.get("streckenflug_limiting_factor", "")
                row["no_go_reasons"] = pipe(an.get("no_go_reasons"))
            else:
                note.append("Archiv-Snapshot ohne analysis-Block -> our_* leer")

            rk = V.day_ranking(day, "climb_rate_max_ms", False)
            pct = rk.get(V.norm(row["region"])) if rk else None
            if pct is not None:
                note.append(f"Region-Perzentil unseres Steigen-Rankings: {pct:.0f}%")

            if row["our_status"] == "not_safe":
                row["finding_type"] = "false_positive_notsafe"
            elif pct is not None and pct > 66.7:
                row["finding_type"] = "underrated_region"
            else:
                row["finding_type"] = "confirm"
            stats[row["finding_type"]] += 1
            row["notes"] = "; ".join(note)
            out_rows.append(row)

    print(f"Zeilen erzeugt: {len(out_rows)}")
    for k, c in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {k:24} {c}")

    if args.append:
        shutil.copy(OBS, OBS.with_suffix(".csv.bak_before_auto"))
        with open(OBS, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=header)
            for row in out_rows:
                w.writerow(row)
        print(f"\nAngehaengt an {OBS.name} (Backup: {OBS.name}.bak_before_auto)")
    else:
        print("\n(Vorschau — mit --append schreiben)")
        for row in out_rows[:3]:
            print({k: v for k, v in row.items() if v})


if __name__ == "__main__":
    main()
