import os
import json
import re
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import requests
from thefuzz import fuzz

app = Flask(__name__)
CORS(app)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
TELEGRAM_USER_ID = os.getenv("TELEGRAM_USER_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

with open("routes.json", "r", encoding="utf-8") as f:
    routes = json.load(f)

common_phrases = [
  "привіт", "добрий день", "вітаю", "хай", "як справи", "ок", "дякую", "добре",
  "здравствуйте", "привет", "добрый день", "как дела", "спасибо", "окей"
]

faq_keywords = {
  "тварин": "Так, перевезення тварин дозволено лише у переносках. Повідомте водія заздалегідь.",
  "багаж": "Безкоштовно дозволено 1 валізу до 20 кг та ручну поклажу. За додатковий багаж — уточнюйте у диспетчера.",
  "wifi": "Так, у більшості наших автобусів є Wi-Fi.",
  "оплата": "Оплата проводиться при посадці або після бронювання з підтвердженням по телефону.",
  "діти": "Діти до 5 років можуть їхати безкоштовно без окремого місця.",
  "перерва": "Автобус зупиняється на 1-2 санітарні перерви під час маршруту."
}

user_sessions = {}

def normalize(text):
    return re.sub(r'\s+', ' ', text.lower().replace("’", "'").replace("і", "и").replace("'", "").strip())

def route_link(start, end):
    s = re.sub(r"[^a-zа-я0-9]", "", normalize(start).replace(" ", "-"))
    e = re.sub(r"[^a-zа-я0-9]", "", normalize(end).replace(" ", "-"))
    return f"https://bus-timel.com.ua/routes/{s}-{e}.html"

def is_friendly(text):
    return normalize(text) in [normalize(p) for p in common_phrases]

def find_best_route(message):
    max_score = 0
    best_route = None
    user_input = normalize(message)
    for route in routes:
        cities = [route["start"]] + [s["city"] for s in route.get("stops", [])] + [route["end"]]
        combo = " ".join(cities)
        score = fuzz.partial_ratio(normalize(combo), user_input)
        if score > max_score:
            max_score = score
            best_route = route
    return best_route if max_score > 65 else None

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")
    session_id = data.get("session_id", "default")

    if is_friendly(user_message):
        return jsonify({"reply": "Вітаю! Я диспетчер Bus-Timel. Напишіть, будь ласка, звідки і куди ви хочете їхати."})

    for keyword, answer in faq_keywords.items():
        if keyword in user_message.lower():
            return jsonify({"reply": answer})

    found_route = find_best_route(user_message)

    if found_route:
        price = str(found_route.get("price", "")).strip().lower()
        reply = ""
        reply += f"🚌 <b>Маршрут:</b> {found_route['start']} → {found_route['end']}\n"
        if price and "уточнюйте" not in price and price.replace(" ", "").isdigit():
            reply += f"💰 <b>Ціна:</b> {price} грн\n"
        else:
            reply += "💰 <b>Ціна:</b> Уточнюйте за номером +380753750000\n"
        reply += f"⏳ <b>Тривалість:</b> {found_route.get('duration', '—')}\n"
        if found_route.get("departure_times"):
            reply += f"⏰ <b>Відправлення:</b> {', '.join(found_route['departure_times'])}\n"
        if found_route.get("arrival_times"):
            reply += f"🕓 <b>Прибуття:</b> {', '.join(found_route['arrival_times'])}\n"
        if found_route.get("stops"):
            reply += "🗺️ <b>Зупинки:</b> " + " → ".join([s['city'] for s in found_route["stops"]]) + "\n"
        link = route_link(found_route['start'], found_route['end'])
        reply += f"\n🔗 <a href='{link}'>Переглянути маршрут</a>"
        reply += f"\n📝 <a href='{link}'>Забронювати місце</a>"
        return jsonify({"reply": reply, "html": True})

    return jsonify({"reply": "Не знайшов маршрут. Напишіть, будь ласка, звідки і куди ви хочете їхати."})

@app.route("/")
def index():
    return "Bus-Timel SUPERBOT is live."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
