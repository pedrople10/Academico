// Cliente da API da Anthropic (Claude) usado para analisar as fotos do
// produto e gerar os dados sugeridos do anúncio (título, descrição, etc).
//
// Referência: https://docs.claude.com/en/api/messages

import { storage } from "./storage.js";

const API_URL = "https://api.anthropic.com/v1/messages";
const ANTHROPIC_VERSION = "2023-06-01";

const SYSTEM_PROMPT = `Você é um especialista em criar anúncios de venda no Mercado Livre (Brasil).
Analise as fotos de um produto enviadas pelo usuário e responda APENAS com um JSON válido,
sem markdown, sem comentários, no seguinte formato exato:

{
  "title": "título do anúncio, até 60 caracteres, sem emojis, no estilo Mercado Livre",
  "description": "descrição de venda completa e persuasiva, em texto simples, várias frases",
  "condition": "new" ou "used",
  "suggested_price_brl": número (preço sugerido em reais, sua melhor estimativa de mercado) ou null,
  "category_search_query": "termo curto de busca para encontrar a categoria certa no Mercado Livre, ex: 'tênis de corrida masculino'",
  "brand": "marca identificada" ou null,
  "model": "modelo identificado" ou null,
  "color": "cor predominante" ou null,
  "attributes": [{"name": "nome do atributo em português", "value": "valor identificado"}],
  "notes": "qualquer observação relevante para o vendedor revisar antes de publicar"
}

Seja honesto: se não tiver certeza de um campo, use null em vez de inventar.`;

async function fileToBase64(dataUrl) {
  // dataUrl já vem como "data:image/jpeg;base64,...."
  const [, base64] = dataUrl.split(",");
  return base64;
}

function mediaTypeFromDataUrl(dataUrl) {
  const match = /^data:([^;]+);base64,/.exec(dataUrl);
  return match ? match[1] : "image/jpeg";
}

function extractJson(text) {
  const cleaned = text
    .trim()
    .replace(/^```(?:json)?/i, "")
    .replace(/```$/, "")
    .trim();
  return JSON.parse(cleaned);
}

// images: array de data URLs (base64) das fotos enviadas pelo usuário.
export async function analyzeProductImages(images) {
  const { apiKey, model } = await storage.getAiConfig();
  if (!apiKey) {
    throw new Error(
      "Configure sua chave de API da Anthropic nas opções da extensão."
    );
  }
  if (!images || images.length === 0) {
    throw new Error("Envie pelo menos uma foto do produto.");
  }

  const imageBlocks = await Promise.all(
    images.map(async (dataUrl) => ({
      type: "image",
      source: {
        type: "base64",
        media_type: mediaTypeFromDataUrl(dataUrl),
        data: await fileToBase64(dataUrl),
      },
    }))
  );

  const response = await fetch(API_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": ANTHROPIC_VERSION,
      "anthropic-dangerous-direct-browser-access": "true",
    },
    body: JSON.stringify({
      model: model || "claude-sonnet-5",
      max_tokens: 1500,
      system: SYSTEM_PROMPT,
      messages: [
        {
          role: "user",
          content: [
            ...imageBlocks,
            {
              type: "text",
              text: "Analise estas fotos e gere os dados do anúncio conforme o formato pedido.",
            },
          ],
        },
      ],
    }),
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(
      `Falha ao chamar a API da Anthropic: ${data.error?.message || response.status}`
    );
  }

  const text = data.content?.[0]?.text;
  if (!text) {
    throw new Error("A IA não retornou nenhum conteúdo analisável.");
  }

  try {
    return extractJson(text);
  } catch {
    throw new Error(
      "Não foi possível interpretar a resposta da IA como JSON. Tente novamente."
    );
  }
}
