# MarketPulse AI v6.0 — Statistical Intelligence Edition

Backend upgrade for your existing Render Flask service. Five additive modules
plus ~6 lines wired into `app.py`. Your OpenAI / news / earnings / dividend /
Telegram flow is **unchanged** — v6.0 only writes signals to a database, tracks
their outcomes, and *appends* a historical-edge block to the Telegram message.

The Pine scanner (v2.6.1) needs **no change** — its JSON payload already carries
every field v6.0 needs.

---

## Files

| File | Role |
|------|------|
| `mp_db.py` | Persistent SQLite layer; new `trades` table; records each signal |
| `mp_providers.py` | Price data (yfinance default / Polygon optional); intraday + EOD |
| `mp_tracker.py` | Background tracker; outcome maths; APScheduler runner |
| `mp_stats.py` | Win-rate engine (setup / ticker / score / confidence / hour / weekday / side) |
| `mp_probability.py` | Cohort probability + Telegram block |
| `app.py` | **Your file, already patched** — every change marked `# v6.0` |
| `requirements.txt` | Adds `apscheduler` + `gunicorn` |

Drop the five `mp_*.py` files next to `app.py` in the same repo folder.

---

## The 5 changes in `app.py` (search `v6.0`)

1. Import the four modules.
2. `DB_FILE = mp_db.DB_PATH` — moves the DB onto the persistent disk (this also
   makes your existing `alerts` table survive deploys).
3. `mp_db.record_signal(data, news_risk, event_risk)` right after `save_alert(...)`.
4. Append `mp_probability.telegram_block(data)` to the message before sending.
5. `mp_db.init_db()` + `mp_tracker.start()` on startup, and a new `/stats/v6`
   endpoint.

If you prefer, copy these lines into your own `app.py` instead of using the
patched copy — the logic lives entirely in the `mp_*` modules.

---

## A. Render Persistent Disk (required)

Without a disk, Render wipes the filesystem on every deploy/restart, erasing the
database and resetting the probability engine to zero. Add one:

**Dashboard → your service → Disks → Add Disk**

| Setting | Value |
|---------|-------|
| Name | `marketpulse-data` |
| Mount Path | `/var/data` |
| Size | `1 GB` (years of signals are well under this) |

Then set env var `DATA_DIR=/var/data` to match the mount path.

Notes:
- A persistent disk requires a **paid instance** (Starter, ~$7/mo). The free tier
  has no disk and sleeps between requests — it would miss alerts anyway.
- With a disk, Render pins the service to a **single instance**, which matches the
  tracker's single-scheduler design.

---

## B. Tracking modes — works today on yfinance, Polygon optional

The tracker needs price *after* a signal fires to measure highest/lowest,
drawdown and target/invalidation hits. Two modes, chosen automatically:

- **intraday** — 1-minute bars (precise time-to-target). yfinance provides these
  free for the last ~7 days, so this works **now**, no Polygon plan needed.
- **eod** — daily bars; automatic fallback when intraday data is empty
  (delayed/limited feed).

`TRACKER_MODE=auto` (default) tries intraday first, falls back to EOD per fetch.

To switch to Polygon later: set `TRACKER_PROVIDER=polygon` and `POLYGON_API_KEY`.
If your plan lacks minute aggregates it returns empty and auto-falls back to EOD —
nothing breaks.

---

## Start command (Render → Settings)

```
gunicorn --workers 1 --threads 8 --timeout 120 app:app
```

`--workers 1` keeps a single tracker scheduler and one writer to the disk.
(The webhook already offloads heavy work to a thread pool, so threads cover
concurrency.) `mp_tracker` also holds a PID lock, so an accidental extra worker
won't double-count.

---

## Environment variables

Keep your existing: `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

New:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATA_DIR` | `/var/data` | Persistent-disk mount path (must match the disk) |
| `ENABLE_TRACKER` | `true` | Master on/off for the background tracker |
| `TRACKER_PROVIDER` | `yfinance` | `yfinance` or `polygon` |
| `TRACKER_MODE` | `auto` | `auto` / `intraday` / `eod` |
| `TRACKER_INTERVAL_MIN` | `5` | Minutes between tracker passes |
| `TRACKER_MAX_HOURS` | `24` | Intraday horizon before a trade EXPIRES |
| `TRACKER_MAX_DAYS` | `10` | EOD horizon before a trade EXPIRES |
| `PROB_MIN_SAMPLE` | `20` | Min cohort size before a probability is shown |
| `POLYGON_API_KEY` | — | Only if `TRACKER_PROVIDER=polygon` |

---

## How a signal flows in v6.0

1. Webhook arrives → row written to `trades` immediately (before OpenAI).
2. Your existing pipeline runs unchanged → OpenAI + filters + Telegram.
3. Telegram message gets a **Historical Edge** block appended — but only once a
   matching cohort reaches `PROB_MIN_SAMPLE`; until then the message is identical
   to today's.
4. Every `TRACKER_INTERVAL_MIN`, the tracker updates each OPEN trade and closes it
   as `TARGET_HIT` / `INVALIDATED` / `EXPIRED`.
5. `GET /stats/v6` returns the full win-rate breakdown.

## Outcome rules (so the numbers are trustworthy)

- **Win** = target hit. EXPIRED counts as a non-win.
- **Ambiguous bar**: if one bar's range touches *both* target and invalidation,
  intrabar order is unknowable from OHLC, so it's recorded as INVALIDATION
  (pessimistic) and flagged `ambiguous_bar=1`.
- Probability cohort cascades most→least specific:
  setup+side+score-band+confidence → setup+side+score-band → setup+side,
  taking the first with enough sample.

## Roadmap hooks (v6.1+)

The modules are isolated, so later additions don't touch the webhook path:
ML on the `trades` table, portfolio analytics across tickers, or a setup-ranking
endpoint built on `mp_stats`.
