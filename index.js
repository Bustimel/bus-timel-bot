
const { Telegraf } = require('telegraf');
const fs = require('fs');

// Token from environment variable
const bot = new Telegraf(process.env.BOT_TOKEN);

// Load routes
let routes = [];
try {
  const raw = fs.readFileSync('routes.json', 'utf8');
  routes = JSON.parse(raw);
} catch (err) {
  console.error('Не вдалося завантажити routes.json:', err.message);
}

const normalize = (text) => text.toLowerCase().replace(/[’'`"]/g, "").trim();

bot.start((ctx) => {
  ctx.reply("Вітаю! Я диспетчер Bus-Timel. Напишіть звідки і куди хочете поїхати, або поставте запитання.");
});

bot.hears(/^(привіт|привет)/i, (ctx) => {
  ctx.reply("Вітаю! Як я можу допомогти?");
});

bot.hears(/(як справи|как дела)/i, (ctx) => {
  ctx.reply("Все добре! Працюю для вас щодня.");
});

bot.on('text', (ctx) => {
  const text = normalize(ctx.message.text);
  const found = routes.find(r => {
    return normalize(r.start) === text || normalize(r.end) === text ||
           normalize(r.start + ' ' + r.end) === text || 
           normalize(r.start + ' – ' + r.end) === text;
  });

  if (found) {
    ctx.reply(`Маршрут: ${found.start} → ${found.end}
Час: ${found.departure_times?.[0] || '-'} → ${found.arrival_times?.[0] || '-'}
Ціна: ${found.price || 'Уточнюйте'} грн`);
  } else {
    ctx.reply("Не знайшов маршрут або питання незрозуміле. Напишіть звідки і куди їдете, або зателефонуйте: +38 075 375 00 00.");
  }
});

bot.launch();
