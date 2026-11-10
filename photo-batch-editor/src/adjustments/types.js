function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

// AdjustmentSet: conjunto neutro de ajustes que tanto o motor automatico
// quanto o interpretador de prompt produzem, para depois serem somados.
function emptyAdjustment() {
  return {
    exposureEV: 0, // stops (-2..2)
    contrast: 0, // -100..100
    temperature: 0, // -100 (frio/azul) .. 100 (quente/laranja)
    tint: 0, // -100 (verde) .. 100 (magenta)
    saturation: 0, // -100..100
    shadows: 0, // -100..100 (positivo = abre sombras)
    highlights: 0, // -100..100 (positivo = recupera altas luzes)
    grayscale: false,
  };
}

function clampAdjustment(adj) {
  return {
    exposureEV: clamp(adj.exposureEV, -2, 2),
    contrast: clamp(adj.contrast, -80, 80),
    temperature: clamp(adj.temperature, -80, 80),
    tint: clamp(adj.tint, -60, 60),
    saturation: clamp(adj.saturation, -100, 100),
    shadows: clamp(adj.shadows, -100, 100),
    highlights: clamp(adj.highlights, -100, 100),
    grayscale: !!adj.grayscale,
  };
}

module.exports = { clamp, emptyAdjustment, clampAdjustment };
