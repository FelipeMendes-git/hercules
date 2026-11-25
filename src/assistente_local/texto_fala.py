"""Prepara as respostas do Claude para voz e descreve as ações dele em português."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path, PurePath
from urllib.parse import unquote, urlparse

_TAG_FALA = re.compile(r"<falar>(.*?)</falar>", re.IGNORECASE | re.DOTALL)
_TAG_SOLTA = re.compile(r"</?falar>", re.IGNORECASE)


def extrair_fala(texto: str) -> tuple[str, str]:
    """Separa a linha ``<falar>...</falar>`` do resto.

    Retorna ``(fala, visivel)``: o que deve ser dito (já limpo para voz; vazio se o
    Claude não mandou a linha) e o texto para a tela, sem as marcações.
    """
    texto = texto or ""
    achados = _TAG_FALA.findall(texto)
    fala = limpar_para_fala(achados[-1]) if achados else ""
    visivel = _TAG_SOLTA.sub("", _TAG_FALA.sub("", texto)).strip()
    return fala, visivel


def sem_marcacao_de_fala(texto: str) -> str:
    return extrair_fala(texto)[1]


_BLOCO_CODIGO = re.compile(r"```.*?(?:```|\Z)", re.DOTALL)
_CODIGO_INLINE = re.compile(r"`([^`\n]*)`")
_IMAGEM = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"https?://[^\s)>\]]+")
_TITULO = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]*", re.MULTILINE)
_CITACAO = re.compile(r"^[ \t]*>[ \t]?", re.MULTILINE)
_MARCADOR = re.compile(r"^[ \t]*(?:[-*+•]|\d{1,3}[.)])[ \t]+", re.MULTILINE)
_LINHA_TABELA = re.compile(r"^[ \t]*\|.*$", re.MULTILINE)
_REGUA = re.compile(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$", re.MULTILINE)
_ENFASE = re.compile(r"(\*\*|__|\*|~~)(?=\S)(.+?)(?<=\S)\1")
_CAMINHO = re.compile(r"(?<![\w/\\])(?:[A-Za-z]:)?[\\/]?(?:[\w.\-]+[\\/])+[\w.\-]+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]")


def _trocar_inline(casamento: re.Match[str]) -> str:
    conteudo = casamento.group(1).strip()
    if conteudo and len(conteudo) <= 30 and not re.search(r"[{}();=<>\[\]]", conteudo):
        return conteudo
    return "um trecho de código"


def _trocar_caminho(casamento: re.Match[str]) -> str:
    trecho = casamento.group()
    partes = [p for p in re.split(r"[\\/]", trecho) if p]
    if not partes:
        return trecho
    tem_drive = bool(re.match(r"[A-Za-z]:", trecho))
    tem_extensao = bool(re.search(r"\.[A-Za-z0-9]{1,6}$", partes[-1]))
    if len(partes) >= 3 or tem_drive or tem_extensao:
        return partes[-1]
    return trecho  # "e/ou", "km/h"


def limpar_para_fala(texto: str) -> str:
    """Tira de um texto em markdown o que não faz sentido em voz alta."""
    t = _BLOCO_CODIGO.sub(" ", texto or "")
    t = _LINHA_TABELA.sub(" ", t)
    t = _REGUA.sub(" ", t)
    t = _IMAGEM.sub(r"\1", t)
    t = _LINK.sub(r"\1", t)
    t = _URL.sub("um link", t)
    t = _CODIGO_INLINE.sub(_trocar_inline, t)
    t = _CAMINHO.sub(_trocar_caminho, t)
    t = _TITULO.sub("", t)
    t = _CITACAO.sub("", t)
    t = _MARCADOR.sub("", t)
    t = _ENFASE.sub(r"\2", t)
    t = _EMOJI.sub("", t)
    frases = []
    for linha in t.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        if linha[-1] not in ".!?:;,…":
            linha += "."
        frases.append(linha)
    t = " ".join(frases)
    t = re.sub(r"\s+([.,;:!?])", r"\1", t)
    t = re.sub(r"([.!?])(?:\s*\.)+", r"\1", t)
    return re.sub(r"\s{2,}", " ", t).strip()


_FIM_FRASE = re.compile(r"(?<=[.!?…])\s+")


def dividir_frases(texto: str, maximo: int = 220) -> list[str]:
    """Divide o texto em frases curtas, para a voz começar a falar mais cedo."""
    frases: list[str] = []
    for parte in _FIM_FRASE.split(texto or ""):
        parte = parte.strip()
        while len(parte) > maximo:
            corte = max(parte.rfind(", ", 0, maximo), parte.rfind("; ", 0, maximo))
            if corte <= maximo // 3:
                corte = parte.rfind(" ", 0, maximo)
            if corte <= 0:
                corte = maximo
            frases.append(parte[:corte].strip(" ,;"))
            parte = parte[corte:].strip(" ,;")
        if parte:
            frases.append(parte)
    return frases


def agrupar_frases(frases: list[str], minimo: int = 60, maximo: int = 220, maximo_primeiro: int = 100) -> list[str]:
    """Junta frases curtas com a seguinte, até ``minimo`` caracteres (sem passar de ``maximo``).

    Enquanto um trecho toca, o próximo é gerado. Se o trecho que toca é curto ("Pronto.", 0,7 s) e o
    próximo é longo, a voz para no meio esperando. Trechos muito curtos também saem piores no Kokoro.
    O primeiro trecho fica em até ``maximo_primeiro``, para a voz começar logo.
    """
    grupos: list[str] = []
    for frase in frases:
        limite = maximo_primeiro if len(grupos) == 1 else maximo
        if grupos and len(grupos[-1]) < minimo and len(grupos[-1]) + 1 + len(frase) <= limite:
            grupos[-1] = f"{grupos[-1]} {frase}"
        else:
            grupos.append(frase)
    return grupos


def resumo_falavel(texto: str, max_frases: int = 2, max_caracteres: int = 320) -> str:
    """Quando o Claude não manda a linha ``<falar>``: as primeiras frases, limpas para voz."""
    frases = dividir_frases(limpar_para_fala(texto))
    resumo = ""
    usadas = 0
    for frase in frases[:max_frases]:
        if resumo and len(resumo) + len(frase) > max_caracteres:
            break
        resumo = f"{resumo} {frase}".strip()
        usadas += 1
    if resumo and usadas < len(frases):
        resumo += " Os detalhes estão na tela."
    return resumo


_CODIGO_EM_LINHA = re.compile(r"`([^`\n]+)`")
_CAMINHO_ABSOLUTO = re.compile(r"(?<![\w`])[A-Za-z]:[\\/][^\s<>\"|?*`'()\[\]{}]*")
_LINK_DE_ARQUIVO = re.compile(r"\]\((file:///[^)\s]+)\)")


def encontrar_caminhos(texto: str, base: str | None = None, limite: int = 10) -> list[str]:
    """Arquivos e pastas que existem de verdade e foram citados no texto.

    Olha o que está entre crases (aceita espaços e caminhos relativos ao projeto), caminhos
    absolutos soltos no texto (C:\\...) e links ``file:///``. Devolve caminhos absolutos.
    """
    texto = texto or ""
    candidatos = [m.group(1) for m in _CODIGO_EM_LINHA.finditer(texto)]
    candidatos += [m.group().rstrip(".,;:!?") for m in _CAMINHO_ABSOLUTO.finditer(texto)]
    candidatos += [unquote(urlparse(m.group(1)).path).lstrip("/") for m in _LINK_DE_ARQUIVO.finditer(texto)]
    achados: list[str] = []
    vistos: set[str] = set()
    for candidato in candidatos:
        candidato = candidato.strip().strip("\"'")
        if not candidato or len(candidato) > 400:
            continue
        caminho = Path(candidato)
        if not caminho.is_absolute():
            # Palavras soltas entre crases (comandos, nomes) não são caminhos.
            if not base or not re.search(r"[\\/.]", candidato) or " " in candidato.strip():
                continue
            caminho = Path(base) / candidato
        try:
            if not caminho.exists():
                continue
            absoluto = str(caminho.resolve())
        except (OSError, ValueError):
            continue
        chave = os.path.normcase(absoluto)
        if chave not in vistos:
            vistos.add(chave)
            achados.append(absoluto)
            if len(achados) >= limite:
                break
    return achados


def _nome_arquivo(entrada: dict) -> str:
    for chave in ("file_path", "notebook_path", "path"):
        valor = entrada.get(chave)
        if isinstance(valor, str) and valor:
            return PurePath(valor.replace("\\", "/")).name or valor
    return ""


def _caminho(entrada: dict) -> str:
    for chave in ("file_path", "notebook_path", "path"):
        valor = entrada.get(chave)
        if isinstance(valor, str) and valor:
            return valor
    return ""


# Ferramentas de terminal do Claude Code (no Windows ele costuma usar o PowerShell).
FERRAMENTAS_DE_COMANDO = ("Bash", "PowerShell")


def descrever_ferramenta(nome: str, entrada: dict) -> tuple[str, str]:
    """Descreve uma ação do Claude: ``(frase curta para falar, detalhe para a tela)``."""
    arquivo = _nome_arquivo(entrada) or "um arquivo"
    if nome == "Read":
        return f"Lendo {arquivo}.", f"Lendo {_caminho(entrada) or arquivo}"
    if nome == "Write":
        return f"Criando {arquivo}.", f"Escrevendo {_caminho(entrada) or arquivo}"
    if nome in ("Edit", "MultiEdit"):
        return f"Editando {arquivo}.", f"Editando {_caminho(entrada) or arquivo}"
    if nome == "NotebookEdit":
        return "Editando o notebook.", f"Editando {_caminho(entrada) or 'o notebook'}"
    if nome in FERRAMENTAS_DE_COMANDO:
        comando = " ".join(str(entrada.get("command", "")).split())
        return "Rodando um comando.", f"Rodando: {comando[:240]}"
    if nome == "ToolSearch":
        return "Buscando a ferramenta certa.", "Buscando a ferramenta certa"
    if nome == "Skill":
        habilidade = str(entrada.get("skill", "")).strip()
        return "Usando uma habilidade.", f"Usando a habilidade {habilidade}".strip()
    if nome in ("TaskCreate", "TaskUpdate", "TaskList", "TaskGet"):
        return "Organizando as tarefas.", "Atualizando a lista de tarefas"
    if nome in ("Glob", "Grep"):
        return "Procurando nos arquivos.", f"Procurando: {entrada.get('pattern', '')}"
    if nome == "WebSearch":
        return "Pesquisando na internet.", f"Pesquisando: {entrada.get('query', '')}"
    if nome == "WebFetch":
        url = str(entrada.get("url", ""))
        return f"Abrindo {urlparse(url).netloc or 'uma página'}.", f"Abrindo {url}"
    if nome in ("Task", "Agent"):
        return "Delegando uma parte do trabalho.", f"Subtarefa: {entrada.get('description', '')}"
    if nome == "TodoWrite":
        return "Organizando as tarefas.", "Atualizando a lista de tarefas"
    if nome.startswith("mcp__app__"):
        acao = nome.removeprefix("mcp__app__")
        detalhes = {
            "listar_projetos": "Vendo os projetos",
            "trocar_projeto": f"Trocando para o projeto {entrada.get('projeto', '')}".strip(),
            "nova_conversa": "Começando uma conversa nova",
            "copiar": "Copiando para a área de transferência",
            "abrir": f"Abrindo {entrada.get('caminho', '')}".strip(),
            "desfazer": "Desfazendo as alterações do último pedido",
            "ajustar_claude": "Ajustando o esforço e o modelo do Claude",
            "ver_tela": "Olhando a sua tela",
        }
        detalhe = detalhes.get(acao, f"Usando a ferramenta do app {acao}")
        return f"{detalhe}.", detalhe
    if nome.startswith("mcp__"):
        partes = nome.split("__")
        servidor = partes[1] if len(partes) > 2 else ""
        return "Usando uma ferramenta externa.", f"Ferramenta {servidor}: {partes[-1]}".replace(" :", ":")
    return f"Usando {nome}.", f"Usando {nome}"


_COMANDO_COMPLICADO = re.compile(r"[|&;<>$`\\\"']")


def descrever_pedido(nome: str, entrada: dict) -> tuple[str, str]:
    """Descreve um pedido de permissão: ``(trecho que completa "Posso ...?", detalhe para a tela)``."""
    arquivo = _nome_arquivo(entrada) or "um arquivo"
    if nome in FERRAMENTAS_DE_COMANDO:
        comando = " ".join(str(entrada.get("command", "")).split())
        if comando and len(comando) <= 48 and not _COMANDO_COMPLICADO.search(comando):
            return f"rodar o comando {comando}", comando
        return "rodar um comando no terminal", comando
    if nome == "Write":
        return f"criar o arquivo {arquivo}", _caminho(entrada)
    if nome in ("Edit", "MultiEdit", "NotebookEdit"):
        return f"editar o arquivo {arquivo}", _caminho(entrada)
    if nome == "WebFetch":
        url = str(entrada.get("url", ""))
        return f"abrir o site {urlparse(url).netloc or 'pedido'}", url
    if nome == "WebSearch":
        return "pesquisar na internet", str(entrada.get("query", ""))
    detalhe = json.dumps(entrada, ensure_ascii=False)[:500]
    if nome.startswith("mcp__"):
        return f"usar a ferramenta {nome.split('__')[-1]}", detalhe
    return f"usar a ferramenta {nome}", detalhe
