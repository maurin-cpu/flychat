"""i18n-Sync-Waechter: der Fingerabdruck haengt am Inhalt, nicht an Zeilenenden.

Ein Stempel von Windows (CRLF) muss auf dem Server (LF) gleich gelten — sonst
meldet der Waechter Drift, wo keine ist (04.10.2026: 13 Fehlalarme).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_i18n_sync as c  # noqa: E402


def test_line_endings_and_bom_do_not_change_the_hash(tmp_path):
    lf = tmp_path / "lf.md"
    crlf = tmp_path / "crlf.md"
    bom = tmp_path / "bom.md"
    lf.write_bytes(b"Zeile eins\nZeile zwei\n")
    crlf.write_bytes(b"Zeile eins\r\nZeile zwei\r\n")
    bom.write_bytes(b"\xef\xbb\xbfZeile eins\r\nZeile zwei\r\n")
    assert c._sha256(lf) == c._sha256(crlf) == c._sha256(bom)


def test_real_change_changes_the_hash(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_bytes(b"Schwelle 30 km/h\n")
    b.write_bytes(b"Schwelle 40 km/h\n")
    assert c._sha256(a) != c._sha256(b)


def test_repo_is_in_sync():
    """Alle EN-Bausteine sind auf dem Stand ihrer DE-Quelle gestempelt."""
    stamps = c.load_manifest().get("pairs", {})
    for p in c.discover_pairs():
        assert p["de_exists"], p["en"]
        assert stamps.get(p["en"]) == c._sha256(p["_de_abs"]), (
            f"{p['en']}: DE-Quelle geaendert — EN nachziehen, dann "
            f"`python scripts/check_i18n_sync.py --update`")


def test_every_de_block_has_an_en_twin():
    """Jeder deutsche Prompt-Baustein hat eine englische Fassung — sonst laeuft
    der EN-Modus still mit deutschem Prompt (10.10.2026: 8 fehlten)."""
    assert c.missing_en() == []
