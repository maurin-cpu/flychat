"""MACHBARKEITS-TEST: Lassen sich Fronten aus dem Modellraster ableiten?

Kein Produktivcode — dieses Skript beantwortet EINE Frage, bevor ein Plan
geschrieben wird: Reicht das, was wir per Open-Meteo holen koennen, fuer eine
Frontenanalyse, die neben einer handanalysierten DWD-Bodenkarte bestehen kann?

Verfahren (Literatur-Standard):
  1. 850-hPa-Temperatur + relative Feuchte auf ein regelmaessiges Europa-Raster
     holen (feiner als das Synoptik-Raster: dessen 2.5 x 3.5 Grad ~ 275 km
     koennen eine 50-200 km breite Frontalzone gar nicht aufloesen).
  2. Daraus die aequivalentpotentielle Temperatur Theta-e rechnen (Bolton 1980).
     Theta-e ist die uebliche Frontengroesse — sie fasst Temperatur UND Feuchte,
     und genau der Feuchtesprung macht viele Fronten aus.
  3. Thermal Front Parameter:  TFP = -grad(|grad Theta-e|) . (grad Theta-e / |grad Theta-e|)
     Die Frontlinie liegt auf der Achse des staerksten Gradienten, also dort, wo
     TFP entlang der Gradientenrichtung durch null geht (Hewson 1998).
  4. Warm/Kalt aus der Advektion: adv = -(u,v) . grad Theta-e. Positiv heisst
     Warmluftadvektion (Warmfront), negativ Kaltluftadvektion (Kaltfront).

Ausgabe: PNG je Zeitschritt (Theta-e-Feld + Frontkandidaten) plus Kennzahlen
zur Gradientenstaerke. Der Abgleich gegen echte DWD-Karten passiert per Auge.

Run:  python scripts/experiment_fronten_tfp.py --start 2026-07-20 --end 2026-07-26
      python scripts/experiment_fronten_tfp.py --res 1.5   (grobes Raster testen)
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config_overrides  # noqa: E402
config_overrides.init()

import config  # noqa: E402

OUT_DIR = ROOT / "data" / "_experiment_fronten"

# Europa-Fenster des Briefing-Ausschnitts, grosszuegig erweitert: eine Front,
# die gleich hinter dem Bildrand liegt, muss zur Kontrolle mitgerechnet werden.
LAT_MIN, LAT_MAX = 34.0, 66.0
LON_MIN, LON_MAX = -20.0, 32.0

CHUNK = 90          # Punkte pro Open-Meteo-Call (wie synoptic_grid)
P_LEVEL = 850.0     # hPa


# ============================================================================
# Fetch
# ============================================================================

def build_grid(res: float):
    lats = np.arange(LAT_MIN, LAT_MAX + 1e-9, res)
    lons = np.arange(LON_MIN, LON_MAX + 1e-9, res)
    return lats, lons


def fetch_fields(lats, lons, start: str, end: str, hours: list) -> dict:
    """Holt T850/RH850/Wind850 fuer alle Rasterpunkte.

    Returns {timestep: {"t": 2D, "rh": 2D, "u": 2D, "v": 2D}} in Grad C / % / m/s.
    """
    points = [(float(la), float(lo)) for la in lats for lo in lons]
    ny, nx = len(lats), len(lons)
    print(f"Raster {ny} x {nx} = {len(points)} Punkte, "
          f"{math.ceil(len(points)/CHUNK)} Calls")

    wanted = [f"{d}T{h:02d}:00" for d in _daterange(start, end) for h in hours]
    out = {ts: {k: np.full((ny, nx), np.nan) for k in ("t", "rh", "u", "v", "pr")}
           for ts in wanted}

    for c0 in range(0, len(points), CHUNK):
        chunk = points[c0:c0 + CHUNK]
        params = {
            "latitude": ",".join(str(la) for la, _ in chunk),
            "longitude": ",".join(str(lo) for _, lo in chunk),
            "hourly": ("temperature_850hPa,relative_humidity_850hPa,"
                       "wind_speed_850hPa,wind_direction_850hPa,precipitation"),
            "models": "ecmwf_ifs025",
            "start_date": start,
            "end_date": end,
            "timezone": config.TIMEZONE,
        }
        params = config.with_api_key(params)
        r = requests.get(config.API_URL, params=params, timeout=config.API_TIMEOUT)
        r.raise_for_status()
        payload = r.json()
        if isinstance(payload, dict):
            payload = [payload]
        if len(payload) != len(chunk):
            raise RuntimeError(f"Chunk {c0//CHUNK}: {len(payload)} statt {len(chunk)}")

        for k, loc in enumerate(payload):
            idx = c0 + k
            j, i = divmod(idx, nx)
            h = loc.get("hourly") or {}
            tindex = {t: n for n, t in enumerate(h.get("time") or [])}
            for ts in wanted:
                n = tindex.get(ts)
                if n is None:
                    continue
                t = _get(h, "temperature_850hPa", n)
                rh = _get(h, "relative_humidity_850hPa", n)
                sp = _get(h, "wind_speed_850hPa", n)
                dr = _get(h, "wind_direction_850hPa", n)
                pr = _get(h, "precipitation", n)
                out[ts]["t"][j, i] = t if t is not None else np.nan
                out[ts]["rh"][j, i] = rh if rh is not None else np.nan
                out[ts]["pr"][j, i] = pr if pr is not None else np.nan
                if sp is not None and dr is not None:
                    ms = sp / 3.6
                    rad = math.radians(dr)
                    out[ts]["u"][j, i] = -ms * math.sin(rad)
                    out[ts]["v"][j, i] = -ms * math.cos(rad)
        print(f"  Chunk {c0//CHUNK + 1} ok")
    return out


def _get(hourly, key, n):
    arr = hourly.get(key) or []
    return arr[n] if n < len(arr) else None


def _daterange(start: str, end: str):
    from datetime import date, timedelta
    y0, m0, d0 = (int(x) for x in start.split("-"))
    y1, m1, d1 = (int(x) for x in end.split("-"))
    cur, last = date(y0, m0, d0), date(y1, m1, d1)
    while cur <= last:
        yield cur.isoformat()
        cur += timedelta(days=1)


# ============================================================================
# Meteorologie
# ============================================================================

def theta_e(t_c: np.ndarray, rh: np.ndarray, p_hpa: float = P_LEVEL) -> np.ndarray:
    """Aequivalentpotentielle Temperatur nach Bolton (1980), Gl. 15/38/39."""
    t_k = t_c + 273.15
    es = 6.112 * np.exp(17.67 * t_c / (t_c + 243.5))        # hPa
    e = np.clip(rh, 1e-3, 100.0) / 100.0 * es
    r = 0.622 * e / (p_hpa - e)                              # kg/kg
    # Temperatur am Hebungskondensationsniveau
    t_lcl = 2840.0 / (3.5 * np.log(t_k) - np.log(np.maximum(e, 1e-6)) - 4.805) + 55.0
    theta = t_k * (1000.0 / p_hpa) ** (0.2854 * (1.0 - 0.28 * r))
    return theta * np.exp((3.376 / t_lcl - 0.00254) * r * 1000.0 * (1.0 + 0.81 * r))


def theta_w(te: np.ndarray) -> np.ndarray:
    """Feuchttemperatur-Potential Theta-w aus Theta-e (Davies-Jones 2008, 3.8).

    Die Literatur rechnet Frontendetektion auf Theta-w, nicht Theta-e. Beide
    sind monoton verknuepft, aber die Umrechnung ist nichtlinear: sie staucht
    das warme Ende und veraendert damit die Gradientenbetraege — und die
    entscheiden ueber die Schwellen.
    """
    a = (7.101574, -20.68208, 16.11182, 2.574631, -5.205688)
    b = (-3.552497, 3.781782, -0.6899655, -0.5929340)
    x = te / 273.15
    num = a[0] + a[1]*x + a[2]*x**2 + a[3]*x**3 + a[4]*x**4
    den = 1.0 + b[0]*x + b[1]*x**2 + b[2]*x**3 + b[3]*x**4
    out = te - np.exp(np.clip(num / den, -50, 50))
    return np.where(te > 173.15, out, te)


def smooth_5point(field: np.ndarray, passes: int) -> np.ndarray:
    """n Durchgaenge eines 5-Punkt-Mittels (Zentrum + 4 Nachbarn).

    Das ist die Glaettung des Literatur-Verfahrens — acht Durchgaenge bei
    0.75 Grad. Ohne sie erzeugt jedes Rauschen im Temperaturfeld eigene
    Nulldurchgaenge, und die Linien zerfallen in Fragmente.
    """
    f = np.array(field, dtype=float)
    for _ in range(passes):
        p = np.pad(f, 1, mode="edge")
        f = (p[1:-1, 1:-1] + p[:-2, 1:-1] + p[2:, 1:-1]
             + p[1:-1, :-2] + p[1:-1, 2:]) / 5.0
    return f


def gradients_si(field: np.ndarray, lats: np.ndarray, lons: np.ndarray):
    """d/dx, d/dy in Einheit pro METER (fuer den Vergleich mit den
    publizierten Schwellen, die in K/m bzw. K/m^2 angegeben sind)."""
    dlat_m = 111200.0 * (lats[1] - lats[0])
    coslat = np.cos(np.radians(lats))[:, None]
    dlon_m = 111200.0 * (lons[1] - lons[0]) * coslat
    dfdy, dfdx = np.gradient(field)
    return dfdx / dlon_m, dfdy / dlat_m


def gradients(field: np.ndarray, lats: np.ndarray, lons: np.ndarray):
    """d/dx, d/dy in Einheit pro 100 km (Kugel, lokal kartesisch)."""
    gx, gy = gradients_si(field, lats, lons)
    return gx * 1e5, gy * 1e5


def smooth(field: np.ndarray, sigma: float) -> np.ndarray:
    from scipy.ndimage import gaussian_filter
    m = np.isnan(field)
    filled = np.where(m, np.nanmean(field), field)
    return gaussian_filter(filled, sigma=sigma)


def front_diagnostics(te: np.ndarray, u: np.ndarray, v: np.ndarray,
                      lats, lons, sigma: float):
    """Liefert (Theta-e geglaettet, Gradientbetrag, TFP, Advektion)."""
    tes = smooth(te, sigma)
    gx, gy = gradients(tes, lats, lons)
    g = np.hypot(gx, gy)                      # K / 100 km
    gs = smooth(g, sigma)
    ggx, ggy = gradients(gs, lats, lons)
    with np.errstate(invalid="ignore", divide="ignore"):
        nx_ = gx / np.where(g > 1e-6, g, np.nan)
        ny_ = gy / np.where(g > 1e-6, g, np.nan)
    tfp = -(ggx * nx_ + ggy * ny_)            # K / (100 km)^2
    adv = -(u * gx + v * gy)                  # K/100km * m/s (Vorzeichen zaehlt)
    return tes, g, tfp, adv


# ============================================================================
# Plot
# ============================================================================

def hewson_fronts(t_c, rh, u, v, lats, lons, passes=8,
                  tfp_pct=75.0, grad_pct=50.0, min_len_km=250.0):
    """Frontendetektion nach Literatur-Standard (Hewson 1998 / Sansom & Catto 2024).

    Unterschiede zur ersten Fassung (`front_diagnostics` + `front_mask`), die
    alle fuenf aus der Recherche stammen:

    1. Theta-w statt Theta-e
    2. 8 Durchgaenge 5-Punkt-Mittel statt einem Gauss
    3. Die Linie liegt auf dem TFP-MAXIMUM am warmen Rand der Frontalzone,
       nicht auf der Gradientenachse. Das entspricht der Handanalyse: der
       Meteorologe zeichnet die Front an die warme Kante, nicht in die Mitte.
       Ortsbestimmung = Nulldurchgang des Lokators L = grad(TFP) . n.
    4. Schwellen als Perzentile statt geraten; die Gradientenbedingung wird
       eine halbe Gitterweite Richtung Kaltluft geprueft ("adjacent
       baroclinic zone") — die Front braucht die kraeftige Zone NEBEN sich.
    5. Linien unter `min_len_km` werden verworfen.

    Returns (tw_smooth, g_si, tfp, mask, speed) — Betraege in SI (K/m, K/m^2).
    """
    from scipy.ndimage import label

    tw = smooth_5point(theta_w(theta_e(t_c, rh)), passes)
    gx, gy = gradients_si(tw, lats, lons)
    g = np.hypot(gx, gy)
    with np.errstate(invalid="ignore", divide="ignore"):
        nx_, ny_ = gx / g, gy / g          # Einheitsvektor Richtung Warmluft

    ggx, ggy = gradients_si(g, lats, lons)
    tfp = -(ggx * nx_ + ggy * ny_)         # > 0 auf der warmen Flanke

    lx, ly = gradients_si(tfp, lats, lons)
    loc = lx * nx_ + ly * ny_              # Lokator: 0 im TFP-Maximum

    # Adjacent Baroclinic Zone: Gradient eine halbe Zelle Richtung Kaltluft
    g_abz = _shift_along(g, -nx_, -ny_)

    tfp_min = np.nanpercentile(tfp, tfp_pct)
    g_min = np.nanpercentile(g_abz, grad_pct)

    s = np.sign(np.nan_to_num(loc))
    z = np.zeros(loc.shape, dtype=bool)
    z[:, :-1] |= (s[:, :-1] * s[:, 1:] < 0)
    z[:-1, :] |= (s[:-1, :] * s[1:, :] < 0)
    mask = z & (tfp >= tfp_min) & (g_abz >= g_min)

    # Kurze Bruchstuecke verwerfen — der Standard zieht bei 250 km die Grenze
    lab, n = label(mask, structure=np.ones((3, 3)))
    for k in range(1, n + 1):
        idx = np.argwhere(lab == k)
        if _extent_km(idx, lats, lons) < min_len_km:
            mask[lab == k] = False

    # Frontgeschwindigkeit (Hewson Gl. 13): Windkomponente entlang grad(|grad|)
    gg = np.hypot(ggx, ggy)
    with np.errstate(invalid="ignore", divide="ignore"):
        speed = (u * ggx + v * ggy) / gg
    return tw, g, tfp, mask, speed


def _shift_along(field, dx, dy):
    """Feld eine halbe Zelle in Richtung (dx, dy) abgetastet (bilinear)."""
    ny, nx = field.shape
    jj, ii = np.mgrid[0:ny, 0:nx]
    sj = np.clip(jj + 0.5 * np.nan_to_num(dy), 0, ny - 1)
    si = np.clip(ii + 0.5 * np.nan_to_num(dx), 0, nx - 1)
    j0, i0 = np.floor(sj).astype(int), np.floor(si).astype(int)
    j1, i1 = np.minimum(j0 + 1, ny - 1), np.minimum(i0 + 1, nx - 1)
    fj, fi = sj - j0, si - i0
    return ((field[j0, i0] * (1 - fi) + field[j0, i1] * fi) * (1 - fj)
            + (field[j1, i0] * (1 - fi) + field[j1, i1] * fi) * fj)


def _extent_km(idx, lats, lons) -> float:
    """Groesste Punkt-zu-Punkt-Distanz einer Linie (Naeherung ihrer Laenge)."""
    if len(idx) < 2:
        return 0.0
    la = np.radians(lats[idx[:, 0]])
    lo = np.radians(lons[idx[:, 1]])
    x, y, z = np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)
    p = np.stack([x, y, z], axis=1)
    d = p @ p.T
    return float(6371.0 * np.arccos(np.clip(d.min(), -1, 1)))


def front_mask(tfp: np.ndarray, g: np.ndarray, g_min: float) -> np.ndarray:
    """Zellen auf der Frontlinie: Nulldurchgang des TFP, wo der Gradient
    stark genug ist. Das ist die Achse des staerksten Theta-e-Gefaelles."""
    s = np.sign(np.nan_to_num(tfp))
    z = np.zeros(tfp.shape, dtype=bool)
    z[:, :-1] |= (s[:, :-1] * s[:, 1:] < 0)
    z[:-1, :] |= (s[:-1, :] * s[1:, :] < 0)
    return z & (g >= g_min)


def precip_check(mask: np.ndarray, pr: np.ndarray, thr: float = 0.1) -> dict:
    """Gegenprobe ohne Fremdkarte: eine echte Front fuehrt ein Niederschlags-
    band mit sich. Trifft die Linie oefter Niederschlag als der Durchschnitt,
    markiert sie etwas Reales — sonst ist sie Rauschen im Temperaturfeld.
    Verglichen wird gegen die Grundrate desselben Feldes (Basisrate)."""
    wet = np.nan_to_num(pr) >= thr
    valid = ~np.isnan(pr)
    n_front = int(np.sum(mask & valid))
    if not n_front:
        return {"n_front": 0, "hit": None, "base": None, "lift": None}
    hit = float(np.sum(mask & wet) / n_front)
    base = float(np.sum(wet & valid) / max(int(np.sum(valid)), 1))
    return {"n_front": n_front, "hit": hit, "base": base,
            "lift": (hit / base if base > 0 else None)}


def plot_step(ts, tes, g, tfp, adv, lats, lons, g_min, out_path, pr=None,
              front_cells=None, var_label="Theta-e 850 hPa [K]"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 7.5), dpi=110)
    lon2, lat2 = np.meshgrid(lons, lats)

    cf = ax.contourf(lon2, lat2, tes, levels=18, cmap="RdYlBu_r", alpha=0.75)
    plt.colorbar(cf, ax=ax, label=var_label, shrink=0.85)
    ax.contour(lon2, lat2, tes, levels=18, colors="#555", linewidths=0.4, alpha=0.5)

    if front_cells is not None:
        # Hewson: fertige Frontpunkte, klassifiziert ueber die Frontgeschwindigkeit
        # (+/-1.5 m/s -> Warm / Kalt / quasistationaer)
        for sel, col, lbl in ((front_cells & (adv > 1.5), "#cc0000", "Warmfront"),
                              (front_cells & (adv < -1.5), "#0033cc", "Kaltfront"),
                              (front_cells & (np.abs(adv) <= 1.5), "#555555",
                               "quasistationaer")):
            if np.any(sel):
                ax.scatter(lon2[sel], lat2[sel], s=26, c=col, marker="s",
                           edgecolors="none", label=lbl)
        if np.any(front_cells):
            ax.legend(loc="lower left", fontsize=8, framealpha=0.9)
    else:
        # erste Fassung: TFP-Nulldurchgang, maskiert ueber den Gradienten
        mask = g >= g_min
        warm = np.where(mask & (adv > 0), tfp, np.nan)
        cold = np.where(mask & (adv <= 0), tfp, np.nan)
        ax.contour(lon2, lat2, cold, levels=[0.0], colors="#0033cc", linewidths=2.4)
        ax.contour(lon2, lat2, warm, levels=[0.0], colors="#cc0000", linewidths=2.4)

    # Niederschlag als Gegenprobe: die Frontlinie sollte im Regenband liegen
    if pr is not None:
        ax.contourf(lon2, lat2, np.nan_to_num(pr), levels=[0.1, 1.0, 100.0],
                    colors=["#1f7a1f", "#0d4d0d"], alpha=0.22)

    ax.set_title(f"{ts}   Fronten-Kandidaten (blau = Kaltluftadvektion, "
                 f"rot = Warmluftadvektion)\nGradient-Schwelle "
                 f"{g_min:.1f} K/100km   max |grad| = {np.nanmax(g):.1f}")
    ax.set_xlabel("Laenge"); ax.set_ylabel("Breite")
    ax.grid(alpha=0.25, linewidth=0.4)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


# ============================================================================

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-07-20")
    ap.add_argument("--end", default="2026-07-26")
    ap.add_argument("--res", type=float, default=1.0, help="Rasterweite in Grad")
    ap.add_argument("--hours", default="12", help="Stunden lokal, z.B. '0,12'")
    ap.add_argument("--sigma", type=float, default=1.0, help="Glaettung (Zellen)")
    ap.add_argument("--gmin", type=float, default=2.0,
                    help="Mindest-Gradient in K/100km fuer eine Frontlinie")
    ap.add_argument("--cache", action="store_true",
                    help="Rohdaten aus data/_experiment_fronten/raw.npz nutzen")
    ap.add_argument("--method", choices=("naiv", "hewson"), default="naiv",
                    help="naiv = erste Fassung; hewson = Literatur-Standard")
    ap.add_argument("--passes", type=int, default=8,
                    help="Glaettungsdurchgaenge (hewson): 8 bei 0.75 Grad")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lats, lons = build_grid(args.res)
    hours = [int(h) for h in args.hours.split(",")]
    raw_path = OUT_DIR / f"raw_{args.start}_{args.end}_{args.res}.npz"

    if args.cache and raw_path.exists():
        z = np.load(raw_path, allow_pickle=True)
        fields = z["fields"].item()
        print(f"Rohdaten aus Cache: {raw_path.name}")
    else:
        fields = fetch_fields(lats, lons, args.start, args.end, hours)
        np.savez_compressed(raw_path, fields=fields)
        print(f"Rohdaten gespeichert: {raw_path.name}")

    print(f"\n{'Zeitschritt':<20} {'max|grad|':>10} {'P95|grad|':>10} "
          f"{'Front-Zellen':>13} {'Regen auf Linie':>16} {'Basisrate':>10} "
          f"{'Faktor':>7}")
    print("-" * 92)
    summary = []
    for ts in sorted(fields):
        f = fields[ts]
        if np.all(np.isnan(f["t"])):
            continue
        if args.method == "hewson":
            tes, g_si, tfp, mask, adv = hewson_fronts(
                f["t"], f["rh"], f["u"], f["v"], lats, lons, passes=args.passes)
            g = g_si * 1e5          # K/m -> K/100km, nur fuer die Anzeige
        else:
            te = theta_e(f["t"], f["rh"])
            tes, g, tfp, adv = front_diagnostics(te, f["u"], f["v"], lats,
                                                 lons, args.sigma)
            mask = front_mask(tfp, g, args.gmin)
        chk = precip_check(mask, f.get("pr"))
        hit = f"{chk['hit']*100:6.1f} %" if chk["hit"] is not None else "     —"
        base = f"{chk['base']*100:5.1f} %" if chk["base"] is not None else "    —"
        lift = f"{chk['lift']:5.2f}x" if chk["lift"] else "    —"
        print(f"{ts:<20} {np.nanmax(g):10.2f} {np.nanpercentile(g, 95):10.2f} "
              f"{chk['n_front']:13d} {hit:>16} {base:>10} {lift:>7}")
        summary.append({"ts": ts, "max_grad": float(np.nanmax(g)),
                        "p95_grad": float(np.nanpercentile(g, 95)),
                        **chk})
        out = (OUT_DIR /
               f"front_{ts.replace(':', '')}_res{args.res}_{args.method}.png")
        plot_step(ts, tes, g, tfp, adv, lats, lons, args.gmin, out,
                  pr=f.get("pr"),
                  front_cells=mask if args.method == "hewson" else None,
                  var_label=("Theta-w 850 hPa [K]" if args.method == "hewson"
                             else "Theta-e 850 hPa [K]"))

    (OUT_DIR / "summary.json").write_text(
        json.dumps({"res_deg": args.res, "sigma": args.sigma,
                    "gmin_k_per_100km": args.gmin, "steps": summary},
                   indent=2), encoding="utf-8")
    print(f"\nPNGs + summary.json in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
