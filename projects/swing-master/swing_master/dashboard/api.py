"""JSON payload builders for every screen.  Pure functions of the Platform state."""
from __future__ import annotations

from datetime import timedelta
from typing import Dict, List, Optional

from ..config.scoring_config import (ABLATION_LADDER, CANDLE_RULES, COMPONENTS, CONFLUENCE_WEIGHTS, PCR_BANDS_LONG,
                                     ZONE_SCORE_WEIGHTS)
from ..config.strategy_config import EDITABLE_PARAMETERS
from ..derivatives.pcr import compute_pcr
from ..execution.order_manager import MODES
from ..indicators.utilities import ema_series, volatility_profile
from ..journal import build_journal, chart_snapshot
from ..logging_utils import counts as log_counts, recent as recent_logs
from ..notifications import EVENT_TYPES
from ..positioning import divergence
from ..price_action.candlesticks import detect_patterns
from ..risk.portfolio_risk import correlation_warnings, exposure_report, open_risk
from ..risk.position_size import position_size
from ..schemas import Trend, to_jsonable
from ..strategy.long_setup import LONG_SPEC
from ..strategy.short_setup import SHORT_SPEC
from ..strategy.signal_engine import decide, why_lines
from ..volume_profile.confluence import price_location, relation, zone_profile_confluence
from ..volume_profile.profile import PROFILE_TYPES
from ..zones.zone_lifecycle import distance_to_zone
from ..zones.zone_quality import score_zone, zone_components

TIMEFRAMES = ["1M", "1W", "1D", "4H", "1H", "15m", "5m"]


def _r(x, n=2):
    return None if x is None else round(x, n)


def _series_close(bars, n=60):
    return [round(b.close, 2) for b in bars[-n:]]


# --------------------------------------------------------------------------- #
def meta(p) -> Dict:
    return {
        "app": p.settings.APP_NAME, "version": p.settings.VERSION, "status": p.status,
        "demo": p.provider.is_demo, "source": p.provider.source_label,
        "as_of": p.as_of.isoformat(), "built_at": p.built_at.isoformat() if getattr(p, "built_at", None) else None,
        "timings": p.timings, "timeframes": TIMEFRAMES, "modes": list(MODES), "execution_mode": p.execution_mode,
        "live_enabled": p.settings.LIVE_TRADING_ENABLED,
        "universe": [{"symbol": i.symbol, "name": i.name, "sector": i.sector, "is_index": i.is_index,
                      "lot_size": i.lot_size, "has_options": i.has_options} for i in p.universe],
        "market": "NSE", "universe_name": p.universe_info["label"] + (" (demo subset)" if p.provider.is_demo else ""),
        "universe_info": {k: v for k, v in p.universe_info.items() if k != "missing_data"}
        | {"missing_data": len(p.universe_info["missing_data"])},
        "profile_types": list(PROFILE_TYPES),
        "min_conf": p.cfg.MIN_CONFLUENCE_SCORE, "min_zone": p.cfg.MIN_ZONE_SCORE,
        "scanner_timeframes": ["1W", "1D", "4H", "1H"], "mtf_hierarchy": p.cfg.MTF_HIERARCHY,
    }


def market_context(p) -> Dict:
    nifty = p.datasets[p._anchor_symbol()]
    bars = nifty.bars
    last, prev = bars[-1], bars[-2]
    ema200 = ema_series([b.close for b in bars], 200)[-1]
    trend = nifty.analyzer.structure.trend
    stocks = [ds for ds in p.datasets.values() if not ds.instrument.is_index]
    adv = sum(1 for ds in stocks if ds.bars[-1].close > ds.bars[-2].close)
    dec = sum(1 for ds in stocks if ds.bars[-1].close < ds.bars[-2].close)
    above50 = sum(1 for ds in stocks if ds.bars[-1].close > sum(b.close for b in ds.bars[-50:]) / 50)
    breadth_hist = []
    for k in range(30, 0, -1):
        a = sum(1 for ds in stocks if len(ds.bars) > k and ds.bars[-k].close > ds.bars[-k - 1].close)
        breadth_hist.append(round(a / max(len(stocks), 1), 3))
    vix = p.provider.volatility_index()
    vix_card = None
    if vix:
        vix_card = {"value": vix[-1].close, "change": _r(vix[-1].close - vix[-2].close),
                    "change_pct": _r(100 * (vix[-1].close / vix[-2].close - 1)), "series": _series_close(vix, 60),
                    "label": "INDIA VIX (demo)" if p.provider.is_demo else "INDIA VIX"}
    regime = trend if trend in (Trend.BULLISH, Trend.BEARISH) else "RANGE / TRANSITION"
    word = {"BULLISH": "UPTREND", "BEARISH": "DOWNTREND"}.get(regime, "TRANSITION")
    return {
        "index": {"symbol": nifty.symbol, "name": nifty.instrument.name, "price": last.close,
                  "change": _r(last.close - prev.close), "change_pct": _r(100 * (last.close / prev.close - 1)),
                  "series": _series_close(bars, 90), "time": last.close_time.isoformat()},
        "regime": {"label": word, "structure": trend, "htf": nifty.htf.trend,
                   "above_ema200": ema200 is not None and last.close > ema200,
                   "ema200": _r(ema200), "detail": f"Structure {trend.title()} | "
                                                   f"{'Above' if ema200 and last.close > ema200 else 'Below'} 200 EMA"},
        "breadth": {"advances": adv, "declines": dec, "unchanged": len(stocks) - adv - dec, "universe": len(stocks),
                    "adv_pct": _r(adv / max(len(stocks), 1), 3), "above_50dma": above50, "history": breadth_hist,
                    "label": f"Universe breadth ({len(stocks)} stocks)"},
        "vix": vix_card,
        "health": health_summary(p),
    }


def health_summary(p) -> Dict:
    h = p.provider.health()
    bad = [k for k, v in h.items() if v["status"] in ("DOWN", "ERROR")]
    return {"label": "All systems operational" if not bad else f"{len(bad)} feed(s) down",
            "ok": not bad, "demo": p.provider.is_demo,
            "feeds": {k: v["status"] for k, v in h.items() if k in ("market_feed", "futures_oi", "options_feed",
                                                                        "positioning_feed")}}


def account(p, result=None, report=None) -> Dict:
    result = result or p.paper
    report = report or p.paper_report
    m = report["metrics"]
    eq = result.equity_curve
    last = eq[-1] if eq else {"equity": result.initial_capital, "cash": result.initial_capital, "invested": 0}
    prev = eq[-2] if len(eq) > 1 else last
    unreal = sum(t.unrealized(t.last_price) for t in result.open_trades)
    realized = sum(t.net_pnl for t in result.trades) + sum(t.gross_pnl - t.costs for t in result.open_trades)
    return {
        "capital": result.initial_capital, "equity": last["equity"], "cash": last["cash"], "invested": last["invested"],
        "day_pnl": _r(last["equity"] - prev["equity"]), "day_pnl_pct": _r((last["equity"] / prev["equity"] - 1) * 100),
        "open_pnl": _r(unreal), "realized_pnl": _r(realized), "total_pnl": _r(last["equity"] - result.initial_capital),
        "total_pnl_pct": _r((last["equity"] / result.initial_capital - 1) * 100),
        "open_positions": len(result.open_trades), "open_risk": _r(sum(open_risk(t) for t in result.open_trades)),
        "open_risk_pct": _r(100 * sum(open_risk(t) for t in result.open_trades) / last["equity"], 2),
        "max_risk_pct": p.cfg.MAX_PORTFOLIO_RISK * 100, "risk_per_trade_pct": p.cfg.RISK_PER_TRADE * 100,
        "win_rate": m.get("win_rate"), "avg_r": m.get("average_r"), "closed_trades": m.get("total_trades"),
        "equity_series": [x["equity"] for x in eq[-90:]],
        "session_start": result.start.isoformat() if result.start else None,
    }


def overview(p) -> Dict:
    rows = p.scan["rows"]
    top_long = [r for r in rows if r["direction"] == "LONG" and r["status"] != "REJECTED"][:6]
    top_short = [r for r in rows if r["direction"] == "SHORT" and r["status"] != "REJECTED"][:6]
    snaps = p.positioning.snapshot(p.as_of + timedelta(hours=6))
    nifty = p.datasets[p._anchor_symbol()]
    oi = nifty.derivs.oi_state(p.as_of + timedelta(hours=6)) if nifty.derivs else None
    recent = sorted(p.paper.signals, key=lambda s: s["time"], reverse=True)[:14]
    focus = next((r["symbol"] for r in rows if r["status"] in ("READY", "ACTIVE", "WAIT")), p._anchor_symbol())
    return {
        "focus_symbol": focus,
        "market": market_context(p),
        "account": account(p),
        "active_trades": [trade_row(t) for t in p.paper.open_trades],
        "top_long": top_long, "top_short": top_short,
        "scanner_counts": p.scan["counts"], "funnel": p.scan["funnel"],
        "positioning": {k: v.to_dict() for k, v in snaps.items()},
        "positioning_proxy": oi,
        "recent_signals": recent,
        "notifications": list(p.bus.history)[-12:][::-1],
    }


# --------------------------------------------------------------------------- #
def trade_row(t) -> Dict:
    d = t.to_dict()
    d["last_confirmed_pivot"] = t.last_trail_pivot
    d["current_r"] = d["r_multiple"]
    return d


def scanner(p, status: Optional[str] = None, direction: Optional[str] = None, tf: str = "1D") -> Dict:
    sc = p.scan_tf(tf)
    rows = sc["rows"]
    if status:
        rows = [r for r in rows if r["status"] == status.upper()]
    if direction:
        rows = [r for r in rows if r["direction"] == direction.upper()]
    return {"rows": rows, "funnel": sc["funnel"], "counts": sc["counts"], "as_of": p.as_of.isoformat(),
            "timeframe": tf, "watch_distance_atr": 2.0}


# --------------------------------------------------------------------------- #
def chart(p, symbol: str, tf: str = "1D", profile_type: str = "FIXED", bars_n: int = 320) -> Dict:
    ds = p.dataset(symbol, tf)
    an = ds.analyzer
    n = len(an.bars)
    off = max(0, n - bars_n)
    bars = an.bars[off:]
    pivots = [pv for pv in an.pivots.pivots if pv.pivot_bar >= off]
    cand = an.zigzag.candidate()
    zones = []
    for z in an.zones.zones:
        if z.creation_bar < off - 150:
            continue
        inval = z.is_invalidated_as_of(an.i)
        if inval and z.invalidation_bar < off:
            continue
        if not inval and z not in an.zones.active():
            continue
        zones.append(z.to_dict(an.i))
    zones = zones[-24:]
    vp = an.profile(profile_type)
    events = [e.to_dict() for e in an.events.events if e.event_bar >= off]
    trade = next((t for t in p.paper.open_trades if t.symbol == symbol), None) if tf == "1D" else None
    plan = None
    latest = [e for e in ds.evaluations if e.bar == an.i and e.trigger == "ZONE"]
    if latest:
        best = max(latest, key=lambda e: (e.decision["accepted"], e.decision["confluence"]["score"]))
        plan = {"direction": best.direction, "entry": _r(best.entry_ref), "stop": _r(best.stop),
                "t1": _r(best.targets.get("t1")), "t2": _r(best.targets.get("t2")), "t3": _r(best.targets.get("t3")),
                "status": best.decision["status"], "score": best.decision["confluence"]["score"]}
    markers = []
    if tf == "1D":
        for t in list(p.backtest.trades) + list(p.paper.open_trades):
            if t.symbol != symbol:
                continue
            if t.entry_bar >= off:
                markers.append({"bar": t.entry_bar, "kind": "entry", "direction": t.direction,
                                "price": round(t.entry, 2), "trade_id": t.trade_id})
            if t.exit_bar is not None and t.exit_bar >= off:
                markers.append({"bar": t.exit_bar, "kind": "exit", "direction": t.direction,
                                "price": round(t.exit_price, 2), "reason": t.exit_reason, "trade_id": t.trade_id})
    last, prev = an.bars[-1], an.bars[-2] if n > 1 else an.bars[-1]
    patterns = []
    for k in range(max(off, n - 40), n):
        for pr in detect_patterns(an.bars, k, an.atr_values[k], p.cfg.PATTERN_MIN_RANGE_ATR):
            patterns.append({"bar": k, "pattern": pr.pattern, "direction": pr.direction,
                             "confidence": round(pr.confidence, 2)})
    return {
        "symbol": symbol, "name": ds.instrument.name, "timeframe": tf, "htf": p.cfg.MTF_HIERARCHY.get(tf),
        "note": "Forming period excluded: only completed candles are analysed." if tf in ("1W", "1M") else None,
        "source": p.provider.source_label, "offset": off, "total_bars": n,
        "bars": [b.to_dict() for b in bars],
        "pivots": [pv.to_dict() for pv in pivots],
        "candidate": None if cand is None else {"type": cand[0], "price": _r(cand[1]), "bar": cand[2],
                                                "status": "UNCONFIRMED"},
        "events": events, "zones": zones,
        "profile": None if vp is None else vp.to_dict(),
        "profile_type": profile_type,
        "trade": None if trade is None else trade_row(trade),
        "plan": plan, "markers": markers, "patterns": patterns,
        "summary": {"trend": an.structure.trend, "htf_trend": ds.htf.trend, "atr": _r(an.atr),
                    "last": last.to_dict(), "change": _r(last.close - prev.close),
                    "change_pct": _r(100 * (last.close / prev.close - 1)),
                    "last_pivot": an.pivots.last(an.i).to_dict() if an.pivots.pivots else None,
                    "last_event": an.events.events[-1].to_dict() if an.events.events else None,
                    "price_location": price_location(last.close, vp),
                    "volatility": volatility_profile(an.atr_values, [b.close for b in an.bars], p.cfg.ATR_PERCENTILE_LOOKBACK)},
    }


def zones_payload(p, symbol: str, tf: str = "1D") -> Dict:
    ds = p.dataset(symbol, tf)
    an = ds.analyzer
    atr = an.atr or 0.0
    vp = an.profile()
    price = an.bars[-1].close
    htf = ds.htf.trend if ds.htf.trend != Trend.UNDEFINED else None
    cards = []
    active = an.zones.active()
    for z in reversed(an.zones.zones):
        inval = z.is_invalidated_as_of(an.i)
        if not inval and z not in active:
            continue
        if inval and z.invalidation_bar < an.i - 60:
            continue
        if len(cards) >= 18:
            break
        vpc = zone_profile_confluence(z, vp, atr, p.cfg.VP_NEAR_ATR)
        fr = zone_components(z, an.i, False, an.pivots.confirmed_as_of(an.i), an.events.events, atr, htf,
                             vpc["poc_fraction"], vpc["score"], None, None, None)
        sc = score_zone(fr, p.cfg.UNAVAILABLE_FACTOR_POLICY)
        d = z.to_dict(an.i)
        d.update({
            "score": sc["score"], "score_rows": sc["rows"], "coverage": sc["coverage"],
            "distance_atr": _r(distance_to_zone(z, price) / atr, 2) if atr else None,
            "poc_alignment": vpc["levels"].get("POC", {}).get("relation") if vpc["available"] else None,
            "htf_alignment": {None: "UNDEFINED", 1.0: "ALIGNED", 0.0: "OPPOSED", 0.5: "NEUTRAL"}.get(fr["htf_alignment"]),
            "pivot_alignment": bool(fr["pivot_alignment"]),
            "structure_alignment": _structure_alignment(z.zone_type, z.trend_at_creation, an.structure.trend),
            "invalidation_rule": (f"{'Close' if z.invalidation_mode == 'CLOSE' else 'Any trade'} "
                                  f"{'below' if z.zone_type == 'DEMAND' else 'above'} {z.distal:.2f}"),
            "origin_date": z.origin_timestamp.date().isoformat(),
            "freshness_note": "Score components needing a live test (candle, R:R, positioning) are pending",
        })
        cards.append(d)
    return {"symbol": symbol, "timeframe": tf, "price": price, "atr": _r(atr), "zones": cards,
            "weights": ZONE_SCORE_WEIGHTS, "min_zone_score": p.cfg.MIN_ZONE_SCORE}


def _structure_alignment(zone_type: str, at_creation: str, now: str) -> str:
    want = "BULLISH" if zone_type == "DEMAND" else "BEARISH"
    opp = "BEARISH" if want == "BULLISH" else "BULLISH"
    tag = lambda t: "WITH" if t == want else "AGAINST" if t == opp else "NEUTRAL"  # noqa: E731
    return f"{tag(at_creation)} trend at creation / {tag(now)} now"


def volume_profile_payload(p, symbol: str, tf: str = "1D", kind: str = "FIXED", lookback: int = 0) -> Dict:
    ds = p.dataset(symbol, tf)
    an = ds.analyzer
    if lookback and kind.upper() in ("FIXED", "HIGHER_TF"):
        from ..volume_profile.profile import build_profile, profile_window
        s, e = profile_window(kind, an.bars, an.i, an.pivots.confirmed_as_of(an.i), lookback)
        vp = build_profile(an.bars, s, e, p.cfg.VOLUME_PROFILE_BINS, p.cfg.VALUE_AREA_PERCENT, kind.upper(),
                           p.cfg.HVN_THRESHOLD, p.cfg.LVN_THRESHOLD)
    else:
        vp = an.profile(kind)
    atr = an.atr or 0.0
    rel = []
    for z in an.active_zones():
        vpc = zone_profile_confluence(z, vp, atr, p.cfg.VP_NEAR_ATR)
        rel.append({"zone": z.to_dict(an.i), "confluence": vpc})
    price = an.bars[-1].close
    return {"symbol": symbol, "timeframe": tf, "type": kind, "types": list(PROFILE_TYPES),
            "lookback": lookback or p.cfg.VP_LOOKBACK_BARS,
            "profile": vp.to_dict() if vp else None, "price": price, "location": price_location(price, vp),
            "atr": _r(atr), "relations": rel,
            "method": "Uniform-range approximation: each bar's volume spread evenly over its high-low range."}


# --------------------------------------------------------------------------- #
def positioning_payload(p) -> Dict:
    as_of = p.as_of + timedelta(hours=6)
    snaps = p.positioning.snapshot(as_of)
    proxies = []
    for sym in ("NIFTY", "BANKNIFTY", "FINNIFTY"):
        ds = p.datasets.get(sym)
        if ds is None or ds.derivs is None or ds.derivs.futures is None:
            continue
        proxies.append({"symbol": sym, "state": ds.derivs.oi_state(as_of),
                        "state_5d": ds.derivs.futures.state_as_of(as_of, 5),
                        "history": ds.derivs.futures.history(as_of, 30)})
    return {
        "categories": {k: v.to_dict() for k, v in snaps.items()},
        "divergence": divergence(snaps["COMMERCIAL"], snaps["INSTITUTIONAL"], snaps["RETAIL"]),
        "proxies": proxies,
        "bands": list(p.cfg.POSITIONING_BANDS),
        "source_help": ("Load NSE participant-wise OI (date, participant, future_index_long, future_index_short) "
                        "via SM_POSITIONING_CSV or participant_oi.csv in SM_DATA_DIR. Client -> Retail, "
                        "FII + DII -> Institutional, Pro -> Commercial. Never derived from OHLCV."),
        "as_of": as_of.isoformat(),
    }


def derivatives_payload(p, symbol: str, days: int = 30, strikes_each_side: int = 0) -> Dict:
    n_side = strikes_each_side or p.cfg.PCR_STRIKES_EACH_SIDE
    ds = p.datasets[symbol]
    as_of = p.as_of + timedelta(hours=6)
    fut = None
    if ds.derivs and ds.derivs.futures:
        fut = {"state": ds.derivs.oi_state(as_of), "history": ds.derivs.futures.history(as_of, days)}
    options = None
    if ds.instrument.has_options:
        dates = [b.timestamp.date() for b in ds.bars[-days:]]
        hist = []
        for d in dates:
            info = ds.derivs.pcr(d, as_of)
            if info and info.get("available"):
                hist.append({"date": d.isoformat(), "pcr": info["pcr"], "change_oi_pcr": info["change_oi_pcr"],
                             "rollover": info["expiry_rollover"]})
        chain = p.provider.option_chain(symbol, dates[-1])
        now = compute_pcr(chain, n_side, p.cfg.PCR_MIN_STRIKE_OI)
        strikes = []
        if chain:
            lo, hi = now["strike_range"]
            strikes = [{"strike": s.strike, "call_oi": s.call_oi, "put_oi": s.put_oi, "call_change_oi": s.call_change_oi,
                        "put_change_oi": s.put_change_oi, "selected": lo <= s.strike <= hi}
                       for s in sorted(chain.strikes, key=lambda s: s.strike)]
        options = {"now": now, "history": hist, "strikes": strikes, "strikes_each_side": n_side}
    return {"symbol": symbol, "futures": fut, "options": options, "days": days,
            "source": "DEMO" if p.provider.is_demo else "PROXY",
            "note": "Futures OI is a POSITIONING PROXY. PCR is context, not a standalone signal."}


def candles_payload(p, symbol: str, tf: str = "1D", lookback: int = 60) -> Dict:
    ds = p.dataset(symbol, tf)
    an = ds.analyzer
    n = len(an.bars)
    rows = []
    for k in range(max(p.cfg.WARMUP_BARS, n - lookback), n):
        atr = an.atr_values[k]
        pats = detect_patterns(an.bars, k, atr, p.cfg.PATTERN_MIN_RANGE_ATR)
        if not pats:
            continue
        zones_k = [z for z in an.zones.zones if z.creation_bar < k and not z.is_invalidated_as_of(k)]
        vp = None
        for pr in pats:
            want = "DEMAND" if pr.direction == "BULLISH" else "SUPPLY"
            zrel = "NONE"
            near = [relation(an.bars[k].low if want == "DEMAND" else an.bars[k].high, z, atr, 0.5)
                    for z in zones_k if z.zone_type == want]
            if near:
                best = min(near, key=lambda r: {"INSIDE": 0, "NEAR": 1, "FAR": 2}[r["relation"]])
                zrel = best["relation"]
            if vp is None:
                from ..volume_profile.profile import build_profile, profile_window
                s, e = profile_window("FIXED", an.bars, k, an.pivots.confirmed_as_of(k), p.cfg.VP_LOOKBACK_BARS)
                vp = build_profile(an.bars, s, e, p.cfg.VOLUME_PROFILE_BINS, p.cfg.VALUE_AREA_PERCENT)
            poc_dist = abs(an.bars[k].close - vp.poc) / atr if vp and atr else None
            rows.append({"bar": k, "time": an.bars[k].timestamp.isoformat(), "pattern": pr.pattern,
                         "direction": pr.direction, "confidence": round(pr.confidence, 2), **pr.metrics,
                         "zone_relationship": zrel,
                         "poc_relationship": None if poc_dist is None else ("NEAR" if poc_dist <= 1 else "FAR"),
                         "poc_distance_atr": _r(poc_dist), "ohlc": an.bars[k].to_dict()})
    return {"symbol": symbol, "timeframe": tf, "rows": rows[::-1], "lookback": lookback,
            "definitions": _pattern_definitions()}


def _pattern_definitions() -> List[Dict]:
    return [
        {"pattern": "Hammer / Shooting Star", "rule": "Long wick >= 2x body, opposite wick <= 25% of range, close in the favourable 40%"},
        {"pattern": "Pin Bar", "rule": "Wick >= 66% of range, body <= 33%, probes beyond prior low/high, range >= 0.8 ATR"},
        {"pattern": "Engulfing", "rule": "Opposite-coloured prior candle whose body is fully engulfed by a larger body"},
        {"pattern": "Morning / Evening Star", "rule": "Large candle (>= 0.6 ATR body), small middle body, close beyond first body's midpoint"},
        {"pattern": "Tweezer Bottom / Top", "rule": "Opposite-coloured pair with lows/highs within 0.1 ATR, both ranges >= 0.5 ATR"},
        {"pattern": "Rejection", "rule": "Wick >= 50% of range, close in the top/bottom 30%, range >= 0.8 ATR, beyond the prior two bars"},
    ]


# --------------------------------------------------------------------------- #
def setup_payload(p, symbol: str, tf: str = "1D") -> Dict:
    ds = p.dataset(symbol, tf)
    an = ds.analyzer
    equity = p.paper.equity_curve[-1]["equity"] if p.paper.equity_curve else p.cfg.INITIAL_CAPITAL
    latest = [e for e in ds.evaluations if e.bar == an.i and e.trigger == "ZONE"]
    history = [e for e in ds.evaluations if e.trigger == "ZONE"][-12:][::-1]
    out = {"symbol": symbol, "name": ds.instrument.name, "timeframe": tf, "price": an.bars[-1].close,
           "trend": an.structure.trend, "htf_trend": ds.htf.trend, "weights": CONFLUENCE_WEIGHTS,
           "min_confluence": p.cfg.MIN_CONFLUENCE_SCORE, "min_zone_score": p.cfg.MIN_ZONE_SCORE,
           "history": [{"eval_id": e.eval_id, "time": e.timestamp.isoformat(), "direction": e.direction,
                        "status": e.decision["status"], "score": e.decision["confluence"]["score"],
                        "reason": e.decision["reason"]} for e in history]}
    if latest:
        best = max(latest, key=lambda e: (e.decision["accepted"], e.decision["confluence"]["score"]))
        best.decision = decide(best, p.cfg)
        size = position_size(equity, p.cfg.RISK_PER_TRADE, best.entry_ref, best.stop or best.entry_ref,
                             best.lot_size, p.cfg.MAX_POSITION_PERCENT, equity) if best.stop else None
        out.update({"mode": "EVALUATED", "evaluation": to_jsonable(best.to_dict()), "why": why_lines(best),
                    "plan": _plan(p, best.direction, best.entry_ref, best.stop, best.targets, size, equity,
                                  best.zone, best.lot_size)})
        return out
    # WHY NO TRADE -- nothing interacted with a zone at the latest bar
    reasons = []
    projected = None
    for row in [r for r in p.scan["rows"] if r["symbol"] == symbol] if tf == "1D" else []:
        reasons.append({"direction": row["direction"], "status": row["status"], "reason": row["reason"]})
        if row.get("entry") and row.get("stop"):
            projected = row
    specs = (LONG_SPEC, SHORT_SPEC)
    checklist = []
    for spec in specs:
        zs = [z for z in an.active_zones(spec.zone_type) if distance_to_zone(z, an.bars[-1].close) > 0]
        nearest = min(zs, key=lambda z: distance_to_zone(z, an.bars[-1].close)) if zs else None
        checklist.append({
            "direction": spec.direction,
            "items": [
                {"ok": ds.htf.trend != spec.opposite_trend, "text": f"Higher-TF trend {ds.htf.trend}"},
                {"ok": an.structure.trend == spec.trend, "text": f"Confirmed structure {an.structure.trend} (need {spec.trend})"},
                {"ok": nearest is not None and distance_to_zone(nearest, an.bars[-1].close) <= 2 * (an.atr or 1),
                 "text": (f"Nearest {spec.zone_type.lower()} {nearest.proximal:.2f}-{nearest.distal:.2f}, "
                          f"{distance_to_zone(nearest, an.bars[-1].close) / (an.atr or 1):.1f} ATR away")
                 if nearest else f"No active {spec.zone_type.lower()} zone"},
                {"ok": False, "text": "Price has not traded into a qualified zone on the latest bar"},
            ]})
    out.update({"mode": "NO_TRIGGER", "reasons": reasons, "checklist": checklist})
    if projected:
        spec = LONG_SPEC if projected["direction"] == "LONG" else SHORT_SPEC
        stop, entry = projected["stop"], projected["entry"]
        risk = abs(entry - stop)
        r = lambda k: entry + spec.sign * risk * k  # noqa: E731
        struct = projected.get("t2")
        use_struct = struct is not None and risk > 0 and 1.5 <= (struct - entry) * spec.sign / risk <= 4.0
        t2 = struct if use_struct else r(p.cfg.TARGET_2_R)
        t3 = r(p.cfg.TARGET_3_R)
        if (t3 - t2) * spec.sign <= 0:  # keep T1 < T2 < T3 ordering
            t3 = t2 + spec.sign * 0.5 * risk
        tg = {"t1": r(p.cfg.TARGET_1_R), "t2": t2, "t3": t3,
              "methods": [f"{p.cfg.TARGET_1_R:g}R", "prior swing" if use_struct else f"{p.cfg.TARGET_2_R:g}R",
                          f"{p.cfg.TARGET_3_R:g}R" if t3 == r(p.cfg.TARGET_3_R) else "T2 + 0.5R"]}
        size = position_size(equity, p.cfg.RISK_PER_TRADE, entry, stop, ds.instrument.lot_size,
                             p.cfg.MAX_POSITION_PERCENT, equity)
        out["plan"] = _plan(p, projected["direction"], entry, stop, tg, size, equity, None, ds.instrument.lot_size)
        out["plan"]["projected"] = True
    return out


def _plan(p, direction, entry, stop, targets, size, equity, zone, lot) -> Dict:
    if stop is None:
        return {"valid": False, "reason": "No valid structural stop"}
    risk = abs(entry - stop)
    rr = lambda t: None if (t is None or not risk) else round(abs(t - entry) / risk, 2)  # noqa: E731
    q = size.quantity if size and size.valid else 0
    from ..risk.position_size import split_quantities
    legs = split_quantities(q, p.cfg.TARGET_1_EXIT_PERCENT, p.cfg.TARGET_2_EXIT_PERCENT, lot)
    return {
        "valid": True, "direction": direction, "capital": round(equity, 2), "risk_pct": p.cfg.RISK_PER_TRADE * 100,
        "risk_amount": round(equity * p.cfg.RISK_PER_TRADE, 2), "entry": round(entry, 2), "stop": round(stop, 2),
        "risk_per_share": round(risk, 2), "quantity": q, "lot_size": lot,
        "size_notes": size.reasons if size else [], "size_valid": bool(size and size.valid),
        "position_value": round(q * entry, 2),
        "t1": _r(targets.get("t1")), "t2": _r(targets.get("t2")), "t3": _r(targets.get("t3")),
        "rr": [rr(targets.get("t1")), rr(targets.get("t2")), rr(targets.get("t3"))],
        "methods": targets.get("methods", []),
        "allocation": {"t1": p.cfg.TARGET_1_EXIT_PERCENT, "t2": p.cfg.TARGET_2_EXIT_PERCENT,
                       "runner": p.cfg.RUNNER_PERCENT, "qty": legs},
        "zone": zone, "breakeven_mode": p.cfg.BREAKEVEN_MODE, "trail": f"Confirmed {'HL' if direction == 'LONG' else 'LH'} "
                                                                     f"- {p.cfg.TRAIL_ATR_BUFFER:g} ATR",
    }


# --------------------------------------------------------------------------- #
def trades_payload(p) -> Dict:
    closed = sorted(p.paper.trades, key=lambda t: t.exit_time, reverse=True)
    return {"open": [trade_row(t) for t in p.paper.open_trades],
            "closed": [trade_row(t) for t in closed[:30]],
            "account": account(p), "session_start": p.paper.start.isoformat() if p.paper.start else None,
            "orders": [o.to_dict() for o in p.paper_broker.orders()][-40:][::-1],
            "note": "Paper session = replay of the last sessions through the live decision engine and PaperBroker."}


def risk_payload(p) -> Dict:
    acc = account(p)
    prices = {t.symbol: t.last_price for t in p.paper.open_trades}
    exp = exposure_report(p.paper.open_trades, acc["equity"], prices)
    closes = {t.symbol: [b.close for b in p.datasets[t.symbol].bars] for t in p.paper.open_trades}
    corr = correlation_warnings(closes, p.cfg.CORRELATION_WARNING, p.cfg.CORRELATION_LOOKBACK) if len(closes) > 1 else []
    rejections = [r for r in p.paper.rejected if r["reason"] and r["reason"].startswith("RISK")][-20:][::-1]
    return {
        "account": acc, "exposure": exp, "correlation": corr,
        "limits": {"risk_per_trade": p.cfg.RISK_PER_TRADE, "max_positions": p.cfg.MAX_POSITIONS,
                   "max_position_pct": p.cfg.MAX_POSITION_PERCENT, "max_portfolio_risk": p.cfg.MAX_PORTFOLIO_RISK,
                   "max_sector_exposure": p.cfg.MAX_SECTOR_EXPOSURE, "max_positions_per_sector": p.cfg.MAX_POSITIONS_PER_SECTOR,
                   "max_daily_loss": p.cfg.MAX_DAILY_LOSS},
        "positions": [trade_row(t) for t in p.paper.open_trades],
        "risk_rejections": rejections,
        "equity": [{"t": x["time"][:10], "equity": x["equity"], "open_risk": x["open_risk"]} for x in p.paper.equity_curve],
    }


def backtest_payload(p, custom: bool = False) -> Dict:
    if custom and p.custom_backtest:
        res, rep = p.custom_backtest["result"], p.custom_backtest["report"]
        disabled = p.custom_backtest["disabled"]
    else:
        res, rep, disabled = p.backtest, p.backtest_report, []
    trades = sorted(res.trades, key=lambda t: t.entry_time, reverse=True)
    return {
        "label": res.label, "start": res.start.isoformat() if res.start else None,
        "end": res.end.isoformat() if res.end else None, "metrics": rep["metrics"], "charts": rep["charts"],
        "attribution": rep.get("attribution", []), "components": COMPONENTS,
        "enabled": [c for c in COMPONENTS if c not in disabled], "ladder": [l for l, _ in ABLATION_LADDER],
        "trades": [trade_row(t) for t in trades[:250]], "open_trades": [trade_row(t) for t in res.open_trades],
        "signals": len(res.signals), "rejected": len(res.rejected),
        "data_note": ("DEMO data is a synthetic random walk with regime drift: by construction it holds no "
                      "exploitable edge, so these results illustrate the machinery, not a strategy's merit."
                      if p.provider.is_demo else ""),
        "config": {k: res.config[k] for k in ("MIN_CONFLUENCE_SCORE", "MIN_ZONE_SCORE", "RISK_PER_TRADE", "ENTRY_MODE",
                                               "BREAKEVEN_MODE", "TRAIL_ACTIVATION", "MIN_RR")},
    }


def journal_payload(p, source: str = "backtest") -> Dict:
    trades = list(p.paper.trades) + list(p.paper.open_trades) if source == "paper" else list(p.backtest.trades)
    return {"source": source, "entries": build_journal(trades)}


def journal_detail(p, trade_id: str) -> Optional[Dict]:
    for t in list(p.backtest.trades) + list(p.paper.trades) + list(p.paper.open_trades):
        if t.trade_id == trade_id:
            from ..journal import journal_entry
            return {"entry": journal_entry(t), "chart": chart_snapshot(p.datasets[t.symbol], t)}
    return None


def rejected_payload(p, symbol: Optional[str] = None, reason: Optional[str] = None, limit: int = 300) -> Dict:
    rows = p.backtest.rejected
    counts: Dict[str, int] = {}
    for r in rows:
        key = (r["reason"] or "").split(":")[0]
        counts[key] = counts.get(key, 0) + 1
    if symbol:
        rows = [r for r in rows if r["symbol"] == symbol]
    if reason:
        rows = [r for r in rows if (r["reason"] or "").startswith(reason)]
    return {"total": len(p.backtest.rejected), "counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
            "rows": list(reversed(rows[-limit:]))}


def reports_payload(p) -> Dict:
    trades = p.backtest.trades
    by = lambda key: _group(trades, key)  # noqa: E731
    wf = p._walk_forward["summary"] if p._walk_forward else None
    return {"metrics": p.backtest_report["metrics"], "monthly": p.backtest_report["charts"]["monthly"],
            "by_symbol": by(lambda t: t.symbol), "by_sector": by(lambda t: t.sector),
            "by_direction": by(lambda t: t.direction), "by_exit": by(lambda t: t.exit_reason),
            "by_year": by(lambda t: str(t.entry_time.year)),
            "rejections": rejected_payload(p, limit=0)["counts"], "walk_forward": wf,
            "paper": p.paper_report["metrics"]}


def _group(trades, keyf) -> List[Dict]:
    groups: Dict[str, List] = {}
    for t in trades:
        groups.setdefault(keyf(t), []).append(t)
    out = []
    for k, ts in groups.items():
        rs = [t.r_multiple() or 0 for t in ts]
        out.append({"key": k, "trades": len(ts), "win_rate": round(sum(1 for r in rs if r > 0) / len(ts), 3),
                    "avg_r": round(sum(rs) / len(ts), 3), "net_pnl": round(sum(t.net_pnl for t in ts), 2)})
    return sorted(out, key=lambda r: -r["net_pnl"])


def mtf_payload(p, symbol: str) -> Dict:
    return p.mtf_context(symbol)


def notifications_payload(p) -> Dict:
    return {"items": list(p.bus.history)[::-1],
            "events": [{"type": k, "title": v, "enabled": k in p.notify_events} for k, v in EVENT_TYPES.items()],
            "channel": p.telegram.status()}


def health_payload(p) -> Dict:
    h = p.provider.health()
    db = {"status": "OK" if p.repo else "DOWN", "detail": str(p.settings.analytics_db_path) if p.repo else "not initialised"}
    if p.repo:
        try:
            db["detail"] += f" ({p.repo.count('trades')} trade rows, {p.repo.count('pivots')} pivots)"
        except Exception as exc:
            db = {"status": "ERROR", "detail": str(exc)}
    feeds = [
        ("Market Feed", h["market_feed"]), ("WebSocket", h["websocket"]), ("Database", db),
        ("Historical Sync", h["historical_sync"]), ("Futures OI", h["futures_oi"]), ("Options Feed", h["options_feed"]),
        ("Positioning Feed", h["positioning_feed"]),
        ("Broker Connection", {"status": "PAPER", "detail": "PaperBroker connected; live broker not configured"}),
        ("Last Candle", h["last_candle"]), ("Latency", h["latency"]), ("Data Gaps", h["data_gaps"]),
        ("Notifications", {"status": "ON" if p.telegram.enabled else "OFF", "detail": p.telegram.status()["detail"]}),
        ("Persistence", {"status": "OK" if p.persist_state == "done" else ("PENDING" if p.persist_state in ("running", "idle")
                                                                           else "ERROR"),
                         "detail": p.persist_state if p.repo else "database not initialised"}),
    ]
    return {"feeds": [{"name": n, **v} for n, v in feeds], "timings": p.timings, "status": p.status,
            "logs": recent_logs(700), "log_counts": log_counts(), "notification_errors": list(p.bus.errors),
            "stats": {"symbols": len(p.datasets), "bars": sum(len(ds.bars) for ds in p.datasets.values()),
                      "pivots": sum(len(ds.analyzer.pivots.pivots) for ds in p.datasets.values()),
                      "zones": sum(len(ds.analyzer.zones.zones) for ds in p.datasets.values()),
                      "evaluations": sum(len(ds.evaluations) for ds in p.datasets.values())}}


def settings_payload(p) -> Dict:
    cfg = p.cfg.to_dict()
    return {
        "editable": [{"key": k, "value": cfg[k], "help": v, "type": type(cfg[k]).__name__} for k, v in EDITABLE_PARAMETERS.items()],
        "config": cfg,
        "choices": {"ZIGZAG_METHOD": ["PERCENT", "ATR", "HYBRID"],
                    "UNAVAILABLE_FACTOR_POLICY": ["RENORMALIZE", "ZERO", "REJECT"],
                    "ENTRY_MODE": ["REVERSAL_CLOSE", "NEXT_OPEN", "BREAK_OF_REVERSAL", "LIMIT_IN_ZONE"],
                    "BREAKEVEN_MODE": ["KEEP", "ENTRY", "ENTRY_PLUS_COSTS", "ATR_ADJUSTED"],
                    "TRAIL_ACTIVATION": ["IMMEDIATE", "AFTER_T1", "AFTER_T2"],
                    "HTF_POLICY": ["ALIGNED", "NOT_OPPOSITE", "OFF"]},
        "weights": {"confluence": CONFLUENCE_WEIGHTS, "zone": ZONE_SCORE_WEIGHTS},
        "rules": {"candlestick": CANDLE_RULES, "pcr_bands_long": [[None if b == float("inf") else b, f, l] for b, f, l in PCR_BANDS_LONG],
                  "positioning_bands": list(p.cfg.POSITIONING_BANDS), "mtf_hierarchy": p.cfg.MTF_HIERARCHY},
        "modes_help": {"BACKTEST": "Simulation only", "PAPER": "Orders go to the PaperBroker",
                       "MANUAL": "Analysis only; nothing is sent", "SEMI_AUTO": "System proposes, you confirm",
                       "AUTO": "Broker execution after safeguards and validation"},
        "app": {"data_source": p.settings.DATA_SOURCE, "execution_mode": p.execution_mode,
                "live_trading_enabled": p.settings.LIVE_TRADING_ENABLED,
                "secrets": {"Kite API key": p.settings.KITE_API_KEY_ENV, "Kite access token": p.settings.KITE_ACCESS_TOKEN_ENV,
                            "Telegram bot token": p.settings.TELEGRAM_TOKEN_ENV, "Telegram chat id": p.settings.TELEGRAM_CHAT_ENV}},
    }


def walk_forward_payload(p, background: bool = True) -> Dict:
    return p.walk_forward(background=background)


def ablation_payload(p) -> Dict:
    return {"rows": p.ablation()}
