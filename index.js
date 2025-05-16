const { Telegraf } = require('telegraf');
const fs = require('fs');
const routes = JSON.parse(fs.readFileSync('./routes.json', 'utf8'));

const bot = new Telegraf(process.env.BOT_TOKEN);

const greetings = ['привіт', 'привет', 'доброго дня', 'здравствуйте'];
const fallback = 'Не зрозумів. Напишіть звідки і куди їдете, або зателефонуйте: +38 075 375 00 00';
const bagRules = `Ручна поклажа — до 7 кг (до 40×20×60 см).
Багаж — до 15 кг (50×40×80 см) — безкоштовно.
Більше — за згодою водія.`;

bot.start(ctx => {
  ctx.reply('Вітаю! Я диспетчер Bus-Timel. Напишіть маршрут або поставте запитання.');
});

bot.on('text', ctx => {
  const msg = ctx.message.text.toLowerCase();

  if (greetings.some(g => msg.includes(g))) {
    return ctx.reply('Вітаю! Як я можу допомогти? Напишіть місто відправлення і прибуття.');
  }

  if (msg.includes('багаж') || msg.includes('вещи') || msg.includes('чемодан')) {
    return ctx.reply(bagRules);
  }

  if (msg.includes('як справи') || msg.includes('как дела')) {
    return ctx.reply('Усе добре! Готовий допомогти з вашим маршрутом.');
  }

  if (msg.includes('машина') || msg.includes('автобус')) {
    return ctx.reply('Ми використовуємо Mercedes Sprinter або Volkswagen Crafter. Комфорт та безпека!');
  }

  if (msg.includes('посадка') || msg.includes('звідки') || msg.includes('остановка')) {
    return ctx.reply('Напишіть маршрут — я підкажу адресу посадки.');
  }

  // Поиск маршрута
  const allRoutes = routes.map(r => ({
    from: r.start.toLowerCase(),
    to: r.end.toLowerCase(),
    route: r
  }));

  const match = allRoutes.find(r =>
    msg.includes(r.from) && msg.includes(r.to)
  );

  if (match) {
    const { route } = match;
    const duration = route.duration || 'уточнюйте';
    const price = route.price ? `${route.price} грн` : 'уточнюйте';
    const dep = route.departure_times?.[0] || '-';
    const arr = route.arrival_times?.[0] || '-';
    const pickup = route.pickup_address || 'уточніть у диспетчера';

    return ctx.reply(`Маршрут: ${route.start} → ${route.end}
Відправлення: ${dep}
Прибуття: ${arr}
Тривалість: ${duration}
Ціна: ${price}
Посадка: ${pickup}`);
  }

  return ctx.reply(fallback);
});

bot.launch();
console.log('✅ Bus-Timel бот запущено!');