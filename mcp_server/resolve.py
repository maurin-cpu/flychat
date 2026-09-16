"""Namen aufloesen: Spot / Region → Treffer oder Kandidatenliste (nie raten).

Port von engine/chat_orchestrator._resolve_spot_by_name (exakt → case-insensitive
→ Teilstring), ergaenzt um Umlaut-Normalisierung, Fluggebiet-Match und
Mehrdeutigkeit als Rueckgabe statt "erster Treffer gewinnt".
"""
from __future__ import annotations

import re


def _norm(s: str) -> str:
    s = (s or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("é", "e"), ("è", "e"), ("à", "a")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def resolve_spot(query: str, spots: list[dict]) -> tuple[dict | None, list[dict]]:
    """(spot, candidates): genau ein Treffer → (spot, []), mehrere → (None, [...]), keiner → (None, [])."""
    q = (query or "").strip()
    if not q:
        return None, []
    for s in spots:
        if s["name"] == q or s.get("slug") == q:
            return s, []
    qn = _norm(q)
    exact = [s for s in spots if _norm(s["name"]) == qn]
    if len(exact) == 1:
        return exact[0], []
    if exact:
        return None, exact
    sub = [s for s in spots if qn in _norm(s["name"])]
    if len(sub) == 1:
        return sub[0], []
    if sub:
        return None, sub[:15]
    # Fluggebiet (z. B. "Grindelwald" → alle Startplaetze des Gebiets)
    fg = [s for s in spots if qn and qn in _norm(s.get("fluggebiet") or "")]
    if len(fg) == 1:
        return fg[0], []
    if fg:
        return None, fg[:15]
    # Wortweise: alle Wörter der Anfrage im Namen
    words = qn.split()
    if len(words) > 1:
        ww = [s for s in spots if all(w in _norm(s["name"]) for w in words)]
        if len(ww) == 1:
            return ww[0], []
        if ww:
            return None, ww[:15]
    return None, []


def resolve_region(query: str, regions: list[dict]) -> tuple[dict | None, list[dict]]:
    q = (query or "").strip()
    if not q:
        return None, []
    qn = _norm(q)
    for r in regions:
        if r.get("id") == q or r.get("name") == q:
            return r, []
    exact = [r for r in regions if _norm(r.get("name")) == qn or _norm(r.get("id")) == qn]
    if len(exact) == 1:
        return exact[0], []
    sub = [r for r in regions if qn in _norm(r.get("name")) or qn in _norm(r.get("id"))]
    if len(sub) == 1:
        return sub[0], []
    return None, sub


def candidates_text(kind: str, query: str, cands: list[dict]) -> str:
    if not cands:
        return f"{kind} '{query}' nicht gefunden. Nutze list_regions / search_spots, um gueltige Namen zu sehen."
    names = "\n".join(f"  - {c.get('name')}" + (f" ({c.get('region')})" if c.get("region") else "") for c in cands)
    return f"{kind} '{query}' ist mehrdeutig — bitte einen davon exakt angeben:\n{names}"
