import os
import json
import sqlite3
import requests
import yfinance as yf
from datetime import datetime, timezone
from flask import Flask, request
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

executor = ThreadPoolExecutor(max_workers=10)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

DB_FILE = "marketpulse_ai_v5.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            ticker TEXT,
            signal TEXT,
            price TEXT,
            setup TEXT,
            daily_trend TEXT,
            hour_trend TEXT,
            fifteen_trend TEXT,
            buy_score TEXT,
            short_score TEXT,
            confidence TEXT,
            target TEXT,
            invalidation TEXT,
            ai_validation TEXT,
            ai_reason TEXT,
            earnings_risk TEXT,
            dividend_risk TEXT,
            news_risk TEXT,
            event_risk TEXT,
            raw_json TEXT
        )
    """)
    conn.commit()
    conn.close()


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(
        url,
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
        timeout=10
    )


def get_value(data, key, default="N/A"):
    return data.get(key, default)


def check_market_events(ticker):
    earnings_risk = "No earnings risk detected"
    dividend_risk = "No dividend risk detected"
    news_risk = "No major news risk detected"
    event_risk = "LOW"

    try:
        stock = yf.Ticker(ticker)

        # Earnings check
        try:
            cal = stock.calendar
            if cal is not None and not cal.empty:
                earnings_date = cal.index[0]
                earnings_risk = f"Possible earnings date: {earnings_date}"
                event_risk = "MEDIUM"
        except Exception:
            earnings_risk = "Earnings check unavailable"

        # Dividend check
        try:
            divs = stock.dividends
            if divs is not None and len(divs) > 0:
                last_div_date = divs.index[-1].date()
                dividend_risk = f"Last dividend recorded: {last_div_date}"
        except Exception:
            dividend_risk = "Dividend check unavailable"

        # News check
        try:
            news = stock.news
            if news and len(news) > 0:
                latest_titles = []
                for item in news[:3]:
                    title = item.get("title", "")
                    if title:
                        latest_titles.append(title)

                if latest_titles:
                    news_risk = "Latest headlines checked"
        except Exception:
            news_risk = "News check unavailable"

    except Exception:
        earnings_risk = "Event data unavailable"
        dividend_risk = "Event data unavailable"
        news_risk = "Event data unavailable"
        event_risk = "UNKNOWN"

    return earnings_risk, dividend_risk, news_risk, event_risk


def ai_validate_trade(data, earnings_risk, dividend_risk, news_risk, event_risk):
    signal = str(get_value(data, "signal")).upper()
    ticker = get_value(data, "ticker")
    price = get_value(data, "price")
    daily = get_value(data, "dailyTrend")
    hour = get_value(data, "hourTrend")
    fifteen = get_value(data, "fifteenTrend")
    setup = get_value(data, "setup")
    buy_score = get_value(data, "buyScore")
    short_score = get_value(data, "shortScore")
    confidence = get_value(data, "confidence")
    target = get_value(data, "target")
    invalidation = get_value(data, "invalidation")

    prompt = f"""
You are MarketPulse AI v5.1, a strict professional trading assistant.

Validate this trade setup using only the data provided.

Signal: {signal}
Ticker: {ticker}
Price: {price}
Daily Trend: {daily}
1H Trend: {hour}
15m Trend: {fifteen}
Setup: {setup}
Buy Score: {buy_score}
Short Score: {short_score}
System Confidence: {confidence}
Target: {target}
Invalidation: {invalidation}

Event Checks:
Earnings: {earnings_risk}
Dividend: {dividend_risk}
News: {news_risk}
Overall Event Risk: {event_risk}

Classify the trade as exactly one of:
HIGH QUALITY
MODERATE
AVOID

Reply in this exact format:

Validation: HIGH QUALITY / MODERATE / AVOID
Reason: maximum two short sentences.

Rules:
- Be strict.
- If trends conflict, choose MODERATE or AVOID.
- If score is weak, choose MODERATE or AVOID.
- If event risk is HIGH, downgrade the trade.
- Do not mention guarantees.
- Do not give financial advice disclaimers.
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt
    )

    text = response.output_text.strip()

    validation = "MODERATE"
    reason = text

    for line in text.splitlines():
        if line.lower().startswith("validation"):
            validation = line.split(":", 1)[-1].strip()
        if line.lower().startswith("reason"):
            reason = line.split(":", 1)[-1].strip()

    return validation, reason


def save_alert(data, validation, reason, earnings_risk, dividend_risk, news_risk, event_risk):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO alerts (
            created_at,
            ticker,
            signal,
            price,
            setup,
            daily_trend,
            hour_trend,
            fifteen_trend,
            buy_score,
            short_score,
            confidence,
            target,
            invalidation,
            ai_validation,
            ai_reason,
            earnings_risk,
            dividend_risk,
            news_risk,
            event_risk,
            raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now(timezone.utc).isoformat(),
        get_value(data, "ticker"),
        get_value(data, "signal"),
        str(get_value(data, "price")),
        get_value(data, "setup"),
        get_value(data, "dailyTrend"),
        get_value(data, "hourTrend"),
        get_value(data, "fifteenTrend"),
        str(get_value(data, "buyScore")),
        str(get_value(data, "shortScore")),
        get_value(data, "confidence"),
        str(get_value(data, "target")),
        str(get_value(data, "invalidation")),
        validation,
        reason,
        earnings_risk,
        dividend_risk,
        news_risk,
        event_risk,
        json.dumps(data)
    ))

    conn.commit()
    conn.close()


def process_alert(data):
    try:
        signal = str(get_value(data, "signal")).upper()
        ticker = get_value(data, "ticker")
        price = get_value(data, "price")
        daily = get_value(data, "dailyTrend")
        hour = get_value(data, "hourTrend")
        fifteen = get_value(data, "fifteenTrend")
        setup = get_value(data, "setup")
        buy_score = get_value(data, "buyScore")
        short_score = get_value(data, "shortScore")
        confidence = get_value(data, "confidence")
        target = get_value(data, "target")
        invalidation = get_value(data, "invalidation")

        emoji = "🟢" if signal == "BUY" else "🔴"

        earnings_risk, dividend_risk, news_risk, event_risk = check_market_events(ticker)

        validation, reason = ai_validate_trade(
            data,
            earnings_risk,
            dividend_risk,
            news_risk,
            event_risk
        )

        save_alert(
            data,
            validation,
            reason,
            earnings_risk,
            dividend_risk,
            news_risk,
            event_risk
        )

        message = f"""
{emoji} {signal} NOW

📌 {ticker} @ {price}

📈 Trend Alignment
Daily : {daily}
1H    : {hour}
15m   : {fifteen}

⚡ Setup
{setup}

📊 Scores
Buy   : {buy_score}/100
Short : {short_score}/100

🔥 System Confidence
{confidence}

🤖 AI Validation
{validation}

📰 News
{news_risk}

📅 Earnings
{earnings_risk}

💵 Dividend
{dividend_risk}

🚨 Event Risk
{event_risk}

📝 Reason
{reason}

🎯 Target
{target}

🛑 Invalidation
{invalidation}

💾 Saved to MarketPulse AI v5.1 database
"""

        send_telegram(message.strip())

    except Exception as e:
        send_telegram(f"⚠️ MarketPulse AI v5.1 error\n\n{str(e)}")


@app.route("/")
def home():
    return "MarketPulse AI v5.1 Running 🚀"


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)

    if data is None:
        raw_text = request.data.decode("utf-8")
        try:
            data = json.loads(raw_text)
        except Exception:
            data = {"raw_message": raw_text}

    print("Received webhook data:")
    print(data)

    executor.submit(process_alert, data)

    return {"status": "accepted", "version": "v5.1"}, 200


@app.route("/stats")
def stats():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM alerts")
    total = cur.fetchone()[0]

    cur.execute("""
        SELECT ai_validation, COUNT(*)
        FROM alerts
        GROUP BY ai_validation
    """)
    validation_rows = cur.fetchall()

    cur.execute("""
        SELECT ticker, COUNT(*)
        FROM alerts
        GROUP BY ticker
        ORDER BY COUNT(*) DESC
        LIMIT 10
    """)
    ticker_rows = cur.fetchall()

    cur.execute("""
        SELECT setup, COUNT(*)
        FROM alerts
        GROUP BY setup
        ORDER BY COUNT(*) DESC
        LIMIT 10
    """)
    setup_rows = cur.fetchall()

    conn.close()

    return {
        "version": "MarketPulse AI v5.1",
        "total_alerts": total,
        "validation_summary": validation_rows,
        "top_tickers": ticker_rows,
        "top_setups": setup_rows
    }


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8080)
else:
    init_db()
