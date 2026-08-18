// Domínio de autorização OAuth varia por país no Mercado Livre.
// A API (api.mercadolibre.com) é única para todos os países.
export const AUTH_DOMAINS = {
  MLA: "auth.mercadolibre.com.ar", // Argentina
  MLB: "auth.mercadolivre.com.br", // Brasil
  MLC: "auth.mercadolibre.cl", // Chile
  MCO: "auth.mercadolibre.com.co", // Colômbia
  MLM: "auth.mercadolibre.com.mx", // México
  MLU: "auth.mercadolibre.com.uy", // Uruguai
  MPE: "auth.mercadolibre.com.pe", // Peru
};

export function authDomainFor(siteId) {
  return AUTH_DOMAINS[siteId] || AUTH_DOMAINS.MLB;
}
