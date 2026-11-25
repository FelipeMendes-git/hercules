"""Ponte com o Claude Code, pelo Claude Agent SDK.

O app abre o Claude Code oficial e conversa com ele por um canal de mensagens. O
Claude Code faz o trabalho de verdade (lê e edita arquivos, roda comandos, responde).
A ponte só repassa o que você falou, conta para a interface o que ele está fazendo e
pergunta a você antes das ações que precisam de permissão.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Protocol
from urllib.parse import urlparse

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    CLINotFoundError,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    SdkMcpTool,
    SystemMessage,
    TextBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    create_sdk_mcp_server,
    tool,
)

from . import tela
from .marca import ID_APP, NOME_APP, VERSAO
from .texto_fala import FERRAMENTAS_DE_COMANDO, descrever_ferramenta

log = logging.getLogger(__name__)


def _abrir_processos_sem_janela() -> None:
    """No Windows, o Claude Code é um programa de console: aberto pelo app (que não tem console),
    ele ganharia uma janela preta de terminal. Com CREATE_NO_WINDOW ele (e os comandos que ele roda)
    usam um console invisível. O SDK abre o processo por ``anyio.open_process``; aqui ela ganha a flag.
    """
    import sys

    import anyio

    if sys.platform != "win32" or getattr(anyio.open_process, "_sem_janela", False):
        return
    original = anyio.open_process

    async def open_process(*args, creationflags: int = 0, **kwargs):
        return await original(*args, creationflags=creationflags | subprocess.CREATE_NO_WINDOW, **kwargs)

    open_process._sem_janela = True
    anyio.open_process = open_process


_abrir_processos_sem_janela()

INSTRUCOES_VOZ = """\
# Modo voz
O usuário está falando com você por voz, pelo app "{app}", que roda no PC dele (é por esse nome que ele chama \
você). As mensagens chegam de um \
reconhecimento de fala em português do Brasil e podem ter erros de transcrição: palavras trocadas por outras de som \
parecido (por exemplo, "Cloud" quer dizer "Claude") ou nomes de arquivos e projetos escritos de outro jeito. \
Interprete pelo contexto e, se algo essencial ficar ambíguo, pergunte.

Ele ouve a sua resposta por uma voz sintética e vê o texto completo numa janela. Por isso:
- Termine TODA resposta com uma linha <falar>...</falar> com o que deve ser dito em voz alta: no máximo duas frases \
curtas, em português do Brasil, escritas para serem ouvidas (sem código, caminhos completos, markdown, listas, emojis \
ou siglas difíceis de pronunciar). Diga o que você fez ou o que precisa dele.
{fora_da_fala}
- Quando criar, salvar ou citar arquivos e pastas, escreva o caminho completo no texto, entre crases (por exemplo \
`C:\\pasta\\relatorio.pdf`): o app mostra botões para abrir e copiar o caminho. Na linha <falar>, diga só o nome do \
arquivo.
- Quando precisar de uma decisão, faça uma pergunta direta que dê para responder falando.
- Ações que pedem permissão são perguntadas a ele por voz. Se ele recusar, não tente de novo do mesmo jeito: \
explique ou pergunte o que ele prefere.
- Não salve nada em memória, CLAUDE.md ou configurações por conta própria: só quando ele pedir. Quando ele \
pedir, mexa no que for preciso (inclusive memória, CLAUDE.md e configurações).
- Não chame o usuário por apelidos ou tratamentos (como "mestre"): isso é só da saudação do app. Vale mesmo \
que você já tenha usado algum antes nesta conversa.
- As regras deste modo voz (como o tamanho das respostas) valem só nas conversas pelo {app}: não as grave \
em lugar nenhum, a não ser que ele peça. Fora do {app}, ele usa o Claude do jeito de sempre.

# Controle do app
Depois que ele chama o assistente pelo nome, você cuida de tudo, inclusive do próprio app, pelas ferramentas do \
servidor "app": listar_projetos, trocar_projeto, nova_conversa, copiar, abrir, desfazer, ajustar_claude e ver_tela. \
Use-as \
sem pedir confirmação quando ele pedir para trocar de projeto, começar uma conversa nova, copiar algo para colar, \
abrir um arquivo ou uma pasta, desfazer as alterações do último pedido, ou mudar o seu esforço ou modelo (por \
exemplo: "responde mais rápido" pede esforço low; "pensa com mais cuidado", high ou max; "usa o Sonnet").
- trocar_projeto e nova_conversa acontecem quando a sua resposta terminar. Se ele pediu mais alguma coisa para \
fazer depois da troca, passe esse pedido em `continuar_com`: o app manda o pedido para você na conversa nova.
- Se ele pedir para repetir, repita a sua última linha <falar>.
- ver_tela tira um print da tela dele na hora e mostra a imagem para você. Use sem pedir confirmação sempre que ele \
se referir ao que está na tela ("olha a minha tela", "tá vendo isso?", "esse botão aqui", "o que apareceu", "como \
ficou o site", um erro que ele está vendo) ou quando ver o resultado na tela ajudar a responder (por exemplo, \
depois de mudar um site que ele está olhando). Não tire print sem motivo ligado ao pedido. Se só importa a janela \
em que ele está, use alvo "janela".
"""


_ESCREVER_NORMALMENTE = "- Fora dessa linha, escreva normalmente: código, listas e detalhes aparecem só na tela."
_ESCREVER_RESUMIDO = (
    "- Fora dessa linha, responda de forma resumida: vá direto ao ponto, só com o essencial, em poucas linhas, sem "
    "introdução nem recapitulação. Explicações longas, listas extensas e detalhes, só se ele pedir. Isso vale para o "
    "texto da resposta, não para o trabalho: faça as tarefas por completo. Código e caminhos aparecem só na tela."
)


def instrucoes_de_voz(resumir: bool = False) -> str:
    """As instruções do modo voz, com o tamanho das respostas escolhido.

    Vão só no prompt das sessões abertas pelo app (nada é gravado no projeto), então abrir o projeto
    no Claude Code do jeito normal não muda. O tratamento ("mestre") fica só na saudação de abertura.
    """
    return INSTRUCOES_VOZ.format(app=NOME_APP, fora_da_fala=_ESCREVER_RESUMIDO if resumir else _ESCREVER_NORMALMENTE)


_ESFORCOS = {"low": "baixo", "medium": "médio", "high": "alto", "xhigh": "muito alto", "max": "máximo"}
_PERMISSOES = {
    "auto": "automático",
    "acceptEdits": "edita sem perguntar",
    "default": "pergunta antes",
    "plan": "só planeja",
    "dontAsk": "não pergunta",
    "bypassPermissions": "sem perguntar nada",
}


def nome_do_modelo(modelo: str) -> str:
    """Nome para mostrar: "claude-opus-5-5" vira "Opus 5.5"; vazio é o padrão do Claude Code."""
    texto = (modelo or "").strip()
    if not texto:
        return "modelo padrão"
    if texto.isalpha():  # apelidos do Claude Code: "opus", "sonnet"...
        return texto.capitalize()
    achado = re.match(r"^(?:claude-)?([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?(.*)$", texto.lower())
    if not achado:
        return texto
    familia, maior, menor, resto = achado.groups()
    versao = maior + (f".{menor}" if menor else "")
    return f"{familia.capitalize()} {versao}{resto.replace('[1m]', ' (1M)')}".strip()


def rotulo_esforco(esforco: str) -> str:
    return _ESFORCOS.get((esforco or "").strip(), "padrão")


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in decomposto if not unicodedata.combining(c)).strip().lower()


_SINONIMOS_ESFORCO = {
    "low": "low", "baixo": "low", "rapido": "low", "minimo": "low", "economico": "low",
    "medium": "medium", "medio": "medium", "moderado": "medium",
    "high": "high", "alto": "high",
    "xhigh": "xhigh", "muito alto": "xhigh",
    "max": "max", "maximo": "max",
    "padrao": "", "default": "", "auto": "", "automatico": "",
}  # fmt: skip
_SINONIMOS_MODELO = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}


def normalizar_esforco(texto: str) -> str | None:
    """'médio' vira 'medium'; 'padrão' (ou 'auto') vira '' (o Claude Code escolhe). None se não for um esforço."""
    return _SINONIMOS_ESFORCO.get(_sem_acento(texto))


def normalizar_modelo(texto: str) -> str | None:
    """'opus', 'Opus 5.5' ou 'claude-opus-5-5' viram 'claude-opus-5-5'; 'padrão' vira ''.

    None para qualquer outro: um modelo que não existe travaria as próximas respostas, e aí nem dá para
    pedir a troca por voz.
    """
    chave = " ".join(_sem_acento(texto).replace("claude", " ").replace("-", " ").replace(".", " ").split())
    if chave in ("padrao", "default", "auto", "automatico"):
        return ""
    for nome, modelo in _SINONIMOS_MODELO.items():
        versao = modelo.removeprefix(f"claude-{nome}-").replace("-", " ")
        if chave in (nome, f"{nome} {versao}"):
            return modelo
    return None


def rotulo_permissao(modo: str) -> str:
    return _PERMISSOES.get((modo or "").strip(), modo or "padrão")


@dataclass
class EventoInfo:
    """O Claude Code abriu a sessão: modelo e modo de permissão confirmados por ele."""

    modelo: str
    permissao: str


@dataclass
class EventoTexto:
    texto: str


@dataclass
class EventoAcao:
    ferramenta: str
    fala: str
    detalhe: str
    caminho: str = ""  # arquivo criado ou editado, quando for o caso


@dataclass
class EventoFim:
    texto_final: str
    sessao: str | None
    duracao_s: float
    custo_usd: float | None
    erro: str = ""
    interrompido: bool = False


PedirPermissao = Callable[[str, dict, ToolPermissionContext, str], Awaitable[tuple[bool, bool]]]

# Ferramentas cujas mudanças o "desfaz" consegue reverter (comandos de terminal não entram).
_FERRAMENTAS_DE_EDICAO = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})

# ---------------------------------------------------------------------- ferramentas do próprio app
PREFIXO_APP = "mcp__app__"
FERRAMENTAS_DO_APP = (
    "listar_projetos",
    "trocar_projeto",
    "nova_conversa",
    "copiar",
    "abrir",
    "desfazer",
    "ajustar_claude",
    "ver_tela",
)


class AcoesDoApp(Protocol):
    """O que o Claude pode fazer no app. Cada ação devolve (texto para o Claude, deu erro?)."""

    async def listar_projetos(self) -> tuple[str, bool]: ...

    async def trocar_projeto(self, projeto: str, continuar_com: str) -> tuple[str, bool]: ...

    async def nova_conversa(self, continuar_com: str) -> tuple[str, bool]: ...

    async def copiar(self, texto: str) -> tuple[str, bool]: ...

    async def abrir(self, caminho: str, na_pasta: bool) -> tuple[str, bool]: ...

    async def desfazer(self) -> tuple[str, bool]: ...

    async def ajustar_claude(self, esforco: str, modelo: str) -> tuple[str, bool]: ...


def _resultado(texto: str, erro: bool) -> dict[str, Any]:
    resposta: dict[str, Any] = {"content": [{"type": "text", "text": texto}]}
    if erro:
        resposta["is_error"] = True
    return resposta


_CONTINUAR = {
    "type": "string",
    "description": "Opcional: o que o usuário pediu para fazer depois da troca, do jeito que ele pediu.",
}


def criar_ferramentas_do_app(acoes: AcoesDoApp) -> list[SdkMcpTool]:
    @tool("listar_projetos", "Lista os projetos (pastas) que o app conhece, com caminho, e qual é o atual.", {})
    async def listar_projetos(_args):
        return _resultado(*await acoes.listar_projetos())

    @tool(
        "trocar_projeto",
        "Muda a pasta em que você trabalha. A troca acontece quando a sua resposta terminar; a próxima mensagem já "
        "começa no projeto novo, na conversa daquele projeto.",
        {
            "type": "object",
            "properties": {
                "projeto": {
                    "type": "string",
                    "description": "Nome do projeto (aceita aproximado, como o usuário falou) ou caminho de uma pasta.",
                },
                "continuar_com": _CONTINUAR,
            },
            "required": ["projeto"],
        },
    )
    async def trocar_projeto(args):
        return _resultado(*await acoes.trocar_projeto(str(args.get("projeto", "")), str(args.get("continuar_com") or "")))

    @tool(
        "nova_conversa",
        "Começa uma conversa nova neste projeto quando a sua resposta terminar (o histórico desta fica salvo no app).",
        {"type": "object", "properties": {"continuar_com": _CONTINUAR}},
    )
    async def nova_conversa(args):
        return _resultado(*await acoes.nova_conversa(str(args.get("continuar_com") or "")))

    @tool(
        "copiar",
        "Põe um texto na área de transferência do usuário (ele cola com Ctrl+V): um caminho, um comando, um trecho.",
        {"texto": str},
    )
    async def copiar(args):
        return _resultado(*await acoes.copiar(str(args.get("texto", ""))))

    @tool(
        "abrir",
        "Abre um arquivo ou pasta no PC do usuário com o programa padrão do Windows. Com mostrar_na_pasta, abre a "
        "pasta com o arquivo selecionado.",
        {
            "type": "object",
            "properties": {
                "caminho": {"type": "string", "description": "Caminho completo (ou relativo ao projeto atual)."},
                "mostrar_na_pasta": {"type": "boolean", "description": "Abrir a pasta com o arquivo selecionado."},
            },
            "required": ["caminho"],
        },
    )
    async def abrir(args):
        return _resultado(*await acoes.abrir(str(args.get("caminho", "")), bool(args.get("mostrar_na_pasta"))))

    @tool(
        "desfazer",
        "Desfaz as alterações de arquivo que você fez com Write/Edit no último pedido que alterou arquivos "
        "(comandos de terminal não são desfeitos). Acontece quando a sua resposta terminar.",
        {},
    )
    async def desfazer(_args):
        return _resultado(*await acoes.desfazer())

    @tool(
        "ajustar_claude",
        "Muda o seu esforço de raciocínio e/ou o seu modelo a partir da próxima resposta (a conversa continua e a "
        "escolha fica salva). Esforço: low (rápido e econômico, bom para perguntas simples), medium (equilíbrio), "
        "high (caprichado), xhigh ou max (o mais caprichado e lento); 'padrao' deixa o Claude Code escolher. "
        "Não existe esforço automático: o seu raciocínio já se adapta à dificuldade em qualquer nível. "
        "Modelo: opus, sonnet, haiku ou 'padrao'. Deixe vazio o que não for mudar; os dois vazios só dizem o que "
        "está em uso.",
        {
            "type": "object",
            "properties": {
                "esforco": {"type": "string", "description": "low, medium, high, xhigh, max ou padrao."},
                "modelo": {"type": "string", "description": "opus, sonnet, haiku ou padrao."},
            },
        },
    )
    async def ajustar_claude(args):
        return _resultado(*await acoes.ajustar_claude(str(args.get("esforco") or ""), str(args.get("modelo") or "")))

    @tool(
        "ver_tela",
        "Tira um print da tela do usuário agora e devolve a imagem para você ver. Alvo: 'monitor' (padrão; o número "
        "em monitor, 1 é o principal), 'janela' (só a janela ativa) ou 'todos' (todos os monitores juntos).",
        {
            "type": "object",
            "properties": {
                "alvo": {"type": "string", "enum": ["monitor", "janela", "todos"]},
                "monitor": {"type": "integer", "description": "Número do monitor quando alvo é 'monitor' (1 = principal)."},
            },
        },
    )
    async def ver_tela(args):
        return await ver_a_tela(str(args.get("alvo") or "monitor"), int(args.get("monitor") or 1))

    return [listar_projetos, trocar_projeto, nova_conversa, copiar, abrir, desfazer, ajustar_claude, ver_tela]


async def ver_a_tela(alvo: str, monitor: int, capturar=tela.capturar) -> dict[str, Any]:
    """Resultado da ferramenta ver_tela: a imagem e uma linha dizendo o que foi capturado."""
    try:
        captura = await asyncio.to_thread(capturar, alvo, monitor)
    except Exception as erro:
        log.warning("Falha ao capturar a tela: %s", erro)
        return _resultado(f"Não consegui ver a tela: {erro}", True)
    return {
        "content": [
            {"type": "text", "text": f"Print de agora: {captura.descricao}."},
            {"type": "image", "data": base64.b64encode(captura.png).decode("ascii"), "mimeType": "image/png"},
        ]
    }


class ErroClaude(RuntimeError):
    pass


def _versao(texto: str) -> tuple[int, ...]:
    casamento = re.search(r"(\d+)\.(\d+)\.(\d+)", texto or "")
    return tuple(int(x) for x in casamento.groups()) if casamento else ()


def _texto_versao(versao: tuple[int, ...]) -> str:
    return ".".join(map(str, versao)) if versao else "?"


def resolver_cli(configurado: str) -> tuple[str | None, str]:
    """Qual ``claude.exe`` usar e uma descrição para a tela.

    Em ``auto``, usa o Claude Code instalado no PC quando ele é pelo menos tão novo
    quanto o que vem dentro do SDK; senão, usa o do SDK. Os dois usam o mesmo login
    (pasta ``~/.claude``).
    """
    if configurado and configurado != "auto":
        return configurado, f"Claude Code em {configurado}"
    import claude_agent_sdk

    pasta_sdk = Path(claude_agent_sdk.__file__).parent / "_bundled"
    embutido = pasta_sdk / "claude.exe"
    arquivo_versao = pasta_sdk / "claude.version"
    versao_embutido = _versao(arquivo_versao.read_text(encoding="utf-8")) if arquivo_versao.is_file() else ()
    local = Path.home() / ".local" / "bin" / "claude.exe"
    instalado = shutil.which("claude.exe") or (str(local) if local.is_file() else None)
    versao_instalado: tuple[int, ...] = ()
    if instalado:
        try:
            saida = subprocess.run(
                [instalado, "--version"],
                capture_output=True,
                text=True,
                timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            versao_instalado = _versao(saida.stdout)
        except Exception as erro:
            log.warning("Não consegui ver a versão de %s: %s", instalado, erro)
    if instalado and versao_instalado and (not embutido.is_file() or versao_instalado >= versao_embutido):
        return instalado, f"Claude Code {_texto_versao(versao_instalado)}, o instalado no PC"
    if embutido.is_file():
        return str(embutido), f"Claude Code {_texto_versao(versao_embutido)}, o que vem com o app"
    return None, "Claude Code"


DICA_LOGIN = (
    "O Claude Code precisa de login. Use o botão “Fazer login” (ou rode  claude auth login --claudeai  num "
    "terminal), entre com a sua conta do Claude e depois clique em “Já fiz login”."
)
DICA_INSTALAR = "Não encontrei o Claude Code. Instale pelo PowerShell com:  irm https://claude.ai/install.ps1 | iex"
_SINAIS_DE_LOGIN = (
    "not logged in",
    "/login",
    "auth login",
    "failed to authenticate",
    "authentication_failed",
    "authentication_error",
    "cannot be renewed",
    "setup-token",
    "invalid api key",
    "oauth token has expired",
)


def eh_erro_de_login(texto: str) -> bool:
    texto = (texto or "").lower()
    return texto == DICA_LOGIN.lower() or any(trecho in texto for trecho in _SINAIS_DE_LOGIN)


def explicar_erro(erro: BaseException | str, stderr: list[str] | None = None) -> str:
    texto = str(erro)
    junto = (texto + "\n" + "\n".join(stderr or [])).lower()
    if isinstance(erro, CLINotFoundError):
        return DICA_INSTALAR
    if eh_erro_de_login(junto):
        return DICA_LOGIN
    if "credit balance is too low" in junto:
        return "A sua conta da API está sem créditos."
    if any(trecho in junto for trecho in ("rate limit", "usage limit", "rate_limit")):
        return "O limite de uso da sua conta foi atingido por agora. Tente de novo mais tarde."
    ultimas = " | ".join(linha.strip() for linha in (stderr or [])[-3:] if linha.strip())
    return texto + (f" (Claude Code: {ultimas})" if ultimas else "")


def chave_permissao(ferramenta: str, entrada: dict) -> str:
    """Agrupa permissões para o botão "sempre nesta conversa"."""
    if ferramenta in FERRAMENTAS_DE_COMANDO:
        primeiro = (str(entrada.get("command", "")).split() or [""])[0]
        return f"{ferramenta}:{primeiro}"
    if ferramenta == "WebFetch":
        return f"WebFetch:{urlparse(str(entrada.get('url', ''))).netloc}"
    return ferramenta


class PonteClaude:
    """Mantém uma sessão do Claude Code aberta para o projeto atual.

    O SDK exige que conectar, perguntar e desconectar aconteçam na mesma tarefa
    asyncio; por isso tudo passa por uma fila atendida por uma única tarefa. Só a
    interrupção é chamada direto, de fora.
    """

    def __init__(
        self,
        cfg_claude,
        pedir_permissao: PedirPermissao,
        acoes: AcoesDoApp | None = None,
    ):
        self.cfg = cfg_claude
        self._pedir_permissao = pedir_permissao
        self._acoes = acoes
        self._cliente: ClaudeSDKClient | None = None
        self._fila: asyncio.Queue | None = None
        self._tarefa: asyncio.Task | None = None
        self._cli: str | None = None
        self.descricao_cli = "Claude Code"
        self.cwd: str | None = None
        self.sessao: str | None = None
        self._ocupado = False
        self._reconectar = False
        self._permitidos: set[str] = set()
        self._ponto_desfazer: str | None = None
        self._nota_proxima = ""
        self._stderr: list[str] = []
        self.info: tuple[str, str] = ("", "")  # (modelo, permissões) que o Claude Code confirmou

    # ------------------------------------------------------------------ API
    async def iniciar(self) -> None:
        self._cli, self.descricao_cli = await asyncio.to_thread(resolver_cli, self.cfg.cli)
        log.info("Usando %s (%s)", self.descricao_cli, self._cli or "busca do SDK")
        self._fila = asyncio.Queue()
        self._tarefa = asyncio.create_task(self._trabalhador(), name="ponte-claude")

    @property
    def ocupado(self) -> bool:
        return self._ocupado

    @property
    def pode_desfazer(self) -> bool:
        return bool(self._ponto_desfazer)

    async def definir_destino(self, cwd: str, sessao: str | None) -> None:
        """Escolhe a pasta e a conversa, sem abrir o Claude Code (ele abre quando precisar)."""
        await self._pedir("destino", cwd, sessao)

    async def preaquecer(self) -> str | None:
        """Abre o Claude Code agora, se ainda não estiver aberto. Retorna a sessão em uso."""
        return await self._pedir("preaquecer")

    async def descansar(self) -> None:
        """Fecha o Claude Code para liberar memória; a conversa continua e é retomada depois."""
        await self._pedir("descansar")

    @property
    def conectado(self) -> bool:
        return self._cliente is not None

    async def perguntar(self, texto: str) -> AsyncIterator[EventoInfo | EventoTexto | EventoAcao | EventoFim]:
        assert self._fila is not None, "chame iniciar() antes"
        eventos: asyncio.Queue = asyncio.Queue()
        futuro = asyncio.get_running_loop().create_future()
        await self._fila.put(("perguntar", (texto, eventos), futuro))
        while True:
            evento = await eventos.get()
            if evento is None:
                break
            yield evento
        await futuro

    async def interromper(self) -> None:
        if self._cliente is not None and self._ocupado:
            try:
                await self._cliente.interrupt()
            except Exception as erro:
                log.warning("Falha ao interromper o Claude: %s", erro)

    async def desfazer(self) -> bool:
        return await self._pedir("desfazer")

    async def fechar(self) -> None:
        if self._tarefa is not None and not self._tarefa.done():
            await self._pedir("fechar")
            await self._tarefa

    async def verificar_login(self) -> bool | None:
        """True ou False conforme o ``claude auth status``; None se não deu para saber."""
        if not self._cli:
            return None

        def consultar() -> bool | None:
            try:
                saida = subprocess.run(
                    [self._cli, "auth", "status", "--json"],
                    capture_output=True,
                    text=True,
                    timeout=40,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return bool(json.loads(saida.stdout or "{}").get("loggedIn"))
            except Exception as erro:
                log.warning("Não consegui verificar o login do Claude Code: %s", erro)
                return None

        return await asyncio.to_thread(consultar)

    def abrir_login(self) -> bool:
        """Abre uma janela de terminal com o login oficial do Claude Code.

        Usa ``--claudeai`` de propósito: entra com a assinatura do Claude (a mesma do Claude
        Desktop), nunca com cobrança por uso de API (``--console``).
        """
        if not self._cli:
            return False
        subprocess.Popen(
            ["cmd.exe", "/c", "start", "Login do Claude Code", "cmd.exe", "/k", self._cli, "auth", "login", "--claudeai"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True


    def esquecer_permissoes(self) -> None:
        self._permitidos.clear()

    async def _pedir(self, tipo: str, *argumentos):
        assert self._fila is not None, "chame iniciar() antes"
        futuro = asyncio.get_running_loop().create_future()
        await self._fila.put((tipo, argumentos, futuro))
        return await futuro

    # ------------------------------------------------------------------ tarefa única
    async def _trabalhador(self) -> None:
        while True:
            tipo, argumentos, futuro = await self._fila.get()
            try:
                if tipo == "destino":
                    resultado = await self._destino(*argumentos)
                elif tipo == "preaquecer":
                    resultado = await self._preaquecer()
                elif tipo == "descansar":
                    resultado = await self._desconectar()
                elif tipo == "perguntar":
                    resultado = await self._perguntar(*argumentos)
                elif tipo == "desfazer":
                    resultado = await self._desfazer()
                elif tipo == "fechar":
                    await self._desconectar()
                    if not futuro.done():
                        futuro.set_result(None)
                    return
                else:
                    resultado = None
                if not futuro.done():
                    futuro.set_result(resultado)
            except Exception as erro:
                if not futuro.done():
                    futuro.set_exception(erro)

    def _opcoes(self, cwd: str, sessao: str | None) -> ClaudeAgentOptions:
        instrucoes = instrucoes_de_voz(resumir=self.cfg.respostas_resumidas)
        if self.cfg.instrucoes_extras.strip():
            instrucoes += "\n" + self.cfg.instrucoes_extras.strip() + "\n"
        servidores = {}
        if self._acoes is not None:
            servidores["app"] = create_sdk_mcp_server("app", "1.0.0", criar_ferramentas_do_app(self._acoes))
        return ClaudeAgentOptions(
            cwd=cwd,
            cli_path=self._cli,
            resume=sessao or None,
            permission_mode=self.cfg.modo_permissao or None,
            system_prompt={"type": "preset", "preset": "claude_code", "append": instrucoes},
            setting_sources=["user", "project", "local"],
            mcp_servers=servidores,  # as ferramentas do app são liberadas em _permissao
            can_use_tool=self._permissao,
            disallowed_tools=["AskUserQuestion"],
            model=self.cfg.modelo or None,
            effort=self.cfg.esforco or None,
            enable_file_checkpointing=True,
            extra_args={"replay-user-messages": None},
            stderr=self._guardar_stderr,
            client_app=f"{ID_APP}/{VERSAO}",
        )

    def _guardar_stderr(self, linha: str) -> None:
        self._stderr.append(linha)
        del self._stderr[:-60]
        log.debug("claude: %s", linha.rstrip())

    async def _destino(self, cwd: str, sessao: str | None) -> None:
        if cwd == self.cwd and sessao == self.sessao:
            return
        await self._desconectar()
        self.cwd, self.sessao = cwd, sessao
        # Conversa diferente: permissões "sempre", desfazer e avisos não valem mais.
        self._permitidos.clear()
        self._ponto_desfazer = None
        self._nota_proxima = ""

    async def _preaquecer(self) -> str | None:
        if self._cliente is None and self.cwd:
            await self._conectar(self.cwd, self.sessao)
        return self.sessao

    async def _conectar(self, cwd: str, sessao: str | None) -> str | None:
        await self._desconectar()
        self.cwd, self.sessao = cwd, sessao
        self._stderr.clear()
        try:
            cliente = ClaudeSDKClient(self._opcoes(cwd, sessao))
            await cliente.connect()
        except Exception as erro:
            if not sessao:
                raise ErroClaude(explicar_erro(erro, self._stderr)) from erro
            log.warning("Não deu para retomar a conversa %s (%s). Começando uma nova.", sessao, erro)
            sessao = self.sessao = None
            try:
                cliente = ClaudeSDKClient(self._opcoes(cwd, None))
                await cliente.connect()
            except Exception as erro_novo:
                raise ErroClaude(explicar_erro(erro_novo, self._stderr)) from erro_novo
        self._cliente = cliente
        self._reconectar = False
        return sessao

    async def _desconectar(self) -> None:
        if self._cliente is not None:
            try:
                await self._cliente.disconnect()
            except Exception as erro:
                log.warning("Falha ao fechar o Claude Code: %s", erro)
            self._cliente = None

    @staticmethod
    def _eh_resultado_de_ferramenta(mensagem: UserMessage) -> bool:
        return isinstance(mensagem.content, list) and any(isinstance(b, ToolResultBlock) for b in mensagem.content)

    async def _perguntar(self, texto: str, eventos: asyncio.Queue) -> None:
        textos: list[str] = []
        try:
            if self._cliente is None or self._reconectar:
                if not self.cwd:
                    raise ErroClaude("Nenhum projeto aberto.")
                await self._conectar(self.cwd, self.sessao)
            if self._nota_proxima:
                texto = f"{self._nota_proxima}\n\n{texto}"
                self._nota_proxima = ""
            self._ocupado = True
            ponto: str | None = None
            editou_arquivo = False
            await self._cliente.query(texto)
            async for mensagem in self._cliente.receive_response():
                if isinstance(mensagem, UserMessage):
                    if ponto is None and mensagem.uuid and not self._eh_resultado_de_ferramenta(mensagem):
                        ponto = mensagem.uuid
                elif isinstance(mensagem, AssistantMessage):
                    if mensagem.parent_tool_use_id:
                        continue  # mensagens internas de subagentes
                    if mensagem.error:
                        # O texto de uma mensagem de erro volta no resultado; não mostrar duas vezes.
                        log.warning("Erro na resposta do Claude: %s", mensagem.error)
                        continue
                    for bloco in mensagem.content:
                        if isinstance(bloco, TextBlock) and bloco.text.strip():
                            textos.append(bloco.text)
                            await eventos.put(EventoTexto(bloco.text))
                        elif isinstance(bloco, ToolUseBlock):
                            entrada = bloco.input or {}
                            caminho = ""
                            if bloco.name in _FERRAMENTAS_DE_EDICAO:
                                editou_arquivo = True
                                caminho = str(entrada.get("file_path") or entrada.get("notebook_path") or "")
                            fala, detalhe = descrever_ferramenta(bloco.name, entrada)
                            await eventos.put(EventoAcao(bloco.name, fala, detalhe, caminho))
                elif isinstance(mensagem, SystemMessage):
                    if mensagem.subtype == "init":
                        if mensagem.data.get("session_id"):
                            self.sessao = mensagem.data["session_id"]
                        info = (str(mensagem.data.get("model") or ""), str(mensagem.data.get("permissionMode") or ""))
                        if info[0] and info != self.info:
                            self.info = info
                            await eventos.put(EventoInfo(*info))
                elif isinstance(mensagem, ResultMessage):
                    self.sessao = mensagem.session_id or self.sessao
                    interrompido = mensagem.terminal_reason in ("aborted_streaming", "aborted_tools")
                    erro = ""
                    if mensagem.is_error and not interrompido:
                        bruto = "; ".join(mensagem.errors or []) or (mensagem.result or "") or mensagem.subtype
                        erro = explicar_erro(bruto, self._stderr)
                    if ponto and editou_arquivo and not erro:
                        self._ponto_desfazer = ponto
                    final = "\n\n".join(textos) or (mensagem.result or "")
                    await eventos.put(
                        EventoFim(
                            final,
                            self.sessao,
                            mensagem.duration_ms / 1000,
                            mensagem.total_cost_usd,
                            erro,
                            interrompido,
                        )
                    )
        except Exception as erro:
            log.exception("Falha na conversa com o Claude")
            self._reconectar = True
            await eventos.put(EventoFim("\n\n".join(textos), self.sessao, 0.0, None, explicar_erro(erro, self._stderr)))
        finally:
            self._ocupado = False
            await eventos.put(None)

    async def _desfazer(self) -> bool:
        if not self._ponto_desfazer:
            return False
        if self._cliente is None:
            if not self.cwd:
                return False
            await self._conectar(self.cwd, self.sessao)  # em espera: reabre a mesma conversa
        await self._cliente.rewind_files(self._ponto_desfazer)
        self._ponto_desfazer = None
        self._nota_proxima = (
            "(Aviso do app: o usuário desfez, por voz, as alterações de arquivo feitas na sua última resposta. "
            "Os arquivos voltaram ao estado de antes dela.)"
        )
        return True

    async def _permissao(self, ferramenta: str, entrada: dict, contexto: ToolPermissionContext):
        if ferramenta.startswith(PREFIXO_APP):
            return PermissionResultAllow()  # ferramentas do próprio app: o usuário pediu por voz
        chave = chave_permissao(ferramenta, entrada)
        if chave in self._permitidos:
            return PermissionResultAllow()
        try:
            aprovado, sempre = await self._pedir_permissao(ferramenta, entrada, contexto, chave)
        except Exception:
            log.exception("Falha ao pedir permissão")
            aprovado, sempre = False, False
        if aprovado:
            if sempre:
                self._permitidos.add(chave)
            return PermissionResultAllow()
        return PermissionResultDeny(
            message=(
                "O usuário não autorizou esta ação (respondeu por voz ou na janela, ou não respondeu a tempo). "
                "Não tente de novo do mesmo jeito; explique ou pergunte o que ele prefere."
            )
        )
