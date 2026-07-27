"""Trefferqualitaet ueber den Alpen — gemessen an Tagen, an denen dort
ueberhaupt eine Front war.

Warum das noetig wurde: die erste regionale Messung (§1c) lief auf 8 Tagen, an
denen ueber den Alpen Hochdruck herrschte. Der Faktor 0.12 dort war also eine
FEHLALARMRATE, keine Trefferquote — die Frage "sitzt eine echte Front richtig?"
war nie gestellt, weil im Sample keine vorkam.

Dieses Skript trennt die zwei Fragen sauber:
  * RUHIGE Tage -> wie oft zeichnen wir etwas, wo nichts ist? (Fehlalarm)
  * FRONT-Tage  -> wenn dort eine Front liegt, trifft die Linie? (Treffer)

Die Auswahl der Front-Tage ist unabhaengig vom Detektor: sie schaut nur, ob im
Alpenfenster ueberhaupt ein kraeftiger Theta-w-Gradient liegt und ob die
Luftmasse innerhalb von 24 h wechselt. Sonst wuerde der Detektor sich selbst
benoten.

Run:  python scripts/experiment_fronten_alpentage.py
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.experiment_fronten_tfp import (  # noqa: E402
    OUT_DIR, build_grid, fetch_elevation, gradients_si, hewson_fronts,
    hewson_fronts_contour, precip_check, region_masks, smooth_5point,
    terrain_filter, theta_e, theta_w,
)

RAW = "raw_2026-05-01_2026-07-26_0.75.npz"
RES = 0.75

CONFIGS = [
    ("A  Stand 26.07.",      "hewson",  0,     0,   0),
    ("B  A + Gel. 1000",     "hewson",  1000,  0,   0),
    ("E  contour + Jenkner", "hewson2", 0,     60000, 0),
    ("H  E + Gel. 1000",     "hewson2", 1000,  60000, 0),
    ("J  E + Bruecke 1000",  "hewson2", 1000,  60000, 600),
]


def main() -> int:
    lats, lons = build_grid(RES)
    areas = region_masks(lats, lons)
    alp = areas["Alpenraum"]

    path = OUT_DIR / RAW
    if not path.exists():
        raise SystemExit(f"Cache fehlt: {RAW}")
    fields = np.load(path, allow_pickle=True)["fields"].item()

    elev_path = OUT_DIR / f"elev_{RES}.npy"
    elev = (np.load(elev_path) if elev_path.exists()
            else fetch_elevation(lats, lons))

    # --- Front-Tage bestimmen, ohne den Detektor zu fragen ------------------
    day, tw_mean, gmax = [], [], []
    for ts in sorted(fields):
        f = fields[ts]
        if np.all(np.isnan(f["t"])):
            continue
        tw = smooth_5point(theta_w(theta_e(f["t"], f["rh"])), 8)
        gx, gy = gradients_si(tw, lats, lons)
        g = np.hypot(gx, gy) * 1e5           # K / 100 km
        day.append(ts)
        tw_mean.append(float(np.nanmean(tw[alp])))
        gmax.append(float(np.nanpercentile(g[alp], 95)))

    tw_mean, gmax = np.array(tw_mean), np.array(gmax)
    drop = np.zeros_like(tw_mean)
    drop[1:] = tw_mean[:-1] - tw_mean[1:]    # Abkuehlung von gestern auf heute

    g_thr = float(np.percentile(gmax, 75))
    front_day = (gmax >= g_thr) & (drop >= 1.5)
    calm_day = (gmax < np.percentile(gmax, 50)) & (np.abs(drop) < 1.0)

    print(f"{len(day)} Tage 01.05.-26.07.2026, Alpenfenster")
    print(f"Front-Tag = P95-Gradient >= {g_thr:.2f} K/100km UND "
          f"Theta-w-Sturz >= 1.5 K in 24 h")
    print(f"  -> {int(front_day.sum())} Front-Tage, "
          f"{int(calm_day.sum())} ruhige Tage\n")
    print("Front-Tage:", ", ".join(day[k][5:10] for k in np.where(front_day)[0]))
    print()

    # --- Detektor auf beiden Gruppen bewerten ------------------------------
    print(f"{'Konfiguration':<22}{'FRONT-Tage (Treffer)':>28}"
          f"{'RUHIGE Tage (Fehlalarm)':>30}")
    print(f"{'':<22}{'Zellen   Regen   Basis  Faktor':>28}"
          f"{'Zellen  je Tag':>30}")
    print("-" * 80)

    for label, meth, m_elev, area, bridge in CONFIGS:
        acc = {"F": {k: 0 for k in ("n_front", "n_front_wet", "n_valid", "n_wet")},
               "R": {k: 0 for k in ("n_front", "n_front_wet", "n_valid", "n_wet")}}
        for k, ts in enumerate(day):
            if not (front_day[k] or calm_day[k]):
                continue
            f = fields[ts]
            if meth == "hewson2":
                _, _, _, mask, _ = hewson_fronts_contour(
                    f["t"], f["rh"], f["u"], f["v"], lats, lons, passes=8,
                    min_area_km2=area, elev=elev, max_elev_m=m_elev,
                    bridge_km=bridge)
            else:
                _, _, _, mask, _ = hewson_fronts(f["t"], f["rh"], f["u"],
                                                 f["v"], lats, lons, passes=8)
                if m_elev > 0:
                    mask = terrain_filter(mask, elev, lats, lons, m_elev)
            r = precip_check(mask, f["pr"], area=alp)
            tgt = acc["F" if front_day[k] else "R"]
            for key in tgt:
                tgt[key] += r[key]

        a = acc["F"]
        if a["n_front"] and a["n_wet"]:
            hit = a["n_front_wet"] / a["n_front"]
            base = a["n_wet"] / a["n_valid"]
            f_txt = (f"{a['n_front']:>8d}{hit*100:>7.0f} %{base*100:>7.0f} %"
                     f"{hit/base:>7.2f}x")
        else:
            f_txt = f"{a['n_front']:>8d}{'—':>22}"
        r = acc["R"]
        r_txt = f"{r['n_front']:>10d}{r['n_front']/max(int(calm_day.sum()),1):>10.1f}"
        print(f"{label:<22}{f_txt:>28}{r_txt:>30}")

    print("\nFaktor auf FRONT-Tagen > 1 = die Linie sitzt, wo die Front ist.")
    print("Zellen je Tag auf RUHIGEN Tagen = was wir zeichnen, wo nichts ist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
