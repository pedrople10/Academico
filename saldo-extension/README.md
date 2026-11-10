# Saldo Total – extensão do Chrome

Extensão (Manifest V3) que lê sozinha o saldo exibido nas páginas das casas de apostas em que você está logado e soma tudo. Os dados ficam só no seu navegador (`chrome.storage.local`); nada é enviado para servidor.

## Como funciona

- **Leitura automática:** o `content.js` roda em toda página, espera ~1,5 s a página carregar e procura valores em R$ perto de palavras como "saldo", "carteira", "depositar" e "sacar".
  - Se encontrar **um** valor claro, salva para aquela casa (pelo domínio, ex.: `betano.bet.br`).
  - Se encontrar **mais de um**, guarda como pendente e o popup/painel mostra um aviso amarelo para você escolher o certo.
- **Não apaga saldos anteriores:** depois que uma casa tem saldo salvo, a leitura automática não mexe mais nele. Trocar de login na mesma casa não sobrescreve o valor. Para mudar, use a edição manual.
- **Edição manual:** botão **editar** ao lado de cada casa preenche o formulário com o valor atual. Também dá para adicionar casas pelo nome; use nomes diferentes (ex.: `Bet365` e `Bet365-2`) para guardar logins separados da mesma casa.
- **Painel em aba própria:** `dashboard.html` abre numa aba normal e atualiza em tempo real (escuta `chrome.storage.onChanged`), sem precisar clicar na extensão.

## Arquivos

| Arquivo | Função |
| --- | --- |
| `manifest.json` | Configuração da extensão (permissões e content script) |
| `content.js` | Leitura automática do saldo em cada página |
| `popup.html/.css/.js` | Janela do ícone: total, pendências, leitura forçada, edição manual e botão do painel |
| `dashboard.html/.css/.js` | Painel completo numa aba, atualizado ao vivo |

## Instalação

1. Baixe esta pasta `saldo-extension/` (clone o repositório ou baixe o ZIP pelo GitHub e extraia).
2. No Chrome, abra `chrome://extensions`.
3. Ative o **Modo do desenvolvedor** (canto superior direito).
4. Clique em **Carregar sem compactação** e selecione a pasta `saldo-extension`.
5. O Chrome vai pedir a permissão "Ler e alterar todos os seus dados nos sites que você visita". Ela é necessária para a leitura automática em cada casa.
6. Clique no ícone de quebra-cabeça 🧩 e fixe **Saldo Total** na barra.

## Uso

1. Clique no ícone da extensão e em **Abrir painel completo numa aba**.
2. Clique com o botão direito na aba do painel e escolha **Fixar aba**.
3. Navegue nas casas de apostas logado normalmente. O total no painel se atualiza sozinho.
4. Se aparecer o aviso amarelo de pendência, clique no valor que é o seu saldo.
5. Para corrigir um valor, clique em **editar** na casa, troque o número e salve.

## Atualizar

Substitua os arquivos da pasta pelos novos e clique no botão de recarregar (↻) no card da extensão em `chrome://extensions`.
