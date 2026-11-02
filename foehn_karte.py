"""Föhn-Karte (/foehn, Admin): eingefrorene Stundendaten für die Karte.

Der Morgenlauf schreibt sie aus decide_foehn_summary nach data/foehn_karte.json
(server-lokal, gitignored). /api/foehn/karte liest sie. Enthalten ist, was die Seite
zeigt: das Windraster über die Schweiz, Rasterzellen in Föhnrichtung je Stunde, die
Talpunkte mit dem Stundenzustand, Druck und Luvseite an Zürich/Lugano.

Keine eigene Zählregel: Rasterzellen über foehn_indicators.karte_punkt_rot, Täler über
foehn_indicators.talpunkt_stunde — dieselben Funktionen wie das Briefing.
"""

import json
import math
import logging
import os
from datetime import datetime

import config
import foehn_indicators as fi
from engine.synoptic_grid import _winddir_to_uv

logger = logging.getLogger(__name__)

# Druck-/Luvstationen wie fetch_foehn_data (Zürich = Nordseite, Lugano = Südseite)
STATIONEN = {
    "nord": {"name": "Zürich", "lat": 47.37, "lon": 8.55},
    "sued": {"name": "Lugano", "lat": 46.00, "lon": 8.96},
}
ROT_CODE = {"sued": 1, "nord": 2}   # 0 = nicht rot


def _flug(ts: str) -> bool:
    return config.FLIGHT_HOURS_START <= int(ts[11:13]) < config.FLIGHT_HOURS_END


def stunden() -> list:
    """Flugstunden als "HH" (06–17)."""
    return [f"{h:02d}" for h in range(config.FLIGHT_HOURS_START, config.FLIGHT_HOURS_END)]


def build(karte, data, tal_series, dates, kamm=None, hoehen=None) -> dict:
    """Stundendaten der Prognosetage `dates` (nur Flugstunden) aus den Rohdaten des Laufs.

    karte: fi.fetch_wind_karte (Raster), data: fi.fetch_foehn_data (Zürich/Lugano),
    tal_series: wetterdaten._meta.foehn_tal_series (Talpunkte),
    kamm: fi.fetch_kamm_wind (Wind in 700 hPa an den Kammpunkten)."""
    raster = fi.karte_raster()
    tage = set(dates)

    # --- Windraster: u/v (m/s) je Zelle und Stunde, Rot-Code je Zelle ---
    k_time = karte.get("time") or []
    k_idx = {t: i for i, t in enumerate(k_time)}
    k_model = karte.get("model") or []
    punkte = karte.get("punkte") or []
    winds, rot, modell = {}, {}, {}
    for t in k_time:
        if t[:10] not in tage or not _flug(t):
            continue
        i = k_idx[t]
        u_l, v_l, r_l = [], [], []
        for p in punkte:
            h = p.get("hourly") or {}
            w = fi._num(h.get("wind_speed_10m"), i)
            d = fi._num(h.get("wind_direction_10m"), i)
            g = fi._num(h.get("wind_gusts_10m"), i)
            if w is None or d is None:
                u_l.append(None)
                v_l.append(None)
            else:
                u, v = _winddir_to_uv(w, d)
                u_l.append(u)
                v_l.append(v)
            side = fi.karte_punkt_rot(w, d, g) if p.get("region_id") else None
            r_l.append(ROT_CODE.get(side, 0))
        winds[t] = {"u": u_l, "v": v_l}
        rot[t] = r_l
        if i < len(k_model):
            modell[t] = k_model[i]

    # --- Druck und Luvseite an Zürich/Lugano ---
    druck = {}
    for seite in ("nord", "sued"):
        h = (data.get(seite) or {}).get("hourly") or {}
        for i, t in enumerate(h.get("time") or []):
            if t[:10] not in tage or not _flug(t):
                continue
            p = fi._num(h.get("pressure_msl"), i)
            t8 = fi._num(h.get("temperature_800hPa"), i)
            rh = fi._num(h.get("relative_humidity_2m"), i)
            druck.setdefault(t, {})[seite] = {
                "druck": round(p, 1) if p is not None else None,
                "t800": round(t8, 1) if t8 is not None else None,
                "rh": round(rh) if rh is not None else None,
            }
    for t, d in druck.items():
        n, s = d.get("nord", {}).get("druck"), d.get("sued", {}).get("druck")
        d["dp"] = round(s - n, 1) if n is not None and s is not None else None   # Lugano − Zürich

    # --- Talpunkte: Stundenzustand über talpunkt_stunde (eine Regel für Briefing und Karte) ---
    talpunkte, taeler = [], {}
    tt = (tal_series or {}).get("time") or []
    t_idx = {t: i for i, t in enumerate(tt)}
    for pid, pd in ((tal_series or {}).get("punkte") or {}).items():
        m = pd.get("meta") or {}
        talpunkte.append({"id": pid, "tal": m.get("tal"), "gruppe": m.get("gruppe"),
                          "region_id": m.get("region_id"), "lat": m.get("lat"), "lon": m.get("lon")})
        sektor = _sektor(pid, m)
        h = pd.get("hourly") or {}
        for t, i in t_idx.items():
            if t[:10] not in tage or not _flug(t):
                continue
            w = fi._num(h.get("wind_speed_10m"), i)
            g = fi._num(h.get("wind_gusts_10m"), i)
            d = fi._num(h.get("wind_direction_10m"), i)
            rh = fi._num(h.get("relative_humidity_2m"), i)
            if None in (w, g, d, rh):
                continue
            st = fi.talpunkt_stunde(w, g, d, rh, *sektor)
            taeler.setdefault(t, {})[pid] = {
                "wind": round(w), "gust": round(g), "dir": round(d), "rh": round(rh),
                "dir_dry": st["dir_dry"], "strikt": st["strikt"],
            }

    # --- Zeichen je Region und Stunde (0–4) ---
    regionen = _regionen_zeichen(raster, rot, druck, taeler, talpunkte)

    # --- Zeichen je Föhntal und Stunde (0–4): Druck und Luvseite schweizweit, Wind aus der
    # Region des Tals, Talzeichen aus der eigenen Messung ---
    talzeichen = {}
    for t, zeile in regionen.items():
        for tp in talpunkte:
            pid, rid = tp["id"], tp.get("region_id")
            z = zeile.get(rid) if rid else None
            if z is None:
                continue
            werte = (taeler.get(t) or {}).get(pid) or {}
            tal_on = bool(werte.get("dir_dry"))
            tal_lvl = 2 if werte.get("strikt") else 1 if tal_on else 0   # Talwind: schwach / stark
            n = int(z["dp"]) + int(z["luv"]) + int(z["wind"]) + int(tal_on)
            stufen = z["lvl"]["dp"] + z["lvl"]["luv"] + z["lvl"]["wind"] + tal_lvl
            talzeichen.setdefault(t, {})[pid] = {
                "n": n, "s": stufen, "stark": tal_lvl == 2,
                "tal": tal_on, "wind": z["wind"], "dp": z["dp"], "luv": z["luv"]}

    # --- Höhenwind (700 hPa) je Region und Stunde: Vektormittel über die Rasterpunkte ---
    hoehen_region = {}
    per = {}
    for z in hoehen or []:
        idx = {t: i for i, t in enumerate(z.get("time") or [])}
        for t, i in idx.items():
            if t[:10] not in tage or not _flug(t):
                continue
            sp = fi._num(z.get("speed"), i)
            dr = fi._num(z.get("dir"), i)
            if sp is None or dr is None:
                continue
            per.setdefault((t, z["region_id"]), []).append((sp, dr))
    for (t, rid), liste in per.items():
        # Wind weht nach u = -s·sin(dir), v = -s·cos(dir); Mittel der Komponenten, dann zurück
        u = sum(-sp * math.sin(math.radians(dr)) for sp, dr in liste) / len(liste)
        v = sum(-sp * math.cos(math.radians(dr)) for sp, dr in liste) / len(liste)
        hoehen_region.setdefault(t, {})[rid] = {
            "speed": round(math.hypot(u, v)),
            "dir": round(math.degrees(math.atan2(-u, -v)) % 360),
        }

    # --- Kammwind: je Flugstunde die Punkte mit Geschwindigkeit und Richtung (woher) ---
    kammwerte, kamm_punkte = {}, []
    for k in kamm or []:
        kamm_punkte.append({"id": k["id"], "name": k["name"], "lat": k["lat"], "lon": k["lon"]})
        idx = {t: i for i, t in enumerate(k.get("time") or [])}
        for t, i in idx.items():
            if t[:10] not in tage or not _flug(t):
                continue
            sp = fi._num(k.get("speed"), i)
            dr = fi._num(k.get("dir"), i)
            if sp is None or dr is None:
                continue
            kammwerte.setdefault(t, []).append({"id": k["id"], "speed": round(sp), "dir": round(dr)})

    # Föhnrichtungen je Region aus regionen.csv (kritischer_foehn): wer betroffen sein KANN
    richtungen = {}
    for c in raster:
        if c.get("region_id"):
            richtungen[c["region_id"]] = list(c.get("sides") or [])

    return {
        "erzeugt": datetime.now().isoformat(timespec="seconds"),
        "richtungen": richtungen,
        "tage": list(dates),
        "kamm": kammwerte,
        "kamm_punkte": kamm_punkte,
        "regionen": regionen,
        "talzeichen": talzeichen,
        "hoehen": hoehen_region,
        "raster": {
            "meta": dict(fi.KARTE_RASTER),
            "zellen": [[c["lat"], c["lon"], c["region_id"]] for c in raster],
        },
        "winds": winds,
        "rot": rot,
        "druck": druck,
        "taeler": taeler,
        "talpunkte": talpunkte,
        "modell": modell,
    }


def _regionen_zeichen(raster, rot, druck, taeler, talpunkte) -> dict:
    """Zeichen je Region und Stunde, 0–4. Druckunterschied und kühlere Luvseite gelten
    schweizweit (gleich für alle Regionen); Wind in der Region (Anteil Rasterpunkte ab
    KARTE_REGION_SHARE) und trockener Föhnwind in einem Tal dieser Region sind regional.
    Stundenwerte: die Tageszählung bleibt im Briefing."""
    zellen = {}
    for c in raster:
        if c.get("region_id"):
            zellen[c["region_id"]] = zellen.get(c["region_id"], 0) + 1
    tal_je_region = {}
    for tp in talpunkte:
        if tp.get("region_id"):
            tal_je_region.setdefault(tp["region_id"], []).append(tp["id"])

    out = {}
    for t, codes in rot.items():
        d = druck.get(t) or {}
        dp = d.get("dp")
        s8, n8 = (d.get("sued") or {}).get("t800"), (d.get("nord") or {}).get("t800")
        luv = s8 - n8 if s8 is not None and n8 is not None else None
        dp_on = dp is not None and abs(dp) >= fi.DP_INDICATOR_HPA
        # Luvseite: die Seite, aus der der Wind kommt, ist kühler (dp>0 = Süden höher → Lugano)
        luv_on = luv is not None and dp is not None and (
            (dp >= 0 and luv <= -fi.LUV_COOLER_MIN_K) or (dp < 0 and luv >= fi.LUV_COOLER_MIN_K))

        sued, nord = {}, {}
        for k, code in enumerate(codes):
            rid = raster[k].get("region_id")
            if not rid:
                continue
            if code == 1:
                sued[rid] = sued.get(rid, 0) + 1
            elif code == 2:
                nord[rid] = nord.get(rid, 0) + 1

        # Stärke je Tal in dieser Stunde (für die Region: das stärkste Tal der Region)
        tal_stufe = {}
        for tp in talpunkte:
            if tp.get("region_id"):
                w = (taeler.get(t) or {}).get(tp["id"]) or {}
                st = 2 if w.get("strikt") else 1 if w.get("dir_dry") else 0
                tal_stufe[tp["region_id"]] = max(tal_stufe.get(tp["region_id"], 0), st)

        zeile = {}
        for rid, n in zellen.items():
            s_anteil, n_anteil = sued.get(rid, 0) / n, nord.get(rid, 0) / n
            anteil = max(s_anteil, n_anteil)
            wind_on = anteil >= fi.KARTE_REGION_SHARE
            # Talzeichen nur prüfbar, wo ein Talpunkt liegt; sonst zählen nur drei Zeichen
            tal_messbar = bool(tal_je_region.get(rid))
            tal_on = tal_messbar and any(((taeler.get(t) or {}).get(pid) or {}).get("dir_dry")
                                         for pid in tal_je_region.get(rid, []))
            zeile[rid] = {
                "n": int(dp_on) + int(luv_on) + int(wind_on) + int(tal_on),
                "m": 4 if tal_messbar else 3,
                "dp": dp_on, "luv": luv_on, "wind": wind_on, "tal": tal_on, "tal_messbar": tal_messbar,
                # Stärke je Zeichen: Druck mäßig ab 4, stark ab 8 hPa (Schwellentabelle);
                # Luftseite und Wind in der Region nur zweistufig (starke Stufen nicht belegt)
                "lvl": {"dp": int(dp_on),
                        "luv": int(luv_on), "wind": int(wind_on)},
                "anteil": round(anteil, 2), "seite": "sued" if s_anteil >= n_anteil else "nord",
                # Je Richtung: betroffen, wenn ≥ KARTE_REGION_SHARE der Punkte Föhnwind haben.
                # Eine Region kann in beiden Richtungen betroffen sein.
                "wind_sued": s_anteil >= fi.KARTE_REGION_SHARE,
                "wind_nord": n_anteil >= fi.KARTE_REGION_SHARE,
                # Gesamtstärke der Region (0–6): Druck + Luftseite + Wind + stärkstes Tal
                "s": int(dp_on)
                     + int(luv_on) + int(wind_on) + tal_stufe.get(rid, 0),
            }
        out[t] = zeile
    return out


def _sektor(pid: str, meta: dict):
    """Föhnsektor eines Tals wie evaluate_talpunkt: gemessener Sektor, sonst Halbkreis je foehn_typ."""
    from foehn_talpunkte import sektor_fuer
    s = sektor_fuer(pid, meta)
    if s and len(s) == 2:
        return float(s[0]), float(s[1])
    return fi.TAL_SEKTOR.get(meta.get("foehn_typ"), fi.TAL_SEKTOR["Süd"])


def speichere(store: dict, pfad=None) -> None:
    """Atomar schreiben (Temp-Datei + replace), damit die Seite nie eine halbe Datei liest."""
    pfad = pfad or config.FOEHN_KARTE_PATH
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, pfad)


def lade(pfad=None):
    pfad = pfad or config.FOEHN_KARTE_PATH
    if not pfad.exists():
        return None
    with open(pfad, "r", encoding="utf-8") as f:
        return json.load(f)


def ansicht(store: dict, datum: str) -> dict:
    """Ein Tag für die Seite: Stundenschlüssel "HH" statt voller Zeitstempel."""
    def tag_werte(werte: dict) -> dict:
        return {t[11:13]: v for t, v in werte.items() if t[:10] == datum}

    stat = [dict(seite=s, **STATIONEN[s]) for s in ("nord", "sued")]
    return {
        "datum": datum,
        "erzeugt": store.get("erzeugt"),
        "stunden": stunden(),
        "grid": {
            "meta": store["raster"]["meta"],
            "zellen": store["raster"]["zellen"],
            "winds": tag_werte(store.get("winds") or {}),
            "rot": tag_werte(store.get("rot") or {}),
        },
        "druck": tag_werte(store.get("druck") or {}),
        "kamm": tag_werte(store.get("kamm") or {}),
        "regionen": tag_werte(store.get("regionen") or {}),
        "richtungen": store.get("richtungen") or {},
        "talzeichen": tag_werte(store.get("talzeichen") or {}),
        "hoehen": tag_werte(store.get("hoehen") or {}),
        "kamm_punkte": store.get("kamm_punkte") or [],
        "taeler": tag_werte(store.get("taeler") or {}),
        "talpunkte": store.get("talpunkte") or [],
        "stationen": stat,
        "modell": tag_werte(store.get("modell") or {}),
    }
