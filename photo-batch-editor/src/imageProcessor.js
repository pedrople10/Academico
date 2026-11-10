const sharp = require('sharp');
const { clamp } = require('./adjustments/types');

// Menos memoria no servidor (importante no plano gratuito do Render, 512MB).
sharp.cache(false);

// Abre a foto ja auto-orientada (EXIF) e garantindo 3 canais RGB.
// Fotos em escala de cinza (1 canal) quebram o .linear() por canal
// ("Band expansion using linear is unsupported") e a analise automatica,
// entao elas sao convertidas para sRGB numa passada previa em raw.
// `input` pode ser um Buffer ou o caminho de um arquivo.
async function openRgb(input) {
  const meta = await sharp(input).metadata();
  if ((meta.channels || 3) >= 3) {
    return { image: sharp(input).rotate(), keepMetadata: true };
  }
  const { data, info } = await sharp(input)
    .rotate()
    .toColourspace('srgb')
    .raw()
    .toBuffer({ resolveWithObject: true });
  return {
    image: sharp(data, { raw: { width: info.width, height: info.height, channels: info.channels } }),
    keepMetadata: false,
  };
}

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

async function applyAdjustments(input, adjustment, { maxWidth } = {}) {
  const { mul, offset } = computeLinearParams(adjustment);

  const { image, keepMetadata } = await openRgb(input);
  let pipeline = image;

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

  if (keepMetadata) pipeline = pipeline.withMetadata();
  // Fundo branco para PNGs transparentes (JPEG nao tem canal alfa).
  pipeline = pipeline.flatten({ background: '#ffffff' });
  return pipeline.jpeg({ quality: 90, mozjpeg: true }).toBuffer();
}

async function buildPreviewDataUrl(input, adjustment) {
  const editedThumb = await applyAdjustments(input, adjustment, { maxWidth: 480 });
  return `data:image/jpeg;base64,${editedThumb.toString('base64')}`;
}

async function buildOriginalPreviewDataUrl(input) {
  const thumb = await sharp(input)
    .rotate()
    .flatten({ background: '#ffffff' })
    .resize({ width: 480, withoutEnlargement: true })
    .jpeg({ quality: 85 })
    .toBuffer();
  return `data:image/jpeg;base64,${thumb.toString('base64')}`;
}

module.exports = {
  openRgb,
  applyAdjustments,
  buildPreviewDataUrl,
  buildOriginalPreviewDataUrl,
  computeLinearParams,
  computeGamma,
};
