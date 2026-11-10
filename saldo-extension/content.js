(function () {
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

  function scan() {
    const fullText = document.body ? document.body.innerText || '' : '';
    const lowerText = fullText.toLowerCase();
    const strictMap = new Map();

    let match;
    currencyPattern.lastIndex = 0;
    while ((match = currencyPattern.exec(fullText)) !== null) {
      const raw = match[0];
      const idx = match.index;
      const value = parseAmount(raw);
      if (value === null) continue;

      const windowStart = Math.max(0, idx - 120);
      const windowEnd = Math.min(fullText.length, idx + raw.length + 120);
      const context = fullText.slice(windowStart, windowEnd).replace(/\s+/g, ' ').trim();
      const hasKeyword = keywords.some((k) => lowerText.slice(windowStart, windowEnd).includes(k));

      if (hasKeyword && !strictMap.has(value)) {
        strictMap.set(value, { raw, value, context });
      }
    }

    return Array.from(strictMap.values()).slice(0, 12);
  }

  function getHost() {
    return location.hostname.replace(/^www\./, '');
  }

  let debounceTimer = null;

  async function runScanAndSave() {
    if (!document.body || !chrome.runtime || !chrome.runtime.id) return;
    const host = getHost();

    try {
      const existing = await chrome.storage.local.get(host);
      if (existing[host]) {
        // ja tem um saldo salvo pra essa casa - so muda por edicao manual,
        // pra nao sobrescrever quando trocar de login na mesma casa.
        return;
      }

      const strict = scan();
      if (strict.length === 1) {
        const value = strict[0].value;
        await chrome.storage.local.set({
          [host]: { value, updated: Date.now(), auto: true },
        });
        await chrome.storage.local.remove('_pending_' + host);
      } else if (strict.length > 1) {
        await chrome.storage.local.set({
          ['_pending_' + host]: { candidates: strict, updated: Date.now() },
        });
      }
    } catch (e) {
      // extension context may have been invalidated (e.g. reload) - ignore silently
    }
  }

  function scheduleScan() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(runScanAndSave, 1500);
  }

  scheduleScan();

  const observer = new MutationObserver(() => scheduleScan());
  if (document.documentElement) {
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  }
})();
