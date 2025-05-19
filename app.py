import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import requests
import re

app = Flask(__name__)
CORS(app)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
TELEGRAM_USER_ID = os.getenv("TELEGRAM_USER_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

with open("routes.json", "r", encoding="utf-8") as f:
    routes = json.load(f)

def normalize(text):
    return text.lower().replace("’", "'").replace("і", "и").replace("'", "").strip()

def route_link(start, end):
    s = re.sub(r"[^a-zа-я0-9]", "", normalize(start).replace(" ", "-"))
    e = re.sub(r"[^a-zа-я0-9]", "", normalize(end).replace(" ", "-"))
    return f"https://bus-timel.com.ua/routes/{s}-{e}.html"

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")
    found_route = None
    for route in routes:
        if normalize(route["start"]) in normalize(user_message) and normalize(route["end"]) in normalize(user_message):
            found_route = route
            break

    if found_route:
        details = f"Маршрут: {found_route['start']} → {found_route['end']}\n"
        details += f"Ціна: {found_route['price']} грн\n"
        details += f"Тривалість: {found_route['duration']}\n"
        if found_route.get("departure_times"):
            details += f"Відправлення: {', '.join(found_route['departure_times'])}\n"
        if found_route.get("arrival_times"):
            details += f"Прибуття: {', '.join(found_route['arrival_times'])}\n"
        details += "Зупинки: " + ", ".join([s['city'] for s in found_route["stops"]]) + "\n"
        details += f"\n[Перейти на сторінку маршруту]({route_link(found_route['start'], found_route['end'])})"
        reply = details
    else:
        messages = [
            {
                "role": "system",
                "content": (
                    "Ти диспетчер компанії Bus-Timel. Відповідай українською, коротко і чітко. "
                    "Форматуй посилання типу /routes/{start}-{end}.html. "
                    "Говори як живий оператор, допомагай обрати маршрут."
                )
            },
            {"role": "user", "content": user_message}
        ]
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        reply = response.choices[0].message.content

    return jsonify({"reply": reply})

@app.route("/request", methods=["POST"])
def request_submit():
    data = request.json
    name = data.get("name", "")
    phone = data.get("phone", "")
    route = data.get("route", "")
    date = data.get("date", "")
    text = f"""ЗАЯВКА:
Ім'я: {name}
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
