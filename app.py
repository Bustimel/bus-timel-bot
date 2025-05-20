import os
import json
import re
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import requests
from thefuzz import fuzz
from datetime import datetime

app = Flask(__name__)
CORS(app)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
TELEGRAM_USER_ID = os.getenv("TELEGRAM_USER_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

with open("routes.json", "r", encoding="utf-8") as f:
    routes = json.load(f)

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

def find_similar_routes(message):
    user_input = normalize(message)
    suggestions = []
    for route in routes:
        label = f"{route['start']} → {route['end']}"
        combo = f"{route['start']} {route['end']}"
        score = fuzz.partial_ratio(normalize(combo), user_input)
        if score > 50:
            suggestions.append((score, label))
    suggestions.sort(reverse=True)
    return [label for score, label in suggestions[:3]]

def find_route_between_stops(message):
    user_input = normalize(message)
    best = None
    best_score = 0
    for route in routes:
        cities = [route["start"]] + [s["city"] for s in route.get("stops", [])] + [route["end"]]
        for i, from_city in enumerate(cities):
            for j in range(i + 1, len(cities)):
                to_city = cities[j]
                combo = f"{from_city} {to_city}"
                score = fuzz.partial_ratio(normalize(combo), user_input)
                if score > best_score:
                    best_score = score
                    best = (route, from_city, to_city, i, j)
    return best if best_score > 65 else None

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "")
    session_id = data.get("session_id", "default")

    # Нічний режим
    now_hour = datetime.now().hour
    if now_hour >= 21 or now_hour < 7:
        return jsonify({"reply": "Диспетчер зараз відпочиває. Ми з вами зв’яжемося зранку!"})

    # FAQ відповіді
    for keyword, answer in faq_keywords.items():
        if keyword in user_message.lower():
            return jsonify({"reply": answer})

    if '→' not in user_message and session_id in user_sessions:
        from_city = user_sessions[session_id]
        to_city = user_message.strip()
        combined = f"{from_city} {to_city}"
        found_route = find_best_route(combined)
        if found_route:
            del user_sessions[session_id]
            user_message = combined
        else:
            return jsonify({"reply": "Не знайшов маршрут. Спробуйте інше місто або повний напрямок."})

    if any(user_message.lower().startswith(prefix) for prefix in ["з ", "із ", "від "]):
        city = user_message.split(" ", 1)[-1].strip()
        user_sessions[session_id] = city
        return jsonify({"reply": f"Куди саме ви хочете їхати з {city}?"})

    route_between = find_route_between_stops(user_message)
    if route_between:
        route, from_city, to_city, i, j = route_between
        price = "Уточнюйте за номером +380753750000"
        if 'stops' in route:
            segment = route['stops'][i:j] if j <= len(route['stops']) else []
            for stop in segment:
                if stop.get("city") == to_city and stop.get("price", "").replace(" ", "").isdigit():
                    price = f"{stop['price']} грн"
        reply = f"Маршрут: {from_city} → {to_city}\nЦіна: {price}\nТривалість: Уточнюйте у оператора\nМаршрут проходить через: " + ", ".join([s['city'] for s in route['stops'][i:j]])
        text = f"[ЗАПИТ]\n{from_city} → {to_city}\nЦіна: {price}\nКористувач написав: {user_message}"
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_USER_ID, "text": text})
        return jsonify({"reply": reply})

    found_route = find_best_route(user_message)
    if found_route:
        details = f"Маршрут: {found_route['start']} → {found_route['end']}\n"
        price = str(found_route.get("price", "")).strip().lower()
        if price and "уточнюйте" not in price and price.replace(" ", "").isdigit():
            details += f"Ціна: {price} грн\n"
        else:
            details += "Ціна: Уточнюйте за номером +380753750000\n"
        details += f"Тривалість: {found_route.get('duration', '—')}\n"
        if found_route.get("departure_times"):
            details += f"Відправлення: {', '.join(found_route['departure_times'])}\n"
        if found_route.get("arrival_times"):
            details += f"Прибуття: {', '.join(found_route['arrival_times'])}\n"
        if found_route.get("stops"):
            details += "Зупинки: " + ", ".join([s['city'] for s in found_route["stops"]]) + "\n"
        link = route_link(found_route['start'], found_route['end'])
        details += f"\nПереглянути маршрут: {link}"
        reply = details
    else:
        suggestions = find_similar_routes(user_message)
        if suggestions:
            reply = "Не знайшов точний маршрут. Можливо ви мали на увазі:\n" + "\n".join(suggestions)
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
    text = f'''ЗАЯВКА:
Ім'я: {name}
Телефон: {phone}
Маршрут: {route}
Дата: {date}'''
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_USER_ID, "text": text})
    return jsonify({"status": "ok"})

@app.route("/")
def index():
    return "Bus-Timel SUPERBOT API is running."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
