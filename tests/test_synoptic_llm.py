"""Tests fuer engine/synoptic_llm.py — Validierung, Finalisierung, Payload.

Deckt Halluzinations-Schutz und den Korrektur-Loop-Vertrag ab:
  - _validate erkennt Verbotsbegriffe, erfundene Regionen, Schema-Fehler,
    fehlende flight_hints, Foehn-Lee-Inversionen, Zonen-Vollstaendigkeit —
    und liefert eine Fehlerliste (loescht selbst NICHTS)
  - _finalize baut das Zonen-Format (short/zones) plus Legacy-Felder,
    setzt Wochentag-Praefixe autoritativ, prune=True entfernt chirurgisch
  - Provenance wird vor LLM-Uebergabe gestrippt

Format seit Synoptik 2.0 (Flugwetter-Zonen):
  {"lead": str, "zones": [{"zone": <id>, "days": [{text, flight_hint}]}]}

LLM-Calls selbst werden NICHT getestet (Integration).
"""
import unittest

import config
from engine import synoptic_llm as sl

ZONES = list(config.SYNOPTIC_ZONES)


def _ctx(dates=("2026-07-05", "2026-07-06"), centers=("Azoren",), foehn=None):
    """Minimales Strukturfeld fuer Validierungs-Tests."""
    return {
        "forecast_dates": list(dates),
        "pressure_centers_per_day": [{
            "date": dates[0],
            "centers": [{"type": "Hoch", "region_label": c} for c in centers],
        }],
        "foehn": foehn or {},
    }


def _days(n_days=2):
    return [{"text": f"Tag {i+1} stabil und sonnig.",
             "flight_hint": "Gute Thermik erwartet."} for i in range(n_days)]


def _parsed(lead="Ruhige Hochdrucklage praegt die Tage.", days=None, n_days=2,
            zone_days=None):
    """Baut einen vollstaendigen Zonen-Output.

    days       — Tages-Eintraege fuer ALLE Zonen (Default: n_days generische)
    zone_days  — {zone_id: [days]} ueberschreibt einzelne Zonen gezielt
    """
    base = days if days is not None else _days(n_days)
    overrides = zone_days or {}
    return {
        "lead": lead,
        "zones": [{"zone": z, "days": overrides.get(z, base)} for z in ZONES],
        "day_lines": ["Ruhige Hochdrucklage mit trockener Luft." for _ in base],
    }


def _precip_zones(dates, gewitter_share_per_day):
    """precip_zones-Strukturfeld, reduziert auf gewitter_share pro Zone/Tag."""
    return {"per_day": [
        {"date": d,
         "zones": {z: {"day": {"gewitter_share": share}} for z in ZONES}}
        for d, share in zip(dates, gewitter_share_per_day)
    ]}


def _wind_zones(dates, class_by_zone_per_day):
    """wind_zones-Strukturfeld: [{zone: wind_class}] pro Tag."""
    return {"per_day": [
        {"date": d,
         "zones": {z: {"wind_class": cls} for z, cls in per_day.items()}}
        for d, per_day in zip(dates, class_by_zone_per_day)
    ]}


class TestValidate(unittest.TestCase):
    def test_accept_clean_output(self):
        errors = sl._validate(_parsed(), _ctx())
        self.assertEqual(errors, [])

    def test_reject_kaltfront_in_lead(self):
        errors = sl._validate(_parsed(lead="Eine Kaltfront zieht durch."), _ctx())
        self.assertTrue(any(e["kind"] == "forbidden_term" and e["scope"] == "lead"
                            for e in errors))

    def test_reject_hpa_value_in_day(self):
        days = [{"text": "Der Druck steigt auf 1025 hPa.",
                 "flight_hint": "Ruhiger Tag."},
                {"text": "Stabil.", "flight_hint": "Gut fliegbar."}]
        errors = sl._validate(_parsed(zone_days={"wallis": days}), _ctx())
        self.assertTrue(any(e["kind"] == "forbidden_term"
                            and e["scope"] == "zones[wallis].days[0]"
                            for e in errors))

    def test_reject_trog_and_geopotential(self):
        errors = sl._validate(
            _parsed(lead="Das Geopotential zeigt einen Trog."), _ctx())
        self.assertTrue(any(e["kind"] == "forbidden_term" for e in errors))

    def test_reject_invalid_region(self):
        # "Island" ist im Grid, aber NICHT detektiert
        errors = sl._validate(
            _parsed(lead="Ein Hoch ueber Island setzt sich durch."), _ctx())
        self.assertTrue(any(e["kind"] == "invalid_region" for e in errors))

    def test_invalid_region_message_lists_allowed_labels(self):
        """Die Korrektur-Nachricht muss die erlaubten Labels mitgeben — auf
        das blosse Verbot hin erfand das LLM in der naechsten Runde die
        naechste Region (25.07.2026: 'Adria')."""
        errors = sl._validate(
            _parsed(lead="Ein Hoch ueber Island setzt sich durch."),
            _ctx(centers=("Azoren",)))
        msg = next(e["message"] for e in errors
                   if e["kind"] == "invalid_region")
        self.assertIn("Azoren", msg)

    def test_accept_valid_region(self):
        errors = sl._validate(
            _parsed(lead="Ein Hoch ueber den Azoren reicht zur Schweiz."),
            _ctx(centers=("Azoren",)))
        self.assertEqual(errors, [])

    def test_reject_missing_lead(self):
        errors = sl._validate({"zones": _parsed()["zones"]}, _ctx())
        self.assertTrue(any(e["scope"] == "lead" and e["kind"] == "schema"
                            for e in errors))

    def test_reject_day_count_mismatch(self):
        errors = sl._validate(_parsed(zone_days={"tessin": _days(1)}), _ctx())
        self.assertTrue(any(e["scope"] == "zones[tessin]"
                            and e["kind"] == "schema" for e in errors))

    def test_reject_missing_flight_hint(self):
        days = [{"text": "Stabil und sonnig."},
                {"text": "Weiter stabil.", "flight_hint": "Gut fliegbar."}]
        errors = sl._validate(_parsed(zone_days={"wallis": days}), _ctx())
        self.assertTrue(any(e["scope"] == "zones[wallis].days[0]"
                            and e["kind"] == "schema" for e in errors))

    def test_reject_lead_too_long(self):
        errors = sl._validate(_parsed(lead="Wort " * 200), _ctx())
        self.assertTrue(any(e["kind"] == "too_long" for e in errors))

    def test_reject_missing_zone(self):
        parsed = _parsed()
        parsed["zones"] = parsed["zones"][:-1]
        errors = sl._validate(parsed, _ctx())
        self.assertTrue(any(e["scope"] == "zones" and e["kind"] == "incomplete"
                            for e in errors))

    def test_reject_unknown_zone_id(self):
        parsed = _parsed()
        parsed["zones"][0] = {"zone": "mittelland", "days": _days()}
        errors = sl._validate(parsed, _ctx())
        self.assertTrue(any(e["kind"] == "unknown_zone" for e in errors))

    def test_reject_duplicate_zone(self):
        parsed = _parsed()
        parsed["zones"].append({"zone": ZONES[0], "days": _days()})
        errors = sl._validate(parsed, _ctx())
        self.assertTrue(any(e["kind"] == "duplicate" for e in errors))

    def test_reject_praise_in_blown_out_zone(self):
        """Lob-Gate greift jetzt PRO ZONE — frueher nur, wenn beide
        Alpenseiten windkritisch waren (eine verblasene Zone neben einer
        ruhigen rutschte durch)."""
        dates = ("2026-07-05", "2026-07-06")
        ctx = _ctx(dates=dates)
        ctx["wind_zones"] = _wind_zones(dates, [
            {"alpennordhang": "verblasen", "wallis": "unauffaellig",
             "tessin": "unauffaellig", "graubuenden_engadin": "unauffaellig"},
            {z: "unauffaellig" for z in ZONES},
        ])
        praise = [{"text": "Sonnig und trocken.",
                   "flight_hint": "Gute Flugbedingungen, ideal für XC."},
                  {"text": "Stabil.", "flight_hint": "Gut fliegbar."}]
        errors = sl._validate(_parsed(zone_days={"alpennordhang": praise,
                                                 "wallis": praise}), ctx)
        # verblasene Zone: Lob ist ein Fehler
        self.assertTrue(any(e["kind"] == "wind_contradiction"
                            and e["scope"] == "zones[alpennordhang].days[0]"
                            for e in errors))
        # unauffaellige Zone am selben Tag: Lob erlaubt
        self.assertFalse(any(e["kind"] == "wind_contradiction"
                             and e["scope"].startswith("zones[wallis]")
                             for e in errors))

    def test_reject_foehn_lee_inversion_by_zone(self):
        """Nordfoehn -> Zone tessin ist LEE: Ruhe-Behauptung im Zonentext
        ist ein Fehler, auch ohne das Wort 'Tessin' im Satz."""
        foehn = {"per_day": [
            {"date": "2026-07-05", "nord_active": False, "sued_active": False},
            {"date": "2026-07-06", "nord_active": True, "sued_active": False},
        ]}
        days = [{"text": "Stabil.", "flight_hint": "Gut fliegbar."},
                {"text": "Bleibt windgeschuetzt und ruhig.",
                 "flight_hint": "Gut fliegbar."}]
        errors = sl._validate(_parsed(zone_days={"tessin": days}),
                              _ctx(foehn=foehn))
        self.assertTrue(any(e["kind"] == "foehn_lee_inversion"
                            and e["scope"] == "zones[tessin].days[1]"
                            for e in errors))

    def test_foehn_lee_message_is_prescriptive(self):
        """Nennt das konkrete Wort und ein Ersatz-Baumuster. Reines
        Verbieten liess das LLM am 25.07.2026 zweimal hintereinander in
        dieselbe Formulierung zurueckfallen (3/3 Versuche verbraucht)."""
        foehn = {"per_day": [
            {"date": "2026-07-05", "nord_active": False, "sued_active": False},
            {"date": "2026-07-06", "nord_active": True, "sued_active": False},
        ]}
        days = [{"text": "Stabil.", "flight_hint": "Gut fliegbar."},
                {"text": "Sonnig, sheltered in den Taelern.",
                 "flight_hint": "Gut fliegbar."}]
        errors = sl._validate(_parsed(zone_days={"tessin": days}),
                              _ctx(foehn=foehn))
        msg = next(e["message"] for e in errors
                   if e["kind"] == "foehn_lee_inversion")
        self.assertIn("sheltered", msg)      # das gefundene Wort
        self.assertIn("boeiger Nordfoehn", msg)   # der geforderte Ersatz

    def test_reject_foehn_mention_on_inactive_day(self):
        """`foehn.active` gilt fuer den Zeitraum, die Gefahr nur an
        `days_affected`. Der DE-Lauf 26.07.2026 schrieb 'Foehnschneisen
        kritisch' an einem Tag, an dem das Strukturfeld keinen Foehn
        meldete — eine erfundene Gefahrenlage."""
        foehn = {"per_day": [
            {"date": "2026-07-05", "nord_active": False, "sued_active": False},
            {"date": "2026-07-06", "nord_active": True, "sued_active": False},
        ]}
        days = [{"text": "Trocken und sonnig, aber die Foehnschneisen "
                         "sind kritisch.",
                 "flight_hint": "Boeigkeit beachten."},
                {"text": "Boeiger Nordfoehn in den Lee-Taelern.",
                 "flight_hint": "Foehnschneisen meiden."}]
        errors = sl._validate(_parsed(zone_days={"tessin": days}),
                              _ctx(foehn=foehn))
        # Tag 0 (kein Foehn): Erwaehnung ist ein Fehler
        self.assertTrue(any(e["kind"] == "foehn_not_active"
                            and e["scope"] == "zones[tessin].days[0]"
                            for e in errors))
        # Tag 1 (Nordfoehn aktiv, Lee-Zone): Erwaehnung ist PFLICHT, kein Fehler
        self.assertFalse(any(e["kind"] == "foehn_not_active"
                             and e["scope"] == "zones[tessin].days[1]"
                             for e in errors))

    def test_reject_gewitter_without_signal(self):
        """Gewitter braucht `gewitter_share > 0` — hohe CAPE reicht nicht.
        Der DE-Lauf 26.07.2026 schrieb 'Schauer und Gewitter' bei CAPE 1360
        und gewitter_share 0."""
        dates = ("2026-07-05", "2026-07-06")
        ctx = _ctx(dates=dates)
        ctx["precip_zones"] = _precip_zones(dates, [0.0, 0.02])
        days = [{"text": "Ab Mittag kraeftige Schauer und Gewitter.",
                 "flight_hint": "Frueh landen."},
                {"text": "Einzelne Gewitter am Abend.",
                 "flight_hint": "Aufzug beachten."}]
        errors = sl._validate(_parsed(zone_days={"alpennordhang": days}), ctx)
        # Tag 0: share 0 -> Gewitter unzulaessig
        self.assertTrue(any(e["kind"] == "gewitter_without_signal"
                            and e["scope"] == "zones[alpennordhang].days[0]"
                            for e in errors))
        # Tag 1: share > 0 -> zulaessig
        self.assertFalse(any(e["kind"] == "gewitter_without_signal"
                             and e["scope"] == "zones[alpennordhang].days[1]"
                             for e in errors))

    def test_cape_without_gewitter_data_is_not_flagged(self):
        """Ohne precip_zones im Kontext greift die Pruefung nicht (kein
        Fehlalarm auf unvollstaendigen Strukturfeldern)."""
        days = [{"text": "Einzelne Gewitter moeglich.",
                 "flight_hint": "Frueh landen."},
                {"text": "Stabil.", "flight_hint": "Gut fliegbar."}]
        errors = sl._validate(_parsed(zone_days={"alpennordhang": days}),
                              _ctx())
        self.assertFalse(any(e["kind"] == "gewitter_without_signal"
                             for e in errors))

    def test_reject_vb_abbreviation(self):
        """"Vb" ist die van-Bebber-Zugbahnnummer — im Cast unverstaendlich.
        Der Sachverhalt heisst "Genua-Tief"."""
        errors = sl._validate(
            _parsed(lead="Ein Vb-Tief bringt wechselhaftes Wetter."), _ctx())
        self.assertTrue(any(e["kind"] == "forbidden_term"
                            and e["scope"] == "lead" for e in errors))

    def test_accept_genua_tief(self):
        errors = sl._validate(
            _parsed(lead="Ein Genua-Tief bringt wechselhaftes Wetter."),
            _ctx())
        self.assertEqual(errors, [])

    def test_reject_cape_jargon(self):
        """CAPE ist Modell-Jargon — der Skill verlangt 'labile Luft'."""
        days = [{"text": "Labile Luft und hoher CAPE am Nachmittag.",
                 "flight_hint": "Frueh starten."},
                {"text": "Stabil.", "flight_hint": "Gut fliegbar."}]
        errors = sl._validate(_parsed(zone_days={"alpennordhang": days}),
                              _ctx())
        self.assertTrue(any(e["kind"] == "forbidden_term"
                            and e["scope"] == "zones[alpennordhang].days[0]"
                            for e in errors))

    def test_foehn_calm_allowed_in_stau_zone(self):
        """Dieselbe Aussage in der STAU-Zone (Alpennordhang bei Nordfoehn)
        ist kein Fehler — nur die Lee-Zone darf nicht ruhig heissen."""
        foehn = {"per_day": [
            {"date": "2026-07-05", "nord_active": False, "sued_active": False},
            {"date": "2026-07-06", "nord_active": True, "sued_active": False},
        ]}
        days = [{"text": "Stabil.", "flight_hint": "Gut fliegbar."},
                {"text": "Bleibt windgeschuetzt und ruhig.",
                 "flight_hint": "Gut fliegbar."}]
        errors = sl._validate(_parsed(zone_days={"alpennordhang": days}),
                              _ctx(foehn=foehn))
        self.assertFalse(any(e["kind"] == "foehn_lee_inversion"
                             for e in errors))


class TestFinalize(unittest.TestCase):
    def _zone(self, out, zone_id):
        return next(z for z in out["zones"] if z["zone"] == zone_id)

    def test_zone_format_and_weekday_prefixes(self):
        out = sl._finalize(_parsed(), _ctx(), attempts=1, unresolved=[])
        self.assertEqual(out["short"], "Ruhige Hochdrucklage praegt die Tage.")
        self.assertEqual([z["zone"] for z in out["zones"]], ZONES)
        days = self._zone(out, "alpennordhang")["days"]
        self.assertEqual(len(days), 2)
        # 2026-07-05 = Sonntag, 2026-07-06 = Montag — autoritativ gesetzt
        self.assertTrue(days[0]["text"].startswith("Sonntag: "))
        self.assertTrue(days[1]["text"].startswith("Montag: "))
        self.assertEqual(out["attempts"], 1)
        self.assertEqual(out["unresolved"], [])

    def test_zone_order_follows_config_not_llm(self):
        parsed = _parsed()
        parsed["zones"].reverse()
        out = sl._finalize(parsed, _ctx(), attempts=1, unresolved=[])
        self.assertEqual([z["zone"] for z in out["zones"]], ZONES)

    def test_legacy_fields_filled(self):
        """Konsumenten ohne Zonen-Support (alte Caches/Clients) bekommen
        weiterhin short + long_with_sources (groesste Zone)."""
        out = sl._finalize(_parsed(), _ctx(), attempts=1, unresolved=[])
        self.assertEqual(len(out["long_with_sources"]), 2)
        self.assertTrue(out["long_with_sources"][0]["text"].startswith("Sonntag: "))
        self.assertIn("Alpennordhang", out["long"])

    def test_wrong_prefix_corrected(self):
        days = [{"text": "Heute: stabil.", "flight_hint": "Gut."},
                {"text": "Dienstag: stabil.", "flight_hint": "Gut."}]
        out = sl._finalize(_parsed(days=days), _ctx(), attempts=1, unresolved=[])
        days_out = self._zone(out, "tessin")["days"]
        self.assertTrue(days_out[0]["text"].startswith("Sonntag: "))
        self.assertTrue(days_out[1]["text"].startswith("Montag: "))

    def test_parenthetical_and_stacked_prefixes_stripped(self):
        # Der 05.07.-Fall: LLM schrieb "Sonntag (Sunday):" → frueher wurde
        # "Sonntag: " nochmal davor gesetzt. Auch gestapelte + EN-Praefixe.
        days = [{"text": "Sonntag (Sunday): High pressure settles in.",
                 "flight_hint": "Gut."},
                {"text": "Montag: Montag (Monday): A foehn affects the south.",
                 "flight_hint": "Gut."}]
        out = sl._finalize(_parsed(days=days), _ctx(), attempts=1, unresolved=[])
        days_out = self._zone(out, "wallis")["days"]
        self.assertEqual(days_out[0]["text"],
                         "Sonntag: High pressure settles in.")
        self.assertEqual(days_out[1]["text"],
                         "Montag: A foehn affects the south.")

    def test_english_prefix_replaced(self):
        days = [{"text": "Sunday: sunny.", "flight_hint": "Gut."},
                {"text": "Tomorrow: windy.", "flight_hint": "Gut."}]
        out = sl._finalize(_parsed(days=days), _ctx(), attempts=1, unresolved=[])
        days_out = self._zone(out, "alpennordhang")["days"]
        self.assertEqual(days_out[0]["text"], "Sonntag: sunny.")
        self.assertEqual(days_out[1]["text"], "Montag: windy.")

    def test_en_mode_uses_english_weekdays_and_labels(self):
        # Im EN-Modus (config.LANG=en) muessen Payload-Wochentage,
        # autoritatives Praefix UND Zonen-Label englisch sein — sonst
        # entstehen Mischformen wie "Sonntag (Sunday):" (Vorfall 05.07.2026).
        old_lang = getattr(config, "LANG", "de")
        config.LANG = "en"
        try:
            days = [{"text": "Sonntag (Sunday): sunny.", "flight_hint": "Gut."},
                    {"text": "stable.", "flight_hint": "Gut."}]
            out = sl._finalize(_parsed(days=days), _ctx(), attempts=1,
                               unresolved=[])
            days_out = self._zone(out, "alpennordhang")["days"]
            self.assertEqual(days_out[0]["text"], "Sunday: sunny.")
            self.assertEqual(days_out[1]["text"], "Monday: stable.")
            self.assertEqual(self._zone(out, "tessin")["label"], "Ticino")
            payload = sl._build_llm_payload(_ctx())
            self.assertIn('"weekday": "Sunday"', payload)
        finally:
            config.LANG = old_lang

    def test_prune_removes_violating_day_keeps_rest(self):
        days = [{"text": "Eine Kaltfront zieht durch.", "flight_hint": "Gut."},
                {"text": "Stabil und sonnig.", "flight_hint": "Gut fliegbar."}]
        out = sl._finalize(
            _parsed(zone_days={"wallis": days}), _ctx(), attempts=3,
            unresolved=[sl._verr("zones[wallis].days[0]", "forbidden_term", "x")],
            prune=True)
        days_out = self._zone(out, "wallis")["days"]
        self.assertEqual(len(days_out), 1)
        # Der ueberlebende Eintrag behaelt seinen korrekten Wochentag (Montag)
        self.assertTrue(days_out[0]["text"].startswith("Montag: "))
        # andere Zonen bleiben vollstaendig
        self.assertEqual(len(self._zone(out, "tessin")["days"]), 2)
        self.assertEqual(len(out["unresolved"]), 1)

    def test_prune_strips_bad_hint_keeps_entry(self):
        days = [{"text": "Stabil.", "flight_hint": "Kaltfront beachten."},
                {"text": "Sonnig.", "flight_hint": "Gut fliegbar."}]
        out = sl._finalize(_parsed(zone_days={"tessin": days}), _ctx(),
                           attempts=3, unresolved=[], prune=True)
        days_out = self._zone(out, "tessin")["days"]
        self.assertEqual(len(days_out), 2)
        self.assertNotIn("flight_hint", days_out[0])
        self.assertEqual(days_out[1]["flight_hint"], "Gut fliegbar.")

    def test_prune_removes_calm_claim_in_foehn_lee_zone(self):
        foehn = {"per_day": [{"date": "2026-07-05", "nord_active": True,
                              "sued_active": False}]}
        days = [{"text": "Bleibt windgeschuetzt und ruhig.",
                 "flight_hint": "Gut."}]
        out = sl._finalize(_parsed(days=days), _ctx(dates=("2026-07-05",),
                                                    foehn=foehn),
                           attempts=3, unresolved=[], prune=True)
        # tessin (Lee bei Nordfoehn) faellt raus, alpennordhang (Stau) bleibt
        self.assertNotIn("tessin", [z["zone"] for z in out["zones"]])
        self.assertIn("alpennordhang", [z["zone"] for z in out["zones"]])

    def test_all_invalid_returns_none(self):
        days = [{"text": "Kaltfront!", "flight_hint": "x"}]
        out = sl._finalize({"lead": "Trog ueber Europa.",
                            "zones": [{"zone": z, "days": days} for z in ZONES]},
                           _ctx(dates=("2026-07-05",)), attempts=3,
                           unresolved=[], prune=True)
        self.assertIsNone(out)


class TestCorrectionMessage(unittest.TestCase):
    def test_contains_errors_and_keywords(self):
        errors = [sl._verr("lead", "forbidden_term", "enthaelt Kaltfront"),
                  sl._verr("days[2]", "schema", "flight_hint fehlt")]
        msg = sl._build_correction_message(errors)
        self.assertIn("KORREKTUR NOETIG", msg)
        self.assertIn("CORRECTION REQUIRED", msg)
        self.assertIn("[lead]", msg)
        self.assertIn("[days[2]]", msg)
        self.assertIn("KOMPLETTE JSON", msg)
        # Format-Erinnerung muss das Zonen-Schema nennen
        self.assertIn('"zones"', msg)


class TestStripProvenance(unittest.TestCase):
    def test_strips_internal_fields(self):
        field = {
            "value": "Hochdruck",
            "trend": "stabil",
            "decided_by": "decide_pressure_influence",
            "inputs": {"msl_by_day": [1023, 1024]},
            "thresholds": {"hoch_hpa": 1020},
        }
        out = sl._strip_provenance(field)
        self.assertIn("value", out)
        self.assertIn("trend", out)
        self.assertNotIn("decided_by", out)
        self.assertNotIn("inputs", out)
        self.assertNotIn("thresholds", out)

    def test_none_input(self):
        self.assertIsNone(sl._strip_provenance(None))


class TestBuildLlmPayload(unittest.TestCase):
    def test_no_raw_numbers_in_payload(self):
        ctx = {
            "forecast_dates": ["2026-05-17"],
            "lage_label": {"value": "Hochdrucklage", "decided_by": "x"},
            "pressure_influence": {"value": "Hochdruck", "trend": "stabil",
                                   "inputs": {"msl_by_day": [1023]}},
            "flow_overhead": {"value": "West", "strength": "schwach"},
            "t850_trend": {"value": "stabil"},
            "pressure_centers_per_day": [{
                "date": "2026-05-17",
                "centers": [{"type": "Hoch", "region_label": "Azoren",
                             "msl_hpa": 1027.0, "gradient_hpa": 12.9}],
            }],
            "bise": {"value": "nicht aktiv", "active_any_day": False},
            "vb_lage": {"value": "nicht aktiv"},
            "foehn": {"value": "nicht aktiv"},
            "precip_pattern": {"per_day": [{
                "date": "2026-05-17",
                "alpennord": {"peak_mm": 0.0, "wet_share": 0.0,
                              "max_cape": 100, "max_coverage": 0.0, "n_spots": 50},
                "alpensued": {"peak_mm": 0.0, "wet_share": 0.0,
                              "max_cape": 80, "max_coverage": 0.0, "n_spots": 30},
            }]},
            "schneefallgrenze": {"value": 2300, "per_day": []},
            "confidence_per_day": [{"date": "2026-05-17", "level": "high"}],
        }
        payload = sl._build_llm_payload(ctx)
        # Rohzahlen aus inputs sollten NICHT im Payload sein
        self.assertNotIn("msl_by_day", payload)
        # Center-Details (msl_hpa, gradient_hpa) auch nicht
        self.assertNotIn("1027", payload)
        self.assertNotIn("gradient_hpa", payload)
        # Aber das Lage-Label und der Druckeinfluss schon
        self.assertIn("Hochdrucklage", payload)
        self.assertIn("Hochdruck", payload)


class _FakeMessage:
    def __init__(self, content, reasoning_content=None):
        self.content = content
        if reasoning_content is not None:
            self.reasoning_content = reasoning_content


class _FakeChoice:
    def __init__(self, message, finish_reason="stop"):
        self.message = message
        self.finish_reason = finish_reason


class _FakeResponse:
    def __init__(self, content, reasoning_content=None, finish_reason="stop"):
        self.choices = [_FakeChoice(_FakeMessage(content, reasoning_content),
                                    finish_reason)]


class _FakeClient:
    """Faengt die create()-kwargs ab und liefert eine vorgegebene Response."""
    def __init__(self, response):
        self.captured_kwargs = None
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.captured_kwargs = kwargs
                return response

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


class TestCallLlm(unittest.TestCase):
    """Thinking-Schalter + reasoning_content-Fallback (Ausfall 01.08.2026:
    v4-flash schrieb die Antwort in reasoning_content, content blieb leer)."""

    def _with_synoptic_config(self, provider, thinking):
        self._old = (getattr(config, "SYNOPTIC_PROVIDER", None),
                     getattr(config, "SYNOPTIC_THINKING", None))
        config.SYNOPTIC_PROVIDER = provider
        config.SYNOPTIC_THINKING = thinking

    def _restore(self):
        config.SYNOPTIC_PROVIDER, config.SYNOPTIC_THINKING = self._old

    def test_empty_content_uses_json_from_reasoning(self):
        answer = '{"lead": "Stabil.", "zones": []}'
        reasoning = ("Ich pruefe die Zonen... Entwurf: {\"lead\": \"alt\"} "
                     "verworfen. Finale Antwort:\n" + answer)
        client = _FakeClient(_FakeResponse(content="",
                                           reasoning_content=reasoning))
        self._with_synoptic_config("deepseek", True)
        try:
            raw = sl._call_llm(client, "deepseek-v4-flash", [])
        finally:
            self._restore()
        self.assertEqual(raw, answer)  # das LETZTE Objekt, nicht der Entwurf

    def test_empty_content_without_reasoning_returns_none(self):
        client = _FakeClient(_FakeResponse(content=""))
        self._with_synoptic_config("deepseek", True)
        try:
            raw = sl._call_llm(client, "deepseek-v4-flash", [])
        finally:
            self._restore()
        self.assertIsNone(raw)

    def test_thinking_off_sends_disable_kwargs(self):
        client = _FakeClient(_FakeResponse(content='{"lead": "x"}'))
        self._with_synoptic_config("deepseek", False)
        try:
            sl._call_llm(client, "deepseek-v4-flash", [])
        finally:
            self._restore()
        self.assertEqual(
            client.captured_kwargs.get("extra_body"),
            {"thinking": {"type": "disabled"}})

    def test_thinking_on_sends_no_disable_kwargs(self):
        client = _FakeClient(_FakeResponse(content='{"lead": "x"}'))
        self._with_synoptic_config("deepseek", True)
        try:
            sl._call_llm(client, "deepseek-v4-flash", [])
        finally:
            self._restore()
        self.assertNotIn("extra_body", client.captured_kwargs)

    def test_non_deepseek_provider_untouched(self):
        client = _FakeClient(_FakeResponse(content='{"lead": "x"}'))
        self._with_synoptic_config("openai", False)
        try:
            sl._call_llm(client, "gpt-4o-mini", [])
        finally:
            self._restore()
        self.assertNotIn("extra_body", client.captured_kwargs)


class TestExtractJsonObject(unittest.TestCase):
    def test_last_complete_object_wins(self):
        text = 'Draft {"a": 1} then prose... final {"b": {"c": 2}} done.'
        self.assertEqual(sl._extract_json_object(text), '{"b": {"c": 2}}')

    def test_no_object_returns_none(self):
        self.assertIsNone(sl._extract_json_object("nur Prosa, kein JSON"))
        self.assertIsNone(sl._extract_json_object("kaputt {\"a\": "))
        self.assertIsNone(sl._extract_json_object(None))


class TestLabelVariants(unittest.TestCase):
    def test_simple_label(self):
        v = sl._label_variants("Schottland")
        self.assertIn("schottland", v)

    def test_slashed_label(self):
        v = sl._label_variants("Norditalien / Genua")
        self.assertIn("norditalien", v)
        self.assertIn("genua", v)


def _zone_ctx(date="2026-05-17"):
    """Strukturfeld mit Zonen-Feldern (precip_zones/wind_zones/zugbahn)."""
    def _pz(zone_vals):
        return {z: {
            "day": {"wet_share": v[0], "p90_mm": v[1], "max_mm": v[2],
                    "gewitter_share": 0.0, "max_wc": 61, "max_cape": v[3],
                    "max_coverage": 0.8},
            "windows": {w: {"wet_share": v[0], "p90_mm": v[1],
                            "gewitter_share": 0.0, "max_cape": v[3]}
                        for w in ("morning", "midday", "afternoon", "evening")},
        } for z, v in zone_vals.items()}

    vals = {"alpennordhang": (0.64, 9.2, 35.6, 1360),
            "wallis": (1.0, 11.8, 20.1, 1330),
            "tessin": (0.0, 0.0, 0.1, 900),
            "graubuenden_engadin": (0.08, 0.2, 6.9, 800)}
    return {
        "forecast_dates": [date],
        "precip_zones": {
            "per_day": [{"date": date, "zones": _pz(vals)}],
            "windows": [{"key": "morning", "hours": [6, 10]},
                        {"key": "midday", "hours": [10, 14]},
                        {"key": "afternoon", "hours": [14, 18]},
                        {"key": "evening", "hours": [18, 21]}],
            "n_spots_by_zone": {"alpennordhang": 327, "wallis": 57,
                                "tessin": 34, "graubuenden_engadin": 76},
            "thresholds": {"dry_mm": 0.5, "window_wet_mm": 0.2},
        },
        "wind_zones": {
            "per_day": [{"date": date, "zones": {
                z: {"wind_class": "verblasen", "share_wind_crit": 0.8,
                    "share_wind_warn": 0.9, "wind_driver": "beide",
                    "median_aloft_kmh": 36.1, "max_aloft_kmh": 60.0,
                    "aloft_over_kmh": {"30": 0.6},
                    "windows": {
                        "morning": {"share_wind_crit": 0.91,
                                    "p90_gust_kmh": 41.0,
                                    "max_gust_kmh": 48.2},
                        "evening": {"share_wind_crit": 0.95,
                                    "p90_gust_kmh": 88.6,
                                    "max_gust_kmh": 97.4}}}
                for z in config.SYNOPTIC_ZONES}}],
            "thresholds": {"wind_danger_kmh": 30},
        },
        "zugbahn": {"per_day": [{
            "date": date,
            "onset_hour_by_group": {"alpennordhang_west": 14,
                                    "alpennordhang_ost": 16,
                                    "wallis": 13, "tessin": None,
                                    "graubuenden_engadin": None},
            "movement": {"west_ost": "west_nach_ost",
                         "sued_nord": "gleichzeitig"},
        }]},
    }


class TestPayloadZones(unittest.TestCase):
    """Synoptik 2.0: der LLM bekommt Zonen-Rohwerte inkl. Tagesfenster und
    Zugbahn — die Nord/Sued-Tagespauschale ist raus."""

    def test_payload_has_zone_windows_and_movement(self):
        payload = sl._build_llm_payload(_zone_ctx())
        for zone in config.SYNOPTIC_ZONES:
            self.assertIn(zone, payload)
        # Tagesfenster-Rohwerte
        self.assertIn("precip_windows", payload)
        self.assertIn("afternoon", payload)
        self.assertIn("wet_share", payload)
        self.assertIn("p90_mm", payload)
        # Wind pro Zone inkl. autoritativem Label
        self.assertIn("wind_class", payload)
        self.assertIn("verblasen", payload)
        # Boeenwerte je Fenster muessen beziffert durchkommen — der blosse
        # Anteil sagt nicht, WIE STARK es blaest (Boeenfront 30.07.2026).
        self.assertIn("evening", payload)
        self.assertIn("97.4", payload)
        self.assertIn("88.6", payload)
        # Zugbahn
        self.assertIn("west_nach_ost", payload)
        # Konkrete Werte kommen durch
        self.assertIn("9.2", payload)
        self.assertIn("1360", payload)

    def test_payload_drops_old_nord_sued_block(self):
        ctx = _zone_ctx()
        ctx["precip_pattern"] = {"per_day": [{"date": "2026-05-17",
                                              "alpennord": {"peak_mm": 3.2}}]}
        ctx["wind_pattern"] = {"per_day": [{"date": "2026-05-17",
                                            "alpensued": {"wind_class": "windig"}}]}
        payload = sl._build_llm_payload(ctx)
        self.assertNotIn("precip_pattern", payload)
        self.assertNotIn("wind_pattern", payload)
        self.assertNotIn("alpensued", payload)
        self.assertNotIn("peak_mm", payload)

    def test_zugbahn_omitted_when_no_onset(self):
        ctx = _zone_ctx()
        ctx["zugbahn"]["per_day"][0]["onset_hour_by_group"] = {
            k: None for k in ctx["zugbahn"]["per_day"][0]["onset_hour_by_group"]}
        payload = sl._build_llm_payload(ctx)
        self.assertIn('"zugbahn": null', payload)
        # KEIN char-Feld mehr
        self.assertNotIn('"char"', payload)
        self.assertNotIn('"value"', payload.split("precip_pattern")[1] if "precip_pattern" in payload else "")


# ============================================================================
# Gefahren schweizweit (hazards)
# ============================================================================

def _hz_ctx(dates=("2026-07-05", "2026-07-06")):
    """Ruhiges Strukturfeld: keine Gefahr aktiv, alle Felder vorhanden."""
    ctx = _ctx(dates=dates)
    ctx["precip_zones"] = {"per_day": [
        {"date": d, "zones": {z: {"day": {"wet_share": 0.0, "p90_mm": 0.0,
                                          "gewitter_share": 0.0}} for z in ZONES}}
        for d in dates]}
    ctx["wind_zones"] = _wind_zones(dates, [{z: "unauffaellig" for z in ZONES}
                                            for _ in dates])
    return ctx


def _set_rain(ctx, i, zone, share, p90=1.5, windows=None):
    """windows: {fenster: wet_share} — ohne das bleibt der Tag pauschal."""
    ctx["precip_zones"]["per_day"][i]["zones"][zone]["day"].update(
        {"wet_share": share, "p90_mm": p90})
    if windows:
        ctx["precip_zones"]["per_day"][i]["zones"][zone]["windows"] = {
            w: {"wet_share": v} for w, v in windows.items()}


def _set_wind(ctx, i, zone, cls="verblasen", windows=None):
    """windows: {fenster: share_wind_crit}."""
    z = ctx["wind_zones"]["per_day"][i]["zones"][zone]
    z["wind_class"] = cls
    if windows:
        z["windows"] = {w: {"share_wind_crit": v} for w, v in windows.items()}


RAIN_TEXT = "Regen erfasst ab Mittag den Alpennordhang von Westen her."


class TestHazardChecks(unittest.TestCase):
    def test_all_inactive_on_calm_day(self):
        checks = sl.hazard_checks(_hz_ctx())
        self.assertEqual(len(checks), 2)
        for c in checks:
            self.assertFalse(any(v["active"] for v in c["checks"].values()))

    def test_rain_above_threshold_lists_zones(self):
        ctx = _hz_ctx()
        _set_rain(ctx, 0, "alpennordhang", 0.5)
        checks = sl.hazard_checks(ctx)
        self.assertTrue(checks[0]["checks"]["RAIN"]["active"])
        self.assertEqual(checks[0]["checks"]["RAIN"]["zones"], ["alpennordhang"])
        self.assertEqual(checks[0]["checks"]["RAIN"]["facts"]["wet_share"], 0.5)
        self.assertFalse(checks[1]["checks"]["RAIN"]["active"])

    def test_rain_below_threshold_inactive(self):
        ctx = _hz_ctx()
        _set_rain(ctx, 0, "tessin", 0.1)
        self.assertFalse(sl.hazard_checks(ctx)[0]["checks"]["RAIN"]["active"])

    def test_thunder_from_gewitter_share_or_konvektion(self):
        ctx = _hz_ctx()
        ctx["precip_zones"]["per_day"][0]["zones"]["wallis"]["day"]["gewitter_share"] = 0.1
        ctx["konvektion"] = {"per_day": [
            {}, {"zones": {"tessin": {"gewitter": [["Sopraceneri", "14:00-16:00"]]}}}]}
        checks = sl.hazard_checks(ctx)
        self.assertEqual(checks[0]["checks"]["THUNDER"]["zones"], ["wallis"])
        self.assertEqual(checks[1]["checks"]["THUNDER"]["zones"], ["tessin"])
        self.assertEqual(checks[0]["checks"]["THUNDER"]["level"], "stop")

    def test_foehn_side_level_and_lee_zones(self):
        ctx = _hz_ctx()
        ctx["foehn"] = {"per_day": [{"date": "2026-07-05", "nord_active": True,
                                     "peak_nord": "danger", "nord_hours": 6}]}
        f = sl.hazard_checks(ctx)[0]["checks"]["FOEHN"]
        self.assertTrue(f["active"])
        self.assertEqual(f["level"], "stop")
        self.assertEqual(f["zones"], ["tessin"])
        self.assertEqual(f["facts"]["side"], "nord")
        self.assertEqual(f["facts"]["hours"], 6)

    def test_bise_active(self):
        ctx = _hz_ctx()
        ctx["bise"] = {"per_day": [{"date": "2026-07-06", "active": True,
                                    "strength": "maessig", "delta_p_hpa": 3.1}]}
        checks = sl.hazard_checks(ctx)
        self.assertFalse(checks[0]["checks"]["BISE"]["active"])
        self.assertTrue(checks[1]["checks"]["BISE"]["active"])

    def test_wind_verblasen_is_stop(self):
        ctx = _hz_ctx()
        ctx["wind_zones"]["per_day"][0]["zones"]["alpennordhang"]["wind_class"] = "verblasen"
        ctx["wind_zones"]["per_day"][1]["zones"]["wallis"]["wind_class"] = "stark_eingeschraenkt"
        checks = sl.hazard_checks(ctx)
        self.assertEqual(checks[0]["checks"]["WIND"]["level"], "stop")
        self.assertEqual(checks[1]["checks"]["WIND"]["level"], "warn")
        self.assertEqual(checks[1]["checks"]["WIND"]["zones"], ["wallis"])

    def test_old_cache_without_fields(self):
        checks = sl.hazard_checks(_ctx())
        self.assertFalse(any(v["active"] for c in checks for v in c["checks"].values()))


class TestValidateHazards(unittest.TestCase):
    def setUp(self):
        self.ctx = _hz_ctx()
        _set_rain(self.ctx, 0, "alpennordhang", 0.5)

    def _parsed(self, day0_items, day1_items=None):
        p = _parsed()
        p["hazards"] = [{"items": day0_items}, {"items": day1_items or []}]
        return p

    def test_accept_matching_items(self):
        errors = sl._validate(self._parsed([{"topic": "RAIN", "text": RAIN_TEXT}]), self.ctx)
        self.assertEqual(errors, [])

    def test_missing_field_when_hazard_active(self):
        errors = sl._validate(_parsed(), self.ctx)
        self.assertTrue(any(e["scope"] == "hazards" and e["kind"] == "schema"
                            for e in errors))

    def test_missing_field_ok_when_nothing_active(self):
        self.assertEqual(sl._validate(_parsed(), _hz_ctx()), [])

    def test_active_topic_without_sentence(self):
        errors = sl._validate(self._parsed([]), self.ctx)
        self.assertTrue(any(e["kind"] == "hazard_missing" for e in errors))

    def test_topic_not_active(self):
        errors = sl._validate(self._parsed(
            [{"topic": "RAIN", "text": RAIN_TEXT},
             {"topic": "FOEHN", "text": "Nordfoehn im Tessin."}]), self.ctx)
        self.assertTrue(any(e["kind"] == "hazard_not_active"
                            and e["scope"] == "hazards[0].FOEHN" for e in errors))

    def test_text_without_place(self):
        errors = sl._validate(self._parsed(
            [{"topic": "RAIN", "text": "Ab Mittag verbreitet Regen."}]), self.ctx)
        self.assertTrue(any(e["kind"] == "no_place" for e in errors))

    def test_foehn_word_without_foehn(self):
        errors = sl._validate(self._parsed(
            [{"topic": "RAIN", "text": RAIN_TEXT + " Im Tessin foehnig."}]), self.ctx)
        self.assertTrue(any(e["kind"] == "foehn_not_active" for e in errors))

    def test_thunder_word_without_signal(self):
        errors = sl._validate(self._parsed(
            [{"topic": "RAIN", "text": "Schauer und Gewitter am Alpennordhang."}]), self.ctx)
        self.assertTrue(any(e["kind"] == "gewitter_without_signal" for e in errors))


class TestFinalizeHazards(unittest.TestCase):
    def setUp(self):
        self.ctx = _hz_ctx()
        _set_rain(self.ctx, 0, "alpennordhang", 0.5)
        self.ctx["bise"] = {"per_day": [{"date": "2026-07-05", "active": True,
                                         "strength": "maessig", "delta_p_hpa": 3.0}]}

    def test_checks_and_items_per_day(self):
        p = _parsed()
        p["hazards"] = [{"items": [{"topic": "BISE", "text": "Bise im Mittelland."},
                                   {"topic": "RAIN", "text": RAIN_TEXT}]},
                        {"items": []}]
        hz = sl._finalize(p, self.ctx, attempts=1, unresolved=[])["hazards"]
        self.assertEqual([h["date"] for h in hz], ["2026-07-05", "2026-07-06"])
        # Reihenfolge = HAZARD_TOPICS, nicht LLM-Reihenfolge
        self.assertEqual([i["topic"] for i in hz[0]["items"]], ["RAIN", "BISE"])
        self.assertTrue(hz[0]["checks"]["RAIN"]["active"])
        self.assertEqual(hz[1]["items"], [])

    def test_inactive_topic_dropped_even_without_prune(self):
        p = _parsed()
        p["hazards"] = [{"items": [{"topic": "FOEHN", "text": "Foehn im Tessin."}]},
                        {"items": [{"topic": "RAIN", "text": RAIN_TEXT}]}]
        hz = sl._finalize(p, self.ctx, attempts=1, unresolved=[])["hazards"]
        self.assertEqual(hz[0]["items"], [])
        self.assertEqual(hz[1]["items"], [])

    def test_prune_drops_only_bad_item(self):
        p = _parsed()
        p["hazards"] = [{"items": [{"topic": "RAIN", "text": "Verbreitet Regen."},
                                   {"topic": "BISE", "text": "Bise im Mittelland."}]},
                        {"items": []}]
        hz = sl._finalize(p, self.ctx, attempts=4, unresolved=[], prune=True)["hazards"]
        self.assertEqual([i["topic"] for i in hz[0]["items"]], ["BISE"])

    def test_checks_present_without_llm_hazards(self):
        hz = sl._finalize(_parsed(), self.ctx, attempts=1, unresolved=[])["hazards"]
        self.assertTrue(hz[0]["checks"]["BISE"]["active"])
        self.assertEqual(hz[0]["items"], [])

    def test_payload_carries_active_hazards(self):
        payload = sl._build_llm_payload(self.ctx)
        self.assertIn('"hazards_per_day"', payload)
        self.assertIn('"RAIN"', payload)


# ============================================================================
# Tagesverlauf und Folgetag — die Warnung darf keine Tagespauschale sein
# ============================================================================

class TestDayShape(unittest.TestCase):
    def test_none_without_window_data(self):
        self.assertIsNone(sl._day_shape({}))

    def test_ganztags(self):
        sh = sl._day_shape({"tessin": ["morning", "midday", "afternoon", "evening"]})
        self.assertEqual(sh["shape"], "ganztags")

    def test_ab_nachmittag(self):
        sh = sl._day_shape({"alpennordhang": ["afternoon", "evening"]})
        self.assertEqual((sh["shape"], sh["from"]), ("ab", "afternoon"))

    def test_bis_mittag(self):
        sh = sl._day_shape({"alpennordhang": ["morning", "midday"]})
        self.assertEqual((sh["shape"], sh["to"]), ("bis", "midday"))

    def test_nur_ein_fenster(self):
        self.assertEqual(sl._day_shape({"wallis": ["midday"]})["shape"], "nur")

    def test_spanne_in_der_tagesmitte(self):
        sh = sl._day_shape({"wallis": ["midday", "afternoon"]})
        self.assertEqual((sh["shape"], sh["from"], sh["to"]),
                         ("spanne", "midday", "afternoon"))

    def test_luecke_ist_wechselnd(self):
        sh = sl._day_shape({"wallis": ["morning", "evening"]})
        self.assertEqual(sh["shape"], "wechselnd")

    def test_zonen_werden_vereinigt(self):
        sh = sl._day_shape({"alpennordhang": ["midday"],
                            "tessin": ["afternoon", "evening"]})
        self.assertEqual(sh["hit"], ["midday", "afternoon", "evening"])

    def test_unterschiedliche_zonen_sind_gemischt_nicht_ganztags(self):
        """Vorfall 16.09.2026: Alpennordhang ganztags, Wallis nur morgens und
        abends — die Vereinigung hiess 'ganztags', die KI schrieb 'all day'."""
        full = ["morning", "midday", "afternoon", "evening"]
        sh = sl._day_shape({"alpennordhang": full,
                            "wallis": ["morning", "evening"]})
        self.assertEqual(sh["shape"], "gemischt")

    def test_gleicher_verlauf_bleibt_eine_form(self):
        sh = sl._day_shape({"alpennordhang": ["afternoon", "evening"],
                            "tessin": ["afternoon", "evening"]})
        self.assertEqual((sh["shape"], sh["from"]), ("ab", "afternoon"))


class TestHazardWindows(unittest.TestCase):
    def test_rain_windows_per_zone(self):
        ctx = _hz_ctx()
        _set_rain(ctx, 0, "alpennordhang", 0.6,
                  windows={"morning": 0.0, "midday": 0.3, "afternoon": 0.7,
                           "evening": 0.5})
        f = sl.hazard_checks(ctx)[0]["checks"]["RAIN"]["facts"]
        self.assertEqual(f["windows"],
                         {"alpennordhang": ["midday", "afternoon", "evening"]})
        self.assertEqual(f["day_shape"]["shape"], "ab")
        self.assertEqual(f["day_shape"]["from"], "midday")

    def test_dry_morning_is_not_in_the_window_list(self):
        ctx = _hz_ctx()
        _set_rain(ctx, 0, "wallis", 0.5,
                  windows={"morning": 0.05, "midday": 0.6, "afternoon": 0.6,
                           "evening": 0.6})
        f = sl.hazard_checks(ctx)[0]["checks"]["RAIN"]["facts"]
        self.assertNotIn("morning", f["windows"]["wallis"])

    def test_wind_windows_use_share_wind_crit(self):
        ctx = _hz_ctx()
        _set_wind(ctx, 0, "alpennordhang", "verblasen",
                  windows={"morning": 0.1, "midday": 0.4, "afternoon": 0.8,
                           "evening": 0.9})
        f = sl.hazard_checks(ctx)[0]["checks"]["WIND"]["facts"]
        self.assertEqual(f["windows"],
                         {"alpennordhang": ["midday", "afternoon", "evening"]})
        self.assertEqual(f["day_shape"]["shape"], "ab")

    def test_thunder_windows_from_konvektion_time_span(self):
        ctx = _hz_ctx()
        ctx["konvektion"] = {"per_day": [
            {"zones": {"tessin": {"gewitter": [["Sopraceneri", "14:00-16:00"]]}}},
            {}]}
        f = sl.hazard_checks(ctx)[0]["checks"]["THUNDER"]["facts"]
        self.assertEqual(f["windows"], {"tessin": ["afternoon"]})
        self.assertEqual(f["day_shape"]["shape"], "nur")

    def test_no_windows_in_old_cache(self):
        ctx = _hz_ctx()
        _set_rain(ctx, 0, "tessin", 0.4)
        f = sl.hazard_checks(ctx)[0]["checks"]["RAIN"]["facts"]
        self.assertEqual(f["windows"], {})
        self.assertIsNone(f["day_shape"])


class TestFoehnCourse(unittest.TestCase):
    """Foehn: Tagesverlauf, Staerke und die Spur in den Winddaten."""

    def _ctx(self, win_hours, peak="caution"):
        """win_hours: {fenster: stunden} fuer Nordfoehn an Tag 0."""
        ctx = _hz_ctx()
        ctx["foehn"] = {"per_day": [{
            "date": "2026-07-05", "nord_active": True, "peak_nord": peak,
            "nord_hours": sum(win_hours.values()),
            "nord_windows": {w: {"hours": h, "peak": peak if h else "none"}
                             for w, h in win_hours.items()},
        }]}
        return ctx

    def test_windows_map_to_the_lee_zone(self):
        f = sl.hazard_checks(self._ctx({"morning": 0, "midday": 2,
                                        "afternoon": 4, "evening": 3})
                             )[0]["checks"]["FOEHN"]["facts"]
        self.assertEqual(f["windows"], {"tessin": ["midday", "afternoon", "evening"]})
        self.assertEqual(f["day_shape"]["shape"], "ab")

    def test_course_increases_towards_evening(self):
        f = sl.hazard_checks(self._ctx({"morning": 1, "midday": 1,
                                        "afternoon": 4, "evening": 4})
                             )[0]["checks"]["FOEHN"]["facts"]
        self.assertEqual(f["course"], "zunehmend")

    def test_course_eases_off(self):
        f = sl.hazard_checks(self._ctx({"morning": 4, "midday": 4,
                                        "afternoon": 1, "evening": 0})
                             )[0]["checks"]["FOEHN"]["facts"]
        self.assertEqual(f["course"], "abflauend")

    def test_course_steady(self):
        f = sl.hazard_checks(self._ctx({"morning": 3, "midday": 3,
                                        "afternoon": 3, "evening": 3})
                             )[0]["checks"]["FOEHN"]["facts"]
        self.assertEqual(f["course"], "gleich")

    def test_danger_peak_beats_hours(self):
        """Eine Stunde 'danger' am Nachmittag wiegt schwerer als vier
        Stunden 'caution' am Morgen — sonst heisst ein Tag, der erst
        gefaehrlich wird, 'abflauend'."""
        ctx = self._ctx({"morning": 4, "midday": 0, "afternoon": 1, "evening": 0})
        wins = ctx["foehn"]["per_day"][0]["nord_windows"]
        wins["morning"]["peak"] = "caution"
        wins["afternoon"]["peak"] = "danger"
        f = sl.hazard_checks(ctx)[0]["checks"]["FOEHN"]["facts"]
        self.assertEqual(f["course"], "zunehmend")

    def test_lee_gusts_come_from_the_wind_windows(self):
        ctx = self._ctx({"morning": 0, "midday": 2, "afternoon": 4, "evening": 2})
        ctx["wind_zones"]["per_day"][0]["zones"]["tessin"]["windows"] = {
            "midday": {"p90_gust_kmh": 38.0}, "afternoon": {"p90_gust_kmh": 55.4}}
        f = sl.hazard_checks(ctx)[0]["checks"]["FOEHN"]["facts"]
        self.assertEqual(f["lee_gust_kmh"], 55)

    def test_old_cache_without_foehn_windows(self):
        ctx = _hz_ctx()
        ctx["foehn"] = {"per_day": [{"date": "2026-07-05", "nord_active": True,
                                     "peak_nord": "caution", "nord_hours": 3}]}
        f = sl.hazard_checks(ctx)[0]["checks"]["FOEHN"]["facts"]
        self.assertEqual(f["windows"], {})
        self.assertIsNone(f["day_shape"])
        self.assertIsNone(f["course"])

    def test_payload_carries_course_and_gusts(self):
        ctx = self._ctx({"morning": 0, "midday": 2, "afternoon": 4, "evening": 2})
        ctx["wind_zones"]["per_day"][0]["zones"]["tessin"]["windows"] = {
            "afternoon": {"p90_gust_kmh": 55.4}}
        payload = sl._build_llm_payload(ctx)
        hz = payload.split('"hazards_per_day"')[1]
        self.assertIn('"course": "zunehmend"', hz)
        self.assertIn('"lee_gust_kmh": 55', hz)
        self.assertIn('"peak": "caution"', hz)


class TestHazardOutlook(unittest.TestCase):
    def test_hazard_over_tomorrow(self):
        ctx = _hz_ctx()
        _set_rain(ctx, 0, "alpennordhang", 0.6)
        tm = sl.hazard_checks(ctx)[0]["checks"]["RAIN"]["facts"]["tomorrow"]
        self.assertEqual(tm, {"active": False, "trend": "vorbei"})

    def test_increasing_and_easing(self):
        ctx = _hz_ctx(dates=("2026-07-05", "2026-07-06", "2026-07-07"))
        _set_rain(ctx, 0, "alpennordhang", 0.3)
        _set_rain(ctx, 1, "alpennordhang", 0.9)
        _set_rain(ctx, 2, "alpennordhang", 0.3)
        checks = sl.hazard_checks(ctx)
        self.assertEqual(
            checks[0]["checks"]["RAIN"]["facts"]["tomorrow"]["trend"], "zunehmend")
        self.assertEqual(
            checks[1]["checks"]["RAIN"]["facts"]["tomorrow"]["trend"], "abklingend")

    def test_same_strength_is_gleich(self):
        ctx = _hz_ctx()
        _set_rain(ctx, 0, "alpennordhang", 0.5)
        _set_rain(ctx, 1, "alpennordhang", 0.5)
        self.assertEqual(
            sl.hazard_checks(ctx)[0]["checks"]["RAIN"]["facts"]["tomorrow"]["trend"],
            "gleich")

    def test_last_day_has_no_outlook(self):
        ctx = _hz_ctx()
        _set_rain(ctx, 1, "alpennordhang", 0.5)
        self.assertIsNone(
            sl.hazard_checks(ctx)[1]["checks"]["RAIN"]["facts"]["tomorrow"])

    def test_wind_trend_counts_zones(self):
        ctx = _hz_ctx()
        _set_wind(ctx, 0, "alpennordhang")
        _set_wind(ctx, 1, "alpennordhang")
        _set_wind(ctx, 1, "wallis")
        self.assertEqual(
            sl.hazard_checks(ctx)[0]["checks"]["WIND"]["facts"]["tomorrow"]["trend"],
            "zunehmend")


class TestHazardProse(unittest.TestCase):
    """Der Gefahren-Satz ist ein Wetterbericht, kein Zonen-Protokoll."""

    def setUp(self):
        self.ctx = _hz_ctx()
        _set_rain(self.ctx, 0, "alpennordhang", 0.6)

    def _errors(self, text):
        p = _parsed()
        p["hazards"] = [{"items": [{"topic": "RAIN", "text": text}]}, {"items": []}]
        return sl._validate(p, self.ctx)

    def test_zone_protocol_rejected(self):
        errors = self._errors("Alpennordhang: nass, Tessin: trocken.")
        self.assertTrue(any(e["kind"] == "enumeration" for e in errors))

    def test_bullet_list_rejected(self):
        errors = self._errors("Regen am Alpennordhang \u00b7 Tessin trocken.")
        self.assertTrue(any(e["kind"] == "enumeration" for e in errors))

    def test_flowing_sentence_accepted(self):
        errors = self._errors("Ab Mittag greift von Westen her Regen auf die "
                              "Alpennordseite ueber, im Tessin bleibt es trocken.")
        self.assertEqual(errors, [])


class TestHazardTimeRequired(unittest.TestCase):
    """Sagt der Code 'nicht ganztags', MUSS der Satz die Tageszeit nennen."""

    def _ctx_ab_mittag(self):
        ctx = _hz_ctx()
        _set_rain(ctx, 0, "alpennordhang", 0.6,
                  windows={"morning": 0.0, "midday": 0.5, "afternoon": 0.7,
                           "evening": 0.6})
        return ctx

    def _parsed_rain(self, text):
        p = _parsed()
        p["hazards"] = [{"items": [{"topic": "RAIN", "text": text}]}, {"items": []}]
        return p

    def test_missing_time_is_an_error(self):
        errors = sl._validate(
            self._parsed_rain("Regen erfasst den Alpennordhang von Westen her."),
            self._ctx_ab_mittag())
        self.assertTrue(any(e["kind"] == "no_time"
                            and e["scope"] == "hazards[0].RAIN" for e in errors))

    def test_time_reference_accepted(self):
        errors = sl._validate(
            self._parsed_rain("Ab Mittag Regen am Alpennordhang, Tessin bleibt trocken."),
            self._ctx_ab_mittag())
        self.assertEqual(errors, [])

    def test_no_time_required_when_all_day(self):
        ctx = _hz_ctx()
        _set_rain(ctx, 0, "alpennordhang", 0.8,
                  windows={"morning": 0.7, "midday": 0.8, "afternoon": 0.8,
                           "evening": 0.7})
        errors = sl._validate(
            self._parsed_rain("Regen am Alpennordhang, Tessin bleibt trocken."), ctx)
        self.assertEqual(errors, [])

    def test_prune_drops_sentence_without_time(self):
        hz = sl._finalize(self._parsed_rain("Regen am Alpennordhang."),
                          self._ctx_ab_mittag(), attempts=4, unresolved=[],
                          prune=True)["hazards"]
        self.assertEqual(hz[0]["items"], [])

    def test_payload_carries_day_shape(self):
        payload = sl._build_llm_payload(self._ctx_ab_mittag())
        self.assertIn('"day_shape": "ab"', payload)

    def test_payload_hides_the_next_day_trend(self):
        """Der Folgetag-Trend darf den LLM nicht erreichen — der Satz steht
        in der Tages-Sektion und muss tagesrein bleiben."""
        payload = sl._build_llm_payload(self._ctx_ab_mittag())
        self.assertNotIn('"tomorrow"', payload.split('"hazards_per_day"')[1])


class TestHazardMixedTiming(unittest.TestCase):
    """day_shape 'gemischt': der Satz muss die Zonen zeitlich unterscheiden."""

    def setUp(self):
        full = {"morning": 0.6, "midday": 0.6, "afternoon": 0.6, "evening": 0.6}
        self.ctx = _hz_ctx()
        _set_wind(self.ctx, 0, "alpennordhang", windows={k: 0.8 for k in full})
        _set_wind(self.ctx, 0, "wallis", windows={"morning": 0.5, "midday": 0.0,
                                                  "afternoon": 0.0, "evening": 0.5})

    def _errors(self, text):
        p = _parsed()
        p["hazards"] = [{"items": [{"topic": "WIND", "text": text}]}, {"items": []}]
        return sl._validate(p, self.ctx)

    def test_one_time_for_all_rejected(self):
        errors = self._errors("Strong wind blows across the northern Alps and "
                              "Valais all day.")
        self.assertTrue(any(e["kind"] == "time_not_differentiated" for e in errors))

    def test_differentiated_sentence_accepted(self):
        errors = self._errors("Strong wind blows over the northern Alps all day, "
                              "in Valais only in the morning and again in the evening.")
        self.assertEqual(errors, [])


class TestHazardOnset(unittest.TestCase):
    """Genannter Beginn je Zone darf nicht spaeter liegen als die Daten."""

    WINDOWS = {"alpennordhang": ["morning", "midday", "afternoon", "evening"],
               "wallis": ["morning", "afternoon", "evening"],
               "graubuenden_engadin": ["morning", "afternoon", "evening"]}

    def test_incident_wind_sentence_is_caught(self):
        """Der Satz aus der Vorschau vom 16.09.2026."""
        text = ("Strong upper wind and gusts blow out the northern Alps all day, "
                "while Valais and the Grisons turn critical from the afternoon "
                "onwards; Ticino stays calmer until the evening.")
        late = {z for z, _, _ in sl._onset_too_late(text, self.WINDOWS)}
        self.assertEqual(late, {"wallis", "graubuenden_engadin"})

    def test_correct_rain_sentence_passes(self):
        windows = {"alpennordhang": ["morning", "midday", "afternoon", "evening"],
                   "wallis": ["morning", "afternoon", "evening"],
                   "tessin": ["afternoon", "evening"],
                   "graubuenden_engadin": ["midday", "afternoon", "evening"]}
        text = ("Widespread rain sets in over the northern Alps from the morning and "
                "spreads eastwards, reaching the Grisons by midday and Ticino by the "
                "afternoon; Valais sees rain in the morning and again from the "
                "afternoon, with a drier midday gap.")
        self.assertEqual(sl._onset_too_late(text, windows), [])

    def test_earlier_than_data_is_allowed(self):
        """Zu frueh gewarnt ist nicht gefaehrlich — kein Fehler."""
        self.assertEqual(sl._onset_too_late(
            "Ab dem Morgen Regen im Tessin.", {"tessin": ["afternoon", "evening"]}), [])

    def test_until_is_not_an_onset(self):
        self.assertEqual(sl._onset_too_late(
            "Regen im Wallis bis Mittag.", {"wallis": ["morning", "midday"]}), [])

    def test_unaffected_zone_is_not_checked(self):
        self.assertEqual(sl._onset_too_late(
            "Im Tessin bleibt es bis zum Abend trocken.",
            {"alpennordhang": ["morning"]}), [])

    def test_german_sentence(self):
        late = sl._onset_too_late(
            "Ab Nachmittag greift Regen auf die Alpennordseite ueber.",
            {"alpennordhang": ["midday", "afternoon", "evening"]})
        self.assertEqual(late, [("alpennordhang", "afternoon", "midday")])

    def test_validator_reports_onset_too_late(self):
        ctx = _hz_ctx()
        _set_wind(ctx, 0, "wallis", windows={"morning": 0.5, "midday": 0.0,
                                             "afternoon": 0.5, "evening": 0.5})
        p = _parsed()
        p["hazards"] = [{"items": [{"topic": "WIND", "text":
                         "Im Wallis wird der Wind ab Nachmittag kritisch."}]},
                        {"items": []}]
        errors = sl._validate(p, ctx)
        self.assertTrue(any(e["kind"] == "onset_too_late" for e in errors))


class TestShortSentences(unittest.TestCase):
    """Wunsch User 16.09.2026: KI-Saetze kurz und ohne Urteil."""

    def setUp(self):
        self.ctx = _hz_ctx()
        _set_rain(self.ctx, 0, "alpennordhang", 0.6)

    def _hazard_errors(self, text):
        p = _parsed()
        p["hazards"] = [{"items": [{"topic": "RAIN", "text": text}]}, {"items": []}]
        return sl._validate(p, self.ctx)

    def test_long_hazard_sentence_rejected(self):
        """Der Regen-Satz aus der Vorschau vom 16.09.2026 (58 Woerter, 2 Saetze)."""
        text = ("Rain spreads in from the west over the northern Alps from the morning "
                "and reaches the Grisons by midday and Ticino by the afternoon; Valais "
                "sees rain in the morning and again in the afternoon. The rain is "
                "widespread and solid, with heavy peaks in Ticino from the afternoon "
                "and in the Grisons from midday.")
        kinds = {e["kind"] for e in self._hazard_errors(text)}
        self.assertIn("too_long", kinds)
        self.assertIn("more_than_one_sentence", kinds)

    def test_short_hazard_sentence_accepted(self):
        self.assertEqual(self._hazard_errors(
            "Ab Mittag greift Regen von Westen auf die Alpennordseite ueber."), [])

    def test_verdict_in_hazard_rejected(self):
        errors = self._hazard_errors(
            "Regen an der Alpennordseite macht das Fliegen unmoeglich.")
        self.assertTrue(any(e["kind"] == "verdict" for e in errors))

    def test_day_lines_required(self):
        p = _parsed()
        del p["day_lines"]
        errors = sl._validate(p, _hz_ctx())
        self.assertTrue(any(e["scope"] == "day_lines" and e["kind"] == "schema"
                            for e in errors))

    def test_day_line_too_long_and_verdict(self):
        p = _parsed()
        p["day_lines"][0] = ("Ein Tief bei Island lenkt feuchte Luft an die Alpen, es regnet "
                             "verbreitet und der Wind ist so stark, dass kein nutzbares "
                             "Fenster bleibt.")
        kinds = {e["kind"] for e in sl._validate(p, _hz_ctx())
                 if e["scope"] == "day_lines[0]"}
        self.assertIn("too_long", kinds)
        self.assertIn("verdict", kinds)

    def test_day_line_other_day_rejected(self):
        p = _parsed()
        p["day_lines"][0] = "Regen heute, ab Donnerstag trocken."
        self.assertTrue(any(e["kind"] == "cross_day" for e in sl._validate(p, _hz_ctx())))

    def test_day_lines_in_finalize(self):
        p = _parsed()
        p["day_lines"] = ["Ein Tief bringt Regen an die Alpen.", ""]
        out = sl._finalize(p, _hz_ctx(), attempts=1, unresolved=[])["day_lines"]
        self.assertEqual(out[0], {"date": "2026-07-05",
                                  "text": "Ein Tief bringt Regen an die Alpen."})
        self.assertEqual(out[1]["text"], "")

    def test_prune_empties_bad_day_line(self):
        p = _parsed()
        p["day_lines"][0] = "Ideale Bedingungen fuer lange Fluege."
        out = sl._finalize(p, _hz_ctx(), attempts=4, unresolved=[], prune=True)["day_lines"]
        self.assertEqual(out[0]["text"], "")


class TestLanguageDrift(unittest.TestCase):
    """Vorfall 16.09.2026: im EN-Modus kam nach Korrekturrunden alles deutsch."""

    def setUp(self):
        self._lang = config.LANG
        config.LANG = "en"

    def tearDown(self):
        config.LANG = self._lang

    def test_correction_message_names_the_language(self):
        msg = sl._build_correction_message([{"scope": "lead", "message": "zu lang"}])
        self.assertIn("OUTPUT LANGUAGE: ENGLISH", msg)

    def test_german_text_is_flagged_in_english_mode(self):
        p = _parsed(lead="A low near Iceland steers moist air against the Alps.")
        p["day_lines"] = ["Ein Tief bei Island lenkt feuchte Luft an die Alpen.",
                          "Dry and calm air over the Alps."]
        errors = [e for e in sl._validate(p, _ctx()) if e["kind"] == "wrong_language"]
        self.assertEqual(len(errors), 1)
        self.assertIn("day_lines[0]", errors[0]["message"])
        self.assertNotIn("day_lines[1]", errors[0]["message"])

    def test_umlaut_is_enough(self):
        self.assertTrue(sl._looks_german("Rain over Graub\u00fcnden from midday."))

    def test_english_sentences_pass(self):
        for text in ("Rain spreads in from the west over the northern Alps from midday.",
                     "Strong wind blows out the northern Alps all day, while Ticino stays calmer.",
                     "Moderate north foehn breaks through over Ticino, gusts around 35 km/h."):
            self.assertFalse(sl._looks_german(text), text)

    def test_german_mode_is_not_checked(self):
        config.LANG = "de"
        p = _parsed()
        self.assertEqual([e for e in sl._validate(p, _ctx())
                          if e["kind"] == "wrong_language"], [])


class TestHazardDayScope(unittest.TestCase):
    """Warnungen stehen in der Tages-Sektion: kein anderer Tag im Satz."""

    def setUp(self):
        self.ctx = _hz_ctx()
        _set_rain(self.ctx, 0, "alpennordhang", 0.6)

    def _errors(self, text):
        p = _parsed()
        p["hazards"] = [{"items": [{"topic": "RAIN", "text": text}]}, {"items": []}]
        return sl._validate(p, self.ctx)

    def test_folgetag_rejected(self):
        errors = self._errors("Regen an der Alpennordseite. Am Folgetag klingt er ab.")
        self.assertTrue(any(e["kind"] == "cross_day" for e in errors))

    def test_weekday_rejected(self):
        errors = self._errors("Am Donnerstag greift Regen auf die Alpennordseite ueber.")
        self.assertTrue(any(e["kind"] == "cross_day" for e in errors))

    def test_time_of_day_still_allowed(self):
        errors = self._errors("Am Morgen greift Regen auf die Alpennordseite ueber, "
                              "morgens bleibt das Tessin trocken.")
        self.assertEqual(errors, [])

    def test_prune_drops_cross_day_sentence(self):
        p = _parsed()
        p["hazards"] = [{"items": [{"topic": "RAIN",
                                    "text": "Regen an der Alpennordseite, morgen vorbei."}]},
                        {"items": []}]
        hz = sl._finalize(p, self.ctx, attempts=4, unresolved=[], prune=True)["hazards"]
        self.assertEqual(hz[0]["items"], [])


if __name__ == "__main__":
    unittest.main()
