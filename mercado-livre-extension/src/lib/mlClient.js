// Cliente da API do Mercado Livre: login OAuth2 (Authorization Code + PKCE),
// refresh de token, predição de categoria, atributos, upload de fotos e
// criação do anúncio.
//
// Referência: https://developers.mercadolivre.com.br/

import { storage } from "./storage.js";
import { createPkcePair } from "./pkce.js";
import { authDomainFor } from "./mlSites.js";

const API_BASE = "https://api.mercadolibre.com";

function getRedirectUrl() {
  // Ex: https://<extension-id>.chromiumapp.org/
  // Precisa ser cadastrada como Redirect URI no app do Mercado Livre Developers.
  return chrome.identity.getRedirectURL();
}

async function tokenRequest(params) {
  const response = await fetch(`${API_BASE}/oauth/token`, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Accept: "application/json",
    },
    body: new URLSearchParams(params).toString(),
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(
      `Falha na autenticação com o Mercado Livre: ${data.message || response.status}`
    );
  }
  return data;
}

async function persistTokenResponse(data, siteId) {
  const auth = {
    accessToken: data.access_token,
    refreshToken: data.refresh_token,
    userId: data.user_id,
    siteId,
    expiresAt: Date.now() + (data.expires_in ?? 21600) * 1000,
  };
  await storage.setMlAuth(auth);
  return auth;
}

export async function login() {
  const config = await storage.getMlConfig();
  if (!config.clientId) {
    throw new Error(
      "Configure o Client ID do Mercado Livre nas opções da extensão antes de conectar."
    );
  }

  const redirectUri = getRedirectUrl();
  const { codeVerifier, codeChallenge } = await createPkcePair();
  const domain = authDomainFor(config.siteId);

  const authUrl = new URL(`https://${domain}/authorization`);
  authUrl.searchParams.set("response_type", "code");
  authUrl.searchParams.set("client_id", config.clientId);
  authUrl.searchParams.set("redirect_uri", redirectUri);
  authUrl.searchParams.set("code_challenge", codeChallenge);
  authUrl.searchParams.set("code_challenge_method", "S256");

  const resultUrl = await chrome.identity.launchWebAuthFlow({
    url: authUrl.toString(),
    interactive: true,
  });

  if (!resultUrl) {
    throw new Error("Login cancelado.");
  }

  const code = new URL(resultUrl).searchParams.get("code");
  if (!code) {
    throw new Error("O Mercado Livre não retornou um código de autorização.");
  }

  const params = {
    grant_type: "authorization_code",
    client_id: config.clientId,
    code,
    redirect_uri: redirectUri,
    code_verifier: codeVerifier,
  };
  if (config.clientSecret) params.client_secret = config.clientSecret;

  const data = await tokenRequest(params);
  return persistTokenResponse(data, config.siteId);
}

export async function logout() {
  await storage.clearMlAuth();
}

async function refreshAccessToken(auth) {
  const config = await storage.getMlConfig();
  const params = {
    grant_type: "refresh_token",
    client_id: config.clientId,
    refresh_token: auth.refreshToken,
  };
  if (config.clientSecret) params.client_secret = config.clientSecret;

  const data = await tokenRequest(params);
  return persistTokenResponse(data, auth.siteId);
}

// Garante um access_token válido, renovando com o refresh_token se preciso.
export async function ensureAuth() {
  let auth = await storage.getMlAuth();
  if (!auth || !auth.accessToken) {
    throw new Error(
      "Você ainda não conectou sua conta do Mercado Livre. Abra as opções da extensão."
    );
  }

  const isExpiringSoon = Date.now() > auth.expiresAt - 60_000;
  if (isExpiringSoon) {
    if (!auth.refreshToken) {
      throw new Error("Sessão do Mercado Livre expirada. Conecte novamente.");
    }
    auth = await refreshAccessToken(auth);
  }
  return auth;
}

async function apiFetch(path, { method = "GET", body, auth, headers } = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      ...(body && !(body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...(auth ? { Authorization: `Bearer ${auth.accessToken}` } : {}),
      ...headers,
    },
    body: body
      ? body instanceof FormData
        ? body
        : JSON.stringify(body)
      : undefined,
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message =
      data.message ||
      data.error ||
      (data.cause && JSON.stringify(data.cause)) ||
      response.statusText;
    throw new Error(`Mercado Livre API (${path}): ${message}`);
  }
  return data;
}

// Sugere a melhor categoria do ML a partir de um texto de busca (ex.: título).
export async function predictCategory(query, siteId) {
  const results = await apiFetch(
    `/sites/${siteId}/domain_discovery/search?limit=1&q=${encodeURIComponent(query)}`
  );
  return Array.isArray(results) && results.length > 0 ? results[0] : null;
}

// Lista os atributos (obrigatórios e opcionais) exigidos por uma categoria.
export async function getCategoryAttributes(categoryId) {
  return apiFetch(`/categories/${categoryId}/attributes`);
}

// Envia uma imagem (base64 data URL) e retorna o id da imagem no ML.
export async function uploadPicture(auth, dataUrl, filename) {
  const blob = await (await fetch(dataUrl)).blob();
  const form = new FormData();
  form.append("file", blob, filename || "foto.jpg");

  const data = await apiFetch("/pictures/items/upload", {
    method: "POST",
    body: form,
    auth,
  });
  return data.id;
}

// Cria o anúncio. `payload` segue o formato da API de Items do Mercado Livre.
export async function createItem(auth, payload) {
  return apiFetch("/items", { method: "POST", body: payload, auth });
}

export async function setItemDescription(auth, itemId, plainText) {
  return apiFetch(`/items/${itemId}/description`, {
    method: "POST",
    body: { plain_text: plainText },
    auth,
  });
}

export async function getMe(auth) {
  return apiFetch("/users/me", { auth });
}
