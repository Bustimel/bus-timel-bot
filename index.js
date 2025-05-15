
const TelegramBot = require("node-telegram-bot-api");
const fs = require("fs");

const routes = JSON.parse(fs.readFileSync("routes.json", "utf8"));
const token = process.env.BOT_TOKEN;
const bot = new TelegramBot(token, { polling: true });

function normalize(text) {
  return text
    .toLowerCase()
    .replace(/’/g, "'")
    .replace(/[^а-яa-zіїєґё\s]/gi, "")
    .trim();
}

bot.on("message", (msg) => {
  const chatId = msg.chat.id;
  const text = normalize(msg.text || "");

  if (text.includes("привіт") || text.includes("привет") || text.includes("як справи")) {
    return bot.sendMessage(chatId, "Вітаю! Я диспетчер Bus-Timel. Напишіть звідки і куди хочете поїхати, або поставте запитання.");
  }

  if (text.includes("багаж") || text.includes("поклажа") || text.includes("речі")) {
    return bot.sendMessage(chatId, "Ручна поклажа — до 7 кг. Багаж — 1 одиниця до 15 кг безкоштовно. Більше — лише за згодою водія.");
  }

  if (text.includes("автобус") || text.includes("машина") || text.includes("транспорт")) {
    return bot.sendMessage(chatId, "Ми їздимо Mercedes Sprinter або Volkswagen Crafter — комфорт, Wi-Fi, кондиціонер.");
  }

  if (text.includes("місце") || text.includes("місця") || text.includes("забронювати")) {
    return bot.sendMessage(chatId, "Місця можна бронювати через сайт або за телефоном +38 075 375 00 00.");
  }

  for (let route of routes) {
    const aliases = route.aliases || {};
    const allStarts = [route.start, ...(aliases.start || [])].map(normalize);
    const allEnds = [route.end, ...(aliases.end || [])].map(normalize);

    const hasStart = allStarts.some((name) => text.includes(name));
    const hasEnd = allEnds.some((name) => text.includes(name));

    if (hasStart && hasEnd) {
      const stops = (route.stops || []).map(s => s.city_ua || s.city).join(", ");
      const price = route.price ? `${route.price} грн` : "Уточнюйте";
      const time = route.duration || "уточнюйте";
      const pickup = route.pickup_address || "адресу уточнюйте";

      return bot.sendMessage(
        chatId,
        `Маршрут: ${route.start_ua} → ${route.end_ua}
Ціна: ${price}
Тривалість: ${time}
Зупинки: ${stops}
Посадка: ${pickup}`
      );
    }
  }

  return bot.sendMessage(chatId, "Не знайшов маршрут або питання незрозуміле. Напишіть звідки і куди їдете, або зателефонуйте: +38 075 375 00 00.");
});
