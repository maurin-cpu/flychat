import base64, os
# Read base64 from stdin, decode, write to build_complete_csv.py
import sys
data = sys.stdin.read().strip()
content = base64.b64decode(data).decode("utf-8")
outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_complete_csv.py")
with open(outpath, "w", encoding="utf-8", newline="\n") as out:
    out.write(content)
print(f"Wrote {len(content)} chars to {outpath}")
