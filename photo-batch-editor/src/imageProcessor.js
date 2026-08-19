const sharp = require('sharp');
const { clamp } = require('./adjustments/types');

// Converte o AdjustmentSet (exposicao/contraste/temperatura/tint) em uma
// unica transformacao linear por canal: out = mul[c] * in + offset[c].
// Isso evita varias passadas de processamento e mantem o pipeline rapido.
function computeLinearParams(adj) {
  const expMul = Math.pow(2, adj.exposureEV);
  const contrastSlope = 1 + (adj.contrast / 100) * 0.5;

  const rTempMul = 1 + (adj.temperature / 100) * 0.3;
  const bTempMul = 1 - (adj.temperature / 100) * 0.3;
  const gTintMul = 1 - (adj.tint / 100) * 0.2;
  const rTintMul = 1 + (adj.tint / 100) * 0.1;
  const bTintMul = 1 + (adj.tint / 100) * 0.1;

  const rMul = clamp(contrastSlope * expMul * rTempMul * rTintMul, 0.2, 3.5);
  const gMul = clamp(contrastSlope * expMul * gTintMul, 0.2, 3.5);
  const bMul = clamp(contrastSlope * expMul * bTempMul * bTintMul, 0.2, 3.5);

  const offset = 128 * (1 - contrastSlope);

  return { mul: [rMul, gMul, bMul], offset: [offset, offset, offset] };
}

// Sombras/altas-luzes sao aproximadas por uma correcao de gamma: abrir
// sombras usa gamma > 1 (clareia meios-tons/sombras mais que as altas
// luzes); recuperar altas luzes reduz esse mesmo efeito. E uma aproximacao
// deliberada (sharp so aceita gamma >= 1), documentada aqui por ser a parte
// menos "exata" do pipeline.
function computeGamma(adj) {
  const gamma = 1 + (adj.shadows / 100) * 0.4 - (adj.highlights / 100) * 0.15;
  return clamp(gamma, 1, 2.5);
}

async function applyAdjustments(inputBuffer, adjustment, { maxWidth } = {}) {
  const { mul, offset } = computeLinearParams(adjustment);

  let pipeline = sharp(inputBuffer).rotate(); // auto-orienta pelo EXIF

  if (maxWidth) {
    pipeline = pipeline.resize({ width: maxWidth, withoutEnlargement: true });
  }

  pipeline = pipeline.linear(mul, offset);

  const gamma = computeGamma(adjustment);
  if (gamma > 1.001) {
    pipeline = pipeline.gamma(gamma);
  }

  if (adjustment.grayscale) {
    // Usa toColourspace('b-w') em vez de .grayscale(): o sharp reordena a
    // conversao de espaco de cor para antes do .linear() internamente, e
    // .grayscale() antes de um linear() com array por canal falha com
    // "Band expansion using linear is unsupported". toColourspace('b-w')
    // nao sofre esse reordenamento.
    pipeline = pipeline.toColourspace('b-w');
  } else {
    const saturationMul = clamp(1 + adjustment.saturation / 100, 0, 2.5);
    pipeline = pipeline.modulate({ saturation: saturationMul });
  }

  return pipeline.withMetadata().jpeg({ quality: 90, mozjpeg: true }).toBuffer();
}

async function buildPreviewDataUrl(buffer, adjustment) {
  const editedThumb = await applyAdjustments(buffer, adjustment, { maxWidth: 480 });
  return `data:image/jpeg;base64,${editedThumb.toString('base64')}`;
}

async function buildOriginalPreviewDataUrl(buffer) {
  const thumb = await sharp(buffer)
    .rotate()
    .resize({ width: 480, withoutEnlargement: true })
    .jpeg({ quality: 85 })
    .toBuffer();
  return `data:image/jpeg;base64,${thumb.toString('base64')}`;
}

module.exports = {
  applyAdjustments,
  buildPreviewDataUrl,
  buildOriginalPreviewDataUrl,
  computeLinearParams,
  computeGamma,
};
