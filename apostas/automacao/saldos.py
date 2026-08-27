"""
Leitor genérico de saldo das casas de apostas.

Ideia: em vez de configurar seletor CSS casa por casa, injeta um script que
procura QUALQUER valor em reais na página e pontua cada candidato pelo
contexto (fica no topo? tem "saldo" perto? a classe fala "balance"?).
O melhor pontuado vence.

Defesas embutidas:
  - clica no "olhinho" quando o saldo está oculto (R$ ••••) e lê de novo
  - fecha banners de cookie/notificação que cobrem a tela
  - ignora valores de odds, cotações, promoções e tabelas de transação
  - tenta a home e, se não achar, algumas URLs comuns de "minha conta"
  - recarrega uma vez se a página vier vazia

No modo --gui nada é gravado sem você ver: depois de cada leitura a janela
para e mostra o valor encontrado junto com todos os outros valores em R$ da
página. Se pegou o número errado, você escolhe outro da lista, digita o certo
ou clica em "🎯 Clicar na tela" e aponta o saldo com o mouse no navegador.
Dá também para voltar uma casa e, no fim, corrigir qualquer linha antes de
salvar.

Uso: pode ser importado pelo app.py e também roda sozinho:
    python saldos.py                  # todos os perfis do profiles.json
    python saldos.py Mae              # somente um perfil
    python saldos.py Mae Pai          # mais de um perfil
    python saldos.py mamae            # apelido, se você configurar aliases
"""

import json
import threading
import time
import urllib.request
import urllib.error
from urllib.parse import quote

try:
    import websocket
except ImportError:
    websocket = None

try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    tk = None
    ttk = None

try:
    import nuvem            # ponte com o painel (Supabase) — opcional
except ImportError:
    nuvem = None

from opera_perfis import abrir_perfil

TIMEOUT = 15

# paleta da janela flutuante (modo manual)
BG_W, CARD_W, FG_W, MUTED_W = "#15171c", "#1e2129", "#e8eaed", "#8b91a1"
ACCENT_W, OK_W, WARN_W, ERR_W = "#2f80ed", "#27ae60", "#f2994a", "#eb5757"

# Caminhos comuns de "minha conta" — tentados só se a home não revelar nada
CAMINHOS_FALLBACK = [
    "/minha-conta", "/conta", "/account", "/my-account",
    "/carteira", "/wallet", "/perfil", "/cashier", "/caixa",
]

# ---------------------------------------------------------------- JS
JS_SCANNER = r"""
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const RE_BRL = /R\$\s*\d{1,3}(?:\.\d{3})*,\d{2}|R\$\s*\d+,\d{2}/;
  const RE_OCULTO = /R\$\s*[•*·\u2022\u00b7]{2,}|[•*]{4,}/;

  // ---------- 1. tira obstáculos da frente ----------
  const textoBotao = el => (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim().toLowerCase();
  const PALAVRAS_FECHAR = ['aceitar','aceito','entendi','ok','fechar','concordo','continuar','permitir todos','agora não','depois'];
  for (const el of document.querySelectorAll('button, a[role=button], [class*=cookie] button, [class*=consent] button')) {
    const t = textoBotao(el);
    if (t && PALAVRAS_FECHAR.some(p => t === p || t.startsWith(p))) {
      try { el.click(); await sleep(150); } catch(e){}
    }
  }

  // ---------- 2. revela saldo oculto (olhinho) ----------
  function pareceToggleSaldo(el) {
    const attrs = [
      el.getAttribute('aria-label'), el.getAttribute('title'),
      el.getAttribute('data-testid'), el.className && el.className.baseVal,
      typeof el.className === 'string' ? el.className : '',
      el.id
    ].filter(Boolean).join(' ').toLowerCase();
    if (/olho|eye|visib|mostrar|exibir|ocultar|toggle.*(saldo|balance)|(saldo|balance).*toggle|show.*balance|hide.*balance/.test(attrs)) return true;
    return false;
  }
  let revelou = false;
  const ocultos = [...document.querySelectorAll('*')].filter(el =>
      el.children.length === 0 && RE_OCULTO.test(el.textContent || ''));
  for (const alvo of ocultos.slice(0, 4)) {
    // procura um botão clicável até 4 níveis acima, ou irmãos próximos
    let escopo = alvo;
    for (let i = 0; i < 4 && escopo; i++) {
      const cands = [...escopo.querySelectorAll('button, svg, i, span[role=button], [class*=eye], [class*=olho], [class*=visib]')];
      const btn = cands.find(pareceToggleSaldo) || cands.find(c => c.tagName === 'BUTTON' || c.tagName === 'SVG');
      if (btn) { try { btn.click(); revelou = true; await sleep(400); } catch(e){} break; }
      escopo = escopo.parentElement;
    }
  }
  if (revelou) await sleep(500);

  // ---------- 3. coleta candidatos ----------
  const vh = window.innerHeight || 800;
  const cands = [];
  const NEGATIVO = /odd|cotac|cotaç|aposta minima|aposta mínima|bônus|bonus|promo|premio|prêmio|ganho potencial|retorno|stake|deposito minimo|depósito mínimo|limite|taxa|valor da aposta/i;
  const POSITIVO = /saldo|balance|carteira|wallet|disponivel|disponível|meu dinheiro|conta/i;

  for (const el of document.querySelectorAll('*')) {
    if (el.children.length > 0) continue;                 // só folhas
    const txt = (el.textContent || '').trim();
    if (!txt || txt.length > 40) continue;
    const m = txt.match(RE_BRL);
    if (!m) continue;

    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;        // invisível
    const est = getComputedStyle(el);
    if (est.visibility === 'hidden' || est.display === 'none' || est.opacity === '0') continue;

    // contexto: texto e atributos dos 4 ancestrais
    let ctx = '', attrs = '';
    let p = el;
    for (let i = 0; i < 4 && p; i++) {
      ctx += ' ' + (p.textContent || '').slice(0, 200);
      attrs += ' ' + [typeof p.className === 'string' ? p.className : '', p.id,
                      p.getAttribute && (p.getAttribute('data-testid') || ''),
                      p.getAttribute && (p.getAttribute('aria-label') || '')].join(' ');
      p = p.parentElement;
    }
    ctx = ctx.toLowerCase(); attrs = attrs.toLowerCase();

    let score = 0;
    if (POSITIVO.test(attrs)) score += 45;
    if (POSITIVO.test(ctx))   score += 30;
    if (/saldo|balance/.test(attrs)) score += 25;
    if (NEGATIVO.test(ctx))   score -= 55;
    if (NEGATIVO.test(attrs)) score -= 40;

    // posição: cabeçalho vale muito
    if (r.top >= 0 && r.top < 120) score += 35;
    else if (r.top < vh * 0.4)     score += 15;
    else if (r.top > vh)           score -= 20;

    // dentro de header/nav explícito
    if (el.closest('header, nav, [class*=header], [class*=navbar], [class*=topbar]')) score += 25;
    // dentro de tabela/lista = provavelmente histórico, não saldo
    if (el.closest('table, tbody, [class*=historic], [class*=transac], [class*=extrato]')) score -= 45;
    // perto de botão de depósito costuma ser o saldo real
    if (/depositar|deposit|sacar|saque/.test(ctx)) score += 20;

    cands.push({ texto: m[0], score, top: Math.round(r.top),
                 amostra: ctx.replace(/\s+/g,' ').trim().slice(0, 90) });
  }

  cands.sort((a, b) => b.score - a.score);

  // tira valores repetidos (o mesmo saldo costuma aparecer em vários lugares),
  // mantendo sempre o de maior pontuação
  const vistos = new Set();
  const unicos = [];
  for (const c of cands) {
    const chave = c.texto.replace(/\s+/g, '');
    if (vistos.has(chave)) continue;
    vistos.add(chave);
    unicos.push(c);
  }

  return JSON.stringify({
    ok: unicos.length > 0,
    revelou,
    melhor: unicos[0] || null,
    alternativas: unicos.slice(1, 4),
    candidatos: unicos.slice(0, 12),   // usado pela janela de revisão do --gui
    titulo: document.title,
    url: location.href
  });
})()
"""


# Modo "clicar na tela": destaca o elemento sob o mouse e captura o valor do
# que o usuário clicar. Serve para quando o scanner pega o número errado —
# você aponta o saldo certo com o mouse, dentro do próprio navegador.
JS_PICKER = r"""
(() => {
  const RE_BRL = /R\$\s*\d{1,3}(?:\.\d{3})*,\d{2}|R\$\s*\d+,\d{2}|\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}/;
  if (window.__saldoPickerStop) { try { window.__saldoPickerStop(); } catch (e) {} }
  window.__saldoEscolhido = null;

  const marca = document.createElement('div');
  marca.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;' +
    'border:2px solid #2f80ed;background:rgba(47,128,237,.18);border-radius:4px;display:none';
  document.documentElement.appendChild(marca);

  const dica = document.createElement('div');
  dica.textContent = 'Clique no saldo correto  ·  Esc cancela';
  dica.style.cssText = 'position:fixed;z-index:2147483647;top:12px;left:50%;' +
    'transform:translateX(-50%);background:#15171c;color:#fff;' +
    'font:600 13px/1.4 system-ui,sans-serif;padding:8px 16px;border-radius:20px;' +
    'box-shadow:0 4px 14px rgba(0,0,0,.45);pointer-events:none';
  document.documentElement.appendChild(dica);

  function mover(e) {
    const el = e.target;
    if (!el || !el.getBoundingClientRect) return;
    const r = el.getBoundingClientRect();
    marca.style.display = 'block';
    marca.style.top = r.top + 'px';
    marca.style.left = r.left + 'px';
    marca.style.width = r.width + 'px';
    marca.style.height = r.height + 'px';
  }

  function limpar() {
    document.removeEventListener('mousemove', mover, true);
    document.removeEventListener('click', clicou, true);
    document.removeEventListener('keydown', tecla, true);
    try { marca.remove(); dica.remove(); } catch (e) {}
    window.__saldoPickerStop = null;
  }

  // Caminho CSS curto e estável do elemento: serve para procurar direto
  // nele na próxima varredura, em vez de varrer a página inteira.
  function caminho(el) {
    const partes = [];
    let n = el;
    for (let i = 0; n && n.nodeType === 1 && i < 6; i++) {
      if (n.id && /^[A-Za-z][\w-]*$/.test(n.id)) { partes.unshift('#' + n.id); break; }
      let s = n.tagName.toLowerCase();
      const bruto = (typeof n.className === 'string') ? n.className.trim() : '';
      const cls = bruto ? bruto.split(/\s+/).filter(c =>
        /^[A-Za-z][\w-]*$/.test(c) && !/\d{4,}/.test(c)).slice(0, 2) : [];
      if (cls.length) s += '.' + cls.join('.');
      const pai = n.parentElement;
      if (pai) {
        const irmaos = Array.prototype.filter.call(pai.children, x => x.tagName === n.tagName);
        if (irmaos.length > 1) s += ':nth-of-type(' + (irmaos.indexOf(n) + 1) + ')';
      }
      partes.unshift(s);
      n = n.parentElement;
    }
    return partes.join(' > ');
  }

  function clicou(e) {
    e.preventDefault(); e.stopPropagation();
    if (e.stopImmediatePropagation) e.stopImmediatePropagation();
    let el = e.target;
    let txt = (el.innerText || el.textContent || '').trim();
    let m = txt.match(RE_BRL);
    // se clicou no ícone/wrapper, sobe alguns níveis procurando o número
    for (let i = 0; i < 3 && !m && el.parentElement; i++) {
      el = el.parentElement;
      txt = (el.innerText || el.textContent || '').trim();
      m = txt.match(RE_BRL);
    }
    window.__saldoEscolhido = {
      texto: m ? m[0] : txt.slice(0, 40),
      bruto: txt.replace(/\s+/g, ' ').slice(0, 120),
      seletor: caminho(el),
      achou: !!m
    };
    limpar();
  }

  function tecla(e) {
    if (e.key === 'Escape') { window.__saldoEscolhido = { cancelado: true }; limpar(); }
  }

  document.addEventListener('mousemove', mover, true);
  document.addEventListener('click', clicou, true);
  document.addEventListener('keydown', tecla, true);
  window.__saldoPickerStop = limpar;
  return 'ok';
})()
"""

# Farejador: versão leve e SOMENTE LEITURA do scanner, usada para perceber
# sozinho quando o saldo aparece na tela. Não clica em olhinho nem em nada —
# rodar de 1,5 em 1,5 segundo enquanto você navega tem que ser inofensivo.
JS_FAREJAR = r"""
(() => {
  const RE = /R\$\s*\d{1,3}(?:\.\d{3})*,\d{2}|R\$\s*\d+,\d{2}/;
  const NEG = /odd|cotac|cotaç|aposta m|b[oô]nus|promo|pr[eê]mio|retorno|stake|dep[oó]sito m[ií]nimo|limite|taxa/i;
  const POS = /saldo|carteira|dispon|minha conta|banca|balance|sacar/i;
  let melhor = 0, texto = '';
  const els = document.querySelectorAll('body *');
  const alturaTela = window.innerHeight || 800;
  for (let i = 0; i < els.length && i < 4000; i++) {
    const el = els[i];
    if (el.children.length) continue;
    const t = (el.textContent || '').trim();
    if (!t || t.length > 40) continue;
    const m = t.match(RE);
    if (!m) continue;
    const r = el.getBoundingClientRect();
    if (r.top < 0 || r.top > alturaTela || r.width === 0) continue;
    let ctx = '', p = el;
    for (let k = 0; k < 3 && p; k++) { p = p.parentElement; if (p) ctx += ' ' + (p.textContent || '').slice(0, 120); }
    if (NEG.test(ctx)) continue;
    let s = 40;
    if (POS.test(ctx)) s += 40;
    if (r.top < 220) s += 10;
    if (s > melhor) { melhor = s; texto = m[0]; }
  }
  return JSON.stringify({
    score: melhor,
    texto,
    login: !!document.querySelector('input[type=password]')
  });
})()
"""

def js_ler_seletor(seletor):
    """Lê o valor direto no elemento que você apontou da última vez."""
    return r"""
(() => {
  const sel = %s;
  const RE = /R\$\s*\d{1,3}(?:\.\d{3})*,\d{2}|R\$\s*\d+,\d{2}|\d{1,3}(?:\.\d{3})*,\d{2}/;
  try {
    const el = document.querySelector(sel);
    if (!el) return JSON.stringify({achou: false});
    const t = (el.innerText || el.textContent || '').trim();
    const m = t.match(RE);
    if (!m) return JSON.stringify({achou: false});
    let ctx = '', p = el;
    for (let k = 0; k < 3 && p; k++) { p = p.parentElement; if (p) ctx += ' ' + (p.textContent || '').slice(0, 80); }
    return JSON.stringify({achou: true, texto: m[0], amostra: ctx.replace(/\s+/g, ' ').trim().slice(0, 120)});
  } catch (e) {
    return JSON.stringify({achou: false});
  }
})()
""" % json.dumps(seletor)


JS_PICKER_LER = "JSON.stringify(window.__saldoEscolhido || null)"

JS_PICKER_CANCELAR = r"""
(() => {
  if (window.__saldoPickerStop) { try { window.__saldoPickerStop(); } catch (e) {} }
  window.__saldoEscolhido = null;
  return 'ok';
})()
"""



JS_LOGIN = r"""
(() => {
  const txt = (document.body ? document.body.innerText : '').toLowerCase();
  const url = location.href.toLowerCase();

  // campo de senha visível é o sinal mais forte
  const senhas = [...document.querySelectorAll('input[type=password]')].filter(i => {
    const r = i.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  });

  // botões/links de entrar
  const temBotaoEntrar = [...document.querySelectorAll('button, a, [role=button]')].some(el => {
    const t = (el.innerText || el.textContent || '').trim().toLowerCase();
    return /^(entrar|login|fazer login|acessar|iniciar sess)/.test(t);
  });

  // já logado? procura sinais de sessão ativa
  const logado = /sair|logout|minha conta|meu perfil|depositar|sacar|saldo/.test(txt);

  const urlLogin = /\/(login|signin|sign-in|entrar|acesso|auth)/.test(url);

  let precisaLogin = false;
  if (senhas.length > 0 && !logado) precisaLogin = true;
  if (urlLogin && senhas.length > 0) precisaLogin = true;
  if (temBotaoEntrar && !logado && senhas.length > 0) precisaLogin = true;

  return JSON.stringify({ precisaLogin, logado, urlLogin, campos_senha: senhas.length });
})()
"""

# ---------------------------------------------------------------- CDP
class Aba:
    """Uma aba controlada via CDP, com websocket próprio."""

    def __init__(self, port, url="about:blank"):
        self.port = port
        alvo = self._http(f"/json/new?{quote(url, safe='')}", "PUT")
        self.id = alvo["id"]
        self.ws_url = alvo["webSocketDebuggerUrl"]
        self.url_atual = url          # para recriar a aba se ela morrer
        self.recriada = False         # vira True se precisou abrir outra aba
        self.ws = websocket.create_connection(
            self.ws_url, timeout=TIMEOUT, suppress_origin=True
        )
        self._seq = 0

    def _reconectar(self):
        """
        Duas coisas quebram a conexão com a aba:

        1. O Windows derruba socket parado (WinError 10053). A aba continua
           viva — basta um websocket novo para o mesmo alvo.
        2. A aba deixou de existir (você fechou, o perfil reiniciou). Aí a
           tentativa de reconectar dá "No such target id" e a única saída é
           abrir uma aba nova na mesma página.
        """
        try:
            self.ws.close()
        except Exception:
            pass

        alvo = None
        try:
            alvos = self._http("/json/list")
            alvo = next((t for t in alvos if t.get("id") == self.id), None)
        except Exception:
            pass

        if alvo and alvo.get("webSocketDebuggerUrl"):
            self.ws_url = alvo["webSocketDebuggerUrl"]
        else:
            # a aba sumiu: abre outra onde estávamos e adota como a nossa
            destino = self.url_atual or "about:blank"
            novo = self._http(f"/json/new?{quote(destino, safe='')}", "PUT")
            self.id = novo["id"]
            self.ws_url = novo["webSocketDebuggerUrl"]
            self.recriada = True
            time.sleep(1.5)          # dá um tempo pra página carregar

        self.ws = websocket.create_connection(self.ws_url, timeout=TIMEOUT,
                                              suppress_origin=True)

    def _http(self, path, metodo="GET"):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=metodo)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                corpo = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (405, 501):
                req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    corpo = r.read().decode("utf-8", "replace")
            else:
                raise
        return json.loads(corpo) if corpo.strip().startswith(("{", "[")) else corpo

    def cmd(self, metodo, params=None, espera=TIMEOUT):
        """Manda um comando; se o socket tiver caído, reconecta e tenta de novo."""
        for tentativa in (1, 2):
            try:
                return self._cmd_uma_vez(metodo, params, espera)
            except RuntimeError:
                raise           # erro do próprio CDP: não adianta reconectar
            except Exception:
                if tentativa == 2:
                    raise
                self._reconectar()

    def _cmd_uma_vez(self, metodo, params=None, espera=TIMEOUT):
        self._seq += 1
        sid = self._seq
        self.ws.send(json.dumps({"id": sid, "method": metodo, "params": params or {}}))
        fim = time.time() + espera
        while time.time() < fim:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == sid:
                if "error" in msg:
                    raise RuntimeError(msg["error"].get("message", "erro CDP"))
                return msg.get("result", {})
        raise RuntimeError("timeout no CDP")

    def ir_para(self, url, espera_carregar=4.0):
        self.url_atual = url
        self.cmd("Page.enable")
        self.cmd("Page.navigate", {"url": url})
        time.sleep(espera_carregar)

    def js(self, expr, espera=TIMEOUT):
        r = self.cmd("Runtime.evaluate",
                     {"expression": expr, "awaitPromise": True, "returnByValue": True},
                     espera=espera)
        return r.get("result", {}).get("value")

    def pagina_vazia(self):
        try:
            n = self.js("document.body ? document.body.innerText.length : 0")
            return not n or n < 200
        except Exception:
            return True

    def fechar(self):
        try: self.ws.close()
        except Exception: pass
        try: self._http(f"/json/close/{self.id}")
        except Exception: pass


# ---------------------------------------------------------------- casas
def url_da_casa(casa):
    """Aceita 'betano.bet.br' (profiles.json) ou o dict de casa do painel."""
    if isinstance(casa, dict):
        link = casa.get("link") or casa.get("url") or ""
        if link:
            return link if "://" in link else "https://" + link
        alvo = casa.get("dominio") or casa.get("nome") or ""
    else:
        alvo = str(casa)
    return alvo if "://" in alvo else "https://" + alvo


def dominio_da_casa(casa):
    from urllib.parse import urlparse

    if isinstance(casa, dict) and casa.get("dominio"):
        return casa["dominio"]
    host = (urlparse(url_da_casa(casa)).netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def rotulo_da_casa(casa):
    if isinstance(casa, dict):
        return casa.get("nome") or casa.get("dominio") or "?"
    return str(casa)


def identidade_da_casa(casa):
    """Campos que viajam junto do resultado para o painel saber onde gravar."""
    if not isinstance(casa, dict):
        return {"dominio": dominio_da_casa(casa)}
    return {
        "dominio": dominio_da_casa(casa),
        "casa_id": casa.get("casa_id") or casa.get("id"),
        "nome_casa": casa.get("nome"),
        "saldo_anterior": casa.get("saldo_anterior"),
        "tipo_casa": casa.get("tipo"),
    }


# ---------------------------------------------------------------- leitura
def ler_saldo(port, casa, log=lambda s: None):
    """
    Tenta descobrir o saldo da casa (domínio ou dict do painel) no perfil
    que está na `port`. Devolve dict com saldo, confianca e detalhes.
    """
    if websocket is None:
        raise RuntimeError("pip install websocket-client")

    base = url_da_casa(casa)
    identidade = identidade_da_casa(casa)
    aba = Aba(port, base)
    try:
        time.sleep(3)

        # se veio vazio, dá um F5
        if aba.pagina_vazia():
            log("página vazia, recarregando")
            aba.ir_para(base, 5)

        # antes de procurar saldo: a casa está pedindo login?
        try:
            chk = json.loads(aba.js(JS_LOGIN, espera=10) or "{}")
        except Exception:
            chk = {}
        if chk.get("precisaLogin"):
            log("pediu login")
            return dict(identidade, saldo=None, confianca="precisa login",
                        precisa_login=True,
                        detalhe="tela de login — faça o login nesse perfil e rode de novo")

        tentativas = [None] + CAMINHOS_FALLBACK
        melhor_geral = None

        for caminho in tentativas:
            if caminho:
                log(f"tentando {caminho}")
                try:
                    aba.ir_para(base + caminho, 4)
                except Exception:
                    continue

            try:
                bruto = aba.js(JS_SCANNER, espera=20)
                res = json.loads(bruto) if bruto else None
            except Exception as e:
                log(f"scanner falhou: {e}")
                res = None

            if res and res.get("melhor"):
                m = res["melhor"]
                if melhor_geral is None or m["score"] > melhor_geral["melhor"]["score"]:
                    melhor_geral = res
                # score alto o bastante = para por aqui
                if m["score"] >= 60:
                    break

        if not melhor_geral or not melhor_geral.get("melhor"):
            return dict(identidade, saldo=None, confianca="nao encontrado",
                        detalhe="nenhum valor em R$ localizado")

        m = melhor_geral["melhor"]
        conf = "alta" if m["score"] >= 80 else "media" if m["score"] >= 45 else "baixa"
        return dict(
            identidade,
            **{
            "saldo": m["texto"],
            "score": m["score"],
            "confianca": conf,
            "revelou_oculto": melhor_geral.get("revelou", False),
            "url": melhor_geral.get("url"),
            "alternativas": [a["texto"] for a in melhor_geral.get("alternativas", [])],
            "contexto": m.get("amostra", ""),
            })
    finally:
        aba.fechar()


def ler_varios(port, casas, log=lambda s: None, pausa=1.0, progresso=None):
    """Percorre a lista inteira sem nunca interromper por causa de uma casa."""
    saida = []
    total = len(casas)
    for i, casa in enumerate(casas, 1):
        rotulo = rotulo_da_casa(casa)
        if progresso:
            progresso(i, total, rotulo)
        log(f"[{i}/{total}] {rotulo}")
        try:
            saida.append(ler_saldo(port, casa, log))
        except Exception as e:
            # qualquer falha vira uma linha de erro; o loop continua
            saida.append(dict(identidade_da_casa(casa), saldo=None,
                              confianca="erro", detalhe=str(e)[:160]))
        time.sleep(pausa)
    return saida


def normalizar_valor(texto):
    """
    Aceita o que a pessoa digitar e devolve sempre no formato 'R$ 1.234,56'.

    Entende: '1234,5' · '1.234,56' · 'R$ 1234.56' · '1234' · '-50,00'
    Devolve None se não houver número nenhum no texto.
    """
    import re

    if texto is None:
        return None
    bruto = re.sub(r"(?i)r\$", "", str(texto)).strip()
    achado = re.search(r"-?\d[\d.,\s]*", bruto)
    if not achado:
        return None

    num = achado.group(0).replace(" ", "").rstrip(".,")
    negativo = num.startswith("-")
    num = num.lstrip("-")
    if not num:
        return None

    if "," in num and "." in num:
        # o separador que aparece por último é o decimal
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif "," in num:
        num = num.replace(",", ".")
    else:
        partes = num.split(".")
        # '1.234' é milhar; '1234.56' é decimal
        if len(partes) > 1 and len(partes[-1]) in (1, 2):
            num = "".join(partes[:-1]) + "." + partes[-1]
        else:
            num = num.replace(".", "")

    try:
        valor = float(num)
    except ValueError:
        return None

    inteiro, decimal = f"{abs(valor):,.2f}".split(".")
    inteiro = inteiro.replace(",", ".")
    sinal = "-" if negativo and valor != 0 else ""
    return f"{sinal}R$ {inteiro},{decimal}"


def resumo(resultados):
    """Separa o que leu, o que precisa login e o que falhou."""
    ok      = [r for r in resultados if r.get("saldo")]
    login   = [r for r in resultados if r.get("precisa_login")]
    falhou  = [r for r in resultados if not r.get("saldo") and not r.get("precisa_login")]
    return ok, login, falhou


# ---------------------------------------------------------------- multi-perfil

def _normalizar_nome_perfil(nome):
    """Normaliza nomes para permitir Mãe/Mae, Ângela/Angela etc."""
    import re
    import unicodedata

    texto = unicodedata.normalize("NFKD", str(nome or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-zA-Z0-9]+", " ", texto).strip().lower()
    return texto


def selecionar_perfis(perfis, alvos=None):
    """
    Seleciona perfis pelo nome. Sem alvos, devolve todos.

    Aceita aliases úteis deste projeto:
      - Mãe -> Mae
      - apelidos que você configurar em `aliases`
      - todos / all / * -> todos
    """
    if not alvos:
        return list(perfis)

    partes = []
    for alvo in alvos:
        partes.extend(x.strip() for x in str(alvo).split(",") if x.strip())

    chaves = [_normalizar_nome_perfil(x) for x in partes]
    if any(x in {"todos", "all", "*"} for x in chaves):
        return list(perfis)

    # Apelidos que você quer poder digitar na linha de comando em vez do
    # nome completo do perfil. Ex.: `python saldos.py mamae` achar "Mãe".
    #     aliases = {"mamae": "mae"}
    aliases = {}

    por_nome = {_normalizar_nome_perfil(p.get("nome")): p for p in perfis}
    selecionados = []
    vistos = set()
    faltando = []

    for original, chave in zip(partes, chaves):
        chave = aliases.get(chave, chave)
        perfil = por_nome.get(chave)
        if perfil is None:
            faltando.append(original)
            continue
        identidade = perfil.get("porta") or perfil.get("nome")
        if identidade not in vistos:
            vistos.add(identidade)
            selecionados.append(perfil)

    if faltando:
        disponiveis = ", ".join(p.get("nome", "?") for p in perfis)
        raise ValueError(
            f"Perfil(is) não encontrado(s): {', '.join(faltando)}. "
            f"Disponíveis: {disponiveis}"
        )
    return selecionados


def localizar_arquivo_perfis(pasta, caminho_informado=None):
    """Localiza profiles.json; aceita profiles(2).json como fallback de upload."""
    from pathlib import Path

    if caminho_informado:
        caminho = Path(caminho_informado).expanduser()
        if not caminho.is_absolute():
            caminho = pasta / caminho
        if not caminho.exists():
            raise FileNotFoundError(f"Arquivo de perfis não encontrado: {caminho}")
        return caminho

    candidatos = [pasta / "profiles.json", pasta / "profiles(2).json"]
    for caminho in candidatos:
        if caminho.exists():
            return caminho
    raise FileNotFoundError(
        "Não encontrei profiles.json na mesma pasta do saldos.py."
    )


def obter_debug_port(perfil, timeout=25):
    """Garante que o perfil está aberto no Opera e devolve sua porta CDP."""
    try:
        return abrir_perfil(perfil, timeout_abertura=timeout)
    except Exception as e:
        return None, f"falha ao abrir o Opera: {e}"


def ler_perfil(port, perfil, log=lambda s: None, pausa=1.0, progresso=None):
    """Lê todas as casas de um perfil e identifica cada resultado."""
    from datetime import datetime

    casas = perfil.get("casas") or []
    resultados = ler_varios(
        port,
        casas,
        log=log,
        pausa=pausa,
        progresso=progresso,
    )
    agora = datetime.now().isoformat(timespec="seconds")
    for item in resultados:
        item["perfil"] = perfil.get("nome")
        item["porta"] = perfil.get("porta")
        item["lido_em"] = agora
    return resultados


def imprimir_bloco_resultados(nome, resultados):
    """Exibe o relatório LIDOS / LOGIN / FALHAS de um perfil."""
    ok, login, falhou = resumo(resultados)

    print("\n" + "-" * 72)
    print(f"PERFIL {nome} · LIDOS ({len(ok)})")
    for item in sorted(ok, key=lambda x: x.get("dominio", "")):
        dominio = item.get("dominio", "")
        saldo = item.get("saldo", "")
        confianca = item.get("confianca", "")
        print(f"  {dominio:<30} {saldo:<16} conf: {confianca}")

    if login:
        print(f"\nPRECISAM DE LOGIN ({len(login)}):")
        for item in sorted(login, key=lambda x: x.get("dominio", "")):
            print(f"  {item.get('dominio', '')}")

    if falhou:
        print(f"\nNÃO CONSEGUI LER ({len(falhou)}):")
        for item in sorted(falhou, key=lambda x: x.get("dominio", "")):
            dominio = item.get("dominio", "")
            detalhe = item.get("detalhe", "")[:80]
            print(f"  {dominio:<30} {detalhe}")

    return len(ok), len(login), len(falhou)


class Aprendizado:
    """
    Memória das suas correções, por domínio.

    Toda vez que você confirma um valor na tela de revisão, guardamos o
    contexto em que aquele número estava (as palavras em volta) e o quanto
    ele estava fora da primeira posição. Na próxima varredura, candidatos
    com contexto parecido sobem na lista — então a casa que erra sempre
    passa a acertar sozinha depois de uma ou duas correções.

    Fica num `aprendizado.json` ao lado do script. Apagar o arquivo apenas
    faz o scanner voltar ao comportamento original.
    """

    ARQUIVO = "aprendizado.json"
    MAX_EXEMPLOS = 5
    # palavras genéricas demais para servirem de pista
    IGNORAR = {"r", "rs", "de", "do", "da", "em", "no", "na", "e", "o", "a",
               "para", "por", "com", "seu", "sua", "voce", "você", "mais"}

    def __init__(self, pasta):
        from pathlib import Path

        self.caminho = Path(pasta) / self.ARQUIVO
        try:
            with open(self.caminho, encoding="utf-8") as arquivo:
                self.dados = json.load(arquivo)
        except Exception:
            self.dados = {}

    # ---------- utilidades ----------
    @staticmethod
    def _tokens(texto):
        import re
        import unicodedata

        texto = unicodedata.normalize("NFKD", str(texto or ""))
        texto = "".join(c for c in texto if not unicodedata.combining(c))
        cru = re.findall(r"[a-zA-Z]{2,}", texto.lower())
        return [t for t in cru if t not in Aprendizado.IGNORAR]

    def _registro(self, dominio):
        return self.dados.get((dominio or "").lower())

    # ---------- escrita ----------
    def registrar(self, dominio, escolhido, candidatos, origem):
        """Guarda o contexto do valor que o usuário deu como certo."""
        dominio = (dominio or "").lower()
        if not dominio or not escolhido:
            return
        contexto = (escolhido.get("amostra") or "").strip()
        tokens = self._tokens(contexto)
        reg = self.dados.setdefault(
            dominio, {"pistas": {}, "acertos": 0, "correcoes": 0, "exemplos": []})

        # o peso de cada palavra cresce quando ela aparece de novo numa escolha
        for token in set(tokens):
            reg["pistas"][token] = min(reg["pistas"].get(token, 0) + 1, 10)

        if origem == "scanner":
            reg["acertos"] = reg.get("acertos", 0) + 1
        else:
            reg["correcoes"] = reg.get("correcoes", 0) + 1

        if contexto:
            exemplos = reg.setdefault("exemplos", [])
            if contexto not in exemplos:
                exemplos.insert(0, contexto[:120])
            del exemplos[self.MAX_EXEMPLOS:]

        from datetime import datetime
        reg["ultima_vez"] = datetime.now().isoformat(timespec="seconds")
        self.salvar()

    def registrar_seletor(self, dominio, seletor, contexto=""):
        """
        Guarda ONDE na página estava o saldo que você apontou com o mouse.
        É o sinal mais forte que existe: você olhou e disse "é esse".
        Guardamos até 3 por casa — o site muda de layout e o caminho antigo
        para de valer, então vale ter alternativa.
        """
        dominio = (dominio or "").lower()
        if not dominio or not seletor:
            return
        reg = self.dados.setdefault(
            dominio, {"pistas": {}, "acertos": 0, "correcoes": 0, "exemplos": []})
        seletores = reg.setdefault("seletores", [])
        if seletor in seletores:
            seletores.remove(seletor)
        seletores.insert(0, seletor)
        del seletores[3:]
        for token in set(self._tokens(contexto)):
            reg["pistas"][token] = min(reg["pistas"].get(token, 0) + 1, 10)
        reg["correcoes"] = reg.get("correcoes", 0) + 1

        from datetime import datetime
        reg["ultima_vez"] = datetime.now().isoformat(timespec="seconds")
        self.salvar()

    def seletores(self, dominio):
        reg = self._registro(dominio)
        return list((reg or {}).get("seletores") or [])

    def esquecer_seletor(self, dominio, seletor):
        """Caminho quebrou (site mudou de layout): tira da memória."""
        reg = self._registro(dominio)
        if not reg or seletor not in (reg.get("seletores") or []):
            return
        reg["seletores"].remove(seletor)
        self.salvar()

    def salvar(self):
        try:
            with open(self.caminho, "w", encoding="utf-8") as arquivo:
                json.dump(self.dados, arquivo, ensure_ascii=False, indent=1)
        except Exception:
            pass    # aprender é bônus; nunca deve quebrar a varredura

    # ---------- leitura ----------
    def reordenar(self, dominio, candidatos):
        """
        Devolve (candidatos_reordenados, aprendeu). Cada candidato ganha
        `bonus` e `score_final`; a ordem original é preservada no empate.
        """
        reg = self._registro(dominio)
        if not reg or not reg.get("pistas"):
            for c in candidatos:
                c["score_final"] = c.get("score", 0)
                c["bonus"] = 0
            return (sorted(candidatos, key=lambda c: (0 if c.get("fixo") else 1,
                                                      -c["score_final"])),
                    any(c.get("fixo") for c in candidatos))

        pistas = reg["pistas"]
        maior = max(pistas.values()) or 1
        for posicao, c in enumerate(candidatos):
            tokens = set(self._tokens(c.get("amostra")))
            forca = sum(pistas.get(t, 0) for t in tokens)
            # normalizado para no máximo ~40 pontos, o bastante para virar o
            # jogo contra o score do scanner sem atropelar um caso óbvio
            bonus = min(round(40 * forca / (maior * 3)), 40)
            c["bonus"] = bonus
            c["score_final"] = c.get("score", 0) + bonus
        # o valor vindo do lugar que você apontou não perde para score nenhum
        ordenados = sorted(candidatos,
                           key=lambda c: (0 if c.get("fixo") else 1, -c["score_final"]))
        return ordenados, any(c["bonus"] > 0 for c in ordenados)

    def resumo(self, dominio):
        reg = self._registro(dominio)
        if not reg:
            return None
        return {
            "acertos": reg.get("acertos", 0),
            "correcoes": reg.get("correcoes", 0),
            "exemplo": (reg.get("exemplos") or [""])[0],
        }


class Progresso:
    """
    Guarda onde você parou. Uma varredura de 40 casas é meia hora de
    trabalho — fechar a janela no meio (ou o computador reiniciar) não pode
    custar tudo de novo.

    O arquivo é apagado assim que a varredura termina e os saldos são
    enviados para o painel.
    """

    ARQUIVO = "varredura_em_andamento.json"

    def __init__(self, pasta):
        from pathlib import Path

        self.caminho = Path(pasta) / self.ARQUIVO

    def salvar(self, perfil, fila, indice, resultados):
        from datetime import datetime

        try:
            dados = {
                "perfil": perfil.get("nome"),
                "porta": perfil.get("porta"),
                "indice": indice,
                "fila": fila,
                "resultados": resultados,
                "salvo_em": datetime.now().isoformat(timespec="seconds"),
            }
            with open(self.caminho, "w", encoding="utf-8") as arquivo:
                json.dump(dados, arquivo, ensure_ascii=False, indent=1)
        except Exception:
            pass    # nunca deixar o autosave atrapalhar a varredura

    def carregar(self):
        try:
            with open(self.caminho, encoding="utf-8") as arquivo:
                dados = json.load(arquivo)
        except Exception:
            return None
        if not dados.get("fila") or dados.get("indice", 0) >= len(dados["fila"]):
            return None
        return dados

    def pendente(self):
        """Resumo curto para o botão de retomar, ou None."""
        dados = self.carregar()
        if not dados:
            return None
        quando = (dados.get("salvo_em") or "")[:16].replace("T", " às ")
        return {
            "perfil": dados.get("perfil") or "?",
            "feitos": dados.get("indice", 0),
            "total": len(dados["fila"]),
            "quando": quando,
        }

    def limpar(self):
        try:
            self.caminho.unlink()
        except Exception:
            pass


def carregar_casas_do_perfil(pasta, perfil):
    """
    Monta a lista de casas de um perfil, priorizando o painel (Supabase).

    Devolve (casas, contexto, aviso):
      casas    -> lista de dicts com nome, link, saldo_anterior e `tipo`
                  ('ativa', 'zerada', 'nova', 'excluida')
      contexto -> {"cfg","user_id","dados"} quando a nuvem respondeu, senão None
      aviso    -> texto explicando por que caiu no modo offline, ou None

    Quando a nuvem responde, o profiles.json local também é atualizado —
    assim as casas cadastradas no painel entram na próxima varredura mesmo
    que você rode sem internet.
    """
    aviso = None
    if nuvem is not None:
        try:
            cfg = nuvem.carregar_config(pasta)
            user_id, dados = nuvem.baixar_estado(cfg)
            casas = nuvem.casas_do_perfil(dados, perfil)
            try:
                nuvem.atualizar_profiles_json(pasta, dados)
            except Exception:
                pass    # sincronizar o arquivo local é só conveniência
            if casas:
                return casas, {"cfg": cfg, "user_id": user_id, "dados": dados}, None
            aviso = (f"O painel não tem casas para o perfil "
                     f"'{nuvem.usuario_do_perfil(perfil)}'. Usando o profiles.json.")
        except Exception as e:
            aviso = f"Sem painel ({e}). Usando o profiles.json local."
    else:
        aviso = "nuvem.py não encontrado — usando só o profiles.json."

    # ---- offline: profiles.json ----
    completas = perfil.get("casas_painel") or []
    if completas:
        casas = [dict(c, saldo_anterior=c.get("saldo_anterior"),
                      tipo=c.get("tipo") or "ativa") for c in completas]
    else:
        casas = [{"nome": d, "dominio": d, "link": f"https://{d}",
                  "saldo_anterior": None, "tipo": "ativa"}
                 for d in (perfil.get("casas") or [])]
    return casas, None, aviso


def salvar_resultados(pasta, resultados):
    """Grava os dois arquivos combinados, preservando perfil e porta."""
    import csv

    json_path = pasta / "saldos.json"
    csv_path = pasta / "saldos.csv"

    with open(json_path, "w", encoding="utf-8") as arquivo:
        json.dump(resultados, arquivo, ensure_ascii=False, indent=2)

    colunas = [
        "perfil", "porta", "nome_casa", "dominio", "saldo", "saldo_anterior",
        "confianca", "origem", "corrigido", "precisa_login", "score",
        "casa_id", "detalhe", "url", "lido_em",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as arquivo:
        writer = csv.DictWriter(arquivo, fieldnames=colunas, extrasaction="ignore")
        writer.writeheader()
        for item in resultados:
            linha = dict(item)
            linha["precisa_login"] = "sim" if item.get("precisa_login") else ""
            linha["corrigido"] = "sim" if item.get("corrigido") else ""
            writer.writerow(linha)

    return json_path, csv_path


# ---------------------------------------------------------------- modo manual (janela flutuante)
class ScannerManual:
    """
    Mantém UMA aba aberta durante toda a varredura manual: navega para
    a página de cada casa e só roda o scanner quando o usuário mandar (ou
    seja, quando clicar "Saldo apareceu" na janela) — lendo exatamente o
    que está na tela naquele instante, sem tentar caminhos de fallback
    nem clicar em nada sozinho.

    Também sabe ligar o modo "clicar na tela", em que o próprio usuário
    aponta com o mouse qual número é o saldo.
    """

    def __init__(self, port):
        self.port = port
        self.aba = None
        self.aba_prox = None        # aba já carregando a próxima casa
        self.url_prox = None
        self._lock = threading.Lock()   # um comando por vez em cada aba

    def ir_para(self, casa):
        url = url_da_casa(casa)
        with self._lock:
            # se a próxima casa já estava carregando em segundo plano,
            # é só trazer aquela aba para a frente — página pronta, zero espera
            if self.aba_prox is not None and self.url_prox == url:
                antiga, self.aba = self.aba, self.aba_prox
                self.aba_prox, self.url_prox = None, None
                try:
                    self.aba.cmd("Page.bringToFront")
                except Exception:
                    pass
                if antiga is not None:
                    try:
                        antiga.fechar()
                    except Exception:
                        pass
                return url
            if self.aba is None:
                self.aba = Aba(self.port, url)
            else:
                self.aba.ir_para(url, espera_carregar=1.5)
        return url

    def preparar_proxima(self, casa):
        """Abre a próxima casa numa aba de fundo enquanto você confere a atual."""
        url = url_da_casa(casa)
        with self._lock:
            if self.aba_prox is not None:
                try:
                    self.aba_prox.fechar()
                except Exception:
                    pass
                self.aba_prox = None
            try:
                self.aba_prox = Aba(self.port, url)
                self.url_prox = url
                # a aba nova rouba o foco ao nascer; devolve para a atual
                if self.aba is not None:
                    self.aba.cmd("Page.bringToFront")
            except Exception:
                self.aba_prox, self.url_prox = None, None

    def ler_seletor(self, seletor):
        with self._lock:
            bruto = self.aba.js(js_ler_seletor(seletor), espera=8)
        try:
            return json.loads(bruto) if bruto else None
        except Exception:
            return None

    def farejar(self):
        """Olhada rápida e sem efeitos colaterais: já dá para ler o saldo?"""
        with self._lock:
            bruto = self.aba.js(JS_FAREJAR, espera=8)
        return json.loads(bruto) if bruto else None

    def ler_tela_atual(self):
        """Roda o JS_SCANNER na página exatamente como ela está agora."""
        with self._lock:
            bruto = self.aba.js(JS_SCANNER, espera=15)
        return json.loads(bruto) if bruto else None

    def iniciar_picker(self):
        with self._lock:
            self.aba.js(JS_PICKER, espera=10)

    def ler_picker(self):
        with self._lock:
            bruto = self.aba.js(JS_PICKER_LER, espera=8)
        if not bruto or bruto == "null":
            return None
        try:
            return json.loads(bruto)
        except Exception:
            return None

    def cancelar_picker(self):
        with self._lock:
            try:
                self.aba.js(JS_PICKER_CANCELAR, espera=8)
            except Exception:
                pass

    def fechar(self):
        for atributo in ("aba_prox", "aba"):
            aba = getattr(self, atributo, None)
            if aba is not None:
                try:
                    aba.fechar()
                except Exception:
                    pass
                setattr(self, atributo, None)
        self.url_prox = None


def _fmt_brl(valor):
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    except Exception:
        return "R$ 0,00"


class JanelaFlutuante(tk.Tk if tk else object):
    """
    Janelinha estilo TeamViewer, fixada no canto da tela.

    Fluxo:
      1. escolhe o perfil (você, Mãe, Pai...)
      2. baixa do painel (Supabase) as casas DAQUELE perfil e mostra a tela
         de seleção: as com saldo já vêm marcadas, as zeradas e as novas
         vêm desmarcadas — e você inclui/exclui o que quiser antes de começar
      3. abre uma casa por vez; você clica "Saldo apareceu"
      4. confere/corrige o valor lido (lista, digitação ou clique na tela)
      5. no fim, revisa tudo e manda os saldos de volta para o painel
    """

    LARGURA = 360
    ALT_INICIO = 210
    ALT_CASAS = 520
    ALT_VARREDURA = 415
    ALT_REVISAO = 520
    ALT_FINAL = 470

    FILTROS = [("todas", "Todas"), ("saldo", "Com saldo"),
               ("acao", "💸 Ajustar"), ("zerada", "Zeradas"), ("nova", "Novas")]

    # tipos que o botão "marcar visíveis" nunca marca: não há como varrer
    NAO_VARRE = {"sem_link", "encerrada"}

    def __init__(self, perfis, pasta):
        if tk is None:
            raise RuntimeError(
                "tkinter não está disponível neste Python (normalmente já "
                "vem instalado; em algumas distros Linux é `apt install "
                "python3-tk`)."
            )
        super().__init__()
        self.perfis = perfis
        self.pasta = pasta
        self.scanner = None
        self.resultados = []
        self.fila = []
        self.indice = -1
        self.perfil_atual = None
        self.travado = False
        self.estado = "inicio"
        self.candidatos = []
        self.item_pendente = None
        self.picker_ativo = False
        self.salvo = True
        self.enviado = False
        self.aprendizado = Aprendizado(pasta)
        self.progresso = Progresso(pasta)
        self._farejando = False
        self._agendados = []        # ids de after pendentes, cancelados ao sair

        # nuvem
        self.cfg_nuvem = None
        self.user_id_nuvem = None
        self.dados_nuvem = None
        self.casas_perfil = []      # [{casa..., "var": BooleanVar}]
        self.marcadas_nunca = set()  # casas que você mandou parar de verificar
        self.marcadas_limitada = {}  # casa_id -> data em que você viu a limitação
        self.filtro = "todas"

        self.title("Saldos")
        self.overrideredirect(True)          # sem moldura, estilo widget
        self.attributes("-topmost", True)    # sempre por cima
        try:
            self.attributes("-alpha", 0.97)
        except Exception:
            pass
        x = self.winfo_screenwidth() - self.LARGURA - 24
        self.geometry(f"{self.LARGURA}x{self.ALT_INICIO}+{x}+40")
        self.configure(bg=BG_W)

        self._montar_ui()
        self.bind_all("<Escape>", self._on_escape)

    # ---------- construção ----------
    def _montar_ui(self):
        barra = tk.Frame(self, bg=CARD_W, height=30, cursor="fleur")
        barra.pack(fill="x")
        barra.pack_propagate(False)
        tk.Label(barra, text="⠿ Saldos", bg=CARD_W, fg=MUTED_W,
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=10)
        fechar = tk.Label(barra, text="✕", bg=CARD_W, fg=MUTED_W,
                          cursor="hand2", font=("Segoe UI", 10, "bold"))
        fechar.pack(side="right", padx=10)
        fechar.bind("<Button-1>", lambda e: self.sair())
        barra.bind("<Button-1>", self._agarrar)
        barra.bind("<B1-Motion>", self._arrastar)

        corpo = tk.Frame(self, bg=BG_W)
        corpo.pack(fill="both", expand=True, padx=14, pady=12)
        self.corpo = corpo

        # ---- 1. escolha do perfil ----
        self.frm_inicio = tk.Frame(corpo, bg=BG_W)
        tk.Label(self.frm_inicio, text="Escolha o perfil:",
                 bg=BG_W, fg=FG_W, font=("Segoe UI", 10)).pack(anchor="w")
        self.combo = ttk.Combobox(
            self.frm_inicio, state="readonly",
            values=[p.get("nome", "?") for p in self.perfis])
        if self.perfis:
            self.combo.current(0)
        self.combo.pack(fill="x", pady=(4, 10))
        self.btn_iniciar = tk.Button(
            self.frm_inicio, text="▶ Conectar e listar casas", command=self.on_iniciar,
            bg=ACCENT_W, fg="white", relief="flat", activebackground=ACCENT_W)
        self.btn_iniciar.pack(fill="x")
        self.btn_retomar = tk.Button(
            self.frm_inicio, text="", command=self.on_retomar,
            bg=WARN_W, fg="white", relief="flat")
        self.btn_descartar = tk.Button(
            self.frm_inicio, text="🗑 descartar varredura salva", command=self.on_descartar,
            bg=BG_W, fg=MUTED_W, relief="flat", font=("Segoe UI", 8))

        # ---- 2. seleção de casas ----
        self.frm_casas = tk.Frame(corpo, bg=BG_W)
        self.lbl_casas_titulo = tk.Label(
            self.frm_casas, text="", bg=BG_W, fg=FG_W,
            font=("Segoe UI", 11, "bold"), wraplength=320, justify="left")
        self.lbl_casas_titulo.pack(anchor="w")
        self.lbl_casas_resumo = tk.Label(
            self.frm_casas, text="", bg=BG_W, fg=MUTED_W,
            font=("Segoe UI", 8), wraplength=320, justify="left")
        self.lbl_casas_resumo.pack(anchor="w", pady=(0, 6))

        linha_filtros = tk.Frame(self.frm_casas, bg=BG_W)
        linha_filtros.pack(fill="x", pady=(0, 6))
        self.btns_filtro = {}
        for chave, rotulo in self.FILTROS:
            b = tk.Button(linha_filtros, text=rotulo, relief="flat",
                          bg=CARD_W, fg=MUTED_W, font=("Segoe UI", 8),
                          command=lambda c=chave: self.on_filtro(c))
            b.pack(side="left", fill="x", expand=True, padx=1)
            self.btns_filtro[chave] = b

        caixa = tk.Frame(self.frm_casas, bg=CARD_W)
        caixa.pack(fill="both", expand=True)
        self.cv_casas = tk.Canvas(caixa, bg=CARD_W, highlightthickness=0, bd=0)
        self.sb_casas = ttk.Scrollbar(caixa, orient="vertical",
                                      command=self.cv_casas.yview)
        self.cv_casas.configure(yscrollcommand=self.sb_casas.set)
        self.sb_casas.pack(side="right", fill="y")
        self.cv_casas.pack(side="left", fill="both", expand=True)
        self.frm_lista = tk.Frame(self.cv_casas, bg=CARD_W)
        self.win_lista = self.cv_casas.create_window((0, 0), window=self.frm_lista,
                                                     anchor="nw")
        self.frm_lista.bind(
            "<Configure>",
            lambda e: self.cv_casas.configure(scrollregion=self.cv_casas.bbox("all")))
        self.cv_casas.bind(
            "<Configure>",
            lambda e: self.cv_casas.itemconfig(self.win_lista, width=e.width))
        self.cv_casas.bind("<Enter>", lambda e: self._ligar_roda(True))
        self.cv_casas.bind("<Leave>", lambda e: self._ligar_roda(False))

        linha_marcar = tk.Frame(self.frm_casas, bg=BG_W)
        linha_marcar.pack(fill="x", pady=(6, 6))
        tk.Button(linha_marcar, text="☑ marcar visíveis", relief="flat",
                  bg=CARD_W, fg=FG_W, font=("Segoe UI", 8),
                  command=lambda: self._marcar_visiveis(True)
                  ).pack(side="left", fill="x", expand=True, padx=(0, 3))
        tk.Button(linha_marcar, text="☐ desmarcar visíveis", relief="flat",
                  bg=CARD_W, fg=FG_W, font=("Segoe UI", 8),
                  command=lambda: self._marcar_visiveis(False)
                  ).pack(side="left", fill="x", expand=True, padx=(3, 3))
        tk.Button(linha_marcar, text="◉ só estas", relief="flat",
                  bg=ACCENT_W, fg="white", font=("Segoe UI", 8),
                  command=self._so_estas
                  ).pack(side="left", fill="x", expand=True, padx=(3, 0))

        self.btn_verificar = tk.Button(
            self.frm_casas, text="▶ Verificar casas marcadas",
            command=self.on_verificar, bg=OK_W, fg="white", relief="flat")
        self.btn_verificar.pack(fill="x")
        tk.Button(self.frm_casas, text="◀ trocar de perfil", relief="flat",
                  bg=BG_W, fg=MUTED_W, font=("Segoe UI", 8),
                  command=self.on_voltar_inicio).pack(fill="x", pady=(4, 0))

        # ---- 3. varredura ----
        self.frm_varredura = tk.Frame(corpo, bg=BG_W)
        self.lbl_progresso = tk.Label(self.frm_varredura, text="",
                                      bg=BG_W, fg=MUTED_W, font=("Segoe UI", 9))
        self.lbl_progresso.pack(anchor="w")
        self.lbl_dominio = tk.Label(self.frm_varredura, text="",
                                    bg=BG_W, fg=FG_W,
                                    font=("Segoe UI", 12, "bold"), wraplength=320)
        self.lbl_dominio.pack(anchor="w", pady=(2, 0))
        self.lbl_antes = tk.Label(self.frm_varredura, text="",
                                  bg=BG_W, fg=MUTED_W, font=("Segoe UI", 8))
        self.lbl_antes.pack(anchor="w", pady=(0, 10))
        self.auto = tk.BooleanVar(value=True)
        tk.Checkbutton(
            self.frm_varredura, text="⚡ avançar sozinho quando o saldo aparecer",
            variable=self.auto, command=self._alternar_auto,
            bg=BG_W, fg=MUTED_W, selectcolor=CARD_W, activebackground=BG_W,
            activeforeground=FG_W, anchor="w", highlightthickness=0, bd=0,
            font=("Segoe UI", 8)).pack(fill="x", pady=(0, 4))

        self.btn_ok = tk.Button(
            self.frm_varredura, text="✅ Saldo apareceu",
            command=self.on_confirmar, bg=OK_W, fg="white", relief="flat")
        self.btn_ok.pack(fill="x", pady=(0, 4))
        self.btn_igual = tk.Button(
            self.frm_varredura, text="= Manteve igual (não usei esta semana)",
            command=self.on_manteve_igual, bg=CARD_W, fg=FG_W, relief="flat",
            font=("Segoe UI", 9))
        self.btn_igual.pack(fill="x", pady=(0, 6))
        linha = tk.Frame(self.frm_varredura, bg=BG_W)
        linha.pack(fill="x", pady=(0, 4))
        self.btn_voltar = tk.Button(
            linha, text="◀ Voltar", command=self.on_voltar,
            bg=CARD_W, fg=FG_W, relief="flat")
        self.btn_voltar.pack(side="left", fill="x", expand=True, padx=(0, 3))
        self.btn_pular = tk.Button(
            linha, text="⏭ Pular", command=self.on_pular,
            bg=CARD_W, fg=FG_W, relief="flat")
        self.btn_pular.pack(side="left", fill="x", expand=True, padx=(3, 0))

        linha_b = tk.Frame(self.frm_varredura, bg=BG_W)
        linha_b.pack(fill="x")
        self.btn_login = tk.Button(
            linha_b, text="🔑 Precisa login", command=self.on_precisa_login,
            bg=CARD_W, fg=WARN_W, relief="flat", font=("Segoe UI", 9))
        self.btn_login.pack(side="left", fill="x", expand=True, padx=(0, 3))
        self.btn_nunca = tk.Button(
            linha_b, text="🚫 Nunca verificar", command=self.on_nunca,
            bg=CARD_W, fg=MUTED_W, relief="flat", font=("Segoe UI", 9))
        self.btn_nunca.pack(side="left", fill="x", expand=True, padx=(3, 0))

        self.btn_limitada = tk.Button(
            self.frm_varredura, text="🔒 Marcar como limitada",
            command=self.on_limitada, bg=CARD_W, fg=WARN_W, relief="flat",
            font=("Segoe UI", 9))
        self.btn_limitada.pack(fill="x", pady=(4, 0))

        # ---- 4. revisão / correção do valor lido ----
        self.frm_revisao = tk.Frame(corpo, bg=BG_W)
        self.lbl_rev_casa = tk.Label(self.frm_revisao, text="",
                                     bg=BG_W, fg=MUTED_W, font=("Segoe UI", 9),
                                     wraplength=320)
        self.lbl_rev_casa.pack(anchor="w")
        self.lbl_rev_valor = tk.Label(self.frm_revisao, text="",
                                      bg=BG_W, fg=FG_W,
                                      font=("Segoe UI", 15, "bold"))
        self.lbl_rev_valor.pack(anchor="w")
        self.lbl_rev_delta = tk.Label(self.frm_revisao, text="",
                                      bg=BG_W, fg=MUTED_W, font=("Segoe UI", 8))
        self.lbl_rev_delta.pack(anchor="w", pady=(0, 6))

        tk.Label(self.frm_revisao, text="Valores encontrados na página:",
                 bg=BG_W, fg=MUTED_W, font=("Segoe UI", 8)).pack(anchor="w")
        self.lst_cands = tk.Listbox(
            self.frm_revisao, height=6, bg=CARD_W, fg=FG_W,
            selectbackground=ACCENT_W, selectforeground="white",
            highlightthickness=0, relief="flat", activestyle="none",
            font=("Consolas", 9), exportselection=False)
        self.lst_cands.pack(fill="x", pady=(2, 6))
        self.lst_cands.bind("<<ListboxSelect>>", self._on_selecionou_candidato)
        self.lst_cands.bind("<Double-Button-1>", lambda e: self.on_usar())

        tk.Label(self.frm_revisao, text="…ou digite o valor certo:",
                 bg=BG_W, fg=MUTED_W, font=("Segoe UI", 8)).pack(anchor="w")
        self.ent_manual = tk.Entry(
            self.frm_revisao, bg=CARD_W, fg=FG_W, insertbackground=FG_W,
            relief="flat", font=("Consolas", 11))
        self.ent_manual.pack(fill="x", ipady=4, pady=(2, 8))
        self.ent_manual.bind("<Return>", lambda e: self.on_usar())

        self.mov_var = tk.BooleanVar(value=False)
        self.frm_mov = tk.Frame(self.frm_revisao, bg=BG_W)
        self.chk_mov = tk.Checkbutton(
            self.frm_mov, text="", variable=self.mov_var,
            bg=BG_W, fg=WARN_W, selectcolor=CARD_W, activebackground=BG_W,
            activeforeground=FG_W, anchor="w", highlightthickness=0, bd=0,
            font=("Segoe UI", 8), wraplength=310, justify="left")
        self.chk_mov.pack(fill="x")
        self.frm_mov.pack(fill="x", pady=(0, 6))

        self.btn_usar = tk.Button(
            self.frm_revisao, text="✔ Usar este valor", command=self.on_usar,
            bg=OK_W, fg="white", relief="flat")
        self.btn_usar.pack(fill="x", pady=(0, 6))

        linha2 = tk.Frame(self.frm_revisao, bg=BG_W)
        linha2.pack(fill="x", pady=(0, 6))
        self.btn_picker = tk.Button(
            linha2, text="🎯 Clicar na tela", command=self.on_picker,
            bg=ACCENT_W, fg="white", relief="flat")
        self.btn_picker.pack(side="left", fill="x", expand=True, padx=(0, 3))
        self.btn_reler = tk.Button(
            linha2, text="🔄 Ler de novo", command=self.on_reler,
            bg=CARD_W, fg=FG_W, relief="flat")
        self.btn_reler.pack(side="left", fill="x", expand=True, padx=(3, 0))

        self.btn_pular_rev = tk.Button(
            self.frm_revisao, text="⏭ Pular esta casa (sem saldo)",
            command=self.on_pular, bg=CARD_W, fg=MUTED_W, relief="flat")
        self.btn_pular_rev.pack(fill="x")

        # ---- 5. tela final ----
        self.frm_final = tk.Frame(corpo, bg=BG_W)
        tk.Label(self.frm_final, text="Confira antes de enviar:",
                 bg=BG_W, fg=FG_W, font=("Segoe UI", 10)).pack(anchor="w")
        self.lst_final = tk.Listbox(
            self.frm_final, height=9, bg=CARD_W, fg=FG_W,
            selectbackground=ACCENT_W, selectforeground="white",
            highlightthickness=0, relief="flat", activestyle="none",
            font=("Consolas", 9), exportselection=False)
        self.lst_final.pack(fill="x", pady=(4, 6))
        self.lst_final.bind("<<ListboxSelect>>", self._on_selecionou_final)
        self.ent_final = tk.Entry(
            self.frm_final, bg=CARD_W, fg=FG_W, insertbackground=FG_W,
            relief="flat", font=("Consolas", 11))
        self.ent_final.pack(fill="x", ipady=4, pady=(0, 6))
        self.ent_final.bind("<Return>", lambda e: self.on_corrigir_final())
        self.btn_corrigir = tk.Button(
            self.frm_final, text="✏ Aplicar à linha selecionada",
            command=self.on_corrigir_final, bg=CARD_W, fg=FG_W, relief="flat")
        self.btn_corrigir.pack(fill="x", pady=(0, 6))
        self.btn_enviar = tk.Button(
            self.frm_final, text="☁ Enviar saldos para o painel",
            command=self.on_enviar, bg=OK_W, fg="white", relief="flat")
        self.btn_enviar.pack(fill="x", pady=(0, 6))
        self.btn_outro = tk.Button(
            self.frm_final, text="▶ Rodar outro perfil", command=self.on_outro_perfil,
            bg=CARD_W, fg=FG_W, relief="flat")
        self.btn_outro.pack(fill="x")

        self.lbl_status = tk.Label(corpo, text="", bg=BG_W, fg=MUTED_W,
                                   font=("Segoe UI", 8), wraplength=320,
                                   justify="left")
        self.lbl_status.pack(side="bottom", anchor="w", pady=(8, 0))

        self._montar_teclas()
        self._atualizar_retomar()
        self._ir_para_estado("inicio")

    def _atualizar_retomar(self):
        pend = self.progresso.pendente()
        if not pend:
            self.btn_retomar.pack_forget()
            self.btn_descartar.pack_forget()
            return
        feitos, total = pend["feitos"], pend["total"]
        self.btn_retomar.config(
            text=f"↩ Retomar {pend['perfil']} ({feitos}/{total})")
        self.btn_retomar.pack(fill="x", pady=(6, 0))
        self.btn_descartar.pack(fill="x")
        self._status(
            f"Você parou no meio de uma varredura do {pend['perfil']} "
            f"em {pend['quando']}.", WARN_W)

    # ---------- teclado ----------
    def _montar_teclas(self):
        # Em 40+ casas, tirar a mão do teclado a cada casa custa caro.
        self.bind_all("<Return>", self._tecla_enter)
        self.bind_all("<KP_Enter>", self._tecla_enter)
        self.bind_all("<Control-Right>", self._tecla_pular)
        self.bind_all("<space>", self._tecla_igual)
        self.bind_all("<Control-Left>", self._tecla_voltar)
        self.bind_all("<Up>", self._tecla_seta)
        self.bind_all("<Down>", self._tecla_seta)

    def _no_campo(self):
        try:
            return isinstance(self.focus_get(), tk.Entry)
        except Exception:
            return False

    def _tecla_enter(self, _e=None):
        if self._no_campo():
            return          # o próprio Entry já trata o Enter
        acoes = {"inicio": self.on_iniciar, "casas": self.on_verificar,
                 "varredura": self.on_confirmar, "revisao": self.on_usar,
                 "final": self.on_enviar}
        acao = acoes.get(self.estado)
        if acao:
            acao()
        return "break"

    def _tecla_pular(self, _e=None):
        if self.estado in ("varredura", "revisao"):
            self.on_pular()
        return "break"

    def _tecla_igual(self, _e=None):
        # espaço na tela de varredura = "não mexeu, próxima"
        if self.estado == "varredura" and not self._no_campo():
            self.on_manteve_igual()
            return "break"

    def _tecla_voltar(self, _e=None):
        if self.estado == "varredura":
            self.on_voltar()
        return "break"

    def _tecla_seta(self, evento):
        if self.estado != "revisao" or self._no_campo():
            return
        total = self.lst_cands.size()
        if not total:
            return
        atual = self.lst_cands.curselection()
        pos = atual[0] if atual else 0
        pos = max(0, min(total - 1, pos + (1 if evento.keysym == "Down" else -1)))
        self.lst_cands.selection_clear(0, "end")
        self.lst_cands.selection_set(pos)
        self.lst_cands.see(pos)
        self._on_selecionou_candidato()
        return "break"

    # ---------- utilidades de janela ----------
    def _agarrar(self, event):
        self._dx, self._dy = event.x, event.y

    def _arrastar(self, event):
        x = self.winfo_x() + (event.x - self._dx)
        y = self.winfo_y() + (event.y - self._dy)
        self.geometry(f"+{x}+{y}")

    def _ligar_roda(self, ligar):
        if ligar:
            self.cv_casas.bind_all("<MouseWheel>", self._rolar)
            self.cv_casas.bind_all("<Button-4>", self._rolar)
            self.cv_casas.bind_all("<Button-5>", self._rolar)
        else:
            self.cv_casas.unbind_all("<MouseWheel>")
            self.cv_casas.unbind_all("<Button-4>")
            self.cv_casas.unbind_all("<Button-5>")

    def _rolar(self, event):
        if getattr(event, "num", None) == 4:
            passo = -1
        elif getattr(event, "num", None) == 5:
            passo = 1
        else:
            passo = -1 if event.delta > 0 else 1
        self.cv_casas.yview_scroll(passo, "units")

    def _on_escape(self, _event=None):
        if self.picker_ativo:
            self._parar_picker()
            self._status("Seleção por clique cancelada.", MUTED_W)
            return
        if self.estado == "inicio":
            self.sair()

    def _agendar(self, ms, funcao):
        """after() que não vira erro de console se a janela fechar antes."""
        ident = self.after(ms, funcao)
        self._agendados.append(ident)
        return ident

    def _status(self, texto, cor=MUTED_W):
        self.lbl_status.config(text=texto, fg=cor)
        self.update_idletasks()

    def _ir_para_estado(self, estado):
        self.estado = estado
        frames = {"inicio": self.frm_inicio, "casas": self.frm_casas,
                  "varredura": self.frm_varredura, "revisao": self.frm_revisao,
                  "final": self.frm_final}
        alturas = {"inicio": self.ALT_INICIO, "casas": self.ALT_CASAS,
                   "varredura": self.ALT_VARREDURA, "revisao": self.ALT_REVISAO,
                   "final": self.ALT_FINAL}
        for frame in frames.values():
            frame.pack_forget()
        frames[estado].pack(fill="both", expand=True)
        self.geometry(
            f"{self.LARGURA}x{alturas[estado]}+{self.winfo_x()}+{self.winfo_y()}")

    def _travar(self, travado):
        self.travado = travado
        estado = "disabled" if travado else "normal"
        for botao in (self.btn_ok, self.btn_pular, self.btn_voltar,
                      self.btn_usar, self.btn_picker, self.btn_reler,
                      self.btn_pular_rev, self.btn_login, self.btn_nunca,
                      self.btn_limitada, self.btn_igual):
            botao.config(state=estado)
        if not travado and self.indice <= 0:
            self.btn_voltar.config(state="disabled")

    # ---------- 1. perfil -> casas ----------
    def on_iniciar(self):
        if not self.perfis:
            self._status("Nenhum perfil no profiles.json.", ERR_W)
            return
        nome = self.combo.get()
        self.perfil_atual = next(
            (p for p in self.perfis if p.get("nome") == nome), None)
        if not self.perfil_atual:
            self._status("Selecione um perfil.", ERR_W)
            return
        self.btn_iniciar.config(state="disabled")
        self._status("Abrindo o Opera e buscando as casas...", MUTED_W)
        threading.Thread(target=self._conectar_e_listar, daemon=True).start()

    def _conectar_e_listar(self):
        try:
            porta, erro = obter_debug_port(self.perfil_atual)
        except Exception as e:
            porta, erro = None, str(e)
        if erro:
            self.after(0, lambda: self._status(f"Erro: {erro}", ERR_W))
            self.after(0, lambda: self.btn_iniciar.config(state="normal"))
            return
        if self.scanner:
            self.scanner.fechar()
        self.scanner = ScannerManual(porta)

        casas, contexto, aviso = carregar_casas_do_perfil(self.pasta, self.perfil_atual)
        if contexto:
            self.cfg_nuvem = contexto["cfg"]
            self.user_id_nuvem = contexto["user_id"]
            self.dados_nuvem = contexto["dados"]
        else:
            self.cfg_nuvem = self.user_id_nuvem = self.dados_nuvem = None

        self.resultados = []
        self.indice = -1
        self.salvo = True
        self.enviado = False
        self.after(0, lambda: self._montar_lista_casas(casas, aviso))

    def _montar_lista_casas(self, casas, aviso=None):
        for var in self.frm_lista.winfo_children():
            var.destroy()
        self.casas_perfil = []
        for casa in casas:
            marcado = casa.get("tipo") == "ativa"
            item = dict(casa)
            item["var"] = tk.BooleanVar(value=marcado)
            self.casas_perfil.append(item)

        nome = self.perfil_atual.get("nome", "?")
        contagem = {"ativa": 0, "zerada": 0, "nova": 0, "excluida": 0}
        for casa in self.casas_perfil:
            contagem[casa.get("tipo", "ativa")] = contagem.get(casa.get("tipo", "ativa"), 0) + 1
        self.lbl_casas_titulo.config(text=f"{nome} · {len(self.casas_perfil)} casas")
        precisam = [c for c in self.casas_perfil
                    if c.get("acao") and c.get("tipo") not in self.NAO_VARRE]
        self.n_ajustar = len(precisam)
        semlink = contagem.get("sem_link", 0)
        self.lbl_casas_resumo.config(
            text=(f"{contagem['ativa']} com saldo · {contagem['zerada']} zeradas · "
                  f"{contagem['nova']} novas · {contagem['excluida']} p/ não verificar"
                  + (f" · {semlink} sem link" if semlink else "")
                  + (f"\n💸 {self.n_ajustar} fora da meta: "
                     f"{sum(1 for c in precisam if c['acao']=='sacar')} p/ sacar, "
                     f"{sum(1 for c in precisam if c['acao']=='depositar')} p/ depositar"
                     if precisam else "")))
        self.filtro = "todas"
        self._ir_para_estado("casas")
        self._redesenhar_lista()
        self._status(aviso or "As zeradas e as novas vêm desmarcadas — marque as que quiser incluir.",
                     WARN_W if aviso else MUTED_W)

    def _casas_visiveis(self):
        if self.filtro == "todas":
            return self.casas_perfil
        if self.filtro == "saldo":
            return [c for c in self.casas_perfil if c.get("tipo") == "ativa"]
        if self.filtro == "acao":
            # só as que estão fora da meta do campo "deixar" do painel
            return [c for c in self.casas_perfil
                    if c.get("acao") and c.get("tipo") not in self.NAO_VARRE]
        return [c for c in self.casas_perfil if c.get("tipo") == self.filtro]

    def _redesenhar_lista(self):
        for widget in self.frm_lista.winfo_children():
            widget.destroy()
        for chave, _ in self.FILTROS:
            botao = self.btns_filtro[chave]
            ativo = chave == self.filtro
            botao.config(bg=ACCENT_W if ativo else CARD_W,
                         fg="white" if ativo else MUTED_W)

        marcas = {"ativa": "", "zerada": "💤", "nova": "🆕", "excluida": "🚫",
                  "sem_link": "🔗"}
        cores = {"ativa": FG_W, "zerada": MUTED_W, "nova": WARN_W,
                 "excluida": MUTED_W, "sem_link": ERR_W}
        for casa in self._casas_visiveis():
            tipo = casa.get("tipo", "ativa")
            rotulo = (f"{marcas.get(tipo, '')} {casa['nome']}  ·  "
                      f"{_fmt_brl(casa.get('saldo_anterior') or 0)}").strip()
            if casa.get("acao"):
                seta = "↑ sacar" if casa["acao"] == "sacar" else "↓ depositar"
                rotulo += f"  ({seta} {_fmt_brl(casa.get('quanto') or 0)})"
            chk = tk.Checkbutton(
                self.frm_lista, text=rotulo, variable=casa["var"],
                bg=CARD_W, fg=cores.get(tipo, FG_W), selectcolor=BG_W,
                activebackground=CARD_W, activeforeground=FG_W,
                anchor="w", highlightthickness=0, bd=0, padx=6, pady=1,
                font=("Segoe UI", 9), command=self._atualizar_contador)
            chk.pack(fill="x")
        self.cv_casas.yview_moveto(0)
        self._atualizar_contador()

    def _atualizar_contador(self):
        marcadas = sum(1 for c in self.casas_perfil if c["var"].get())
        self.btn_verificar.config(
            text=f"▶ Verificar {marcadas} casa(s)",
            state="normal" if marcadas else "disabled")

    def on_filtro(self, chave):
        self.filtro = chave
        self._redesenhar_lista()

    def _marcar_visiveis(self, valor):
        bloqueadas = 0
        for casa in self._casas_visiveis():
            if valor and casa.get("tipo") in self.NAO_VARRE:
                bloqueadas += 1
                continue
            casa["var"].set(valor)
        self._atualizar_contador()
        if bloqueadas:
            self._status(f"{bloqueadas} casa(s) sem link ficaram de fora — "
                         "cadastre o link no painel primeiro.", WARN_W)

    def _so_estas(self):
        """
        Marca exatamente as casas do filtro atual e desmarca todo o resto —
        é o que você quer no modo Ajustar: rodar só as que estão fora da meta.
        """
        visiveis = {id(c) for c in self._casas_visiveis()}
        bloqueadas = 0
        for casa in self.casas_perfil:
            if id(casa) in visiveis:
                if casa.get("tipo") in self.NAO_VARRE:
                    bloqueadas += 1
                    casa["var"].set(False)
                else:
                    casa["var"].set(True)
            else:
                casa["var"].set(False)
        self._atualizar_contador()
        marcadas = sum(1 for c in self.casas_perfil if c["var"].get())
        aviso = f" ({bloqueadas} sem link ficaram de fora)" if bloqueadas else ""
        self._status(f"Seleção trocada: só as {marcadas} casa(s) deste filtro{aviso}.",
                     MUTED_W)

    def on_voltar_inicio(self):
        if self.scanner:
            self.scanner.fechar()
            self.scanner = None
        self._ir_para_estado("inicio")
        self.btn_iniciar.config(state="normal")
        self._status("", MUTED_W)

    def on_retomar(self):
        dados = self.progresso.carregar()
        if not dados:
            self._atualizar_retomar()
            return
        perfil = next((p for p in self.perfis
                       if p.get("nome") == dados.get("perfil")), None)
        if not perfil:
            self._status(f"O perfil '{dados.get('perfil')}' não está mais "
                         "no profiles.json.", ERR_W)
            return
        self.perfil_atual = perfil
        self._retomando = dados
        self.btn_iniciar.config(state="disabled")
        self.btn_retomar.config(state="disabled")
        self._status(f"Reconectando ao {perfil.get('nome')}...", MUTED_W)
        threading.Thread(target=self._conectar_e_retomar, daemon=True).start()

    def _conectar_e_retomar(self):
        try:
            porta, erro = obter_debug_port(self.perfil_atual)
        except Exception as e:
            porta, erro = None, str(e)
        if erro:
            self.after(0, lambda: self._status(f"Erro: {erro}", ERR_W))
            self.after(0, lambda: self.btn_iniciar.config(state="normal"))
            self.after(0, lambda: self.btn_retomar.config(state="normal"))
            return
        if self.scanner:
            self.scanner.fechar()
        self.scanner = ScannerManual(porta)

        # a nuvem é recarregada para o envio final continuar funcionando
        _casas, contexto, _aviso = carregar_casas_do_perfil(self.pasta, self.perfil_atual)
        if contexto:
            self.cfg_nuvem = contexto["cfg"]
            self.user_id_nuvem = contexto["user_id"]
            self.dados_nuvem = contexto["dados"]

        dados = self._retomando
        self.fila = dados["fila"]
        self.resultados = dados.get("resultados") or []
        self.indice = dados["indice"] - 1
        self.salvo = True
        self.enviado = False
        self.after(0, lambda: self._ir_para_estado("varredura"))
        self.after(0, self._proxima_casa)

    def on_descartar(self):
        self.progresso.limpar()
        self._atualizar_retomar()
        self._status("Varredura salva descartada.", MUTED_W)

    def on_verificar(self):
        # `var` é widget e `_ref` é ponteiro para o dict da nuvem: nenhum dos
        # dois sobrevive a salvar/retomar, então não entram na fila
        self.fila = [{k: v for k, v in c.items() if k not in ("var", "_ref")}
                     for c in self.casas_perfil
                     if c["var"].get() and c.get("tipo") not in self.NAO_VARRE]
        if not self.fila:
            self._status("Marque pelo menos uma casa.", WARN_W)
            return
        # maiores saldos primeiro: se você parar no meio, já pegou o que pesa
        self.fila.sort(key=lambda c: -(c.get("saldo_anterior") or 0))
        self.resultados = []
        self.indice = -1
        self._ir_para_estado("varredura")
        self._proxima_casa()

    # ---------- 2. varredura ----------
    def _proxima_casa(self):
        self.indice += 1
        if self.indice >= len(self.fila):
            self._finalizar()
            return
        casa = self.fila[self.indice]
        self._ir_para_estado("varredura")
        self.lbl_progresso.config(
            text=f"{self.indice + 1} / {len(self.fila)} · {self.perfil_atual.get('nome')}")
        self.lbl_dominio.config(text=rotulo_da_casa(casa))
        self._limpar_movimento()
        ja_limitada = casa.get("casa_id") in self.marcadas_limitada
        self.btn_limitada.config(
            text="🔒 limitada ✓ (clique p/ desfazer)" if ja_limitada
            else "🔒 Marcar como limitada",
            fg=OK_W if ja_limitada else WARN_W)
        anterior = casa.get("saldo_anterior")
        texto = (f"no painel: {_fmt_brl(anterior)}" if anterior is not None
                 else dominio_da_casa(casa))
        if casa.get("acao"):
            verbo = "SACAR" if casa["acao"] == "sacar" else "DEPOSITAR"
            texto += f"   ➜ {verbo} {_fmt_brl(casa.get('quanto') or 0)}"
        self.lbl_antes.config(
            text=texto,
            fg=WARN_W if casa.get("acao") else MUTED_W)
        self._status("Abrindo a casa...", MUTED_W)
        self._travar(True)
        threading.Thread(target=self._abrir_casa, args=(casa,), daemon=True).start()

    def _abrir_casa(self, casa):
        try:
            self.scanner.ir_para(casa)
            msg = ("Procurando o saldo sozinho..." if self.auto.get()
                   else "Navegue se precisar e clique em Saldo apareceu.")
            cor = MUTED_W
        except Exception as e:
            msg = f"não consegui abrir sozinho ({e}) — pode navegar manualmente e confirmar."
            cor = WARN_W
        self.after(0, lambda: self._status(msg, cor))
        self.after(0, lambda: self._travar(False))
        self.after(0, self._iniciar_farejador)
        # enquanto você olha esta casa, a próxima já vai carregando
        seguinte = self.indice + 1
        if seguinte < len(self.fila):
            try:
                self.scanner.preparar_proxima(self.fila[seguinte])
            except Exception:
                pass

    # ---------- detecção automática ----------
    def _alternar_auto(self):
        if self.auto.get():
            self._iniciar_farejador()
        else:
            self._farejando = False
            self._status("Modo manual: clique em Saldo apareceu.", MUTED_W)

    def _iniciar_farejador(self):
        if not self.auto.get() or self.estado != "varredura" or self.scanner is None:
            return
        if self._farejando:
            return
        self._farejando = True
        threading.Thread(target=self._farejar, daemon=True).start()

    def _farejar(self):
        """
        Fica de olho na página sem tocar em nada. Assim que aparece um valor
        com contexto de saldo (não de odd, não de bônus), avança sozinho para
        a conferência — você só confirma.
        """
        limite = time.time() + 120
        avisou_login = False
        while self._farejando and time.time() < limite:
            time.sleep(1.5)
            if not self._farejando or self.travado:
                continue
            try:
                res = self.scanner.farejar()
            except Exception:
                continue
            if not res:
                continue
            if res.get("login") and not avisou_login:
                avisou_login = True
                self.after(0, lambda: self._status(
                    "Tela de login. Entre, ou clique em 🔑 Precisa login para "
                    "deixar para depois.", WARN_W))
            if res.get("score", 0) >= 70:
                self._farejando = False
                self.after(0, self._auto_achou)
                return

    def _auto_achou(self):
        if self.estado == "varredura" and not self.travado:
            self._status("Achei um saldo na tela — conferindo...", OK_W)
            self.on_confirmar()

    # ---------- 3. leitura + revisão ----------
    def on_confirmar(self):
        if self.travado or self.scanner is None:
            return
        self._farejando = False
        self._travar(True)
        self._status("Lendo o que está na tela agora...", MUTED_W)
        threading.Thread(target=self._ler_tela, daemon=True).start()

    def on_reler(self):
        if self.travado or self.scanner is None:
            return
        self._travar(True)
        self._status("Lendo a tela de novo...", MUTED_W)
        threading.Thread(target=self._ler_tela, daemon=True).start()

    def _ler_tela(self):
        erro = None
        try:
            res = self.scanner.ler_tela_atual()
        except Exception as e:
            res, erro = None, str(e)[:160]

        # aviso separado: se ficasse dentro do try acima, qualquer problema
        # aqui viraria "falha ao ler a tela", que é enganoso
        aba = getattr(self.scanner, "aba", None)
        if getattr(aba, "recriada", False):
            aba.recriada = False
            self.after(0, lambda: self._status(
                "A aba havia fechado — reabri a página. Espere carregar e "
                "clique em 🔄 Ler de novo.", WARN_W))

        # antes de mostrar, olha direto no lugar que você apontou da última
        # vez nessa casa — se ainda existe, ele vira o primeiro da lista
        dominio = dominio_da_casa(self.fila[self.indice])
        fixados = []
        for seletor in self.aprendizado.seletores(dominio):
            try:
                achado = self.scanner.ler_seletor(seletor)
            except Exception:
                continue
            if achado and achado.get("achou") and achado.get("texto"):
                fixados.append({
                    "texto": achado["texto"],
                    "score": 100,
                    "amostra": achado.get("amostra", ""),
                    "fixo": True,
                    "seletor": seletor,
                })
                break
            # caminho não existe mais: o site mudou de layout
            self.aprendizado.esquecer_seletor(dominio, seletor)

        self.after(0, lambda: self._mostrar_revisao(res, erro, fixados))

    def _mostrar_revisao(self, res, erro=None, fixados=None):
        casa = self.fila[self.indice]
        self.candidatos = (res or {}).get("candidatos") or []
        if not self.candidatos and (res or {}).get("melhor"):
            self.candidatos = [res["melhor"]]
        for fixo in (fixados or []):
            # se o scanner já achou o mesmo valor, não duplica: só marca
            igual = next((c for c in self.candidatos
                          if (c.get("texto") or "").replace(" ", "")
                          == fixo["texto"].replace(" ", "")), None)
            if igual:
                igual["fixo"] = True
                igual["seletor"] = fixo["seletor"]
            else:
                self.candidatos.insert(0, fixo)
        dominio = dominio_da_casa(casa)
        self.candidatos, aprendeu = self.aprendizado.reordenar(dominio, self.candidatos)

        self.item_pendente = dict(identidade_da_casa(casa))
        self.item_pendente.update({
            "perfil": self.perfil_atual.get("nome"),
            "porta": self.perfil_atual.get("porta"),
            "url": (res or {}).get("url"),
            "candidatos_vistos": [c.get("texto") for c in self.candidatos],
        })
        if erro:
            self.item_pendente["detalhe"] = erro

        self._ir_para_estado("revisao")
        self.lbl_rev_casa.config(
            text=f"{self.indice + 1}/{len(self.fila)} · {rotulo_da_casa(casa)}")
        self.lst_cands.delete(0, "end")
        self.ent_manual.delete(0, "end")
        # zera a caixinha de saque/depósito: ela é da casa ATUAL. Sem isso, um
        # saque marcado na casa anterior continuava na tela e podia ser gravado
        # na casa errada.
        self._limpar_movimento()

        for c in self.candidatos:
            marca = " 📍" if c.get("fixo") else (" ★" if c.get("bonus") else "  ")
            self.lst_cands.insert(
                "end", f"{c.get('texto', ''):<16}{marca} {c.get('score_final', c.get('score', 0)):>4}")

        if self.candidatos:
            self.lst_cands.selection_set(0)
            self.lst_cands.see(0)
            self.lbl_rev_valor.config(text=self.candidatos[0].get("texto", ""), fg=FG_W)
            self._atualizar_delta(self.candidatos[0].get("texto"))
            memoria = self.aprendizado.resumo(dominio_da_casa(casa))
            if self.candidatos[0].get("fixo"):
                self._status("📍 valor lido do lugar exato que você apontou "
                             "da última vez nesta casa.", OK_W)
            elif aprendeu and memoria:
                self._status(
                    f"★ = parecido com o que você escolheu aqui antes "
                    f"({memoria['correcoes']} correção(ões) aprendidas).", ACCENT_W)
            else:
                self._status(
                    "Certo? Clique em Usar. Errado? Escolha outro da lista, "
                    "digite, ou use 🎯 Clicar na tela.", MUTED_W)
        else:
            self.lbl_rev_valor.config(text="não achei nenhum R$", fg=WARN_W)
            self.lbl_rev_delta.config(text="")
            self._status(
                erro or "Nada em R$ na tela. Digite o valor ou use 🎯 Clicar na tela.",
                WARN_W)
        self._travar(False)

    def _atualizar_delta(self, texto_valor):
        casa = self.fila[self.indice]
        anterior = casa.get("saldo_anterior")
        novo = normalizar_valor(texto_valor)
        self._atualizar_movimento(texto_valor)
        if anterior is None or novo is None:
            self.lbl_rev_delta.config(text="", fg=MUTED_W)
            return
        try:
            numero = float(novo.replace("R$", "").replace(".", "")
                           .replace(",", ".").strip())
        except ValueError:
            self.lbl_rev_delta.config(text="", fg=MUTED_W)
            return
        dif = numero - float(anterior)
        sinal = "+" if dif >= 0 else "−"
        cor = MUTED_W if abs(dif) < 0.005 else (OK_W if dif > 0 else WARN_W)
        self.lbl_rev_delta.config(
            text=f"antes {_fmt_brl(anterior)}  →  {sinal}{_fmt_brl(abs(dif))}", fg=cor)

    def _movimento_confere(self, texto_valor):
        """O saque/depósito pendente bate com o valor que está sendo salvo?"""
        casa = self.fila[self.indice]
        anterior = casa.get("saldo_anterior")
        novo = normalizar_valor(texto_valor)
        if anterior is None or novo is None:
            return False
        try:
            numero = float(novo.replace("R$", "").replace(".", "")
                           .replace(",", ".").strip())
        except ValueError:
            return False
        dif = numero - float(anterior)
        esperado = "saque_casa" if dif < 0 else "deposito_casa"
        return (esperado == self._mov_tipo
                and abs(abs(dif) - float(self._mov_valor or 0)) < 0.01)

    def _limpar_movimento(self):
        self._mov_valor, self._mov_tipo = 0.0, None
        self.mov_var.set(False)
        self.frm_mov.pack_forget()

    def _atualizar_movimento(self, texto_valor):
        """
        Se você acabou de sacar ou depositar nesta casa, a diferença de saldo
        NÃO é lucro. Marcando aqui, ela vai para o painel como movimentação e
        o resultado da casa continua verdadeiro.
        """
        casa = self.fila[self.indice]
        anterior = casa.get("saldo_anterior")
        novo = normalizar_valor(texto_valor)
        self._mov_valor, self._mov_tipo = 0.0, None
        if anterior is None or novo is None or self.dados_nuvem is None:
            self.frm_mov.pack_forget()
            self.mov_var.set(False)
            return
        try:
            numero = float(novo.replace("R$", "").replace(".", "")
                           .replace(",", ".").strip())
        except ValueError:
            self.frm_mov.pack_forget()
            return
        dif = numero - float(anterior)
        if abs(dif) < 1:
            self.frm_mov.pack_forget()
            self.mov_var.set(False)
            return

        # o sinal da diferença diz o que provavelmente aconteceu
        self._mov_tipo = "saque_casa" if dif < 0 else "deposito_casa"
        self._mov_valor = round(abs(dif), 2)
        verbo = "saquei" if dif < 0 else "depositei"
        # já vem marcado quando a casa estava mesmo na lista de ajuste e o
        # sentido bate com o que o painel pedia
        esperado = casa.get("acao")
        bate = (esperado == "sacar" and dif < 0) or (esperado == "depositar" and dif > 0)
        self.chk_mov.config(
            text=f"registrar que {verbo} {_fmt_brl(self._mov_valor)} aqui "
                 f"(senão vira lucro/prejuízo no painel)")
        self.mov_var.set(bool(bate))
        self.frm_mov.pack(fill="x", pady=(0, 6), before=self.btn_usar)

    def _on_selecionou_candidato(self, _event=None):
        sel = self.lst_cands.curselection()
        if not sel:
            return
        c = self.candidatos[sel[0]]
        self.lbl_rev_valor.config(text=c.get("texto", ""), fg=FG_W)
        self._atualizar_delta(c.get("texto"))
        amostra = (c.get("amostra") or "").strip()
        if amostra:
            self._status(f"contexto: {amostra}", MUTED_W)

    # ---------- clicar na tela ----------
    def on_picker(self):
        if self.travado or self.scanner is None or self.picker_ativo:
            return
        self.picker_ativo = True
        self.btn_picker.config(text="✋ Cancelar clique", command=self.on_cancelar_picker)
        self._status("Vá até o navegador e clique no saldo certo (Esc cancela).", ACCENT_W)
        threading.Thread(target=self._rodar_picker, daemon=True).start()

    def on_cancelar_picker(self):
        self._parar_picker()
        self._status("Seleção por clique cancelada.", MUTED_W)

    def _parar_picker(self):
        self.picker_ativo = False
        self.btn_picker.config(text="🎯 Clicar na tela", command=self.on_picker)
        if self.scanner:
            threading.Thread(target=self.scanner.cancelar_picker, daemon=True).start()

    def _rodar_picker(self):
        try:
            self.scanner.iniciar_picker()
        except Exception as e:
            # `e` some ao sair do except: se o lambda ler pelo nome, dá NameError
            # e a mensagem nunca chega na tela. Congela o texto agora.
            bruto = str(e)
            if "No such target" in bruto or "10053" in bruto or "Handshake" in bruto:
                msg = ("A aba desta casa foi fechada ou o perfil reiniciou. "
                       "Clique em 🔄 Ler de novo — eu reabro a página.")
            else:
                msg = f"Não consegui ligar o modo clique: {bruto[:90]}"
            self.after(0, lambda: self._status(msg, WARN_W))
            self.after(0, self._parar_picker)
            return

        limite = time.time() + 120
        while self.picker_ativo and time.time() < limite:
            time.sleep(0.4)
            try:
                escolha = self.scanner.ler_picker()
            except Exception:
                continue
            if not escolha:
                continue
            self.after(0, lambda e=escolha: self._recebeu_clique(e))
            return
        if self.picker_ativo:
            self.after(0, self._parar_picker)
            self.after(0, lambda: self._status("Tempo esgotado no modo clique.", WARN_W))

    def _recebeu_clique(self, escolha):
        self._parar_picker()
        if escolha.get("cancelado"):
            self._status("Você cancelou pelo navegador.", MUTED_W)
            return
        valor = normalizar_valor(escolha.get("texto"))
        if not valor:
            self._status(
                f"Cliquei em '{escolha.get('bruto', '')[:40]}' mas não vi número. "
                "Tente clicar direto no número.", WARN_W)
            return
        self.ent_manual.delete(0, "end")
        self.ent_manual.insert(0, valor)
        self.lbl_rev_valor.config(text=valor, fg=OK_W)
        self._atualizar_delta(valor)
        self.item_pendente["origem_clique"] = escolha.get("bruto", "")[:120]
        seletor = escolha.get("seletor")
        if seletor:
            self.aprendizado.registrar_seletor(
                dominio_da_casa(self.fila[self.indice]), seletor,
                escolha.get("bruto", ""))
            self.item_pendente["seletor"] = seletor
        self._status("Peguei pelo clique. Confira e clique em Usar este valor.", OK_W)

    # ---------- gravar o valor ----------
    def on_usar(self):
        if self.travado or self.estado != "revisao":
            return
        digitado = self.ent_manual.get().strip()
        if digitado:
            valor = normalizar_valor(digitado)
            if not valor:
                self._status("Não entendi esse valor. Ex.: 1234,56", ERR_W)
                return
            origem = "clique" if self.item_pendente.get("origem_clique") else "digitado"
            score = None
            contexto = ""
        else:
            sel = self.lst_cands.curselection()
            if not sel:
                self._status("Escolha um valor na lista ou digite o certo.", WARN_W)
                return
            c = self.candidatos[sel[0]]
            valor = c.get("texto")
            origem = "scanner" if sel[0] == 0 else "lista"
            score = c.get("score")
            contexto = c.get("amostra", "")
            # só aprende com quem tem contexto; digitado/clique não tem
            self.aprendizado.registrar(
                dominio_da_casa(self.fila[self.indice]), c, self.candidatos, origem)

        item = dict(self.item_pendente)
        item.pop("origem_clique", None)
        # a caixinha só vale se corresponder ao valor que está sendo gravado
        # agora — confere sem mexer no que você marcou ou desmarcou
        if self.mov_var.get() and getattr(self, "_mov_tipo", None):
            if self._movimento_confere(valor):
                item["movimento"] = {"tipo": self._mov_tipo, "valor": self._mov_valor}
        item.update({
            "saldo": valor,
            "score": score,
            "confianca": "confirmado" if origem == "scanner" else "corrigido",
            "origem": origem,
            "contexto": contexto,
            "confirmado_manualmente": True,
            "corrigido": origem != "scanner",
        })
        self._registrar(item)

    def on_pular(self):
        if self.travado:
            return
        casa = self.fila[self.indice]
        base = dict(self.item_pendente) if self.item_pendente else dict(identidade_da_casa(casa))
        base.setdefault("perfil", self.perfil_atual.get("nome"))
        base.setdefault("porta", self.perfil_atual.get("porta"))
        base.pop("origem_clique", None)
        base.update({"saldo": None, "confianca": "pulado", "origem": "pulado",
                     "detalhe": "usuário pulou esta casa"})
        self._registrar(base)

    def on_limitada(self):
        """
        Você caiu numa casa que já limitou (stake mínimo, saque travado)?
        Marca aqui e segue lendo o saldo normalmente — o painel passa a
        contar essa casa fora da capacidade real de operação.
        """
        if self.travado:
            return
        from datetime import date

        casa = self.fila[self.indice]
        casa_id = casa.get("casa_id")
        if not casa_id:
            self._status("Sem painel, não dá para marcar a limitação.", WARN_W)
            return
        hoje = date.today().isoformat()
        if casa_id in self.marcadas_limitada:
            del self.marcadas_limitada[casa_id]
            if self.dados_nuvem is not None:
                for h in self.dados_nuvem.get("houses") or []:
                    if h.get("id") == casa_id:
                        h["limitada"] = False
            self.btn_limitada.config(text="🔒 Marcar como limitada", fg=WARN_W)
            self._status("Desmarcada.", MUTED_W)
            return

        self.marcadas_limitada[casa_id] = hoje
        if self.dados_nuvem is not None:
            for h in self.dados_nuvem.get("houses") or []:
                if h.get("id") == casa_id:
                    h["limitada"] = True
                    h["limitadaEm"] = h.get("limitadaEm") or hoje
        self.btn_limitada.config(text="🔒 limitada ✓ (clique p/ desfazer)", fg=OK_W)
        self._status(f"{rotulo_da_casa(casa)} marcada como limitada. "
                     "Continue e leia o saldo normalmente.", OK_W)

    def on_manteve_igual(self):
        """
        Casa que você não usou na semana: confirma o saldo anterior sem abrir,
        sem logar, sem ler a tela. A data de verificação é atualizada, então
        ela sai da lista de "sem verificar há X dias".
        """
        if self.travado:
            return
        casa = self.fila[self.indice]
        anterior = casa.get("saldo_anterior")
        if anterior is None:
            self._status("Sem saldo anterior no painel — leia a tela desta vez.",
                         WARN_W)
            return
        item = dict(identidade_da_casa(casa))
        item.update({
            "perfil": self.perfil_atual.get("nome"),
            "porta": self.perfil_atual.get("porta"),
            "saldo": normalizar_valor(anterior),
            "confianca": "mantido",
            "origem": "inalterado",
            "score": None,
            "confirmado_manualmente": True,
            "detalhe": "você confirmou que o saldo não mudou",
        })
        self._registrar(item)

    def on_precisa_login(self):
        """Sessão caiu: anota como pendência e segue, sem travar a varredura."""
        if self.travado:
            return
        casa = self.fila[self.indice]
        base = dict(self.item_pendente) if self.item_pendente else dict(identidade_da_casa(casa))
        base.setdefault("perfil", self.perfil_atual.get("nome"))
        base.setdefault("porta", self.perfil_atual.get("porta"))
        base.pop("origem_clique", None)
        base.update({"saldo": None, "confianca": "precisa login",
                     "precisa_login": True, "origem": "login",
                     "detalhe": "sessão expirada — logar e verificar depois"})
        self._registrar(base)

    def on_nunca(self):
        """
        Marca a casa como 'não verificar' direto no painel. É assim que as
        contas que existem só por registro somem da varredura de vez, sem
        você precisar abrir o painel e editar uma por uma.
        """
        if self.travado:
            return
        casa = self.fila[self.indice]
        casa_id = casa.get("casa_id")
        marcou = False
        if casa_id:
            self.marcadas_nunca.add(casa_id)
        if self.dados_nuvem is not None and casa_id:
            for h in self.dados_nuvem.get("houses") or []:
                if h.get("id") == casa_id:
                    h["verificarSaldo"] = False
                    marcou = True
                    break
        base = dict(identidade_da_casa(casa))
        base.update({
            "perfil": self.perfil_atual.get("nome"),
            "porta": self.perfil_atual.get("porta"),
            "saldo": None,
            "confianca": "nao verificar",
            "origem": "nunca",
            "detalhe": ("marcada como 'não verificar' — vai junto no envio"
                        if marcou else
                        "marcada aqui, mas sem painel para gravar"),
        })
        self._registrar(base)

    def _registrar(self, item):
        from datetime import datetime

        self._farejando = False

        item["lido_em"] = datetime.now().isoformat(timespec="seconds")
        self.resultados.append(item)
        self.salvo = False
        self.enviado = False
        self.item_pendente = None
        rotulo = item.get("nome_casa") or item.get("dominio")
        self._status(f"{rotulo}: {item.get('saldo') or item.get('confianca')}",
                     OK_W if item.get("saldo") else WARN_W)
        self.progresso.salvar(self.perfil_atual, self.fila,
                              self.indice + 1, self.resultados)
        self._agendar(400, self._proxima_casa)

    def on_voltar(self):
        """Refaz a casa anterior — inclusive para trocar um saldo já gravado."""
        if self.travado or self.indice <= 0:
            return
        anterior = self.fila[self.indice - 1]
        chave = anterior.get("casa_id") or dominio_da_casa(anterior)
        for i in range(len(self.resultados) - 1, -1, -1):
            atual = self.resultados[i]
            if (atual.get("casa_id") or atual.get("dominio")) == chave:
                self.resultados.pop(i)
                break
        self.item_pendente = None
        self.indice -= 2
        self._status(f"Voltando para {rotulo_da_casa(anterior)}.", MUTED_W)
        self._proxima_casa()

    # ---------- 4. final ----------
    def _finalizar(self):
        if self.picker_ativo:
            self._parar_picker()
        self._ir_para_estado("final")
        self._preencher_lista_final()
        self.btn_enviar.config(
            state="normal" if self.dados_nuvem is not None else "disabled",
            text=("☁ Enviar saldos para o painel" if self.dados_nuvem is not None
                  else "☁ Painel indisponível (só arquivo)"))
        self.on_salvar(silencioso=True)
        if self.dados_nuvem is None:
            self.progresso.limpar()   # sem painel, terminou aqui mesmo
        self._status("Corrija o que precisar e envie para o painel.", MUTED_W)

    def _preencher_lista_final(self):
        self.lst_final.delete(0, "end")
        for r in self.resultados:
            rotulo = (r.get("nome_casa") or r.get("dominio") or "")[:20]
            saldo = r.get("saldo") or f"— {r.get('confianca', '')}"
            marca = "✎" if r.get("corrigido") else " "
            self.lst_final.insert("end", f"{marca} {rotulo:<20} {saldo}")

    def _on_selecionou_final(self, _event=None):
        sel = self.lst_final.curselection()
        if not sel:
            return
        r = self.resultados[sel[0]]
        self.ent_final.delete(0, "end")
        if r.get("saldo"):
            self.ent_final.insert(0, r["saldo"])
        antes = r.get("saldo_anterior")
        extra = f" · antes {_fmt_brl(antes)}" if antes is not None else ""
        self._status(f"{r.get('nome_casa') or r.get('dominio')} · "
                     f"origem: {r.get('origem', '?')}{extra}", MUTED_W)

    def on_corrigir_final(self):
        sel = self.lst_final.curselection()
        if not sel:
            self._status("Selecione uma linha da lista primeiro.", WARN_W)
            return
        texto = self.ent_final.get().strip()
        item = self.resultados[sel[0]]
        if not texto:
            item.update({"saldo": None, "confianca": "pulado", "origem": "limpo",
                         "corrigido": True})
        else:
            valor = normalizar_valor(texto)
            if not valor:
                self._status("Não entendi esse valor. Ex.: 1234,56", ERR_W)
                return
            item.update({"saldo": valor, "confianca": "corrigido",
                         "origem": "digitado", "corrigido": True, "score": None})
        self.salvo = False
        self.enviado = False
        self._preencher_lista_final()
        self.lst_final.selection_set(sel[0])
        self._status(f"{item.get('nome_casa') or item.get('dominio')} atualizado.", OK_W)

    def on_salvar(self, silencioso=False):
        try:
            json_path, csv_path = salvar_resultados(self.pasta, self.resultados)
            self.salvo = True
            if not silencioso:
                self._status(f"Salvo em {json_path.name} e {csv_path.name}.", OK_W)
        except Exception as e:
            if not silencioso:
                self._status(f"Não consegui salvar: {e}", ERR_W)

    def on_enviar(self):
        if self.dados_nuvem is None or nuvem is None:
            self._status("Painel indisponível — os saldos ficaram no saldos.json.", WARN_W)
            return
        self.btn_enviar.config(state="disabled")
        self._status("Enviando para o painel...", MUTED_W)
        threading.Thread(target=self._enviar_thread, daemon=True).start()

    def _enviar_thread(self):
        try:
            # Baixa o estado de novo antes de gravar. A varredura leva meia
            # hora; se você (ou a skill do Claude) mexeu no painel nesse meio
            # tempo, mandar a cópia velha apagaria essas mudanças — o PATCH
            # substitui o JSON inteiro.
            try:
                user_id, atual = nuvem.baixar_estado(self.cfg_nuvem)
                self.dados_nuvem = atual
                self.user_id_nuvem = user_id or self.user_id_nuvem
                for casa in atual.get("houses") or []:
                    if casa.get("id") in self.marcadas_nunca:
                        casa["verificarSaldo"] = False
                    if casa.get("id") in self.marcadas_limitada:
                        casa["limitada"] = True
                        casa["limitadaEm"] = (casa.get("limitadaEm")
                                              or self.marcadas_limitada[casa["id"]])
            except Exception:
                pass    # sem rede agora? segue com o que temos em mãos
            movs = nuvem.registrar_movimentos(self.dados_nuvem, self.resultados)
            mudancas = nuvem.aplicar_resultados(self.dados_nuvem, self.resultados)
            nuvem.enviar_estado(self.cfg_nuvem, self.user_id_nuvem, self.dados_nuvem)
        except Exception as e:
            msg = f"Falhou o envio: {e}"
            self.after(0, lambda: self._status(msg, ERR_W))
            self.after(0, lambda: self.btn_enviar.config(state="normal"))
            return
        total = sum(m["diferenca"] for m in mudancas)
        sinal = "+" if total >= 0 else "−"
        self.enviado = True
        self.progresso.limpar()
        self.on_salvar(silencioso=True)
        extra = f" · {len(movs)} movimentação(ões) lançada(s)" if movs else ""
        self.after(0, lambda: self._status(
            f"Painel atualizado: {len(mudancas)} casa(s), "
            f"variação {sinal}{_fmt_brl(abs(total))}{extra}.", OK_W))
        self.after(0, lambda: self.btn_enviar.config(
            state="normal", text="☁ Enviar de novo"))

    def on_outro_perfil(self):
        if not self.salvo:
            self.on_salvar(silencioso=True)
        if self.resultados and not self.enviado and self.dados_nuvem is not None:
            self._status("Atenção: você ainda não enviou esses saldos para o painel.",
                         WARN_W)
            self.enviado = True   # segundo clique segue em frente
            return
        if self.scanner:
            self.scanner.fechar()
            self.scanner = None
        self.resultados = []
        self.indice = -1
        self._ir_para_estado("inicio")
        self.btn_iniciar.config(state="normal", text="▶ Conectar e listar casas")
        self.btn_retomar.config(state="normal")
        self._status("", MUTED_W)
        self._atualizar_retomar()

    def sair(self):
        self._farejando = False      # senão a thread segue chamando widget morto
        for ident in self._agendados:
            try:
                self.after_cancel(ident)
            except Exception:
                pass
        self._agendados.clear()
        if self.resultados and not self.salvo:
            self.on_salvar(silencioso=True)
        if self.picker_ativo:
            self._parar_picker()
        if self.scanner:
            self.scanner.fechar()
        self.destroy()


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    PASTA = Path(__file__).resolve().parent

    parser = argparse.ArgumentParser(
        description=(
            "Lê os saldos das casas no perfil correto do Opera. "
            "Sem informar nomes, processa todos os perfis do profiles.json."
        )
    )
    parser.add_argument(
        "perfis",
        nargs="*",
        help="Perfis a processar (nomes do profiles.json), ou --todos",
    )
    parser.add_argument(
        "--todos",
        action="store_true",
        help="Processa todos os perfis (já é o padrão quando nenhum nome é informado)",
    )
    parser.add_argument(
        "--listar",
        action="store_true",
        help="Mostra os perfis e a quantidade de casas, sem ler saldos",
    )
    parser.add_argument(
        "--profiles",
        dest="profiles_file",
        help="Caminho alternativo para o profiles.json",
    )
    parser.add_argument(
        "--pausa",
        type=float,
        default=1.0,
        help="Pausa em segundos entre casas (padrão: 1.0)",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help=(
            "Abre a janelinha flutuante (estilo TeamViewer) no canto da "
            "tela: você escolhe o perfil, confirma casa por casa quando o "
            "saldo aparecer e revisa cada valor antes de gravar — podendo "
            "escolher outro valor da página, digitar na mão ou clicar no "
            "saldo certo dentro do navegador."
        ),
    )
    parser.add_argument(
        "--incluir-zeradas",
        action="store_true",
        help="No modo linha de comando, também varre as casas zeradas do painel",
    )
    parser.add_argument(
        "--incluir-novas",
        action="store_true",
        help="No modo linha de comando, também varre as casas novas do painel",
    )
    parser.add_argument(
        "--enviar",
        action="store_true",
        help="Ao terminar, grava os saldos lidos de volta no painel (Supabase)",
    )
    args = parser.parse_args()

    try:
        arquivo_perfis = localizar_arquivo_perfis(PASTA, args.profiles_file)
        with open(arquivo_perfis, encoding="utf-8") as arquivo:
            perfis = json.load(arquivo)
        if not isinstance(perfis, list):
            raise ValueError("O arquivo de perfis deve conter uma lista JSON.")
    except Exception as e:
        print(f"Erro lendo perfis: {e}")
        raise SystemExit(1)

    if args.gui:
        try:
            selecionados_gui = selecionar_perfis(perfis, [] if args.todos else args.perfis)
        except ValueError as e:
            print(e)
            raise SystemExit(1)
        if websocket is None:
            print("Dependência ausente: pip install websocket-client")
            raise SystemExit(1)
        JanelaFlutuante(selecionados_gui, PASTA).mainloop()
        raise SystemExit(0)

    if args.listar:
        print(f"Arquivo: {arquivo_perfis}")
        for perfil in perfis:
            print(
                f"  {perfil.get('nome', '?'):<10} "
                f"{perfil.get('porta', 'sem porta'):<12} "
                f"{len(perfil.get('casas') or [])} casas"
            )
        raise SystemExit(0)

    try:
        alvos = [] if args.todos else args.perfis
        selecionados = selecionar_perfis(perfis, alvos)
    except ValueError as e:
        print(e)
        raise SystemExit(1)

    if websocket is None:
        print("Dependência ausente: pip install websocket-client")
        raise SystemExit(1)

    total_casas = sum(len(p.get("casas") or []) for p in selecionados)
    print(f"Arquivo de perfis: {arquivo_perfis.name}")
    print("Perfis selecionados: " + ", ".join(p.get("nome", "?") for p in selecionados))
    print(f"Total cadastrado: {total_casas} casas em {len(selecionados)} perfil(is).")
    print("Perfis fechados serão ignorados e os demais continuarão normalmente.\n")

    inicio_total = time.time()
    todos_resultados = []
    nao_processados = []
    processados = []

    tipos_aceitos = {"ativa"}
    if args.incluir_zeradas:
        tipos_aceitos.add("zerada")
    if args.incluir_novas:
        tipos_aceitos.add("nova")

    contexto_nuvem = None

    for indice, perfil in enumerate(selecionados, 1):
        nome = perfil.get("nome", f"Perfil {indice}")
        todas, contexto, aviso = carregar_casas_do_perfil(PASTA, perfil)
        if contexto:
            contexto_nuvem = contexto
        if aviso:
            print(f"     [{nome}] {aviso}")
        casas = [c for c in todas if (c.get("tipo") or "ativa") in tipos_aceitos]
        fora = len(todas) - len(casas)
        if fora:
            print(f"     [{nome}] {fora} casa(s) fora da varredura "
                  f"(zeradas/novas/marcadas para não verificar)")

        if not casas:
            motivo = "nenhuma casa a verificar"
            nao_processados.append({"perfil": nome, "motivo": motivo})
            print(f"[{indice}/{len(selecionados)}] {nome}: {motivo}; seguindo.")
            continue

        porta, erro = obter_debug_port(perfil)
        if erro:
            nao_processados.append({"perfil": nome, "motivo": erro})
            print(f"[{indice}/{len(selecionados)}] {nome}: {erro}; seguindo.")
            continue

        print("=" * 72)
        print(
            f"[{indice}/{len(selecionados)}] Perfil {nome} · "
            f"porta {porta} · {len(casas)} casas"
        )
        inicio_perfil = time.time()

        try:
            resultados = ler_perfil(
                porta,
                perfil,
                log=lambda mensagem, n=nome: print(f"     [{n}] {mensagem}"),
                pausa=max(0.0, args.pausa),
            )
        except Exception as e:
            motivo = f"erro geral no perfil: {e}"
            nao_processados.append({"perfil": nome, "motivo": motivo})
            print(f"{nome}: {motivo}; seguindo para o próximo.")
            continue

        todos_resultados.extend(resultados)
        processados.append((perfil, resultados, time.time() - inicio_perfil))

    totais = {"lidos": 0, "login": 0, "falhou": 0}
    for perfil, resultados, duracao in processados:
        a, b, c = imprimir_bloco_resultados(perfil.get("nome", "?"), resultados)
        totais["lidos"] += a
        totais["login"] += b
        totais["falhou"] += c
        print(f"tempo do perfil: {duracao:.0f}s")

    print("\n" + "=" * 72)
    print("RESUMO GERAL")
    print(f"  perfis processados: {len(processados)}/{len(selecionados)}")
    print(f"  saldos lidos:       {totais['lidos']}")
    print(f"  precisam de login:  {totais['login']}")
    print(f"  não consegui ler:   {totais['falhou']}")

    if nao_processados:
        print(f"\nPERFIS NÃO PROCESSADOS ({len(nao_processados)}):")
        for item in nao_processados:
            print(f"  {item['perfil']:<12} {item['motivo']}")

    json_path, csv_path = salvar_resultados(PASTA, todos_resultados)
    print(f"\ntempo total: {time.time() - inicio_total:.0f}s")
    print(f"gerados: {json_path.name} e {csv_path.name}")

    if args.enviar:
        if not contexto_nuvem or nuvem is None:
            print("\n--enviar pedido, mas o painel não respondeu: nada foi enviado.")
        else:
            try:
                mudancas = nuvem.aplicar_resultados(contexto_nuvem["dados"], todos_resultados)
                nuvem.enviar_estado(contexto_nuvem["cfg"], contexto_nuvem["user_id"],
                                    contexto_nuvem["dados"])
                total = sum(m["diferenca"] for m in mudancas)
                print(f"\npainel atualizado: {len(mudancas)} casa(s), "
                      f"variação total R$ {total:,.2f}")
                for m in mudancas:
                    print(f"  {m['nome']:<22} {m['antes']:>10,.2f} -> {m['depois']:>10,.2f}")
            except Exception as e:
                print(f"\nfalhou o envio para o painel: {e}")