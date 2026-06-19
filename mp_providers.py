"""
MarketPulse AI v6.0  --  mp_providers.py
Pluggable price-data layer for the tracker.

Answers requirement B: works in TWO modes and degrades automatically.
  * intraday  -> 1-minute bars (precise highest/lowest, real time-to-target)
  * eod       -> daily bars    (coarse, used when intraday isn't available)

Provider is chosen by env var TRACKER_PROVIDER:
  * "yfinance" (default) -- free, gives 1m bars for the last ~7 days. No plan.
  * "polygon"            -- uses POLYGON_API_KEY; needs a minute-aggregate plan.

Every bar is normalised to: {"time": <utc datetime>, "o","h","l","c": float}.
On any failure the function returns ([], mode) so the tracker simply retries
the trade on its next cycle -- it never crashes the loop.
"""

import os
from datetime import datetime, timezone, timedelta

PROVIDER = os.environ.get("TRACKER_PROVIDER", "yfinance").lower()


# --------------------------------------------------------------------------- #
#  yfinance
# --------------------------------------------------------------------------- #
def _yf_bars(ticker, interval, period):
    import yfinance as yf
    df = yf.Ticker(ticker).history(period=period, interval=interval)
    if df is None or df.empty:
        return []
    bars = []
    for idx, r in df.iterrows():
        ts = idx.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        bars.append({
            "time": ts.astimezone(timezone.utc),
            "o": float(r["Open"]), "h": float(r["High"]),
            "l": float(r["Low"]),  "c": float(r["Close"]),
        })
    return bars


# --------------------------------------------------------------------------- #
#  Polygon (optional)
# --------------------------------------------------------------------------- #
def _polygon_bars(ticker, multiplier, timespan, since_dt):
    import requests
    key = os.environ.get("POLYGON_API_KEY")
    if not key:
        return []
    frm = since_dt.strftime("%Y-%m-%d")
    to = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    url = (f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/"
           f"{multiplier}/{timespan}/{frm}/{to}")
    resp = requests.get(url, params={"adjusted": "true", "sort": "asc",
                                     "limit": 50000, "apiKey": key}, timeout=15)
    if resp.status_code != 200:
        return []
    out = []
    for b in resp.json().get("results", []):
        out.append({
            "time": datetime.fromtimestamp(b["t"] / 1000, tz=timezone.utc),
            "o": float(b["o"]), "h": float(b["h"]),
            "l": float(b["l"]), "c": float(b["c"]),
        })
    return out


# --------------------------------------------------------------------------- #
#  Public API
# --------------------------------------------------------------------------- #
def _intraday(ticker, since_dt):
    if PROVIDER == "polygon":
        return _polygon_bars(ticker, 1, "minute", since_dt)
    return _yf_bars(ticker, "1m", "5d")


def _eod(ticker, since_dt):
    if PROVIDER == "polygon":
        return _polygon_bars(ticker, 1, "day", since_dt)
    return _yf_bars(ticker, "1d", "1mo")


def get_bars(ticker, since_dt, mode="auto"):
    """
    Return (bars_at_or_after_since, mode_used).
    mode: "auto" | "intraday" | "eod".  "auto" tries intraday then falls to eod.
    """
    try:
        if mode in ("auto", "intraday"):
            bars = _intraday(ticker, since_dt)
            bars = [b for b in bars if b["time"] >= since_dt]
            if bars or mode == "intraday":
                return bars, "intraday"
        bars = _eod(ticker, since_dt)
        # for EOD, keep the day of entry onward
        cutoff = since_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        bars = [b for b in bars if b["time"] >= cutoff]
        return bars, "eod"
    except Exception as e:
        print(f"[mp_providers] {ticker} fetch failed: {e}")
        return [], mode
