import os
import json
import re
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from thefuzz import process, fuzz
import logging

app = Flask(__name__)
CORS(app, resources={r"/chat": {"origins": "https://bus-timel.com.ua"}})

# Налаштування логування
logging.basicConfig(filename='bot.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Ініціалізація SQLite для заявок
conn = sqlite3.connect('bookings.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS bookings 
                 (id INTEGER PRIMARY KEY, session_id TEXT, name TEXT, phone TEXT, 
                  start_city TEXT, end_city TEXT, date TEXT, created_at TEXT)''')
conn.commit()

# Завантаження маршрутів із валідацією
try:
    with open("routes.json", "r", encoding="utf-8") as f:
        routes = json.load(f)
    # Перевірка структури routes.json
    for route in routes:
        if not all(key in route for key in ["start", "end", "duration"]):
            raise ValueError(f"Некоректний маршрут: {route}")
except Exception as e:
    logging.error(f"Помилка завантаження routes.json: {e}")
    routes = []

# Словники для міст (той самий CITY_FORMS із твого коду, скорочений для прикладу)
CITY_FORMS = {
    "київ": ["київ", "київа", "київе", "київом", "київу"],
    "львів": ["львів", "львіва", "львіве", "львівом", "львіву"],
    "вінниця": ["вінницю", "вінниця", "вінниці"],
    # ... решта міст із твого словника
}

city_aliases = {
    "днепр": "дніпро", "умань": "умань", "львов": "львів", "винница": "вінниця",
    "kiev": "київ", "lviv": "львів", "odessa": "одеса"
}

def normalize(text):
    text = re.sub(r"[’']", "", text.lower()).strip()
    return re.sub(r"\s+", " ", text)

def match_city(word):
    norm = normalize(word)
    for base, forms in CITY_FORMS.items():
        if norm in forms:
            return base
    # Fuzzy-пошук із нижчим порогом і перевіркою кількох варіантів
    results = process.extractBests(norm, list(CITY_FORMS.keys()), scorer=fuzz.token_sort_ratio, score_cutoff=70)
    return results[0][0] if results else None

def extract_cities_and_date(text):
    words = normalize(text).split()
    cities = []
    date = None
    time = None
    
    # Розпізнавання дати й часу
    date_patterns = [r"(\d{1,2}[\./-]\d{1,2}(?:[\./-]\d{2,4})?)", r"(сьогодні|завтра|післязавтра)"]
    time_pattern = r"(\d{1,2}(?::\d{2})?\s*(?:год|ранку|вечора)?)"
    
    for word in words:
        if not date and any(re.match(p, word) for p in date_patterns):
            date = word
        elif not time and re.match(time_pattern, word):
            time = word
        else:
            city = match_city(word)
            if city and city not in cities:
                cities.append(city)
    
    return cities[:2], date, time

def route_link(start, end, date=None):
    url = f"https://bus-timel.com.ua/routes/{start.replace(' ', '-')}-{end.replace(' ', '-')}"
    if date:
        url += f"/{date}"
    return url

def find_real_route(start, end, date=None, time=None):
    matching_routes = []
    for route in routes:
        all_points = [route["start"]] + [s["city"] for s in route.get("stops", [])] + [route["end"]]
        if start in all_points and end in all_points and all_points.index(start) < all_points.index(end):
            if date or time:
                departure_times = route.get("departure_times", [])
                if time and not any(t.startswith(time.split()[0]) for t in departure_times):
                    continue
            matching_routes.append((route, all_points))
    return matching_routes[0] if matching_routes else (None, [])

def extract_price(route, end):
    if route["end"].lower() == end:
        return route.get("price", "Уточнюйте")
    for s in route.get("stops", []):
        if s["city"].lower() == end and s.get("price", "").replace(" ", "").isdigit():
            return s["price"]
    return "Уточнюйте"

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.json
        if not data or "message" not in data:
            return jsonify({"reply": "Будь ласка, вкажіть запит."}), 400
        
        msg_raw = data.get("message", "")
        session_id = data.get("session_id", "default")
        msg = normalize(msg_raw)
        logging.info(f"Session {session_id}: {msg_raw}")

        # Ініціалізація сесії в SQLite
        cursor.execute("SELECT context FROM bookings WHERE session_id = ? ORDER BY created_at DESC LIMIT 1", (session_id,))
        session = cursor.fetchone()
        context = json.loads(session[0]) if session else {"greeted": False, "confirm": None, "booking": None}

        if not context["greeted"]:
            context["greeted"] = True
            cursor.execute("INSERT INTO bookings (session_id, context, created_at) VALUES (?, ?, ?)",
                         (session_id, json.dumps(context), datetime.now().isoformat()))
            conn.commit()
            return jsonify({"reply": "Вітаю! Я диспетчер Bus-Timel. Напишіть, звідки і куди ви хочете їхати."})

        # Обробка бронювання
        if context.get("booking"):
            if msg.lower() in ["так", "да"]:
                name_phone = context["booking"].get("pending_data", {})
                if name_phone:
                    cursor.execute("""INSERT INTO bookings (session_id, name, phone, start_city, end_city, date, created_at)
                                  VALUES (?, ?, ?, ?, ?, ?, ?)""",
                                 (session_id, name_phone.get("name"), name_phone.get("phone"),
                                  context["booking"]["start"], context["booking"]["end"],
                                  context["booking"].get("date"), datetime.now().isoformat()))
                    conn.commit()
                    context["booking"] = None
                    cursor.execute("UPDATE bookings SET context = ? WHERE session_id = ?",
                                 (json.dumps(context), session_id))
                    conn.commit()
                    return jsonify({"reply": "Заявку на бронювання успішно прийнято! Ми зв’яжемося з вами."})
            else:
                context["booking"] = None
                cursor.execute("UPDATE bookings SET context = ? WHERE session_id = ?",
                             (json.dumps(context), session_id))
                conn.commit()
                return jsonify({"reply": "Бронювання скасовано. Напишіть, звідки і куди ви хочете їхати."})

        # Обробка підтвердження маршруту
        if msg.lower() in ["так", "да"] and context["confirm"]:
            start, end, date, time = context["confirm"]
            context["confirm"] = None
            route, points = find_real_route(start, end, date, time)
            if route:
                i1 = points.index(start)
                i2 = points.index(end)
                price = extract_price(route, end)
                link = route_link(start, end, date)
                reply = f"🚌 <b>Маршрут:</b> {start.capitalize()} → {end.capitalize()}\n"
                reply += f"💰 <b>Ціна:</b> {price} грн\n"
                reply += f"⏳ <b>Тривалість:</b> {route.get('duration', '—')}\n"
                if route.get("departure_times"):
                    reply += f"⏰ <b>Відправлення:</b> {route['departure_times'][0]}\n"
                if route.get("arrival_times"):
                    reply += f"🕓 <b>Прибуття:</b> {route['arrival_times'][0]}\n"
                if i2 > i1 + 1:
                    reply += f"🗺️ <b>Зупинки:</b> {' → '.join(points[i1+1:i2])}\n"
                reply += f"🔗 <a href='{link}'>Переглянути маршрут</a>\n"
                reply += "📝 Хочете забронювати? Напишіть ваше ім’я та телефон."
                context["booking"] = {"start": start, "end": end, "date": date}
                cursor.execute("UPDATE bookings SET context = ? WHERE session_id = ?",
                             (json.dumps(context), session_id))
                conn.commit()
                return jsonify({"reply": reply, "html": True})
            else:
                return jsonify({"reply": "Маршрут не знайдено. Уточніть, будь ласка, ще раз."})

        if msg.lower() in ["ні", "нет", "наоборот", "в обратном напрямку", "в обратном направлении"] and context["confirm"]:
            s, e, d, t = context["confirm"]
            context["confirm"] = (e, s, d, t)
            cursor.execute("UPDATE bookings SET context = ? WHERE session_id = ?",
                         (json.dumps(context), session_id))
            conn.commit()
            return jsonify({"reply": f"Тоді, можливо, з {e.capitalize()} до {s.capitalize()}?",
                           "confirm": {"start": e, "end": s, "date": d, "time": t}})

        # Обробка заявки на бронювання
        if context.get("booking") and context["booking"].get("pending"):
            name_phone = re.match(r"(.+?)\s*(\+?\d{10,12})$", msg)
            if name_phone:
                name, phone = name_phone.groups()
                context["booking"]["pending_data"] = {"name": name, "phone": phone}
                cursor.execute("UPDATE bookings SET context = ? WHERE session_id = ?",
                             (json.dumps(context), session_id))
                conn.commit()
                return jsonify({"reply": f"Підтвердіть бронювання для {name} ({phone}): так чи ні?"})
            else:
                return jsonify({"reply": "Будь ласка, вкажіть ім’я та телефон у форматі: Ім’я +380123456789"})

        # Розпізнавання міст, дати й часу
        cities, date, time = extract_cities_and_date(msg)
        if len(cities) == 2:
            context["confirm"] = (cities[0], cities[1], date, time)
            cursor.execute("UPDATE bookings SET context = ? WHERE session_id = ?",
                         (json.dumps(context), session_id))
            conn.commit()
            reply = f"Ви маєте на увазі з {cities[0].capitalize()} до {cities[1].capitalize()}?"
            if date:
                reply += f" Дата: {date}"
            if time:
                reply += f" Час: {time}"
            return jsonify({"reply": reply, "confirm": {"start": cities[0], "end": cities[1], "date": date, "time": time}})
        elif len(cities) == 1:
            return jsonify({"reply": f"З якого міста ви хочете їхати до {cities[0].capitalize()}?"})
        else:
            # Обробка інших запитів
            if "всі маршрути" in msg or "все маршруты" in msg:
                city = next((match_city(word) for word in msg.split() if match_city(word)), None)
                if city:
                    reply = f"Доступні маршрути з {city.capitalize()}:\n"
                    for route in routes:
                        if route["start"].lower() == city:
                            link = route_link(route["start"], route["end"])
                            reply += f"- {route['end'].capitalize()} ({route.get('duration', '—')}, {route.get('price', 'Уточнюйте')} грн) <a href='{link}'>Деталі</a>\n"
                    return jsonify({"reply": reply, "html": True}) if reply != f"Доступні маршрути з {city.capitalize()}:\n" else jsonify({"reply": f"Маршрутів із {city.capitalize()} не знайдено."})
            return jsonify({"reply": "Напишіть, будь ласка, з якого міста і куди ви хочете їхати."})

    except Exception as e:
        logging.error(f"Помилка в /chat: {e}")
        return jsonify({"reply": "Вибачте, сталася помилка. Спробуйте ще раз."}), 500

@app.route("/suggest_cities", methods=["POST"])
def suggest_cities():
    try:
        data = request.json
        query = normalize(data.get("query", ""))
        if not query:
            return jsonify({"suggestions": []})
        
        suggestions = process.extractBests(query, list(CITY_FORMS.keys()), 
                                         scorer=fuzz.partial_ratio, score_cutoff=70, limit=5)
        return jsonify({"suggestions": [s[0].capitalize() for s in suggestions]})
    except Exception as e:
        logging.error(f"Помилка в /suggest_cities: {e}")
        return jsonify({"suggestions": []}), 500

@app.route("/")
def index():
    return "Bus-Timel Enhanced Bot"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
