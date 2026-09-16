"""wingcast MCP-Server: Tools, Resources, Prompts ueber dem ExportStore.

Alle Antworten sind Text (Tokens sparen), tragen den Footer mit Stand/Modell/
Quelle und — wo gesiebt wird — die Zahl der geprueften und ausgeschlossenen
Spot-Tage. Keine LLM-Analysen, keine Ratings der App.
"""
from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer

from . import formatting as fmt
from .geo import geocode, spots_within
from .resolve import candidates_text, resolve_region, resolve_spot
from .screening import (EXCLUSION_REASONS, apply_filters, default_filters, overview_counts, rank)
from .store import ExportMissing, ExportStore

MAX_TOP_N = 100

INSTRUCTIONS = """wingcast liefert Prognose-Rohdaten und deterministische Kennzahlen fuer ~500
Gleitschirm-Startplaetze in der Schweiz (3 Tage, Flugstunden 06-17 Uhr). Es gibt KEINE
Bewertung und KEINE Flugempfehlung der App — du liest die Daten wie ein Pilot das
Meteogramm liest. Lies zuerst die Resource wingcast://guide/pilot_evaluation.

Regeln:
1. Nie aus einer Teilmenge schliessen. Fuer "wo kann ich fliegen" zuerst `overview`,
   dann `day_table` (ALLE Spots eines Tages) oder `search_spots` (meldet, was es warum
   aussortiert hat). Erst dann `spot_series` fuer Kandidaten und `spot_detail` fuer Favoriten.
2. Verlauf statt Einzelwert: Zeitverlauf (Boeen nehmen zu?) und Hoehenverlauf (Wind oben
   viel staerker als am Boden?) immer nennen. Trendpfeil ↗ heisst: Stundenreihe anschauen.
3. Zahlen 1:1 uebernehmen, nicht runden oder schoenreden. Warnungen (DANGER, Gewitter,
   Foehn, Basis unter Start) immer ausdruecklich nennen.
4. `spot_info` (Bemerkungen zum Startplatz) vor einer Empfehlung lesen.
5. Jede Antwort an den Piloten: Stand der Prognose, Modell, Quelle (Open-Meteo CC BY /
   MeteoSchweiz) und "Prognose, kein Ersatz fuer eigene Beurteilung vor Ort".
"""


def build_server(export_dir: str | None = None) -> MCPServer:
    root = export_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "mcp_export")
    store = ExportStore(root)
    server = MCPServer(name="wingcast", instructions=INSTRUCTIONS, version="0.1.0")
    register(server, store)
    return server


def build_http_app(server: MCPServer, allowed_hosts: list[str], rate_per_min: int = 60, host: str = "127.0.0.1"):
    """Streamable-HTTP-App fuer den Betrieb hinter Caddy: offen, aber mit
    Rate-Limit pro IP (Entscheid 16.09.) und Host-Pruefung (DNS-Rebinding).

    Stateless, damit Caddy/claude.ai keine Session-Affinitaet brauchen.
    Der Endpunkt liegt auf /mcp; /healthz fuer Monitoring."""
    import time
    from collections import defaultdict, deque

    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, PlainTextResponse

    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(_: Request):
        try:
            server_store = _STORES.get(id(server))
            if server_store:
                server_store.maybe_reload()
                return PlainTextResponse(f"ok build={server_store._loaded_build} age_h={server_store.age_hours():.1f}")
            return PlainTextResponse("ok")
        except Exception as e:  # noqa: BLE001
            return PlainTextResponse(f"degraded: {e}", status_code=503)

    tss = TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                    allowed_hosts=allowed_hosts, allowed_origins=[f"https://{h}" for h in allowed_hosts])
    app = server.streamable_http_app(stateless_http=True, json_response=True, transport_security=tss, host=host)

    class RateLimit(BaseHTTPMiddleware):
        """Token-Bucket pro Client-IP (X-Forwarded-For von Caddy), Fenster 60 s."""
        def __init__(self, app_, per_min: int):
            super().__init__(app_)
            self.per_min = per_min
            self.hits: dict[str, deque] = defaultdict(deque)

        async def dispatch(self, request: Request, call_next):
            if request.url.path.startswith("/healthz"):
                return await call_next(request)
            ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
            now = time.monotonic()
            q = self.hits[ip]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_min:
                return JSONResponse({"error": "rate limit: max %d Anfragen/min" % self.per_min}, status_code=429,
                                    headers={"Retry-After": "60"})
            q.append(now)
            return await call_next(request)

    app.add_middleware(RateLimit, per_min=rate_per_min)
    return app


_STORES: dict[int, ExportStore] = {}


def _guard(store: ExportStore, screening: bool = False) -> str | None:
    try:
        store.maybe_reload()
    except ExportMissing as e:
        return str(e)
    if screening and store.is_unusable():
        return (f"Prognose ist {store.age_hours():.0f} h alt — Screening verweigert. "
                f"Export neu bauen (scripts/build_mcp_export.py)." + fmt.footer(store))
    return None


def _parse_dates(store: ExportStore, dates: str | None) -> list[str]:
    cur = store.current_dates()
    if not dates:
        return cur
    wanted = [d.strip() for d in dates.split(",") if d.strip()]
    return [d for d in cur if d in wanted]


def _filters(store: ExportStore, **kw) -> dict:
    f = default_filters(store.meta.get("thresholds", {}))
    for k, v in kw.items():
        if v is not None:
            f[k] = v
    return f


def register(server: MCPServer, store: ExportStore) -> None:  # noqa: C901
    _STORES[id(server)] = store
    agl_steps = lambda: store.meta.get("profile_agl_steps", [0, 500, 1000, 1500, 2000, 3000])  # noqa: E731

    @server.tool()
    def data_status() -> str:
        """Stand der Prognose, exportierte Tage, Modelle je Tag, Schwellenwerte, Frische-Warnung."""
        err = _guard(store)
        if err:
            return err
        m = store.meta
        lines = [
            f"Prognose-Stand: {m.get('last_updated')} · Export: {m.get('built_at')} · Alter: {store.age_hours():.1f} h",
            f"Tage: {', '.join(fmt.day_label(d) + ' (' + d + ')' for d in store.current_dates())} · Flugstunden {m.get('hours', [])[0]}-{m.get('hours', [])[-1]} Uhr",
            f"Spots: {m.get('counts', {}).get('spots')} · Spot-Tage: {len(store.current_rows())}",
            "Schwellen: " + ", ".join(f"{k}={v}" for k, v in m.get("thresholds", {}).items()),
        ]
        return "\n".join(lines) + fmt.footer(store)

    @server.tool()
    def list_regions() -> str:
        """Alle Regionen mit ID, Name, Geländetyp, kritischer Föhnrichtung und Spotzahl."""
        err = _guard(store)
        if err:
            return err
        lines = ["id | Name | Gelände | Föhn-kritisch | Spots"]
        for r in sorted(store.regions, key=lambda x: x.get("name") or ""):
            lines.append(f"{r['id']} | {r['name']} | {r.get('terrain_type') or '-'} | {r.get('kritischer_foehn') or '-'} | {r.get('spot_count', 0)}")
        return "\n".join(lines) + fmt.footer(store)

    @server.tool()
    def overview(dates: str | None = None, min_clean_h: int | None = None, allow_gust_danger: bool | None = None,
                 allow_rain_h: int | None = None) -> str:
        """Erster Schritt für 'wo kann ich fliegen': pro Region und Tag, wie viele Startplätze die
        Grundkriterien erfüllen (Startfenster ≥ min_clean_h ohne DANGER, kein Gewitter/Regen im
        Fenster, kein Föhn-danger, Basis über Start) plus Gewitter-Ensemble und Föhn je Tag.
        dates: kommagetrennt YYYY-MM-DD (Standard: alle)."""
        err = _guard(store, screening=True)
        if err:
            return err
        ds = _parse_dates(store, dates)
        f = _filters(store, min_clean_h=min_clean_h, allow_gust_danger=allow_gust_danger, allow_rain_h=allow_rain_h)
        rows = [r for r in store.current_rows() if r["date"] in ds]
        cnt = overview_counts(rows, f)
        regions = sorted({r["region"] for r in rows})
        head = "Region | " + " | ".join(fmt.day_label(d) for d in ds)
        lines = [fmt.filters_line(f), "Zelle = Spots mit Fenster / Spots gesamt · Gewitter-Ensemble % (Region)", head]
        for reg in regions:
            cells = []
            for d in ds:
                c = cnt.get((reg, d))
                cells.append("-" if not c else f"{c['pass']}/{c['total']}" + (f" ⚡{c['thunder_pct']:.0f}%" if c.get("thunder_pct") else ""))
            lines.append(f"{reg} | " + " | ".join(cells))
        tot = []
        for d in ds:
            p = sum(c["pass"] for (rg, dd), c in cnt.items() if dd == d)
            t = sum(c["total"] for (rg, dd), c in cnt.items() if dd == d)
            tot.append(f"{p}/{t}")
        lines.append("GESAMT | " + " | ".join(tot))
        lines.append("")
        lines.append(_foehn_lines(store, ds))
        lines.append("Weiter mit: day_table(<Tag>) für alle Spots eines Tages, oder search_spots mit Umkreis/Filtern.")
        return "\n".join(lines) + fmt.footer(store)

    @server.tool()
    def day_table(date: str, region: str | None = None, sort: str = "window") -> str:
        """ALLE Startplätze eines Tages, eine Zeile pro Spot mit Min→Max und Trendpfeil (↗↘→) für
        Wind, Böen, Höhenwind sowie Fenster, Regen, CAPE, Föhn, Thermik, Basis. Kein Server-Filter —
        du siehst wirklich jeden Spot (~500 Zeilen, ~12k Tokens). Mit region= nur diese Region.
        sort: window | thermal | calm | name."""
        err = _guard(store, screening=True)
        if err:
            return err
        if date not in store.current_dates():
            return f"Tag {date} nicht im Export. Verfügbar: {', '.join(store.current_dates())}"
        rows = [r for r in store.current_rows() if r["date"] == date]
        reg_note = ""
        if region:
            reg, cands = resolve_region(region, store.regions)
            if not reg:
                return candidates_text("Region", region, cands)
            rows = [r for r in rows if r["region_id"] == reg["id"] or r["region"] == reg["name"]]
            reg_note = f" · Region {reg['name']}"
        rows = rank(rows, sort)
        lines = [f"## {fmt.day_label(date)} ({date}){reg_note} · {len(rows)} Spots · sortiert nach {sort}",
                 "Legende: Fenster = Stunden WIND-OK ohne DANGER (Ende exklusiv). Trend ↗↘→ = erstes vs. letztes Drittel 06-17 Uhr. "
                 "Höhe Start→+3000m = Wind 12 Uhr am Start und 3000 m darüber. !! = harte Warnung.",
                 fmt.day_line_header()]
        lines += [fmt.day_line(r) for r in rows]
        lines.append("")
        lines.append(_foehn_lines(store, [date]))
        lines.append("Weiter mit: spot_series(spot, date) für Stundenverlauf + Höhenprofil, spot_info(spot) für Bemerkungen.")
        return "\n".join(lines) + fmt.footer(store)

    @server.tool()
    def search_spots(dates: str | None = None, regions: str | None = None, lat: float | None = None,
                     lon: float | None = None, radius_km: float | None = None, min_clean_h: int | None = None,
                     allow_gust_danger: bool | None = None, allow_aloft_danger: bool | None = None,
                     allow_thunder: bool | None = None, allow_rain_h: int | None = None,
                     allow_foehn_danger: bool | None = None, max_gust: float | None = None,
                     min_thermal_h: int | None = None, min_peak_climb: float | None = None,
                     sort: str = "window", top_n: int = 40, offset: int = 0) -> str:
        """Siebt ALLE Spot-Tage serverseitig und liefert die besten top_n Zeilen plus eine Zusammenfassung,
        wie viele Spot-Tage warum ausgeschlossen wurden (damit du weisst, dass nichts übersehen wurde).
        Standardfilter: Startfenster ≥ CLEAN_WINDOW_MIN_HOURS, keine Böen-/Höhenwind-DANGER, kein
        Gewitter/Regen im Fenster, kein Föhn-danger, Basis über Start. Jeden Filter kannst du lockern
        (allow_*) oder verschärfen (max_gust, min_thermal_h, min_peak_climb). regions: kommagetrennte
        IDs/Namen. lat/lon + radius_km: Luftlinien-Umkreis. sort: window | thermal | calm | name."""
        err = _guard(store, screening=True)
        if err:
            return err
        ds = _parse_dates(store, dates)
        near = {"lat": lat, "lon": lon, "km": radius_km or 60} if lat is not None and lon is not None else None
        reg_ids = None
        if regions:
            reg_ids = []
            for q in regions.split(","):
                reg, cands = resolve_region(q, store.regions)
                if not reg:
                    return candidates_text("Region", q, cands)
                reg_ids.append(reg["id"])
        f = _filters(store, min_clean_h=min_clean_h, allow_gust_danger=allow_gust_danger,
                     allow_aloft_danger=allow_aloft_danger, allow_thunder=allow_thunder, allow_rain_h=allow_rain_h,
                     allow_foehn_danger=allow_foehn_danger, max_gust=max_gust, min_thermal_h=min_thermal_h,
                     min_peak_climb=min_peak_climb, regions=reg_ids, dates=ds, near=near)
        rows = store.current_rows()
        kept, summary = apply_filters(rows, f)
        kept = rank(kept, sort)
        top_n = max(1, min(int(top_n), MAX_TOP_N))
        page = kept[offset:offset + top_n]
        lines = [fmt.filters_line(f), fmt.exclusion_summary(summary, EXCLUSION_REASONS),
                 f"Gezeigt: {len(page)} (sort={sort}, offset={offset})", "",
                 "Legende: Fenster = Stunden WIND-OK ohne DANGER. Trend ↗↘→ = erstes vs. letztes Drittel. Höhe Start→+3000m = 12 Uhr.",
                 "Tag | " + fmt.day_line_header()]
        lines += [f"{fmt.day_label(r['date'])} | " + fmt.day_line(r) for r in page]
        if len(kept) > offset + top_n:
            lines.append(f"… {len(kept) - offset - top_n} weitere: offset={offset + top_n}")
        lines.append("")
        lines.append("Weiter mit: spot_series(spot, date) für Verlauf + Höhenprofil, spot_detail für den vollen Block.")
        return "\n".join(lines) + fmt.footer(store)

    @server.tool()
    def spot_series(spots: str, date: str) -> str:
        """Stundenverlauf 06-17 Uhr (Wind, Richtung, WIND-OK, Böen, 850/700 hPa, Steigen, Top, Basis,
        Bewölkung, Regen, CAPE, Strahlung, Temp) plus Höhenprofil 09/12/15 Uhr (Start bis +3000 m:
        Wind, Richtung, Turbulenz-Exzess) für einen oder mehrere Spots (kommagetrennt) oder eine
        ganze Region (spots='region:<name>'). Das ist die Meteogramm-Sicht in Zahlen."""
        err = _guard(store)
        if err:
            return err
        if date not in store.current_dates():
            return f"Tag {date} nicht im Export. Verfügbar: {', '.join(store.current_dates())}"
        targets: list[dict] = []
        if spots.lower().startswith("region:"):
            reg, cands = resolve_region(spots[7:], store.regions)
            if not reg:
                return candidates_text("Region", spots[7:], cands)
            targets = [s for s in store.spots if s["region_id"] == reg["id"] or s["region"] == reg["name"]]
        else:
            for q in spots.split(","):
                s, cands = resolve_spot(q, store.spots)
                if not s:
                    return candidates_text("Spot", q.strip(), cands)
                targets.append(s)
        if len(targets) > 60:
            return f"{len(targets)} Spots sind zu viele für spot_series — bitte enger wählen (max 60)."
        blocks = []
        for s in targets:
            r = store.row(s["slug"], date)
            if r:
                blocks.append(fmt.series_block(r, agl_steps()))
        return "\n\n".join(blocks) + fmt.footer(store)

    @server.tool()
    def spot_detail(spot: str, date: str) -> str:
        """Der vollständige Datenblock eines Spots an einem Tag: alle Stunden mit allen Tags
        ([WIND-OK], [GUST-*], [ALOFT-WIND-*], [RAIN-WARN], [CAPE-*], [THUNDERSTORM], [THERMAL-ROUGH-*] …),
        Wolkenbasis, Bewölkung, Strahlung, Flugbereich, Höhenwind 850/700 hPa, Thermik-Proxy, Föhn-Indikator
        und Fenster-Info. ~3k Tokens — nur für Favoriten."""
        err = _guard(store)
        if err:
            return err
        s, cands = resolve_spot(spot, store.spots)
        if not s:
            return candidates_text("Spot", spot, cands)
        if date not in store.current_dates():
            return f"Tag {date} nicht im Export. Verfügbar: {', '.join(store.current_dates())}"
        block = store.block(s["slug"], date)
        if not block:
            return f"Kein Block für {s['name']} am {date}."
        return block + fmt.footer(store)

    @server.tool()
    def spot_meteogram(spot: str, date: str) -> str:
        """Meteogramm-Rohreihen 06-17 Uhr wie in der App: Wind/Böen/Richtung (+ICON-CH1 falls vorhanden),
        Regen mm/%/Wettercode/Gewitter-Flag, CAPE, Steigen, Top, LCL, Basis, Bewölkung tief/mittel/hoch."""
        err = _guard(store)
        if err:
            return err
        s, cands = resolve_spot(spot, store.spots)
        if not s:
            return candidates_text("Spot", spot, cands)
        mg = store.meteogram(s["slug"])
        if not mg or date not in mg:
            return f"Kein Meteogramm für {s['name']} am {date}."
        d = mg[date]
        hours = set(store.meta.get("hours", range(6, 18)))
        by = {}
        for key in ("wind", "precipitation", "thermik", "cloudbase"):
            for e in d.get(key, []):
                h = int(e["time"][11:13])
                if h in hours:
                    by.setdefault(h, {})[key] = e
        lines = [f"### {s['name']} · {fmt.day_label(date)} · {s['elev']} m · Sektor {s['windrichtung']}",
                 "Uhr | Wind | Böen | aus | Wind_ch1 | Böen_ch1 | Regen mm | Regen % | WMO | Gewitter | CAPE | Steigen | Top m | LCL m | Basis m | tief | mittel | hoch"]
        for h in sorted(by):
            w, p, t, c = by[h].get("wind", {}), by[h].get("precipitation", {}), by[h].get("thermik", {}), by[h].get("cloudbase", {})
            g = lambda d_, k, nd=0: fmt._f(d_.get(k), nd)  # noqa: E731
            lines.append(f"{h:02d} | {g(w,'speed')} | {g(w,'gusts')} | {fmt._dir8(w.get('direction'))} | {g(w,'speed_ch1')} | {g(w,'gusts_ch1')} | "
                         f"{g(p,'amount',1)} | {g(p,'probability')} | {p.get('weather_code','-')} | {'JA' if p.get('storm') else '-'} | "
                         f"{g(t,'cape')} | {g(t,'climb_rate',1)} | {g(t,'max_height')} | {g(t,'lcl')} | {g(c,'height')} | {g(c,'cover_low')} | {g(c,'cover_mid')} | {g(c,'cover_high')}")
        return "\n".join(lines) + fmt.footer(store)

    @server.tool()
    def spot_altitude_wind(spot: str, date: str, hours: str = "9,12,15", step_m: int = 250) -> str:
        """Höhenwind-Profil je Stunde (Start bis +3500 m, Raster step_m): Wind km/h, Richtung,
        Turbulenz-Exzess (T(z) − Wind; KEIN klassischer Böenwert), Temperatur. hours: kommagetrennt."""
        err = _guard(store)
        if err:
            return err
        s, cands = resolve_spot(spot, store.spots)
        if not s:
            return candidates_text("Spot", spot, cands)
        alt = store.altitude(s["slug"])
        if not alt or date not in alt:
            return f"Kein Höhenprofil für {s['name']} am {date}."
        want = {int(h) for h in hours.split(",") if h.strip()}
        by_hour = {e["hour"]: e["levels"] for e in alt[date] if e["hour"] in want}
        if not by_hour:
            return f"Keine der Stunden {sorted(want)} im Export (Flugstunden {store.meta.get('hours')})."
        hs = sorted(by_hour)
        if any("alt" not in L for h in hs for L in by_hour[h][:1]):
            return "Höhenprofil im alten Exportformat — bitte Export neu bauen (scripts/build_mcp_export.py)."
        step = max(int(step_m), 250)
        all_alts = sorted({L["alt"] for h in hs for L in by_hour[h]})
        # Raster ab der Startplatzhoehe: naechstgelegenes Level je Stufe
        alts = []
        for agl in range(0, 3501, step):
            if all_alts:
                a = min(all_alts, key=lambda x: abs(x - (s["elev"] + agl)))
                if a not in alts:
                    alts.append(a)
        elev = int(s["elev"] or 0)
        lines = [f"### {s['name']} · {fmt.day_label(date)} · Start {elev} m",
                 "Höhe MSL (über Start) | " + " | ".join(f"{h:02d} Uhr: km/h aus +Turb °C" for h in hs)]
        for a in alts:
            cells = []
            for h in hs:
                L = next((x for x in by_hour[h] if x["alt"] == a), None)
                cells.append(f"{fmt._f(L['ws'])} {fmt._dir8(L['wd'])} +{fmt._f(L['tx'])} {fmt._f(L['t'])}°" if L else "-")
            lines.append(f"{a} ({a - elev:+d}) | " + " | ".join(cells))
        return "\n".join(lines) + fmt.footer(store)

    @server.tool()
    def foehn(dates: str | None = None) -> str:
        """Föhn-Zeitreihe je Flugstunde: ΔP Nord–Süd (hPa), Level, Richtung, 700-hPa-Kammwind. Schwellen:
        ΔP ≥ 4 Vorsicht, ≥ 8 gefährlich. Welche Richtung für einen Spot zählt, steht in spot_info."""
        err = _guard(store)
        if err:
            return err
        ds = _parse_dates(store, dates)
        return _foehn_lines(store, ds, full=True) + fmt.footer(store)

    @server.tool()
    def find_spots_near(place: str | None = None, lat: float | None = None, lon: float | None = None,
                        minutes: int = 60, mode: str = "auto", radius_km: float | None = None) -> str:
        """Startplätze in Reichweite: Ort (geokodiert) oder lat/lon, Reisezeit in Minuten (auto |
        bicycle | pedestrian, Isochrone) oder fester Luftlinien-Radius. Liefert Spot, Region, Höhe,
        Sektor, Distanz — danach search_spots mit lat/lon/radius_km oder spot_series für die Treffer."""
        err = _guard(store)
        if err:
            return err
        label = place
        if lat is None or lon is None:
            if not place:
                return "Bitte place oder lat/lon angeben."
            g = geocode(place)
            if not g:
                return f"'{place}' konnte nicht geokodiert werden — bitte lat/lon angeben."
            lat, lon, label = float(g["lat"]), float(g["lon"]), g.get("display_name", place)
        hits, method = spots_within(lat, lon, minutes, mode, [dict(s) for s in store.spots], radius_km)
        lines = [f"Start: {label} ({lat:.4f}, {lon:.4f}) · {method} · {len(hits)} Spots",
                 "Spot | Region | Höhe | Sektor | Distanz km"]
        lines += [f"{s['name']} | {s['region']} | {s['elev']} m | {s['windrichtung'] or '-'} | {s['distance_km']}" for s in hits]
        lines.append(f"\nWeiter mit: search_spots(lat={lat:.4f}, lon={lon:.4f}, radius_km=…) oder spot_series('<Spot>,<Spot>', date).")
        return "\n".join(lines) + fmt.footer(store)

    @server.tool()
    def spot_info(spot: str) -> str:
        """Stammdaten eines Startplatzes: Höhe, Startsektor, Hangausrichtung, Geländetyp, kritische
        Föhnrichtung und die Bemerkungen (Flug, Sicherheit, Sonstiges) mit ihrer Wirkung."""
        err = _guard(store)
        if err:
            return err
        s, cands = resolve_spot(spot, store.spots)
        if not s:
            return candidates_text("Spot", spot, cands)
        lines = [f"### {s['name']} — Fluggebiet {s['fluggebiet']}, Region {s['region']} ({s['region_id']})",
                 f"Höhe {s['elev']} m · Koordinaten {s['lat']}, {s['lon']} · Startsektor {s['windrichtung'] or '-'} · "
                 f"Hang {s.get('slope_azimuth') if s.get('slope_azimuth') is not None else '-'}° / {s.get('slope_angle') or '-'}° · "
                 f"Gelände {s.get('terrain_type') or '-'} · Föhn-kritisch: {s.get('kritischer_foehn') or '-'}"]
        for lab, k1, k2 in (("Flug", "bemerkungen_flug", "bemerkung_flug_effekt"),
                            ("Sicherheit", "bemerkungen_sicherheit", "bemerkung_sicherheit_effekt")):
            if s.get(k1) or s.get(k2):
                lines.append(f"Bemerkung {lab}: {s.get(k1) or '-'}")
                if s.get(k2):
                    lines.append(f"  Wirkung: {s[k2]}")
        if s.get("bemerkungen_sonstiges"):
            lines.append(f"Sonstiges: {s['bemerkungen_sonstiges']}")
        return "\n".join(lines) + fmt.footer(store)

    # ---------- Resources ----------
    @server.resource("wingcast://guide/pilot_evaluation", mime_type="text/markdown")
    def guide() -> str:
        """Wie Piloten Meteogramm-Daten lesen: Parameter, Schwellen, Verlauf über Zeit und Höhe."""
        with open(os.path.join(os.path.dirname(__file__), "guide_de.md"), encoding="utf-8") as fh:
            return fh.read()

    @server.resource("wingcast://thresholds", mime_type="application/json")
    def thresholds() -> str:
        import json
        err = _guard(store)
        return err or json.dumps(store.meta.get("thresholds", {}), ensure_ascii=False, indent=1)

    @server.resource("wingcast://regions", mime_type="text/plain")
    def regions_res() -> str:
        return list_regions()

    # ---------- Prompts ----------
    @server.prompt()
    def where_can_i_fly(region: str = "", dates: str = "") -> str:
        """Ablauf für 'Wo kann ich fliegen?': overview → day_table/search_spots → spot_series → spot_detail."""
        return (f"Finde heraus, wo man {'in ' + region + ' ' if region else ''}{'am ' + dates + ' ' if dates else 'in den nächsten Tagen '}"
                "Gleitschirm fliegen kann. Lies zuerst wingcast://guide/pilot_evaluation. Dann: 1) overview, 2) day_table für den "
                "besten Tag (alle Spots!) oder search_spots mit Umkreis, 3) spot_series für die Kandidaten einer Region, "
                "4) spot_detail + spot_info für 2–4 Favoriten. Nenne für jede Empfehlung Zeitfenster, Wind/Böen-Verlauf, "
                "Höhenwind, Föhn, Regen/Gewitter, Basis und Thermik mit Zahlen — und was dagegen spricht. "
                "Schliesse mit Stand/Modell/Quelle und dem Hinweis, dass der Entscheid beim Piloten liegt.")

    @server.prompt()
    def evaluate_spot(spot: str, date: str) -> str:
        """Einen Startplatz an einem Tag wie ein Pilot beurteilen."""
        return (f"Beurteile den Startplatz '{spot}' am {date} wie ein erfahrener Pilot. Lies wingcast://guide/pilot_evaluation, "
                f"dann spot_info, spot_series, spot_detail und spot_altitude_wind. Beschreibe den Verlauf über den Tag und über die "
                f"Höhe, nenne das brauchbare Fenster mit Begründung, alle Warnungen, und was ein Pilot vor Ort prüfen sollte.")


def _foehn_lines(store: ExportStore, dates: list[str], full: bool = False) -> str:
    f = store.foehn or {}
    if not f.get("available"):
        return "Föhn: keine Zeitreihe im Export (Fetch fehlgeschlagen) — Föhn-Spalten der Spots tragen 'unknown'."
    out = []
    for d in dates:
        hrs = f.get("days", {}).get(d) or []
        if not hrs:
            out.append(f"Föhn {fmt.day_label(d)}: keine Daten")
            continue
        worst = max(hrs, key=lambda x: {"none": 0, "caution": 1, "danger": 2}.get(x.get("level"), 0))
        dps = [x["delta_p"] for x in hrs if x.get("delta_p") is not None]
        head = (f"Föhn {fmt.day_label(d)}: max Level {worst.get('level')} ({worst.get('direction')}), "
                f"ΔP {fmt._rng(dps, 1)} hPa, Kammwind 700 hPa {fmt._rng([x['crest_wind'] for x in hrs])} km/h")
        out.append(head)
        if full:
            out.append("  Uhr | Level | Richtung | ΔP hPa | Kammwind km/h aus | RH Nord %")
            out += [f"  {x['hour']:02d} | {x['level']} | {x.get('direction') or '-'} | {fmt._f(x['delta_p'], 1)} | "
                    f"{fmt._f(x['crest_wind'])} {fmt._dir8(x.get('crest_dir'))} | {fmt._f(x.get('humidity_nord'))}" for x in hrs]
    return "\n".join(out)
