"""
Ponte entre o saldos.py e o painel do apostador (Supabase).

O painel guarda tudo num único registro JSON na tabela `app_state`. Dentro
dele, `data.houses` é a lista de casas, cada uma assim:

    {"id": "...", "nome": "Betano", "usuario": "Mãe", "saldo": 132.63,
     "rolando": 0, "deixar": 200, "link": "https://...", "status": "ativa",
     "verificadoEm": "2026-08-01", "notas": "", "historico": [...]}

`usuario` vazio ("") = as suas próprias casas; os demais perfis usam o
nome da pessoa ("Mãe", "Pai"...).

Este módulo faz três coisas:
  1. baixa a lista de casas de um perfil (para o saldos.py só varrer o que
     interessa, sem as 100 casas zeradas que estão lá só por registro);
  2. devolve os saldos lidos para o painel, atualizando `saldo`,
     `verificadoEm` e o histórico de cada casa;
  3. mantém o profiles.json local em dia com o que existe na nuvem, para
     que casas novas cadastradas no painel apareçam na próxima varredura.

Configuração: crie um arquivo `nuvem.json` nesta mesma pasta:

    {
      "supabase_url": "https://SEUPROJETO.supabase.co",
      "supabase_key": "sb_secret_..."
    }

A chave é a **secret key** do projeto (Settings → API), a mesma usada pela
skill de sincronização. Ela ignora o RLS, então trate como senha de admin:
NUNCA suba o nuvem.json para o GitHub (deixe no .gitignore).
"""

import json
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime

ARQUIVO_CONFIG = "nuvem.json"
TIMEOUT = 25

# Um perfil é identificado por uma CHAVE, não pelo texto exato do campo:
# "" e o seu nome são a mesma pessoa; "Mae" e "Mãe" também.
# Comparar o texto cru fazia o seu perfil não achar casa nenhuma quando o
# painel gravava o nome por extenso em vez de deixar o campo vazio.
# Preencha com os apelidos que VOCÊ usa. A chave da esquerda é como o nome
# pode aparecer (no perfil do Opera ou no painel); a da direita é o nome
# canônico. Exemplo:
#     "mamae": "mae", "pai velho": "pai"
ALIASES_CHAVE = {
    "": "dono",
    "eu": "dono",
}


# ---------------------------------------------------------------- utilidades
def _norm(texto):
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.split()).strip().lower()


def valor_para_float(texto):
    """'R$ 1.234,56' -> 1234.56 · devolve None se não for número."""
    import re

    if texto is None:
        return None
    if isinstance(texto, (int, float)):
        return float(texto)
    bruto = re.sub(r"(?i)r\$", "", str(texto)).strip()
    achado = re.search(r"-?\d[\d.,\s]*", bruto)
    if not achado:
        return None
    num = achado.group(0).replace(" ", "").rstrip(".,")
    negativo = num.startswith("-")
    num = num.lstrip("-")
    if "," in num and "." in num:
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif "," in num:
        num = num.replace(",", ".")
    else:
        partes = num.split(".")
        if len(partes) > 1 and len(partes[-1]) in (1, 2):
            num = "".join(partes[:-1]) + "." + partes[-1]
        else:
            num = num.replace(".", "")
    try:
        valor = float(num)
    except ValueError:
        return None
    return -valor if negativo else valor


def dominio_de(url):
    from urllib.parse import urlparse

    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    host = (urlparse(url).netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


# ---------------------------------------------------------------- config
class NuvemIndisponivel(Exception):
    """Sem configuração ou sem rede — o saldos.py cai no modo offline."""


def carregar_config(pasta):
    from pathlib import Path

    caminho = Path(pasta) / ARQUIVO_CONFIG
    if not caminho.exists():
        raise NuvemIndisponivel(
            f"Não achei o {ARQUIVO_CONFIG} nesta pasta. "
            "Crie o arquivo com supabase_url e supabase_key para ligar o painel."
        )
    try:
        with open(caminho, encoding="utf-8") as arquivo:
            cfg = json.load(arquivo)
    except Exception as e:
        raise NuvemIndisponivel(f"{ARQUIVO_CONFIG} inválido: {e}")

    url = (cfg.get("supabase_url") or "").rstrip("/")
    chave = cfg.get("supabase_key") or ""
    if not url.startswith("http") or not chave or "COLE" in chave.upper():
        raise NuvemIndisponivel(
            f"Preencha supabase_url e supabase_key no {ARQUIVO_CONFIG}."
        )
    return {"url": url, "key": chave}


# ---------------------------------------------------------------- REST
def _pedir(cfg, caminho, metodo="GET", corpo=None, extras=None):
    url = f"{cfg['url']}/rest/v1/{caminho}"
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    cabecalhos = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
        "Content-Type": "application/json",
    }
    cabecalhos.update(extras or {})
    req = urllib.request.Request(url, data=dados, method=metodo, headers=cabecalhos)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resposta:
            texto = resposta.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode("utf-8", "replace")[:300]
        raise NuvemIndisponivel(f"Supabase respondeu {e.code}: {detalhe}")
    except Exception as e:
        raise NuvemIndisponivel(f"Não consegui falar com o Supabase: {e}")
    if not texto.strip():
        return None
    try:
        return json.loads(texto)
    except Exception:
        return texto


def baixar_estado(cfg):
    """Devolve (user_id, data). O painel é pessoal: existe uma linha só."""
    linhas = _pedir(cfg, "app_state?select=user_id,data,updated_at,updated_by")
    if not linhas:
        raise NuvemIndisponivel(
            "A tabela app_state está vazia — abra o painel uma vez para ele criar a linha."
        )
    linha = linhas[0]
    dados = linha.get("data") or {}
    if not isinstance(dados.get("houses"), list):
        dados["houses"] = []
    return linha.get("user_id"), dados


def enviar_estado(cfg, user_id, dados):
    """Grava o estado editado de volta. `updated_by` acorda o painel aberto."""
    corpo = {
        "data": dados,
        "updated_by": "saldos",
        "updated_at": datetime.now().astimezone().isoformat(),
    }
    _pedir(
        cfg,
        f"app_state?user_id=eq.{user_id}",
        metodo="PATCH",
        corpo=corpo,
        extras={"Prefer": "return=minimal"},
    )
    return True


# ---------------------------------------------------------------- casas
def chave_usuario(valor):
    """Texto do campo `usuario` (ou nome de perfil) -> chave canônica."""
    chave = _norm(valor)
    return ALIASES_CHAVE.get(chave, chave)


def usuario_do_perfil(perfil):
    """Nome legível do perfil (o que aparece no painel)."""
    if isinstance(perfil, dict):
        if perfil.get("usuario_painel"):
            return perfil["usuario_painel"]
        nome = perfil.get("nome")
    else:
        nome = perfil
    return str(nome or "Você")


def chave_do_perfil(perfil):
    """Chave usada para casar o perfil do Opera com as casas do painel."""
    if isinstance(perfil, dict) and perfil.get("usuario_painel") is not None:
        return chave_usuario(perfil["usuario_painel"])
    return chave_usuario(perfil.get("nome") if isinstance(perfil, dict) else perfil)


def acao_da_casa(casa):
    """
    Mesma regra do painel: compara o saldo com quanto você quer deixar ali.
    Devolve ("sacar" | "depositar" | None, quanto).
    """
    if (casa.get("status") or "ativa") in ("encerrada", "observar"):
        return None, 0.0
    deixar = valor_para_float(casa.get("deixar")) or 0.0
    if deixar <= 0:
        return None, 0.0          # sem meta definida não há o que cobrar
    saldo = valor_para_float(casa.get("saldo")) or 0.0
    dif = saldo - deixar
    if dif > 0.5:
        return "sacar", round(dif, 2)
    if dif < -0.5:
        return "depositar", round(-dif, 2)
    return None, 0.0


def classificar_casa(casa):
    """
    ativa      -> tem dinheiro, entra na varredura por padrão
    sem_link   -> sem endereço cadastrado: não dá para varrer
    zerada     -> saldo e rolando zerados: conta só registrada, fica de fora
    nova       -> cadastrada no painel e ainda não verificada: fica de fora,
                  mas aparece destacada para você incluir
    excluida   -> você marcou "não verificar" no painel
    encerrada  -> conta encerrada, nunca entra
    """
    if (casa.get("status") or "ativa") == "encerrada":
        return "encerrada"
    if not (casa.get("link") or "").strip():
        # sem endereço o scanner não sabe onde ir; some da varredura até
        # você preencher o link no painel
        return "sem_link"
    if casa.get("verificarSaldo") is False:
        return "excluida"
    if casa.get("novaCasa") or not casa.get("verificadoEm"):
        return "nova"
    # o painel pode ter saldo como texto ("1.234,56") se veio de planilha;
    # float() puro explodia e derrubava a lista inteira do perfil.
    # `rolando` saiu da conta: apostas em aberto agora são um número único
    # vindo do Shark Track, não um campo por casa.
    saldo = valor_para_float(casa.get("saldo")) or 0.0
    if abs(saldo) < 0.005:
        return "zerada"
    return "ativa"


def casas_do_perfil(dados, perfil, incluir_encerradas=False):
    """
    Lista as casas daquele perfil, já classificadas e ordenadas por nome.
    Os dicts devolvidos são os MESMOS objetos de dados["houses"], então
    editá-los aqui reflete no que será enviado de volta.
    """
    alvo = chave_do_perfil(perfil)
    saida = []
    for casa in dados.get("houses") or []:
        if chave_usuario(casa.get("usuario")) != alvo:
            continue
        tipo = classificar_casa(casa)
        if tipo == "encerrada" and not incluir_encerradas:
            continue
        acao, quanto = acao_da_casa(casa)
        saida.append(
            {
                "casa_id": casa.get("id"),
                "nome": casa.get("nome") or "",
                "usuario": casa.get("usuario") or "",
                "link": casa.get("link") or "",
                "dominio": dominio_de(casa.get("link")),
                "saldo_anterior": valor_para_float(casa.get("saldo")) or 0.0,
                "rolando": valor_para_float(casa.get("rolando")) or 0.0,
                "deixar": valor_para_float(casa.get("deixar")) or 0.0,
                "verificado_em": casa.get("verificadoEm") or "",
                "limitada": bool(casa.get("limitada")),
                "stake_max": valor_para_float(casa.get("stakeMax")) or 0.0,
                "tipo": tipo,
                "acao": acao,
                "quanto": quanto,
                "_ref": casa,
            }
        )
    saida.sort(key=lambda c: _norm(c["nome"]))
    return saida


def contar_por_tipo(casas):
    contagem = {"ativa": 0, "zerada": 0, "nova": 0, "excluida": 0, "sem_link": 0}
    for casa in casas:
        contagem[casa["tipo"]] = contagem.get(casa["tipo"], 0) + 1
    return contagem


def _registrar_historico(casa):
    historico = casa.get("historico")
    if not isinstance(historico, list):
        historico = []
        casa["historico"] = historico
    hoje = date.today().isoformat()
    if historico and historico[-1].get("data") == hoje:
        historico[-1]["saldo"] = casa.get("saldo")
    else:
        historico.append({"data": hoje, "saldo": casa.get("saldo")})
    while len(historico) > 24:
        historico.pop(0)


def _id_curto():
    import random
    import string

    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))


def registrar_movimentos(dados, resultados):
    """
    Lança os depósitos/saques que você marcou durante a varredura.

    Sem isso, sacar R$ 800 de uma casa apareceria no painel como prejuízo de
    R$ 800 — o cálculo de resultado real depende dessas linhas.
    """
    movs = dados.setdefault("movimentacoes", [])
    if not isinstance(movs, list):
        movs = dados["movimentacoes"] = []
    por_id = {c.get("id"): c for c in dados.get("houses") or []}
    operacional = ((dados.get("settings") or {}).get("instituicaoOperacional")
                   or "Conta operacional")
    hoje = date.today().isoformat()
    criados = []

    for item in resultados:
        mov = item.get("movimento")
        casa = por_id.get(item.get("casa_id"))
        if not mov or casa is None:
            continue
        valor = round(abs(float(mov.get("valor") or 0)), 2)
        if valor < 0.005:
            continue
        deposito = mov.get("tipo") == "deposito_casa"
        chave = f"{hoje}|{casa.get('id')}|{valor:.2f}|{mov.get('tipo')}"
        if any(m.get("origemVarredura") == chave for m in movs):
            continue        # já lançado (reenvio da mesma varredura)
        movs.append({
            "id": _id_curto(),
            "data": hoje,
            "tipo": mov.get("tipo"),
            "casaId": casa.get("id"),
            "casaNome": casa.get("nome"),
            "usuario": casa.get("usuario") or "",
            "valor": valor if deposito else -valor,
            "contaOrigem": operacional if deposito else casa.get("nome"),
            "contaDestino": casa.get("nome") if deposito else operacional,
            "notas": "registrado na varredura",
            "origemVarredura": chave,
        })
        criados.append({"nome": casa.get("nome"), "tipo": mov.get("tipo"), "valor": valor})
    return criados


def aplicar_resultados(dados, resultados):
    """
    Escreve os saldos lidos nas casas correspondentes de `dados`.
    Devolve a lista de mudanças: [{nome, antes, depois, diferenca}, ...]
    Casas puladas ou sem valor não são tocadas.
    """
    por_id = {c.get("id"): c for c in dados.get("houses") or []}
    hoje = date.today().isoformat()
    mudancas = []

    for item in resultados:
        casa = por_id.get(item.get("casa_id"))
        if casa is None:
            continue
        novo = valor_para_float(item.get("saldo"))
        if novo is None:
            continue
        antes = valor_para_float(casa.get("saldo")) or 0.0
        casa["saldo"] = round(novo, 2)
        casa["verificadoEm"] = hoje
        casa["novaCasa"] = False
        _registrar_historico(casa)
        mudancas.append(
            {
                "nome": casa.get("nome"),
                "usuario": casa.get("usuario") or "",
                "antes": antes,
                "depois": round(novo, 2),
                "diferenca": round(novo - antes, 2),
            }
        )
    return mudancas


# ---------------------------------------------------------------- profiles.json
def atualizar_profiles_json(pasta, dados, arquivo=None):
    """
    Reescreve o profiles.json com as casas que existem hoje no painel.

    - `casas` continua sendo uma lista de domínios (o app.py depende disso);
    - `casas_painel` guarda a versão completa (id, nome, link, saldo), que o
      saldos.py usa quando está sem internet;
    - perfis já existentes mantêm a porta configurada, e nada é apagado se o
      painel não tiver casas daquele perfil.

    Devolve um resumo: {"perfil": {"novas": [...], "total": n}}
    """
    from pathlib import Path

    caminho = Path(arquivo) if arquivo else Path(pasta) / "profiles.json"
    if not caminho.exists():
        raise FileNotFoundError(f"Não achei {caminho}")

    with open(caminho, encoding="utf-8") as arq:
        perfis = json.load(arq)

    resumo = {}
    for perfil in perfis:
        casas = casas_do_perfil(dados, perfil)
        if not casas:
            continue
        antigos = list(perfil.get("casas") or [])
        vistos = {_norm(d) for d in antigos}
        completas, novas = [], []
        for casa in casas:
            dominio = casa["dominio"]
            if dominio and _norm(dominio) not in vistos:
                vistos.add(_norm(dominio))
                antigos.append(dominio)
                novas.append(casa["nome"])
            completas.append(
                {
                    "casa_id": casa["casa_id"],
                    "nome": casa["nome"],
                    "link": casa["link"],
                    "dominio": dominio,
                    "saldo_anterior": casa["saldo_anterior"],
                    "limitada": casa.get("limitada", False),
                    "stake_max": casa.get("stake_max", 0.0),
                    "tipo": casa["tipo"],
                }
            )
        perfil["usuario_painel"] = (casas[0].get("usuario") or "").strip() or usuario_do_perfil(perfil)
        # `casas` é a lista que o app.py usa para saber de quem é cada link:
        # só cresce, nunca perde domínio que você já tinha registrado ali.
        perfil["casas"] = sorted(antigos, key=_norm)
        perfil["casas_painel"] = completas
        resumo[perfil.get("nome", "?")] = {"novas": novas, "total": len(completas)}

    with open(caminho, "w", encoding="utf-8") as arq:
        json.dump(perfis, arq, ensure_ascii=False, indent=2)
    return resumo


# ---------------------------------------------------------------- linha de comando
if __name__ == "__main__":
    import argparse
    from pathlib import Path

    PASTA = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Ferramentas da ponte com o painel (Supabase)."
    )
    parser.add_argument("--listar", metavar="PERFIL", nargs="?", const="__todos__",
                        help="Mostra as casas do painel (opcionalmente de um perfil)")
    parser.add_argument("--sincronizar-profiles", action="store_true",
                        help="Atualiza o profiles.json com as casas do painel")
    args = parser.parse_args()

    try:
        cfg = carregar_config(PASTA)
        _uid, estado = baixar_estado(cfg)
    except NuvemIndisponivel as e:
        print(f"Nuvem indisponível: {e}")
        raise SystemExit(1)

    if args.sincronizar_profiles:
        resumo = atualizar_profiles_json(PASTA, estado)
        for nome, info in resumo.items():
            marca = f" · novas: {', '.join(info['novas'])}" if info["novas"] else ""
            print(f"{nome:<12} {info['total']} casas{marca}")
        raise SystemExit(0)

    if args.listar:
        perfis_alvo = ([args.listar] if args.listar != "__todos__"
                       else sorted({c.get("usuario") or "Você"
                                    for c in estado.get("houses") or []}))
        for nome in perfis_alvo:
            casas = casas_do_perfil(estado, {"nome": nome})
            contagem = contar_por_tipo(casas)
            print(f"\n{nome} — {len(casas)} casas  {contagem}")
            for casa in casas:
                print(f"  [{casa['tipo']:<8}] {casa['nome']:<20} "
                      f"R$ {casa['saldo_anterior']:>10,.2f}  {casa['dominio']}")
        raise SystemExit(0)

    print("Conectado. Use --listar ou --sincronizar-profiles.")
