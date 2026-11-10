const { emptyAdjustment } = require('./types');

function normalize(text) {
  return text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, ''); // remove acentos
}

// Cada regra tem uma lista de padroes (ja normalizados, sem acento) e um
// delta a somar ao AdjustmentSet quando qualquer padrao aparece no prompt.
const RULES = [
  {
    patterns: ['mais quente', 'tom quente', 'quente', 'warm', 'warmer', 'dourad'],
    delta: { temperature: 20 },
  },
  {
    patterns: ['mais fria', 'mais frio', 'esfriar', 'tom frio', 'cool', 'cooler', 'azulad'],
    delta: { temperature: -20 },
  },
  {
    patterns: ['mais contraste', 'alto contraste', 'contrastad', 'high contrast', 'contrast'],
    delta: { contrast: 25 },
  },
  {
    patterns: ['menos contraste', 'baixo contraste', 'suave', 'flat', 'achatad'],
    delta: { contrast: -20 },
  },
  {
    patterns: ['mais saturad', 'vibrante', 'vivid', 'colorid', 'pop de cor'],
    delta: { saturation: 25 },
  },
  {
    patterns: ['menos saturad', 'dessaturad', 'desaturad', 'muted', 'pastel', 'sem cor'],
    delta: { saturation: -25 },
  },
  {
    patterns: [
      'preto e branco',
      'pretoebranco',
      'p&b',
      'p e b',
      'black and white',
      'black & white',
      'monocrom',
      'grayscale',
      'greyscale',
    ],
    delta: { grayscale: true },
  },
  {
    patterns: ['mais clara', 'mais claro', 'clarear', 'brighten', 'mais luz', 'mais brilho'],
    delta: { exposureEV: 0.4 },
  },
  {
    patterns: ['mais escura', 'mais escuro', 'escurecer', 'darken', 'menos luz', 'mais sombrio'],
    delta: { exposureEV: -0.4 },
  },
  {
    patterns: ['abrir sombra', 'realcar sombra', 'clarear sombra', 'lift shadows', 'shadows'],
    delta: { shadows: 30 },
  },
  {
    patterns: ['fechar sombra', 'sombra mais escura', 'crush shadows'],
    delta: { shadows: -25 },
  },
  {
    patterns: ['recuperar luz', 'recuperar altas luzes', 'recover highlights', 'highlights'],
    delta: { highlights: 30 },
  },
  {
    patterns: ['estourar luz', 'queimar luz', 'blown highlights'],
    delta: { highlights: -20 },
  },
  {
    patterns: ['cinematic', 'cinematograf', 'cinema'],
    delta: { temperature: 8, contrast: 15, saturation: -8, shadows: 12 },
  },
  {
    patterns: ['vintage', 'retro', 'analogic', 'filme antigo'],
    delta: { saturation: -15, temperature: 12, contrast: -10 },
  },
  {
    patterns: ['pele natural', 'retrato natural', 'natural'],
    delta: { saturation: -6, contrast: -4 },
  },
  {
    patterns: ['paisagem', 'nature', 'natureza vibrante'],
    delta: { saturation: 18, contrast: 12 },
  },
];

// Interpreta um prompt em texto livre (PT-BR ou EN) e devolve um AdjustmentSet
// com os deltas de todas as regras que casaram. Regras baseadas em palavras
// -chave: nao depende de nenhuma API externa, funciona 100% offline.
function interpretPrompt(promptText) {
  const result = emptyAdjustment();
  if (!promptText || !promptText.trim()) {
    return { adjustment: result, matchedRules: [] };
  }

  const normalized = normalize(promptText);
  const matchedRules = [];

  for (const rule of RULES) {
    const hit = rule.patterns.some((pattern) => normalized.includes(pattern));
    if (!hit) continue;

    matchedRules.push(rule.patterns[0]);
    for (const [key, value] of Object.entries(rule.delta)) {
      if (key === 'grayscale') {
        result.grayscale = result.grayscale || value;
      } else {
        result[key] += value;
      }
    }
  }

  return { adjustment: result, matchedRules };
}

module.exports = { interpretPrompt, normalize, RULES };
