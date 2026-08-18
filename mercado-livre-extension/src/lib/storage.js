// Camada fina sobre chrome.storage.local para configurações e tokens.
// Tudo fica local ao navegador (não sincroniza entre dispositivos), pois
// contém segredos (tokens OAuth, chave de API de IA).

const KEYS = {
  ML_CONFIG: "mlConfig",
  ML_AUTH: "mlAuth",
  AI_CONFIG: "aiConfig",
};

async function get(key, fallback) {
  const result = await chrome.storage.local.get(key);
  return result[key] ?? fallback;
}

async function set(key, value) {
  await chrome.storage.local.set({ [key]: value });
}

export const storage = {
  getMlConfig: () =>
    get(KEYS.ML_CONFIG, {
      clientId: "",
      clientSecret: "",
      siteId: "MLB",
      listingTypeId: "gold_special",
      defaultCurrency: "BRL",
      defaultCondition: "new",
      defaultQuantity: 1,
    }),
  setMlConfig: (config) => set(KEYS.ML_CONFIG, config),

  getMlAuth: () => get(KEYS.ML_AUTH, null),
  setMlAuth: (auth) => set(KEYS.ML_AUTH, auth),
  clearMlAuth: () => chrome.storage.local.remove(KEYS.ML_AUTH),

  getAiConfig: () =>
    get(KEYS.AI_CONFIG, { apiKey: "", model: "claude-sonnet-5" }),
  setAiConfig: (config) => set(KEYS.AI_CONFIG, config),
};
