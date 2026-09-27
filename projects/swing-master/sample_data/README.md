# Loading real data

This folder is the default `SM_DATA_DIR`. No market data is shipped. Put your own files here, or point `SM_DATA_DIR` elsewhere, then run with `SM_DATA_SOURCE=CSV`.

```text
universe.csv            symbol,name,sector,segment,lot_size,is_index,has_futures,has_options,strike_step
ohlcv/<SYMBOL>.csv      date,open,high,low,close,volume                 daily, ascending
intraday/<SYMBOL>.csv   timestamp,open,high,low,close,volume            5-minute bars, optional
futures_oi/<SYMBOL>.csv date,close,open_interest                        optional
vix.csv                 date,open,high,low,close                        optional
participant_oi.csv      date,participant,future_index_long,future_index_short   optional (NSE participant-wise OI)
```

Rules:

* Timestamps are IST and naive; the NSE session is 09:15–15:30.
* Rows with inconsistent OHLC, negative volume or non-increasing timestamps raise an error instead of being silently repaired. Calendar gaps longer than 4 days are reported on the Data Health screen.
* `participant` values: `Client` → Retail, `FII` / `DII` → Institutional, `Pro` → Commercial. These records are `DIRECT` and become usable 2 h after a conservative 20:00 IST publication time. The delay is configurable.
* A missing optional file makes that module report `UNAVAILABLE`. Nothing is inferred from OHLCV.
