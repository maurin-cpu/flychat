"""Tests: Ein langer Chat-Verlauf darf beim Kuerzen nicht zerbrechen.

Befund 26.10.2026 (validation/chat/BEFUNDE.md, Nachtrag): Ab 40 Nachrichten
schnitt die Kuerzung mitten in eine Tool-Runde. DeepSeek lehnte danach jede
Frage mit 400 ab, bis der Pilot "Neuer Chat" klickte und damit seinen Verlauf
loeschte. Getroffen am 25.09. und 16.10.; der laengste Verlauf im Datensatz
(45 Nachrichten, August) waere bei der naechsten Frage genau so zerbrochen.

Die Bedingung, die DeepSeek prueft: Jede Tool-Antwort folgt auf den Aufruf mit
ihrer id, und jeder Aufruf bekommt alle seine Antworten.
"""
import unittest

from engine.chat_orchestrator import _verlauf_kuerzen, _verlauf_reparieren


def _runde(nr, n_tools):
    """Frage, Aufruf mit n_tools Werkzeugen, Antworten, Schlusstext."""
    ids = [f"call_{nr}_{k}" for k in range(n_tools)]
    return (
        [{"role": "user", "content": f"Frage {nr}"},
         {"role": "assistant", "content": "", "reasoning_content": "r",
          "tool_calls": [{"id": i, "type": "function",
                          "function": {"name": "get_spot_analysis", "arguments": "{}"}} for i in ids]}]
        + [{"role": "tool", "tool_call_id": i, "name": "get_spot_analysis", "content": "{}"} for i in ids]
        + [{"role": "assistant", "content": f"Antwort {nr}", "reasoning_content": "r"}]
    )


def _gueltig(messages):
    offen = set()
    for m in messages:
        if m["role"] == "tool":
            if m["tool_call_id"] not in offen:
                return False
            offen.discard(m["tool_call_id"])
        else:
            if offen:
                return False
            if m["role"] == "assistant":
                offen = {t["id"] for t in m.get("tool_calls") or []}
    return not offen


def _verlauf(*tools_je_runde):
    msgs = [{"role": "system", "content": "s"}]
    for nr, n in enumerate(tools_je_runde):
        msgs += _runde(nr, n)
    return msgs


class TestKuerzen(unittest.TestCase):
    def test_august_verlauf_bleibt_gueltig(self):
        # 45 Nachrichten wie der Romandie-Verlauf vom August, plus neue Frage.
        msgs = _verlauf(5, 3, 2, 0, 3, 3, 4) + [{"role": "user", "content": "neu"}]
        self.assertGreater(len(msgs), 40)
        alt = msgs[:2] + msgs[-38:]
        self.assertFalse(_gueltig(alt), "Testfall muss den alten Fehler zeigen")
        _verlauf_kuerzen(msgs, 40)
        self.assertLessEqual(len(msgs), 40)
        self.assertTrue(_gueltig(msgs))
        self.assertEqual(msgs[-1]["content"], "neu")
        self.assertEqual(msgs[0]["role"], "system")

    def test_jede_schnittstelle_ergibt_einen_gueltigen_verlauf(self):
        basis = _verlauf(3, 1, 4, 2, 6, 1, 3, 2)
        for max_n in range(10, len(basis) + 2):
            msgs = list(basis) + [{"role": "user", "content": "neu"}]
            _verlauf_kuerzen(msgs, max_n)
            self.assertTrue(_gueltig(msgs), f"max_n={max_n}")

    def test_kurzer_verlauf_unveraendert(self):
        msgs = _verlauf(2, 1)
        vorher = list(msgs)
        _verlauf_kuerzen(msgs, 40)
        self.assertEqual(msgs, vorher)


class TestReparieren(unittest.TestCase):
    def test_verwaiste_tool_antwort_wird_entfernt(self):
        msgs = _verlauf(3, 2)
        kaputt = msgs[:2] + msgs[4:]   # Aufruf weg, zwei seiner Antworten bleiben
        self.assertFalse(_gueltig(kaputt))
        self.assertGreater(_verlauf_reparieren(kaputt), 0)
        self.assertTrue(_gueltig(kaputt))

    def test_aufruf_ohne_antwort_wird_entfernt(self):
        msgs = _verlauf(2) + [{"role": "user", "content": "neu"}]
        del msgs[3]                    # eine von zwei Antworten fehlt
        _verlauf_reparieren(msgs)
        self.assertTrue(_gueltig(msgs))
        self.assertEqual(msgs[-1]["content"], "neu")

    def test_gueltiger_verlauf_bleibt_unberuehrt(self):
        msgs = _verlauf(3, 0, 2)
        vorher = list(msgs)
        self.assertEqual(_verlauf_reparieren(msgs), 0)
        self.assertEqual(msgs, vorher)


if __name__ == "__main__":
    unittest.main()
