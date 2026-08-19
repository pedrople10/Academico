const crypto = require('crypto');

const SESSION_TTL_MS = 30 * 60 * 1000; // 30 minutos
const store = new Map();

function createSession(data) {
  const id = crypto.randomUUID();
  store.set(id, { ...data, createdAt: Date.now() });
  return id;
}

function getSession(id) {
  const session = store.get(id);
  if (!session) return null;
  if (Date.now() - session.createdAt > SESSION_TTL_MS) {
    store.delete(id);
    return null;
  }
  return session;
}

function cleanupExpiredSessions() {
  const now = Date.now();
  for (const [id, session] of store.entries()) {
    if (now - session.createdAt > SESSION_TTL_MS) {
      store.delete(id);
    }
  }
}

setInterval(cleanupExpiredSessions, 5 * 60 * 1000).unref();

module.exports = { createSession, getSession };
