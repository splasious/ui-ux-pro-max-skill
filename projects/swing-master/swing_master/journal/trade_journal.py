"""Trade journal (Section 44) and chart snapshots for entry/exit."""
from __future__ import annotations

import csv
import io
from typing import Dict, List

JOURNAL_COLUMNS = [
    "trade_id", "symbol", "direction", "timeframe", "signal_time", "entry_time", "exit_time", "pivot_time",
    "pivot_confirmation_time", "structure", "structure_event", "zone_type", "zone_pattern", "zone_score",
    "poc", "vah", "val", "commercial", "institutional", "retail", "oi_state", "pcr", "change_oi_pcr",
    "candlestick", "confluence", "entry", "stop", "t1", "t2", "t3", "quantity", "partial_exits",
    "trail_changes", "gross_pnl", "costs", "net_pnl", "r_multiple", "holding_bars", "exit_reason",
]


def journal_entry(trade) -> Dict:
    d = trade.to_dict()
    s = d["snapshot"]
    return {
        "trade_id": d["trade_id"], "symbol": d["symbol"], "direction": d["direction"], "timeframe": d["timeframe"],
        "status": d["status"],
        "signal_time": d["signal_time"], "entry_time": d["entry_time"], "exit_time": d["exit_time"],
        "pivot_time": s.get("pivot_time"), "pivot_confirmation_time": s.get("pivot_confirmation_time"),
        "structure": s.get("structure"), "structure_event": s.get("structure_event"),
        "zone_type": s.get("zone_type"), "zone_pattern": s.get("zone_pattern"), "zone_score": s.get("zone_score"),
        "poc": s.get("poc"), "vah": s.get("vah"), "val": s.get("val"),
        "commercial": s.get("commercial"), "institutional": s.get("institutional"), "retail": s.get("retail"),
        "oi_state": s.get("oi_state"), "pcr": s.get("pcr"), "change_oi_pcr": s.get("change_oi_pcr"),
        "candlestick": s.get("candlestick"), "confluence": s.get("confluence"),
        "entry": d["entry"], "exit_price": d["exit_price"], "stop": d["initial_stop"], "current_stop": d["current_stop"],
        "t1": d["targets"][0], "t2": d["targets"][1], "t3": d["targets"][2], "quantity": d["quantity"],
        "partial_exits": [f for f in d["fills"] if f["reason"] != "ENTRY"],
        "trail_changes": len(d["trail_history"]) - 1, "trail_history": d["trail_history"],
        "gross_pnl": d["gross_pnl"], "costs": d["costs"], "net_pnl": d["net_pnl"], "r_multiple": d["r_multiple"],
        "holding_bars": d["holding_bars"], "exit_reason": d["exit_reason"], "mfe_r": d["mfe_r"], "mae_r": d["mae_r"],
        "snapshot": s,
    }


def build_journal(trades: List) -> List[Dict]:
    return [journal_entry(t) for t in sorted(trades, key=lambda t: t.entry_time, reverse=True)]


def export_csv(entries: List[Dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=JOURNAL_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for e in entries:
        row = dict(e)
        row["partial_exits"] = "; ".join(f"{f['reason']} {f['qty']}@{f['price']}" for f in e["partial_exits"])
        w.writerow(row)
    return buf.getvalue()


def chart_snapshot(dataset, trade, before: int = 30, after: int = 5) -> Dict:
    """Compact OHLC window around the trade for the journal's entry/exit snapshot."""
    bars = dataset.bars
    start = max(0, trade.entry_bar - before)
    end_bar = trade.exit_bar if trade.exit_bar is not None else len(bars) - 1
    end = min(len(bars), end_bar + after + 1)
    return {
        "bars": [b.to_dict() for b in bars[start:end]],
        "offset": start,
        "entry_bar": trade.entry_bar,
        "exit_bar": trade.exit_bar,
        "levels": {"entry": trade.entry, "stop": trade.initial_stop, "t1": trade.targets[0], "t2": trade.targets[1],
                   "t3": trade.targets[2]},
        "trail": trade.trail_history,
    }
