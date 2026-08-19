const { clampAdjustment } = require('./types');

// Combina o baseline automatico (escalado pela intensidade escolhida pelo
// usuario) com os deltas vindos do prompt de texto, produzindo o
// AdjustmentSet final que sera aplicado na foto.
function mergeAdjustments(autoAdjustment, promptAdjustment, autoIntensityPercent) {
  const intensity = Math.max(0, Math.min(150, autoIntensityPercent)) / 100;

  const merged = {
    exposureEV: autoAdjustment.exposureEV * intensity + promptAdjustment.exposureEV,
    contrast: autoAdjustment.contrast * intensity + promptAdjustment.contrast,
    temperature: autoAdjustment.temperature * intensity + promptAdjustment.temperature,
    tint: autoAdjustment.tint * intensity + promptAdjustment.tint,
    saturation: autoAdjustment.saturation * intensity + promptAdjustment.saturation,
    shadows: autoAdjustment.shadows * intensity + promptAdjustment.shadows,
    highlights: autoAdjustment.highlights * intensity + promptAdjustment.highlights,
    grayscale: promptAdjustment.grayscale || autoAdjustment.grayscale,
  };

  return clampAdjustment(merged);
}

module.exports = { mergeAdjustments };
