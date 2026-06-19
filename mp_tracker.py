"""
MarketPulse AI v6.0  --  mp_tracker.py
Background outcome tracker.

Every TRACKER_INTERVAL_MIN minutes it walks each OPEN trade, pulls the bars
that printed AFTER entry, and updates:
  highest / lowest price, max drawdown, max favourable move,
  target hit?, invalidation hit?, time-to-target, trade duration,
  and the final status (TARGET_HIT / INVALIDATED / EXPIRED).

`evaluate()` is a PURE function (no I/O) so it is unit-tested directly.

Intrabar ambiguity rule: if a single bar's range touches BOTH the target and
the invalidation, true order is unknowable from OHLC, so we assume the
invalidation first (pessimistic) and flag ambiguous_bar = 1.
"""

import os
from datetime import datetime, timezone, timedelta

import mp_db
import mp_providers

MAX_HOURS = float(os.environ.get("TRACKER_MAX_HOURS", "24"))    # intraday horizon
MAX_DAYS = float(os.environ.get("TRACKER_MAX_DAYS", "10"))      # eod horizon
INTERVAL_MIN = int(os.environ.get("TRACKER_INTERVAL_MIN", "5"))
MODE = os.environ.get("TRACKER_MODE", "auto")


def _parse(ts):
    return datetime.fromisoformat(ts)


def evaluate(trade, bars, mode, now=None):
    """
    Pure outcome calculation. Returns a dict of column updates for the trade.
    `bars` must already be filtered to time >= entry and sorted ascending.
    """
    now = now or datetime.now(timezone.utc)
    entry = trade.get("entry_price")
    target = trade.get("target_price")
    invalid = trade.get("invalidation_price")
    side = (trade.get("signal") or "").upper()
    entry_time = _parse(trade["created_at"])

    upd = {"last_checked": now.isoformat()}
    if not bars or entry is None or entry == 0:
        # nothing to measure yet; maybe expire on age alone
        return _maybe_expire(trade, upd, entry_time, now, mode, last_close=entry)

    highest = max(b["h"] for b in bars)
    lowest = min(b["l"] for b in bars)
    last_close = bars[-1]["c"]

    if side == "BUY":
        mfe = (highest - entry) / entry * 100.0
        mae = (lowest - entry) / entry * 100.0          # <= 0
    else:  # SHORT
        mfe = (entry - lowest) / entry * 100.0
        mae = (entry - highest) / entry * 100.0          # <= 0

    upd["highest_price"] = round(highest, 4)
    upd["lowest_price"] = round(lowest, 4)
    upd["max_favorable_pct"] = round(max(0.0, mfe), 4)
    upd["max_drawdown_pct"] = round(abs(min(0.0, mae)), 4)

    # Walk forward to find the FIRST resolving bar.
    exit_reason = None
    exit_price = None
    ambiguous = 0
    hit_time = None
    if target is not None and invalid is not None:
        for b in bars:
            if side == "BUY":
                hT, hI = b["h"] >= target, b["l"] <= invalid
            else:
                hT, hI = b["l"] <= target, b["h"] >= invalid
            if hT and hI:
                ambiguous = 1
                exit_reason, exit_price, hit_time = "INVALIDATION", invalid, b["time"]
                break
            if hT:
                exit_reason, exit_price, hit_time = "TARGET", target, b["time"]
                break
            if hI:
                exit_reason, exit_price, hit_time = "INVALIDATION", invalid, b["time"]
                break

    upd["ambiguous_bar"] = ambiguous

    if exit_reason == "TARGET":
        dur = max(0, int((hit_time - entry_time).total_seconds() // 60))
        upd.update({
            "target_hit": 1, "invalidation_hit": 0,
            "time_to_target_min": dur, "trade_duration_min": dur,
            "exit_price": exit_price, "exit_reason": "TARGET",
            "closed_at": now.isoformat(), "status": "TARGET_HIT",
        })
        return upd

    if exit_reason == "INVALIDATION":
        dur = max(0, int((hit_time - entry_time).total_seconds() // 60))
        upd.update({
            "target_hit": 0, "invalidation_hit": 1,
            "trade_duration_min": dur,
            "exit_price": exit_price, "exit_reason": "INVALIDATION",
            "closed_at": now.isoformat(), "status": "INVALIDATED",
        })
        return upd

    # No level hit -> still open unless it has aged out.
    return _maybe_expire(trade, upd, entry_time, now, mode, last_close=last_close)


def _maybe_expire(trade, upd, entry_time, now, mode, last_close):
    horizon = timedelta(hours=MAX_HOURS) if mode == "intraday" else timedelta(days=MAX_DAYS)
    age = now - entry_time
    if age >= horizon:
        dur = int(age.total_seconds() // 60)
        upd.update({
            "trade_duration_min": dur,
            "exit_price": last_close,
            "exit_reason": "EXPIRED",
            "closed_at": now.isoformat(),
            "status": "EXPIRED",
        })
    return upd


# --------------------------------------------------------------------------- #
#  Runner
# --------------------------------------------------------------------------- #
def run_once():
    opened = mp_db.get_open_trades()
    for t in opened:
        try:
            since = _parse(t["created_at"])
            bars, mode_used = mp_providers.get_bars(t["ticker"], since, MODE)
            if not bars and t.get("entry_price"):
                # still try age-based expiry even with no data
                upd = evaluate(t, [], "intraday" if MODE != "eod" else "eod")
            else:
                upd = evaluate(t, bars, mode_used)
            mp_db.update_trade(t["id"], upd)
        except Exception as e:
            print(f"[mp_tracker] trade {t.get('id')} failed: {e}")


# --------------------------------------------------------------------------- #
#  Singleton scheduler (safe under multiple gunicorn workers)
# --------------------------------------------------------------------------- #
_scheduler = None
_LOCK = os.path.join(mp_db.DATA_DIR, ".mp_tracker.lock")


def _acquire_lock():
    """Only one process runs the scheduler. Steals a stale lock (dead PID)."""
    try:
        if os.path.exists(_LOCK):
            with open(_LOCK) as f:
                pid = int((f.read().strip() or "0"))
            alive = True
            try:
                os.kill(pid, 0)
            except (OSError, ProcessLookupError):
                alive = False
            if alive:
                return False
            os.remove(_LOCK)
        fd = os.open(_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except Exception as e:
        print(f"[mp_tracker] lock error: {e}")
        return True  # fail open at low volume


def start():
    """Call once at import. Respects ENABLE_TRACKER and the worker lock."""
    global _scheduler
    if os.environ.get("ENABLE_TRACKER", "true").lower() not in ("1", "true", "yes"):
        print("[mp_tracker] disabled via ENABLE_TRACKER")
        return
    if _scheduler is not None:
        return
    if not _acquire_lock():
        print("[mp_tracker] another worker holds the tracker lock; skipping")
        return
    from apscheduler.schedulers.background import BackgroundScheduler
    _scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    _scheduler.add_job(run_once, "interval", minutes=INTERVAL_MIN,
                       id="mp_tracker", max_instances=1, coalesce=True,
                       next_run_time=datetime.now(timezone.utc))
    _scheduler.start()
    print(f"[mp_tracker] started, every {INTERVAL_MIN} min, mode={MODE}")
