function scanForBalance() {
  const keywords = [
    'saldo', 'balance', 'carteira', 'wallet', 'my balance', 'total',
    'brl', 'conta', 'depositar', 'sacar', 'deposit', 'withdraw',
  ];
  const currencyPattern = /(?:R\$\s?)?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\b/g;

  function parseAmount(raw) {
    let s = raw.replace(/R\$\s?/, '').trim();
    if (/,\d{2}$/.test(s)) {
      s = s.replace(/\./g, '').replace(',', '.');
    } else if (/\.\d{2}$/.test(s)) {
      s = s.replace(/,/g, '');
    } else {
      s = s.replace(/[.,]/g, '');
    }
    const n = parseFloat(s);
    return Number.isFinite(n) ? n : null;
  }

  const fullText = document.body.innerText || '';
  const lowerText = fullText.toLowerCase();

  const withKeyword = [];
  const all = [];
  let match;
  while ((match = currencyPattern.exec(fullText)) !== null) {
    const raw = match[0];
    const idx = match.index;
    const value = parseAmount(raw);
    if (value === null) continue;

    const windowStart = Math.max(0, idx - 120);
    const windowEnd = Math.min(fullText.length, idx + raw.length + 120);
    const context = fullText.slice(windowStart, windowEnd).replace(/\s+/g, ' ').trim();
    const hasKeyword = keywords.some((k) => lowerText.slice(windowStart, windowEnd).includes(k));

    const item = { raw, value, context };
    all.push(item);
    if (hasKeyword) withKeyword.push(item);
  }

  const ranked = withKeyword.length ? withKeyword : all;

  const dedupedMap = new Map();
  for (const item of ranked) {
    if (!dedupedMap.has(item.value)) dedupedMap.set(item.value, item);
  }
  return Array.from(dedupedMap.values()).slice(0, 12);
}

function formatBRL(value) {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value);
}

function parseManualValue(raw) {
  let s = raw.replace(/R\$\s?/, '').trim();
  if (/,\d{2}$/.test(s)) {
    s = s.replace(/\./g, '').replace(',', '.');
  } else {
    s = s.replace(/,/g, '');
  }
  const n = parseFloat(s);
  return Number.isFinite(n) ? n : null;
}

async function getAllHouses() {
  const data = await chrome.storage.local.get(null);
  return data;
}

async function saveHouse(host, value) {
  await chrome.storage.local.set({
    [host]: { value, updated: Date.now() },
  });
}

async function removeHouse(host) {
  await chrome.storage.local.remove(host);
}

async function render() {
  const data = await getAllHouses();
  const hosts = Object.keys(data)
    .filter((k) => !k.startsWith('_pending_'))
    .sort();
  const pendingKeys = Object.keys(data).filter((k) => k.startsWith('_pending_'));

  const body = document.getElementById('housesBody');
  body.innerHTML = '';
  let total = 0;

  for (const host of hosts) {
    const entry = data[host];
    total += entry.value;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${host}</td>
      <td class="value">${formatBRL(entry.value)}</td>
      <td>
        <button class="edit" data-host="${host}" data-value="${entry.value}">editar</button>
        <button class="remove" data-host="${host}">remover</button>
      </td>
    `;
    body.appendChild(tr);
  }

  document.getElementById('total').textContent = formatBRL(total);

  body.querySelectorAll('.remove').forEach((btn) => {
    btn.addEventListener('click', async () => {
      await removeHouse(btn.dataset.host);
      render();
    });
  });

  body.querySelectorAll('.edit').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.getElementById('manualHost').value = btn.dataset.host;
      document.getElementById('manualValue').value = btn.dataset.value.replace('.', ',');
      document.querySelector('details').open = true;
      document.getElementById('manualValue').focus();
    });
  });

  renderPending(pendingKeys, data);
}

function renderPending(pendingKeys, data) {
  const section = document.getElementById('pendingSection');
  section.innerHTML = '';

  for (const key of pendingKeys) {
    const host = key.replace('_pending_', '');
    const entry = data[key];
    if (!entry || !entry.candidates || !entry.candidates.length) continue;

    const block = document.createElement('div');
    block.className = 'pending-block';
    block.innerHTML = `<div class="pending-title">"${host}" tem mais de um valor parecido - qual e o saldo?</div>`;

    for (const c of entry.candidates) {
      const div = document.createElement('div');
      div.className = 'candidate';
      div.innerHTML = `
        <span><strong>${formatBRL(c.value)}</strong></span>
        <span class="ctx" title="${c.context}">${c.context}</span>
      `;
      div.addEventListener('click', async () => {
        await saveHouse(host, c.value);
        await chrome.storage.local.remove(key);
        render();
      });
      block.appendChild(div);
    }

    section.appendChild(block);
  }
}

function renderCandidates(host, candidates) {
  const container = document.getElementById('candidates');
  container.innerHTML = '';

  if (!candidates.length) {
    document.getElementById('scanStatus').textContent =
      'Nao encontrei nenhum valor nesta pagina. Adicione manualmente abaixo.';
    return;
  }

  document.getElementById('scanStatus').textContent =
    'Escolha o valor certo pra salvar como saldo de "' + host + '":';

  for (const c of candidates) {
    const div = document.createElement('div');
    div.className = 'candidate';
    div.innerHTML = `
      <span><strong>${formatBRL(c.value)}</strong></span>
      <span class="ctx" title="${c.context}">${c.context}</span>
    `;
    div.addEventListener('click', async () => {
      await saveHouse(host, c.value);
      container.innerHTML = '';
      document.getElementById('scanStatus').textContent = 'Salvo!';
      render();
    });
    container.appendChild(div);
  }
}

document.getElementById('scanBtn').addEventListener('click', async () => {
  document.getElementById('scanStatus').textContent = 'Lendo pagina...';
  document.getElementById('candidates').innerHTML = '';

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url || !tab.url.startsWith('http')) {
    document.getElementById('scanStatus').textContent =
      'Abra a pagina da casa de apostas (logado) numa aba e tente de novo.';
    return;
  }

  const host = new URL(tab.url).hostname.replace(/^www\./, '');

  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: scanForBalance,
    });
    renderCandidates(host, result || []);
  } catch (e) {
    document.getElementById('scanStatus').textContent =
      'Nao consegui ler esta pagina (' + e.message + '). Adicione manualmente abaixo.';
  }
});

document.getElementById('manualSaveBtn').addEventListener('click', async () => {
  const host = document.getElementById('manualHost').value.trim();
  const rawValue = document.getElementById('manualValue').value.trim();
  const value = parseManualValue(rawValue);

  if (!host || value === null) {
    alert('Preencha o nome da casa e um saldo valido.');
    return;
  }

  await saveHouse(host, value);
  document.getElementById('manualHost').value = '';
  document.getElementById('manualValue').value = '';
  render();
});

document.getElementById('openDashboardBtn').addEventListener('click', () => {
  chrome.tabs.create({ url: chrome.runtime.getURL('dashboard.html') });
});

render();
