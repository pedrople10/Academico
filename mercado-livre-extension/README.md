# Anúncios ML por Imagem

Extensão para Chrome/Edge (Manifest V3) que gera e publica anúncios no
Mercado Livre a partir de fotos de um produto: você envia as imagens, a IA
(Claude, da Anthropic) analisa e sugere título, descrição, categoria,
condição, preço e atributos; você revisa numa tela e publica direto via
API oficial do Mercado Livre.

## Como funciona

1. **Popup**: você arrasta/seleciona as fotos do produto.
2. **IA**: as fotos são enviadas para a API da Anthropic, que devolve um
   rascunho do anúncio (título, descrição, condição, preço sugerido,
   marca/modelo/cor, atributos).
3. **Mercado Livre**: a extensão usa a API pública de categorias do ML para
   sugerir a categoria e os atributos obrigatórios dela.
4. **Revisão**: abre uma aba com tudo pré-preenchido e editável.
5. **Publicação**: ao confirmar, a extensão envia as fotos, cria o item e
   define a descrição usando a API oficial do Mercado Livre, autenticada
   com a sua conta de vendedor (OAuth2).

Nenhum dado é enviado para nenhum servidor próprio — a extensão fala
diretamente com `api.mercadolibre.com` e `api.anthropic.com` a partir do seu
navegador. Tokens e chaves ficam salvos apenas em `chrome.storage.local`
(local ao seu Chrome, não sincronizado).

## Configuração

### 1. Criar um app no Mercado Livre Developers

1. Acesse https://developers.mercadolivre.com.br/ e crie uma aplicação.
2. Carregue a extensão no Chrome primeiro (passo abaixo) para conseguir o
   **Redirect URI** exato: abra as **Opções** da extensão, o campo
   "Redirect URI" mostra algo como
   `https://<id-da-extensao>.chromiumapp.org/`.
3. Cadastre essa URL como Redirect URI da sua aplicação no Mercado Livre.
4. Copie o **Client ID** (e o **Client Secret**, se seu app não usar PKCE
   puro) e cole nas Opções da extensão.

O login usa Authorization Code + PKCE via `chrome.identity.launchWebAuthFlow`,
então o Client Secret é opcional — só preencha se o Mercado Livre exigir
para o seu tipo de aplicação.

### 2. Obter uma chave da Anthropic

1. Crie uma chave em https://console.anthropic.com/.
2. Cole em **Opções → Chave de API da Anthropic**.
3. O modelo padrão é `claude-sonnet-5`; você pode trocar por outro modelo
   com suporte a visão se preferir.

### 3. Carregar a extensão no navegador

1. Gere os ícones (só uma vez, não exige nenhuma dependência):
   ```
   python3 mercado-livre-extension/tools/generate_icons.py
   ```
2. Abra `chrome://extensions`.
3. Ative o **Modo do desenvolvedor**.
4. Clique em **Carregar sem compactação** e selecione a pasta
   `mercado-livre-extension`.
5. Abra as **Opções** da extensão (ícone da engrenagem no popup) e siga a
   configuração acima.
6. Clique em **Conectar conta** para autorizar sua conta do Mercado Livre.

## Uso

1. Clique no ícone da extensão.
2. Arraste ou selecione as fotos do produto (até 8).
3. Clique em **Gerar anúncio com IA**.
4. Na aba de revisão, confira/edite título, descrição, categoria, preço,
   condição e atributos obrigatórios.
5. Clique em **Publicar no Mercado Livre**.

## Limitações e avisos importantes

- **Preço sugerido é só uma estimativa da IA** — sempre revise antes de
  publicar.
- **Categoria automática** usa o endpoint público de descoberta de domínio
  do Mercado Livre; pode errar em produtos ambíguos — use o campo de busca
  manual na tela de revisão se necessário.
- **Atributos obrigatórios**: a extensão tenta preencher automaticamente
  combinando marca/modelo/cor identificados pela IA com os atributos que a
  categoria exige, mas nem sempre encontra correspondência — confira antes
  de publicar. Se a API do Mercado Livre recusar por atributo faltando, a
  mensagem de erro aparece na tela e as fotos já enviadas não são reenviadas
  na nova tentativa.
- **Tipo de anúncio** (`gold_special`/`gold_pro`/`free`) depende do que sua
  conta de vendedor tem disponível para a categoria escolhida; ajuste nas
  Opções ou na revisão se a publicação falhar por esse motivo.
- Chaves e tokens ficam salvos sem criptografia adicional em
  `chrome.storage.local`. Use isso apenas no seu próprio navegador/perfil.
- Este projeto fala diretamente com a API da Anthropic pelo navegador
  (`anthropic-dangerous-direct-browser-access`), o que expõe sua chave de
  API no tráfego do cliente — adequado para uso pessoal, não para distribuir
  a extensão publicamente com sua própria chave embutida.

## Estrutura do projeto

```
mercado-livre-extension/
  manifest.json
  icons/                  # gerados por tools/generate_icons.py (não versionados)
  tools/
    generate_icons.py     # gera icons/icon16.png, icon48.png, icon128.png
  src/
    background.js       # service worker: OAuth, roteamento de mensagens
    popup.html/.js/.css  # tela de envio das fotos
    options.html/.js/.css# configuração (credenciais ML + IA, login)
    review.html/.js/.css # revisão do anúncio antes de publicar
    shared.css           # estilos compartilhados
    lib/
      storage.js         # chrome.storage.local helpers
      pkce.js             # geração do code_verifier/code_challenge
      mlSites.js           # domínios de autorização por país
      mlClient.js           # chamadas à API do Mercado Livre
      aiClient.js            # chamada à API da Anthropic (visão)
      imageUtils.js           # redimensionamento/compressão de fotos
```
