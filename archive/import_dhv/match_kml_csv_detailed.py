#!/usr/bin/env python
# -*- coding: utf-8 -*-
# match_kml_csv_detailed.py
import sys, io, os, csv, re, math
import xml.etree.ElementTree as ET
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
KML = os.path.join(BASE, "dhv_gelaende_2026-04-09_16.27.54.kml")
CSV_F = os.path.join(BASE, "fluggebiete_dhv.csv")
NS = {"kml": "http://www.opengis.net/kml/2.2"}
COLS = ["region","fluggebiet","site_name","latitude","longitude","elevation_m","windrichtung","ideal_wind_max_kmh","slope_azimuth","slope_angle","kritischer_foehn","Bemerkungen"]
