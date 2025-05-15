
const TelegramBot = require("node-telegram-bot-api");
const fs = require("fs");

const routes = JSON.parse(fs.readFileSync("routes.json", "utf8"));
const token = process.env.BOT_TOKEN;
const bot = new TelegramBot(token, { polling: true });

bot.on("message", (msg) => {
  const chatId = msg.chat.id;
  const text = msg.text.toLowerCase();

  if (text.includes("привіт") || text.includes("привет")) {
    return bot.sendMessage(chatId, "Вітаю! Напиши маршрут або питання по перевезеннях.");
  }

  for (let route of routes) {
    if (
      text.includes(route.start.toLowerCase()) &&
      text.includes(route.end.toLowerCase())
    ) {
      const stopNames = route.stops.map(s => s.city).join(", ");
      return bot.sendMessage(
        chatId,
        `Маршрут: ${route.start} → ${route.end}
Ціна: ${route.price} грн
Тривалість: ${route.duration}
Зупинки: ${stopNames}`
      );
    }
  }

  return bot.sendMessage(chatId, "На жаль, не знайшов такий маршрут. Спробуй інше або зателефонуй: +38 075 375 00 00");
});
