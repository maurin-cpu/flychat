"""foehn_karte: Stundendaten der Föhn-Karte aus einem Lauf (synthetisch, echtes Raster)."""

import tempfile
import unittest
from pathlib import Path

import foehn_indicators as fi
import foehn_karte as fk

DATUM = "2026-10-31"
DATES = [DATUM]


def _stunden_zeit(datum=DATUM):
    return [f"{datum}T{h:02d}:00" for h in range(0, 24)]


def _karte(wind=40, richtung=180):
    """fetch_wind_karte-Form über das volle Raster: gleicher Wind in jeder Zelle, alle 24 h."""
    zeit = _stunden_zeit()
    punkte = []
    for c in fi.karte_raster():
        n = len(zeit)
        punkte.append({**c, "hourly": {
            "wind_speed_10m": [wind] * n,
            "wind_direction_10m": [richtung] * n,
            "wind_gusts_10m": [wind + 5] * n,
        }})
    return {"time": zeit, "model": ["icon_ch1"] * len(zeit), "punkte": punkte}


def _data(druck_nord=1000.0, druck_sued=1004.0):
    zeit = _stunden_zeit()
    n = len(zeit)
    h = {"time": zeit, "pressure_msl": [druck_nord] * n, "temperature_800hPa": [5.0] * n}
    hs = {"time": zeit, "pressure_msl": [druck_sued] * n, "temperature_800hPa": [7.0] * n}
    return {"nord": {"hourly": h}, "sued": {"hourly": hs}}


def _talseries(wind=25, gust=35, richtung=180, rh=50):
    zeit = _stunden_zeit()
    n = len(zeit)
    return {
        "time": zeit,
        "punkte": {
            "T_TEST": {
                "meta": {"tal": "Testtal", "gruppe": "Südseite", "foehn_typ": "Süd",
                         "lat": 46.8, "lon": 8.6},
                "hourly": {"wind_speed_10m": [wind] * n, "wind_gusts_10m": [gust] * n,
                           "wind_direction_10m": [richtung] * n,
                           "relative_humidity_2m": [rh] * n},
            }
        },
    }


class FoehnKarteBuildTest(unittest.TestCase):

    def setUp(self):
        self.store = fk.build(_karte(), _data(), _talseries(), DATES)

    def test_winde_nur_flugstunden_und_volles_raster(self):
        stunden = sorted(self.store["winds"])
        self.assertEqual(len(stunden), 12)                       # 06..17
        self.assertEqual(stunden[0], f"{DATUM}T06:00")
        self.assertEqual(stunden[-1], f"{DATUM}T17:00")
        self.assertEqual(len(self.store["winds"][stunden[0]]["u"]), 29 * 46)

    def test_rot_nur_in_alpenregionen_und_mit_südwind(self):
        t = f"{DATUM}T12:00"
        rot = self.store["rot"][t]
        zellen = self.store["raster"]["zellen"]
        for code, z in zip(rot, zellen):
            if z[2] is None:
                self.assertEqual(code, 0)
        self.assertTrue(any(code == fk.ROT_CODE["sued"] for code in rot))
        self.assertFalse(any(code == fk.ROT_CODE["nord"] for code in rot))

    def test_druck_und_dp_lugano_minus_zuerich(self):
        d = self.store["druck"][f"{DATUM}T09:00"]
        self.assertEqual(d["dp"], 4.0)
        self.assertEqual(d["nord"]["t800"], 5.0)

    def test_taeler_nutzen_talpunkt_stunde(self):
        t = self.store["taeler"][f"{DATUM}T10:00"]["T_TEST"]
        self.assertTrue(t["dir_dry"])            # 180° liegt im Südsektor, 50 % RF, 25 km/h
        self.assertTrue(t["strikt"])
        self.assertEqual(t["wind"], 25)

    def test_taeler_trocken_nicht_strikt_bei_feuchte(self):
        store = fk.build(_karte(), _data(), _talseries(wind=18, gust=20, rh=65), DATES)
        t = store["taeler"][f"{DATUM}T10:00"]["T_TEST"]
        self.assertFalse(t["strikt"])

    def test_ansicht_schluessel_sind_stunden(self):
        a = fk.ansicht(self.store, DATUM)
        self.assertEqual(a["stunden"][0], "06")
        self.assertEqual(a["stunden"][-1], "17")
        self.assertIn("06", a["grid"]["winds"])
        self.assertIn("10", a["taeler"])
        self.assertEqual(a["talpunkte"][0]["tal"], "Testtal")
        self.assertEqual([s["seite"] for s in a["stationen"]], ["nord", "sued"])


class FoehnKarteKammTest(unittest.TestCase):

    def test_kamm_je_stunde_mit_richtung_woher(self):
        zeit = _stunden_zeit()
        n = len(zeit)
        kamm = [{"id": "gotthard", "name": "Gotthard", "lat": 46.56, "lon": 8.56,
                 "time": zeit, "speed": [40.0] * n, "dir": [180.0] * n, "model": ["icon_d2"] * n}]
        store = fk.build(_karte(), _data(), _talseries(), DATES, kamm=kamm)
        self.assertEqual(store["kamm_punkte"][0]["name"], "Gotthard")
        werte = store["kamm"][f"{DATUM}T09:00"]
        self.assertEqual(werte, [{"id": "gotthard", "speed": 40, "dir": 180}])
        self.assertNotIn(f"{DATUM}T05:00", store["kamm"])          # vor 06 Uhr nicht

    def test_ansicht_liefert_kamm_als_stundenschluessel(self):
        zeit = _stunden_zeit()
        n = len(zeit)
        kamm = [{"id": "furka", "name": "Furka", "lat": 46.57, "lon": 8.41,
                 "time": zeit, "speed": [25.0] * n, "dir": [90.0] * n, "model": [None] * n}]
        store = fk.build(_karte(), _data(), _talseries(), DATES, kamm=kamm)
        a = fk.ansicht(store, DATUM)
        self.assertIn("09", a["kamm"])
        self.assertEqual(a["kamm_punkte"][0]["id"], "furka")


class FoehnKarteDruckGewichtTest(unittest.TestCase):

    def test_starker_druck_zaehlt_nur_einen_punkt(self):
        region = next(c["region_id"] for c in fi.karte_raster() if c["region_id"])
        store = fk.build(_karte(), _data(druck_nord=1008.2, druck_sued=1000.0), _talseries(wind=10, gust=12, rh=75), DATES)
        z = store["regionen"][f"{DATUM}T10:00"][region]
        self.assertTrue(z["dp"])
        self.assertEqual(z["s"] - z["wind"] - z["luv"], 1)   # Druck: 1 Punkt, auch bei -8.2 hPa


class FoehnKarteTalzeichenTest(unittest.TestCase):

    def test_zeichen_je_tal_summieren_region_und_talmessung(self):
        region = next(c["region_id"] for c in fi.karte_raster() if c["region_id"])
        tal = _talseries()
        tal["punkte"]["T_TEST"]["meta"]["region_id"] = region
        store = fk.build(_karte(), _data(), tal, DATES)
        z = store["talzeichen"][f"{DATUM}T10:00"]["T_TEST"]
        self.assertTrue(z["tal"])      # trockener Südwind im Tal
        self.assertTrue(z["wind"])     # Region mit Südwind
        self.assertTrue(z["dp"])       # +4 hPa
        self.assertFalse(z["luv"])
        self.assertEqual(z["n"], 3)
        # Stärke: Druck +4 hPa = mäßig (1), Wind 1, Talwind stark (25 km/h, Böe 35) = 2 → 4
        self.assertEqual(z["s"], 4)
        self.assertTrue(z["stark"])
        # Region: Gesamtstärke = stärkstes Tal (hier 4), gleiche Skala wie die Täler
        self.assertEqual(store["regionen"][f"{DATUM}T10:00"][region]["s"], 4)


class FoehnKarteRichtungenTest(unittest.TestCase):

    def test_richtungen_je_region_aus_der_konfiguration(self):
        store = fk.build(_karte(), _data(), _talseries(), DATES)
        rid = next(c["region_id"] for c in fi.karte_raster() if c["region_id"])
        self.assertEqual(store["richtungen"][rid], list(next(c["sides"] for c in fi.karte_raster() if c["region_id"] == rid)))


class FoehnKarteHoehenTest(unittest.TestCase):

    def test_hoehenwind_region_ist_vektormittel(self):
        region = next(c["region_id"] for c in fi.karte_raster() if c["region_id"])
        zeit = _stunden_zeit()
        n = len(zeit)
        # zwei Punkte, beide aus Süden (180°): 40 und 60 km/h → Mittel 50 km/h aus 180°
        hoehen = [{"region_id": region, "time": zeit, "speed": [40.0] * n, "dir": [180.0] * n},
                  {"region_id": region, "time": zeit, "speed": [60.0] * n, "dir": [180.0] * n}]
        store = fk.build(_karte(), _data(), _talseries(), DATES, hoehen=hoehen)
        h = store["hoehen"][f"{DATUM}T10:00"][region]
        self.assertEqual(h["speed"], 50)
        self.assertEqual(h["dir"], 180)

    def test_hoehenwind_west_mit_nord_und_sued_mittelt_richtig(self):
        region = next(c["region_id"] for c in fi.karte_raster() if c["region_id"])
        zeit = _stunden_zeit()
        n = len(zeit)
        # 270° (aus Westen) und 90° (aus Osten) mit je 30 km/h → der Wind hebt sich auf
        hoehen = [{"region_id": region, "time": zeit, "speed": [30.0] * n, "dir": [270.0] * n},
                  {"region_id": region, "time": zeit, "speed": [30.0] * n, "dir": [90.0] * n}]
        store = fk.build(_karte(), _data(), _talseries(), DATES, hoehen=hoehen)
        self.assertEqual(store["hoehen"][f"{DATUM}T10:00"][region]["speed"], 0)


class FoehnKarteRegionenTest(unittest.TestCase):

    def test_zeichen_je_region_zaehlen_wind_und_tal(self):
        # Erste Alpenregion aus dem echten Raster; ihr Tal bekommt die Region als region_id
        region = next(c["region_id"] for c in fi.karte_raster() if c["region_id"])
        tal = _talseries()
        tal["punkte"]["T_TEST"]["meta"]["region_id"] = region
        store = fk.build(_karte(), _data(), tal, DATES)
        n = store["regionen"][f"{DATUM}T10:00"][region]
        self.assertTrue(n["wind"])          # 40 km/h aus Süden in allen Zellen
        self.assertTrue(n["wind_sued"])     # Südwind in allen Zellen
        self.assertFalse(n["wind_nord"])    # kein Nordwind
        self.assertTrue(n["tal"])           # trockener Südwind im Tal dieser Region
        self.assertTrue(n["dp"])            # +4 hPa Lugano−Zürich (Schwelle 4)
        self.assertFalse(n["luv"])          # Luvseite 7 °C gegenüber 5 °C: nicht kühler
        self.assertEqual(n["n"], 3)
        self.assertEqual(n["m"], 4)         # Region hat einen Talpunkt: vier Zeichen prüfbar

    def test_region_ohne_talpunkt_zaehlt_drei_zeichen(self):
        region = next(c["region_id"] for c in fi.karte_raster() if c["region_id"])
        store = fk.build(_karte(), _data(), _talseries(), DATES)   # Talpunkt ohne region_id
        n = store["regionen"][f"{DATUM}T10:00"][region]
        self.assertEqual(n["m"], 3)
        self.assertFalse(n["tal_messbar"])
        self.assertFalse(n["tal"])

    def test_luvseite_nur_wenn_windseite_kuehler(self):
        region = next(c["region_id"] for c in fi.karte_raster() if c["region_id"])
        data = _data(druck_nord=1004.0, druck_sued=1000.0)     # Norden höher → Nordföhn
        data["sued"]["hourly"]["temperature_800hPa"] = [7.0] * 24   # Lugano wärmer
        data["nord"]["hourly"]["temperature_800hPa"] = [3.0] * 24   # Zürich kühler → Luv Zürich
        store = fk.build(_karte(), data, None, DATES)
        self.assertTrue(store["regionen"][f"{DATUM}T10:00"][region]["luv"])


class FoehnKartePersistTest(unittest.TestCase):

    def test_speichern_und_laden_roundtrip(self):
        store = fk.build(_karte(), _data(), _talseries(), DATES)
        with tempfile.TemporaryDirectory() as d:
            pfad = Path(d) / "foehn_karte.json"
            self.assertIsNone(fk.lade(pfad))
            fk.speichere(store, pfad)
            back = fk.lade(pfad)
        self.assertEqual(back["tage"], DATES)
        self.assertEqual(back["druck"], store["druck"])


class FoehnKarteApiTest(unittest.TestCase):

    def test_api_ohne_admin_verboten(self):
        # Lokal loggt _local_auto_login jeden als Admin ein — hier den Admin-Status abschalten.
        from unittest import mock
        import web
        with mock.patch.object(web, "_is_admin", return_value=False):
            with web.app.test_client() as c:
                r = c.get("/api/foehn/karte")
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
