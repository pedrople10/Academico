const fs = require('fs');
const os = require('os');
const path = require('path');
const express = require('express');
const multer = require('multer');
const archiver = require('archiver');

const { analyzeImage } = require('./adjustments/autoAnalyzer');
const { interpretPrompt } = require('./adjustments/promptInterpreter');
const { mergeAdjustments } = require('./adjustments/merge');
const {
  applyAdjustments,
  buildPreviewDataUrl,
  buildOriginalPreviewDataUrl,
} = require('./imageProcessor');
const { buildSidecarXmp, buildDevelopPresetXmp } = require('./xmpExporter');
const { createSessionDir, createSession, getSession, removeDir } = require('./sessionStore');
const { clampAdjustment } = require('./adjustments/types');

const app = express();
const PORT = process.env.PORT || 3000;

// Limites configuraveis por variavel de ambiente (ver render.yaml).
const MAX_FILES = Number(process.env.MAX_FILES) || 300;
const MAX_FILE_SIZE_MB = Number(process.env.MAX_FILE_SIZE_MB) || 30;
const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;

// Uploads vao para o disco (pasta temporaria) em vez da memoria: um lote
// grande de fotos nao cabe nos 512MB de RAM do plano gratuito do Render.
const UPLOAD_DIR = path.join(os.tmpdir(), 'photo-batch-editor', 'uploads');
fs.mkdirSync(UPLOAD_DIR, { recursive: true });

const upload = multer({
  storage: multer.diskStorage({ destination: UPLOAD_DIR }),
  limits: { fileSize: MAX_FILE_SIZE_BYTES, files: MAX_FILES },
  // Sem isso, nomes com acento (ex.: "ação.jpg") chegam corrompidos e o
  // .xmp sidecar sai com nome diferente da foto original.
  defParamCharset: 'utf8',
  fileFilter: (req, file, cb) => {
    if (!file.mimetype || !file.mimetype.startsWith('image/')) {
      cb(new Error('Apenas arquivos de imagem sao aceitos.'));
      return;
    }
    cb(null, true);
  },
});

app.use(express.static(path.join(__dirname, '..', 'public')));

// Usado pelo Render (healthCheckPath) para saber se o servico subiu.
app.get('/healthz', (req, res) => res.json({ ok: true }));

// Expoe os limites para o front-end avisar antes de enviar.
app.get('/api/config', (req, res) => res.json({ maxFiles: MAX_FILES, maxFileSizeMB: MAX_FILE_SIZE_MB }));

function sanitizeBaseName(originalName) {
  const base = path.basename(originalName || 'foto');
  const withoutExt = base.replace(/\.[^.]+$/, '');
  const cleaned = withoutExt.replace(/[^a-zA-Z0-9_\-. ]/g, '_').trim();
  return cleaned || 'foto';
}

// Nome-base para o .xmp sidecar: precisa ser IDENTICO ao da foto original
// para o Lightroom associar (foto1.CR2 -> foto1.xmp). Remove so caracteres
// invalidos em nomes de arquivo, preservando acentos e espacos.
function sidecarBaseName(originalName) {
  const base = path.basename(originalName || 'foto').replace(/\.[^.]+$/, '');
  const cleaned = base.replace(/[\\/:*?"<>|\x00-\x1f]/g, '_').trim();
  return cleaned || 'foto';
}

// Evita que duas fotos com o mesmo nome (de pastas diferentes) se
// sobrescrevam dentro do .zip: a segunda vira "foto (2)", etc.
function makeUniqueNamer() {
  const used = new Set();
  return (name) => {
    let candidate = name;
    let n = 2;
    while (used.has(candidate.toLowerCase())) {
      candidate = `${name} (${n})`;
      n += 1;
    }
    used.add(candidate.toLowerCase());
    return candidate;
  };
}

function removeUploadedFiles(files) {
  for (const file of files) {
    if (file.path) fs.rm(file.path, { force: true }, () => {});
  }
}

const MAX_CUSTOM_RULES = 50;

// Regras opcionais tipo "fotos cujo nome termina em X recebem esse
// brilho/contraste extra" (ex.: nome termina em "69"). Vem do front-end
// como JSON no campo customRules do form-data.
function parseCustomRules(raw) {
  if (!raw) return [];
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];

  return parsed
    .slice(0, MAX_CUSTOM_RULES)
    .map((r) => ({
      match: typeof r.match === 'string' ? r.match.trim() : '',
      exposureEV: Number(r.exposureEV) || 0,
      contrast: Number(r.contrast) || 0,
    }))
    .filter((r) => r.match.length > 0);
}

function ruleMatchesFile(originalName, matchText) {
  const base = path.basename(originalName || '').replace(/\.[^.]+$/, '');
  return base.toLowerCase().endsWith(matchText.toLowerCase());
}

// Aplica, por cima do ajuste automatico+prompt ja calculado, o
// brilho/contraste extra de toda regra cujo padrao bate com o final do
// nome do arquivo (sem extensao). Varias regras podem se acumular na
// mesma foto.
function applyCustomRules(adjustment, originalName, rules) {
  let result = adjustment;
  let matchedRule = null;

  for (const rule of rules) {
    if (!ruleMatchesFile(originalName, rule.match)) continue;
    matchedRule = rule.match;
    result = {
      ...result,
      exposureEV: result.exposureEV + rule.exposureEV,
      contrast: result.contrast + rule.contrast,
    };
  }

  return { adjustment: clampAdjustment(result), matchedRule };
}

function averageAdjustment(adjustments) {
  if (adjustments.length === 0) {
    return {
      exposureEV: 0,
      contrast: 0,
      temperature: 0,
      tint: 0,
      saturation: 0,
      shadows: 0,
      highlights: 0,
      grayscale: false,
    };
  }
  const sum = adjustments.reduce(
    (acc, adj) => {
      acc.exposureEV += adj.exposureEV;
      acc.contrast += adj.contrast;
      acc.temperature += adj.temperature;
      acc.tint += adj.tint;
      acc.saturation += adj.saturation;
      acc.shadows += adj.shadows;
      acc.highlights += adj.highlights;
      acc.grayscaleVotes += adj.grayscale ? 1 : 0;
      return acc;
    },
    {
      exposureEV: 0,
      contrast: 0,
      temperature: 0,
      tint: 0,
      saturation: 0,
      shadows: 0,
      highlights: 0,
      grayscaleVotes: 0,
    }
  );
  const n = adjustments.length;
  return {
    exposureEV: sum.exposureEV / n,
    contrast: sum.contrast / n,
    temperature: sum.temperature / n,
    tint: sum.tint / n,
    saturation: sum.saturation / n,
    shadows: sum.shadows / n,
    highlights: sum.highlights / n,
    grayscale: sum.grayscaleVotes > n / 2,
  };
}

app.post('/api/process', (req, res) => {
  upload.array('photos', MAX_FILES)(req, res, async (err) => {
    if (err) {
      if (err.code === 'LIMIT_FILE_COUNT') {
        return res.status(400).json({
          error: `Voce enviou fotos demais de uma vez. O limite e ${MAX_FILES} fotos por lote — separe em grupos menores.`,
        });
      }
      if (err.code === 'LIMIT_FILE_SIZE') {
        return res.status(400).json({
          error: `Uma das fotos passa do tamanho maximo permitido (${MAX_FILE_SIZE_BYTES / 1024 / 1024}MB).`,
        });
      }
      return res.status(400).json({ error: err.message });
    }

    const files = req.files || [];
    if (files.length === 0) {
      return res.status(400).json({ error: 'Envie pelo menos uma foto.' });
    }

    const promptText = typeof req.body.prompt === 'string' ? req.body.prompt : '';
    const autoIntensityRaw = Number(req.body.autoIntensity);
    const autoIntensity = Number.isFinite(autoIntensityRaw) ? autoIntensityRaw : 100;

    const { adjustment: promptAdjustment, matchedRules } = interpretPrompt(promptText);
    const customRules = parseCustomRules(req.body.customRules);

    const { id: sessionId, dir: sessionDir } = createSessionDir();
    const uniqueEditedName = makeUniqueNamer();
    const uniqueSidecarName = makeUniqueNamer();

    try {
      const processed = [];
      const failed = [];
      const finalAdjustments = [];

      // Uma foto por vez: processar o lote em paralelo estouraria a memoria.
      // Se uma foto falhar (arquivo corrompido, formato nao suportado como
      // HEIC/RAW), ela e listada em "failed" e o resto do lote continua.
      for (const file of files) {
        try {
          const autoAdjustment = await analyzeImage(file.path);
          const mergedAdjustment = mergeAdjustments(autoAdjustment, promptAdjustment, autoIntensity);
          const { adjustment: finalAdjustment, matchedRule: matchedCustomRule } = applyCustomRules(
            mergedAdjustment,
            file.originalname,
            customRules
          );

          const editedName = `${uniqueEditedName(sanitizeBaseName(file.originalname))}_editado.jpg`;
          const editedBuffer = await applyAdjustments(file.path, finalAdjustment);
          await fs.promises.writeFile(path.join(sessionDir, editedName), editedBuffer);

          const beforeDataUrl = await buildOriginalPreviewDataUrl(file.path);
          const afterDataUrl = await buildPreviewDataUrl(file.path, finalAdjustment);

          finalAdjustments.push(finalAdjustment);
          processed.push({
            originalName: file.originalname,
            editedName,
            sidecarName: `${uniqueSidecarName(sidecarBaseName(file.originalname))}.xmp`,
            beforeDataUrl,
            afterDataUrl,
            xmp: buildSidecarXmp(finalAdjustment),
            adjustment: finalAdjustment,
            matchedCustomRule,
          });
        } catch (photoError) {
          console.error(`Erro ao processar ${file.originalname}:`, photoError.message);
          failed.push(file.originalname);
        }
      }

      if (processed.length === 0) {
        removeDir(sessionDir);
        return res.status(400).json({
          error: 'Nenhuma foto pode ser processada. Use JPEG, PNG, WebP ou TIFF (HEIC e RAW nao sao suportados).',
          failed,
        });
      }

      const avgAdjustment = averageAdjustment(finalAdjustments);
      const presetName = `Lote ${new Date().toISOString().slice(0, 10)}`;
      const presetXmp = buildDevelopPresetXmp(avgAdjustment, presetName);

      createSession(sessionId, sessionDir, {
        photos: processed.map((p) => ({
          editedName: p.editedName,
          sidecarName: p.sidecarName,
          xmp: p.xmp,
        })),
        presetXmp,
        presetName,
      });

      res.json({
        sessionId,
        matchedRules,
        failed,
        photos: processed.map((p) => ({
          originalName: p.originalName,
          beforeDataUrl: p.beforeDataUrl,
          afterDataUrl: p.afterDataUrl,
          matchedCustomRule: p.matchedCustomRule,
          adjustment: {
            exposureEV: Number(p.adjustment.exposureEV.toFixed(2)),
            contrast: Math.round(p.adjustment.contrast),
            temperature: Math.round(p.adjustment.temperature),
            tint: Math.round(p.adjustment.tint),
            saturation: Math.round(p.adjustment.saturation),
            shadows: Math.round(p.adjustment.shadows),
            highlights: Math.round(p.adjustment.highlights),
            grayscale: p.adjustment.grayscale,
          },
        })),
      });
    } catch (processingError) {
      console.error('Erro ao processar fotos:', processingError);
      removeDir(sessionDir);
      res.status(500).json({ error: 'Falha ao processar as fotos.' });
    } finally {
      removeUploadedFiles(files);
    }
  });
});

const README_TEMPLATE = `Photo Batch Editor - pacote de exportacao
==========================================

Esta pasta contem:

1. editado/
   Fotos ja editadas em JPEG, prontas para usar em qualquer lugar.

2. xmp-para-originais/
   Um arquivo .xmp para cada foto, com o MESMO nome-base do arquivo
   original (ex.: foto1.CR2 -> foto1.xmp). Para aplicar os ajustes
   de forma NAO destrutiva direto no Lightroom Classic:
     a) Copie o(s) arquivo(s) .xmp para a MESMA pasta dos arquivos
        originais (RAW ou JPEG), mantendo o nome-base identico.
     b) No Lightroom Classic, selecione as fotos no Catalogo e va em
        Metadados > Ler Configuracoes de Metadados (ou clique com o
        botao direito > Metadados > Ler Configuracoes de Metadados).
     c) O Lightroom vai importar Exposicao, Contraste, Temperatura,
        Tinta, Saturacao, Sombras e Altas Luzes calculados para cada foto.

3. preset-lightroom/
   Um arquivo .xmp de predefinicao de revelacao com a media dos ajustes
   calculados para todo o lote. Para importar:
     a) Modulo Revelar > painel Predefinicoes > botao "+" >
        Importar Predefinicoes...
     b) Selecione o arquivo .xmp desta pasta.
     c) A predefinicao aparecera na lista para aplicar em 1 clique em
        qualquer foto (inclusive fora deste lote).

Todos os ajustes sao calculados automaticamente a partir de cada foto
(exposicao, contraste e balanco de branco) e, quando um prompt de texto
foi usado, combinados com o pedido descrito (ex.: "mais quente e com
mais contraste", "preto e branco", "cinematic").
`;

app.get('/api/download/:sessionId', (req, res) => {
  const session = getSession(req.params.sessionId);
  if (!session) {
    return res.status(404).json({ error: 'Sessao expirada ou inexistente. Processe as fotos novamente.' });
  }

  res.setHeader('Content-Type', 'application/zip');
  res.setHeader('Content-Disposition', 'attachment; filename="fotos-editadas.zip"');

  // JPEG ja e comprimido: zlib nivel 9 so deixaria o download mais lento.
  const archive = archiver('zip', { zlib: { level: 1 } });
  archive.on('error', (archiveError) => {
    // Os cabecalhos ja foram enviados, entao nao da para mudar o status:
    // so encerra a conexao para o navegador acusar download incompleto.
    console.error('Erro ao gerar zip:', archiveError);
    res.destroy(archiveError);
  });
  archive.pipe(res);

  for (const photo of session.photos) {
    archive.file(path.join(session.dir, photo.editedName), { name: `editado/${photo.editedName}` });
    archive.append(photo.xmp, { name: `xmp-para-originais/${photo.sidecarName}` });
  }

  archive.append(session.presetXmp, {
    name: `preset-lightroom/${session.presetName.replace(/[^a-zA-Z0-9_\- ]/g, '_')}.xmp`,
  });

  archive.append(README_TEMPLATE, { name: 'LEIA-ME.txt' });

  archive.finalize();
});

if (require.main === module) {
  app.listen(PORT, () => {
    console.log(`Photo Batch Editor rodando em http://localhost:${PORT}`);
  });
}

module.exports = app;
