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

try:
    from city_forms import CITY_FORMS
except ImportError:
    logging.warning("Файл city_forms.py не знайдено або CITY_FORMS не визначено. Розпізнавання міст може бути обмеженим.")
    CITY_FORMS = {}

app = Flask(__name__)
CORS(app, resources={r"/chat": {"origins": [
    "https://bus-timel.com.ua",
    "http://localhost:8080"
]}})

logging.basicConfig(filename='bot.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
sessions = {}

try:
    with open("routes.json", encoding="utf-8") as f:
        data = json.load(f)
        routes_data = data["routes"]
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
    norm_word = normalize(word_to_match)
    if not norm_word:
        return None
    for base_form, forms_list in CITY_FORMS.items():
        if norm_word in [normalize(f) for f in forms_list]:
            return base_form
    all_base_city_forms = list(CITY_FORMS.keys())
    if not all_base_city_forms:
        return None
    result = process.extractOne(norm_word, all_base_city_forms, scorer=fuzz.WRatio, score_cutoff=80)
    return result[0] if result else None

def extract_cities_from_text_with_order_hint(text_norm_full_phrase):
    """
    Витягує до двох міст, намагаючись врахувати порядок за ключовими словами "з" / "в/до/на".
    Повертає словник {"start": city1, "end": city2} або {"single_city": city, "type": "destination/origin/unknown"}
    """
    # Спроба знайти "з X до/в/на Y"
    # Зверніть увагу: [\w'-]+(?:\s+[\w'-]+)* дозволяє багатослівні назви міст
    match_from_to = re.search(r"(?:з|из)\s+([\w'-]+(?:\s+[\w'-]+)*)\s+(?:до|в|на)\s+([\w'-]+(?:\s+[\w'-]+)*)", text_norm_full_phrase, re.IGNORECASE)
    if match_from_to:
        start_candidate_str = match_from_to.group(1).strip()
        end_candidate_str = match_from_to.group(2).strip()
        start_city = match_city(start_candidate_str)
        end_city = match_city(end_candidate_str)
        if start_city and end_city and start_city != end_city:
            return {"start": start_city, "end": end_city, "ordered": True}

    # Спроба знайти "в/до/на Y з X"
    match_to_from = re.search(r"(?:в|на|до)\s+([\w'-]+(?:\s+[\w'-]+)*)\s+(?:з|из)\s+([\w'-]+(?:\s+[\w'-]+)*)", text_norm_full_phrase, re.IGNORECASE)
    if match_to_from:
        end_candidate_str = match_to_from.group(1).strip()
        start_candidate_str = match_to_from.group(2).strip()
        start_city = match_city(start_candidate_str)
        end_city = match_city(end_candidate_str)
        if start_city and end_city and start_city != end_city:
            return {"start": start_city, "end": end_city, "ordered": True}

    # Якщо не знайдено чітких пар з прийменниками, використовуємо попередню логіку
    words = text_norm_full_phrase.split()
    found_cities_list = []
    for word in words: # Проста ітерація по словах
        city = match_city(word)
        if city and city not in found_cities_list:
            found_cities_list.append(city)
    
    if len(found_cities_list) == 2:
        # Порядок не визначено, повертаємо як є, можливо знадобиться уточнення
        return {"start": found_cities_list[0], "end": found_cities_list[1], "ordered": False}
    elif len(found_cities_list) == 1:
        # Визначаємо тип одного міста
        city_name = found_cities_list[0]
        if any(kw + city_name in text_norm_full_phrase for kw in ["в ", "на ", "до "]):
            return {"single_city": city_name, "type": "destination"}
        elif any(kw + city_name in text_norm_full_phrase for kw in ["з ", "из "]):
            return {"single_city": city_name, "type": "origin"}
        else: # Якщо місто згадується без явних прийменників напрямку
            return {"single_city": city_name, "type": "unknown"}
            
    return None


def find_route_segments(user_start_city_norm, user_end_city_norm):
    found_segments = []
    for route_entry in routes_data:
        stops = route_entry.get("stops", [])
        if not stops:
            continue
        stop_cities_uk_norm = [normalize(s.get("city", {}).get("uk")) for s in stops]
        try:
            start_index_in_route = stop_cities_uk_norm.index(user_start_city_norm)
            end_index_in_route = stop_cities_uk_norm.index(user_end_city_norm)
            if start_index_in_route < end_index_in_route:
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
                    "original_route_data": route_entry
                }
                found_segments.append(segment_detail)
        except ValueError:
            continue
        except Exception as e:
            logging.error(f"Помилка при обробці маршруту {route_entry.get('route_name', {}).get('uk', 'N/A')}: {e}")
            continue
    return found_segments

def send_email(name, phone, start, end, date_str=None, route_name_str=""):
    email_user = os.environ.get("EMAIL_USER")
    email_pass = os.environ.get("EMAIL_PASS")
    recipient_email = "bustimelll@gmail.com"
    if not email_user or not email_pass:
        logging.error("❌ Email credentials (EMAIL_USER, EMAIL_PASS) не налаштовані.")
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
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if not openai_api_key or openai_api_key == "GPT_KEY_HERE": # Перевірка на плейсхолдер
        logging.error("❌ Ключ API OpenAI (OPENAI_API_KEY) не налаштовано або використовується плейсхолдер.")
        return "На жаль, я зараз не можу обробити ваш запит через технічну проблему. Спробуйте пізніше. 🙏"
    openai.api_key = openai_api_key
    messages_to_send = [
        {"role": "system", "content": "Ти ввічливий диспетчер пасажирських перевезень компанії Bus-Timel. Відповідай українською мовою, чітко, лаконічно та допомагай знайти інформацію про маршрути або забронювати квиток."},
        {"role": "user", "content": prompt_text}
    ]
    try:
        response = openai.ChatCompletion.create(model="gpt-4", messages=messages_to_send, max_tokens=200)
        reply_content = response.choices[0].message["content"]
        return reply_content
    except Exception as e:
        logging.error(f"❌ Помилка GPT: {e}")
        return "На жаль, мій помічник GPT зараз недоступний. Спробуйте, будь ласка, конкретизувати ваш запит щодо маршруту."

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    # ВАЖЛИВО: Фронтенд має надсилати УНІКАЛЬНИЙ session_id для кожної нової розмови!
    session_id = data.get("session_id", f"default_session_{datetime.now().timestamp()}") 

    if not user_message:
        return jsonify({"reply": "Будь ласка, напишіть щось."})

    logging.info(f"[{session_id}] Отримано: '{user_message}'")
    
    context = sessions.setdefault(session_id, {
        "greeted": False, "confirm_pending": None, 
        "booking_details": None, "partial_city": None, "chat_history": []
    })
    
    context["chat_history"].append({"role": "user", "content": user_message})
    user_message_norm = normalize(user_message)
    reply_text = ""

    # --- 1. Обробка стану бронювання (очікування контактів) ---
    if context.get("booking_details") and context["booking_details"].get("pending_contact_info"):
        match_contact = re.match(r"(.+?)\s*(\+?\d{10,13})$", user_message.strip())
        if match_contact:
            name, phone = match_contact.groups()
            name = name.strip()
            booking_info = context["booking_details"]
            email_sent = send_email(name, phone, booking_info["departure_city_uk"], booking_info["arrival_city_uk"], 
                                    date_str=booking_info.get("date_str", "не вказано"), 
                                    route_name_str=booking_info.get("route_name_uk", ""))
            if email_sent:
                reply_text = f"✅ Дякуємо, {name}! Ваша заявка на маршрут {booking_info['departure_city_uk']} - {booking_info['arrival_city_uk']} прийнята. Очікуйте на дзвінок оператора ☎️"
                sessions[session_id] = {"greeted": True, "chat_history": context["chat_history"]} # Скидання стану, залишаємо історію
            else:
                reply_text = "На жаль, не вдалося відправити вашу заявку. Будь ласка, спробуйте пізніше або зв'яжіться з нами напряму."
            context["chat_history"].append({"role": "assistant", "content": reply_text})
            sessions[session_id] = context # Зберегти оновлений context
            return jsonify({"reply": reply_text})
        else:
            reply_text = "Будь ласка, надішліть ваше ім’я та номер телефону у форматі: Олег +380123456789"
            context["chat_history"].append({"role": "assistant", "content": reply_text})
            sessions[session_id] = context
            return jsonify({"reply": reply_text})

    # --- 2. Обробка стану підтвердження маршруту ---
    if context.get("confirm_pending"):
        pending_data = context["confirm_pending"]
        pending_details = pending_data["details"]
        
        if user_message_norm in ["так", "да", "підтверджую", "підходить"]:
            context["booking_details"] = {**pending_details, "pending_contact_info": True}
            context["confirm_pending"] = None
            
            route_info_str = (
                f"🚌 Маршрут: {pending_details['departure_city_uk']} → {pending_details['arrival_city_uk']} ({pending_details['route_name_uk']})\n"
                f"💰 Ціна: {pending_details['price']}{' грн' if pending_details['price'] != 'уточнюйте' else ''}\n"
                f"📅 Частота: {pending_details['frequency']}\n"
                f"⏰ Відправлення з {pending_details['departure_city_uk']} ({pending_details.get('departure_address_uk') or 'N/A'}): {pending_details['departure_time']}\n"
                f"🕓 Прибуття до {pending_details['arrival_city_uk']} ({pending_details.get('arrival_address_uk') or 'N/A'}): {pending_details['arrival_time']}\n"
            )
            if pending_details.get("url_slug"):
                 route_info_str += f"🔗 https://bus-timel.com.ua/routes/{pending_details['url_slug']}.html\n"
            
            reply_text = f"{route_info_str}Для завершення бронювання, будь ласка, напишіть ваше ім'я та номер телефону (наприклад, Олег +380XXXXXXXXX)."
            context["chat_history"].append({"role": "assistant", "content": reply_text})
            sessions[session_id] = context
            return jsonify({"reply": reply_text})
        
        elif user_message_norm in ["ні", "нет", "скасувати", "інший", "не підходить"]:
            reply_text = "Зрозуміло. Спробуйте, будь ласка, сформулювати ваш запит інакше, або вкажіть інші міста."
            context["confirm_pending"] = None
            context["partial_city"] = None # Скидаємо також часткове місто
            context["chat_history"].append({"role": "assistant", "content": reply_text})
            sessions[session_id] = context
            return jsonify({"reply": reply_text})

        elif user_message_norm in ["навпаки", "наоборот", "зворотній", "в зворотньому напрямку"] and pending_details:
            original_start = normalize(pending_details["departure_city_uk"])
            original_end = normalize(pending_details["arrival_city_uk"])
            
            # Готуємо для нового пошуку у зворотньому напрямку
            user_message = f"з {original_end} до {original_start}" # Це буде оброблено нижче
            user_message_norm = normalize(user_message)
            context["confirm_pending"] = None
            context["partial_city"] = None 
            logging.info(f"[{session_id}] Користувач попросив зворотній напрямок. Новий запит: {user_message}")
            # Далі код продовжить обробку з новим user_message_norm
        else:
            reply_text = f"Будь ласка, підтвердіть маршрут: {pending_details['departure_city_uk']} → {pending_details['arrival_city_uk']} ({pending_details['route_name_uk']}), відправлення о {pending_details['departure_time']}. Напишіть 'так' або 'ні'."
            context["chat_history"].append({"role": "assistant", "content": reply_text})
            sessions[session_id] = context # Зберігаємо контекст, хоча він не змінився
            return jsonify({"reply": reply_text})

    # --- 3. Small talk та загальні питання ---
    small_talk_keywords = ["як справи", "привіт", "дякую", "спасибі", "пока", "бувай", "що ти", "ти хто", "бот", "диспетчер", "як забронювати"]
    # Перевіряємо, чи це не запит на бронювання, який має йти до GPT, якщо не в стані бронювання
    is_route_related_request = extract_cities_from_text_with_order_hint(user_message_norm) or \
                               any(kw in user_message_norm for kw in ["маршрути з", "рейси з"])
                               
    if not is_route_related_request and any(keyword in user_message_norm for keyword in small_talk_keywords):
        reply_text = gpt_reply(user_message, session_id)
        context["chat_history"].append({"role": "assistant", "content": reply_text})
        sessions[session_id] = context
        return jsonify({"reply": reply_text})

    # --- 4. Привітання, якщо ще не віталися ---
    if not context.get("greeted"):
        reply_text = "Привіт! Я диспетчер Bus-Timel. Напишіть, звідки, куди та (за бажанням) коли хочете їхати 🚌"
        context["greeted"] = True
        context["chat_history"].append({"role": "assistant", "content": reply_text})
        sessions[session_id] = context
        return jsonify({"reply": reply_text})
    
    # --- 5. Основна логіка пошуку маршрутів ---
    # Використовуємо нову функцію для кращого розпізнавання
    extracted_proposal = extract_cities_from_text_with_order_hint(user_message_norm)
    logging.info(f"[{session_id}] Результат extract_route_proposal_from_text: {extracted_proposal}")

    if extracted_proposal and "start" in extracted_proposal and "end" in extracted_proposal:
        start_city_norm = extracted_proposal["start"]
        end_city_norm = extracted_proposal["end"]
        
        logging.info(f"[{session_id}] Шукаю сегменти для: {start_city_norm} -> {end_city_norm}")
        found_segments = find_route_segments(start_city_norm, end_city_norm)
        context["partial_city"] = None # Очищаємо, оскільки відбувся пошук по парі

        if found_segments:
            if len(found_segments) == 1:
                segment = found_segments[0]
                reply_text = (f"Знайдено рейс: {segment['route_name_uk']}.\n"
                              f"Відправлення з {segment['departure_city_uk']} ({segment.get('departure_address_uk') or 'N/A'}) о {segment['departure_time']}.\n"
                              f"Прибуття до {segment['arrival_city_uk']} ({segment.get('arrival_address_uk') or 'N/A'}) о {segment['arrival_time']}.\n"
                              f"Ціна: {segment['price']}{' грн' if segment['price'] != 'уточнюйте' else ''}. Частота: {segment['frequency']}.\n")
                if segment.get("url_slug"):
                     reply_text += f"Детальніше: https://bus-timel.com.ua/routes/{segment['url_slug']}.html\n"
                reply_text += f"Підходить цей варіант? (так/ні)"
                context["confirm_pending"] = {"details": segment, "alternatives_count": len(found_segments)}
            else:
                reply_text = f"Знайдено декілька варіантів з {start_city_norm.capitalize()} до {end_city_norm.capitalize()}:\n\n"
                for i, segment in enumerate(found_segments[:3]):
                    reply_text += (
                        f"{i+1}. Рейс: {segment['route_name_uk']}\n"
                        f"   Відправлення з {segment['departure_city_uk']} о {segment['departure_time']}\n"
                        f"   Прибуття до {segment['arrival_city_uk']} о {segment['arrival_time']}\n"
                        f"   Ціна: {segment['price']}{' грн' if segment['price'] != 'уточнюйте' else ''}. Частота: {segment['frequency']}\n\n"
                    )
                if len(found_segments) > 3: reply_text += "... та інші.\n"
                reply_text += "Будь ласка, виберіть номер варіанту або напишіть 'інший', якщо жоден не підходить."
                context["confirm_pending"] = {"details": found_segments[0], "alternatives": found_segments, "current_index": 0, "is_list": True} # Зберігаємо для вибору
        else:
            reply_text = f"На жаль, прямих рейсів з {start_city_norm.capitalize()} до {end_city_norm.capitalize()} не знайдено."
            # Тут можна додати GPT fallback, якщо потрібно
            # gpt_prompt = f"Допоможи знайти маршрут з {start_city_norm.capitalize()} до {end_city_norm.capitalize()}, враховуючи, що прямих рейсів немає."
            # reply_text += "\n" + gpt_reply(gpt_prompt, session_id)

    elif extracted_proposal and "single_city" in extracted_proposal:
        current_city_extracted = extracted_proposal["single_city"]
        city_type = extracted_proposal["type"] # "origin", "destination", or "unknown"

        if context.get("partial_city") and context["partial_city"] != current_city_extracted:
            # Є перше місто в контексті, і зараз отримали друге
            if city_type == "destination" or (city_type == "unknown" and context.get("partial_city_type") == "origin"):
                start_city_norm = context["partial_city"]
                end_city_norm = current_city_extracted
            elif city_type == "origin" or (city_type == "unknown" and context.get("partial_city_type") == "destination"):
                start_city_norm = current_city_extracted
                end_city_norm = context["partial_city"]
            else: # Не вдалося чітко визначити напрямок
                reply_text = f"Маємо міста {context['partial_city'].capitalize()} та {current_city_extracted.capitalize()}. Уточніть, будь ласка, звідки куди (наприклад, 'з {context['partial_city'].capitalize()} до {current_city_extracted.capitalize()}')."
                context["chat_history"].append({"role": "assistant", "content": reply_text})
                sessions[session_id] = context
                return jsonify({"reply": reply_text})

            logging.info(f"[{session_id}] Формую пару з контексту: {start_city_norm} -> {end_city_norm}")
            found_segments = find_route_segments(start_city_norm, end_city_norm)
            context["partial_city"] = None # Очищаємо
            context["partial_city_type"] = None
             # ... (логіка для обробки found_segments, аналогічно до len(cities) == 2)
            if found_segments: # Копіпаста з блоку len(cities) == 2
                if len(found_segments) == 1:
                    segment = found_segments[0]
                    reply_text = (f"Знайдено рейс: {segment['route_name_uk']}.\n"
                                  f"Відправлення з {segment['departure_city_uk']} ({segment.get('departure_address_uk') or 'N/A'}) о {segment['departure_time']}.\n"
                                  f"Прибуття до {segment['arrival_city_uk']} ({segment.get('arrival_address_uk') or 'N/A'}) о {segment['arrival_time']}.\n"
                                  f"Ціна: {segment['price']}{' грн' if segment['price'] != 'уточнюйте' else ''}. Частота: {segment['frequency']}.\n")
                    if segment.get("url_slug"):
                        reply_text += f"Детальніше: https://bus-timel.com.ua/routes/{segment['url_slug']}.html\n"
                    reply_text += f"Підходить цей варіант? (так/ні)"
                    context["confirm_pending"] = {"details": segment, "alternatives_count": len(found_segments)}
                else:
                    reply_text = f"Знайдено декілька варіантів з {start_city_norm.capitalize()} до {end_city_norm.capitalize()}:\n\n"
                    for i, segment in enumerate(found_segments[:3]): # Обмежимо показ першими 3
                        reply_text += (
                            f"{i+1}. Рейс: {segment['route_name_uk']}\n"
                            f"   Відправлення з {segment['departure_city_uk']} о {segment['departure_time']}\n"
                            f"   Прибуття до {segment['arrival_city_uk']} о {segment['arrival_time']}\n"
                            f"   Ціна: {segment['price']}{' грн' if segment['price'] != 'уточнюйте' else ''}. Частота: {segment['frequency']}\n\n"
                        )
                    if len(found_segments) > 3: reply_text += "... та інші.\n"
                    reply_text += "Будь ласка, виберіть номер варіанту або напишіть 'інший', якщо жоден не підходить."
                    context["confirm_pending"] = {"details": found_segments[0], "alternatives": found_segments, "current_index": 0, "is_list": True}
            else:
                reply_text = f"На жаль, прямих рейсів з {start_city_norm.capitalize()} до {end_city_norm.capitalize()} не знайдено."

        else: # Перше місто вказано, або те саме місто повторюється
            context["partial_city"] = current_city_extracted
            context["partial_city_type"] = city_type # Зберігаємо тип (origin/destination/unknown)
            if city_type == "destination":
                reply_text = f"Добре, їдемо до {current_city_extracted.capitalize()}. А звідки?"
            elif city_type == "origin":
                reply_text = f"Добре, відправляємось з {current_city_extracted.capitalize()}. Куди прямуєте?"
            else: # type "unknown"
                reply_text = f"Знайшов місто {current_city_extracted.capitalize()}. Це місто відправлення чи прибуття? Або назвіть друге місто."
    
    # Спеціальна обробка для "рейси з {місто}"
    elif any(kw in user_message_norm for kw in ["маршрути з", "рейси з"]):
        city_name_for_listing = None
        # Видаляємо ключові слова і беремо перше розпізнане слово як місто
        temp_msg = user_message_norm.replace("маршрути з", "").replace("рейси з","").strip()
        potential_city_name = temp_msg.split()[0] if temp_msg.split() else None
        if potential_city_name:
            city_name_for_listing = match_city(potential_city_name)
        
        if city_name_for_listing:
            departing_routes_info = []
            for r_data in routes_data:
                if r_data["stops"] and normalize(r_data["stops"][0]["city"]["uk"]) == city_name_for_listing:
                    destination_city_name = r_data["stops"][-1]["city"]["uk"]
                    price = r_data.get("price", "ціна?")
                    departure_time = r_data["stops"][0].get("time", "N/A")
                    departing_routes_info.append(f"– До {destination_city_name.capitalize()} о {departure_time} (ціна: {price}{' грн' if price != 'ціна?' else ''})")
            
            if departing_routes_info:
                reply_text = f"📍 Доступні маршрути, що починаються з {city_name_for_listing.capitalize()}:\n" + "\n".join(departing_routes_info[:5])
                if len(departing_routes_info) > 5:
                    reply_text += "\n... та інші."
            else:
                reply_text = f"На жаль, маршрутів, що починаються з {city_name_for_listing.capitalize()}, не знайдено 🙁"
        else:
            reply_text = "Будь ласка, вкажіть місто, для якого шукати рейси, наприклад: 'рейси з Київ'"
        context["partial_city"] = None # Скидаємо, оскільки це окрема команда

    else: # Не розпізнано міст або відомих команд
        if context.get("partial_city"):
            # Якщо є часткове місто, і нове повідомлення не розпізнається як місто - можливо, це відповідь на питання "куди/звідки"
            # Або це просто незрозуміле повідомлення. Спробуємо GPT.
            logging.info(f"[{session_id}] Не розпізнано друге місто, є часткове: {context['partial_city']}. Запит до GPT: '{user_message}'")
            reply_text = gpt_reply(user_message, session_id)
            # Не скидаємо partial_city тут, раптом GPT допоможе уточнити
        else:
            logging.info(f"[{session_id}] Немає міст, немає часткового. Запит до GPT: '{user_message}'")
            reply_text = gpt_reply(user_message, session_id)

    if not reply_text: # Якщо жодна логіка не спрацювала (малоймовірно, але про всяк випадок)
        reply_text = "Перепрошую, я не зовсім зрозумів ваш запит. Спробуйте сформулювати його інакше, наприклад: 'З Києва до Львова' або 'рейси з Полтави'."

    context["chat_history"].append({"role": "assistant", "content": reply_text})
    sessions[session_id] = context
    
    logging.info(f"[{session_id}] Відповідь: {reply_text}")
    return jsonify({"reply": reply_text})

@app.route("/")
def index():
    return "🤖 Bus-Timel Dispatcher Bot — online."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
