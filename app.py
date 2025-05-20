import os
import json
import re
from flask import Flask, request, jsonify
from flask_cors import CORS
from thefuzz import process

app = Flask(__name__)
CORS(app)

with open("routes.json", "r", encoding="utf-8") as f:
    routes = json.load(f)

# Унікальні міста
ALL_CITIES = sorted(set(
    city.lower()
    for route in routes
    for city in [route["start"], route["end"]] + [s["city"] for s in route.get("stops", [])]
))

# Синоніми і російські назви
city_aliases = {
    "днепр": "дніпро", "умань": "умань", "львов": "львів", "винница": "вінниця",
    "кропивницкий": "кропивницький", "доброполье": "добропілля", "краматорск": "краматорськ",
    "словянск": "слов’янськ", "славянск": "слов’янськ", "павлограл": "павлоград", "черкасс": "черкаси"
}

# Слова–намiри, що позначають бажання поїхати або замовити поїздку
INTENT_KEYWORDS = [
    "їхати", "доїхати", "купити квиток", "замовити", "забронювати",
    "потрібен автобус", "потрібен бус", "маршрутка", "маршрутки"
]

last_session = {}

def normalize(text):
    text = re.sub(r"[’']", "", text.lower()).strip()
    text = re.sub(r"\s+", " ", text)
    for alias, real in city_aliases.items():
        text = text.replace(alias, real)
    return text

def contains_intent(msg):
    return any(kw in msg for kw in INTENT_KEYWORDS)

def fuzzy_city(word):
    word = normalize(word)
    result = process.extractOne(word, ALL_CITIES)
    return result[0] if result and result[1] >= 70 else None

def extract_two_cities(text):
    words = normalize(text).split()
    found = []
    for word in words:
        city = fuzzy_city(word)
        if city and city not in found:
            found.append(city)
    return found[:2]

def route_link(start, end):
    return f"https://bus-timel.com.ua/routes/{normalize(start).replace(' ', '-')}-{normalize(end).replace(' ', '-')}.html"

def find_route_by_stops(start, end):
    for route in routes:
        all_points = [route["start"]] + [s["city"] for s in route.get("stops", [])] + [route["end"]]
        if start in all_points and end in all_points and all_points.index(start) < all_points.index(end):
            return route, all_points
    return None, []

def extract_price(route, end):
    if normalize(route["end"]) == end and route.get("price"):
        return route["price"]
    for stop in route.get("stops", []):
        if normalize(stop["city"]) == end and stop.get("price") and stop["price"].replace(" ", "").isdigit():
            return stop["price"]
    return None

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    message = data.get("message", "")
    session_id = data.get("session_id", "default")
    msg = normalize(message)

    if session_id not in last_session:
        last_session[session_id] = {"greeted": False}

    # Привітання при першому зверненні
    if not last_session[session_id]["greeted"]:
        last_session[session_id]["greeted"] = True
        return jsonify({"reply": "Вітаю! Я диспетчер Bus-Timel. Куди хочете їхати та звідки?"})

    # Якщо повідомлення не містить наміру їхати — перенаправимо
    if not contains_intent(msg) and len(extract_two_cities(msg)) < 2:
        return jsonify({"reply": "Я лише диспетчер автобусних маршрутів. Напишіть, будь ласка, куди ви плануєте їхати та звідки."})

    # Обробка “наоборот”
    if any(w in msg for w in ["в обратном направлении", "наоборот", "ні", "нет"]):
        if "confirm" in last_session[session_id]:
            start, end = last_session[session_id]["confirm"]
            start, end = end, start
        else:
            return jsonify({"reply": "Окей, уточніть, будь ласка, напрямок ще раз — звідки і куди."})

    # Підтвердження
    elif msg in ["так", "да"] and "confirm" in last_session[session_id]:
        start, end = last_session[session_id]["confirm"]

    else:
        # Витягуємо до двох міст
        cities = extract_two_cities(msg)
        if len(cities) == 2:
            start, end = cities[0], cities[1]
            last_session[session_id]["confirm"] = (start, end)
            return jsonify({
                "reply": f"Ви маєте на увазі з {start.capitalize()} до {end.capitalize()}?",
                "confirm": {"start": start, "end": end}
            })
        # Якщо вказано лише призначення
        elif len(cities) == 1:
            city = cities[0]
            # Визначимо, чи воно ймовірно призначення
            return jsonify({"reply": f"З якого міста ви хочете їхати до {city.capitalize()}?"})
        else:
            return jsonify({"reply": "Напишіть, будь ласка, куди ви хочете поїхати і звідки — можливо, з уточненням 'з' або 'до'."})

    # Шукаємо маршрут по зупинках
    route, all_points = find_route_by_stops(start, end)
    if route:
        idx_start = all_points.index(start)
        idx_end = all_points.index(end)
        price = extract_price(route, end) or "Уточнюйте"
        link = route_link(route["start"], route["end"])
        reply = f"🚌 <b>Маршрут:</b> {start.capitalize()} → {end.capitalize()}\n"
        reply += f"💰 <b>Ціна:</b> {price} грн\n"
        reply += f"⏳ <b>Тривалість:</b> {route.get('duration', '—')}\n"
        if route.get("departure_times"):
            reply += f"⏰ <b>Відправлення:</b> {route['departure_times'][0]}\n"
        if route.get("arrival_times"):
            reply += f"🕓 <b>Прибуття:</b> {route['arrival_times'][0]}\n"
        stops_path = all_points[idx_start+1:idx_end]
        if stops_path:
            reply += "🗺️ <b>Зупинки по дорозі:</b> " + " → ".join(stops_path) + "\n"
        reply += f"🔗 <a href='{link}'>Переглянути маршрут</a>\n📝 <a href='{link}'>Забронювати місце</a>"
        return jsonify({"reply": reply, "html": True})

    return jsonify({"reply": "На жаль, маршрут не знайдено. Спробуйте іншу комбінацію міст."})

@app.route("/")
def index():
    return "Bus-Timel Smart Dispatcher is running."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
