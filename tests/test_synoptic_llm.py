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
                    "windows": {"morning": {"share_wind_crit": 0.91}}}
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


if __name__ == "__main__":
    unittest.main()
