# Bus-Timel Bot

Це OpenAI бот для сайту [bus-timel.com.ua](https://bus-timel.com.ua), який:
- відповідає на запитання про маршрути;
- формує посилання на сторінки маршрутів;
- приймає заявку (Ім’я, Телефон, Дата, Маршрут);
- надсилає заявку у Telegram.

## Розгортання на Render

1. Створи новий Web Service на Render.
2. Підключи GitHub репозиторій з цим проєктом.
3. Установи змінні середовища:
   - `OPENAI_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_USER_ID`

Після запуску бот буде доступний через `/chat` і `/request`.
