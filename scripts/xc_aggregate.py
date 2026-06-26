"""XContest-Validierung Aggregator.

Liest kompakte Tagesdaten aus xcontest_validation/_raw/YYYY-MM-DD.tsv
(Format: launch\tkm\tstart\tairtime\tpilot), aggregiert pro Spot, mappt
XContest-Namen auf PGE-DB-Keys, joint our_*/wx_* aus weather_archive und
klassifiziert finding_type.

Output:
  - xcontest_validation/_raw/_obs_YYYY-MM-DD.csv  (Kandidaten-observations-Zeilen)
  - Konsole: Digest pro Tag (Spot-Tabelle sortiert nach best_km + Stats)

Usage: PYTHONUTF8=1 python scripts/xc_aggregate.py 2026-05-27 2026-05-28 ...
"""
from __future__ import annotations
import csv, json, sys, re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "xcontest_validation" / "_raw"
ARCHIVE = ROOT / "data" / "weather_archive"

# --- XContest-Name -> PGE-DB-Key Mapping (kuratiert) ---
MAPPING = {
    "Niesen": "Niesen-2280",
    "Riederalp": "Riederalp- Greicheralp",
    "Grindelwald": "Grindelwald - First",
    "Ebenalp": "Ebenalp (Appenzell- Wasserauen)",
    "Brunni": "Engelberg - Brunni - Schonegg",
    "Mentschelen": "Möntschelealp",
    "Galgenen": "Gschwänd - Galgenen",
    "Amisbühl": "Amisbuehl",
    "Fiesch": "Fiesch -Kuehboden (Heimat- Galfera)",
    "Verbier": "Verbier - Ruinettes _ Fontanets_Attelas",
    "Vounetz": "Vounetz-1620",
    "Cimetta": "Locarno- Cardada - Cimetta -1570",
    "Niederhorn": "Niederhorn-1920",
    "Haldigrat": "Dalenwil - Haldigrat",
    "Mauborget": "Mauborget",
    "Le Suchet": "Le Suchet",
    "Pléiades": "Pleiades",
    "Cret du Midi": "Crêt-du-Midi",
    "Veysonnaz": "Crete de Thyon-2060 (Veysonnaz)",
    "Jaman": "Dent de Jaman (Rochers de Naye)",
    "Weissenstein": "Weissenstein",
    "Tschenten": "Tschentenegg",
    "Kronberg": "Kronberg (Appenzell- Jakobsbad)",
    "Hohwacht": "Hohwacht",
    "Mäggisseren": "Mägisserhorn-2260",
    "Schwängimatt": "Schwaengimatt",
    "Marbachegg": "Marbachegg-1480",
    "Hüsliberg": "Schänis - Hüsliberg",
    "Montlinge...": "Montlinger Schwamm",
    "Fronalpstock": "Fronalpstock",
    "Klewenalp": "Klewenalp",
    "Niederbauen": "Emmetten - Niederbauen",
    "Pizol": "Wangs -Pizolbahn Endstation",
    "Hinterrugg": "Hinterrugg",
    "Braunwald": "Braunwald 'Kiosk'",
    "Stanserhorn": "Stanserhorn",
    "Hoch Ybrig": "Hoch-Ybrig",
    "Gummen": "Gummen",
    "Monte Tamaro": "Monte Tamaro -Alpe Foppa",
    "Monte Gen...": "Monte Generoso -1600",
    "Monte Lema": "Monte Lema",
    "Hoher Kasten": "Hoher Kasten",
    "Grabserberg": "Grabserberg",
    "Motta Naluns": "Motta Naluns (Schuls- Scuol)",
    "Fanas": "Fanas -Hörnli -Eggli",
    "Davos": "Davos - Jakobshorn -2560",
    "Riggisalp": "Riggisalp",
    "Grandvillard": "La Vudalla-1620",
    "Obere Wengi": "Obere Wengi",
    "Rotenflue": "Rotenflue",
    "Zugerberg": "Zugerberg",
    "Chasseral": "Chasseral",
    "Chaumont": "Chaumont",
    "Mont-Soleil": "Mont-Soleil",
    "Montoz": "Werdtberg-1240 (Montoz nord)",
    "Leysin": "Berneuse-2020",
    "Cousimbert": "Cousimbert",
    "Sonchaux": "Sonchaux (Villeneuve)",
    "Rigi Sche...": "Rigi-Scheidegg",
    "Rigi Kulm": "Rigi Kulm",
    "Rigi Staffel": "Rigi-Staffelhöhe",
    "Buochserhorn": "Buochserhorn",
    "Riffelberg": "Riffelberg-2700",
    "Scheidegg": "Alp Scheidegg (Wald)",
    "La Robella": "La Robella",
    "Verneys": "Les Verneys",
    "schönbüel": "Lungern Schönbüel",
    "Crans-Mon...": "Montana - Cry d Er-2250",
    "Hohmattli": "Hohmattli-1770",
    "Grand Cha...": "Le Chamossaire-1980",
    "Allmenalp...": "Allmenalp (Kandersteg)",
    "Lai Alv": "Disentis: Caischavedra - Lai Alv - Plaun Tir",
    "La Baye": "La Baye",
    "Plan du Fou": "Plan du fou",
    "Schilthorn": "Schilthorn -Mürren - Muerren",
    "Schiltgra...": "Schiltgrat Muerren",
    "Bündner Rigi": "Bündner Rigi",
    "Albagno": "Capanna Albagno",
    "Brandberg": "Brandberg",
    "Hummel": "Hummel (Oben)",
    "Amden": "Weesen- Amden -Durschlegi",
    "Gurnigel": "Obere Gurnigal",
    "Schönhalde": "Flums -Schönhalden (Schoenhalden)",
    "Moléson": "Le Moléson-2000",
    "Valerette": "Valerette",
    "Büelen": "Büelen - Bueelen",
    "Le pont": "Le Pont-Vallée de Joux",
    "Mostelegg": "Mostelegg",
    "Urmiberg": "Urmiberg (Brunnen)",
    "Wispile": "Wispile-1900 (Saanen- Gstaad)",
    "Präzer Alp": "Präzer Alp",
    "Präzer_Al...": "Präzer Alp",
    "Vilan": "Vilan -Gipfel",
    "Vercorin...": "Vercorin",
    "Pra de Cray": "Pra de Cray",
    "Fürenalp": "Engelberg -Fuerenalp",
    "Männlichen": "Maennlichen (Wengen)",
    "Musenalp": "Musenalp",
    "Titlis": "Engelberg -Titlis",
    "Walegg": "Walegg",
    "Burgfelds...": "Burgfeldstand",
    "Hochstollen": "Hochstollen",
    "Prodchamm": "Prodkamm",
    "La Breya": "La Breya (Orsieres, Champex)",
    "Ruedlen": "Ruedlen",
    "Bietschho...": "Bietschhorn",
    "Gurli": "Gurli",
    "Balderen": "Baldern (Uetliberg)",
    "Les Pètis": "Les Pétis",
    "Saas-Fee ...": "Saas Fee -Plattjen",
    "Brienz": "Brienzer Rothorn",
    "Brändlen-...": "Brändlen-1240",
    "Brändlen": "Brändlen-1240",
}

# Namen, die keine echten Spots sind -> ignorieren (kein observation-Row)
SKIP = {"?", "Inconnu", "unknown", "TO (N-NW)...", "TO (WNW)...", "Talstatio...", "TO"}

# Snapshot-Vollstaendigkeit pro Tag (siehe Investigation):
#   xc_ok   = streckenflug_rating ist valide (LLM-XC-Pass gelaufen)
#   exp_ok  = experience_rating ist valide
# 29.05 06:15-Snapshot: XC+exp-Pass NICHT gelaufen (xc=0 ueberall, exp nur 33/488)
# 30.05 06:18-Snapshot: XC gecappt auf 0/1 (Artefakt), exp ok
# 14.-19.06 ~06:40-Snapshots: XC gecappt auf 0/1 (xc>=2: 0/494, vor XC-LLM-Pass),
#   exp hat echte Streuung 1-5 -> xc_ok=False, exp_ok=True (wie 30.05).
# 20.06 06:05-Snapshot: KAPUTT (status=error 487/494, exp+xc gedeckelt) -> nicht
#   validierbar, NICHT aggregieren (siehe README Daten-Luecken).
DATE_FLAGS = {
    "2026-05-27": {"xc_ok": True, "exp_ok": True},
    "2026-05-28": {"xc_ok": True, "exp_ok": True},
    "2026-05-29": {"xc_ok": False, "exp_ok": False},
    "2026-05-30": {"xc_ok": False, "exp_ok": True},
    # 06.-13.06 ~06:20-Snapshots: xc gedeckelt 0/1 (xc>=2: 0/488 ueberall).
    # exp valide ausser 09./10.06 (exp>=3: 0-2/163 -> gedeckelt wie 29.05).
    "2026-06-06": {"xc_ok": False, "exp_ok": True},
    "2026-06-07": {"xc_ok": False, "exp_ok": True},
    "2026-06-08": {"xc_ok": False, "exp_ok": True},
    "2026-06-09": {"xc_ok": False, "exp_ok": False},
    "2026-06-10": {"xc_ok": False, "exp_ok": False},
    "2026-06-12": {"xc_ok": False, "exp_ok": True},
    "2026-06-13": {"xc_ok": False, "exp_ok": True},
    "2026-06-14": {"xc_ok": False, "exp_ok": True},
    "2026-06-15": {"xc_ok": False, "exp_ok": True},
    "2026-06-16": {"xc_ok": False, "exp_ok": True},
    "2026-06-17": {"xc_ok": False, "exp_ok": True},
    "2026-06-18": {"xc_ok": False, "exp_ok": True},
    "2026-06-19": {"xc_ok": False, "exp_ok": True},
}
ARTIFACT_NOTE = ("snapshot_xc_unvollstaendig: 06:15-Run vor XC-LLM-Pass, "
                 "streckenflug/exp-Rating Artefakt (nicht validierbar)")

# Ab diesem Datum ist die separate streckenflug-Note abgekuendigt und in die
# Flugeinschaetzung integriert -> XC-Signal = experience_rating. Davor (<=28.05)
# war streckenflug ein eigenes Feld (rating 0-5). Belegt durch Snapshot-Scan:
# <=28.05 streckenflug mit Spread 0-5, ab 30.05 nur noch 0/1-Stub, exp mit Spread.
XC_FROM_EXPERIENCE_SINCE = "2026-05-30"
EXP_XC_NOTE = ("xc_aus_flugeinschaetzung: streckenflug-Feld ab 2026-05-30 "
               "abgekuendigt, XC-Signal=experience_rating")


def parse_airtime(s):
    return s.strip()


def km_to_float(s):
    try:
        return float(s)
    except Exception:
        return 0.0


def load_day(date):
    path = RAW / f"{date}.tsv"
    flights = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        launch = parts[0].strip()
        km = km_to_float(parts[1])
        start = parts[2].strip()
        airtime = parts[3].strip() if len(parts) > 3 else ""
        pilot = parts[4].strip() if len(parts) > 4 else ""
        flights.append((launch, km, start, airtime, pilot))
    return flights


def aggregate(flights):
    agg = defaultdict(lambda: {"launches": 0, "best_km": -1, "top": None})
    for launch, km, start, airtime, pilot in flights:
        a = agg[launch]
        a["launches"] += 1
        if km > a["best_km"]:
            a["best_km"] = km
            a["top"] = (pilot, start, airtime)
    return agg


def map_to_pge(name, arch_spots):
    if name in SKIP:
        return None, "skip"
    if name in MAPPING:
        key = MAPPING[name]
        if key in arch_spots:
            return key, "mapped"
        return None, "mapped_missing:" + key
    if name in arch_spots:
        return name, "exact"
    return None, "gap"


COLS = ["date","spot","region","launches","best_km","top_pilot","top_start_time","top_airtime",
        "our_safety_rating","our_experience_rating","our_xc_rating","our_status",
        "our_streckenflug_tier","our_streckenflug_limiting_factor","decisions_applied","no_go_reasons",
        "wx_climb_rate_max_ms","wx_max_thermal_height_m","wx_blh_max_m","wx_wind_gust_max_kmh",
        "wx_wind_dir_dominant_deg","wx_t2m_max","wx_precip_sum_mm","wx_cloud_low_mean_pct",
        "wx_cape_max","wx_lifted_index_min","wx_productive_thermal_h","finding_type","notes"]


def classify(status, xc, best_km):
    if status == "not_safe":
        return "false_positive_notsafe"
    if status == "conditional":
        if best_km >= 60 and (xc is None or xc <= 2):
            return "underrated_spot"
        return "confirm"
    if status == "safe":
        if best_km >= 80 and (xc is not None and xc <= 2):
            return "underrated_spot"
        return "confirm"
    return "confirm"


def build_rows(date, agg, arch):
    arch_spots = arch.get("spots", {})
    flags = DATE_FLAGS.get(date, {"xc_ok": True, "exp_ok": True})
    xc_ok, exp_ok = flags["xc_ok"], flags["exp_ok"]
    rows = []
    diag = {"mapped": 0, "exact": 0, "gap": 0, "skip": 0, "mapped_missing": 0}
    for name, a in sorted(agg.items(), key=lambda kv: -kv[1]["best_km"]):
        pge, how = map_to_pge(name, arch_spots)
        if how.startswith("mapped_missing"):
            diag["mapped_missing"] += 1
            how_short = "gap"
        else:
            how_short = how
            diag[how] = diag.get(how, 0) + 1
        pilot, start, airtime = a["top"] or ("", "", "")
        row = {c: "" for c in COLS}
        row.update({
            "date": date, "spot": name if pge is None else pge,
            "launches": a["launches"], "best_km": f"{a['best_km']:.2f}",
            "top_pilot": pilot, "top_start_time": start, "top_airtime": airtime,
        })
        if how == "skip":
            continue
        if pge is None:
            row["finding_type"] = "coverage_gap"
            row["notes"] = f"Nicht in PGE-DB (XContest: {name})."
            row["region"] = ""
            row["spot"] = name
            rows.append(row)
            continue
        s = arch_spots[pge]
        row["region"] = s.get("analyse_region") or ""
        ana = s.get("analysis") or {}
        agg_wx = s.get("daily_aggregates") or {}
        status = ana.get("status") or ""
        exp_val = ana.get("experience_rating")
        xc_legacy = ana.get("streckenflug_rating")
        row["our_safety_rating"] = ana.get("rating", "")
        row["our_experience_rating"] = (exp_val if (exp_val is not None and exp_ok) else "")
        # Ab 2026-05-30: streckenflug abgekuendigt -> XC-Signal = experience_rating
        # (in die Flugeinschaetzung integriert). Davor: eigenes streckenflug-Feld.
        xc_in_exp = date >= XC_FROM_EXPERIENCE_SINCE
        if xc_in_exp:
            xc_signal = exp_val if exp_ok else None
            row["our_xc_rating"] = xc_signal if xc_signal is not None else ""
            row["our_streckenflug_tier"] = ""
            row["our_streckenflug_limiting_factor"] = ""
        elif xc_ok:
            xc_signal = xc_legacy
            row["our_xc_rating"] = xc_legacy if xc_legacy is not None else ""
            row["our_streckenflug_tier"] = ana.get("streckenflug_tier") or ""
            row["our_streckenflug_limiting_factor"] = ana.get("streckenflug_limiting_factor") or ""
        else:
            xc_signal = None
            row["our_xc_rating"] = ""
            row["our_streckenflug_tier"] = ""
            row["our_streckenflug_limiting_factor"] = ""
        row["decisions_applied"] = "|".join(ana.get("decisions_applied") or [])
        row["no_go_reasons"] = "|".join(ana.get("no_go_reasons") or [])
        row["wx_climb_rate_max_ms"] = agg_wx.get("climb_rate_max_ms", "")
        row["wx_max_thermal_height_m"] = agg_wx.get("max_thermal_height_max_m", "")
        row["wx_blh_max_m"] = agg_wx.get("blh_max_m", "")
        row["wx_wind_gust_max_kmh"] = agg_wx.get("wind_gust_max_kmh", "")
        row["wx_wind_dir_dominant_deg"] = agg_wx.get("wind_dir_dominant_deg", "")
        row["wx_t2m_max"] = agg_wx.get("t2m_max", "")
        row["wx_precip_sum_mm"] = agg_wx.get("precip_sum_mm", "")
        row["wx_cloud_low_mean_pct"] = agg_wx.get("cloud_low_mean_pct", "")
        row["wx_cape_max"] = agg_wx.get("cape_max", "")
        row["wx_lifted_index_min"] = agg_wx.get("lifted_index_min", "")
        row["wx_productive_thermal_h"] = agg_wx.get("productive_thermal_h", "")
        if not ana:
            row["finding_type"] = "bug"
            row["notes"] = "Spot in PGE, aber analysis fehlt im Snapshot."
        else:
            # XC-Signal validierbar? Ab Cutoff via exp_ok, davor via xc_ok.
            xc_valid = exp_ok if xc_in_exp else xc_ok
            if xc_valid:
                row["finding_type"] = classify(status, xc_signal, a["best_km"])
                row["notes"] = EXP_XC_NOTE if xc_in_exp else ""
            else:
                row["finding_type"] = (
                    "false_positive_notsafe" if status == "not_safe" else "confirm")
                row["notes"] = ARTIFACT_NOTE
        rows.append(row)
    return rows, diag


def main(argv):
    dates = argv or ["2026-05-27", "2026-05-28", "2026-05-29", "2026-05-30"]
    for date in dates:
        flights = load_day(date)
        agg = aggregate(flights)
        arch = json.loads((ARCHIVE / f"{date}.json").read_text(encoding="utf-8"))
        rows, diag = build_rows(date, agg, arch)
        outp = RAW / f"_obs_{date}.csv"
        with open(outp, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            w.writeheader()
            w.writerows(rows)
        # Digest
        print(f"\n===== {date} =====")
        print(f"Fluege: {len(flights)}  Spots: {len(agg)}  "
              f"mapped={diag.get('mapped',0)} exact={diag.get('exact',0)} "
              f"gap={diag.get('gap',0)} skip={diag.get('skip',0)} "
              f"mapped_missing={diag.get('mapped_missing',0)}")
        from collections import Counter
        ft = Counter(r["finding_type"] for r in rows)
        print("finding_type:", dict(ft))
        print(f"{'spot':38s} {'L':>3s} {'best':>7s} {'st':>11s} {'xc':>2s} {'wind':>5s} {'gust':>5s} {'ft':s}")
        for r in rows:
            if float(r["best_km"]) < 30 and r["finding_type"] not in ("false_positive_notsafe", "underrated_spot"):
                continue
            print(f"{r['spot'][:38]:38s} {r['launches']:>3} {r['best_km']:>7} "
                  f"{str(r['our_status']):>11s} {str(r['our_xc_rating']):>2s} "
                  f"{str(r['wx_wind_dir_dominant_deg']):>5s} {str(r['wx_wind_gust_max_kmh']):>5s} {r['finding_type']}")
        print(f"-> {outp.name} ({len(rows)} Zeilen)")


if __name__ == "__main__":
    main(sys.argv[1:])
