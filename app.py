import os
import json
import requests
from flask import Flask, request
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

executor = ThreadPoolExecutor(max_workers=10)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        },
        timeout=10
    )


def get_value(data, key, default="N/A"):
    return data.get(key, default)


def ai_validate_trade(data):
    signal = get_value(data, "signal")
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
You are MarketPulse AI, a professional trading assistant.

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

Classify the trade as exactly one of:
HIGH QUALITY
MODERATE
AVOID

Reply in this exact format:

Validation:
Reason:

Rules:
- The validation must be only HIGH QUALITY, MODERATE, or AVOID.
- The reason must be maximum two short sentences.
- Do not mention guarantees.
- Do not give financial advice disclaimers.
- Be strict. If trends conflict or scores are weak, choose MODERATE or AVOID.
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt
    )

    return response.output_text.strip()


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

        ai_result = ai_validate_trade(data)

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
{ai_result}

🎯 Target
{target}

🛑 Invalidation
{invalidation}
"""

        send_telegram(message.strip())

    except Exception as e:
        send_telegram(f"⚠️ MarketPulse AI error\n\n{str(e)}")


@app.route("/")
def home():
    return "MarketPulse AI Server Running 🚀"


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)

    if data is None:
        raw_text = request.data.decode("utf-8")

        try:
            data = json.loads(raw_text)
        except Exception:
            data = {"raw_message": raw_text}

    executor.submit(process_alert, data)

    return {"status": "accepted"}, 200


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8080
    )
