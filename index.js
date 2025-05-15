
const { Telegraf } = require('telegraf');
const fs = require('fs');
const path = require('path');
require('dotenv').config();

const bot = new Telegraf(process.env.BOT_TOKEN);

// Загрузка маршрутов
let routes = [];
try {
  const rawData = fs.readFileSync(path.join(__dirname, 'routes.json'));
  routes = JSON.parse(rawData);
} catch (error) {
  console.error('Помилка при завантаженні routes.json:', error.message);
}

function normalizeText(text) {
  return text.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
}

function findRoute(from, to) {
  const nFrom = normalizeText(from);
  const nTo = normalizeText(to);
  return routes.find(route => {
    return (
      normalizeText(route.start) === nFrom &&
      normalizeText(route.end) === nTo
    );
  });
}

// Ответы на стандартные фразы
const greetings = ['привіт', 'привет', 'доброго дня', 'здравствуйте', 'хай'];
const fallback = 'Вибач, я ще вчуся. Напишіть звідки і куди хочете поїхати, або зателефонуйте: +38 075 375 00 00';

bot.start((ctx) =>
  ctx.reply(
    'Вітаю! Я диспетчер Bus–Timel.
Напишіть звідки і куди хочете поїхати, або поставте запитання.'
  )
);

bot.on('text', (ctx) => {
  const msg = ctx.message.text.trim().toLowerCase();

  if (greetings.includes(msg)) {
    ctx.reply('Вітаю! Я диспетчер Bus–Timel.
Напишіть звідки і куди хочете поїхати, або поставте запитання.');
    return;
  }

  const match = msg.match(/(?:з|із|from)?\s*(.+?)\s*(?:до|в|у|to)?\s*(.+)/i);
  if (match && match[1] && match[2]) {
    const route = findRoute(match[1], match[2]);
    if (route) {
      const duration = route.duration || 'уточнюйте';
      const price = route.price ? `${route.price} грн` : 'уточнюйте';
      const dep = route.departure_times ? route.departure_times.join(', ') : 'уточнюйте';
      const arr = route.arrival_times ? route.arrival_times.join(', ') : 'уточнюйте';
      ctx.reply(
        `Маршрут ${route.start} – ${route.end}:
Відправлення: ${dep}
Прибуття: ${arr}
Тривалість: ${duration}
Ціна: ${price}`
      );
    } else {
      ctx.reply('На жаль, не знайшов такий маршрут. Спробуй інше або зателефонуй: +38 075 375 00 00');
    }
  } else {
    ctx.reply(fallback);
  }
});

bot.launch();
console.log('Bus-Timel бот запущено!');
