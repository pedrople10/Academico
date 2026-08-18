import { fileToResizedDataUrl } from "./lib/imageUtils.js";

const MAX_IMAGES = 8;

const dropZone = document.getElementById("dropZone");
const fileInput = document.getElementById("fileInput");
const thumbsEl = document.getElementById("thumbs");
const generateBtn = document.getElementById("generateBtn");
const statusRow = document.getElementById("statusRow");
const messageArea = document.getElementById("messageArea");
const openOptionsBtn = document.getElementById("openOptions");

let images = []; // data URLs
let status = { connectedToMl: false, hasAiKey: false, mlConfigured: false };

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
  messageArea.innerHTML = `<div class="error">${text}</div>`;
}

function clearMessage() {
  messageArea.innerHTML = "";
}

function renderThumbs() {
  thumbsEl.innerHTML = "";
  images.forEach((src, index) => {
    const div = document.createElement("div");
    div.className = "thumb";
    div.innerHTML = `<img src="${src}" alt="foto ${index + 1}" /><button class="remove" data-index="${index}">✕</button>`;
    thumbsEl.appendChild(div);
  });
  updateGenerateState();
}

thumbsEl.addEventListener("click", (event) => {
  const btn = event.target.closest(".remove");
  if (!btn) return;
  const index = Number(btn.dataset.index);
  images.splice(index, 1);
  renderThumbs();
});

async function addFiles(fileList) {
  clearMessage();
  const files = Array.from(fileList).filter((f) => f.type.startsWith("image/"));
  const room = MAX_IMAGES - images.length;
  if (files.length > room) {
    showError(`Máximo de ${MAX_IMAGES} fotos por anúncio.`);
  }
  const toAdd = files.slice(0, room);
  try {
    const dataUrls = await Promise.all(toAdd.map(fileToResizedDataUrl));
    images.push(...dataUrls);
    renderThumbs();
  } catch (err) {
    showError(err.message);
  }
}

dropZone.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", (e) => addFiles(e.target.files));

["dragenter", "dragover"].forEach((evt) =>
  dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  })
);
["dragleave", "drop"].forEach((evt) =>
  dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
  })
);
dropZone.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));

function updateGenerateState() {
  generateBtn.disabled =
    images.length === 0 ||
    !status.connectedToMl ||
    !status.hasAiKey ||
    !status.mlConfigured;
}

function renderStatus() {
  statusRow.innerHTML = "";

  const mlLine = document.createElement("div");
  mlLine.className = "status-line";
  if (status.connectedToMl) {
    mlLine.innerHTML = `<span class="pill ok">✓ Mercado Livre conectado</span>`;
  } else {
    mlLine.innerHTML = `<span class="pill warn">Mercado Livre desconectado</span>`;
    const btn = document.createElement("button");
    btn.className = "btn-secondary";
    btn.textContent = status.mlConfigured ? "Conectar" : "Configurar";
    btn.addEventListener("click", async () => {
      if (!status.mlConfigured) {
        chrome.runtime.openOptionsPage();
        return;
      }
      try {
        btn.disabled = true;
        await sendMessage("ml:login");
        await refreshStatus();
      } catch (err) {
        showError(err.message);
      } finally {
        btn.disabled = false;
      }
    });
    mlLine.appendChild(btn);
  }
  statusRow.appendChild(mlLine);

  if (!status.hasAiKey) {
    const aiLine = document.createElement("div");
    aiLine.className = "status-line";
    aiLine.innerHTML = `<span class="pill warn">Chave da IA não configurada</span>`;
    const btn = document.createElement("button");
    btn.className = "btn-secondary";
    btn.textContent = "Configurar";
    btn.addEventListener("click", () => chrome.runtime.openOptionsPage());
    aiLine.appendChild(btn);
    statusRow.appendChild(aiLine);
  }

  updateGenerateState();
}

async function refreshStatus() {
  status = await sendMessage("status:get");
  renderStatus();
}

openOptionsBtn.addEventListener("click", () => chrome.runtime.openOptionsPage());

generateBtn.addEventListener("click", async () => {
  clearMessage();
  generateBtn.disabled = true;
  generateBtn.innerHTML = `<span class="spinner"></span> Analisando fotos...`;
  try {
    await sendMessage("listing:generate", { images });
    window.close();
  } catch (err) {
    showError(err.message);
    generateBtn.textContent = "Gerar anúncio com IA";
    updateGenerateState();
  }
});

refreshStatus();
