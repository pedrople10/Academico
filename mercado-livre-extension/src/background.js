// Service worker: ponto único que fala com as APIs externas (Mercado Livre e
// Anthropic) e guarda o estado temporário do anúncio sendo gerado, repassado
// entre o popup e a aba de revisão via chrome.storage.session.

import { storage } from "./lib/storage.js";
import * as ml from "./lib/mlClient.js";
import { analyzeProductImages } from "./lib/aiClient.js";

const PENDING_KEY = "pendingListing";

async function getSession(key) {
  const result = await chrome.storage.session.get(key);
  return result[key];
}

async function setSession(key, value) {
  await chrome.storage.session.set({ [key]: value });
}

async function handleGetStatus() {
  const [auth, mlConfig, aiConfig] = await Promise.all([
    storage.getMlAuth(),
    storage.getMlConfig(),
    storage.getAiConfig(),
  ]);
  return {
    connectedToMl: Boolean(auth?.accessToken),
    hasAiKey: Boolean(aiConfig?.apiKey),
    mlConfigured: Boolean(mlConfig?.clientId),
  };
}

async function handleGenerate({ images }) {
  await ml.ensureAuth(); // falha cedo se não estiver logado
  const config = await storage.getMlConfig();

  const draft = await analyzeProductImages(images);

  let category = null;
  try {
    category = await ml.predictCategory(
      draft.category_search_query || draft.title,
      config.siteId
    );
  } catch {
    category = null; // usuário escolhe manualmente na revisão se falhar
  }

  let requiredAttributes = [];
  if (category?.category_id) {
    try {
      const attrs = await ml.getCategoryAttributes(category.category_id);
      requiredAttributes = attrs
        .filter((a) => a.tags?.required)
        .map((a) => ({ id: a.id, name: a.name }));
    } catch {
      requiredAttributes = [];
    }
  }

  const pending = {
    images,
    draft,
    category,
    requiredAttributes,
    config,
    createdAt: Date.now(),
  };
  await setSession(PENDING_KEY, pending);

  const tab = await chrome.tabs.create({
    url: chrome.runtime.getURL("src/review.html"),
  });
  return { tabId: tab.id };
}

async function handleGetPending() {
  return (await getSession(PENDING_KEY)) || null;
}

async function handleUpdatePending(patch) {
  const current = (await getSession(PENDING_KEY)) || {};
  const updated = { ...current, ...patch };
  await setSession(PENDING_KEY, updated);
  return updated;
}

async function handlePublish({ listing }) {
  const auth = await ml.ensureAuth();

  let pictureIds = listing.pictureIds;
  if (!pictureIds || pictureIds.length !== listing.images.length) {
    pictureIds = [];
    for (const [index, image] of listing.images.entries()) {
      const id = await ml.uploadPicture(auth, image, `foto-${index + 1}.jpg`);
      pictureIds.push(id);
    }
    await handleUpdatePending({ pictureIds });
  }

  const payload = {
    title: listing.title.slice(0, 60),
    category_id: listing.categoryId,
    price: listing.price,
    currency_id: listing.currencyId || "BRL",
    available_quantity: listing.quantity || 1,
    buying_mode: "buy_it_now",
    condition: listing.condition || "new",
    listing_type_id: listing.listingTypeId || "gold_special",
    pictures: pictureIds.map((id) => ({ id })),
    attributes: (listing.attributes || [])
      .filter((a) => a.id && a.value)
      .map((a) => ({ id: a.id, value_name: a.value })),
  };

  const item = await ml.createItem(auth, payload);

  if (listing.description) {
    await ml.setItemDescription(auth, item.id, listing.description);
  }

  await chrome.storage.session.remove(PENDING_KEY);
  return { id: item.id, permalink: item.permalink };
}

async function handlePredictCategory({ query }) {
  const config = await storage.getMlConfig();
  const category = await ml.predictCategory(query, config.siteId);
  let requiredAttributes = [];
  if (category?.category_id) {
    const attrs = await ml.getCategoryAttributes(category.category_id);
    requiredAttributes = attrs
      .filter((a) => a.tags?.required)
      .map((a) => ({ id: a.id, name: a.name }));
  }
  await handleUpdatePending({ category, requiredAttributes });
  return { category, requiredAttributes };
}

const handlers = {
  "status:get": handleGetStatus,
  "ml:login": () => ml.login(),
  "ml:logout": () => ml.logout(),
  "listing:generate": handleGenerate,
  "listing:getPending": handleGetPending,
  "listing:updatePending": (payload) => handleUpdatePending(payload),
  "listing:predictCategory": handlePredictCategory,
  "listing:publish": handlePublish,
};

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const handler = handlers[message?.action];
  if (!handler) return false;

  handler(message.payload)
    .then((result) => sendResponse({ ok: true, result }))
    .catch((error) =>
      sendResponse({ ok: false, error: error.message || String(error) })
    );

  return true; // mantém o canal aberto para a resposta assíncrona
});
