import os
import requests
from flask import Flask, request
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

# Process multiple alerts simultaneously
executor = ThreadPoolExecutor(max_workers=10)

client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY")
)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        }
    )


def process_alert(data):

    prompt = f"""
You are MarketPulse AI, an expert trading assistant.

Analyse this TradingView alert:

{data}

Reply in EXACTLY this format:

🟢 BUY NOW
or
🔴 SHORT NOW

Ticker:
Price:

📈 TREND ALIGNMENT
Daily:
1H:
15m:

⚡ Setup:

📊 Buy Score:
📊 Short Score:

🔥 Confidence:

🎯 Target:

Reason:
Maximum two short sentences explaining why the setup is attractive.

Rules:

- Keep the answer concise.
- Sound like a professional trader.
- Do not mention guarantees.
- Do not mention probabilities.
- No disclaimers.
- Use emojis exactly as shown.
"""

    try:

        response = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt
        )

        ai_message = response.output_text

        send_telegram(ai_message)

    except Exception as e:

        send_telegram(
            f"⚠️ MarketPulse AI error\n\n{str(e)}"
        )


@app.route("/")
def home():
    return "MarketPulse AI Server Running 🚀"


@app.route("/webhook", methods=["POST"])
def webhook():

    data = request.get_json(silent=True)

    if data is None:
        data = {
            "raw_message": request.data.decode("utf-8")
        }

    # Process in background
    executor.submit(process_alert, data)

    # Reply immediately to TradingView
    return {"status": "accepted"}, 200


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8080
    )
