"""Put-call ratio engine (Section 18).  PCR is context, never a standalone signal.

Safety rules
* Overall PCR = sum(put OI) / sum(call OI); undefined when call OI is 0.
* ΔOI PCR = sum(put ΔOI) / sum(call ΔOI); undefined when call ΔOI <= 0
  (a negative denominator flips the ratio's meaning), and undefined on an
  expiry-rollover day because ΔOI resets with the new series.
"""
from __future__ import annotations

from typing import Dict, Optional

from ..config.scoring_config import pcr_fraction_long
from ..schemas import OptionChainSnapshot
from .options_chain import select_strikes


def compute_pcr(chain: Optional[OptionChainSnapshot], n_each_side: int = 10, min_oi: float = 0.0) -> Dict:
    if chain is None:
        return {"available": False, "reason": "No option chain for this instrument"}
    atm, strikes, skipped = select_strikes(chain, n_each_side, min_oi)
    if not strikes:
        return {"available": False, "reason": "No liquid strikes in the selected range", "atm": atm}
    call_oi = sum(s.call_oi for s in strikes)
    put_oi = sum(s.put_oi for s in strikes)
    call_d = sum(s.call_change_oi for s in strikes)
    put_d = sum(s.put_change_oi for s in strikes)
    pcr = put_oi / call_oi if call_oi > 0 else None
    d_reason = None
    if chain.expiry_rollover:
        d_pcr, d_reason = None, "Expiry rollover: ΔOI resets with the new series"
    elif call_d <= 0:
        d_pcr, d_reason = None, "Call ΔOI <= 0: ratio undefined"
    else:
        d_pcr = put_d / call_d
    return {
        "available": pcr is not None,
        "reason": None if pcr is not None else "Call OI is zero",
        "date": chain.trade_date.isoformat(), "expiry": chain.expiry.isoformat(),
        "underlying": round(chain.underlying, 2), "atm": atm,
        "strike_range": [strikes[0].strike, strikes[-1].strike], "strikes_used": len(strikes),
        "skipped_illiquid": skipped, "call_oi": round(call_oi), "put_oi": round(put_oi),
        "call_change_oi": round(call_d), "put_change_oi": round(put_d),
        "pcr": None if pcr is None else round(pcr, 3),
        "change_oi_pcr": None if d_pcr is None else round(d_pcr, 3), "change_oi_pcr_reason": d_reason,
        "expiry_rollover": chain.expiry_rollover, "source": chain.source_type,
    }


def pcr_fraction(direction: str, pcr_info: Optional[Dict]) -> Optional[float]:
    if not pcr_info or not pcr_info.get("available") or pcr_info.get("pcr") is None:
        return None
    frac, _ = pcr_fraction_long(pcr_info["pcr"])
    return frac if direction == "LONG" else 1.0 - frac
