import json
from chat_engine import _build_context

with open("data/wetterdaten.json", "r", encoding="utf-8") as f:
    wetterdaten = json.load(f)

ctx = _build_context(wetterdaten, "Brunnihütte", "2026-03-12", "Zentralschweiz")
print(ctx)
