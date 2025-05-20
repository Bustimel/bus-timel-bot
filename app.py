import os
import json
import re
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

with open("routes.json", "r", encoding="utf-8") as f:
    routes = json.load(f)

# Синоніми міст (російська → українська)
city_aliases = {
    "днепр": "дніпро",
    "дніпр": "дніпро",
    "умань": "умань",
    "умани": "умань",
    "львов": "львів",
    "харьков": "харків",
    "винница": "вінниця",
    "кропивницкий": "кропивницький",
    "доброполье": "добропілля",
    "краматорск": "краматорськ",
    "словянск": "слов’янськ",
    "павлоград": "павлоград"
}

faq_keywords = {
    "багаж": "✅ Безкоштовно дозволено 1 валізу до 20 кг та ручну поклажу.",
    "тварин": "✅ Так, тварини дозволені у переносках. Повідомте водія.",
    "діти": "👶 Діти до 5 років — безкоштовно без окремого місця.",
    "оплата": "💳 Оплата при посадці або після бронювання з підтвердженням.",
    "перерва": "🚻 Санітарні перерви заплановані по маршруту.",
    "wifi": "📶 У більшості автобусів є Wi-Fi."
}

friendly_phrases = ["привіт", "як справи", "добрий день", "здравствуйте", "привет", "ок", "спасибо", "дякую", "нормально"]

last_session = {}

def normalize(text):
    text = re.sub(r"['’`]", "", text.lower().strip())
    text = re.sub(r"\s+", " ", text)
    for alias, real in city_aliases.items():
        if alias in text:
            text = text.replace(alias, real)
    return text

def extract_cities(text):
    all_cities = set()
    for r in routes:
        all_cities.add(normalize(r["start"]))
        all_cities.add(normalize(r["end"]))
    found = [c for c in all_cities if c in normalize(text)]
    return found

def route_link(start, end):
    s = normalize(start).replace(" ", "-")
    e = normalize(end).replace(" ", "-")
    return f"https://bus-timel.com.ua/routes/{s}-{e}.html"

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    message = data.get("message", "").lower()
    session_id = data.get("session_id", "default")

    msg = normalize(message)

    if msg in friendly_phrases:
        return jsonify({"reply": "Вітаю! Я диспетчер Bus-Timel. Напишіть, будь ласка, з якого міста і куди ви хочете їхати."})

    for keyword, answer in faq_keywords.items():
        if keyword in msg:
            return jsonify({"reply": answer})

    if msg in ["так", "да"] and session_id in last_session:
        start, end = last_session[session_id]
    elif msg in ["ні", "нет"] and session_id in last_session:
        del last_session[session_id]
        return jsonify({"reply": "Окей, тоді уточніть, будь ласка, напрямок ще раз."})
    else:
        cities = extract_cities(msg)
        if len(cities) == 2:
            start, end = cities[1], cities[0]
            last_session[session_id] = (start, end)
            return jsonify({
                "reply": f"Ви маєте на увазі з {start.capitalize()} до {end.capitalize()}?",
                "confirm": {"start": start, "end": end}
            })
        else:
            return jsonify({"reply": "Напишіть, будь ласка, звідки і куди ви хочете їхати (можна українською або російською)."})

    # Пошук маршруту
    for r in routes:
        if normalize(r["start"]) == start and normalize(r["end"]) == end:
            link = route_link(r["start"], r["end"])
            reply = f"🚌 <b>Маршрут:</b> {r['start']} → {r['end']}\n"
            reply += f"💰 <b>Ціна:</b> {r.get('price', 'Уточнюйте')} грн\n"
            reply += f"⏳ <b>Тривалість:</b> {r.get('duration', '—')}\n"
            if r.get("departure_times"):
                reply += f"⏰ <b>Відправлення:</b> {', '.join(r['departure_times'])}\n"
            if r.get("arrival_times"):
                reply += f"🕓 <b>Прибуття:</b> {', '.join(r['arrival_times'])}\n"
            reply += f"🔗 <a href='{link}'>Переглянути маршрут</a>\n📝 <a href='{link}'>Забронювати місце</a>"
            return jsonify({"reply": reply, "html": True})

    return jsonify({"reply": "Маршрут з цих міст не знайдено. Уточніть, будь ласка, ще раз."})

@app.route("/")
def index():
    return "Bus-Timel universal dispatcher bot."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
