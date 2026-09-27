"""Signal engine -- the ONE authoritative definition of every entry rule.

Two pure stages:

1. :func:`evaluate_bar` runs at the close of bar ``i`` (called immediately
   after ``SymbolAnalyzer.update``) and freezes everything it saw into a
   :class:`SetupEvaluation` -- factor fractions, zone snapshot, levels.
   It is triggered only when price interacts with a qualified area, so each
   evaluation is a genuine "setup moment" worth keeping (accepted or not).

2. :func:`decide` applies thresholds, gates, ablation switches and the
   unavailable-data policy to a frozen evaluation.  Backtest, walk-forward,
   scanner and paper trading all call this same function, so they cannot
   disagree about what a valid trade is.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

from ..derivatives.futures_oi import oi_fraction
from ..derivatives.pcr import pcr_fraction
from ..positioning import retail_fraction, smart_money_fraction
from ..price_action.candlesticks import best_pattern, detect_patterns
from ..risk.stop_loss import structural_stop
from ..risk.targets import compute_targets, reward_risk
from ..schemas import Bar, Pivot, RuleResult, Trend, Zone
from ..volume_profile.confluence import price_location, zone_profile_confluence
from ..zones.zone_lifecycle import price_interacts
from ..zones.zone_quality import score_zone, zone_components
from .analyzer import HTFTracker, SymbolAnalyzer
from .confluence import bos_fraction_setup, score_confluence, structure_fraction
from .long_setup import LONG_SPEC
from .short_setup import SHORT_SPEC, spec_for

from ..config.scoring_config import rr_fraction


@dataclass
class SetupEvaluation:
    eval_id: str
    symbol: str
    sector: str
    timeframe: str
    direction: str
    trigger: str  # ZONE | PIVOT
    bar: int
    timestamp: datetime
    close_time: datetime
    decision_time: datetime
    price: float
    atr: float
    trend: str
    htf_trend: str
    last_high_label: Optional[str]
    last_low_label: Optional[str]
    zone: Dict
    prior_tests: int
    zone_fractions: Dict[str, Optional[float]]
    factor_fractions: Dict[str, Optional[float]]
    sub_fractions: Dict[str, Optional[float]]
    factor_meta: Dict[str, Dict]
    pattern: Optional[Dict]
    patterns: List[Dict]
    vp: Optional[Dict]
    positioning: Dict
    oi: Optional[Dict]
    pcr: Optional[Dict]
    entry_mode: str
    entry_ref: float
    entry_trigger: Optional[float]
    stop: Optional[float]
    stop_note: str
    targets: Dict
    rr: Optional[float]
    last_pivot: Optional[Dict]
    last_event: Optional[Dict]
    lot_size: int
    decision: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        d = {k: getattr(self, k) for k in (
            "eval_id", "symbol", "sector", "timeframe", "direction", "trigger", "bar", "price", "atr", "trend",
            "htf_trend", "zone", "prior_tests", "pattern", "patterns", "vp", "positioning", "oi", "pcr",
            "entry_mode", "entry_ref", "entry_trigger", "stop", "stop_note", "targets", "rr", "last_pivot",
            "last_event", "lot_size", "decision", "factor_meta")}
        d["timestamp"] = self.timestamp.isoformat()
        d["decision_time"] = self.decision_time.isoformat()
        return d


# --------------------------------------------------------------------------- #
# Stage 1 -- evaluation
# --------------------------------------------------------------------------- #
def decision_time_for(bar: Bar, timeframe: str, cfg) -> datetime:
    """When the decision is actually taken.  EOD daily scans run after the
    evening derivatives publication; REVERSAL_CLOSE decides at the bell."""
    if timeframe in ("1D", "1W", "1M") and cfg.ENTRY_MODE != "REVERSAL_CLOSE":
        return bar.close_time + timedelta(minutes=cfg.EOD_DECISION_DELAY_MIN)
    return bar.close_time


def _pivot_zone(an: SymbolAnalyzer, spec, pivot: Pivot, atr: float) -> Zone:
    lo, hi = pivot.pivot_price - 0.25 * atr, pivot.pivot_price + 0.25 * atr
    prox, dist = (hi, lo) if spec.sign > 0 else (lo, hi)
    return Zone(zone_id=f"{an.symbol}-{an.timeframe}-P{pivot.seq}", symbol=an.symbol, timeframe=an.timeframe,
                zone_type=spec.zone_type, pattern="PIVOT", proximal=prox, distal=dist, origin_bar=pivot.pivot_bar,
                origin_timestamp=pivot.pivot_timestamp, creation_bar=pivot.confirmation_bar,
                creation_timestamp=pivot.confirmation_timestamp, base_bars=1, base_quality=0.0,
                departure_strength=pivot.reversal_atr or 0.0, atr_at_creation=atr,
                trend_at_creation=an.structure.trend)


def find_triggers(an: SymbolAnalyzer, spec, bar: Bar, atr: float, cfg) -> List[Tuple[str, Zone]]:
    buf = atr * cfg.ZONE_TOUCH_BUFFER_ATR
    out: List[Tuple[str, Zone]] = []
    zones = [z for z in an.active_zones(spec.zone_type) if price_interacts(z, bar, buf)]
    if zones:
        best = max(zones, key=lambda z: z.proximal * spec.sign)  # nearest to price
        out.append(("ZONE", best))
    pivot = an.pivots.last(an.i, spec.stop_pivot_type)
    if pivot is not None and pivot.confirmation_bar < an.i:
        pz = _pivot_zone(an, spec, pivot, atr)
        if price_interacts(pz, bar, 0.25 * atr):
            out.append(("PIVOT", pz))
    return out


def evaluate_bar(an: SymbolAnalyzer, htf: Optional[HTFTracker], derivs, positioning, instrument, cfg,
                 vp_cache: Optional[Dict] = None) -> List[SetupEvaluation]:
    i = an.i
    atr = an.atr
    if i < cfg.WARMUP_BARS or not atr:
        return []
    bar = an.bars[i]
    evaluations = []
    for spec in (LONG_SPEC, SHORT_SPEC):
        for trigger, zone in find_triggers(an, spec, bar, atr, cfg):
            evaluations.append(_evaluate(an, htf, derivs, positioning, instrument, cfg, spec, trigger, zone, vp_cache))
    return evaluations


def _evaluate(an, htf, derivs, positioning, instrument, cfg, spec, trigger, zone, vp_cache) -> SetupEvaluation:
    i, bar, atr = an.i, an.bars[an.i], an.atr
    dtime = decision_time_for(bar, an.timeframe, cfg)
    pivots = an.pivots.confirmed_as_of(i)
    htf_trend = htf.trend if htf is not None else Trend.UNDEFINED

    # ---- price action ----------------------------------------------------
    patterns = detect_patterns(an.bars, i, atr, cfg.PATTERN_MIN_RANGE_ATR)
    pat = best_pattern(patterns, spec.direction)
    candle_frac = pat.confidence if pat else 0.0

    # ---- volume profile --------------------------------------------------
    if vp_cache is not None and i in vp_cache:
        vp = vp_cache[i]
    else:
        vp = an.profile()
        if vp_cache is not None:
            vp_cache[i] = vp
    vpc = zone_profile_confluence(zone, vp, atr, cfg.VP_NEAR_ATR)

    # ---- entry / stop / targets -------------------------------------------
    tick = 0.05
    entry_trigger = None
    if cfg.ENTRY_MODE == "BREAK_OF_REVERSAL":
        entry_trigger = (bar.high + tick) if spec.sign > 0 else (bar.low - tick)
        entry_ref = entry_trigger
    elif cfg.ENTRY_MODE == "LIMIT_IN_ZONE":
        entry_trigger = zone.proximal
        entry_ref = entry_trigger
    else:
        entry_ref = bar.close
    stop, stop_note = structural_stop(spec, zone, pivots, atr, entry_ref, cfg.STOP_REFERENCE, cfg.STOP_ATR_BUFFER)
    htf_zones = htf.analyzer.active_zones() if htf is not None and htf.analyzer.bars else []
    if stop is not None:
        targets = compute_targets(spec, entry_ref, stop, pivots, an.active_zones(), vp, htf_zones, cfg)
        rr = reward_risk(entry_ref, stop, targets["t2"])
    else:
        targets, rr = {"t1": None, "t2": None, "t3": None, "methods": [], "notes": [stop_note], "valid": False}, None

    # ---- positioning & derivatives (as of decision time) -----------------
    snaps = positioning.snapshot(dtime)
    smart = smart_money_fraction(spec.direction, snaps["COMMERCIAL"], snaps["INSTITUTIONAL"])
    comm = smart_money_fraction(spec.direction, snaps["COMMERCIAL"], snaps["COMMERCIAL"])
    inst = smart_money_fraction(spec.direction, snaps["INSTITUTIONAL"], snaps["INSTITUTIONAL"])
    retail = retail_fraction(spec.direction, snaps["RETAIL"])
    oi_state = derivs.oi_state(dtime) if derivs is not None else None
    pcr_info = derivs.pcr(bar.timestamp.date(), dtime) if derivs is not None else None
    oi_f = oi_fraction(spec.direction, oi_state)
    pcr_f = pcr_fraction(spec.direction, pcr_info)
    oi_pcr = _mean([oi_f, pcr_f])

    # ---- structure --------------------------------------------------------
    trend = an.structure.trend
    s_frac = structure_fraction(spec, trend, an.structure.last_low_label, an.structure.last_high_label)
    bos_frac, bos_detail = bos_fraction_setup(spec, an.events.events, zone.origin_bar, i)
    htf_frac = None
    if htf_trend != Trend.UNDEFINED:
        htf_frac = 1.0 if htf_trend == spec.trend else (0.0 if htf_trend == spec.opposite_trend else 0.5)
    rr_frac = rr_fraction(rr) if rr is not None else 0.0

    # ---- zone score --------------------------------------------------------
    zfr = zone_components(zone, i, True, pivots, an.events.events, atr, htf_trend if htf_frac is not None else None,
                          vpc["poc_fraction"], vpc["score"], smart, candle_frac, rr_frac)
    if trigger == "PIVOT":
        zfr["freshness"] = 1.0
    prior = max(0, zone.touches_as_of(i) - 1) if trigger == "ZONE" else 0
    zone_score = score_zone(zfr, cfg.UNAVAILABLE_FACTOR_POLICY)

    fractions = {
        "structure": s_frac,
        "zone": zone_score["score"] / 100.0,
        "volume_profile": vpc["score"],
        "htf": htf_frac,
        "candlestick": candle_frac,
        "smart_money": smart,
        "retail": retail,
        "oi_pcr": oi_pcr,
        "bos": bos_frac,
        "risk_reward": rr_frac,
    }
    unavailable_src = "UNAVAILABLE"
    demo = "DEMO" if getattr(derivs, "provider", None) is not None and derivs.provider.is_demo else "PROXY"
    meta = {
        "structure": {"source": "COMPUTED", "detail": f"Trend {trend} (last high {an.structure.last_high_label}, "
                                                        f"last low {an.structure.last_low_label})"},
        "zone": {"source": "COMPUTED", "detail": f"{zone.pattern} {zone.zone_type.lower()} score "
                                                 f"{zone_score['score']:.0f}/100, prior tests {prior}"},
        "volume_profile": {"source": "COMPUTED",
                           "detail": "POC {}".format(vpc["levels"]["POC"]["relation"]) if vpc["available"] else "n/a"},
        "htf": {"source": "COMPUTED" if htf_frac is not None else unavailable_src,
                "detail": f"{an.timeframe}->{cfg.MTF_HIERARCHY.get(an.timeframe)} trend {htf_trend}"},
        "candlestick": {"source": "COMPUTED", "detail": f"{pat.pattern} ({pat.confidence:.2f})" if pat else "No reversal"},
        "smart_money": {"source": snaps["COMMERCIAL"].status if smart is not None else unavailable_src,
                        "detail": snaps["COMMERCIAL"].note or snaps["COMMERCIAL"].classification or ""},
        "retail": {"source": snaps["RETAIL"].status if retail is not None else unavailable_src,
                   "detail": snaps["RETAIL"].note or snaps["RETAIL"].classification or ""},
        "oi_pcr": {"source": demo if oi_pcr is not None else unavailable_src,
                   "detail": " / ".join(filter(None, [
                       f"OI {oi_state['state']}" if oi_state else "OI unavailable",
                       f"PCR {pcr_info['pcr']}" if pcr_info and pcr_info.get("pcr") is not None else "PCR unavailable"]))},
        "bos": {"source": "COMPUTED", "detail": bos_detail},
        "risk_reward": {"source": "COMPUTED", "detail": f"R:R to T2 {rr:.2f}" if rr else "Invalid risk"},
    }

    last_piv = an.pivots.last(i)
    last_ev = an.events.last_event(i)
    loc = price_location(bar.close, vp)
    ev = SetupEvaluation(
        eval_id=f"{an.symbol}-{an.timeframe}-{i}-{spec.direction[0]}-{trigger[0]}",
        symbol=an.symbol, sector=instrument.sector, timeframe=an.timeframe, direction=spec.direction,
        trigger=trigger, bar=i, timestamp=bar.timestamp, close_time=bar.close_time, decision_time=dtime,
        price=bar.close, atr=atr, trend=trend, htf_trend=htf_trend,
        last_high_label=an.structure.last_high_label, last_low_label=an.structure.last_low_label,
        zone={**zone.to_dict(as_of=i), "prior_tests": prior}, prior_tests=prior,
        zone_fractions=zfr, factor_fractions=fractions,
        sub_fractions={"commercial": comm, "institutional": inst, "oi": oi_f, "pcr": pcr_f},
        factor_meta=meta, pattern=pat.to_dict() if pat else None,
        patterns=[p.to_dict() for p in patterns],
        vp=None if vp is None else {"poc": round(vp.poc, 2), "vah": round(vp.vah, 2), "val": round(vp.val, 2),
                                    "hvn": [round(x, 2) for x in vp.hvn], "lvn": [round(x, 2) for x in vp.lvn],
                                    "location": loc, "confluence": vpc},
        positioning={k: v.to_dict() for k, v in snaps.items()},
        oi=oi_state, pcr=pcr_info, entry_mode=cfg.ENTRY_MODE, entry_ref=entry_ref, entry_trigger=entry_trigger,
        stop=stop, stop_note=stop_note, targets=targets, rr=rr,
        last_pivot=last_piv.to_dict() if last_piv else None,
        last_event=last_ev.to_dict() if last_ev else None,
        lot_size=instrument.lot_size,
    )
    ev.decision = decide(ev, cfg)
    return ev


def _mean(vals: Iterable[Optional[float]]) -> Optional[float]:
    xs = [v for v in vals if v is not None]
    return sum(xs) / len(xs) if xs else None


# --------------------------------------------------------------------------- #
# Stage 2 -- decision
# --------------------------------------------------------------------------- #
def effective_fractions(ev: SetupEvaluation, disabled: Iterable[str]) -> Dict[str, Optional[float]]:
    disabled = set(disabled)
    fr = dict(ev.factor_fractions)
    sub = ev.sub_fractions
    fr["smart_money"] = _mean([None if "commercial" in disabled else sub.get("commercial"),
                               None if "institutional" in disabled else sub.get("institutional")])
    fr["oi_pcr"] = _mean([None if "oi" in disabled else sub.get("oi"),
                          None if "pcr" in disabled else sub.get("pcr")])
    return fr


def _scores(ev: SetupEvaluation, policy: str, disabled: set, weight_disabled: set):
    """Zone + confluence scores do not depend on thresholds -> memoised per evaluation."""
    key = (policy, tuple(sorted(disabled)))
    cache = ev.__dict__.setdefault("_score_cache", {})
    if key not in cache:
        zone_score = score_zone(ev.zone_fractions, policy, weight_disabled)
        fractions = effective_fractions(ev, disabled)
        fractions["zone"] = zone_score["score"] / 100.0
        cache[key] = (zone_score, score_confluence(fractions, policy, weight_disabled))
    return cache[key]


def trigger_applicable(ev: SetupEvaluation, disabled: Iterable[str]) -> bool:
    return (ev.trigger == "ZONE") == ("zones" not in set(disabled))


def decide(ev: SetupEvaluation, cfg, disabled: Iterable[str] = ()) -> Dict:
    disabled = set(disabled)
    # smart_money/oi_pcr factors are owned by "commercial"/"oi" in the weight table;
    # only drop them entirely when every contributing source is disabled.
    weight_disabled = set(disabled)
    if not {"commercial", "institutional"} <= disabled:
        weight_disabled.discard("commercial")
    if not {"oi", "pcr"} <= disabled:
        weight_disabled.discard("oi")
    spec = spec_for(ev.direction)
    zone_score, conf = _scores(ev, cfg.UNAVAILABLE_FACTOR_POLICY, disabled, weight_disabled)

    rules: List[RuleResult] = []

    def rule(name, passed, detail, component="core", hard=True):
        if component != "core" and component in disabled:
            rules.append(RuleResult(name, None, "component disabled (ablation)", hard, component))
        else:
            rules.append(RuleResult(name, passed, detail, hard, component))

    applicable = trigger_applicable(ev, disabled)
    rule("Direction enabled", bool(getattr(cfg, spec.config_flag)), f"{spec.config_flag}={getattr(cfg, spec.config_flag)}")
    if cfg.HTF_POLICY == "OFF":
        rules.append(RuleResult("Higher-TF context", None, "HTF_POLICY=OFF", True, "structure"))
    else:
        ok = ev.htf_trend == spec.trend if cfg.HTF_POLICY == "ALIGNED" else ev.htf_trend != spec.opposite_trend
        rule("Higher-TF context", ok, f"HTF trend {ev.htf_trend} ({cfg.HTF_POLICY})", "structure")
    s_ok = ev.trend == spec.trend if cfg.STRUCTURE_POLICY == "TREND" else ev.trend != spec.opposite_trend
    rule("Market structure", s_ok, f"Confirmed trend {ev.trend}; need {spec.trend}", "structure")
    if ev.trigger == "ZONE":
        z_ok = ev.zone["status"] != "INVALIDATED" and ev.prior_tests <= cfg.ZONE_MAX_PRIOR_TESTS
        rule("Qualified zone", z_ok, f"{ev.zone['pattern']} {ev.zone['type']} status {ev.zone['status']}, "
                                     f"prior tests {ev.prior_tests} (max {cfg.ZONE_MAX_PRIOR_TESTS})", "zones")
        rule("Zone score", zone_score["score"] >= cfg.MIN_ZONE_SCORE,
             f"{zone_score['score']:.1f} vs min {cfg.MIN_ZONE_SCORE:g}", "zones")
    else:
        rule("Pullback to confirmed swing", True, f"Retest of confirmed swing at {ev.zone['proximal']:.2f}", "structure")
    pat_ok = ev.pattern is not None and ev.pattern["confidence"] >= cfg.MIN_PATTERN_CONFIDENCE
    rule("Reversal confirmed", pat_ok,
         f"{ev.pattern['pattern']} confidence {ev.pattern['confidence']:.2f}" if ev.pattern else "No reversal candle",
         "candlestick")
    rule("Stop & targets valid", ev.stop is not None and bool(ev.targets.get("valid")),
         ev.stop_note if ev.stop is None else "; ".join(ev.targets.get("notes") or ["ordered T1 < T2 < T3"]))
    rule("Reward : risk", ev.rr is not None and ev.rr >= cfg.MIN_RR,
         f"{ev.rr:.2f} vs min {cfg.MIN_RR:g}" if ev.rr else "undefined")
    coverage_ok = conf["coverage"] >= cfg.MIN_FACTOR_COVERAGE
    if cfg.UNAVAILABLE_FACTOR_POLICY == "REJECT" and conf["unavailable"]:
        coverage_ok = False
    rule("Data coverage", coverage_ok,
         f"{conf['coverage']:.0%} of weight available (min {cfg.MIN_FACTOR_COVERAGE:.0%}); "
         f"unavailable: {', '.join(conf['unavailable']) or 'none'}")
    rule("Confluence score", conf["score"] >= cfg.MIN_CONFLUENCE_SCORE,
         f"{conf['score']:.1f} vs min {cfg.MIN_CONFLUENCE_SCORE:g}")

    failed = [r for r in rules if r.passed is False and r.hard]
    accepted = applicable and not failed
    if not applicable:
        status, reason = "NOT_APPLICABLE", "Trigger type not used under current component set"
    elif accepted:
        status, reason = "CANDIDATE", None
    else:
        status, reason = "REJECTED", f"{failed[0].rule}: {failed[0].detail}"
    return {
        "accepted": accepted,
        "status": status,
        "reason": reason,
        "zone_score": zone_score,
        "confluence": conf,
        "rules": [r.to_dict() for r in rules],
        "min_confluence": cfg.MIN_CONFLUENCE_SCORE,
        "min_zone_score": cfg.MIN_ZONE_SCORE,
    }


def why_lines(ev: SetupEvaluation) -> List[Dict]:
    """Human readable 'WHY THIS TRADE / WHY NO TRADE' checklist (Section 36/53)."""
    d = ev.decision
    lines = []
    for r in d["rules"]:
        lines.append({"ok": r["passed"], "text": f"{r['rule']}: {r['detail']}", "status": r["status"]})
    for row in d["confluence"]["rows"]:
        if row["fraction"] is None:
            lines.append({"ok": None, "text": f"{row['name']}: data unavailable (excluded)", "status": "UNAVAILABLE"})
    return lines
