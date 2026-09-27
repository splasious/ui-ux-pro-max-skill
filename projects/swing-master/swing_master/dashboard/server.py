"""Dependency-free HTTP server for the dashboard (standard library only).

Binds to 127.0.0.1 by default.  Serves the single-page UI from
``application_ui/`` and JSON endpoints under ``/api``.
"""
from __future__ import annotations

import json
import mimetypes
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from ..logging_utils import log
from ..schemas import to_jsonable
from . import api

UI_ROOT = Path(__file__).resolve().parent / "application_ui"


def _q(qs, key, default=None):
    v = qs.get(key)
    return v[0] if v else default


def route_get(p, path: str, qs) -> object:
    sym = _q(qs, "symbol", "NIFTY")
    tf = _q(qs, "tf", "1D")
    routes = {
        "/api/meta": lambda: api.meta(p),
        "/api/overview": lambda: api.overview(p),
        "/api/scanner": lambda: api.scanner(p, _q(qs, "status"), _q(qs, "direction"), tf),
        "/api/mtf": lambda: api.mtf_payload(p, sym),
        "/api/proposals": lambda: p.proposals(),
        "/api/chart": lambda: api.chart(p, sym, tf, _q(qs, "profile", "FIXED")),
        "/api/zones": lambda: api.zones_payload(p, sym, tf),
        "/api/volume-profile": lambda: api.volume_profile_payload(p, sym, tf, _q(qs, "type", "FIXED"), int(_q(qs, "lookback", "0"))),
        "/api/positioning": lambda: api.positioning_payload(p),
        "/api/derivatives": lambda: api.derivatives_payload(p, sym, int(_q(qs, "days", "30")), int(_q(qs, "strikes", "0"))),
        "/api/candles": lambda: api.candles_payload(p, sym, tf, int(_q(qs, "lookback", "60"))),
        "/api/setup": lambda: api.setup_payload(p, sym, tf),
        "/api/trades": lambda: api.trades_payload(p),
        "/api/risk": lambda: api.risk_payload(p),
        "/api/backtest": lambda: api.backtest_payload(p, _q(qs, "custom") == "1"),
        "/api/backtest/ablation": lambda: api.ablation_payload(p),
        "/api/walkforward": lambda: api.walk_forward_payload(p),
        "/api/journal": lambda: api.journal_payload(p, _q(qs, "source", "backtest")),
        "/api/rejected": lambda: api.rejected_payload(p, _q(qs, "symbol"), _q(qs, "reason"), int(_q(qs, "limit", "300"))),
        "/api/reports": lambda: api.reports_payload(p),
        "/api/health": lambda: api.health_payload(p),
        "/api/settings": lambda: api.settings_payload(p),
        "/api/notifications": lambda: api.notifications_payload(p),
    }
    if path in routes:
        return routes[path]()
    if path.startswith("/api/journal/"):
        detail = api.journal_detail(p, unquote(path.rsplit("/", 1)[1]))
        if detail is None:
            raise KeyError("trade not found")
        return detail
    raise KeyError(path)


def route_post(p, path: str, body: dict) -> object:
    if path == "/api/backtest/run":
        p.run_backtest(body.get("components") or [], body.get("overrides") or {})
        return api.backtest_payload(p, custom=True)
    if path == "/api/settings":
        p.reconfigure(body.get("overrides") or {})
        return api.settings_payload(p)
    if path in ("/api/proposals/confirm", "/api/proposals/reject"):
        return p.decide_proposal(str(body.get("id", "")), path.endswith("confirm"))
    if path == "/api/notifications/config":
        from ..notifications import EVENT_TYPES
        events = [e for e in body.get("events", []) if e in EVENT_TYPES]
        p.notify_events = set(events)
        return api.notifications_payload(p)
    if path == "/api/mode":
        mode = str(body.get("mode", "")).upper()
        if mode == "AUTO" and not p.settings.LIVE_TRADING_ENABLED:
            raise PermissionError("AUTO requires SM_LIVE_TRADING_ENABLED=1, a configured broker and validated research")
        from ..execution.order_manager import MODES
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        p.execution_mode = mode
        log("system", f"execution mode set to {mode}")
        return {"execution_mode": mode}
    raise KeyError(path)


def make_handler(platform):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SwingMaster/0.1"

        def log_message(self, fmt, *args):  # quiet access log; errors are logged explicitly
            return

        def _send(self, code: int, payload, ctype: str = "application/json; charset=utf-8"):
            data = payload if isinstance(payload, bytes) else json.dumps(to_jsonable(payload)).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _error(self, code: int, exc: Exception):
            if code >= 500:
                log("error", f"{self.path}: {exc}", trace=traceback.format_exc(limit=4))
            self._send(code, {"error": type(exc).__name__, "detail": str(exc)})

        def do_GET(self):
            url = urlparse(self.path)
            if url.path.startswith("/api/"):
                if url.path == "/api/journal.csv":
                    from ..journal import export_csv
                    csv_text = export_csv(api.journal_payload(platform)["entries"])
                    return self._send(200, csv_text.encode(), "text/csv; charset=utf-8")
                try:
                    return self._send(200, route_get(platform, url.path, parse_qs(url.query)))
                except KeyError as exc:
                    return self._error(404, exc)
                except Exception as exc:  # reported to the UI, never silently suppressed
                    return self._error(500, exc)
            rel = "index.html" if url.path in ("", "/") else unquote(url.path.lstrip("/"))
            target = (UI_ROOT / rel).resolve()
            if not str(target).startswith(str(UI_ROOT)) or not target.is_file():
                return self._send(404, {"error": "not found"})
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            self._send(200, target.read_bytes(), ctype)

        def do_POST(self):
            url = urlparse(self.path)
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                with platform.lock:
                    return self._send(200, route_post(platform, url.path, body))
            except KeyError as exc:
                return self._error(404, exc)
            except (ValueError, PermissionError) as exc:
                return self._error(400, exc)
            except Exception as exc:
                return self._error(500, exc)

    return Handler


def serve(platform, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    httpd = ThreadingHTTPServer((host, port), make_handler(platform))
    url = f"http://{host}:{port}/"
    print(f"Swing Master running at {url}  (Ctrl+C to stop)")
    if open_browser:
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
