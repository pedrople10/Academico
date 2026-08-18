const els = {
  notes: document.getElementById("notes"),
  imageGallery: document.getElementById("imageGallery"),
  categoryQuery: document.getElementById("categoryQuery"),
  searchCategoryBtn: document.getElementById("searchCategoryBtn"),
  categoryResult: document.getElementById("categoryResult"),
  categoryId: document.getElementById("categoryId"),
  title: document.getElementById("title"),
  titleCount: document.getElementById("titleCount"),
  description: document.getElementById("description"),
  price: document.getElementById("price"),
  quantity: document.getElementById("quantity"),
  condition: document.getElementById("condition"),
  listingTypeId: document.getElementById("listingTypeId"),
  attributesList: document.getElementById("attributesList"),
  aiHints: document.getElementById("aiHints"),
  publishBtn: document.getElementById("publishBtn"),
  publishMessage: document.getElementById("publishMessage"),
  messageArea: document.getElementById("messageArea"),
  resultArea: document.getElementById("resultArea"),
};

let pending = null; // { images, draft, category, requiredAttributes, config, pictureIds }
let requiredAttributes = [];

function sendMessage(action, payload) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ action, payload }, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      if (!response?.ok) {
        reject(new Error(response?.error || "Erro desconhecido."));
        return;
      }
      resolve(response.result);
    });
  });
}

function showError(text) {
  els.messageArea.innerHTML = `<div class="error">${text}</div>`;
}

function clearMessage() {
  els.messageArea.innerHTML = "";
}

function normalize(text) {
  return (text || "")
    .toString()
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim();
}

const SYNONYMS = {
  marca: ["brand"],
  modelo: ["model"],
  cor: ["color", "cor"],
};

function guessValueForAttribute(attrName, draft) {
  const normName = normalize(attrName);

  const direct = (draft.attributes || []).find(
    (a) => normalize(a.name) === normName
  );
  if (direct) return direct.value;

  for (const [key, synonyms] of Object.entries(SYNONYMS)) {
    if (normName.includes(key) || synonyms.some((s) => normName.includes(s))) {
      if (key === "marca" && draft.brand) return draft.brand;
      if (key === "modelo" && draft.model) return draft.model;
      if (key === "cor" && draft.color) return draft.color;
    }
  }

  const partial = (draft.attributes || []).find(
    (a) => normName.includes(normalize(a.name)) || normalize(a.name).includes(normName)
  );
  return partial ? partial.value : "";
}

function renderImages() {
  els.imageGallery.innerHTML = "";
  pending.images.forEach((src, index) => {
    const div = document.createElement("div");
    div.className = "thumb";
    div.innerHTML = `<img src="${src}" alt="foto ${index + 1}" /><button class="remove" data-index="${index}">✕</button>`;
    els.imageGallery.appendChild(div);
  });
}

els.imageGallery.addEventListener("click", async (event) => {
  const btn = event.target.closest(".remove");
  if (!btn) return;
  if (pending.images.length <= 1) {
    showError("O anúncio precisa de pelo menos uma foto.");
    return;
  }
  const index = Number(btn.dataset.index);
  pending.images.splice(index, 1);
  pending.pictureIds = null; // força reenvio das fotos
  await sendMessage("listing:updatePending", {
    images: pending.images,
    pictureIds: null,
  });
  renderImages();
});

function renderAttributes() {
  if (requiredAttributes.length === 0) {
    els.attributesList.innerHTML =
      '<span class="muted">Nenhum atributo obrigatório encontrado (ou categoria ainda não definida).</span>';
  } else {
    els.attributesList.innerHTML = "";
    requiredAttributes.forEach((attr) => {
      const row = document.createElement("div");
      row.className = "attribute-row";
      row.innerHTML = `
        <label for="attr-${attr.id}">${attr.name}</label>
        <input id="attr-${attr.id}" type="text" data-attr-id="${attr.id}" value="${attr.value || ""}" />
      `;
      els.attributesList.appendChild(row);
    });
  }

  const draft = pending.draft;
  const extras = (draft.attributes || []).map((a) => `${a.name}: ${a.value}`);
  els.aiHints.textContent = extras.length
    ? `Outras características identificadas pela IA: ${extras.join(" · ")}`
    : "";
}

function fillFormFromPending() {
  const { draft, category } = pending;

  els.title.value = draft.title || "";
  els.description.value = draft.description || "";
  els.price.value = draft.suggested_price_brl ?? "";
  els.condition.value = draft.condition === "used" ? "used" : "new";
  els.listingTypeId.value = pending.config?.listingTypeId || "gold_special";
  els.categoryQuery.value = draft.category_search_query || draft.title || "";

  if (category?.category_id) {
    els.categoryId.value = category.category_id;
    els.categoryResult.textContent = `Categoria sugerida: ${category.category_name || category.category_id} (${category.category_id})`;
  } else {
    els.categoryResult.textContent =
      "Nenhuma categoria sugerida automaticamente. Busque ou preencha o ID manualmente.";
  }

  requiredAttributes = (pending.requiredAttributes || []).map((attr) => ({
    ...attr,
    value: guessValueForAttribute(attr.name, draft),
  }));

  if (draft.notes) {
    els.notes.innerHTML = `<div class="card"><strong>Observação da IA:</strong> ${draft.notes}</div>`;
  }

  renderImages();
  renderAttributes();
  updateTitleCount();
}

function updateTitleCount() {
  els.titleCount.textContent = `${els.title.value.length}/60`;
}
els.title.addEventListener("input", updateTitleCount);

els.searchCategoryBtn.addEventListener("click", async () => {
  clearMessage();
  els.searchCategoryBtn.disabled = true;
  els.categoryResult.textContent = "Buscando...";
  try {
    const { category, requiredAttributes: attrs } = await sendMessage(
      "listing:predictCategory",
      { query: els.categoryQuery.value }
    );
    pending.category = category;
    pending.requiredAttributes = attrs;
    if (category?.category_id) {
      els.categoryId.value = category.category_id;
      els.categoryResult.textContent = `Categoria sugerida: ${category.category_name || category.category_id} (${category.category_id})`;
    } else {
      els.categoryResult.textContent = "Nenhuma categoria encontrada para esse termo.";
    }
    requiredAttributes = attrs.map((attr) => ({
      ...attr,
      value: guessValueForAttribute(attr.name, pending.draft),
    }));
    renderAttributes();
  } catch (err) {
    showError(err.message);
  } finally {
    els.searchCategoryBtn.disabled = false;
  }
});

function collectAttributeValues() {
  return requiredAttributes.map((attr) => {
    const input = document.getElementById(`attr-${attr.id}`);
    return { id: attr.id, value: input ? input.value.trim() : "" };
  });
}

els.publishBtn.addEventListener("click", async () => {
  clearMessage();
  els.resultArea.innerHTML = "";

  if (!els.title.value.trim()) return showError("Preencha o título.");
  if (!els.categoryId.value.trim())
    return showError("Defina a categoria do anúncio.");
  if (!els.price.value || Number(els.price.value) <= 0)
    return showError("Informe um preço válido.");

  const listing = {
    images: pending.images,
    pictureIds: pending.pictureIds || null,
    title: els.title.value.trim(),
    description: els.description.value.trim(),
    categoryId: els.categoryId.value.trim(),
    price: Number(els.price.value),
    currencyId: pending.config?.defaultCurrency || "BRL",
    quantity: Number(els.quantity.value) || 1,
    condition: els.condition.value,
    listingTypeId: els.listingTypeId.value,
    attributes: collectAttributeValues(),
  };

  els.publishBtn.disabled = true;
  els.publishMessage.innerHTML = '<span class="spinner"></span> Publicando...';
  try {
    const result = await sendMessage("listing:publish", { listing });
    els.resultArea.innerHTML = `
      <div class="result-card">
        <strong>Anúncio publicado com sucesso!</strong><br />
        <a href="${result.permalink}" target="_blank" rel="noopener">Ver anúncio no Mercado Livre</a>
      </div>`;
    els.publishMessage.textContent = "";
    document.querySelectorAll("input, textarea, select, button").forEach((el) => {
      if (el !== els.resultArea) el.disabled = true;
    });
  } catch (err) {
    showError(err.message);
    els.publishBtn.disabled = false;
    els.publishMessage.textContent = "";
  }
});

async function init() {
  try {
    pending = await sendMessage("listing:getPending");
    if (!pending) {
      document.getElementById("page").innerHTML =
        '<div class="card"><p>Nenhum anúncio pendente. Volte à extensão e envie fotos primeiro.</p></div>';
      return;
    }
    fillFormFromPending();
  } catch (err) {
    showError(err.message);
  }
}

init();
