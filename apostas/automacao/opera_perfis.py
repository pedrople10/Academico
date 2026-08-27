"""
Perfis do Opera — substitui a Local API do AdsPower.

O AdsPower cobra pela Local API que devolve a "porta de depuração" (debug
port) de um perfil já aberto. O Opera não tem esse serviço, mas não precisa:
ele é Chromium por baixo, então basta abrir cada perfil com sua própria
pasta de dados (`--user-data-dir`) e sua própria porta fixa
(`--remote-debugging-port`) que o resto do sistema (app.py, saldos.py) fala
com ele exatamente como falava com o AdsPower — mesmo protocolo (CDP).

O que isso NÃO faz, diferente de um antidetect de verdade:
  - não troca fingerprint (canvas, fontes, WebGL, etc.) entre perfis;
  - sem um `proxy` configurado, todos os perfis saem pelo mesmo IP da sua casa.
Cada perfil aqui é só "um Opera separado, com cookies e login próprios" —
o suficiente pra não misturar sessão de conta, mas não uma camada
anti-fraude. Veja o aviso no README antes de usar em várias casas.

Uso típico (chamado pelo app.py e pelo saldos.py, não direto):
    from opera_perfis import abrir_perfil
    porta, erro = abrir_perfil(perfil)   # perfil = item do profiles.json
"""

import json
import os
import platform
import shutil
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path

PASTA_PERFIS = Path(__file__).parent / "perfis-opera"
TIMEOUT_PORTA = 1.5          # checar se a porta já responde
TIMEOUT_ABERTURA = 25        # esperar o Opera abrir do zero


def _candidatos_windows():
    base = [os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", "")]
    nomes = ["Opera\\launcher.exe", "Opera GX\\launcher.exe"]
    return [str(Path(b) / n) for b in base if b for n in nomes]


def _candidatos_mac():
    return [
        "/Applications/Opera.app/Contents/MacOS/Opera",
        "/Applications/Opera GX.app/Contents/MacOS/Opera",
        str(Path.home() / "Applications/Opera.app/Contents/MacOS/Opera"),
    ]


def _candidatos_linux():
    return ["/usr/bin/opera", "/usr/bin/opera-stable", "/snap/bin/opera"]


def localizar_opera():
    """
    Acha o executável do Opera. Ordem: variável de ambiente OPERA_PATH,
    `opera`/`opera.exe` no PATH, depois os caminhos de instalação padrão.
    """
    env = os.environ.get("OPERA_PATH")
    if env and Path(env).exists():
        return env

    achou = shutil.which("opera") or shutil.which("opera.exe") or shutil.which("launcher.exe")
    if achou:
        return achou

    sistema = platform.system()
    candidatos = (_candidatos_windows() if sistema == "Windows"
                  else _candidatos_mac() if sistema == "Darwin"
                  else _candidatos_linux())
    for c in candidatos:
        if Path(c).exists():
            return c
    return None


def pasta_do_perfil(perfil):
    """
    Cada perfil tem sua própria pasta de dados — é isso que separa cookies e
    login de um perfil para o outro. Nome customizável via `perfil["pasta"]`;
    por padrão usa o nome do perfil (sanitizado).
    """
    nome = str(perfil.get("pasta") or perfil.get("nome") or "perfil")
    seguro = "".join(c if c.isalnum() or c in "-_ " else "_" for c in nome).strip() or "perfil"
    return PASTA_PERFIS / seguro


def porta_responde(porta, timeout=TIMEOUT_PORTA):
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{porta}/json/version", timeout=timeout
        ) as resp:
            return resp.status == 200
    except Exception:
        return False


def abrir_perfil(perfil, timeout_abertura=TIMEOUT_ABERTURA):
    """
    Garante que o perfil está aberto no Opera e devolve (porta, erro).

    - Se a porta já responde (você abriu manualmente, ou uma chamada
      anterior já abriu), devolve na hora — igual ao AdsPower quando o
      perfil já estava ativo.
    - Senão, lança o Opera com essa porta e essa pasta de dados, e espera
      até `timeout_abertura` segundos ele ficar pronto.
    """
    porta = perfil.get("porta")
    if not porta:
        return None, "campo 'porta' ausente no profiles.json (veja o README)"
    porta = int(porta)

    if porta_responde(porta):
        return porta, None

    exe = localizar_opera()
    if not exe:
        return None, ("não achei o Opera instalado — defina a variável de "
                       "ambiente OPERA_PATH com o caminho do executável")

    pasta = pasta_do_perfil(perfil)
    pasta.mkdir(parents=True, exist_ok=True)

    args = [
        exe,
        f"--remote-debugging-port={porta}",
        f"--user-data-dir={pasta}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
    ]
    proxy = (perfil.get("proxy") or "").strip()
    if proxy:
        # host:porta, sem usuário/senha (Chromium não aceita credenciais aqui;
        # para proxy autenticado, veja a nota no README sobre extensão/local forward)
        args.append(f"--proxy-server={proxy}")
    args.append("about:blank")

    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        return None, f"falha ao abrir o Opera: {e}"

    limite = time.time() + timeout_abertura
    while time.time() < limite:
        if porta_responde(porta):
            return porta, None
        time.sleep(0.5)
    return None, f"o Opera não respondeu na porta {porta} a tempo"


if __name__ == "__main__":
    exe = localizar_opera()
    print(f"Opera encontrado em: {exe}" if exe else
          "Opera não encontrado — defina OPERA_PATH ou instale o Opera.")
    print(f"Pasta de perfis: {PASTA_PERFIS}")
