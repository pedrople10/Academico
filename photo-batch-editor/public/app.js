(function () {
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('fileInput');
  const fileListEl = document.getElementById('fileList');
  const promptEl = document.getElementById('prompt');
  const chipsEl = document.getElementById('chips');
  const intensityEl = document.getElementById('intensity');
  const intensityValueEl = document.getElementById('intensityValue');
  const processBtn = document.getElementById('processBtn');
  const statusEl = document.getElementById('status');
  const resultsPanel = document.getElementById('resultsPanel');
  const resultsGrid = document.getElementById('resultsGrid');
  const matchedRulesEl = document.getElementById('matchedRules');
  const downloadBtn = document.getElementById('downloadBtn');
  const ruleMatchEl = document.getElementById('ruleMatch');
  const ruleExposureEl = document.getElementById('ruleExposure');
  const ruleExposureValueEl = document.getElementById('ruleExposureValue');
  const ruleContrastEl = document.getElementById('ruleContrast');
  const ruleContrastValueEl = document.getElementById('ruleContrastValue');
  const addRuleBtn = document.getElementById('addRuleBtn');
  const rulesListEl = document.getElementById('rulesList');

  let selectedFiles = [];
  let currentSessionId = null;
  let customRules = [];

  function refreshFileList() {
    fileListEl.innerHTML = '';
    selectedFiles.forEach((file, idx) => {
      const row = document.createElement('div');
      const name = document.createElement('span');
      name.textContent = file.name;
      const remove = document.createElement('a');
      remove.textContent = 'remover';
      remove.href = '#';
      remove.style.color = '#ff8080';
      remove.addEventListener('click', (ev) => {
        ev.preventDefault();
        selectedFiles.splice(idx, 1);
        refreshFileList();
      });
      row.appendChild(name);
      row.appendChild(remove);
      fileListEl.appendChild(row);
    });
    processBtn.disabled = selectedFiles.length === 0;
  }

  function addFiles(fileListLike) {
    const incoming = Array.from(fileListLike).filter((f) => f.type.startsWith('image/'));
    if (incoming.length === 0) return;
    selectedFiles = selectedFiles.concat(incoming);
    refreshFileList();
    // Edita automaticamente assim que as fotos sao soltas/selecionadas —
    // nao precisa escrever prompt nem clicar em nada, o ajuste automatico
    // ja roda sozinho. O prompt/intensidade continuam disponiveis para
    // refinar depois com o botao "Processar fotos".
    processPhotos();
  }

  dropzone.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', (e) => addFiles(e.target.files));

  ['dragenter', 'dragover'].forEach((evtName) => {
    dropzone.addEventListener(evtName, (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });
  });
  ['dragleave', 'drop'].forEach((evtName) => {
    dropzone.addEventListener(evtName, (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
    });
  });
  dropzone.addEventListener('drop', (e) => {
    if (e.dataTransfer && e.dataTransfer.files) {
      addFiles(e.dataTransfer.files);
    }
  });

  chipsEl.addEventListener('click', (e) => {
    const btn = e.target.closest('.chip');
    if (!btn) return;
    const text = btn.dataset.text;
    promptEl.value = promptEl.value.trim() ? `${promptEl.value.trim()}, ${text}` : text;
  });

  intensityEl.addEventListener('input', () => {
    intensityValueEl.textContent = `${intensityEl.value}%`;
  });

  ruleExposureEl.addEventListener('input', () => {
    ruleExposureValueEl.textContent = ruleExposureEl.value;
  });
  ruleContrastEl.addEventListener('input', () => {
    ruleContrastValueEl.textContent = ruleContrastEl.value;
  });

  function renderRulesList() {
    rulesListEl.innerHTML = '';
    customRules.forEach((rule, idx) => {
      const row = document.createElement('div');
      const label = document.createElement('span');
      const parts = [];
      if (rule.exposureEV !== 0) parts.push(`brilho ${rule.exposureEV > 0 ? '+' : ''}${rule.exposureEV.toFixed(2)}`);
      if (rule.contrast !== 0) parts.push(`contraste ${rule.contrast > 0 ? '+' : ''}${rule.contrast}`);
      label.textContent = `Termina em "${rule.match}": ${parts.join(', ') || 'sem alteracao'}`;
      const remove = document.createElement('a');
      remove.textContent = 'remover';
      remove.href = '#';
      remove.style.color = '#ff8080';
      remove.addEventListener('click', (ev) => {
        ev.preventDefault();
        customRules.splice(idx, 1);
        renderRulesList();
        if (selectedFiles.length > 0) processPhotos();
      });
      row.appendChild(label);
      row.appendChild(remove);
      rulesListEl.appendChild(row);
    });
  }

  addRuleBtn.addEventListener('click', () => {
    const match = ruleMatchEl.value.trim();
    if (!match) {
      setStatus('Escreva o final do nome do arquivo para criar a regra (ex.: 69).', 'error');
      return;
    }
    const exposureEV = (Number(ruleExposureEl.value) / 100) * 1.5;
    const contrast = Number(ruleContrastEl.value);
    customRules.push({ match, exposureEV, contrast });
    renderRulesList();

    ruleMatchEl.value = '';
    ruleExposureEl.value = 0;
    ruleContrastEl.value = 0;
    ruleExposureValueEl.textContent = '0';
    ruleContrastValueEl.textContent = '0';

    if (selectedFiles.length > 0) processPhotos();
  });

  function setStatus(message, kind) {
    statusEl.textContent = message || '';
    statusEl.className = `status ${kind || ''}`.trim();
  }

  function adjustmentTags(adj) {
    const tags = [];
    if (Math.abs(adj.exposureEV) > 0.05) tags.push(`Exposicao ${adj.exposureEV > 0 ? '+' : ''}${adj.exposureEV}`);
    if (Math.abs(adj.contrast) > 1) tags.push(`Contraste ${adj.contrast > 0 ? '+' : ''}${adj.contrast}`);
    if (Math.abs(adj.temperature) > 1) tags.push(`Temp. ${adj.temperature > 0 ? '+' : ''}${adj.temperature}`);
    if (Math.abs(adj.tint) > 1) tags.push(`Tint ${adj.tint > 0 ? '+' : ''}${adj.tint}`);
    if (Math.abs(adj.saturation) > 1) tags.push(`Saturacao ${adj.saturation > 0 ? '+' : ''}${adj.saturation}`);
    if (Math.abs(adj.shadows) > 1) tags.push(`Sombras ${adj.shadows > 0 ? '+' : ''}${adj.shadows}`);
    if (Math.abs(adj.highlights) > 1) tags.push(`Luzes ${adj.highlights > 0 ? '+' : ''}${adj.highlights}`);
    if (adj.grayscale) tags.push('P&B');
    return tags;
  }

  function renderResults(data) {
    resultsGrid.innerHTML = '';
    data.photos.forEach((photo) => {
      const card = document.createElement('div');
      card.className = 'result-card';

      const compare = document.createElement('div');
      compare.className = 'compare';
      const beforeImg = document.createElement('img');
      beforeImg.src = photo.beforeDataUrl;
      const afterImg = document.createElement('img');
      afterImg.src = photo.afterDataUrl;
      compare.appendChild(beforeImg);
      compare.appendChild(afterImg);

      const compareLabel = document.createElement('div');
      compareLabel.className = 'compare-label';
      compareLabel.innerHTML = '<span>antes</span><span>depois</span>';

      const meta = document.createElement('div');
      meta.className = 'meta';
      const filename = document.createElement('div');
      filename.className = 'filename';
      filename.textContent = photo.originalName;
      const tagsWrap = document.createElement('div');
      tagsWrap.className = 'adjustments';
      const tags = adjustmentTags(photo.adjustment);
      if (photo.matchedCustomRule) tags.push(`Regra: termina em "${photo.matchedCustomRule}"`);
      tags.forEach((t) => {
        const tag = document.createElement('span');
        tag.className = 'tag';
        tag.textContent = t;
        tagsWrap.appendChild(tag);
      });

      meta.appendChild(filename);
      meta.appendChild(tagsWrap);

      card.appendChild(compare);
      card.appendChild(compareLabel);
      card.appendChild(meta);
      resultsGrid.appendChild(card);
    });

    if (data.matchedRules && data.matchedRules.length > 0) {
      matchedRulesEl.textContent = `Prompt interpretado: ${data.matchedRules.join(', ')}`;
    } else {
      matchedRulesEl.textContent = 'Nenhum termo de prompt reconhecido — aplicado apenas o ajuste automatico.';
    }

    resultsPanel.hidden = false;
  }

  async function processPhotos() {
    if (selectedFiles.length === 0) return;

    processBtn.disabled = true;
    setStatus(`Editando ${selectedFiles.length} foto(s) automaticamente...`);

    const formData = new FormData();
    selectedFiles.forEach((file) => formData.append('photos', file));
    formData.append('prompt', promptEl.value);
    formData.append('autoIntensity', intensityEl.value);
    formData.append('customRules', JSON.stringify(customRules));

    try {
      const response = await fetch('/api/process', { method: 'POST', body: formData });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || 'Falha ao processar as fotos.');
      }

      currentSessionId = data.sessionId;
      renderResults(data);
      setStatus(`Pronto! ${data.photos.length} foto(s) editada(s) automaticamente.`, 'ok');
    } catch (err) {
      setStatus(err.message, 'error');
    } finally {
      processBtn.disabled = selectedFiles.length === 0;
    }
  }

  processBtn.addEventListener('click', () => processPhotos());

  downloadBtn.addEventListener('click', () => {
    if (!currentSessionId) return;
    window.location.href = `/api/download/${currentSessionId}`;
  });
})();
