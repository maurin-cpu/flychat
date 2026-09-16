"""ExportStore — liest data/mcp_export/ (Pointer CURRENT), ohne Engine-Import.

Kleine Dateien (meta, spots, regions, screening, foehn) liegen im Speicher und
werden neu geladen, sobald sich CURRENT aendert. Bloecke, Meteogramme und
Hoehenprofile werden pro Anfrage lazy gelesen.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime

STALE_WARN_H = 30      # Banner in jeder Antwort
STALE_REFUSE_H = 72    # Screening-Tools liefern nur noch den Status


class ExportMissing(RuntimeError):
    pass


class ExportStore:
    def __init__(self, root: str, now_fn=None):
        self.root = root
        self._now = now_fn or datetime.now
        self._lock = threading.Lock()
        self._loaded_build: str | None = None
        self._pointer_mtime: float | None = None
        self.meta: dict = {}
        self.spots: list[dict] = []
        self.spots_by_slug: dict[str, dict] = {}
        self.regions: list[dict] = []
        self.rows: list[dict] = []
        self.foehn: dict = {}

    # ---------- Laden ----------
    @property
    def pointer_path(self) -> str:
        return os.path.join(self.root, "CURRENT")

    @property
    def build_dir(self) -> str:
        if not self._loaded_build:
            raise ExportMissing("Kein Export geladen")
        return os.path.join(self.root, self._loaded_build)

    def maybe_reload(self) -> bool:
        """Laedt neu, wenn CURRENT fehlt/neu ist. True = neu geladen."""
        try:
            st = os.stat(self.pointer_path)
        except FileNotFoundError:
            raise ExportMissing(
                f"Kein MCP-Export unter {self.root} — zuerst `python scripts/build_mcp_export.py` ausfuehren.")
        with self._lock:
            if self._pointer_mtime == st.st_mtime and self._loaded_build:
                return False
            with open(self.pointer_path, encoding="utf-8") as fh:
                build = fh.read().strip()
            bdir = os.path.join(self.root, build)
            self.meta = self._json(os.path.join(bdir, "meta.json"))
            self.spots = self._json(os.path.join(bdir, "spots.json"))
            self.spots_by_slug = {s["slug"]: s for s in self.spots}
            self.regions = self._json(os.path.join(bdir, "regions.json"))
            self.foehn = self._json(os.path.join(bdir, "foehn.json"))
            rows = []
            with open(os.path.join(bdir, "screening.jsonl"), encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        rows.append(json.loads(line))
            self.rows = rows
            self._loaded_build = build
            self._pointer_mtime = st.st_mtime
            return True

    @staticmethod
    def _json(path: str):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    # ---------- Frische ----------
    def age_hours(self) -> float | None:
        lu = self.meta.get("last_updated")
        if not lu:
            return None
        try:
            return (self._now() - datetime.fromisoformat(lu)).total_seconds() / 3600.0
        except ValueError:
            return None

    def is_stale(self) -> bool:
        a = self.age_hours()
        return a is not None and a > STALE_WARN_H

    def is_unusable(self) -> bool:
        a = self.age_hours()
        return a is not None and a > STALE_REFUSE_H

    def current_dates(self) -> list[str]:
        """Exportierte Tage ohne Vergangenheit."""
        today = self._now().strftime("%Y-%m-%d")
        return [d for d in self.meta.get("dates", []) if d >= today]

    def current_rows(self) -> list[dict]:
        ok = set(self.current_dates())
        return [r for r in self.rows if r["date"] in ok]

    # ---------- Lazy-Reader ----------
    def block(self, slug: str, date: str) -> str | None:
        p = os.path.join(self.build_dir, "blocks", date, slug + ".txt")
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8") as fh:
            return fh.read()

    def meteogram(self, slug: str) -> dict | None:
        p = os.path.join(self.build_dir, "meteogram", slug + ".json")
        return self._json(p) if os.path.exists(p) else None

    def altitude(self, slug: str) -> dict | None:
        p = os.path.join(self.build_dir, "altitude", slug + ".json")
        return self._json(p) if os.path.exists(p) else None

    def row(self, slug: str, date: str) -> dict | None:
        for r in self.rows:
            if r["slug"] == slug and r["date"] == date:
                return r
        return None
