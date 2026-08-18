// Utilidades para o fluxo OAuth2 Authorization Code + PKCE do Mercado Livre.
// PKCE evita que a extensão precise embutir o client_secret do app.

function randomString(length) {
  const chars =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~";
  const bytes = crypto.getRandomValues(new Uint8Array(length));
  return Array.from(bytes, (b) => chars[b % chars.length]).join("");
}

function base64UrlEncode(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

async function sha256(text) {
  const data = new TextEncoder().encode(text);
  return crypto.subtle.digest("SHA-256", data);
}

export async function createPkcePair() {
  const codeVerifier = randomString(64);
  const digest = await sha256(codeVerifier);
  const codeChallenge = base64UrlEncode(digest);
  return { codeVerifier, codeChallenge };
}
