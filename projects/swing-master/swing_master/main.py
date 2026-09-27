"""Command-line entry point.

    python -m swing_master.main serve [--port 8765] [--open]
    python -m swing_master.main scan
    python -m swing_master.main backtest
    python -m swing_master.main walkforward
    python -m swing_master.main export-static OUT.html [--artifact]
"""
from __future__ import annotations

import argparse
import json
import sys

from .app import Platform
from .config import AppSettings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="swing_master", description="Swing Master research platform")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the dashboard")
    s.add_argument("--host", default=None)
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--open", action="store_true", help="open a browser tab")
    sub.add_parser("scan", help="print the scanner table")
    sub.add_parser("backtest", help="print full-history backtest KPIs")
    sub.add_parser("walkforward", help="run the walk-forward lab")
    e = sub.add_parser("export-static", help="write a self-contained HTML snapshot of the UI")
    e.add_argument("out")
    e.add_argument("--artifact", action="store_true", help="omit the document skeleton (for artifact hosting)")
    args = ap.parse_args(argv)

    settings = AppSettings()
    platform = Platform(settings, persist=args.cmd == "serve")
    if args.cmd == "serve":
        from .dashboard.server import serve
        serve(platform, args.host or settings.HOST, args.port or settings.PORT, args.open)
    elif args.cmd == "scan":
        for r in platform.scan["rows"]:
            print(f"{r['status']:<9} {r['direction']:<5} {r['symbol']:<11} {r['price']:>10.2f}  "
                  f"{(r.get('zone') or '-'):<28} conf={r.get('confluence') or '-'}  {r.get('reason') or ''}")
        print(json.dumps(platform.scan["funnel"]))
    elif args.cmd == "backtest":
        print(json.dumps(platform.backtest_report["metrics"], indent=2))
    elif args.cmd == "walkforward":
        wf = platform.walk_forward(background=False)
        print(json.dumps(wf.get("summary"), indent=2))
        for f in wf.get("folds", []):
            print(f["fold"], f["test"], f["params"], "IS avgR", f["train_metrics"]["average_r"],
                  "OOS avgR", f["test_metrics"]["average_r"], "OOS trades", f["test_metrics"]["total_trades"])
    elif args.cmd == "export-static":
        from .dashboard.export_static import export
        size = export(platform, args.out, artifact=args.artifact)
        print(f"wrote {args.out} ({size / 1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
