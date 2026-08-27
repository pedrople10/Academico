# Ferramentas locais — multicontas (Opera)

Três programas que rodam no seu computador e conversam com o painel:

| arquivo | o que faz |
|---|---|
| `app.py` | abre um link em todos os perfis do Opera de uma vez |
| `saldos.py` | varredura de saldos, casa por casa, e envia pro painel |
| `nuvem.py` | ponte com o Supabase (não roda sozinho) |
| `opera_perfis.py` | abre/detecta cada perfil do Opera (substitui a Local API do AdsPower) |
| `aprendiz.py` | opcional — observa onde ficam os campos das casas |

Eles **não precisam ir para o GitHub** — o código em si não tem segredo
nenhum, mas os arquivos que ele *gera* (`nuvem.json`, `profiles.json` com
dados reais, `saldos.json`...) sim, e já estão no `.gitignore` desta pasta.

---

## Por que Opera em vez de AdsPower

O projeto original usava o **AdsPower**, um navegador "antidetect": além de
isolar cada perfil, ele randomiza fingerprint (canvas, fontes, WebGL) e deixa
configurar um proxy diferente por perfil pela própria interface do app,
tudo isso pensado pra reduzir o risco de uma casa de apostas ligar duas
contas ao mesmo dispositivo.

**O Opera não faz nada disso.** O que ele tem — e que essas ferramentas usam
— é suporte nativo a múltiplos perfis, cada um com sua própria pasta de
dados (cookies, login, extensões). Isso é suficiente para:

- não misturar sessão/login entre contas diferentes;
- automatizar (abrir link em vários perfis, ler saldo) do mesmo jeito que
  era feito com o AdsPower — o protocolo usado por baixo (Chrome DevTools
  Protocol) é o mesmo, o Opera também é Chromium.

**O que ele NÃO faz sozinho:**

- não troca fingerprint entre perfis — todos "parecem" o mesmo navegador
  para o site;
- sem configurar um `proxy` por perfil (veja abaixo), todos saem pela
  mesma internet/IP da sua casa.

Se você administra contas de **pessoas diferentes, cada uma no próprio CPF**
(o caso de uso original: você, mãe, pai...), isso normalmente já é o que as
casas de apostas esperam — a regra costuma ser "uma conta por CPF", não
"um dispositivo por casa". Mesmo assim, alguns sistemas antifraude
consideram múltiplas contas saindo do mesmo IP/dispositivo como sinal de
risco e podem pedir verificação extra ou limitar alguma conta. Se isso for
um problema real pro seu caso, um proxy residencial diferente por perfil
(campo `proxy` abaixo) resolve a parte do IP; a parte de fingerprint só um
antidetect de verdade resolve. Avalie o volume e o risco antes de operar
várias contas no mesmo computador.

---

## Antes de começar

Você precisa de:

1. **Opera** instalado (qualquer versão recente — Opera comum ou Opera GX).
   Não precisa de plano pago nem de API alguma: as ferramentas abrem o
   Opera sozinhas, com `--remote-debugging-port` e `--user-data-dir`
   próprios por perfil.
2. **Python 3.9+**.
3. O **painel** já publicado e com pelo menos uma casa cadastrada
   (veja `../painel/README.md`).

Instale as dependências, no terminal dentro desta pasta:

```
pip install websocket-client
```

(`requests` não é mais necessário — a conversa com o Opera usa só a
biblioteca padrão do Python.)

Se o Opera estiver instalado num lugar fora do padrão e as ferramentas não
acharem o executável sozinhas, defina a variável de ambiente `OPERA_PATH`
apontando pro `opera.exe` (Windows) ou pro binário do Opera (Mac/Linux).

---

## Configuração (uma vez)

### 1. Ligar com o Supabase

Copie `nuvem.exemplo.json` para **`nuvem.json`** e preencha:

```json
{
  "supabase_url": "https://SEUPROJETO.supabase.co",
  "supabase_key": "sb_secret_..."
}
```

A `supabase_key` aqui é a **secret key** (Supabase → Settings → API), não a
anon key que vai no painel. Ela ignora a proteção de linha do banco — trate
como senha de administrador. O `.gitignore` já bloqueia esse arquivo.

### 2. Cadastrar os perfis

Copie `profiles.exemplo.json` para **`profiles.json`** e troque os exemplos
pelos seus:

```json
[
  { "nome": "Você", "porta": 9222, "usuario_painel": "", "proxy": "",
    "casas": ["betano.bet.br", "lottu.bet.br"] },
  { "nome": "Mãe",  "porta": 9223, "usuario_painel": "Mãe", "proxy": "",
    "casas": ["lottu.bet.br"] }
]
```

- **`porta`** é a porta de depuração deste perfil — escolha um número livre
  e único para cada perfil (9222, 9223, 9224...). Não precisa existir antes:
  na primeira vez que você conectar, o app abre o Opera nessa porta sozinho;
  nas próximas, se o Opera já estiver aberto nela, ele só reaproveita.
- **`usuario_painel`** precisa bater com o campo *Usuário* das casas no
  painel. Vazio = as suas próprias casas.
- **`proxy`** é opcional: `"host:porta"` de um proxy sem autenticação para
  este perfil sair por um IP diferente. Deixe vazio se não usar proxy. Para
  proxy com usuário/senha, o Chromium não aceita credenciais na linha de
  comando — use um proxy sem senha (ex: liberado por IP) ou um forwarder
  local que injeta a autenticação.
- **`casas`** é usado pelo `app.py` pra saber em quais perfis abrir cada
  link. O `saldos.py` preenche o resto sozinho.
- **`pasta`** (opcional) troca o nome da pasta de dados daquele perfil,
  criada em `perfis-opera/`. Sem isso, usa o `nome` do perfil.

### 3. Puxar as casas do painel

```
python nuvem.py --sincronizar-profiles
```

Isso baixa do painel o nome, link e saldo de cada casa e grava no
`profiles.json`. Não abre navegador nem lê saldo — é cópia local, leva
segundos. Rode sempre que cadastrar casa nova no painel.

Para conferir o que ele enxerga:

```
python nuvem.py --listar
```

---

## Usar

### Abrir um link em todos os perfis

```
python app.py
```

Clique em **🔌 CONECTAR** — na primeira vez isso abre uma janela do Opera
para cada perfil (pode levar alguns segundos por perfil); nas próximas, se
as janelas já estiverem abertas, é instantâneo. Cole o link e **ABRIR**.
Os perfis que têm aquela casa ficam destacados com o saldo de cada um;
os que estão limitados nela aparecem com 🔒 e ficam fora da seleção.

Botões úteis: **🔄 PERFIS** busca casas novas do painel; **🧹 FECHAR ABAS**
limpa tudo.

### Varredura de saldos

```
python saldos.py --gui
```

Uma janelinha abre no canto da tela:

1. escolhe o perfil — ao confirmar, o Opera abre sozinho (ou é detectado,
   se já estiver aberto) na porta configurada;
2. ele lista as casas — as **com saldo** já vêm marcadas, as **zeradas** e as
   **novas** não. Filtros no topo, e **◉ só estas** troca a seleção inteira;
3. abre uma casa por vez. Quando o saldo aparecer, clique em **Saldo
   apareceu** (ou deixe o modo automático detectar);
4. confere o valor. Errado? escolhe outro da lista, digita, ou usa
   **🎯 Clicar na tela** e aponta o saldo com o mouse;
5. no fim, **☁ Enviar saldos para o painel**.

Atalhos: `Enter` faz a ação principal, `↑ ↓` andam pelos valores, `espaço`
marca "não mexeu", `Ctrl + →` pula.

Se fechar no meio, na próxima abertura aparece **↩ Retomar (12/42)**.

### Modo ajuste

O filtro **💸 Ajustar** mostra só as casas fora da meta (campo "deixar" do
painel), dizendo quanto sacar ou depositar. Depois que você mexe e digita o
saldo novo, uma caixinha registra a movimentação — isso evita que um saque
apareça como prejuízo no resultado da casa.

---

## Sem internet

Tudo continua funcionando com o `profiles.json` local; só o envio ao painel
fica desabilitado, e os saldos ficam em `saldos.json` / `saldos.csv`.

## Se algo der errado

- **"não achei o Opera instalado"** → defina `OPERA_PATH` com o caminho do
  executável, ou confirme que o Opera está no PATH do sistema.
- **"o Opera não respondeu na porta X a tempo"** → a máquina pode estar
  lenta pra abrir vários perfis de uma vez; tente reconectar de novo, ou
  aumente o intervalo entre perfis.
- **"Não achei o nuvem.json"** → passo 1 da configuração.
- **duas portas iguais em profiles.json** → cada perfil precisa de uma
  porta própria; portas repetidas fazem um perfil "roubar" a janela do
  outro.
- **A aba fechou no meio** → clique em **🔄 Ler de novo**, ele reabre.

## Arquivos que aparecem com o uso

`saldos.json`, `saldos.csv`, `aprendizado.json`,
`varredura_em_andamento.json`, `perfis-opera/` — todos locais, todos no
`.gitignore`. Podem ser apagados sem quebrar nada; você só perde a memória
de correções e as sessões salvas dos perfis do Opera (vai precisar logar de
novo nas casas).
