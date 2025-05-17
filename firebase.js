
const admin = require("firebase-admin");

// Чтение ключа из переменной среды
const serviceAccount = JSON.parse(process.env.SERVICE_ACCOUNT_KEY);

admin.initializeApp({
  credential: admin.credential.cert(serviceAccount),
});

const db = admin.firestore();

async function getRoutes() {
  const snapshot = await db.collection("routes").get();
  return snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() }));
}

module.exports = { getRoutes };
