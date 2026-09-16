"""python -m mcp_server [--transport stdio|streamable-http] [--host H] [--port P] [--export-dir DIR]

Betrieb auf dem Server (wingcast-mcp.service): streamable-http auf 127.0.0.1:5100,
Caddy leitet https://app.wingcast.ch/mcp dorthin. Erlaubte Hosts und Rate-Limit
kommen aus WINGCAST_MCP_HOSTS (kommagetrennt) / WINGCAST_MCP_RATE_PER_MIN.
"""
from __future__ import annotations

import argparse
import os
import sys

# Projektroot importierbar machen (routing, config, …)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> None:
    p = argparse.ArgumentParser(description="wingcast MCP-Server (Forecast-Daten)")
    p.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5100)
    p.add_argument("--export-dir", default=os.environ.get("WINGCAST_MCP_EXPORT_DIR"))
    p.add_argument("--allowed-hosts", default=os.environ.get("WINGCAST_MCP_HOSTS", "app.wingcast.ch,localhost:5100,127.0.0.1:5100"))
    p.add_argument("--rate-per-min", type=int, default=int(os.environ.get("WINGCAST_MCP_RATE_PER_MIN", "60")))
    args = p.parse_args()

    from mcp_server.server import build_http_app, build_server
    server = build_server(args.export_dir)
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        import uvicorn
        hosts = [h.strip() for h in args.allowed_hosts.split(",") if h.strip()]
        app = build_http_app(server, allowed_hosts=hosts, rate_per_min=args.rate_per_min, host=args.host)
        uvicorn.run(app, host=args.host, port=args.port, log_level="info", proxy_headers=True, forwarded_allow_ips="127.0.0.1")


if __name__ == "__main__":
    main()
