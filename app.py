import os
import json
from flask import Flask, request, jsonify
import openai
import difflib
import requests

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")
TELEGRAM_USER_ID = os.getenv("TELEGRAM_USER_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

with open("routes.json", "r", encoding="utf-8") as f:
    routes = json.load(f)

def normalize(text):
    return text.lower().replace("’", "'").replace("і", "и").strip()

def find_route(from_city, to_city):
    f = normalize(from_city)
    t = normalize(to_city)
    for route in routes:
        start = normalize(route["start"])
        end = normalize(route["end"])
        if f in start and t in end:
            return route
    return None

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
    response = openai.ChatCompletion.create(model="gpt-4", messages=messages)
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
