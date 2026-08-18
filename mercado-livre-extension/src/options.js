import { storage } from "./lib/storage.js";
import * as ml from "./lib/mlClient.js";

const els = {
  redirectUri: document.getElementById("redirectUri"),
  copyRedirect: document.getElementById("copyRedirect"),
  clientId: document.getElementById("clientId"),
  clientSecret: document.getElementById("clientSecret"),
  siteId: document.getElementById("siteId"),
  listingTypeId: document.getElementById("listingTypeId"),
  defaultCondition: document.getElementById("defaultCondition"),
  accountPill: document.getElementById("accountPill"),
  connectBtn: document.getElementById("connectBtn"),
  disconnectBtn: document.getElementById("disconnectBtn"),
  apiKey: document.getElementById("apiKey"),
  model: document.getElementById("model"),
  saveBtn: document.getElementById("saveBtn"),
  saveMessage: document.getElementById("saveMessage"),
  messageArea: document.getElementById("messageArea"),
};

function showError(text) {
  els.messageArea.innerHTML = `<div class="error">${text}</div>`;
}

function clearMessage() {
  els.messageArea.innerHTML = "";
}

async function loadForm() {
  els.redirectUri.value = chrome.identity.getRedirectURL();

  const mlConfig = await storage.getMlConfig();
  els.clientId.value = mlConfig.clientId || "";
  els.clientSecret.value = mlConfig.clientSecret || "";
  els.siteId.value = mlConfig.siteId || "MLB";
  els.listingTypeId.value = mlConfig.listingTypeId || "gold_special";
  els.defaultCondition.value = mlConfig.defaultCondition || "new";

  const aiConfig = await storage.getAiConfig();
  els.apiKey.value = aiConfig.apiKey || "";
  els.model.value = aiConfig.model || "claude-sonnet-5";

  await refreshAccountStatus();
}

async function refreshAccountStatus() {
  const auth = await storage.getMlAuth();
  const connected = Boolean(auth?.accessToken);
  els.accountPill.textContent = connected ? "✓ Conectado" : "Desconectado";
  els.accountPill.className = `pill ${connected ? "ok" : "warn"}`;
  els.disconnectBtn.hidden = !connected;
  els.connectBtn.textContent = connected ? "Reconectar" : "Conectar conta";
}

els.copyRedirect.addEventListener("click", async () => {
  await navigator.clipboard.writeText(els.redirectUri.value);
  els.copyRedirect.textContent = "Copiado!";
  setTimeout(() => (els.copyRedirect.textContent = "Copiar"), 1500);
});

async function persistFormAsConfig() {
  const mlConfig = {
    clientId: els.clientId.value.trim(),
    clientSecret: els.clientSecret.value.trim(),
    siteId: els.siteId.value,
    listingTypeId: els.listingTypeId.value,
    defaultCurrency: "BRL",
    defaultCondition: els.defaultCondition.value,
    defaultQuantity: 1,
  };
  await storage.setMlConfig(mlConfig);

  const aiConfig = {
    apiKey: els.apiKey.value.trim(),
    model: els.model.value.trim() || "claude-sonnet-5",
  };
  await storage.setAiConfig(aiConfig);
}

els.connectBtn.addEventListener("click", async () => {
  clearMessage();
  try {
    await persistFormAsConfig(); // client id precisa estar salvo antes do login
    els.connectBtn.disabled = true;
    await ml.login();
    await refreshAccountStatus();
  } catch (err) {
    showError(err.message);
  } finally {
    els.connectBtn.disabled = false;
  }
});

els.disconnectBtn.addEventListener("click", async () => {
  await ml.logout();
  await refreshAccountStatus();
});

els.saveBtn.addEventListener("click", async () => {
  clearMessage();
  try {
    await persistFormAsConfig();
    els.saveMessage.textContent = "Salvo!";
    setTimeout(() => (els.saveMessage.textContent = ""), 2000);
  } catch (err) {
    showError(err.message);
  }
});

loadForm();
