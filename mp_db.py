"""
MarketPulse AI v6.0  --  mp_db.py
Persistent SQLite layer for the statistical-intelligence engine.

Owns ONE new table, `trades`, written the instant a signal arrives and then
filled in over time by mp_tracker. It lives in the SAME database file as your
existing `alerts` table, but on the persistent disk (DATA_DIR) so nothing is
lost on a Render redeploy.

Nothing here touches your existing OpenAI / news / Telegram flow.
"""

import os
import json
import sqlite3
from datetime import datetime, timezone

# --- Persistent location ----------------------------------------------------
# DATA_DIR is the Render persistent-disk mount path (e.g. /var/data).
# Falls back to "." for local runs so you can test without a disk.
DATA_DIR = os.environ.get("DATA_DIR", ".")
DB_NAME = os.environ.get("MP_DB_NAME", "marketpulse_ai_v5.db")
DB_PATH = os.path.join(DATA_DIR, DB_NAME)

# Ensure the persistent directory exists the moment this module is imported,
# so the existing app's init_db() can open the file no matter which runs first.
if DATA_DIR not in (".", ""):
    os.makedirs(DATA_DIR, exist_ok=True)

# Column order is defined ONCE and reused for insert, so it can never drift.
SIGNAL_COLS = [
    "created_at", "bar_time", "ticker", "signal", "setup",
    "entry_price", "target_price", "invalidation_price",
    "active_score", "buy_score", "short_score", "confidence",
    "daily_trend", "hour_trend", "fifteen_trend", "direction",
    "timeframe", "news_risk", "event_risk",
]


def _conn():
    # timeout + WAL let the webhook threads and the tracker thread share the
    # file without "database is locked" errors at this volume.
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _f(v):
    """Parse to float, tolerating 'N/A', '', None, formatted strings."""
    try:
        if v is None:
            return None
        s = str(v).strip().replace(",", "")
        if s.lower() in ("", "n/a", "na", "nan", "none", "null"):
            return None
        return float(s)
    except Exception:
        return None


def _i(v):
    f = _f(v)
    return int(round(f)) if f is not None else None


def init_db():
    if DATA_DIR not in (".", ""):
        os.makedirs(DATA_DIR, exist_ok=True)
    conn = _conn()
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,            -- UTC ISO, moment webhook received (tracking anchor)
            bar_time TEXT,              -- scanner bar time (exchange tz) from payload "time"
            ticker TEXT,
            signal TEXT,                -- BUY / SHORT
            setup TEXT,
            entry_price REAL,
            target_price REAL,
            invalidation_price REAL,
            active_score INTEGER,       -- buy_score if BUY else short_score
            buy_score INTEGER,
            short_score INTEGER,
            confidence TEXT,            -- HIGH / MEDIUM / LOW
            daily_trend TEXT,
            hour_trend TEXT,
            fifteen_trend TEXT,
            direction TEXT,
            timeframe TEXT,
            news_risk TEXT,
            event_risk TEXT,
            -- ---- outcome (filled by mp_tracker) ----
            highest_price REAL,
            lowest_price REAL,
            max_drawdown_pct REAL,      -- adverse excursion, stored positive
            max_favorable_pct REAL,     -- favorable excursion, stored positive
            target_hit INTEGER DEFAULT 0,
            invalidation_hit INTEGER DEFAULT 0,
            ambiguous_bar INTEGER DEFAULT 0,  -- one bar's range spanned BOTH levels
            time_to_target_min INTEGER,
            trade_duration_min INTEGER,
            exit_price REAL,
            exit_reason TEXT,           -- TARGET / INVALIDATION / EXPIRED
            closed_at TEXT,
            last_checked TEXT,
            status TEXT DEFAULT 'OPEN'  -- OPEN / TARGET_HIT / INVALIDATED / EXPIRED
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_cohort ON trades(signal, setup, status)")
    conn.commit()
    conn.close()
    return DB_PATH


def record_signal(data, news_risk=None, event_risk=None):
    """
    Insert one row the instant a signal arrives. Mirrors the values your
    webhook already parsed; adds nothing to the critical path but a fast INSERT.
    Returns the new row id (or None on failure -- never raises into your flow).
    """
    try:
        side = str(data.get("signal", "")).upper()
        buy_score = _i(data.get("buyScore"))
        short_score = _i(data.get("shortScore"))
        active = buy_score if side == "BUY" else short_score

        row = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "bar_time": data.get("time"),
            "ticker": data.get("ticker"),
            "signal": side,
            "setup": data.get("setup"),
            "entry_price": _f(data.get("price")),
            "target_price": _f(data.get("target")),
            "invalidation_price": _f(data.get("invalidation")),
            "active_score": active,
            "buy_score": buy_score,
            "short_score": short_score,
            "confidence": data.get("confidence"),
            "daily_trend": data.get("dailyTrend"),
            "hour_trend": data.get("hourTrend"),
            "fifteen_trend": data.get("fifteenTrend"),
            "direction": data.get("direction"),
            "timeframe": data.get("timeframe"),
            "news_risk": news_risk,
            "event_risk": event_risk,
        }
        placeholders = ", ".join(["?"] * len(SIGNAL_COLS))
        sql = f"INSERT INTO trades ({', '.join(SIGNAL_COLS)}) VALUES ({placeholders})"
        conn = _conn()
        cur = conn.cursor()
        cur.execute(sql, [row[c] for c in SIGNAL_COLS])
        conn.commit()
        tid = cur.lastrowid
        conn.close()
        return tid
    except Exception as e:
        print(f"[mp_db] record_signal failed: {e}")
        return None


def get_open_trades():
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM trades WHERE status = 'OPEN' ORDER BY id ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_trade(tid, fields):
    """Generic UPDATE. `fields` keys are internal column names only."""
    if not fields:
        return
    keys = list(fields.keys())
    sets = ", ".join(f"{k} = ?" for k in keys)
    vals = [fields[k] for k in keys] + [tid]
    conn = _conn()
    conn.execute(f"UPDATE trades SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()


def query(sql, params=()):
    conn = _conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]
