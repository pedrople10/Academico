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
  return chrome.storage.local.get(null);
}

async function saveHouse(host, value) {
  await chrome.storage.local.set({
    [host]: { value, updated: Date.now() },
  });
}

async function removeHouse(host) {
  await chrome.storage.local.remove(host);
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

  document.getElementById('emptyMsg').hidden = hosts.length > 0;
  document.getElementById('total').textContent = formatBRL(total);
  document.getElementById('updatedAt').textContent =
    'Atualizado ' + new Date().toLocaleTimeString('pt-BR');

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
      document.getElementById('manualValue').focus();
      window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
    });
  });

  renderPending(pendingKeys, data);
}

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

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName === 'local') render();
});

render();
