
require("dotenv").config();
const express = require("express");
const app = express();
const cors = require("cors");
const { getRoutes } = require("./firebase");

app.use(cors());
app.use(express.json());

app.get("/", (req, res) => {
  res.send("Bus-Timel Bot API працює.");
});

app.get("/routes", async (req, res) => {
  try {
    const routes = await getRoutes();
    res.json(routes);
  } catch (err) {
    res.status(500).json({ error: "Помилка при отриманні маршрутів" });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server запущено на порту ${PORT}`));
