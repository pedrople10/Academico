# Painel do apostador

Painel para quem opera várias contas de aposta e precisa saber, sem planilha:
quanto tem em cada casa, quanto dá pra sacar, quanto é lucro de verdade e
quanto vai pro imposto.

É um arquivo HTML só. Os dados ficam num Supabase (plano gratuito), então dá
pra abrir de qualquer computador ou do celular.

## O que ele faz

**Banca** — cada casa com saldo, quanto você quer deixar ali e o que fazer
(sacar X / depositar Y). Ordena pelo valor da pendência, então você ataca as
maiores primeiro. Marca casas limitadas, que saem da conta de "capacidade
real de operação".

**Resultado real** — variação de saldo descontando depósitos e somando saques.
Sem isso, depositar R$ 500 numa casa aparece como lucro de R$ 500.

**Fechamento mensal** — lucro, provisionamento de IR, retirada sugerida e
histórico.

**IRPF por CPF** — os 15% incidem só sobre o que passar da faixa de isenção
anual, e a faixa é por CPF. Ganho de R$ 30 mil não paga R$ 4.500; paga 15%
sobre o excedente. O painel calcula isso separado por pessoa.

**Vida pessoal** — entradas e saídas fixas, separando custo fixo de gasto
variável (fatura de cartão não é custo fixo), com categorias. Isso define a
meta da sua reserva de emergência.

**Projeção** — desliga qualquer linha (salário, apostas, uma conta) e vê o
que acontece com o patrimônio em 6/12/24/36 meses.

**A receber** — dinheiro emprestado que volta, com data e aviso de atraso.

## Instalar (~15 min)

### 1. Supabase

1. Conta em https://supabase.com e um projeto novo.
2. **SQL Editor → New query**, cola o `schema.sql` e roda.
3. **Project Settings → API**: copia a *Project URL* e a *anon public key*.
4. **Authentication → Providers → Email**: se for uso pessoal, desative
   "Confirm email" pra não precisar confirmar cadastro.

### 2. Configurar

No `index.html`, perto do topo do `<script>`:

```js
const SUPABASE_URL = 'https://SEUPROJETO.supabase.co';
const SUPABASE_ANON_KEY = 'COLE_AQUI_SUA_CHAVE_ANON';
```

A anon key é pública por natureza — quem protege os dados é o Row Level
Security do `schema.sql`, que só deixa cada usuário ler a própria linha.

### 3. Publicar

GitHub Pages, Vercel ou Netlify — é um site estático.

Este repositório já traz `.github/workflows/deploy-painel.yml`, que publica
`apostas/painel/` no GitHub Pages sozinho a cada push na `master`. Só falta
ativar uma vez: **Settings → Pages → Source: GitHub Actions**. Depois disso,
qualquer alteração no painel é publicada automaticamente.

### 4. Usar

Acessa, cria a conta, e começa cadastrando suas casas em **Banca → + Nova
casa**. As 5 casas de exemplo você pode apagar.

## Antes de subir pro GitHub

**Se o repositório for público, qualquer pessoa lê o que está no arquivo.**
A anon key não é problema (é pública por design), mas cuide para não deixar
no `index.html`:

- saldos reais em `SEED_HOUSES` (a base vem com exemplos zerados de propósito)
- nomes de familiares em `PESSOAS_PERFIL_PADRAO`
- qualquer coisa que ligue o painel a você

Os dados de uso ficam no Supabase, não no arquivo — então o normal é o
`index.html` continuar genérico pra sempre. Só tome cuidado se um dia
colar dado real ali "pra testar".

Repositório privado com GitHub Pages exige conta Pro; Vercel e Netlify
servem repo privado no plano grátis.

## Como os perfis funcionam

Cada casa tem um campo `usuario`. Vazio = você. Preenchido = a pessoa cuja
conta você administra. Isso alimenta:

- banca por titular (quanto do seu dinheiro está em CPF de terceiro)
- IRPF por CPF (cada um tem a própria faixa de isenção)
- capital em nome de terceiros (quanto você mandou e quanto voltou)

Em **Configurações → Perfis do Opera**, cada usuário vira um perfil na
varredura de saldos do `saldos.py` — veja `../automacao/README.md` para como
essa parte roda no seu computador (com Opera, não AdsPower).

## Backup

**Configurações → Backup → Baixar backup.** Faça isso de vez em quando: tudo
vive numa linha só de uma tabela, e projeto Supabase gratuito pausa por
inatividade. O painel avisa quando passa de 30 dias sem backup.

## Aviso

Os cálculos de imposto são **estimativa de planejamento**, não apuração
fiscal. A Receita separa apostas por natureza (esportivas, cassino, fantasy)
e a compensação de perdas tem regras próprias. Casas licenciadas retêm na
fonte, então parte pode já estar paga. Com volume relevante — e ainda mais
com prêmios em CPF de terceiros — confirme com um contador.
