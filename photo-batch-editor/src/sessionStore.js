const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const SESSION_TTL_MS = 30 * 60 * 1000; // 30 minutos
const SESSIONS_ROOT = path.join(os.tmpdir(), 'photo-batch-editor', 'sessions');
const store = new Map();

// Cada processamento ganha uma pasta temporaria propria onde ficam as
// fotos editadas em tamanho cheio. Assim elas nao ficam na memoria do
// servidor esperando o download do .zip.
function createSessionDir() {
  const id = crypto.randomUUID();
  const dir = path.join(SESSIONS_ROOT, id);
  fs.mkdirSync(dir, { recursive: true });
  return { id, dir };
}

function removeDir(dir) {
  fs.rm(dir, { recursive: true, force: true }, () => {});
}

function createSession(id, dir, data) {
  store.set(id, { ...data, dir, createdAt: Date.now() });
  return id;
}

function deleteSession(id) {
  const session = store.get(id);
  store.delete(id);
  if (session) removeDir(session.dir);
}

function getSession(id) {
  const session = store.get(id);
  if (!session) return null;
  if (Date.now() - session.createdAt > SESSION_TTL_MS) {
    deleteSession(id);
    return null;
  }
  return session;
}

function cleanupExpiredSessions() {
  const now = Date.now();
  for (const [id, session] of store.entries()) {
    if (now - session.createdAt > SESSION_TTL_MS) {
      deleteSession(id);
    }
  }
}

// Ao subir o servidor, apaga sobras de execucoes anteriores.
fs.rmSync(SESSIONS_ROOT, { recursive: true, force: true });

setInterval(cleanupExpiredSessions, 5 * 60 * 1000).unref();

module.exports = { createSessionDir, createSession, getSession, removeDir };
