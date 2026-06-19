"""
MarketPulse AI v6.0  --  mp_probability.py
Probability engine + Telegram enrichment.

Given a NEW signal, find the most specific historical cohort of RESOLVED
trades that still has at least PROB_MIN_SAMPLE members, and report its
target-hit rate:

    Probability of success: 82%
    Based on 173 resolved ORB Breakdown SHORT trades

Cohort cascade (most -> least specific), first one with enough sample wins:
    1. same signal + setup + score>=band + confidence
    2. same signal + setup + score>=band
    3. same signal + setup

telegram_block(data) returns "" until enough data exists, so early on your
message is byte-for-byte what it is today; the edge block appears automatically
once the sample threshold is crossed.
"""

import os
import mp_db

MIN_SAMPLE = int(os.environ.get("PROB_MIN_SAMPLE", "20"))
RESOLVED = "('TARGET_HIT','INVALIDATED','EXPIRED')"
BANDS = [90, 80, 70, 60, 0]


def _band_of(score):
    if score is None:
        return 0
    for b in BANDS:
        if score >= b:
            return b
    return 0


def _cohort(where, params):
    sql = f"""
        SELECT
            SUM(CASE WHEN status='TARGET_HIT' THEN 1 ELSE 0 END) AS wins,
            COUNT(*) AS n,
            ROUND(AVG(max_favorable_pct), 2) AS avg_gain,
            ROUND(AVG(max_drawdown_pct), 2)  AS avg_dd,
            ROUND(AVG(trade_duration_min), 0) AS avg_hold
        FROM trades
        WHERE status IN {RESOLVED} {where}
    """
    return mp_db.query(sql, params)[0]


def probability(data):
    """Return a dict describing the best cohort, or None if no cohort qualifies."""
    side = str(data.get("signal", "")).upper()
    setup = data.get("setup")
    try:
        score = int(round(float(data.get("buyScore" if side == "BUY" else "shortScore"))))
    except (TypeError, ValueError):
        score = None
    conf = data.get("confidence")
    band = _band_of(score)

    attempts = [
        (" AND signal=? AND setup=? AND active_score>=? AND confidence=?",
         (side, setup, band, conf),
         f"{setup} {side} trades (score {band}+, {conf} confidence)"),
        (" AND signal=? AND setup=? AND active_score>=?",
         (side, setup, band),
         f"{setup} {side} trades (score {band}+)"),
        (" AND signal=? AND setup=?",
         (side, setup),
         f"{setup} {side} trades"),
    ]

    for where, params, basis in attempts:
        r = _cohort(where, params)
        n = r["n"] or 0
        if n >= MIN_SAMPLE:
            return {
                "probability": round(100.0 * (r["wins"] or 0) / n),
                "sample": n,
                "basis": basis,
                "avg_gain": r["avg_gain"],
                "avg_dd": r["avg_dd"],
                "avg_hold": int(r["avg_hold"]) if r["avg_hold"] is not None else None,
            }
    return None


def telegram_block(data):
    """A ready-to-append Telegram string, or '' if sample is too small."""
    p = probability(data)
    if not p:
        return ""
    lines = [
        "",
        "📈 Historical Edge",
        f"Probability of success: {p['probability']}%",
        f"Based on {p['sample']} resolved {p['basis']}",
    ]
    extras = []
    if p["avg_gain"] is not None:
        extras.append(f"Avg gain: +{p['avg_gain']}%")
    if p["avg_dd"] is not None:
        extras.append(f"Avg drawdown: -{p['avg_dd']}%")
    if p["avg_hold"] is not None:
        extras.append(f"Avg hold: {p['avg_hold']}m")
    if extras:
        lines.append(" | ".join(extras))
    return "\n" + "\n".join(lines)
