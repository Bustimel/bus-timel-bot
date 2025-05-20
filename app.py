
import os
import json
import re
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

with open("routes.json", "r", encoding="utf-8") as f:
    routes = json.load(f)

ALL_CITIES = [
  "бабанка",
  "баштанка",
  "бориспіль",
  "велика виска",
  "вороновиця",
  "вінниця",
  "гайсин",
  "гришине",
  "дніпро",
  "добропілля",
  "дружківка",
  "житомир",
  "запоріжжя",
  "знам'янка",
  "золотоноша",
  "казанка",
  "кам'янка",
  "канів",
  "карлівка",
  "київ",
  "коблево",
  "краматорськ",
  "красноград",
  "краснопілка",
  "кривий ріг",
  "кропивницький",
  "лубни",
  "львів",
  "межова",
  "миколаїв",
  "миколаївка",
  "немирів",
  "новий буг",
  "новоархангельск",
  "новомосковськ (самар)",
  "одеса",
  "олександрівка",
  "олександрія",
  "орадівка",
  "п'ятихатки",
  "павлоград",
  "пирятин",
  "покровськ",
  "полтава",
  "райгород",
  "решитилівка",
  "рівне",
  "слов'янка",
  "слов'янськ",
  "слов’янськ",
  "смоліне",
  "сміла",
  "суми",
  "тернопіль",
  "умань",
  "харків",
  "хмельницький",
  "хмельове",
  "хорол",
  "черкаси",
  "ізюм"
]

city_aliases = {
    "днепр": "дніпро",
    "умань": "умань",
    "львов": "львів",
    "винница": "вінниця",
    "кропивницкий": "кропивницький",
    "доброполье": "добропілля",
    "краматорск": "краматорськ",
    "словянск": "слов’янськ",
    "павлоград": "павлоград"
}

last_session = {}

def normalize(text):
    text = re.sub(r"[’']", "", text.lower()).strip()
    text = re.sub(r"\s+", " ", text)
    for alias, true_name in city_aliases.items():
        text = text.replace(alias, true_name)
    return text

def extract_cities(msg):
    return [c for c in ALL_CITIES if c in normalize(msg)]

def route_link(start, end):
    return f"https://bus-timel.com.ua/routes/{normalize(start).replace(' ', '-')}-{normalize(end).replace(' ', '-')}.html"

def find_route_by_stops(start, end):
    for route in routes:
        all_points = [route["start"]] + [s["city"] for s in route.get("stops", [])] + [route["end"]]
        if start in all_points and end in all_points and all_points.index(start) < all_points.index(end):
            return route, all_points
    return None, []

def extract_price(route, end):
    if normalize(route["end"]) == end:
        return route.get("price")
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

    if not last_session[session_id]["greeted"]:
        last_session[session_id]["greeted"] = True
        return jsonify({"reply": "Вітаю! Я диспетчер Bus-Timel. Напишіть, будь ласка, з якого міста і куди ви хочете їхати."})

    if msg in ["так", "да"] and "confirm" in last_session[session_id]:
        start, end = last_session[session_id]["confirm"]
    elif msg in ["ні", "нет", "наоборот"] and "confirm" in last_session[session_id]:
        end, start = last_session[session_id]["confirm"]
    else:
        cities = extract_cities(msg)
        if len(cities) == 2:
            start, end = cities[0], cities[1]
            last_session[session_id]["confirm"] = (start, end)
            return jsonify({
                "reply": f"Ви маєте на увазі з {start.capitalize()} до {end.capitalize()}?",
                "confirm": {"start": start, "end": end}
            })
        else:
            return jsonify({"reply": "Напишіть, будь ласка, з якого міста і куди ви хочете їхати."})

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

    return jsonify({"reply": "На жаль, маршрут з цих міст не знайдено. Уточніть, будь ласка, ще раз."})

@app.route("/")
def index():
    return "Bus-Timel MEGA BOT is running."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
