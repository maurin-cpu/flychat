# Self-contained builder for match_kml_csv.py
import os
target = os.path.join(os.path.dirname(os.path.abspath(__file__)), "match_kml_csv.py")
SQ = chr(39)
NL = chr(10)
L = []
def A(*args):
    for s in args:
        L.append(s)
