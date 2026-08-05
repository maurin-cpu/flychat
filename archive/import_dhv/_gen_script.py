import base64, os
# This script generates build_complete_csv.py
data = input()  # read base64 from stdin
content = base64.b64decode(data).decode("utf-8")
outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_complete_csv.py")
with open(outpath, "w", encoding="utf-8", newline="
") as out:
    out.write(content)
print(f"Wrote {len(content)} chars to {outpath}")
