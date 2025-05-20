import os
import json
import re
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

with open("routes.json", "r", encoding="utf-8") as f:
    routes = json.load(f)

def normalize(text):
    return re.sub(r'\s+', ' ', text.lower().replace("’", "'").replace("і", "и").replace("'", "").strip())

def extract_direction_cities(message, known_cities):
    text = normalize(message)
    return [city for city in known_cities if city in text]

def build_route_link(start, end):
    s = normalize(start).replace(" ", "-")
    e = normalize(end).replace(" ", "-")
    return f"https://bus-timel.com.ua/routes/{s}-{e}.html"

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    message = data.get("message", "")
    session_id = data.get("session_id", "default")

    # Отримуємо список усіх унікальних міст
    all_cities = set()
    for r in routes:
        all_cities.add(normalize(r["start"]))
        all_cities.add(normalize(r["end"]))

    # Знаходимо, які міста згадані в повідомленні
    matched_cities = extract_direction_cities(message, all_cities)

    if len(matched_cities) == 2:
        # Якщо рівно два міста — уточнити
        start, end = matched_cities[1], matched_cities[0]
        return jsonify({
            "reply": f"Ви маєте на увазі з {start.capitalize()} до {end.capitalize()}?",
            "confirm": {
                "start": start,
                "end": end
            }
        })

    if len(matched_cities) < 2:
        return jsonify({"reply": "Напишіть, будь ласка, з якого міста і куди ви хочете їхати."})

    # Якщо більше 2 міст — шукаємо всі маршрути між згаданими
    matched_routes = []
    for route in routes:
        if normalize(route["start"]) in matched_cities and normalize(route["end"]) in matched_cities:
            matched_routes.append(route)

    if matched_routes:
        replies = []
        for r in matched_routes:
            link = build_route_link(r["start"], r["end"])
            reply = f"🚌 <b>Маршрут:</b> {r['start']} → {r['end']}\n"
            reply += f"💰 <b>Ціна:</b> {r.get('price', 'Уточнюйте')} грн\n"
            reply += f"⏳ <b>Тривалість:</b> {r.get('duration', '—')}\n"
            if r.get("departure_times"):
                reply += f"⏰ <b>Відправлення:</b> {', '.join(r['departure_times'])}\n"
            if r.get("arrival_times"):
                reply += f"🕓 <b>Прибуття:</b> {', '.join(r['arrival_times'])}\n"
            reply += f"🔗 <a href='{link}'>Переглянути маршрут</a>\n📝 <a href='{link}'>Забронювати місце</a>"
            replies.append(reply)
        return jsonify({"reply": "\n\n".join(replies), "html": True})

    return jsonify({"reply": "Не знайшов маршрут. Уточніть, будь ласка, напрямок."})

@app.route("/")
def index():
    return "Bus-Timel Directional bot is working."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
