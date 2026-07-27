"""Vergleich der Frontkonfigurationen, gepoolt ueber alle gecachten Termine.

Beantwortet die Frage, die ein Europa-Mittelwert nicht beantwortet: taugt die
Linie DORT, wo geflogen wird? Der Regen-Faktor wird je Teilfenster aus den
Rohzaehlungen gerechnet — nicht als Mittel der Tagesfaktoren, dafuer sind die
Teilfenster zu duenn besetzt.

Zwei Kontrollen lesen sich gegeneinander:
  * Atlantik = dort sitzen die echten Fronten. Faellt der Faktor, kostet die
    Konfiguration Koennen.
  * Alpenraum = Zielgebiet. Faktor unter 1 heisst: die Linie ist schlechter
    als ein zufaellig gesetzter Punkt.

Run:  python scripts/experiment_fronten_sweep.py
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.experiment_fronten_tfp import (  # noqa: E402
    OUT_DIR, P_LEVEL, REGIONS, build_grid, fetch_elevation, hewson_fronts,
    hewson_fronts_contour, precip_check, region_masks, terrain_filter,
)

RUNS = [("2026-05-01", "2026-05-05"), ("2026-07-24", "2026-07-26")]
RES = 0.75

# (Beschriftung, Verfahren, Niveau hPa, Gelaende m, Jenkner km2, Bruecke km)
# Bruecke 0 = Frontpunkte ueber schlechtem Gelaende verwerfen (Luecke),
# Bruecke > 0 = Position zwischen den verlaesslichen Enden durchziehen.
CONFIGS = [
    ("A  Stand 26.07.",     "hewson",  850,    0,     0,    0),
    ("B  A + Gel. 1000",    "hewson",  850, 1000,     0,    0),
    ("C  contour-then-mask","hewson2", 850,    0,     0,    0),
    ("E  C + Jenkner 60k",  "hewson2", 850,    0, 60000,    0),
    ("H  E + Gel. 1000",    "hewson2", 850, 1000, 60000,    0),
    ("I  E + Br. 1000/400", "hewson2", 850, 1000, 60000,  400),
    ("J  E + Br. 1000/600", "hewson2", 850, 1000, 60000,  600),
    ("K  E + Br. 1500/600", "hewson2", 850, 1500, 60000,  600),
    ("L  E + Br.  800/600", "hewson2", 850,  800, 60000,  600),
]


def load(start: str, end: str, level: float) -> dict:
    tag = "" if level == P_LEVEL else f"_{int(level)}"
    path = OUT_DIR / f"raw_{start}_{end}_{RES}{tag}.npz"
    if not path.exists():
        raise SystemExit(f"Cache fehlt: {path.name}")
    return np.load(path, allow_pickle=True)["fields"].item()


def main() -> int:
    lats, lons = build_grid(RES)
    areas = region_masks(lats, lons)
    names = ["Gesamt"] + list(REGIONS)

    elev_path = OUT_DIR / f"elev_{RES}.npy"
    if elev_path.exists():
        elev = np.load(elev_path)
    else:
        elev = fetch_elevation(lats, lons)
        np.save(elev_path, elev)

    # Detektion je (Verfahren, Niveau, Jenkner-Schwelle) einmal rechnen,
    # danach nur noch den Gelaendefilter drueberlegen
    detected = {}
    for key in sorted({(m, lv, ar, el, br)
                       for _, m, lv, el, ar, br in CONFIGS}):
        meth, level, area, m_elev, bridge = key
        steps = []
        for start, end in RUNS:
            for ts, f in sorted(load(start, end, level).items()):
                if np.all(np.isnan(f["t"])):
                    continue
                if meth == "hewson2":
                    _, _, _, mask, _ = hewson_fronts_contour(
                        f["t"], f["rh"], f["u"], f["v"], lats, lons,
                        passes=8, min_area_km2=area, level=level,
                        elev=elev, max_elev_m=m_elev, bridge_km=bridge)
                else:
                    _, _, _, mask, _ = hewson_fronts(
                        f["t"], f["rh"], f["u"], f["v"], lats, lons,
                        passes=8, level=level)
                steps.append((mask, f["pr"]))
        detected[key] = steps
    print(f"{len(next(iter(detected.values())))} Termine, Raster {RES} Grad, "
          f"Mai + Juli 2026\n")

    print(f"{'Konfiguration':<22}" + "".join(f"{n:>21}" for n in names))
    print(f"{'':<22}" + "".join(f"{'Zellen   Faktor':>21}" for _ in names))
    print("-" * (22 + 21 * len(names)))

    for label, meth, level, thr, area, bridge in CONFIGS:
        acc = {n: {"n_front": 0, "n_front_wet": 0, "n_valid": 0, "n_wet": 0}
               for n in names}
        key = (meth, level, area, thr, bridge)
        raster_filter = (thr > 0 and meth != "hewson2")
        for mask, pr in detected[key]:
            m = (terrain_filter(mask, elev, lats, lons, thr)
                 if raster_filter else mask)
            for n in names:
                r = precip_check(m, pr, area=areas[n])
                for k in acc[n]:
                    acc[n][k] += r[k]
        cells = []
        for n in names:
            a = acc[n]
            if a["n_front"] and a["n_valid"] and a["n_wet"]:
                lift = (a["n_front_wet"] / a["n_front"]) / (a["n_wet"] / a["n_valid"])
                cells.append(f"{a['n_front']:>13d}{lift:>7.2f}x")
            else:
                cells.append(f"{a['n_front']:>13d}{'—':>8}")
        print(f"{label:<22}" + "".join(cells))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
