"""
Aprende, observando você apostar, onde fica o campo de stake e o botão de
confirmar em cada casa.

Como funciona
-------------
O `app.py` injeta um gravador leve em cada aba aberta nos perfis. Ele NÃO
clica em nada e NÃO envia nada para fora: só anota, dentro da própria página,
o caminho CSS dos elementos com que você interagiu — o campo onde digitou um
valor e o botão que clicou em seguida. A cada poucos segundos o app esvazia
essa anotação e grava num arquivo local.

Depois de uma semana apostando normalmente, cada casa tem dezenas de
observações. A parte de inferência escolhe os caminhos que se repetem e
descarta o que foi acidente.

Nada aqui aposta por você. É só memória de onde ficam as coisas.

Arquivo gerado: `aprendizado_apostas.json`, no formato

    {
      "betano.bet.br": {
        "stake":  [{"seletor": "...", "vezes": 12, "ultima": "2026-08-11"}],
        "botao":  [{"seletor": "...", "texto": "apostar", "vezes": 11, ...}],
        "sessoes": 12
      }
    }
"""

import json
import re
import unicodedata
from datetime import date

ARQUIVO = "aprendizado_apostas.json"

# quanto uma casa precisa repetir para a gente confiar
MIN_OBSERVACOES = 3

# palavras que aparecem no botão que efetiva a aposta
RE_CONFIRMA = re.compile(
    r"apostar|fazer aposta|confirmar|finalizar|realizar aposta|place bet",
    re.I,
)
# botões que NÃO são o de confirmar (evita aprender o alvo errado)
RE_NAO_CONFIRMA = re.compile(
    r"limpar|remover|cancelar|fechar|excluir|depositar|sacar|entrar|login|"
    r"aceitar cookies|adicionar|cupom|copiar",
    re.I,
)


# ---------------------------------------------------------------- gravador (JS)
# Roda dentro da página, em modo somente-leitura de intenção: escuta eventos
# que VOCÊ dispara. Não sintetiza clique nenhum.
JS_GRAVADOR = r"""
(() => {
  if (window.__apostaRec) {                     // já instalado nesta página
    window.__apostaAtivo = true;                // (religa se tinha parado)
    return 'ja';
  }
  window.__apostaRec = true;
  window.__apostaAtivo = true;
  window.__apostaLog = [];

  const MAX = 60;                                // buffer curto; o app esvazia
  const RE_NUM = /^\s*R?\$?\s*\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})?\s*$|^\s*\d+(?:[.,]\d{1,2})?\s*$/;

  function caminho(el) {
    const partes = [];
    let n = el;
    for (let i = 0; n && n.nodeType === 1 && i < 6; i++) {
      if (n.id && /^[A-Za-z][\w-]*$/.test(n.id)) { partes.unshift('#' + n.id); break; }
      let s = n.tagName.toLowerCase();
      const bruto = (typeof n.className === 'string') ? n.className.trim() : '';
      // classes com muitos dígitos costumam ser geradas (hash) e mudam a cada build
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

  function anota(reg) {
    if (!window.__apostaAtivo) return;           // já aprendemos: fica quieto
    reg.t = Date.now();
    window.__apostaLog.push(reg);
    if (window.__apostaLog.length > MAX) window.__apostaLog.shift();
  }

  // campo de stake: input que recebeu algo com cara de valor
  document.addEventListener('input', (e) => {
    try {
      const el = e.target;
      if (!el || el.tagName !== 'INPUT') return;
      if (el.type === 'password') return;                 // nunca
      const v = (el.value || '').trim();
      if (!v || v.length > 12 || !RE_NUM.test(v)) return;
      anota({ tipo: 'stake', seletor: caminho(el), valor: v.slice(0, 12) });
    } catch (err) {}
  }, true);

  // botão: clique seu em algo clicável
  document.addEventListener('click', (e) => {
    try {
      let el = e.target;
      for (let i = 0; i < 4 && el; i++) {
        const tag = el.tagName;
        if (tag === 'BUTTON' || tag === 'A' ||
            (tag === 'INPUT' && /submit|button/i.test(el.type || '')) ||
            el.getAttribute('role') === 'button') break;
        el = el.parentElement;
      }
      if (!el || el.nodeType !== 1) return;
      const txt = (el.innerText || el.value || '').replace(/\s+/g, ' ').trim().slice(0, 40);
      anota({ tipo: 'clique', seletor: caminho(el), texto: txt });
    } catch (err) {}
  }, true);

  return 'ok';
})()
"""

# Desliga a escuta nesta página. Os listeners continuam registrados (não dá
# para removê-los com segurança de fora), mas passam a sair na primeira linha
# e nada mais é acumulado.
JS_PARAR = r"""
(() => {
  window.__apostaAtivo = false;
  if (window.__apostaLog) window.__apostaLog.length = 0;
  return 'parado';
})()
"""

# esvazia o buffer e devolve o que estava lá
JS_DRENAR = r"""
(() => {
  if (!window.__apostaLog) return JSON.stringify({url: location.href, eventos: []});
  const eventos = window.__apostaLog.splice(0, window.__apostaLog.length);
  return JSON.stringify({url: location.href, eventos: eventos});
})()
"""


# ---------------------------------------------------------------- utilidades
def dominio(url):
    from urllib.parse import urlparse

    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    host = (urlparse(url).netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def _norm(texto):
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.split()).strip().lower()


def parece_confirmar(texto):
    """O texto do botão indica que ele efetiva a aposta?"""
    t = _norm(texto)
    if not t or RE_NAO_CONFIRMA.search(t):
        return False
    return bool(RE_CONFIRMA.search(t))


# ---------------------------------------------------------------- memória
class MemoriaApostas:
    def __init__(self, pasta):
        from pathlib import Path

        self.caminho = Path(pasta) / ARQUIVO
        try:
            with open(self.caminho, encoding="utf-8") as arquivo:
                self.dados = json.load(arquivo)
        except Exception:
            self.dados = {}

    def salvar(self):
        try:
            with open(self.caminho, "w", encoding="utf-8") as arquivo:
                json.dump(self.dados, arquivo, ensure_ascii=False, indent=1)
        except Exception:
            pass    # aprender é bônus; nunca deve atrapalhar o app

    # ---------- registro ----------
    def _bucket(self, dom, chave):
        reg = self.dados.setdefault(dom, {"stake": [], "botao": [], "sessoes": 0})
        return reg.setdefault(chave, [])

    def _somar(self, lista, seletor, extra=None):
        for item in lista:
            if item["seletor"] == seletor:
                item["vezes"] += 1
                item["ultima"] = date.today().isoformat()
                if extra:
                    item.update({k: v for k, v in extra.items() if v})
                return item
        novo = {"seletor": seletor, "vezes": 1, "ultima": date.today().isoformat()}
        if extra:
            novo.update(extra)
        lista.append(novo)
        return novo

    def registrar(self, url, eventos):
        """
        Recebe o que o gravador anotou numa aba e extrai o que interessa.

        A regra é: um clique num botão com cara de "apostar" conta como
        confirmação. O último campo numérico mexido ANTES dele, na mesma
        página, é o campo de stake. Cliques em outras coisas são ignorados.
        """
        dom = dominio(url)
        if not dom or not eventos:
            return None

        eventos = sorted(eventos, key=lambda e: e.get("t") or 0)
        ultimo_stake = None
        achou = None

        for ev in eventos:
            if ev.get("tipo") == "stake":
                ultimo_stake = ev
                continue
            if ev.get("tipo") != "clique":
                continue
            if not parece_confirmar(ev.get("texto")):
                continue

            # é uma confirmação: aprende o botão, e o campo que veio antes
            self._somar(self._bucket(dom, "botao"), ev["seletor"],
                        {"texto": _norm(ev.get("texto"))[:40]})
            if ultimo_stake:
                self._somar(self._bucket(dom, "stake"), ultimo_stake["seletor"],
                            {"exemplo": ultimo_stake.get("valor")})
            reg = self.dados[dom]
            reg["sessoes"] = reg.get("sessoes", 0) + 1
            achou = {"dominio": dom, "botao": ev.get("texto"),
                     "stake": bool(ultimo_stake)}
            ultimo_stake = None

        if achou:
            self.salvar()
        return achou

    # ---------- consulta ----------
    def melhor(self, dom, chave):
        itens = sorted((self.dados.get(dom) or {}).get(chave) or [],
                       key=lambda i: -i.get("vezes", 0))
        return itens[0] if itens else None

    def receita(self, dom):
        """O que sabemos sobre essa casa, e se dá pra confiar."""
        dom = (dom or "").lower()
        reg = self.dados.get(dom)
        if not reg:
            return None
        stake = self.melhor(dom, "stake")
        botao = self.melhor(dom, "botao")
        if not botao:
            return None
        confianca = min(botao.get("vezes", 0), stake.get("vezes", 0) if stake else 0)
        return {
            "dominio": dom,
            "stake": stake,
            "botao": botao,
            "sessoes": reg.get("sessoes", 0),
            "confianca": confianca,
            "pronta": confianca >= MIN_OBSERVACOES,
        }

    def cobertura(self, dominios=None):
        """Resumo de quantas casas já foram aprendidas."""
        prontas, parciais = [], []
        for dom in sorted(self.dados):
            if dominios and dom not in dominios:
                continue
            r = self.receita(dom)
            if not r:
                continue
            (prontas if r["pronta"] else parciais).append(r)
        return {"prontas": prontas, "parciais": parciais}


# ---------------------------------------------------------------- linha de comando
if __name__ == "__main__":
    import argparse
    from pathlib import Path

    PASTA = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Mostra o que o gravador já aprendeu sobre cada casa.")
    parser.add_argument("--detalhe", metavar="DOMINIO",
                        help="mostra os caminhos aprendidos de uma casa")
    args = parser.parse_args()

    memoria = MemoriaApostas(PASTA)
    if args.detalhe:
        r = memoria.receita(args.detalhe)
        if not r:
            print(f"Nada aprendido ainda sobre {args.detalhe}.")
            raise SystemExit(1)
        print(f"{r['dominio']} — {r['sessoes']} aposta(s) observada(s) · "
              f"{'PRONTA' if r['pronta'] else 'ainda aprendendo'}")
        print(f"  stake: {(r['stake'] or {}).get('seletor', '(não identificado)')}")
        print(f"  botão: {r['botao']['seletor']}  «{r['botao'].get('texto','')}»")
        raise SystemExit(0)

    c = memoria.cobertura()
    print(f"{len(c['prontas'])} casa(s) prontas · {len(c['parciais'])} em aprendizado\n")
    for r in c["prontas"]:
        print(f"  ✅ {r['dominio']:<28} {r['sessoes']:>3} aposta(s)")
    for r in c["parciais"]:
        falta = MIN_OBSERVACOES - r["confianca"]
        print(f"  ⏳ {r['dominio']:<28} {r['sessoes']:>3} aposta(s) · "
              f"faltam ~{falta} pra confiar")
    if not c["prontas"] and not c["parciais"]:
        print("  (nada ainda — aposte normalmente com o app.py aberto)")
