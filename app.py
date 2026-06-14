import os
import requests
from flask import Flask, request
from openai import OpenAI

app = Flask(__name__)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    })

@app.route("/")
def home():
    return "MarketPulse AI Server Running"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)

    if data is None:
        data = {"raw_message": request.data.decode("utf-8")}

    prompt = f"""
You are MarketPulse AI, a trading assistant.

Analyse this TradingView alert:

{data}

Reply in this exact style:

🟢 BUY NOW or 🔴 SHORT NOW

Ticker:
Price:
Daily Trend:
1H Trend:
15m Trend:
Setup:
Score:
Target:
Invalidation:
Confidence: LOW / MEDIUM / HIGH

Reason:
Short, clear explanation.

Important:
Do not say it guarantees profit.
Keep it practical for a trader.
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt
    )

    ai_message = response.output_text
    send_telegram(ai_message)

    return {"status": "sent", "analysis": ai_message}

if __name__ == "__main__":
    app.run()
