import os
import requests
from flask import Flask, request
from openai import OpenAI

app = Flask(__name__)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

@app.route("/")
def home():
    return "MarketPulse AI Server Running"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    prompt = f"""
You are a trading assistant. Analyse this TradingView signal.

Data:
{data}

Give:
1. BUY, SELL, WAIT, or AVOID
2. Confidence %
3. Reason
4. 1% target price if possible

Keep it short.
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