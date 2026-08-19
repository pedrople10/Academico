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
const { createSession, getSession } = require('./sessionStore');

const app = express();
const PORT = process.env.PORT || 3000;

const MAX_FILES = 60;
const MAX_FILE_SIZE_BYTES = 30 * 1024 * 1024; // 30MB por foto

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: MAX_FILE_SIZE_BYTES, files: MAX_FILES },
  fileFilter: (req, file, cb) => {
    if (!file.mimetype || !file.mimetype.startsWith('image/')) {
      cb(new Error('Apenas arquivos de imagem sao aceitos.'));
      return;
    }
    cb(null, true);
  },
});

app.use(express.static(path.join(__dirname, '..', 'public')));
app.use(express.json());

function sanitizeBaseName(originalName) {
  const base = path.basename(originalName || 'foto');
  const withoutExt = base.replace(/\.[^.]+$/, '');
  const cleaned = withoutExt.replace(/[^a-zA-Z0-9_\-. ]/g, '_').trim();
  return cleaned || 'foto';
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

    try {
      const processed = [];
      const finalAdjustments = [];

      for (const file of files) {
        const autoAdjustment = await analyzeImage(file.buffer);
        const finalAdjustment = mergeAdjustments(autoAdjustment, promptAdjustment, autoIntensity);
        finalAdjustments.push(finalAdjustment);

        const [beforeDataUrl, afterDataUrl, editedBuffer] = await Promise.all([
          buildOriginalPreviewDataUrl(file.buffer),
          buildPreviewDataUrl(file.buffer, finalAdjustment),
          applyAdjustments(file.buffer, finalAdjustment),
        ]);

        const baseName = sanitizeBaseName(file.originalname);
        const originalExt = path.extname(file.originalname || '').replace('.', '') || 'jpg';

        processed.push({
          baseName,
          originalExt,
          originalName: file.originalname,
          beforeDataUrl,
          afterDataUrl,
          editedBuffer,
          xmp: buildSidecarXmp(finalAdjustment),
          adjustment: finalAdjustment,
        });
      }

      const avgAdjustment = averageAdjustment(finalAdjustments);
      const presetName = `Lote ${new Date().toISOString().slice(0, 10)}`;
      const presetXmp = buildDevelopPresetXmp(avgAdjustment, presetName);

      const sessionId = createSession({
        photos: processed.map((p) => ({
          baseName: p.baseName,
          originalExt: p.originalExt,
          editedBuffer: p.editedBuffer,
          xmp: p.xmp,
        })),
        presetXmp,
        presetName,
      });

      res.json({
        sessionId,
        matchedRules,
        photos: processed.map((p) => ({
          originalName: p.originalName,
          beforeDataUrl: p.beforeDataUrl,
          afterDataUrl: p.afterDataUrl,
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
      res.status(500).json({ error: 'Falha ao processar uma ou mais fotos.' });
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
   original (ex.: foto1.jpg -> foto1.jpg.xmp). Para aplicar os ajustes
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

  const archive = archiver('zip', { zlib: { level: 9 } });
  archive.on('error', (archiveError) => {
    console.error('Erro ao gerar zip:', archiveError);
    res.status(500).end();
  });
  archive.pipe(res);

  for (const photo of session.photos) {
    archive.append(photo.editedBuffer, { name: `editado/${photo.baseName}_editado.jpg` });
    archive.append(photo.xmp, {
      name: `xmp-para-originais/${photo.baseName}.${photo.originalExt}.xmp`,
    });
  }

  archive.append(session.presetXmp, {
    name: `preset-lightroom/${session.presetName.replace(/[^a-zA-Z0-9_\- ]/g, '_')}.xmp`,
  });

  archive.append(README_TEMPLATE, { name: 'LEIA-ME.txt' });

  archive.finalize();
});

app.listen(PORT, () => {
  console.log(`Photo Batch Editor rodando em http://localhost:${PORT}`);
});

module.exports = app;
