"""Setup scanner (Section 28).

Funnel:  NSE UNIVERSE -> HTF STRUCTURE -> VALID ZONES -> VOLUME/POC -> POSITIONING
         -> CANDLE CONFIRMATION -> R:R -> FINAL CANDIDATES

The scanner reads the latest bar of each ``SymbolDataset`` and re-uses the
signal engine's own evaluation and ``decide()``; it adds no rules of its own
beyond the WATCH proximity used to rank setups that have not triggered yet.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..risk.stop_loss import structural_stop
from ..risk.targets import reward_risk
from ..schemas import ScanStatus, Trend
from ..strategy.long_setup import LONG_SPEC
from ..strategy.short_setup import SHORT_SPEC
from ..strategy.signal_engine import decide
from ..volume_profile.confluence import zone_profile_confluence
from ..zones.zone_lifecycle import distance_to_zone
from ..zones.zone_quality import score_zone, zone_components
from ..config.scoring_config import rr_fraction

WATCH_DISTANCE_ATR = 2.0
SOFT_RULES = {"Reversal confirmed", "Confluence score", "Zone score"}
STATUS_ORDER = {ScanStatus.READY: 0, ScanStatus.ACTIVE: 1, ScanStatus.WAIT: 2, ScanStatus.WATCH: 3,
                ScanStatus.REJECTED: 4}


def _fmt_zone(z: Dict) -> str:
    return f"{z['pattern']} {z['proximal']:.2f}-{z['distal']:.2f}"


def _base_row(ds, spec) -> Dict:
    an = ds.analyzer
    bar, prev = an.bars[-1], an.bars[-2] if len(an.bars) > 1 else an.bars[-1]
    last_p = an.pivots.last(an.i)
    last_ev = an.events.last_event(an.i)
    oi = ds.derivs.oi_state(bar.close_time.replace(hour=23, minute=59)) if ds.derivs else None
    pcr = ds.derivs.pcr(bar.timestamp.date(), bar.close_time.replace(hour=23, minute=59)) if ds.derivs else None
    return {
        "symbol": ds.symbol, "name": ds.instrument.name, "sector": ds.instrument.sector,
        "price": round(bar.close, 2), "change_pct": round(100 * (bar.close / prev.close - 1), 2),
        "timeframe": ds.timeframe, "direction": spec.direction, "structure": an.structure.trend,
        "htf_structure": ds.htf.trend,
        "last_pivot": None if last_p is None else {"label": last_p.label or last_p.pivot_type,
                                                   "price": round(last_p.pivot_price, 2),
                                                   "time": last_p.pivot_timestamp.date().isoformat(),
                                                   "confirmed": last_p.confirmation_timestamp.date().isoformat()},
        "structure_event": None if last_ev is None else f"{last_ev.direction.title()} {last_ev.event_type}",
        "positioning": "UNAVAILABLE",
        "oi_state": oi["state"] if oi else "UNAVAILABLE",
        "pcr": pcr.get("pcr") if pcr else None,
        "atr": round(an.atr or 0, 2),
    }


def _row_from_eval(ds, ev, cfg, status: str, reason: Optional[str]) -> Dict:
    spec = LONG_SPEC if ev.direction == "LONG" else SHORT_SPEC
    row = _base_row(ds, spec)
    d = ev.decision
    row.update({
        "zone": _fmt_zone(ev.zone), "zone_type": ev.zone["type"], "freshness": ev.zone["status"],
        "zone_score": d["zone_score"]["score"],
        "poc": ev.vp["poc"] if ev.vp else None,
        "poc_relation": ev.vp["confluence"]["levels"]["POC"]["relation"] if ev.vp and ev.vp["confluence"]["available"] else None,
        "pattern": ev.pattern["pattern"] if ev.pattern else None,
        "rr": None if ev.rr is None else round(ev.rr, 2),
        "confluence": d["confluence"]["score"], "coverage": d["confluence"]["coverage"],
        "status": status, "reason": reason, "eval_id": ev.eval_id,
        "distance_atr": 0.0,
        "entry": round(ev.entry_ref, 2), "stop": None if ev.stop is None else round(ev.stop, 2),
        "t1": ev.targets.get("t1") and round(ev.targets["t1"], 2),
        "t2": ev.targets.get("t2") and round(ev.targets["t2"], 2),
        "t3": ev.targets.get("t3") and round(ev.targets["t3"], 2),
        "rules": d["rules"],
    })
    return row


def _watch_row(ds, spec, cfg) -> Optional[Dict]:
    an = ds.analyzer
    atr = an.atr
    if not atr:
        return None
    price = an.bars[-1].close
    zones = [z for z in an.active_zones(spec.zone_type) if z.touches_as_of(an.i) <= cfg.ZONE_MAX_PRIOR_TESTS]
    zones = [z for z in zones if distance_to_zone(z, price) > 0]
    row = _base_row(ds, spec)
    if not zones:
        row.update({"status": ScanStatus.REJECTED, "reason": f"No qualified {spec.zone_type.lower()} zone",
                    "zone": None, "freshness": None, "zone_score": None, "confluence": None, "rr": None,
                    "pattern": None, "poc": None, "poc_relation": None, "distance_atr": None, "zone_type": spec.zone_type})
        return row
    z = min(zones, key=lambda zz: distance_to_zone(zz, price))
    dist_atr = distance_to_zone(z, price) / atr
    vp = an.profile()
    vpc = zone_profile_confluence(z, vp, atr, cfg.VP_NEAR_ATR)
    stop, _ = structural_stop(spec, z, an.pivots.confirmed_as_of(an.i), atr, z.proximal, cfg.STOP_REFERENCE,
                              cfg.STOP_ATR_BUFFER)
    target = None
    for p in reversed(an.pivots.confirmed_as_of(an.i)):
        if p.pivot_type == spec.target_pivot_type and spec.better(p.pivot_price, z.proximal):
            target = p.pivot_price
            break
    rr = reward_risk(z.proximal, stop, target) if stop is not None and target is not None else None
    fr = zone_components(z, an.i, False, an.pivots.confirmed_as_of(an.i), an.events.events, atr,
                         ds.htf.trend if ds.htf.trend != Trend.UNDEFINED else None, vpc["poc_fraction"], vpc["score"],
                         None, None, rr_fraction(rr) if rr else None)
    zs = score_zone(fr, cfg.UNAVAILABLE_FACTOR_POLICY)
    structure_ok = an.structure.trend == spec.trend and ds.htf.trend != spec.opposite_trend
    if structure_ok and dist_atr <= WATCH_DISTANCE_ATR and zs["score"] >= cfg.MIN_ZONE_SCORE - 10:
        status, reason = ScanStatus.WATCH, f"Approaching {z.pattern} {z.zone_type.lower()} ({dist_atr:.1f} ATR away)"
    elif not structure_ok:
        status, reason = ScanStatus.REJECTED, f"Structure {an.structure.trend} / HTF {ds.htf.trend} not aligned for {spec.direction}"
    else:
        status, reason = ScanStatus.REJECTED, f"Nearest zone {dist_atr:.1f} ATR away (watch <= {WATCH_DISTANCE_ATR:g})"
    row.update({
        "zone": _fmt_zone(z.to_dict(an.i)), "zone_type": z.zone_type, "freshness": z.status_as_of(an.i),
        "zone_score": zs["score"], "poc": round(vp.poc, 2) if vp else None,
        "poc_relation": vpc["levels"]["POC"]["relation"] if vpc["available"] else None,
        "pattern": None, "rr": None if rr is None else round(rr, 2), "confluence": None,
        "status": status, "reason": reason, "distance_atr": round(dist_atr, 2),
        "entry": round(z.proximal, 2), "stop": None if stop is None else round(stop, 2),
        "t2": None if target is None else round(target, 2),
    })
    return row


def scan(datasets: Dict, cfg, active_positions: List = ()) -> Dict:
    active = {p.symbol: p for p in active_positions}
    rows: List[Dict] = []
    funnel = {"universe": 0, "htf_structure": 0, "valid_zones": 0, "volume_poc": 0, "positioning": 0,
              "candle": 0, "rr": 0, "final": 0}
    for ds in datasets.values():
        if not ds.instrument.tradable:
            continue
        funnel["universe"] += 1
        an = ds.analyzer
        latest = [e for e in ds.evaluations if e.bar == an.i and e.trigger == "ZONE"]
        candidates = []
        for spec in (LONG_SPEC, SHORT_SPEC):
            ev = next((e for e in latest if e.direction == spec.direction), None)
            if ds.symbol in active and active[ds.symbol].direction == spec.direction:
                row = _base_row(ds, spec)
                t = active[ds.symbol]
                row.update({"status": ScanStatus.ACTIVE, "reason": f"Open {t.direction} since {t.entry_time.date()}",
                            "zone": None, "freshness": None, "zone_score": t.snapshot.get("zone_score"),
                            "confluence": t.snapshot.get("confluence"), "rr": t.snapshot.get("rr"),
                            "pattern": t.snapshot.get("candlestick"), "poc": t.snapshot.get("poc"),
                            "poc_relation": t.snapshot.get("poc_relation"), "distance_atr": None,
                            "zone_type": spec.zone_type, "trade_id": t.trade_id})
                candidates.append(row)
                continue
            if ev is not None:
                d = decide(ev, cfg)
                ev.decision = d
                if d["accepted"]:
                    candidates.append(_row_from_eval(ds, ev, cfg, ScanStatus.READY, None))
                else:
                    failed = {r["rule"] for r in d["rules"] if r["passed"] is False}
                    soft = failed <= SOFT_RULES and (d["confluence"]["score"] >= cfg.MIN_CONFLUENCE_SCORE - 10)
                    candidates.append(_row_from_eval(ds, ev, cfg, ScanStatus.WAIT if soft else ScanStatus.REJECTED,
                                                     d["reason"]))
            else:
                row = _watch_row(ds, spec, cfg)
                if row is not None:
                    candidates.append(row)
        if not candidates:
            continue
        candidates.sort(key=lambda r: (STATUS_ORDER[r["status"]], -(r.get("confluence") or r.get("zone_score") or 0),
                                       0 if r["structure"] == (LONG_SPEC.trend if r["direction"] == "LONG" else SHORT_SPEC.trend) else 1))
        best = candidates[0]
        rows.append(best)
        # funnel on the best row
        if best["structure"] in (Trend.BULLISH, Trend.BEARISH) and best["htf_structure"] != (
                Trend.BEARISH if best["direction"] == "LONG" else Trend.BULLISH):
            funnel["htf_structure"] += 1
            if best.get("zone"):
                funnel["valid_zones"] += 1
                if best.get("poc_relation") in ("INSIDE", "NEAR"):
                    funnel["volume_poc"] += 1
                    funnel["positioning"] += 1  # positioning UNAVAILABLE -> passed through, not scored
                    if best.get("pattern"):
                        funnel["candle"] += 1
                        if best.get("rr") and best["rr"] >= cfg.MIN_RR:
                            funnel["rr"] += 1
        if best["status"] == ScanStatus.READY:
            funnel["final"] += 1
    rows.sort(key=lambda r: (STATUS_ORDER[r["status"]], -(r.get("confluence") or r.get("zone_score") or 0)))
    counts: Dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"rows": rows, "funnel": funnel, "counts": counts}
