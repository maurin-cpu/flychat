# -*- coding: utf-8 -*-
"""Schutz fuer die Regionen-Umbenennung 2026-08 in der Abo-Datenbank.

Die Abos halten Regions-IDs, keine Namen. Die Umbenennung enthaelt eine Kette:

    schwarzsee_gantrisch -> freiburger_voralpen -> berner_oberland -> emmental

Das vorhandene Verfahren von 2026-04 ersetzt sequenziell je Paar per SQL-
REPLACE. Auf diese Kette angewandt haette es aus einem Abo auf
schwarzsee_gantrisch nacheinander freiburger_voralpen, berner_oberland und
emmental gemacht - drei Regionen waeren zu einer zusammengefallen, still und
ohne Fehlermeldung.

Zwei Dinge muessen deshalb halten, und beide werden hier geprueft:
  1. jede id wandert genau EINE Stufe
  2. der Block laeuft nur einmal, auch wenn die App x-mal startet
     ("berner_oberland" ist zugleich Alt- und Neuwert)
"""
import json
import sqlite3

import pytest

from subscriber import SubscriberManager


KETTE = ["schwarzsee_gantrisch", "freiburger_voralpen",
         "berner_oberland", "seeland_emmental"]
KETTE_ERWARTET = ["freiburger_voralpen", "berner_oberland",
                  "emmental", "seeland"]


def _db_ohne_migration(tmp_path, abos):
    """Legt eine DB an und setzt sie auf den Stand VOR der 2026-08-Migration."""
    pfad = tmp_path / "subscribers.db"
    SubscriberManager(pfad)
    conn = sqlite3.connect(pfad)
    conn.execute("DELETE FROM schema_migrations WHERE name = ?",
                 (SubscriberManager._MIGRATION_KEY_2026_08,))
    for i, regionen in enumerate(abos, start=1):
        conn.execute(
            "INSERT INTO subscribers (email, regions, action_token) VALUES (?, ?, ?)",
            (f"pilot{i}@example.ch", json.dumps(regionen), f"token{i}"),
        )
    conn.commit()
    conn.close()
    return pfad


def _regionen(pfad):
    conn = sqlite3.connect(pfad)
    try:
        return [json.loads(r) for (r,) in
                conn.execute("SELECT regions FROM subscribers ORDER BY id")]
    finally:
        conn.close()


def test_kette_faellt_nicht_zusammen(tmp_path):
    """Vier Kettenglieder in einem Abo bleiben vier verschiedene Regionen."""
    pfad = _db_ohne_migration(tmp_path, [KETTE])
    SubscriberManager(pfad)                       # Migration laeuft beim Init
    (regionen,) = _regionen(pfad)
    assert regionen == KETTE_ERWARTET
    assert len(set(regionen)) == 4


def test_anzahl_regionen_je_abo_bleibt(tmp_path):
    abos = [
        KETTE,
        ["jura_ost", "mittelland_ost", "tessin_nord", "waadtlaender_alpen"],
        ["mittelland_ost", "surselva", "jura_zentral"],   # keine davon wird umbenannt
        [],
    ]
    pfad = _db_ohne_migration(tmp_path, abos)
    SubscriberManager(pfad)
    assert [len(r) for r in _regionen(pfad)] == [len(a) for a in abos]


def test_unbenannte_regionen_bleiben_unangetastet(tmp_path):
    unberuehrt = ["mittelland_ost", "surselva", "jura_zentral", "unterwallis"]
    pfad = _db_ohne_migration(tmp_path, [unberuehrt])
    SubscriberManager(pfad)
    assert _regionen(pfad) == [unberuehrt]


def test_migration_ist_einmalig(tmp_path):
    """Mehrfacher App-Start darf die Kette nicht weiterschieben."""
    pfad = _db_ohne_migration(tmp_path, [KETTE])
    for _ in range(4):
        SubscriberManager(pfad)
    assert _regionen(pfad) == [KETTE_ERWARTET]


def test_marker_wird_gesetzt(tmp_path):
    pfad = _db_ohne_migration(tmp_path, [KETTE])
    SubscriberManager(pfad)
    conn = sqlite3.connect(pfad)
    try:
        treffer = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE name = ?",
            (SubscriberManager._MIGRATION_KEY_2026_08,)).fetchone()
    finally:
        conn.close()
    assert treffer is not None


def test_mapping_deckt_die_csv_ab():
    """Die Liste im Code muss zur Mapping-Tabelle passen - sonst driftet sie ab."""
    import csv
    from pathlib import Path

    tabelle = Path(__file__).resolve().parent.parent / "data" / "region_renames_2026-08.csv"
    if not tabelle.exists():                      # Tabelle ist optional im Deploy
        pytest.skip("region_renames_2026-08.csv nicht vorhanden")
    with tabelle.open(encoding="utf-8") as fh:
        aus_csv = {(r["alt"], r["neu"]) for r in csv.DictReader(fh, delimiter=";")
                   if r["typ"] == "id"}
    assert aus_csv == set(SubscriberManager._REGION_ID_RENAMES_2026_08)
