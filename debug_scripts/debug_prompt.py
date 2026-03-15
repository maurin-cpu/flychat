import json
import sys

with open("data/history/sess_k9vjaiopimmgedhwc.json", "r", encoding="utf-8") as f:
    d = json.load(f)

for msg in d.get("messages", []):
    if msg.get("role") == "user":
        content = msg.get("content", "")
        if "Brunnihütte" in content:
            lines = content.split("\n")
            in_brunn = False
            for line in lines:
                if "SPOT: Brunnihütte" in line:
                    in_brunn = True
                if in_brunn:
                    print(line)
                if in_brunn and line.startswith("SPOT:") and "Brunnihütte" not in line:
                    break
            break
