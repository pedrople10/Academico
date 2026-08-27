"""
Abridor multi-perfil — Opera

Fluxo:
  1. CONECTAR (uma vez). Abre (ou detecta, se já estiver aberto) cada perfil
     do Opera com sua própria pasta de dados e sua própria porta de depuração.
  2. Cole o link -> o perfil dono da casa fica destacado -> ABRIR.
     A partir daqui é instantâneo (vai direto no Opera, sem reabrir nada).
  3. PING mede a latência real do proxy de cada perfil (se você configurou um
     `proxy` naquele perfil; sem proxy, mede a sua própria conexão).
  4. FECHAR ABAS ANTIGAS deixa só a aba mais recente de cada perfil.

Cada perfil é um Opera isolado (cookies e login próprios), não um antidetect
de verdade — veja o aviso em opera_perfis.py e no README antes de usar isso
em várias casas de apostas.

Atalhos:
  Ctrl+V  na janela   -> cola e já destaca
  Enter               -> abre nos marcados
  Ctrl+Shift+A        -> atalho global (precisa de: pip install keyboard)

Uso:
    pip install websocket-client
    python app.py
"""

import json
import threading
import time
import tkinter as tk
from pathlib import Path
from urllib.parse import quote, urlparse
import urllib.request
import urllib.error

try:
    import nuvem            # ponte com o painel (Supabase) — opcional
except ImportError:
    nuvem = None

from opera_perfis import abrir_perfil

try:
    import aprendiz         # aprende onde ficam stake e botão — opcional
except ImportError:
    aprendiz = None

try:
    import websocket  # websocket-client (opcional, usado no PING)
except ImportError:
    websocket = None

try:
    import keyboard   # opcional, usado no atalho global
except ImportError:
    keyboard = None

try:
    import pystray                      # opcional, ícone na bandeja
    from PIL import Image, ImageDraw
except ImportError:
    pystray = None

PROFILES_FILE = Path(__file__).parent / "profiles.json"
HIST_FILE = Path(__file__).parent / "historico.json"
TIMEOUT = 8
RATE_LIMIT_S = 1.1        # espaçamento ao abrir vários Operas de uma vez (só no CONECTAR)
PING_URL = "https://geo.brdtest.com/mygeo.json"
MAX_HIST = 12
# Ping automático DESLIGADO por padrão. Cada medição precisa abrir uma aba
# dentro do perfil (é o único jeito de sair pelo proxy dele), e com 6 perfis
# a cada 5 min isso viravam ~1700 aberturas de aba por dia: piscava a tela,
# criava um processo renderer por vez e ainda consumia franquia do proxy
# residencial. Ligue pelo botão da interface quando quiser vigiar os proxies.
PING_AUTO_MIN = 15         # intervalo quando você LIGA o ping automático
PING_AUTO_PADRAO = False   # começa ligado?
PING_ALERTA_MS = 1200      # acima disso, alerta

# paleta
BG       = "#15171c"
CARD     = "#1e2129"
CARD_HI  = "#272b36"
FG       = "#e8eaed"
MUTED    = "#8b91a1"
ACCENT   = "#2f80ed"
OK       = "#27ae60"
WARN     = "#f2994a"
ERR      = "#eb5757"
MATCH_BG = "#1f3d2b"
MATCH_BD = "#27ae60"


# ---------------------------------------------------------------- helpers
def dominio(url):
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url
    h = urlparse(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def fmt_brl(valor):
    return f"R$ {float(valor):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def saldo_da_casa(profile, dom):
    """
    Quanto tem nessa casa, nesse perfil, segundo a última varredura.

    O saldos.py grava `casas_painel` no profiles.json toda vez que fala com
    o painel. Aqui só lemos — na hora de decidir onde apostar, saber o saldo
    evita abrir o painel em paralelo.
    """
    if not dom:
        return None
    for casa in profile.get("casas_painel") or []:
        alvo = (casa.get("dominio") or "").lower()
        if not alvo:
            continue
        if dom == alvo or dom.endswith("." + alvo) or alvo.endswith("." + dom):
            return casa
    return None


def casa_limitada(profile, dom):
    """Essa casa, nesse perfil, está marcada como limitada no painel?"""
    casa = saldo_da_casa(profile, dom)
    return bool(casa and casa.get("limitada"))


def casa_bate(dom, casas):
    if not dom:
        return False
    for c in casas:
        c = c.lower()
        if dom == c or dom.endswith("." + c) or c.endswith("." + dom):
            return True
    return False


def load_profiles():
    with open(PROFILES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_hist():
    try:
        return json.load(open(HIST_FILE, encoding="utf-8"))
    except Exception:
        return []


def save_hist(lista):
    try:
        json.dump(lista[:MAX_HIST], open(HIST_FILE, "w", encoding="utf-8"),
                  indent=2, ensure_ascii=False)
    except Exception:
        pass


def cdp(port, path, method="GET"):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", "replace")


def open_tab(port, url):
    path = f"/json/new?{quote(url, safe='')}"
    try:
        return json.loads(cdp(port, path, "PUT"))
    except urllib.error.HTTPError as e:
        if e.code in (405, 501):
            return json.loads(cdp(port, path, "GET"))
        raise


def close_old_tabs(port):
    tabs = json.loads(cdp(port, "/json/list"))
    pages = [t for t in tabs if t.get("type") == "page"]
    if len(pages) <= 1:
        return 0
    manter = pages[0]["id"]
    n = 0
    for t in pages:
        if t["id"] != manter:
            try:
                cdp(port, f"/json/close/{t['id']}")
                n += 1
            except Exception:
                pass
    return n


def paginas(port):
    try:
        return [t for t in json.loads(cdp(port, "/json/list"))
                if t.get("type") == "page"]
    except Exception:
        return []


def limpar_abas_orfas(port):
    """
    Fecha about:blank sobrando. Quando o fechamento da aba de ping falha
    (perfil reiniciado, porta trocada), ela ficava lá para sempre — e cada
    uma é um processo renderer parado comendo memória.
    """
    n = 0
    for t in paginas(port):
        url = (t.get("url") or "").strip()
        if url in ("about:blank", "") and not (t.get("title") or "").strip():
            try:
                cdp(port, f"/json/close/{t['id']}")
                n += 1
            except Exception:
                pass
    return n


def _js_na_aba(port, tab, expressao, espera=8):
    """Roda um JS numa aba já aberta e devolve o resultado."""
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url or websocket is None:
        return None
    ws = websocket.create_connection(ws_url, timeout=espera, suppress_origin=True)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                            "params": {"expression": expressao,
                                       "returnByValue": True}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                return (msg.get("result", {}).get("result", {}) or {}).get("value")
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _trazer_para_frente(port, tab_id):
    """Devolve o foco para a aba onde a pessoa estava."""
    if not tab_id:
        return
    try:
        alvo = next((t for t in paginas(port) if t["id"] == tab_id), None)
        if not alvo or not alvo.get("webSocketDebuggerUrl") or websocket is None:
            return
        ws = websocket.create_connection(alvo["webSocketDebuggerUrl"],
                                         timeout=TIMEOUT, suppress_origin=True)
        try:
            ws.send(json.dumps({"id": 99, "method": "Page.bringToFront"}))
            ws.recv()
        finally:
            ws.close()
    except Exception:
        pass


def ping_proxy(port):
    """
    Mede a latência REAL do proxy daquele perfil: abre uma aba, faz um fetch
    de dentro dela (ou seja, saindo pelo proxy do perfil) e cronometra.

    A aba precisa existir de verdade, mas o foco volta na hora para a aba em
    que você estava — antes disso, a cada 5 minutos a tela pulava sozinha.
    """
    if websocket is None:
        raise RuntimeError("pip install websocket-client")

    limpar_abas_orfas(port)
    antes = paginas(port)
    voltar_para = antes[0]["id"] if antes else None

    alvo = open_tab(port, "about:blank")
    ws_url = alvo.get("webSocketDebuggerUrl")
    tab_id = alvo.get("id")
    _trazer_para_frente(port, voltar_para)
    try:
        ws = websocket.create_connection(
            ws_url, timeout=TIMEOUT,
            suppress_origin=True,   # Chrome recusa (403) se vier header Origin
        )
        expr = (
            "(async()=>{const t=performance.now();"
            f"await fetch('{PING_URL}',{{mode:'no-cors',cache:'no-store'}});"
            "return Math.round(performance.now()-t);})()"
        )
        ws.send(json.dumps({
            "id": 1, "method": "Runtime.evaluate",
            "params": {"expression": expr, "awaitPromise": True,
                       "returnByValue": True},
        }))
        deadline = time.time() + TIMEOUT
        while time.time() < deadline:
            msg = json.loads(ws.recv())
            if msg.get("id") == 1:
                res = msg.get("result", {}).get("result", {})
                if "value" in res:
                    return int(res["value"])
                raise RuntimeError("sem resposta do fetch")
        raise RuntimeError("timeout")
    finally:
        try:
            ws.close()
        except Exception:
            pass
        # duas tentativas: se a primeira falhar, a aba fica órfã para sempre
        for _ in range(2):
            try:
                cdp(port, f"/json/close/{tab_id}")
                break
            except Exception:
                time.sleep(0.3)
        _trazer_para_frente(port, voltar_para)


# ---------------------------------------------------------------- widgets
class Row(tk.Frame):
    def __init__(self, master, profile, **kw):
        super().__init__(master, bg=CARD, **kw)
        self.profile = profile
        self.casas = profile.get("casas", [])
        self.marcado = tk.BooleanVar(value=True)
        self.port = None

        self.box = tk.Label(self, text="✓", font=("Segoe UI", 15, "bold"),
                            width=3, bg=ACCENT, fg="white", cursor="hand2")
        self.box.pack(side="left", fill="y")

        mid = tk.Frame(self, bg=CARD)
        mid.pack(side="left", fill="both", expand=True, padx=14, pady=10)
        self.lbl_nome = tk.Label(mid, text=profile["nome"],
                                 font=("Segoe UI", 13, "bold"),
                                 bg=CARD, fg=FG, anchor="w")
        self.lbl_nome.pack(fill="x")
        self.badge = tk.Label(mid, text="", font=("Segoe UI", 9, "bold"),
                              bg=CARD, fg=MATCH_BD, anchor="w")
        self.lbl_status = tk.Label(mid, text="não conectado",
                                   font=("Segoe UI", 10),
                                   bg=CARD, fg=MUTED, anchor="w")
        self.lbl_status.pack(fill="x")

        self.lbl_ping = tk.Label(self, text="", font=("Consolas", 12, "bold"),
                                 bg=CARD, fg=MUTED, width=9)
        self.lbl_ping.pack(side="right", padx=(0, 12))

        # só aparece quando a linha está destacada por um link colado
        self.btn_limitar = tk.Button(self, text="🔒", font=("Segoe UI", 12),
                                     bg=CARD_HI, fg=WARN, relief="flat",
                                     cursor="hand2", width=3,
                                     command=self.on_limitar)
        self.casa_atual = None

        self._clicaveis = (self, mid, self.lbl_nome, self.lbl_status,
                           self.box, self.badge, self.lbl_ping)
        for w in self._clicaveis:
            w.bind("<Button-1>", self.toggle)

    def on_limitar(self):
        """
        Marca (ou desmarca) no painel que ESTA casa, NESTE perfil, está
        limitada. Grava direto no Supabase e atualiza o profiles.json local —
        o app recarrega sozinho em seguida.
        """
        casa = self.casa_atual
        if not casa or not casa.get("casa_id") or nuvem is None:
            return
        virar = not casa.get("limitada")
        self.btn_limitar.config(state="disabled")
        self.lbl_status.config(text="gravando no painel...", fg=MUTED)
        threading.Thread(target=self._gravar_limitacao,
                         args=(casa, virar), daemon=True).start()

    def _gravar_limitacao(self, casa, limitada):
        from datetime import date

        erro = None
        try:
            cfg = nuvem.carregar_config(PROFILES_FILE.parent)
            user_id, dados = nuvem.baixar_estado(cfg)
            achou = False
            for h in dados.get("houses") or []:
                if h.get("id") == casa["casa_id"]:
                    h["limitada"] = limitada
                    if limitada and not h.get("limitadaEm"):
                        h["limitadaEm"] = date.today().isoformat()
                    achou = True
                    break
            if not achou:
                raise RuntimeError("essa casa não existe mais no painel")
            nuvem.enviar_estado(cfg, user_id, dados)
            try:
                nuvem.atualizar_profiles_json(PROFILES_FILE.parent, dados,
                                              arquivo=PROFILES_FILE)
            except Exception:
                pass
            casa["limitada"] = limitada
        except Exception as e:
            erro = str(e)[:120]

        def concluir():
            self.btn_limitar.config(state="normal")
            if erro:
                self.lbl_status.config(text=f"falhou: {erro}", fg=ERR)
                return
            self.btn_limitar.config(text="🔓" if limitada else "🔒",
                                    fg=OK if limitada else WARN)
            nome = casa.get("nome") or "casa"
            self.lbl_status.config(
                text=f"{nome}: {'marcada como limitada' if limitada else 'limitação removida'}",
                fg=OK if limitada else MUTED)
        self.after(0, concluir)

    def toggle(self, _=None):
        self.marcar(not self.marcado.get())

    def marcar(self, valor):
        self.marcado.set(bool(valor))
        self.box.config(text="✓" if valor else "",
                        bg=ACCENT if valor else "#3a3f4b")

    def _pintar(self, cor):
        self.config(bg=cor)
        for w in self.winfo_children():
            if isinstance(w, tk.Frame):
                w.config(bg=cor)
                for c in w.winfo_children():
                    c.config(bg=cor)
            elif w not in (self.box, self.btn_limitar):
                w.config(bg=cor)

    def destacar(self, ativo, nome_casa=""):
        """
        `ativo` = este perfil tem a casa do link colado.

        Casa limitada continua mostrando o aviso (você precisa saber que ela
        existe ali), mas não fica verde nem entra na seleção — não adianta
        abrir uma casa que só aceita R$ 15 de stake.
        """
        self.casa_atual = saldo_da_casa(self.profile, nome_casa) if ativo else None
        limitada = bool(self.casa_atual and self.casa_atual.get("limitada"))
        realcar = ativo and not limitada

        cor = MATCH_BG if realcar else CARD
        self._pintar(cor)
        self.config(highlightthickness=2 if realcar else 0,
                    highlightbackground=MATCH_BD, highlightcolor=MATCH_BD)
        if ativo and self.casa_atual and self.casa_atual.get("casa_id") and nuvem is not None:
            self.btn_limitar.config(
                text="🔓" if self.casa_atual.get("limitada") else "🔒",
                fg=OK if self.casa_atual.get("limitada") else WARN)
            self.btn_limitar.pack(side="right", padx=(0, 6))
        else:
            self.btn_limitar.pack_forget()
        if ativo:
            casa = self.casa_atual
            if casa:
                saldo = float(casa.get("saldo_anterior") or 0)
                quando = (casa.get("verificado_em") or casa.get("verificadoEm") or "")
                extra = f" · {fmt_brl(saldo)}" + (f" em {quando[5:]}" if quando else "")
                if casa.get("limitada"):
                    stake = float(casa.get("stake_max") or casa.get("stakeMax") or 0)
                    extra += "  🔒 limitada" + (f" (até {fmt_brl(stake)})" if stake else "")
                self.badge.config(
                    text=f"★  {casa.get('nome') or nome_casa}{extra}",
                    fg=WARN if casa.get("limitada") else (OK if saldo > 0.005 else MUTED),
                    bg=cor)
            else:
                self.badge.config(text=f"★  perfil desta casa · {nome_casa}",
                                  fg=MATCH_BD, bg=cor)
            self.badge.pack(fill="x", before=self.lbl_status)
        else:
            self.badge.pack_forget()

    def status(self, texto, cor=MUTED):
        self.lbl_status.config(text=texto, fg=cor)
        self.update_idletasks()

    def ping(self, texto, cor=MUTED):
        self.lbl_ping.config(text=texto, fg=cor)
        self.update_idletasks()


# ---------------------------------------------------------------- app
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Abridor multi-perfil — Opera")
        self.geometry("760x720")
        self.configure(bg=BG)
        self.minsize(680, 560)

        # link
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=18, pady=(18, 0))
        tk.Label(top, text="LINK", font=("Segoe UI", 9, "bold"),
                 bg=BG, fg=MUTED).pack(anchor="w")
        self.url_entry = tk.Entry(top, font=("Consolas", 13), bg=CARD, fg=FG,
                                  insertbackground=FG, relief="flat",
                                  highlightthickness=2, highlightbackground=CARD_HI,
                                  highlightcolor=ACCENT)
        self.url_entry.pack(fill="x", ipady=10, pady=(4, 0))
        self.url_entry.bind("<Return>", lambda e: self.on_abrir())
        self.url_entry.bind("<KeyRelease>", lambda e: self.atualizar_destaque())
        self.url_entry.bind("<<Paste>>", lambda e: self.after(30, self.atualizar_destaque))

        acoes = tk.Frame(top, bg=BG)
        acoes.pack(fill="x", pady=(6, 0))
        for txt, cmd in (("Colar", self.colar),
                         ("Limpar", lambda: (self.url_entry.delete(0, "end"),
                                             self.atualizar_destaque()))):
            tk.Button(acoes, text=txt, command=cmd, font=("Segoe UI", 10),
                      bg=CARD_HI, fg=FG, relief="flat", cursor="hand2",
                      padx=14, pady=4).pack(side="left", padx=(0, 6))

        # histórico
        self.hist = load_hist()
        self.hist_var = tk.StringVar(value="histórico ▾")
        self.btn_hist = tk.Menubutton(acoes, textvariable=self.hist_var,
                                      font=("Segoe UI", 10), bg=CARD_HI, fg=FG,
                                      relief="flat", cursor="hand2", padx=14, pady=4)
        self.menu_hist = tk.Menu(self.btn_hist, tearoff=0, bg=CARD, fg=FG,
                                 activebackground=ACCENT, activeforeground="white")
        self.btn_hist.config(menu=self.menu_hist)
        self.btn_hist.pack(side="left")
        self.render_hist()

        # botão principal
        self.btn_abrir = tk.Button(self, text="ABRIR NOS PERFIS MARCADOS",
                                   font=("Segoe UI", 15, "bold"), bg=ACCENT,
                                   fg="white", relief="flat", cursor="hand2",
                                   command=self.on_abrir, activebackground="#1c6fd6",
                                   activeforeground="white")
        self.btn_abrir.pack(fill="x", padx=18, pady=(14, 0), ipady=16)

        # secundários
        sec = tk.Frame(self, bg=BG)
        sec.pack(fill="x", padx=18, pady=(10, 0))
        self.btn_conectar = tk.Button(sec, text="🔌  CONECTAR", command=self.on_conectar,
                                      font=("Segoe UI", 11, "bold"), bg=CARD_HI,
                                      fg=FG, relief="flat", cursor="hand2")
        self.btn_conectar.pack(side="left", fill="x", expand=True, ipady=10)
        self.auto_ping = tk.BooleanVar(value=PING_AUTO_PADRAO)
        self.btn_ping = tk.Button(sec, text="📶  PING", command=self.on_ping,
                                  font=("Segoe UI", 11, "bold"), bg=CARD_HI,
                                  fg=FG, relief="flat", cursor="hand2")
        self.btn_ping.pack(side="left", fill="x", expand=True, ipady=10, padx=(10, 0))
        self.btn_recarregar = tk.Button(sec, text="🔄  PERFIS",
                                        command=self.on_sincronizar_perfis,
                                        font=("Segoe UI", 11, "bold"), bg=CARD_HI,
                                        fg=FG, relief="flat", cursor="hand2")
        self.btn_recarregar.pack(side="left", fill="x", expand=True, ipady=10, padx=(10, 0))
        self.btn_aprendizado = tk.Button(sec, text="📝  APRENDIZADO",
                                         command=self.on_ver_aprendizado,
                                         font=("Segoe UI", 11, "bold"), bg=CARD_HI,
                                         fg=FG, relief="flat", cursor="hand2")
        self.btn_aprendizado.pack(side="left", fill="x", expand=True, ipady=10, padx=(10, 0))
        self.btn_limpar_abas = tk.Button(sec, text="🧹  FECHAR ABAS",
                                         command=self.on_fechar_abas,
                                         font=("Segoe UI", 11, "bold"), bg=CARD_HI,
                                         fg=FG, relief="flat", cursor="hand2")
        self.btn_limpar_abas.pack(side="left", fill="x", expand=True, ipady=10, padx=(10, 0))

        # seleção
        selbar = tk.Frame(self, bg=BG)
        selbar.pack(fill="x", padx=18, pady=(16, 4))
        tk.Label(selbar, text="PERFIS", font=("Segoe UI", 9, "bold"),
                 bg=BG, fg=MUTED).pack(side="left")
        tk.Button(selbar, text="nenhum", command=lambda: self.marcar_todos(False),
                  font=("Segoe UI", 9), bg=BG, fg=MUTED, relief="flat",
                  cursor="hand2").pack(side="right")
        tk.Button(selbar, text="todos", command=lambda: self.marcar_todos(True),
                  font=("Segoe UI", 9), bg=BG, fg=MUTED, relief="flat",
                  cursor="hand2").pack(side="right", padx=8)
        tk.Button(selbar, text="só o da casa", command=self.marcar_so_casa,
                  font=("Segoe UI", 9), bg=BG, fg=MATCH_BD, relief="flat",
                  cursor="hand2").pack(side="right", padx=8)

        # lista
        lista = tk.Frame(self, bg=BG)
        lista.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        self.lista = lista
        self.rows = []
        self._mtime_perfis = 0
        try:
            self._mtime_perfis = PROFILES_FILE.stat().st_mtime
        except Exception:
            pass
        try:
            profiles = load_profiles()
        except Exception as e:
            profiles = []
            tk.Label(lista, text=f"Erro lendo profiles.json: {e}",
                     bg=BG, fg=ERR).pack()
        for p in profiles:
            r = Row(lista, p)
            r.pack(fill="x", pady=3)
            self.rows.append(r)

        tk.Checkbutton(
            self, text=f"vigiar proxies sozinho (abre uma aba em cada perfil a cada "
                       f"{PING_AUTO_MIN} min)",
            variable=self.auto_ping, command=self.alternar_auto_ping,
            font=("Segoe UI", 9), bg=BG, fg=MUTED, selectcolor=CARD,
            activebackground=BG, activeforeground=FG, anchor="w",
            highlightthickness=0, bd=0).pack(fill="x", padx=18, pady=(0, 4))

        self.lbl_gravando = tk.Label(
            self, text="", font=("Segoe UI", 9, "bold"), bg=BG, fg=WARN, anchor="w")
        self.lbl_gravando.pack(fill="x", padx=18)

        self.rodape = tk.Label(self, text="Clique em CONECTAR para abrir os perfis no Opera.",
                               font=("Segoe UI", 10), bg=BG, fg=MUTED, anchor="w")
        self.rodape.pack(fill="x", padx=18, pady=(0, 14))

        self.registrar_atalho_global()
        self.montar_bandeja()
        self.protocol("WM_DELETE_WINDOW", self.esconder)
        self._pingando = False
        self._ping_agendado = None
        self.memoria_apostas = aprendiz.MemoriaApostas(PROFILES_FILE.parent) if aprendiz else None
        self._gravando = False
        # A gravação não roda o tempo todo: ela liga quando você abre um link
        # e desliga sozinha. Assim o que é gravado é sempre "acabei de abrir
        # este jogo", em vez de você navegando à toa — sinal muito mais limpo,
        # e sem varrer abas o dia inteiro.
        self.sessao = None          # {"ate": timestamp, "abas": {port: [tab_id]}}
        # O botão PERFIS busca do painel na hora. Este vigia é para o outro
        # caminho: quando o saldos.py reescreve o profiles.json no meio de uma
        # varredura, o app percebe sozinho sem você clicar em nada.
        self.after(20_000, self._vigiar_perfis)
        if self.auto_ping.get():
            self._agendar_ping()

    # ---------- histórico ----------
    def render_hist(self):
        self.menu_hist.delete(0, "end")
        if not self.hist:
            self.menu_hist.add_command(label="(vazio)", state="disabled")
            return
        for u in self.hist:
            self.menu_hist.add_command(
                label=u if len(u) < 70 else u[:67] + "...",
                command=lambda x=u: self.usar_link(x))

    def usar_link(self, url):
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, url)
        self.atualizar_destaque()

    def add_hist(self, url):
        if url in self.hist:
            self.hist.remove(url)
        self.hist.insert(0, url)
        self.hist = self.hist[:MAX_HIST]
        save_hist(self.hist)
        self.render_hist()

    # ---------- atalho global ----------
    def registrar_atalho_global(self):
        if keyboard is None:
            return
        try:
            keyboard.add_hotkey("ctrl+shift+a", lambda: self.after(0, self.disparo_rapido))
        except Exception:
            pass

    def disparo_rapido(self):
        """Cola do clipboard e abre nos perfis da casa detectada."""
        self.colar()
        self.marcar_so_casa()
        self.deiconify()
        self.lift()
        self.on_abrir()

    # ---------- helpers ----------
    def colar(self):
        try:
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, self.clipboard_get().strip())
            self.atualizar_destaque()
        except Exception:
            pass

    def atualizar_destaque(self):
        dom = dominio(self.url_entry.get().strip())
        achou, limitados = False, 0
        for r in self.rows:
            bate = casa_bate(dom, r.casas)
            r.destacar(bate, dom if bate else "")
            if dom:
                # colar o link já deixa marcados só os perfis que têm a casa
                # e não estão limitados nela
                limitada = bate and casa_limitada(r.profile, dom)
                r.marcar(bate and not limitada)
                limitados += 1 if limitada else 0
            achou = achou or bate
        if dom and not achou:
            self.info(f"{dom} — nenhum perfil cadastrado para esta casa.", WARN)
        elif dom:
            extra = f"  ·  {limitados} limitado(s), fora da seleção" if limitados else ""
            self.info(self._resumo_saldos(dom) + extra, OK)

    def _resumo_saldos(self, dom):
        """'betano.bet.br — Você R$ 1.234,56 · Mãe R$ 0,00 · total R$ ...'"""
        partes, total, com_dado = [], 0.0, 0
        for r in self.rows:
            if not casa_bate(dom, r.casas):
                continue
            casa = saldo_da_casa(r.profile, dom)
            if casa is None:
                partes.append(f"{r.profile['nome']} —")
                continue
            saldo = float(casa.get("saldo_anterior") or 0)
            total += saldo
            com_dado += 1
            marca = " 🔒" if casa.get("limitada") else ""
            partes.append(f"{r.profile['nome']} {fmt_brl(saldo)}{marca}")
        if not com_dado:
            return f"{dom} — perfil correspondente destacado abaixo."
        junto = "  ·  ".join(partes)
        if com_dado > 1:
            junto += f"  ·  total {fmt_brl(total)}"
        return f"{dom} — {junto}"

    def marcar_todos(self, valor):
        for r in self.rows:
            if r.marcado.get() != valor:
                r.toggle()

    def marcar_so_casa(self):
        dom = dominio(self.url_entry.get().strip())
        if not dom:
            return
        limitados = 0
        for r in self.rows:
            quer = casa_bate(dom, r.casas)
            if quer and casa_limitada(r.profile, dom):
                quer = False
                limitados += 1
            r.marcar(quer)
        if limitados:
            self.info(f"{limitados} perfil(is) fora da seleção por estarem "
                      f"limitados em {dom}.", WARN)

    def marcados(self):
        return [r for r in self.rows if r.marcado.get()]

    def info(self, texto, cor=MUTED):
        self.rodape.config(text=texto, fg=cor)
        self.update_idletasks()

    def travar(self, travado):
        estado = "disabled" if travado else "normal"
        for b in (self.btn_abrir, self.btn_conectar,
                  self.btn_limpar_abas, self.btn_ping):
            b.config(state=estado)

    # ---------- ações ----------
    def on_conectar(self):
        self.travar(True)
        threading.Thread(target=self._conectar, daemon=True).start()

    def _conectar(self, alvos=None):
        alvos = alvos or self.rows
        self.info("Conectando...", ACCENT)
        ok = 0
        for i, r in enumerate(alvos):
            if i:
                time.sleep(RATE_LIMIT_S)
            try:
                r.status("abrindo no Opera..." if i == 0 else "verificando...", MUTED)
                port, erro = abrir_perfil(r.profile)
                if port is None:
                    r.port = None
                    r.status(erro or "não abriu no Opera", WARN)
                else:
                    r.port = port
                    r.status(f"conectado · porta {port}", OK)
                    ok += 1
            except Exception as e:
                r.port = None
                r.status(f"erro: {e}", ERR)
        self.info(f"{ok}/{len(alvos)} conectados. Abrir agora é instantâneo.",
                  OK if ok else WARN)
        self.travar(False)
        return ok

    def links_do_campo(self):
        """Aceita 1 link ou vários separados por espaço/quebra de linha."""
        bruto = self.url_entry.get().strip()
        partes = [x.strip() for x in bruto.replace("\n", " ").split() if x.strip()]
        return ["https://" + x if not x.startswith("http") else x for x in partes]

    def on_abrir(self):
        urls = self.links_do_campo()
        if not urls:
            self.info("Cole um link primeiro.", WARN)
            return
        self._iniciar_sessao()
        if len(urls) > 1:
            self.travar(True)
            threading.Thread(target=self._abrir_lote, args=(urls,),
                             daemon=True).start()
            return
        alvos = self.marcados()
        if not alvos:
            self.info("Marque pelo menos um perfil.", WARN)
            return
        self.travar(True)
        threading.Thread(target=self._abrir, args=(urls[0], alvos),
                         daemon=True).start()

    def _abrir_lote(self, urls):
        """Vários links: cada um vai só pro perfil dono daquela casa."""
        t0, total, sem_dono = time.time(), 0, []
        for u in urls:
            dom = dominio(u)
            donos = [r for r in self.rows if casa_bate(dom, r.casas)]
            if not donos:
                sem_dono.append(dom)
                continue
            for r in donos:
                if not r.port:
                    self._conectar([r])
                if not r.port:
                    continue
                try:
                    aba = open_tab(r.port, u)
                    self._marcar_aba_sessao(r, aba)
                    r.status(f"aba aberta ✓ · {dom}", OK)
                    total += 1
                except Exception as e:
                    r.status(f"falhou {dom}: {e}", ERR)
            self.add_hist(u)
        msg = f"{total} aba(s) em {time.time()-t0:.2f}s"
        if sem_dono:
            msg += f" · sem perfil: {', '.join(sem_dono)}"
        self.info(msg, OK if total else WARN)
        self.travar(False)

    def _abrir(self, url, alvos):
        t0 = time.time()
        ok, caidos = 0, []
        for r in alvos:
            if not r.port:
                caidos.append(r)
                continue
            try:
                aba = open_tab(r.port, url)
                self._marcar_aba_sessao(r, aba)
                r.status("aba aberta ✓", OK)
                ok += 1
            except Exception:
                r.port = None
                caidos.append(r)

        # auto-reconecta quem caiu e tenta de novo
        if caidos:
            self.info(f"Reconectando {len(caidos)} perfil(is)...", WARN)
            self._conectar(caidos)
            for r in caidos:
                if not r.port:
                    continue
                try:
                    aba = open_tab(r.port, url)
                    self._marcar_aba_sessao(r, aba)
                    r.status("aba aberta ✓ (reconectado)", OK)
                    ok += 1
                except Exception as e:
                    r.status(f"falhou: {e}", ERR)

        if ok:
            self.add_hist(url)
        self.info(f"{ok} aba(s) aberta(s) em {time.time()-t0:.2f}s",
                  OK if ok else ERR)
        self.travar(False)

    def on_ping(self):
        if websocket is None:
            self.info("PING precisa de: pip install websocket-client", ERR)
            return
        self.travar(True)
        threading.Thread(target=self._ping, daemon=True).start()

    def _ping(self):
        for r in self.marcados():
            if not r.port:
                r.ping("—", MUTED)
                r.status("sem conexão — CONECTAR", WARN)
                continue
            try:
                r.ping("...", MUTED)
                ms = ping_proxy(r.port)
                cor = OK if ms < 400 else (WARN if ms < 1000 else ERR)
                r.ping(f"{ms} ms", cor)
            except Exception as e:
                r.ping("erro", ERR)
                r.status(f"ping falhou: {e}", ERR)
        self.info("Ping medido pelo proxy de cada perfil "
                  "(verde <400ms · laranja <1s · vermelho acima).", MUTED)
        self.travar(False)

    def on_ver_aprendizado(self):
        """Quantas casas já sabemos operar, e quais ainda faltam."""
        if self.memoria_apostas is None:
            self.info("aprendiz.py não encontrado nesta pasta.", WARN)
            return
        conhecidos = set()
        for r in self.rows:
            for c in (r.casas or []):
                conhecidos.add(c.lower())
        c = self.memoria_apostas.cobertura(conhecidos or None)
        prontas, parciais = c["prontas"], c["parciais"]
        faltam = len(conhecidos) - len(prontas) - len(parciais)
        if not prontas and not parciais:
            self.info("Ainda não observei nenhuma aposta. Aposte normalmente "
                      "com o app aberto que eu vou aprendendo.", MUTED)
            return
        exemplo = ", ".join(r["dominio"] for r in prontas[:3])
        self.info(
            f"📝 {len(prontas)} casa(s) prontas ({exemplo}{'...' if len(prontas) > 3 else ''}) · "
            f"{len(parciais)} em aprendizado · {max(faltam, 0)} sem nenhuma aposta ainda. "
            f"Detalhe: python aprendiz.py",
            OK if prontas else MUTED)

    # ---------- aprendizado de apostas (só durante a sessão) ----------
    SESSAO_MINUTOS = 20        # depois disso, desliga sozinha

    def _iniciar_sessao(self):
        """Abrir um link liga a gravação. Nada é gravado fora disso."""
        if self.memoria_apostas is None or websocket is None:
            return
        nova = self.sessao is None
        self.sessao = {"ate": time.time() + self.SESSAO_MINUTOS * 60,
                       "abas": (self.sessao or {}).get("abas", {}),
                       "prontas": (self.sessao or {}).get("prontas", set())}
        if nova:
            self.after(4_000, self._ciclo_sessao)

    def _marcar_aba_sessao(self, row, aba):
        """Guarda exatamente qual aba foi aberta por este clique."""
        if self.sessao is None or not isinstance(aba, dict):
            return
        tab_id = aba.get("id")
        if not tab_id:
            return
        self.sessao["abas"].setdefault(row.port, [])
        if tab_id not in self.sessao["abas"][row.port]:
            self.sessao["abas"][row.port].append(tab_id)

    def _ciclo_sessao(self):
        if self.sessao is None:
            return
        if time.time() > self.sessao["ate"]:
            self._encerrar_sessao()
            return
        abas = sum(len(v) for v in self.sessao["abas"].values())
        prontas = len(self.sessao["prontas"])
        if abas and prontas >= abas:
            # todas as abas desta abertura já ensinaram: não há mais o que ouvir
            self._encerrar_sessao("Aprendi em todas as abas desta abertura.")
            return
        restam = int((self.sessao["ate"] - time.time()) / 60) + 1
        self.lbl_gravando.config(
            text=f"⏺ observando {abas - prontas} de {abas} aba(s) · {restam} min")
        if not self._gravando:
            threading.Thread(target=self._gravar_uma_volta, daemon=True).start()
        self.after(4_000, self._ciclo_sessao)

    def _encerrar_sessao(self, motivo=None):
        if self.sessao is None:
            return
        # deixa as páginas quietas antes de soltar a sessão
        for r in self.rows:
            for tab_id in (self.sessao["abas"].get(r.port) or []):
                if tab_id in self.sessao["prontas"] or not r.port:
                    continue
                try:
                    tab = next((t for t in paginas(r.port) if t.get("id") == tab_id), None)
                    if tab:
                        _js_na_aba(r.port, tab, aprendiz.JS_PARAR)
                except Exception:
                    pass
        self.sessao = None
        self.lbl_gravando.config(text="")
        if self.memoria_apostas is not None:
            self.info(f"{motivo or 'Gravação encerrada'} — abra outro link para retomar.",
                      MUTED)

    def _gravar_uma_volta(self):
        """
        Olha SÓ as abas que este app abriu nesta sessão. Não varre o resto do
        navegador, não toca em perfil que não recebeu link.
        """
        self._gravando = True
        aprendeu = []
        try:
            sessao = self.sessao
            if sessao is None:
                return
            for r in self.rows:
                alvos = sessao["abas"].get(r.port) or []
                if not r.port or not alvos:
                    continue
                for tab in paginas(r.port):
                    tab_id = tab.get("id")
                    if tab_id not in alvos or tab_id in sessao["prontas"]:
                        continue          # nunca vista, ou já ensinou o que tinha
                    url = tab.get("url") or ""
                    if not url.startswith("http"):
                        continue
                    try:
                        _js_na_aba(r.port, tab, aprendiz.JS_GRAVADOR)
                        bruto = _js_na_aba(r.port, tab, aprendiz.JS_DRENAR)
                    except Exception:
                        continue
                    if not bruto:
                        continue
                    try:
                        pacote = json.loads(bruto)
                    except Exception:
                        continue
                    achou = self.memoria_apostas.registrar(
                        pacote.get("url") or url, pacote.get("eventos") or [])
                    if not achou:
                        continue
                    # aprendeu o que precisava aqui: desliga a escuta nesta aba
                    sessao["prontas"].add(tab_id)
                    try:
                        _js_na_aba(r.port, tab, aprendiz.JS_PARAR)
                    except Exception:
                        pass
                    aprendeu.append((r.profile.get("nome"), achou))
        except Exception:
            pass
        finally:
            self._gravando = False

        if aprendeu:
            self.after(0, lambda: self._avisar_aprendizado(aprendeu))

    def _avisar_aprendizado(self, aprendeu):
        # você ainda está apostando: estende o prazo
        if self.sessao is not None:
            self.sessao["ate"] = max(self.sessao["ate"],
                                     time.time() + self.SESSAO_MINUTOS * 60)
        nome, achou = aprendeu[-1]
        r = self.memoria_apostas.receita(achou["dominio"])
        if not r:
            return
        estado = ("já sei apostar aqui" if r["pronta"]
                  else f"aprendendo ({r['confianca']}/{aprendiz.MIN_OBSERVACOES})")
        self.info(f"📝 aposta observada em {achou['dominio']} ({nome}) — {estado}.",
                  OK if r["pronta"] else MUTED)

    def on_sincronizar_perfis(self):
        """
        Faz o mesmo que `python nuvem.py --sincronizar-profiles`: busca as
        casas no painel, reescreve o profiles.json e recarrega a lista.
        Sem painel configurado, cai para só reler o arquivo local.
        """
        if nuvem is None:
            self.info("nuvem.py não encontrado — relendo só o arquivo local.", WARN)
            self.recarregar_perfis(True)
            return
        self.btn_recarregar.config(state="disabled", text="🔄  BUSCANDO...")
        self.info("Buscando as casas no painel...", MUTED)
        threading.Thread(target=self._sincronizar_perfis, daemon=True).start()

    def _sincronizar_perfis(self):
        resumo, erro = None, None
        try:
            cfg = nuvem.carregar_config(PROFILES_FILE.parent)
            _uid, dados = nuvem.baixar_estado(cfg)
            resumo = nuvem.atualizar_profiles_json(PROFILES_FILE.parent, dados,
                                                   arquivo=PROFILES_FILE)
        except Exception as e:
            erro = str(e)[:160]

        def concluir():
            self.btn_recarregar.config(state="normal", text="🔄  PERFIS")
            if erro:
                self.info(f"Painel indisponível ({erro}) — relendo o arquivo local.", WARN)
                self.recarregar_perfis(True)
                return
            try:
                self._mtime_perfis = PROFILES_FILE.stat().st_mtime
            except Exception:
                pass
            self.recarregar_perfis(avisar=False)
            novas = [f"{nome}: {', '.join(info['novas'])}"
                     for nome, info in (resumo or {}).items() if info.get("novas")]
            total = sum(info.get("total", 0) for info in (resumo or {}).values())
            if novas:
                self.info(f"Painel sincronizado · casas novas → {' · '.join(novas)}", OK)
            else:
                self.info(f"Painel sincronizado · {total} casa(s), nada novo.", OK)
        self.after(0, concluir)

    def _vigiar_perfis(self):
        """Recarrega o profiles.json quando ele muda, sem derrubar conexões."""
        try:
            mtime = PROFILES_FILE.stat().st_mtime
        except Exception:
            mtime = self._mtime_perfis
        if mtime != self._mtime_perfis:
            self._mtime_perfis = mtime
            self.recarregar_perfis()
        self.after(20_000, self._vigiar_perfis)

    def recarregar_perfis(self, avisar=True):
        try:
            perfis = load_profiles()
        except Exception as e:
            self.info(f"Não consegui reler o profiles.json: {e}", ERR)
            return

        por_nome = {p.get("nome"): p for p in perfis}
        novas, perfis_novos = 0, 0
        for r in self.rows:
            p = por_nome.get(r.profile.get("nome"))
            if not p:
                continue
            antes = {c.lower() for c in (r.casas or [])}
            r.profile = p                      # traz casas_painel e saldos novos
            r.casas = p.get("casas", [])
            novas += len({c.lower() for c in r.casas} - antes)

        conhecidos = {r.profile.get("nome") for r in self.rows}
        for p in perfis:
            if p.get("nome") in conhecidos:
                continue
            linha = Row(self.lista, p)
            linha.pack(fill="x", pady=3)
            self.rows.append(linha)
            perfis_novos += 1

        if not avisar:
            return
        if novas or perfis_novos:
            partes = []
            if novas:
                partes.append(f"{novas} casa(s) nova(s)")
            if perfis_novos:
                partes.append(f"{perfis_novos} perfil(is)")
            self.info(f"profiles.json atualizado: {' e '.join(partes)}.", OK)
        else:
            self.info("profiles.json relido — nada novo.", MUTED)

    def alternar_auto_ping(self):
        """Liga/desliga a vigilância dos proxies. Desligado, nada abre sozinho."""
        if self.auto_ping.get():
            self._agendar_ping()
            self.info(f"Ping automático ligado (a cada {PING_AUTO_MIN} min). "
                      "Uma aba pisca em cada perfil a cada ciclo.", MUTED)
        else:
            if self._ping_agendado is not None:
                try:
                    self.after_cancel(self._ping_agendado)
                except Exception:
                    pass
                self._ping_agendado = None
            self.info("Ping automático desligado. Use o botão PING quando quiser.", MUTED)

    def _agendar_ping(self):
        if self._ping_agendado is not None:
            try:
                self.after_cancel(self._ping_agendado)
            except Exception:
                pass
        self._ping_agendado = self.after(PING_AUTO_MIN * 60_000, self.ping_automatico)

    def ping_automatico(self):
        """Mede em background e só incomoda se algo degradar."""
        if not self.auto_ping.get():
            self._ping_agendado = None
            return
        # se o ciclo anterior ainda está rodando, pula este: threads
        # empilhadas seguravam websockets e abas abertas sem necessidade
        if websocket is not None and not self._pingando:
            threading.Thread(target=self._ping_silencioso, daemon=True).start()
        self._agendar_ping()

    def _ping_silencioso(self):
        self._pingando = True
        try:
            self._rodar_ping_silencioso()
        finally:
            self._pingando = False

    def _rodar_ping_silencioso(self):
        ruins = []
        for r in self.rows:
            if not r.port:
                continue
            try:
                ms = ping_proxy(r.port)
                cor = OK if ms < 400 else (WARN if ms < PING_ALERTA_MS else ERR)
                r.ping(f"{ms} ms", cor)
                if ms >= PING_ALERTA_MS:
                    ruins.append(f"{r.profile['nome']} {ms}ms")
            except Exception:
                r.ping("erro", ERR)
                ruins.append(f"{r.profile['nome']} sem resposta")
        if ruins:
            self.bell()
            self.info("⚠ proxy lento: " + " · ".join(ruins), ERR)

    def on_fechar_abas(self):
        self.travar(True)
        threading.Thread(target=self._fechar_abas, daemon=True).start()

    def _fechar_abas(self):
        # fechar abas é o sinal claro de "terminei com estes perfis"
        self._encerrar_sessao("Gravação encerrada junto com as abas")
        # aproveita e varre about:blank esquecidas de ciclos de ping antigos
        for r in self.rows:
            if r.port:
                try:
                    limpar_abas_orfas(r.port)
                except Exception:
                    pass
        total = 0
        for r in self.marcados():
            if not r.port:
                r.status("sem conexão — CONECTAR", WARN)
                continue
            try:
                n = close_old_tabs(r.port)
                total += n
                r.status(f"{n} aba(s) fechada(s)" if n else "já estava limpo", OK)
            except Exception as e:
                r.status(f"erro ao limpar: {e}", ERR)
        self.info(f"{total} aba(s) fechada(s) no total.", OK)
        self.travar(False)


    # ---------- bandeja ----------
    def montar_bandeja(self):
        self.tray = None
        if pystray is None:
            return
        img = Image.new("RGB", (64, 64), "#15171c")
        d = ImageDraw.Draw(img)
        d.ellipse((14, 14, 50, 50), fill="#2f80ed")
        menu = pystray.Menu(
            pystray.MenuItem("Abrir janela", lambda: self.after(0, self.mostrar),
                             default=True),
            pystray.MenuItem("Colar e abrir (casa)",
                             lambda: self.after(0, self.disparo_rapido)),
            pystray.MenuItem("Reconectar perfis",
                             lambda: self.after(0, self.on_conectar)),
            pystray.MenuItem("Sair", lambda: self.after(0, self.sair)),
        )
        self.tray = pystray.Icon("adspower_launcher", img,
                                 "Abridor multi-perfil", menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    def esconder(self):
        if getattr(self, "tray", None):
            self.withdraw()
        else:
            self.sair()

    def mostrar(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def sair(self):
        if getattr(self, "tray", None):
            try:
                self.tray.stop()
            except Exception:
                pass
        self.destroy()


if __name__ == "__main__":
    App().mainloop()