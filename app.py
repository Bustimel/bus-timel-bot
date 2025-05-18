import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
import requests

app = Flask(__name__)
CORS(app)

openai.api_key = os.getenv("OPENAI_API_KEY")
TELEGRAM_USER_ID = os.getenv("TELEGRAM_USER_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

with open("routes.json", "r", encoding="utf-8") as f:
    routes = json.load(f)

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")
    messages = [
        {
            "role": "system",
            "content": (
                "Ти диспетчер компанії Bus-Timel. Відповідай українською, коротко і зрозуміло. "
                "Ти знаєш всі маршрути, розклад, ціни та зупинки з файлу routes.json. "
                "Також можеш дати посилання на сторінку маршруту типу /routes/{start}-{end}.html"
            )
        },
        {"role": "user", "content": user_message}
    ]
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",  # ← зміна тут
        messages=messages
    )
    answer = response.choices[0].message["content"]
    return jsonify({"reply": answer})

@app.route("/request", methods=["POST"])
def request_submit():
    data = request.json
    name = data.get("name", "")
    phone = data.get("phone", "")
    route = data.get("route", "")
    date = data.get("date", "")
    text = f"""ЗАЯВКА:
Ім’я: {name}
Телефон: {phone}
Маршрут: {route}
Дата: {date}"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_USER_ID, "text": text})
    return jsonify({"status": "ok"})

@app.route("/")
def index():
    return "Bus-Timel bot API is running."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
