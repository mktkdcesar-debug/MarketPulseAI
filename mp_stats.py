"""
MarketPulse AI v6.0  --  mp_stats.py
Statistics engine. Pure SQL aggregates over RESOLVED trades.

A trade is RESOLVED when status is TARGET_HIT, INVALIDATED or EXPIRED.
A WIN is TARGET_HIT. (EXPIRED counts as a non-win -- it never reached target.)
Win rate = wins / resolved.

summary() returns a JSON-friendly dict for the /stats/v6 endpoint.
"""

import mp_db

RESOLVED = "('TARGET_HIT','INVALIDATED','EXPIRED')"


def _rate(rows):
    out = []
    for r in rows:
        n = r["resolved"] or 0
        wins = r["wins"] or 0
        out.append({
            "key": r["k"],
            "resolved": n,
            "wins": wins,
            "win_rate": round(100.0 * wins / n, 1) if n else None,
        })
    return out


def _grouped(expr, having_min=1):
    sql = f"""
        SELECT {expr} AS k,
               SUM(CASE WHEN status='TARGET_HIT' THEN 1 ELSE 0 END) AS wins,
               COUNT(*) AS resolved
        FROM trades
        WHERE status IN {RESOLVED} AND {expr} IS NOT NULL
        GROUP BY k
        HAVING resolved >= ?
        ORDER BY resolved DESC
    """
    return _rate(mp_db.query(sql, (having_min,)))


def _score_band_breakdown():
    bands = [(90, "90+"), (80, "80+"), (70, "70+"), (60, "60+")]
    out = []
    for low, label in bands:
        r = mp_db.query(f"""
            SELECT SUM(CASE WHEN status='TARGET_HIT' THEN 1 ELSE 0 END) AS wins,
                   COUNT(*) AS resolved
            FROM trades
            WHERE status IN {RESOLVED} AND active_score >= ?
        """, (low,))[0]
        n = r["resolved"] or 0
        out.append({
            "band": label, "resolved": n, "wins": r["wins"] or 0,
            "win_rate": round(100.0 * (r["wins"] or 0) / n, 1) if n else None,
        })
    return out


def summary():
    totals = mp_db.query(f"""
        SELECT
            COUNT(*) AS resolved,
            SUM(CASE WHEN status='TARGET_HIT'  THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN status='INVALIDATED' THEN 1 ELSE 0 END) AS losses,
            SUM(CASE WHEN status='EXPIRED'     THEN 1 ELSE 0 END) AS expired,
            ROUND(AVG(max_favorable_pct), 2) AS avg_favorable_pct,
            ROUND(AVG(max_drawdown_pct), 2)  AS avg_drawdown_pct,
            ROUND(MAX(max_drawdown_pct), 2)  AS worst_drawdown_pct,
            ROUND(AVG(trade_duration_min), 1) AS avg_hold_min
        FROM trades WHERE status IN {RESOLVED}
    """)[0]
    open_n = mp_db.query("SELECT COUNT(*) AS n FROM trades WHERE status='OPEN'")[0]["n"]
    n = totals["resolved"] or 0

    return {
        "version": "MarketPulse AI v6.0",
        "open_trades": open_n,
        "resolved_trades": n,
        "overall_win_rate": round(100.0 * (totals["wins"] or 0) / n, 1) if n else None,
        "wins": totals["wins"] or 0,
        "losses": totals["losses"] or 0,
        "expired": totals["expired"] or 0,
        "avg_gain_pct": totals["avg_favorable_pct"],
        "avg_drawdown_pct": totals["avg_drawdown_pct"],
        "worst_drawdown_pct": totals["worst_drawdown_pct"],
        "avg_hold_min": totals["avg_hold_min"],
        "by_side": _grouped("signal"),
        "by_setup": _grouped("setup"),
        "by_ticker": _grouped("ticker"),
        "by_confidence": _grouped("confidence"),
        "by_score_band": _score_band_breakdown(),
        # bar_time looks like 'YYYY-MM-DD HH:MM:SS' (exchange tz) -> slice hour
        "by_hour": _grouped("substr(bar_time, 12, 2)"),
        "by_weekday": _grouped(
            "CASE CAST(strftime('%w', substr(bar_time,1,10)) AS INTEGER) "
            "WHEN 0 THEN 'Sun' WHEN 1 THEN 'Mon' WHEN 2 THEN 'Tue' "
            "WHEN 3 THEN 'Wed' WHEN 4 THEN 'Thu' WHEN 5 THEN 'Fri' "
            "WHEN 6 THEN 'Sat' END"),
    }
