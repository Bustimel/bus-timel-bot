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

# Припускаємо, що city_forms.py знаходиться поруч і містить CITY_FORMS
# Наприклад, CITY_FORMS = {"київ": ["київ", "kiev", "kyiv"], ...}
try:
    from city_forms import CITY_FORMS
except ImportError:
    logging.warning("Файл city_forms.py не знайдено або CITY_FORMS не визначено. Розпізнавання міст може бути обмеженим.")
    CITY_FORMS = {}


app = Flask(__name__)
CORS(app, resources={r"/chat": {"origins": [
    "https://bus-timel.com.ua",
    "http://localhost:8080" # Для локальної розробки
]}})

logging.basicConfig(filename='bot.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
sessions = {}

# Завантаження маршрутів
try:
    with open("routes.json", encoding="utf-8") as f:
        data = json.load(f)
        routes_data = data["routes"] # Перейменовано в routes_data, щоб не конфліктувати з модулем routes
except FileNotFoundError:
    logging.error("❌ Файл routes.json не знайдено.")
    routes_data = []
except json.JSONDecodeError as e:
    logging.error(f"❌ Помилка декодування routes.json: {e}")
    routes_data = []
except Exception as e:
    logging.error(f"❌ Загальна помилка завантаження маршрутів: {e}")
    routes_data = []

if not routes_data:
    logging.warning("⚠️ Список маршрутів порожній. Бот не зможе знаходити маршрути.")

def normalize(text):
    if not isinstance(text, str):
        return ""
    return re.sub(r"[’']", "", text.lower()).strip()

def match_city(word_to_match):
    """Знаходить базову форму міста для заданого слова."""
    norm_word = normalize(word_to_match)
    if not norm_word:
        return None

    for base_form, forms_list in CITY_FORMS.items():
        if norm_word in [normalize(f) for f in forms_list]:
            return base_form
    
    # Якщо точного співпадіння немає, використовуємо fuzzy matching
    # (Переконайся, що CITY_FORMS.keys() містить саме базові форми для кращого результату)
    # Краще мати список всіх базових форм окремо для process.extractOne
    all_base_city_forms = list(CITY_FORMS.keys())
    if not all_base_city_forms: # Якщо CITY_FORMS порожній
        return None

    result = process.extractOne(norm_word, all_base_city_forms, scorer=fuzz.WRatio, score_cutoff=80) # WRatio часто дає кращі результати
    return result[0] if result else None


def extract_cities_from_text(text):
    """Витягує до двох міст з тексту."""
    norm_text = normalize(text)
    words = norm_text.split()
    found_cities = []
    
    # Спробуємо знайти міста, що складаються з кількох слів (потрібно додати їх у CITY_FORMS)
    # Наприклад, "Біла Церква"
    # Ця частина потребує більш складного NLU, для простоти поки що залишимо пошук по словах
    
    for word in words:
        city = match_city(word)
        if city and city not in found_cities:
            found_cities.append(city)
            if len(found_cities) == 2:
                break
    return found_cities # Повертає список нормалізованих базових форм міст

def find_route_segments(user_start_city_norm, user_end_city_norm):
    """
    Шукає сегменти маршрутів, що відповідають запиту користувача.
    Повертає список деталей знайдених сегментів.
    """
    found_segments = []
    for route_entry in routes_data: # route_entry це один об'єкт маршруту з routes.json
        stops = route_entry.get("stops", [])
        if not stops:
            continue

        stop_cities_uk_norm = [normalize(s.get("city", {}).get("uk")) for s in stops]

        try:
            start_index_in_route = stop_cities_uk_norm.index(user_start_city_norm)
            end_index_in_route = stop_cities_uk_norm.index(user_end_city_norm)

            if start_index_in_route < end_index_in_route:
                # Користувацький маршрут є сегментом цього рейсу
                departure_stop_info = stops[start_index_in_route]
                arrival_stop_info = stops[end_index_in_route]

                segment_detail = {
                    "route_name_uk": route_entry.get("route_name", {}).get("uk", "N/A"),
                    "price": route_entry.get("price", "уточнюйте"),
                    "frequency": route_entry.get("frequency", "не вказано"),
                    "url_slug": route_entry.get("url_slug"),
                    "departure_city_uk": departure_stop_info.get("city", {}).get("uk", user_start_city_norm.capitalize()),
                    "departure_time": departure_stop_info.get("time", "N/A"),
                    "departure_address_uk": departure_stop_info.get("address", {}).get("uk", ""),
                    "arrival_city_uk": arrival_stop_info.get("city", {}).get("uk", user_end_city_norm.capitalize()),
                    "arrival_time": arrival_stop_info.get("time", "N/A"),
                    "arrival_address_uk": arrival_stop_info.get("address", {}).get("uk", ""),
                    "original_route_data": route_entry # Зберігаємо для можливого використання slug
                }
                found_segments.append(segment_detail)
        except ValueError:
            # Один із міст (або обидва) не знайдено у цьому конкретному рейсі
            continue
        except Exception as e:
            logging.error(f"Помилка при обробці маршруту {route_entry.get('route_name', {}).get('uk', 'N/A')}: {e}")
            continue
            
    return found_segments


def send_email(name, phone, start, end, date_str=None, route_name_str=""):
    """Надсилає email із заявкою."""
    email_user = os.environ.get("EMAIL_USER")
    email_pass = os.environ.get("EMAIL_PASS")
    recipient_email = "bustimelll@gmail.com" # Ваш email

    if not email_user or not email_pass:
        logging.error("❌ Email credentials (EMAIL_USER, EMAIL_PASS) не налаштовані в змінних середовища.")
        return False

    subject = f"Нова заявка з сайту Bus-Timel: {start} - {end}"
    body = (f"📥 Нова заявка:\n"
            f"Ім’я: {name}\n"
            f"Телефон: {phone}\n"
            f"Маршрут: {start.capitalize()} → {end.capitalize()}\n")
    if route_name_str:
        body += f"Назва рейсу: {route_name_str}\n"
    body += f"Дата: {date_str or 'не вказано'}"


    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = email_user
    msg["To"] = recipient_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_user, email_pass)
            server.send_message(msg)
        logging.info(f"✅ Email надіслано для заявки: {name}, {phone}, {start}-{end}")
        return True
    except Exception as e:
        logging.error(f"❌ Помилка надсилання Email: {e}")
        return False

def gpt_reply(prompt_text, session_id="default"):
    """Отримує відповідь від GPT."""
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if not openai_api_key:
        logging.error("❌ Ключ API OpenAI (OPENAI_API_KEY) не налаштовано.")
        return "Вибачте, сталася технічна помилка. Повторіть спробу пізніше. 🙏"

    openai.api_key = openai_api_key
    
    # Можна додати історію чату для кращого контексту
    # history = sessions.get(session_id, {}).get("chat_history", [])
    # messages_to_send = history + [{"role": "user", "content": prompt_text}]
    
    messages_to_send = [
        {"role": "system", "content": "Ти ввічливий диспетчер пасажирських перевезень компанії Bus-Timel. Відповідай українською мовою, чітко, лаконічно та допомагай знайти інформацію про маршрути або забронювати квиток."},
        {"role": "user", "content": prompt_text}
    ]

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4", # Або "gpt-3.5-turbo", якщо потрібно зекономити
            messages=messages_to_send,
            max_tokens=200
        )
        reply_content = response.choices[0].message["content"]
        # Додавання відповіді до історії (якщо потрібно)
        # sessions.setdefault(session_id, {}).setdefault("chat_history", []).append({"role": "assistant", "content": reply_content})
        return reply_content
    except Exception as e:
        logging.error(f"❌ Помилка GPT: {e}")
        return "На жаль, я зараз не можу обробити ваш запит через технічну проблему. Спробуйте пізніше. 🙏"

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    session_id = data.get("session_id", "default_session") # Важливо мати унікальний session_id

    if not user_message:
        return jsonify({"reply": "Будь ласка, напишіть щось."})

    logging.info(f"[{session_id}] Отримано: {user_message}")
    
    # Ініціалізація або отримання контексту сесії
    # Переконайтесь, що greeted скидається для нових сесій або після завершення бронювання
    context = sessions.get(session_id, {"greeted": False, "confirm_pending": None, "booking_details": None, "partial_city": None, "chat_history": []})
    
    # Додаємо повідомлення користувача до історії чату
    context.setdefault("chat_history", []).append({"role": "user", "content": user_message})

    user_message_norm = normalize(user_message)
    reply_text = ""

    # 1. Перевірка стану бронювання
    if context.get("booking_details") and context["booking_details"].get("pending_contact_info"):
        match_contact = re.match(r"(.+?)\s*(\+?\d{10,13})$", user_message.strip()) # Дозволяємо до 13 цифр для міжнародних
        if match_contact:
            name, phone = match_contact.groups()
            name = name.strip()
            booking_info = context["booking_details"]
            
            # Надсилання email
            email_sent = send_email(name, phone, booking_info["departure_city_uk"], booking_info["arrival_city_uk"], 
                                    date_str=booking_info.get("date_str", "не вказано"), 
                                    route_name_str=booking_info.get("route_name_uk", ""))
            
            if email_sent:
                reply_text = f"✅ Дякуємо, {name}! Ваша заявка на маршрут {booking_info['departure_city_uk']} - {booking_info['arrival_city_uk']} прийнята. Очікуйте на дзвінок оператора ☎️"
                # Скидання контексту після успішного бронювання
                sessions[session_id] = {"greeted": True, "chat_history": context["chat_history"]} # Зберігаємо історію, але скидаємо стан
            else:
                reply_text = "На жаль, не вдалося відправити вашу заявку. Будь ласка, спробуйте пізніше або зв'яжіться з нами напряму."
            return jsonify({"reply": reply_text})
        else:
            reply_text = "Будь ласка, надішліть ваше ім’я та номер телефону у форматі: Олег +380123456789"
            return jsonify({"reply": reply_text})

    # 2. Перевірка стану підтвердження маршруту
    if context.get("confirm_pending"):
        pending_details = context["confirm_pending"]["details"]
        if user_message_norm in ["так", "да", "підтверджую", "підходить"]:
            context["booking_details"] = {
                **pending_details, # Розпаковуємо всі деталі маршруту
                "pending_contact_info": True
            }
            context["confirm_pending"] = None # Очищаємо стан підтвердження
            
            route_info_str = (
                f"🚌 Маршрут: {pending_details['departure_city_uk']} → {pending_details['arrival_city_uk']} ({pending_details['route_name_uk']})\n"
                f"💰 Ціна: {pending_details['price']} грн\n"
                f"📅 Частота: {pending_details['frequency']}\n"
                f"⏰ Відправлення з {pending_details['departure_city_uk']} ({pending_details.get('departure_address_uk', 'N/A')}): {pending_details['departure_time']}\n"
                f"🕓 Прибуття до {pending_details['arrival_city_uk']} ({pending_details.get('arrival_address_uk', 'N/A')}): {pending_details['arrival_time']}\n"
            )
            if pending_details.get("url_slug"):
                 route_info_str += f"🔗 https://bus-timel.com.ua/routes/{pending_details['url_slug']}.html\n"
            
            reply_text = f"{route_info_str}Для завершення бронювання, будь ласка, напишіть ваше ім'я та номер телефону (наприклад, Олег +380XXXXXXXXX)."
            sessions[session_id] = context
            return jsonify({"reply": reply_text})
        
        elif user_message_norm in ["ні", "нет", "скасувати", "інший", "не підходить"]:
            # Якщо є альтернативні варіанти, можна їх запропонувати
            if context["confirm_pending"].get("alternatives_count", 0) > 1:
                reply_text = "Зрозуміло. Можливо, вас зацікавить інший варіант з попереднього списку? Або спробуйте уточнити запит."
            else:
                reply_text = "Зрозуміло. Спробуйте, будь ласка, сформулювати ваш запит інакше, або вкажіть інші міста."
            context["confirm_pending"] = None
            sessions[session_id] = context
            return jsonify({"reply": reply_text})
        
        elif user_message_norm in ["навпаки", "наоборот", "зворотній", "в зворотньому напрямку"] and pending_details:
            # Логіка для зворотнього напрямку
            original_start = normalize(pending_details["departure_city_uk"])
            original_end = normalize(pending_details["arrival_city_uk"])
            
            context["confirm_pending"] = None # Скидаємо попереднє підтвердження
            context["partial_city"] = None    # Скидаємо частково введене місто
            sessions[session_id] = context   # Зберігаємо зміни перед новим пошуком

            # Запускаємо пошук у зворотньому напрямку
            user_message_for_reverse = f"З {original_end} до {original_start}"
            # Це викличе основну логіку обробки міст нижче
            # Щоб уникнути рекурсії, просто модифікуємо user_message_norm і дозволяємо коду йти далі
            user_message_norm = normalize(user_message_for_reverse)
            # Очистимо cities, щоб extract_cities_from_text спрацював для нового запиту
            cities = []
            # Продовжуємо обробку з новим user_message_norm
        else:
            # Якщо відповідь нечітка, можна попросити уточнити або повторити підтвердження
            reply_text = f"Будь ласка, підтвердіть маршрут: {pending_details['departure_city_uk']} → {pending_details['arrival_city_uk']} ({pending_details['route_name_uk']}), відправлення о {pending_details['departure_time']}. Напишіть 'так' або 'ні'."
            return jsonify({"reply": reply_text})


    # 3. Small talk та загальні питання (можна розширити)
    small_talk_keywords = ["як справи", "привіт", "дякую", "спасибі", "пока", "бувай", "що ти", "ти хто", "бот", "диспетчер"]
    if any(keyword in user_message_norm for keyword in small_talk_keywords) and not extract_cities_from_text(user_message_norm):
        # Якщо це small talk і не містить назв міст (щоб не перебивати пошук маршруту)
        reply_text = gpt_reply(user_message, session_id)
        context.setdefault("chat_history", []).append({"role": "assistant", "content": reply_text})
        sessions[session_id] = context
        return jsonify({"reply": reply_text})

    # 4. Привітання, якщо ще не віталися
    if not context["greeted"]:
        reply_text = "Привіт! Я диспетчер Bus-Timel. Напишіть, звідки, куди та (за бажанням) коли хочете їхати 🚌"
        context["greeted"] = True
        context.setdefault("chat_history", []).append({"role": "assistant", "content": reply_text})
        sessions[session_id] = context
        return jsonify({"reply": reply_text})
    
    # 5. Основна логіка пошуку маршрутів
    cities = extract_cities_from_text(user_message_norm)

    if len(cities) == 2:
        start_city_norm, end_city_norm = cities[0], cities[1]
        
        if start_city_norm == end_city_norm:
            reply_text = "Будь ласка, вкажіть різні міста для відправлення та прибуття."
        else:
            logging.info(f"Шукаю сегменти: {start_city_norm} -> {end_city_norm}")
            found_segments = find_route_segments(start_city_norm, end_city_norm)

            if found_segments:
                if len(found_segments) == 1:
                    segment = found_segments[0]
                    reply_text = (f"Знайдено рейс: {segment['route_name_uk']}.\n"
                                  f"Відправлення з {segment['departure_city_uk']} ({segment.get('departure_address_uk', 'N/A')}) о {segment['departure_time']}.\n"
                                  f"Прибуття до {segment['arrival_city_uk']} ({segment.get('arrival_address_uk', 'N/A')}) о {segment['arrival_time']}.\n"
                                  f"Ціна: {segment['price']} грн. Частота: {segment['frequency']}.\n"
                                  f"Підходить цей варіант? (так/ні)")
                    if segment.get("url_slug"):
                         reply_text += f"\nДетальніше: https://bus-timel.com.ua/routes/{segment['url_slug']}.html"

                    context["confirm_pending"] = {"details": segment, "alternatives_count": len(found_segments)}
                else:
                    reply_text = f"Знайдено декілька варіантів з {start_city_norm.capitalize()} до {end_city_norm.capitalize()}:\n\n"
                    for i, segment in enumerate(found_segments[:3]): # Обмежимо показ першими 3
                        reply_text += (
                            f"{i+1}. Рейс: {segment['route_name_uk']}\n"
                            f"   Відправлення з {segment['departure_city_uk']} о {segment['departure_time']}\n"
                            f"   Прибуття до {segment['arrival_city_uk']} о {segment['arrival_time']}\n"
                            f"   Ціна: {segment['price']} грн. Частота: {segment['frequency']}\n\n"
                        )
                    reply_text += "Будь ласка, виберіть номер варіанту або напишіть 'інший', якщо жоден не підходить."
                    # Зберігаємо варіанти для вибору на наступному кроці (поки не реалізовано)
                    # context["route_options"] = found_segments 
            else:
                reply_text = f"На жаль, прямих рейсів з {start_city_norm.capitalize()} до {end_city_norm.capitalize()} не знайдено. Спробуйте уточнити запит або запитати GPT."
                # Можна додати опцію "Запитати GPT?"
                # if "запитати gpt" in user_message_norm or True: # Тимчасово завжди питаємо GPT
                #    gpt_prompt = f"Чи є автобусні маршрути з {start_city_norm.capitalize()} до {end_city_norm.capitalize()}? Якщо так, надай деталі. Якщо ні, запропонуй альтернативу."
                #    reply_text += "\n\n" + gpt_reply(gpt_prompt, session_id)

    elif len(cities) == 1:
        partial_city = cities[0]
        if context.get("partial_city") and context["partial_city"] != partial_city : # Якщо вже було одне місто і ввели друге
            # Це логіка для випадку, коли користувач вводить міста по одному.
            # Поточна extract_cities_from_text намагається знайти два міста одразу.
            # Для простоти, якщо введено одне місто, просто просимо друге.
            context["partial_city"] = partial_city
            reply_text = f"З {partial_city.capitalize()} куди бажаєте їхати? Напишіть, будь ласка, місто прибуття."
        else:
            context["partial_city"] = partial_city
            reply_text = f"Добре, місто відправлення {partial_city.capitalize()}. А куди прямуєте?"

    elif any(kw in user_message_norm for kw in ["маршрути з", "рейси з"]):
        city_match_for_listing = None
        words_in_msg = user_message_norm.replace("маршрути з", "").replace("рейси з","").strip().split()
        for word in words_in_msg:
            city_match_for_listing = match_city(word)
            if city_match_for_listing:
                break
        
        if city_match_for_listing:
            departing_routes = []
            for r_data in routes_data:
                if r_data["stops"] and normalize(r_data["stops"][0]["city"]["uk"]) == city_match_for_listing:
                    destination_city = r_data["stops"][-1]["city"]["uk"]
                    price = r_data.get("price", "ціна?")
                    departing_routes.append(f"– {destination_city.capitalize()} ({price} грн) час: {r_data['stops'][0]['time']}")
            
            if departing_routes:
                reply_text = f"📍 Доступні маршрути, що починаються з {city_match_for_listing.capitalize()}:\n" + "\n".join(departing_routes[:5])
                if len(departing_routes) > 5:
                    reply_text += "\n... та інші."
            else:
                reply_text = f"На жаль, маршрутів, що починаються з {city_match_for_listing.capitalize()}, не знайдено 🙁"
        else:
            reply_text = "Будь ласка, вкажіть місто, для якого шукати рейси, наприклад: 'рейси з Київ'"
            
    else: # Якщо не вдалося розпізнати міста або команду
        if not reply_text: # Якщо жодна з умов вище не спрацювала
             # Якщо не розпізнали міста і не було інших команд, передаємо GPT
            if context.get("greeted"): # Не відповідати GPT на перше "привіт"
                logging.info(f"Не вдалося розпізнати команду/міста: '{user_message}'. Передаю GPT.")
                reply_text = gpt_reply(user_message, session_id)
            else: # Якщо ще не віталися і прийшло незрозуміле повідомлення
                reply_text = "Привіт! Я диспетчер Bus-Timel. Напишіть, звідки і куди хочете їхати 🚌"
                context["greeted"] = True


    # Збереження контексту та історії
    context.setdefault("chat_history", []).append({"role": "assistant", "content": reply_text})
    sessions[session_id] = context
    
    logging.info(f"[{session_id}] Відповідь: {reply_text}")
    return jsonify({"reply": reply_text})

@app.route("/")
def index():
    return "🤖 Bus-Timel Dispatcher Bot — online."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # Для розробки можна увімкнути debug=True, але НЕ для продакшену!
    app.run(host="0.0.0.0", port=port, debug=False)
