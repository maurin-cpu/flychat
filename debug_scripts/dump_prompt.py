import json

with open("data/history/sess_k9vjaiopimmgedhwc.json", "r", encoding="utf-8") as f:
    d = json.load(f)

with open("log.txt", "w", encoding="utf-8") as out:
    for msg in d.get("messages", []):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if "Brunnihütte" in content:
                out.write(content)
