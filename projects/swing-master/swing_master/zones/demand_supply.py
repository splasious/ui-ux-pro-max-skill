"""Demand / supply zone detection (Section 9).

Pattern: LEG-IN -> BASE (1..N small-bodied candles) -> LEG-OUT (strong candle).
Detection runs at the close of the leg-out bar, so the zone's
``creation_bar`` is that bar -- zones are never created retrospectively and
cannot be traded before they exist.

    leg-in up   + leg-out up   = RBR (demand)
    leg-in down + leg-out up   = DBR (demand)
    leg-in up   + leg-out down = RBD (supply)
    leg-in down + leg-out down = DBD (supply)

Demand: proximal = highest base body, distal = lowest low of base + leg-out.
Supply: proximal = lowest base body,  distal = highest high of base + leg-out.
"""
from __future__ import annotations

from typing import List, Optional

from ..schemas import Bar, Zone
from .zone_lifecycle import update_zone


def body_ratio(bar: Bar) -> float:
    rng = bar.high - bar.low
    return abs(bar.close - bar.open) / rng if rng > 0 else 0.0


class ZoneEngine:
    def __init__(self, symbol: str, timeframe: str, cfg):
        self.symbol = symbol
        self.timeframe = timeframe
        self.cfg = cfg
        self.zones: List[Zone] = []
        self._active: List[Zone] = []

    # ------------------------------------------------------------------ #
    def update(self, i: int, bars: List[Bar], atr: Optional[float], trend: str) -> Optional[Zone]:
        bar = bars[i]
        buffer = (atr or 0.0) * self.cfg.ZONE_TOUCH_BUFFER_ATR
        for z in self._active:
            update_zone(z, i, bar, buffer)
        self._active = [z for z in self._active if z.invalidation_bar is None]
        zone = self._detect(i, bars, atr, trend)
        if zone is not None:
            self.zones.append(zone)
            self._active.append(zone)
            self._trim()
        return zone

    def active(self) -> List[Zone]:
        return list(self._active)

    def _trim(self) -> None:
        cap = self.cfg.ZONE_MAX_ACTIVE_PER_SIDE
        for side in ("DEMAND", "SUPPLY"):
            same = [z for z in self._active if z.zone_type == side]
            if len(same) > cap:
                drop = set(id(z) for z in same[: len(same) - cap])
                self._active = [z for z in self._active if id(z) not in drop]

    # ------------------------------------------------------------------ #
    def _detect(self, i: int, bars: List[Bar], atr: Optional[float], trend: str) -> Optional[Zone]:
        cfg = self.cfg
        if atr is None or atr <= 0 or i < 3:
            return None
        out = bars[i]
        out_range = out.high - out.low
        if body_ratio(out) < cfg.ZONE_LEG_MIN_BODY_RATIO or out_range < cfg.ZONE_LEG_MIN_RANGE_ATR * atr:
            return None
        out_up = out.close > out.open
        # the candle immediately before the leg-out must be a base candle
        if body_ratio(bars[i - 1]) > cfg.ZONE_BASE_MAX_BODY_RATIO:
            return None
        base_start = i - 1
        while (base_start - 1 >= 1 and i - base_start < cfg.ZONE_BASE_MAX_BARS
               and body_ratio(bars[base_start - 1]) <= cfg.ZONE_BASE_MAX_BODY_RATIO):
            base_start -= 1
        base = bars[base_start:i]
        leg_in = bars[base_start - 1]
        if body_ratio(leg_in) < cfg.ZONE_LEGIN_MIN_BODY_RATIO:
            return None
        in_up = leg_in.close > leg_in.open

        base_high = max(b.high for b in base)
        base_low = min(b.low for b in base)
        if (base_high - base_low) > cfg.ZONE_BASE_MAX_RANGE_ATR * atr:
            return None

        if out_up:
            proximal = max(max(b.open, b.close) for b in base)
            distal = min(base_low, out.low)
            departure = (out.close - base_high) / atr
            zone_type = "DEMAND"
            pattern = "RBR" if in_up else "DBR"
        else:
            proximal = min(min(b.open, b.close) for b in base)
            distal = max(base_high, out.high)
            departure = (base_low - out.close) / atr
            zone_type = "SUPPLY"
            pattern = "RBD" if in_up else "DBD"
        if departure < cfg.ZONE_MIN_DEPARTURE_ATR or proximal == distal:
            return None

        avg_body = sum(body_ratio(b) for b in base) / len(base)
        tightness = (base_high - base_low) / atr
        quality = 0.6 * (1.0 - avg_body) + 0.4 * max(0.0, min(1.0, 1.0 - (tightness - 0.5) / 1.5))
        return Zone(
            zone_id=f"{self.symbol}-{self.timeframe}-{zone_type[0]}{i}",
            symbol=self.symbol,
            timeframe=self.timeframe,
            zone_type=zone_type,
            pattern=pattern,
            proximal=proximal,
            distal=distal,
            origin_bar=base_start,
            origin_timestamp=base[0].timestamp,
            creation_bar=i,
            creation_timestamp=out.close_time,
            base_bars=len(base),
            base_quality=max(0.0, min(1.0, quality)),
            departure_strength=departure,
            atr_at_creation=atr,
            trend_at_creation=trend,
            invalidation_mode=cfg.ZONE_INVALIDATION_MODE,
        )
