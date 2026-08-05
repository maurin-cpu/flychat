"""Simulation der answer_stream Tool-Schleife mit den neuen Tools.

Kein echter LLM/API-Key noetig: ein geskripteter Fake-Client emittiert
genau die Tool-Calls, die DeepSeek bei einer Detailfrage ausloesen wuerde.
Die ECHTE Produktionsschleife (answer_stream), _dispatch_tool und
_resolve_spot_by_name werden dabei ungestubbt durchlaufen.

Ziel: beweisen, dass Tool-Call -> Dispatch -> Ergebnis zurueck an Modell
-> finale Antwort sauber funktioniert.
"""
import json
import logging
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import engine.chat_orchestrator as co
from engine.chat_orchestrator import ChatOrchestratorMixin

logging.disable(logging.CRITICAL)
# Cache-Logging braucht response.usage — fuer die Simulation neutralisieren.
co._log_prompt_cache_usage = lambda *a, **k: None

TODAY = date.today().isoformat()


# ── Fake-LLM-Objekte (Form wie OpenAI/DeepSeek SDK) ──────────────────────────
class FakeFn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments

class FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.type = "function"
        self.function = FakeFn(name, arguments)

class FakeMessage:
    def __init__(self, content="", tool_calls=None, reasoning_content=None):
        self.content = content
        self.tool_calls = tool_calls
        self.reasoning_content = reasoning_content

class FakeChoice:
    def __init__(self, message, finish_reason):
        self.message = message
        self.finish_reason = finish_reason

class FakeResponse:
    def __init__(self, message, finish_reason):
        self.choices = [FakeChoice(message, finish_reason)]
        self.usage = None


class ScriptedClient:
    """Spielt eine konfigurierbare Sequenz von Modell-Antworten ab.

    script: Liste von Tool-Call-Schritten (name, args-dict). Nach allen
    Tool-Schritten folgt die finale Text-Antwort. Protokolliert die
    Tool-Resultate, die das 'Modell' vor der Antwort tatsaechlich gesehen hat.
    """
    def __init__(self, script, final_answer):
        self.script = script
        self.final_answer = final_answer
        self.turn = 0
        self.chat = self  # so dass client.chat.completions.create() geht
        self.completions = self
        self.seen_tool_results = []

    def create(self, model, messages, **kwargs):
        if self.turn < len(self.script):
            name, fn_args = self.script[self.turn]
            tc = FakeToolCall(f"call_{self.turn + 1}", name, json.dumps(fn_args))
            self.turn += 1
            return FakeResponse(
                FakeMessage(content="", tool_calls=[tc],
                            reasoning_content=f"Rufe {name} auf."),
                "tool_calls")
        # Finale Antwort — Tool-Resultate aus der History einsammeln (Beweis Rueckfluss)
        for m in messages:
            if m.get("role") == "tool":
                self.seen_tool_results.append((m["name"], m["content"]))
        self.turn += 1
        return FakeResponse(
            FakeMessage(content=self.final_answer, reasoning_content="Antwort fertig."),
            "stop")


# ── Dummy-Engine: echte Tool-Logik, gestubbte Umgebung ───────────────────────
class SimEngine(ChatOrchestratorMixin):
    def __init__(self, script, final_answer):
        self.chat_client = ScriptedClient(script, final_answer)
        self.chat_model = "deepseek-v4-flash"
        self.chat_provider = "deepseek"
        self.conversations = {}
        self.weather_context_str = "ROHKONTEXT (Platzhalter, nicht leer)"
        self.spots = [
            {"name": "Niederbauen", "fluggebiet": "Klewenalp", "region": "Zentralschweiz",
             "elevation_m": 1587, "windrichtung": "NW", "ideal_wind_max": 25,
             "kritischer_foehn": "S", "latitude": 46.93, "longitude": 8.55},
        ]
        self.spot_analyses = {
            "Niederbauen": {
                TODAY: {
                    "safety": {
                        "safety_status": "conditional",
                        "safe_window": "10-13 Uhr",
                        "no_go_reasons": [],
                        "caution_notes": ["Foehntendenz ab ca. 14 Uhr", "Boeen im Lee moeglich"],
                        "primary_caution": "Foehntendenz ab ca. 14 Uhr",
                        "foehn_risk": "moderate",
                        "wind_summary": "Vormittags NW schwach, nachmittags drehend S auffrischend",
                    },
                    "status": "kurzer_thermikflug",
                    "best_window": "10-13 Uhr",
                    "recommendation": "Frueh starten, vor 14 Uhr landen. Nachmittags Foehngefahr.",
                    "experience_rating": 2,
                    "flyability": {"flyability_tier": "kurzer_thermikflug", "peak_climb_rate": 1.8},
                }
            }
        }
        self.weather_data = {"Niederbauen": {"hourly_data": {}}, "_meta": {}}
        # Regionsdaten (analog zu Spots) — region_analyses ist nach Region-ID gekeyt.
        self.region_analyses = {
            "berner_oberland": {
                TODAY: {
                    "region_name": "Berner Oberland",
                    "experience_rating": 4,
                    "safety": {"safety_status": "safe", "foehn_risk": "none"},
                    "best_window": "12-17 Uhr",
                    "recommendation": "Solide Basis ueber 3000m, gute XC-Chancen Richtung Westen.",
                    "flyability": {"peak_climb_rate": 2.6},
                }
            }
        }
        self.region_weather_data = {"berner_oberland": {"hourly_data": {}}}

    # — gestubbte Umgebung (nicht Gegenstand des Tests) —
    def _ensure_weather_context(self): pass
    def _ensure_spot_analyses(self): pass
    def _build_compact_analyses_for_chat(self):
        return ("VORANALYSEN — KURZUEBERSICHT\n"
                f"─── {TODAY} ───\n"
                "  Rating 2/5 — kurzer_thermikflug: Niederbauen (Fenster: 10-13, Peak: 1.8 m/s)")
    def _build_foehn_context_for_ai(self):
        return "FÖHN-INDIKATOR: ΔP moderat."
    def _save_conversation(self, session_id): pass
    def _get_or_create_conversation(self, session_id):
        if session_id not in self.conversations:
            self.conversations[session_id] = {"first_question": True, "messages": [
                {"role": "system", "content": "Du bist ein Flugwetter-Assistent."}
            ]}
        return self.conversations[session_id]["messages"]
    # ECHTE Rohwetter-Formatierung simulieren (Inhalt realistisch, kurz)
    def _build_single_spot_context(self, spot, date_str, mode="chat"):
        return (f"WETTERDATEN FÜR: {spot['name']} — TAG: {date_str} [mode={mode}]\n"
                f"  {date_str} 10:00 | Wind 12 km/h NW [WIND-OK] | THERMIK 1.8 m/s bis 2400m\n"
                f"  {date_str} 13:00 | Wind 18 km/h NW [WIND-OK] | THERMIK 1.2 m/s\n"
                f"  {date_str} 15:00 | Wind 34/48 km/h S [WIND-WRONG] [GUST-WARN]  ← Foehn")
    # Region-Resolver gestubbt (echte Variante separat gegen 29 reale Regionen getestet)
    def _resolve_region_by_name(self, query):
        ql = (query or "").strip().lower()
        reg = {"id": "berner_oberland", "region": "Berner Oberland",
               "elevation_ref": 1500, "kritischer_foehn": "Sued"}
        if ql and (ql in reg["region"].lower() or ql in reg["id"].lower()):
            return reg
        return None
    def _build_single_region_context(self, region, date_str):
        return (f"WETTERDATEN FÜR REGION: {region['region']} — TAG: {date_str}\n"
                f"  {date_str} 13:00 | 700hPa(3000m): 22 km/h SW | Basis ~3200m | THERMIK 2.6 m/s\n"
                f"  {date_str} 16:00 | 700hPa(3000m): 28 km/h SW | leichte Quellbewoelkung")


# ── Ein Szenario durch die echte answer_stream-Schleife fahren ───────────────
def run_scenario(title, question, script, final_answer, expect):
    """expect: dict {tool_name: [substrings die im Tool-Resultat stehen muessen]}"""
    print(f"\n{'='*70}\n{title}\n{'='*70}")
    eng = SimEngine(script, final_answer)
    print(f"PILOT: {question}\n")
    print("─── Event-Stream aus answer_stream() ───")
    events = list(eng.answer_stream("sim-session", question))
    for ev in events:
        t = ev.get("type")
        if t == "status":
            print(f"  [STATUS]  {ev['content']}")
        elif t == "text":
            print(f"  [ANTWORT] {ev['content']}")
        elif t == "error":
            print(f"  [FEHLER]  {ev['content']}")
        elif t == "done":
            print("  [DONE]")
        else:
            print(f"  [{t}] {ev}")

    print("\n─── Beweis: Daten, die das Modell vor der Antwort gesehen hat ───")
    seen = dict(eng.chat_client.seen_tool_results)
    for name, content in eng.chat_client.seen_tool_results:
        short = content if len(content) < 400 else content[:400] + "…"
        print(f"  • Tool '{name}' lieferte: {short}\n")

    # Harte Checks
    called = list(seen.keys())
    assert any(ev.get("type") == "text" for ev in events), "Keine finale Antwort"
    for tool_name, substrings in expect.items():
        assert tool_name in called, f"{tool_name} wurde nicht durchgereicht"
        payload = seen[tool_name]
        for s in substrings:
            assert s in payload, f"'{s}' fehlt im Resultat von {tool_name}"
    print(f"✓ CHECKS BESTANDEN: {', '.join(called)} aufgerufen, "
          "echte Daten flossen zurueck ans Modell, finale Antwort erzeugt.")


def run():
    run_scenario(
        title="SZENARIO A — SPOT-Detailfrage",
        question="Warum ist Niederbauen heute nur bedingt fliegbar, und wie stark wird der Wind?",
        script=[
            ("get_spot_analysis", {"spot_name": "niederbauen", "date": TODAY}),
            ("get_spot_weather", {"spot_name": "Niederbauen", "date": TODAY}),
        ],
        final_answer=(
            "Niederbauen ist heute nur *bedingt* fliegbar: Foehntendenz am Nachmittag "
            "(caution). Rohdaten: ab ca. 15 Uhr frischt der Wind auf 34/48 km/h aus Sued "
            "auf — am Vormittag ist das Fenster sauber."
        ),
        expect={
            "get_spot_analysis": ["Foehntendenz", "conditional"],
            "get_spot_weather": ["GUST-WARN", "THERMIK"],
        },
    )

    run_scenario(
        title="SZENARIO B — REGION-Detailfrage",
        question="Wie ist die Grosswetterlage im Berner Oberland heute, und der Hoehenwind?",
        script=[
            ("get_region_analysis", {"region_name": "berner oberland", "date": TODAY}),
            ("get_region_weather", {"region_name": "Berner Oberland", "date": TODAY}),
        ],
        final_answer=(
            "Berner Oberland heute stark (Rating 4/5, sicher): Basis ueber 3000m, gute "
            "XC-Chancen nach Westen. Hoehenwind moderat (700hPa ~22-28 km/h SW), "
            "am spaeten Nachmittag leichte Quellbewoelkung."
        ),
        expect={
            "get_region_analysis": ["experience_rating", "Berner Oberland"],
            "get_region_weather": ["700hPa", "Basis"],
        },
    )

    print(f"\n{'='*70}\n✓✓ BEIDE SZENARIEN GRÜN — Spot- UND Regionen-Tools laufen "
          f"end-to-end durch die echte answer_stream-Schleife.\n{'='*70}")


if __name__ == "__main__":
    run()
