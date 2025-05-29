import os
import json
import re
import smtplib
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from email.mime.text import MIMEText
from thefuzz import process, fuzz
import logging
import openai
from city_forms import CITY_FORMS

app = Flask(__name__)
CORS(app, resources={r"/chat": {"origins": [
    "https://bus-timel.com.ua",
    "http://localhost:8080"
]}})

logging.basicConfig(filename='bot.log', level=logging.INFO, format='%(asctime)s - %(message)s')
sessions = {}

# Завантаження маршрутів
try:
    with open("routes.json", encoding="utf-8") as f:
        data = json.load(f)
        routes = data["routes"]
except Exception as e:
    logging.error(f"❌ Error loading routes: {e}")
    routes = []

def normalize(text):
    return re.sub(r"[’']", "", text.lower()).strip()

def match_city(word):
    norm = normalize(word)
    for base, forms in CITY_FORMS.items():
        if norm in forms:
            return base
    result = process.extractOne(norm, CITY_FORMS.keys(), scorer=fuzz.partial_ratio)
    return result[0] if result and result[1] > 70 else None

def extract_cities(text):
    words = normalize(text).split()
    found = []
    for word in words:
        city = match_city(word)
        if city and city not in found:
            found.append(city)
    return found[:2]

def find_real_route(start, end):
    for route in routes:
        all_points = [route.get("start", "").lower()] + \
                     [s["city"]["uk"].lower() for s in route.get("stops", [])] + \
                     [route.get("end", "").lower()]
        if start in all_points and end in all_points and all_points.index(start) < all_points.index(end):
            return route
    return None

def send_email(name, phone, start, end, date=None):
    msg = MIMEText(f"📥 Нова заявка:\nІм’я: {name}\nТелефон: {phone}\nМаршрут: {start} → {end}\nДата: {date or 'не вказано'}")
    msg["Subject"] = "Нова заявка з сайту Bus-Timel"
    msg["From"] = os.environ.get("EMAIL_USER", "📩_EMAIL_USER_HERE")
    msg["To"] = "bustimelll@gmail.com"
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(os.environ["EMAIL_USER"], os.environ["EMAIL_PASS"])
            server.send_message(msg)
    except Exception as e:
        logging.error(f"❌ Email error: {e}")

def gpt_reply(prompt):
    openai.api_key = os.environ.get("OPENAI_API_KEY", "GPT_KEY_HERE")
    messages = [
        {"role": "system", "content": "Ти ввічливий диспетчер Bus-Timel. Відповідай українською, чітко і допомагай."},
        {"role": "user", "content": prompt}
    ]
    try:
        response = openai.ChatCompletion.create(model="gpt-4", messages=messages, max_tokens=200)
        return response.choices[0].message["content"]
    except Exception as e:
        logging.error(f"GPT error: {e}")
        return "Вибач, я не зрозумів. Спробуй інакше 🙏"

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    msg = data.get("message", "").strip()
    session_id = data.get("session_id", "default")
    logging.info(f"[{session_id}] {msg}")
    context = sessions.get(session_id, {"greeted": False, "confirm": None, "booking": None})
    msg_norm = normalize(msg)

    # 🧠 Small talk до витягу міст
    if any(kw in msg_norm for kw in ["як справи", "как дела", "що ти", "ти хто", "бот", "диспетчер"]):
        return jsonify({"reply": gpt_reply(msg)})

    if not context["greeted"]:
        context["greeted"] = True
        sessions[session_id] = context
        return jsonify({"reply": "Привіт! Я диспетчер Bus-Timel. Напишіть, звідки і куди хочете їхати 🚌"})

    # Підтвердження
    if msg.lower() in ["так", "да"] and context.get("confirm"):
        start = context["confirm"]["start"]
        end = context["confirm"]["end"]
        route = find_real_route(start, end)
        if route:
            link = f"https://bus-timel.com.ua/routes/{route['url_slug']}.html"
            reply = f"🚌 Маршрут: {start.capitalize()} → {end.capitalize()}\n"
            reply += f"💰 Ціна: {route.get('price', 'уточнюйте')} грн\n"
            if route.get("departure_times"):
                reply += f"⏰ Відправлення: {route['departure_times'][0]}\n"
            if route.get("arrival_times"):
                reply += f"🕓 Прибуття: {route['arrival_times'][0]}\n"
            reply += f"🔗 {link}\n"
            reply += "Щоб забронювати — напишіть ім’я та телефон."
            context["booking"] = {"start": start, "end": end, "pending": True}
            context["confirm"] = None
            sessions[session_id] = context
            return jsonify({"reply": reply})

    # Зворотній напрямок
    if msg.lower() in ["ні", "нет", "наоборот", "в обратном напрямку"] and context.get("confirm"):
        s, e = context["confirm"]["start"], context["confirm"]["end"]
        context["confirm"] = {"start": e, "end": s}
        sessions[session_id] = context
        return jsonify({"reply": f"Тоді, можливо, з {e.capitalize()} до {s.capitalize()}?", "confirm": context["confirm"]})

    # Ім’я + телефон
    if context.get("booking") and context["booking"].get("pending"):
        match = re.match(r"(.+?)\s*(\+?\d{10,12})$", msg)
        if match:
            name, phone = match.groups()
            b = context["booking"]
            send_email(name, phone, b["start"], b["end"])
            sessions[session_id] = {"greeted": True}
            return jsonify({"reply": f"✅ Дякуємо, {name}! Заявка прийнята. Очікуйте дзвінок ☎️"})
        else:
            return jsonify({"reply": "Будь ласка, надішліть ім’я та номер у форматі: Олег +380123456789"})

    # 🧹 Витяг міст з фільтрацією
    def extract_cities_filtered(text):
        words = normalize(text).split()
        found = []
        for word in words:
            city = match_city(word)
            if city and "-" not in city and city not in found:
                found.append(city)
        return found[:2]

    cities = extract_cities_filtered(msg)

    # Питання про час, прибуття, ціну
    if any(word in msg_norm for word in ["во сколько", "время", "відправлення", "коли", "выезд", "отправка"]):
        if len(cities) == 1:
            return jsonify({"reply": f"У яке місто ви хочете їхати з {cities[0].capitalize()}?"})
        elif len(cities) == 2:
            route = find_real_route(cities[0], cities[1])
            if route and route.get("departure_times"):
                return jsonify({"reply": f"⏰ Відправлення з {cities[0].capitalize()} до {cities[1].capitalize()} о {route['departure_times'][0]}"})

    if any(word in msg_norm for word in ["прибуття", "прибытие", "будет в"]):
        if len(cities) == 1:
            return jsonify({"reply": f"З якого міста ви хочете їхати до {cities[0].capitalize()}?"})
        elif len(cities) == 2:
            route = find_real_route(cities[0], cities[1])
            if route and route.get("arrival_times"):
                return jsonify({"reply": f"🕓 Прибуття до {cities[1].capitalize()} з {cities[0].capitalize()} о {route['arrival_times'][0]}"})

    if any(word in msg_norm for word in ["цена", "вартість", "коштує", "стоимость", "скільки"]):
        if len(cities) == 1:
            return jsonify({"reply": f"З якого міста ви хочете їхати до {cities[0].capitalize()}?"})
        elif len(cities) == 2:
            route = find_real_route(cities[0], cities[1])
            if route:
                return jsonify({"reply": f"💰 Вартість проїзду з {cities[0].capitalize()} до {cities[1].capitalize()}: {route.get('price', 'уточнюйте')} грн"})

    # Якщо 2 міста → підтвердження
    if len(cities) == 2:
        context["confirm"] = {"start": cities[0], "end": cities[1]}
        sessions[session_id] = context
        return jsonify({"reply": f"Ви маєте на увазі з {cities[0].capitalize()} до {cities[1].capitalize()}?", "confirm": context["confirm"]})

    # Якщо 1 місто → уточнення
    if len(cities) == 1:
        if re.search(r"\b(до|в|на|у)\b", msg):
            return jsonify({"reply": f"З якого міста ви хочете їхати до {cities[0].capitalize()}?"})
        else:
            return jsonify({"reply": f"У яке місто ви хочете їхати з {cities[0].capitalize()}?"})

    sessions[session_id] = context
    return jsonify({"reply": "Напишіть, будь ласка, звідки і куди хочете їхати. Я підкажу маршрут, ціну та час 🚌"})

@app.route("/")
def index():
    return "🤖 Bus-Timel Dispatcher Bot — online."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
