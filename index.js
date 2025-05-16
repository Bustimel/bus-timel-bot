
const { Telegraf, session } = require('telegraf');
const fs = require('fs');
const stringSimilarity = require('string-similarity');

const bot = new Telegraf(process.env.BOT_TOKEN);
bot.use(session());

let routes = [];
try {
  const data = fs.readFileSync('./routes.json', 'utf8');
  routes = JSON.parse(data);
} catch (error) {
  console.error("Помилка завантаження маршруту:", error);
}

// --- КАНОНІЧНИЙ СПИСОК МІСТ ---
const allCities = new Set();
routes.forEach(route => {
  if (route.start) allCities.add(route.start.toLowerCase());
  if (route.end) allCities.add(route.end.toLowerCase());
  if (route.stops) route.stops.forEach(stop => {
    if (stop.city) allCities.add(stop.city.toLowerCase());
  });
});
const canonicalCityList = [...allCities];

// --- ПОРІГИ ---
const SIMILARITY_THRESHOLD = 0.6;
const CONFIDENT_THRESHOLD = 0.95;

// --- ПОШУК СХОЖИХ МІСТ ---
function findBestCityMatch(input, cityList) {
  if (!input) return null;
  const normalized = input.toLowerCase().trim();
  const match = stringSimilarity.findBestMatch(normalized, cityList);
  return match.bestMatch && match.bestMatch.rating > 0
    ? { original: input, bestMatch: match.bestMatch.target, rating: match.bestMatch.rating }
    : null;
}

// --- ВІДПОВІДІ НА ЗАПИТ ПРО БАГАЖ ---
bot.action('baggage_restrictions', async ctx => {
  await ctx.replyWithMarkdown(`🚫 **Обмеження:**
Не дозволено перевозити речі, що можуть заважати іншим або створити небезпеку.`);
  return ctx.answerCbQuery();
});
bot.action('baggage_excess', async ctx => {
  await ctx.replyWithMarkdown(`➕ **Понад норму:**
Додатковий багаж можливий лише за згодою водія.`);
  return ctx.answerCbQuery();
});
bot.action('baggage_liability', async ctx => {
  await ctx.replyWithMarkdown(`🛅 **Відповідальність:**
Перевізник не несе відповідальності за збереження багажу.`);
  return ctx.answerCbQuery();
});
bot.action('baggage_inspection', async ctx => {
  await ctx.replyWithMarkdown(`🔍 **Огляд:**
Персонал має право перевірити вміст багажу з міркувань безпеки.`);
  return ctx.answerCbQuery();
});
bot.action('baggage_other_rules', async ctx => {
  await ctx.replyWithMarkdown(`📎 **Інше:**
Багаж без супроводу пасажира не перевозиться. Забуті речі — звертайтесь до диспетчера.`);
  return ctx.answerCbQuery();
});

// --- ОБРОБКА ТЕКСТУ ---
bot.on('text', async ctx => {
  const msg = ctx.message.text.toLowerCase();

  // Привітання
  if (msg.includes('привіт') || msg.includes('привет')) {
    return ctx.reply('Вітаю! Напишіть місто відправлення і прибуття, наприклад: "з Києва до Львова".');
  }

  // Запит про багаж
  if (msg.includes('багаж') || msg.includes('сумки') || msg.includes('валіза') || msg.includes('речі')) {
    return ctx.replyWithMarkdown(`🛄 **Правила перевезення багажу:**
    
👜 Ручна поклажа — 1 місце до 7 кг (40×20×60 см).
🧳 Багаж — 1 місце до 15 кг (50×40×80 см).
  
Оберіть нижче, щоб дізнатись більше:`, {
      reply_markup: {
        inline_keyboard: [
          [{ text: "🚫 Заборони", callback_data: "baggage_restrictions" }],
          [{ text: "➕ Понад норму", callback_data: "baggage_excess" }],
          [{ text: "🛅 Відповідальність", callback_data: "baggage_liability" }],
          [{ text: "🔍 Огляд", callback_data: "baggage_inspection" }],
          [{ text: "📎 Інше", callback_data: "baggage_other_rules" }]
        ]
      }
    });
  }

  // (Інші логіки розпізнавання маршруту можуть бути вставлені тут...)
  return ctx.reply('Вибач, не розпізнав запит. Напиши, звідки і куди хочеш їхати.');
});

bot.launch();
console.log("✅ Бот запущено.");
