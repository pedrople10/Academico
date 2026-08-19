const sharp = require('sharp');
const { clamp, emptyAdjustment } = require('./types');

// Analisa a foto (histograma/estatisticas por canal) e propoe um AdjustmentSet
// automatico: exposicao, contraste, balanco de branco (metodo "gray world")
// e saturacao. E uma correcao heuristica, nao colorimetricamente exata, mas
// e calculada a partir dos pixels reais de cada foto (nao e um valor fixo).
async function analyzeImage(buffer) {
  const image = sharp(buffer);
  const stats = await image.stats();
  const [rC, gC, bC] = stats.channels;

  const luminance = 0.2126 * rC.mean + 0.7152 * gC.mean + 0.0722 * bC.mean;

  // Exposicao: tenta levar a luminancia media para perto de 128 (meio-tom).
  const targetLuminance = 128;
  const exposureEV = clamp(
    Math.log2(targetLuminance / Math.max(luminance, 1)),
    -0.6,
    0.6
  );

  // Contraste: se o desvio padrao dos canais e baixo, a imagem esta "chapada"
  // (baixo contraste) e vale a pena realcar; se ja e alto, reduz um pouco.
  const avgStdev = (rC.stdev + gC.stdev + bC.stdev) / 3;
  const contrast = clamp((55 - avgStdev) * 1.1, -20, 35);

  // Balanco de branco por "gray world": assume que a media dos canais
  // deveria ser neutra (cinza). Desvios indicam dominante de cor.
  const grayMean = (rC.mean + gC.mean + bC.mean) / 3;
  const rDiff = rC.mean - grayMean;
  const gDiff = gC.mean - grayMean;
  const bDiff = bC.mean - grayMean;
  const temperature = clamp((bDiff - rDiff) * 0.8, -25, 25);
  const tint = clamp(-gDiff * 0.8, -20, 20);

  // Saturacao: mede a saturacao media (espaco HSV) e da um leve reforco
  // quando a imagem esta visualmente "sem vida".
  const hsvStats = await sharp(buffer).toColourspace('hsv').stats();
  const satMeanPct = (hsvStats.channels[1].mean / 255) * 100;
  const saturation = clamp((85 - satMeanPct) * 0.5, -5, 22);

  return {
    ...emptyAdjustment(),
    exposureEV,
    contrast,
    temperature,
    tint,
    saturation,
  };
}

module.exports = { analyzeImage };
