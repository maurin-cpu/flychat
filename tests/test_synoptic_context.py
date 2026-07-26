"""Tests fuer engine/synoptic_context.py — Wetterlage-Block.

Deckt ab:
  - Helper: _wind_direction_to_sector, _flow_strength, _wind_vector_mean,
    _msl_from_surface
  - Aggregation: aggregate_ch_daily_snapshot
  - Detektoren: find_pressure_centers, decide_pressure_influence,
    decide_flow_overhead, decide_t850_trend
  - Konfidenz-Decay: decide_confidence_per_day

Hoehere Klassifikatoren (decide_bise, decide_vb_lage, decide_lage_label,
decide_precip_pattern_nord_sued, decide_schneefallgrenze, decide_foehn_summary)
sind in Phase 3 noch nicht implementiert — Tests folgen dort.
"""
import unittest

import config
from engine import synoptic_context as sc


class TestWindDirectionToSector(unittest.TestCase):
    def test_cardinals(self):
        self.assertEqual(sc._wind_direction_to_sector(0), "Nord")
        self.assertEqual(sc._wind_direction_to_sector(90), "Ost")
        self.assertEqual(sc._wind_direction_to_sector(180), "Sued")
        self.assertEqual(sc._wind_direction_to_sector(270), "West")

    def test_intercardinals(self):
        self.assertEqual(sc._wind_direction_to_sector(45), "Nordost")
        self.assertEqual(sc._wind_direction_to_sector(135), "Suedost")
        self.assertEqual(sc._wind_direction_to_sector(225), "Suedwest")
        self.assertEqual(sc._wind_direction_to_sector(315), "Nordwest")

    def test_wrap_around_at_north(self):
        # 350° und 10° muessen beide "Nord" liefern
        self.assertEqual(sc._wind_direction_to_sector(350), "Nord")
        self.assertEqual(sc._wind_direction_to_sector(10), "Nord")
        self.assertEqual(sc._wind_direction_to_sector(359), "Nord")

    def test_negative_and_overflow(self):
        # Modulo-Normalisierung
        self.assertEqual(sc._wind_direction_to_sector(-10), "Nord")
        self.assertEqual(sc._wind_direction_to_sector(370), "Nord")


class TestFlowStrength(unittest.TestCase):
    def test_classes(self):
        self.assertEqual(sc._flow_strength(5), "schwach")
        self.assertEqual(sc._flow_strength(14.9), "schwach")
        self.assertEqual(sc._flow_strength(15), "maessig")
        self.assertEqual(sc._flow_strength(29.9), "maessig")
        self.assertEqual(sc._flow_strength(30), "kraeftig")
        self.assertEqual(sc._flow_strength(49.9), "kraeftig")
        self.assertEqual(sc._flow_strength(50), "stuermisch")
        self.assertEqual(sc._flow_strength(80), "stuermisch")


class TestWindVectorMean(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(sc._wind_vector_mean([]))

    def test_all_none(self):
        self.assertIsNone(sc._wind_vector_mean([(None, None), (None, None)]))

    def test_uniform_direction(self):
        # Alle aus 90° (Ost), 20 km/h → Mittel 20 km/h aus 90°
        m = sc._wind_vector_mean([(20, 90), (20, 90), (20, 90)])
        self.assertAlmostEqual(m["speed_kmh"], 20.0, places=1)
        self.assertAlmostEqual(m["dir_deg"], 90.0, places=0)

    def test_wrap_around(self):
        # 350° und 10° -> Mittel ist 0° (Nord), NICHT 180°
        m = sc._wind_vector_mean([(10, 350), (10, 10)])
        # Vektor-Mittel um 0° → Ergebnis nahe 0/360
        d = m["dir_deg"]
        self.assertTrue(d < 5 or d > 355, f"Direction {d} sollte um 0° sein")


class TestMslFromSurface(unittest.TestCase):
    def test_sea_level(self):
        # Bei 0m Hoehe ist MSL == surface
        msl = sc._msl_from_surface(1013.25, 0, 15.0)
        self.assertAlmostEqual(msl, 1013.25, places=1)

    def test_700m_typical_ch_lowland(self):
        # 920 hPa surface auf 700m → ca. 1000-1005 hPa MSL
        msl = sc._msl_from_surface(920, 700, 10.0)
        self.assertTrue(995 < msl < 1015, f"MSL {msl} sollte 995-1015 hPa sein")

    def test_none_inputs(self):
        self.assertIsNone(sc._msl_from_surface(None, 100))
        self.assertIsNone(sc._msl_from_surface(1000, None))


class TestAggregateChDailySnapshot(unittest.TestCase):
    def _mock_cache(self, msl_per_day=None, t850_per_day=None,
                    wind_per_day=None, use_msl=True):
        dates = ["2026-05-17", "2026-05-18"]
        msls = msl_per_day or {"2026-05-17": 1020.0, "2026-05-18": 1018.0}
        t850s = t850_per_day or {"2026-05-17": 5.0, "2026-05-18": 6.0}
        winds = wind_per_day or {
            "2026-05-17": {"speed": 20.0, "dir": 250.0},
            "2026-05-18": {"speed": 22.0, "dir": 260.0},
        }
        spots = {}
        for spot_idx in range(3):
            hourly = {}
            pld = {}
            for d in dates:
                t = f"{d}T12:00"
                if use_msl:
                    hourly[t] = {"pressure_msl": msls[d], "temperature_2m": 12.0}
                else:
                    # surface_pressure mit Hoehe → MSL muss errechnet werden
                    hourly[t] = {"surface_pressure": 930.0, "temperature_2m": 12.0}
                pld[t] = {
                    "temperature_850hPa": t850s[d],
                    "wind_speed_700hPa": winds[d]["speed"],
                    "wind_direction_700hPa": winds[d]["dir"],
                }
            spots[f"spot_{spot_idx}"] = {
                "latitude": 47.0 + spot_idx * 0.1,
                "longitude": 8.0,
                "elevation_m": 700,
                "hourly_data": hourly,
                "pressure_level_data": pld,
            }
        return spots, dates

    def test_with_pressure_msl(self):
        cache, dates = self._mock_cache(use_msl=True)
        snaps = sc.aggregate_ch_daily_snapshot(cache, dates)
        self.assertEqual(len(snaps), 2)
        self.assertEqual(snaps[0]["msl_hpa"], 1020.0)
        self.assertEqual(snaps[0]["msl_source"], "pressure_msl")
        self.assertEqual(snaps[0]["t850_c"], 5.0)
        self.assertIsNotNone(snaps[0]["wind_700"])
        self.assertEqual(snaps[0]["n_spots"], 3)

    def test_fallback_to_surface_pressure(self):
        cache, dates = self._mock_cache(use_msl=False)
        snaps = sc.aggregate_ch_daily_snapshot(cache, dates)
        self.assertEqual(snaps[0]["msl_source"], "derived_from_surface")
        # 930 hPa auf 700m sollte ca. 1010 hPa MSL ergeben
        self.assertTrue(1000 < snaps[0]["msl_hpa"] < 1025,
                        f"MSL {snaps[0]['msl_hpa']} ausserhalb erwarteter Range")

    def test_no_data_returns_none(self):
        result = sc.aggregate_ch_daily_snapshot({}, ["2026-05-17"])
        self.assertIsNone(result)


class TestFindPressureCenters(unittest.TestCase):
    def _build_grid(self, msl_pattern):
        """msl_pattern: dict {label: msl_value} fuer den einen Test-Tag."""
        grid = []
        for p in config.EUROPE_PRESSURE_GRID:
            v = msl_pattern.get(p["label"])
            if v is not None:
                grid.append({
                    "lat": p["lat"],
                    "lon": p["lon"],
                    "label": p["label"],
                    "msl_by_day": {"2026-05-17": v},
                })
        return grid

    def test_clear_low_over_uk(self):
        # Tief klar ueber Schottland (985), Umgebung 1015
        pattern = {p["label"]: 1015.0 for p in config.EUROPE_PRESSURE_GRID}
        pattern["Schottland"] = 985.0
        grid = self._build_grid(pattern)
        centers = sc.find_pressure_centers(grid, "2026-05-17")
        types = [(c["type"], c["region_label"]) for c in centers]
        self.assertIn(("Tief", "Schottland"), types)

    def test_no_center_when_flat(self):
        # Alles 1013 hPa → kein Zentrum (Gradient 0)
        pattern = {p["label"]: 1013.0 for p in config.EUROPE_PRESSURE_GRID}
        grid = self._build_grid(pattern)
        centers = sc.find_pressure_centers(grid, "2026-05-17")
        self.assertEqual(centers, [])

    def test_weak_gradient_rejected(self):
        # Tief mit nur 2 hPa Gradient → unter Schwelle (5 hPa), verworfen
        pattern = {p["label"]: 1015.0 for p in config.EUROPE_PRESSURE_GRID}
        pattern["Schottland"] = 1013.0  # nur 2 hPa unter Umgebung
        grid = self._build_grid(pattern)
        centers = sc.find_pressure_centers(grid, "2026-05-17")
        self.assertEqual(centers, [], "Schwacher Gradient darf nicht detektieren")

    def test_high_over_azores(self):
        pattern = {p["label"]: 1010.0 for p in config.EUROPE_PRESSURE_GRID}
        pattern["Azoren"] = 1030.0
        grid = self._build_grid(pattern)
        centers = sc.find_pressure_centers(grid, "2026-05-17")
        types = [(c["type"], c["region_label"]) for c in centers]
        self.assertIn(("Hoch", "Azoren"), types)


class TestDecidePressureInfluence(unittest.TestCase):
    def _snaps(self, msl_list):
        return [
            {"date": f"2026-05-{17 + i:02d}", "msl_hpa": v,
             "t850_c": 5.0, "wind_700": None}
            for i, v in enumerate(msl_list)
        ]

    def test_stable_high(self):
        d = sc.decide_pressure_influence(self._snaps([1023, 1024, 1022, 1023, 1024]))
        self.assertEqual(d["value"], "Hochdruck")
        self.assertEqual(d["trend"], "stabil")

    def test_rising_pressure(self):
        d = sc.decide_pressure_influence(self._snaps([1010, 1015, 1020, 1025, 1030]))
        self.assertEqual(d["trend"], "aufbauend")
        # Slope ~5 hPa/Tag — deutlich ueber 2-hPa-Schwelle
        self.assertGreater(d["slope_hpa_per_day"], 2.0)

    def test_transition_high_to_low(self):
        d = sc.decide_pressure_influence(self._snaps([1025, 1020, 1015, 1010, 1005]))
        # Mehrere Regimes → Uebergangslage
        self.assertEqual(d["value"], "Uebergangslage")
        self.assertEqual(d["trend"], "abschwaechend")

    def test_strong_low(self):
        d = sc.decide_pressure_influence(self._snaps([998, 996, 995, 999, 1000]))
        self.assertIn(d["value"], ("starker Tiefdruck", "Tiefdruck"))

    def test_empty(self):
        d = sc.decide_pressure_influence([])
        self.assertEqual(d["value"], "unbekannt")


class TestDecideFlowOverhead(unittest.TestCase):
    def _snaps(self, winds):
        return [
            {"date": f"2026-05-{17 + i:02d}", "msl_hpa": 1015,
             "t850_c": 5.0,
             "wind_700": ({"speed_kmh": s, "dir_deg": d} if s is not None else None)}
            for i, (s, d) in enumerate(winds)
        ]

    def test_stable_west(self):
        d = sc.decide_flow_overhead(self._snaps([(20, 270), (22, 275), (18, 268)]))
        self.assertEqual(d["value"], "West")
        self.assertEqual(d["trend"], "stabil")

    def test_rotation_south_to_west(self):
        # 180° → 270° = 90° Drehung
        d = sc.decide_flow_overhead(self._snaps([(20, 180), (20, 180), (20, 270), (20, 270)]))
        self.assertIsNotNone(d["rotation"])
        self.assertIn("dreht", d["trend"])

    def test_kraeftig_west(self):
        d = sc.decide_flow_overhead(self._snaps([(40, 270), (45, 275), (42, 268)]))
        self.assertEqual(d["strength"], "kraeftig")

    def test_no_wind_data(self):
        d = sc.decide_flow_overhead(self._snaps([(None, None), (None, None)]))
        self.assertEqual(d["value"], "unbekannt")


class TestDecideT850Trend(unittest.TestCase):
    def _snaps(self, ts):
        return [
            {"date": f"2026-05-{17 + i:02d}", "msl_hpa": 1015,
             "t850_c": t, "wind_700": None}
            for i, t in enumerate(ts)
        ]

    def test_stable(self):
        d = sc.decide_t850_trend(self._snaps([5.0, 5.5, 4.8, 5.2, 5.0]))
        self.assertEqual(d["value"], "stabil")

    def test_cooler_sprung(self):
        # 4 K Abfall in einem Tag
        d = sc.decide_t850_trend(self._snaps([8.0, 8.5, 4.0, 3.5, 3.0]))
        self.assertIn("kuehler", d["value"])
        self.assertIsNotNone(d.get("change"))

    def test_warmer_overall(self):
        # Insgesamt 5 K waermer ueber Woche, aber kein Sprung
        d = sc.decide_t850_trend(self._snaps([3.0, 4.0, 5.5, 6.5, 8.0]))
        self.assertIn("waermer", d["value"])

    def test_empty(self):
        d = sc.decide_t850_trend(self._snaps([None, None, None]))
        self.assertEqual(d["value"], "unbekannt")


class TestConfidencePerDay(unittest.TestCase):
    def test_default_5_days(self):
        c = sc.decide_confidence_per_day(5)
        self.assertEqual(c, ["high", "high", "medium", "low", "low"])

    def test_more_days_get_low(self):
        c = sc.decide_confidence_per_day(7)
        self.assertEqual(c[-1], "low")


class TestClassifyNordSued(unittest.TestCase):
    def test_zurich_mittelland_nord(self):
        # Zuerich-Raum (47.37, 8.55) → alpennord
        self.assertEqual(sc._classify_nord_sued(47.37, 8.55), "alpennord")

    def test_voralpen_nord(self):
        # Berner Oberland (~46.6, 7.9) → alpennord (lat >= 46.45)
        self.assertEqual(sc._classify_nord_sued(46.6, 7.9), "alpennord")

    def test_tessin_sued(self):
        # Tessin (46.1, 8.96) → alpensued
        self.assertEqual(sc._classify_nord_sued(46.1, 8.96), "alpensued")

    def test_wallis_haupttal_sued(self):
        # Sion (46.23, 7.36) → alpensued
        self.assertEqual(sc._classify_nord_sued(46.23, 7.36), "alpensued")

    def test_none_inputs(self):
        self.assertEqual(sc._classify_nord_sued(None, 8.0), "unknown")


def _make_grid(pattern: dict) -> list:
    """Helfer: baut grid_values aus {label: msl_value} fuer date 2026-05-17."""
    out = []
    for p in config.EUROPE_PRESSURE_GRID:
        v = pattern.get(p["label"])
        if v is not None:
            out.append({
                "lat": p["lat"], "lon": p["lon"], "label": p["label"],
                "msl_by_day": {"2026-05-17": v},
            })
    return out


def _snaps_with_wind(winds: list):
    return [
        {"date": f"2026-05-{17 + i:02d}", "msl_hpa": 1015, "t850_c": 5.0,
         "gh850_m": 1500,
         "wind_700": ({"speed_kmh": s, "dir_deg": d} if s is not None else None)}
        for i, (s, d) in enumerate(winds)
    ]


class TestDecideBise(unittest.TestCase):
    def test_classic_bise(self):
        # Hoch NE-Europa (1025), Tief Mittelmeer (1010), NE-Wind 20 km/h
        pattern = {
            "Suedskandinavien": 1025.0,
            "Mitteleuropa": 1024.0,
            "Osteuropa": 1023.0,
            "Westliches Mittelmeer": 1010.0,
            "Adria": 1011.0,
            "Norditalien": 1012.0,
        }
        grid = _make_grid(pattern)
        snaps = _snaps_with_wind([(20, 50)])
        bise = sc.decide_bise(grid, snaps, ["2026-05-17"])
        self.assertTrue(bise["per_day"][0]["active"])
        self.assertTrue(bise["active_any_day"])
        self.assertGreaterEqual(bise["per_day"][0]["delta_p_hpa"], 4)

    def test_no_bise_west_wind(self):
        # Druckmuster waere bise-faehig, aber Wind aus W (270°) → nicht aktiv
        pattern = {
            "Skandinavien Sued": 1025.0, "Mitteleuropa": 1024.0,
            "Osteuropa": 1023.0,
            "Westmittelmeer": 1010.0, "Adria": 1011.0,
            "Norditalien / Genua": 1012.0,
        }
        grid = _make_grid(pattern)
        snaps = _snaps_with_wind([(20, 270)])
        bise = sc.decide_bise(grid, snaps, ["2026-05-17"])
        self.assertFalse(bise["per_day"][0]["active"])

    def test_no_bise_weak_gradient(self):
        # Gradient zu klein (2 hPa) → nicht aktiv trotz NE-Wind
        pattern = {
            "Suedskandinavien": 1015.0, "Mitteleuropa": 1014.0,
            "Osteuropa": 1014.0,
            "Westliches Mittelmeer": 1013.0, "Adria": 1013.0,
            "Norditalien": 1013.0,
        }
        grid = _make_grid(pattern)
        snaps = _snaps_with_wind([(20, 50)])
        bise = sc.decide_bise(grid, snaps, ["2026-05-17"])
        self.assertFalse(bise["per_day"][0]["active"])


class TestDecideVbLage(unittest.TestCase):
    def test_genoa_tief(self):
        # Tief 1000 hPa in Genua-Box → aktiv
        pattern = {"Norditalien": 1000.0}
        # Andere Punkte mit Standard-Hochdruck
        for p in config.EUROPE_PRESSURE_GRID:
            pattern.setdefault(p["label"], 1018.0)
        grid = _make_grid(pattern)
        vb = sc.decide_vb_lage(grid, ["2026-05-17"])
        self.assertTrue(vb["per_day"][0]["active"])
        self.assertEqual(vb["per_day"][0]["region_label"], "Norditalien")

    def test_no_vb_when_high_pressure(self):
        pattern = {p["label"]: 1020.0 for p in config.EUROPE_PRESSURE_GRID}
        grid = _make_grid(pattern)
        vb = sc.decide_vb_lage(grid, ["2026-05-17"])
        self.assertFalse(vb["per_day"][0]["active"])


class TestDecideLageLabel(unittest.TestCase):
    def test_foehn_priority(self):
        # Foehn aktiv → ueberschreibt alles andere
        label = sc.decide_lage_label(
            pressure_influence={"value": "Hochdruck"},
            flow_overhead={"value": "Sued", "strength": "kraeftig"},
            bise={"active_any_day": False},
            foehn={"active": True, "side": "Sued"},
            vb_lage={"active_any_day": False},
        )
        self.assertEqual(label["value"], "Suedfoehnlage")

    def test_vb_priority(self):
        # Kein Foehn aber Vb-Lage aktiv
        label = sc.decide_lage_label(
            pressure_influence={"value": "Tiefdruck"},
            flow_overhead={"value": "Ost", "strength": "maessig"},
            bise={"active_any_day": False},
            foehn={"active": False, "side": None},
            vb_lage={"active_any_day": True},
        )
        # Label ohne das Kuerzel "Vb" — van-Bebber-Zugbahnnummer, im Cast
        # unverstaendlich (der i18n-Key haengt am Wert: js.lage.<value>)
        self.assertEqual(label["value"], "Genua-Tief")

    def test_bise_priority(self):
        label = sc.decide_lage_label(
            pressure_influence={"value": "Hochdruck"},
            flow_overhead={"value": "Nordost", "strength": "maessig"},
            bise={"active_any_day": True},
            foehn={"active": False, "side": None},
            vb_lage={"active_any_day": False},
        )
        self.assertEqual(label["value"], "Bisenlage")

    def test_west_strong(self):
        label = sc.decide_lage_label(
            pressure_influence={"value": "Tiefdruck"},
            flow_overhead={"value": "West", "strength": "kraeftig"},
            bise={"active_any_day": False},
            foehn={"active": False, "side": None},
            vb_lage={"active_any_day": False},
        )
        self.assertEqual(label["value"], "Westlage")

    def test_high_pressure_dominant(self):
        label = sc.decide_lage_label(
            pressure_influence={"value": "Hochdruck"},
            flow_overhead={"value": "West", "strength": "schwach"},
            bise={"active_any_day": False},
            foehn={"active": False, "side": None},
            vb_lage={"active_any_day": False},
        )
        # Strömung schwach → Hochdruck setzt durch
        self.assertEqual(label["value"], "Hochdrucklage")

    def test_uebergang(self):
        label = sc.decide_lage_label(
            pressure_influence={"value": "Uebergangslage"},
            flow_overhead={"value": "West", "strength": "schwach"},
            bise={"active_any_day": False},
            foehn={"active": False, "side": None},
            vb_lage={"active_any_day": False},
        )
        self.assertEqual(label["value"], "Uebergangslage")


class TestDecidePrecipPatternNordSued(unittest.TestCase):
    def _make_cache(self, nord_pattern: dict, sued_pattern: dict):
        """Baut Mock-Cache mit jeweils 2 Nord- und 2 Sued-Spots fuer ein Datum."""
        date = "2026-05-17"
        cache = {}

        def spot_at(lat, lon, hours_data):
            hd = {}
            for hour, vals in hours_data.items():
                hd[f"{date}T{hour:02d}:00"] = vals
            return {"latitude": lat, "longitude": lon, "elevation_m": 500,
                    "hourly_data": hd, "pressure_level_data": {}}

        # 2 Nord-Spots (Mittelland)
        cache["nord_a"] = spot_at(47.3, 8.5, nord_pattern)
        cache["nord_b"] = spot_at(47.5, 8.8, nord_pattern)
        # 2 Sued-Spots (Tessin)
        cache["sued_a"] = spot_at(46.1, 8.9, sued_pattern)
        cache["sued_b"] = spot_at(46.0, 8.95, sued_pattern)
        return cache

    def test_dry_everywhere(self):
        dry = {h: {"precipitation": 0.0, "cape": 50, "weather_code": 0,
                   "precipitation_coverage": 0.0} for h in range(6, 21)}
        cache = self._make_cache(dry, dry)
        out = sc.decide_precip_pattern_nord_sued(cache, ["2026-05-17"])
        nord = out["per_day"][0]["alpennord"]
        sued = out["per_day"][0]["alpensued"]
        # Pure-LLM-Variante: nur Rohwerte, keine Klassifikation
        self.assertEqual(nord["peak_mm"], 0.0)
        self.assertEqual(nord["wet_share"], 0.0)
        self.assertEqual(sued["peak_mm"], 0.0)
        self.assertNotIn("value", nord)  # kein char/value-Feld mehr

    def test_high_cape_with_rain_returns_raw_values(self):
        # Konvektive Lage: CAPE 1200, NS bei 14-16 Uhr
        thunder = {h: {"precipitation": 3.0 if h in (14, 15, 16) else 0,
                       "cape": 1200, "weather_code": 80 if h == 15 else 0,
                       "precipitation_coverage": 0.5 if h in (14, 15) else 0}
                   for h in range(6, 21)}
        dry = {h: {"precipitation": 0, "cape": 100, "weather_code": 0,
                   "precipitation_coverage": 0.0} for h in range(6, 21)}
        cache = self._make_cache(thunder, dry)
        out = sc.decide_precip_pattern_nord_sued(cache, ["2026-05-17"])
        nord = out["per_day"][0]["alpennord"]
        # Rohwerte korrekt aggregiert
        self.assertEqual(nord["peak_mm"], 3.0)
        self.assertEqual(nord["max_cape"], 1200)
        self.assertGreaterEqual(nord["max_coverage"], 0.5)

    def test_widespread_rain_returns_high_wet_share(self):
        # Hohe Coverage, mehrere mm verteilt
        rain = {h: {"precipitation": 2.0, "cape": 100, "weather_code": 63,
                    "precipitation_coverage": 0.85}
                for h in range(8, 20)}
        cache = self._make_cache(rain, rain)
        out = sc.decide_precip_pattern_nord_sued(cache, ["2026-05-17"])
        nord = out["per_day"][0]["alpennord"]
        # Alle Spots nass → wet_share=1.0
        self.assertEqual(nord["wet_share"], 1.0)
        self.assertEqual(nord["peak_mm"], 2.0)
        self.assertGreaterEqual(nord["max_coverage"], 0.85)

    def _make_mixed_nord_cache(self, n_total: int, n_wet: int, wet_pattern: dict):
        """Mixed Nord-Cache: n_wet von n_total Spots haben wet_pattern, Rest trocken."""
        date = "2026-05-17"
        dry_hours = {h: {"precipitation": 0.0, "cape": 50, "weather_code": 0,
                         "precipitation_coverage": 0.0} for h in range(6, 21)}
        cache = {}
        for i in range(n_total):
            hours = wet_pattern if i < n_wet else dry_hours
            hd = {f"{date}T{h:02d}:00": v for h, v in hours.items()}
            # Alle Nord (Mittelland-Region), leicht versetzte Koordinaten
            cache[f"nord_{i}"] = {
                "latitude": 47.3 + i * 0.001, "longitude": 8.5,
                "elevation_m": 500, "hourly_data": hd, "pressure_level_data": {},
            }
        return cache

    def test_isolated_cell_aggregates_correctly(self):
        # Pure-LLM-Variante: keine Klassifikation, aber Rohwerte korrekt aggregiert.
        # 2/50 Spots (4%) mit hohem peak und CAPE — LLM bekommt die Zahlen
        # und entscheidet selbst, ob "Hitzegewitter" oder "trocken".
        wet = {h: {"precipitation": 13.5 if h == 15 else 0, "cape": 1430,
                   "weather_code": 80 if h == 15 else 0,
                   "precipitation_coverage": 0.12 if h == 15 else 0}
               for h in range(6, 21)}
        cache = self._make_mixed_nord_cache(n_total=50, n_wet=2, wet_pattern=wet)
        out = sc.decide_precip_pattern_nord_sued(cache, ["2026-05-17"])
        nord = out["per_day"][0]["alpennord"]
        # wet_share korrekt: 2/50 = 0.04
        self.assertEqual(nord["wet_share"], 0.04)
        # peak_mm = max der nassen Spots
        self.assertEqual(nord["peak_mm"], 13.5)
        # max_cape weitergegeben
        self.assertEqual(nord["max_cape"], 1430)

    def test_single_high_peak_spot_aggregates(self):
        # 1/50 Spots mit 41 mm — LLM bekommt peak=41mm bei ws=2%
        wet = {h: {"precipitation": 41.1 if h == 15 else 0, "cape": 1520,
                   "weather_code": 63 if h == 15 else 0,
                   "precipitation_coverage": 0.25 if h == 15 else 0}
               for h in range(6, 21)}
        cache = self._make_mixed_nord_cache(n_total=50, n_wet=1, wet_pattern=wet)
        out = sc.decide_precip_pattern_nord_sued(cache, ["2026-05-17"])
        nord = out["per_day"][0]["alpennord"]
        self.assertEqual(nord["peak_mm"], 41.1)
        self.assertEqual(nord["wet_share"], 0.02)
        self.assertEqual(nord["max_cape"], 1520)

    def test_high_cape_alone_is_no_gewitter(self):
        # Gewitter-Umbau: hohes CAPE OHNE weather_code 95/96/99 darf
        # gewitter_share NICHT erhoehen. CAPE = nur Ueberentwicklungs-Signal.
        cape_only = {h: {"precipitation": 4.0 if h == 15 else 0, "cape": 3000,
                         "weather_code": 80 if h == 15 else 0,  # Schauer, kein Gewitter
                         "precipitation_coverage": 0.4 if h == 15 else 0}
                     for h in range(6, 21)}
        cache = self._make_cache(cape_only, cape_only)
        out = sc.decide_precip_pattern_nord_sued(cache, ["2026-05-17"])
        nord = out["per_day"][0]["alpennord"]
        # CAPE landet als Rohwert, aber gewitter_share bleibt 0.
        self.assertEqual(nord["max_cape"], 3000)
        self.assertEqual(nord["gewitter_share"], 0.0)
        self.assertEqual(nord["max_wc"], 80)

    def test_weather_code_drives_gewitter_share(self):
        # weather_code 96 (Gewitter mit Hagel) auf den Nord-Spots,
        # niedriges CAPE -> gewitter_share=1.0 kommt rein aus weather_code.
        ts = {h: {"precipitation": 9.0 if h == 15 else 0, "cape": 350,
                  "weather_code": 96 if h == 15 else 0,
                  "precipitation_coverage": 0.6 if h == 15 else 0}
              for h in range(6, 21)}
        dry = {h: {"precipitation": 0.0, "cape": 50, "weather_code": 0,
                   "precipitation_coverage": 0.0} for h in range(6, 21)}
        cache = self._make_cache(ts, dry)
        out = sc.decide_precip_pattern_nord_sued(cache, ["2026-05-17"])
        nord = out["per_day"][0]["alpennord"]
        sued = out["per_day"][0]["alpensued"]
        # Beide Nord-Spots haben wc 96 -> gewitter_share=1.0, max_wc=96
        self.assertEqual(nord["gewitter_share"], 1.0)
        self.assertEqual(nord["max_wc"], 96)
        # Trockene Sued-Seite: kein Gewitter trotz vorhandener CAPE-Basis
        self.assertEqual(sued["gewitter_share"], 0.0)
        self.assertEqual(sued["max_wc"], 0)


class TestBuildSynopticContext(unittest.TestCase):
    def test_empty_cache_returns_none(self):
        # Komplett leerer Cache → None (kein Forecast-Datum verfuegbar)
        self.assertIsNone(sc.build_synoptic_context({}, write_audit=False))

    def test_no_msl_data_returns_none(self):
        # Cache mit Spots aber ohne MSL/Surface-Pressure → None
        cache = {
            "spot_x": {
                "latitude": 47.0, "longitude": 8.0, "elevation_m": 500,
                "hourly_data": {"2026-05-17T12:00": {"temperature_2m": 15}},
                "pressure_level_data": {},
            }
        }
        # Es gibt einen Forecast-Date, aber keine MSL-Quelle
        self.assertIsNone(sc.build_synoptic_context(cache, write_audit=False))


class TestExtractForecastDates(unittest.TestCase):
    def test_extracts_first_5_dates(self):
        cache = {
            "spot_x": {
                "latitude": 47.0, "longitude": 8.0, "elevation_m": 500,
                "hourly_data": {
                    f"2026-05-{17 + i:02d}T{h:02d}:00": {}
                    for i in range(7) for h in range(0, 24)
                },
                "pressure_level_data": {},
            }
        }
        dates = sc._extract_forecast_dates(cache, max_days=5)
        self.assertEqual(len(dates), 5)
        self.assertEqual(dates[0], "2026-05-17")

    def test_empty_cache(self):
        self.assertEqual(sc._extract_forecast_dates({}), [])


class TestDecideSchneefallgrenze(unittest.TestCase):
    def _snaps(self, ts, ghs):
        return [
            {"date": f"2026-05-{17 + i:02d}", "msl_hpa": 1015, "t850_c": t,
             "gh850_m": g, "wind_700": None}
            for i, (t, g) in enumerate(zip(ts, ghs))
        ]

    def test_in_season(self):
        # Mai = in Saison, T850=5°C, gh850=1500m → SSG ~ 1500 + 4/0.0065 ≈ 2115m
        snaps = self._snaps([5.0], [1500])
        ssg = sc.decide_schneefallgrenze(snaps, today_month=5)
        self.assertIsNotNone(ssg)
        # SSG zwischen 2000 und 2200 m
        self.assertTrue(2000 <= ssg["per_day"][0]["ssg_m"] <= 2200)

    def test_out_of_season(self):
        # Juli = NICHT in Saison → None
        snaps = self._snaps([15.0], [1500])
        self.assertIsNone(sc.decide_schneefallgrenze(snaps, today_month=7))

    def test_cold_snap_low_ssg(self):
        # Sehr kalter Tag: T850 = -5°C, gh850=1400 → SSG ~ 1400 + (-5-1)/0.0065 ≈ 477m
        snaps = self._snaps([-5.0], [1400])
        ssg = sc.decide_schneefallgrenze(snaps, today_month=11)
        self.assertIsNotNone(ssg)
        self.assertLessEqual(ssg["per_day"][0]["ssg_m"], 700)


class TestAggregateWindSide(unittest.TestCase):
    def test_distribution_driver_and_class(self):
        # 4 Spots: 2x Hoehenwind kritisch, 0x Boeen kritisch → driver=hoehenwind
        entries = [
            {"aloft_max": 45.0, "gust_max": 25.0},
            {"aloft_max": 35.0, "gust_max": 20.0},
            {"aloft_max": 22.0, "gust_max": 15.0},
            {"aloft_max": 12.0, "gust_max": 10.0},
        ]
        out = sc._aggregate_wind_side(entries)
        self.assertEqual(out["n_spots"], 4)
        self.assertEqual(out["share_aloft_crit"], 0.5)
        self.assertEqual(out["share_gust_crit"], 0.0)
        self.assertEqual(out["wind_driver"], "hoehenwind")
        self.assertEqual(out["wind_class"], "stark_eingeschraenkt")
        # Kumulative Verteilung: >10 → 4/4, >20 → 3/4, >30 → 2/4, >40 → 1/4
        self.assertEqual(out["aloft_over_kmh"]["10"], 1.0)
        self.assertEqual(out["aloft_over_kmh"]["20"], 0.75)
        self.assertEqual(out["aloft_over_kmh"]["30"], 0.5)
        self.assertEqual(out["aloft_over_kmh"]["40"], 0.25)
        self.assertEqual(out["aloft_over_kmh"]["60"], 0.0)
        self.assertEqual(out["gust_over_kmh"]["20"], 0.25)

    def test_calm_side_has_null_driver(self):
        entries = [{"aloft_max": 12.0, "gust_max": 10.0},
                   {"aloft_max": 8.0, "gust_max": 12.0}]
        out = sc._aggregate_wind_side(entries)
        self.assertIsNone(out["wind_driver"])
        self.assertEqual(out["wind_class"], "unauffaellig")

    def test_empty_side(self):
        out = sc._aggregate_wind_side([])
        self.assertEqual(out["n_spots"], 0)
        self.assertIsNone(out["aloft_over_kmh"])
        self.assertIsNone(out["wind_class"])


# ============================================================================
# SYNOPTIK 2.0 — FLUGWETTER-ZONEN, TAGESFENSTER, ZUGBAHN
# ============================================================================

def _spot_hours(date: str, precip_by_hour: dict, wc_by_hour: dict = None,
                lat: float = 46.8, lon: float = 8.0, elev: int = 1500) -> dict:
    """Baut einen weather_cache-Spot mit stuendlichem Niederschlag."""
    wc_by_hour = wc_by_hour or {}
    return {
        "latitude": lat, "longitude": lon, "elevation_m": elev,
        "hourly_data": {
            f"{date}T{h:02d}:00": {
                "precipitation": precip_by_hour.get(h, 0.0),
                "weather_code": wc_by_hour.get(h, 3),
                "cape": 500,
                "precipitation_coverage": 0.5,
                "wind_gusts_10m": 10.0,
            } for h in range(6, 21)
        },
        "pressure_level_data": {},
    }


class TestZoneMapping(unittest.TestCase):
    def test_maps_all_spots_to_valid_zones(self):
        """Kette Spot -> analyse_region -> regionen.csv[zone] muss fuer alle
        Spots aufgehen; ohne das kippen ganze Zonen-Aggregate stillschweigend
        auf 0 Spots."""
        zm = sc.build_spot_zone_map()
        self.assertGreater(len(zm), 100)
        self.assertTrue(set(zm.values()) <= set(config.SYNOPTIC_ZONES))
        # jede Zone muss echte Spots haben
        for zone in config.SYNOPTIC_ZONES:
            self.assertGreater(sum(1 for v in zm.values() if v == zone), 0,
                               f"Zone {zone} hat keine Spots")

    def test_fallback_for_unmapped_spot(self):
        self.assertEqual(sc._classify_zone_fallback(46.2, 8.8), "tessin")
        self.assertEqual(sc._classify_zone_fallback(46.2, 7.4), "wallis")
        self.assertEqual(sc._classify_zone_fallback(46.8, 9.8),
                         "graubuenden_engadin")
        self.assertEqual(sc._classify_zone_fallback(47.0, 7.5), "alpennordhang")
        self.assertIsNone(sc._classify_zone_fallback(None, None))


class TestP90(unittest.TestCase):
    """P90 statt Maximum — ein Einzelspot-Extrem (Gletscher-Spot mit
    35 mm/h) darf nicht das Bild fuer eine ganze Zone praegen."""

    def test_ignores_single_outlier(self):
        values = [0.0] * 19 + [35.6]
        self.assertLess(sc._p90(values), 1.0)

    def test_carries_broad_signal(self):
        values = [5.0] * 20
        self.assertEqual(sc._p90(values), 5.0)

    def test_empty(self):
        self.assertEqual(sc._p90([]), 0.0)


class TestPrecipZones(unittest.TestCase):
    DATE = "2026-07-25"

    def _cache(self):
        # Nordhang: trocken bis 14 Uhr, dann nass (der 25.07.-Fall)
        nord = {h: (0.0 if h < 14 else 3.0) for h in range(6, 21)}
        # Tessin: ganztags trocken
        dry = {h: 0.0 for h in range(6, 21)}
        return {
            "NordA": _spot_hours(self.DATE, nord),
            "NordB": _spot_hours(self.DATE, nord),
            "TessinA": _spot_hours(self.DATE, dry),
        }

    def _zone_map(self):
        return {"NordA": "alpennordhang", "NordB": "alpennordhang",
                "TessinA": "tessin"}

    def test_windows_preserve_time_axis(self):
        out = sc.decide_precip_pattern_zones(self._cache(), [self.DATE],
                                             self._zone_map())
        wins = out["per_day"][0]["zones"]["alpennordhang"]["windows"]
        self.assertEqual(wins["morning"]["wet_share"], 0.0)
        self.assertEqual(wins["midday"]["wet_share"], 0.0)
        self.assertEqual(wins["afternoon"]["wet_share"], 1.0)
        self.assertEqual(wins["evening"]["wet_share"], 1.0)
        # Tagespauschale wuerde denselben Tag als durchgehend nass zeigen
        self.assertEqual(
            out["per_day"][0]["zones"]["alpennordhang"]["day"]["wet_share"], 1.0)

    def test_zones_are_separated(self):
        out = sc.decide_precip_pattern_zones(self._cache(), [self.DATE],
                                             self._zone_map())
        zones = out["per_day"][0]["zones"]
        self.assertEqual(zones["tessin"]["day"]["wet_share"], 0.0)
        self.assertEqual(zones["tessin"]["windows"]["evening"]["wet_share"], 0.0)
        # Zonen ohne Spots liefern n_spots=0 statt zu fehlen
        self.assertEqual(zones["wallis"]["day"]["n_spots"], 0)

    def test_gewitter_share_not_rounded_away(self):
        """1 Gewitterzelle unter vielen Spots darf nicht auf 0.0 runden —
        die Skill-Regel 'Gewitter nur bei gewitter_share > 0' haengt daran."""
        cache = {f"S{i}": _spot_hours(self.DATE, {h: 0.0 for h in range(6, 21)})
                 for i in range(200)}
        cache["S0"] = _spot_hours(self.DATE, {17: 5.0}, wc_by_hour={17: 95})
        zm = {k: "alpennordhang" for k in cache}
        out = sc.decide_precip_pattern_zones(cache, [self.DATE], zm)
        day = out["per_day"][0]["zones"]["alpennordhang"]["day"]
        self.assertGreater(day["gewitter_share"], 0.0)
        self.assertEqual(day["max_wc"], 95)


class TestZugbahn(unittest.TestCase):
    DATE = "2026-07-25"

    def _cache(self, west_onset: int, ost_onset: int):
        cache = {}
        for i in range(6):
            cache[f"W{i}"] = _spot_hours(
                self.DATE, {h: (3.0 if h >= west_onset else 0.0)
                            for h in range(6, 21)}, lon=7.0)
            cache[f"O{i}"] = _spot_hours(
                self.DATE, {h: (3.0 if h >= ost_onset else 0.0)
                            for h in range(6, 21)}, lon=9.0)
        return cache

    def _zm(self, cache):
        return {k: "alpennordhang" for k in cache}

    def test_detects_west_to_east(self):
        cache = self._cache(west_onset=13, ost_onset=18)
        out = sc.decide_zugbahn(cache, [self.DATE], self._zm(cache))
        day = out["per_day"][0]
        self.assertEqual(day["onset_hour_by_group"]["alpennordhang_west"], 13)
        self.assertEqual(day["onset_hour_by_group"]["alpennordhang_ost"], 18)
        self.assertEqual(day["movement"]["west_ost"], "west_nach_ost")

    def test_simultaneous_when_diff_below_threshold(self):
        cache = self._cache(west_onset=14, ost_onset=15)
        out = sc.decide_zugbahn(cache, [self.DATE], self._zm(cache))
        self.assertEqual(out["per_day"][0]["movement"]["west_ost"],
                         "gleichzeitig")

    def test_no_movement_on_dry_day(self):
        cache = {f"W{i}": _spot_hours(self.DATE, {}, lon=7.0) for i in range(6)}
        out = sc.decide_zugbahn(cache, [self.DATE], self._zm(cache))
        day = out["per_day"][0]
        self.assertIsNone(day["onset_hour_by_group"]["alpennordhang_west"])
        self.assertIsNone(day["movement"]["west_ost"])

    def test_ignores_groups_below_min_spots(self):
        """Eine Gruppe mit zu wenigen Spots darf keine Richtungsaussage
        tragen (sonst entscheidet ein Einzelspot die Zugbahn)."""
        cache = {"W0": _spot_hours(self.DATE, {h: 3.0 for h in range(6, 21)},
                                   lon=7.0)}
        out = sc.decide_zugbahn(cache, [self.DATE], self._zm(cache))
        self.assertIsNone(
            out["per_day"][0]["onset_hour_by_group"]["alpennordhang_west"])


class TestWindZones(unittest.TestCase):
    DATE = "2026-07-25"

    def test_window_shares_and_day_class(self):
        # Boeen ueber Gefahrenschwelle nur am Nachmittag
        spot = _spot_hours(self.DATE, {})
        for h in range(6, 21):
            spot["hourly_data"][f"{self.DATE}T{h:02d}:00"]["wind_gusts_10m"] = (
                60.0 if h >= 14 else 5.0)
        cache = {"A": spot}
        out = sc.decide_wind_pattern_zones(cache, [self.DATE],
                                           {"A": "alpennordhang"})
        z = out["per_day"][0]["zones"]["alpennordhang"]
        self.assertEqual(z["windows"]["morning"]["share_wind_crit"], 0.0)
        self.assertEqual(z["windows"]["afternoon"]["share_wind_crit"], 1.0)
        self.assertEqual(z["wind_class"], "verblasen")

    def test_zone_without_spots_is_empty_not_missing(self):
        out = sc.decide_wind_pattern_zones({"A": _spot_hours(self.DATE, {})},
                                           [self.DATE], {"A": "tessin"})
        zones = out["per_day"][0]["zones"]
        for zone in config.SYNOPTIC_ZONES:
            self.assertIn(zone, zones)
        self.assertEqual(zones["wallis"]["n_spots"], 0)


if __name__ == "__main__":
    unittest.main()
