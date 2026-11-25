"""Configuração do app, guardada em ``config.toml`` na pasta de dados."""

from __future__ import annotations

import logging
import os
import tomllib
import typing
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path

import tomli_w

from . import caminhos
from .marca import NOME_APP, NOME_ATIVACAO_PADRAO

log = logging.getLogger(__name__)


@dataclass
class Ativacao:
    # "nome": você chama o assistente pelo nome antes de pedir algo.
    # "continuo": tudo o que você fala vai para o Claude (use com fone de ouvido).
    modo: str = "nome"
    nome: str = NOME_ATIVACAO_PADRAO
    # Outras grafias que o reconhecimento de voz costuma escrever para o nome.
    apelidos: list[str] = field(default_factory=list)
    # O nome só acorda: depois de chamar, tudo o que você fala é com ele, até a palavra de parar (ou até
    # ele cochilar sozinho, sem uso). False = o nome em todo pedido, fora da janela de conversa abaixo.
    nome_so_para_acordar: bool = True
    # Depois de uma resposta, por quantos segundos dá para continuar sem repetir o nome (quando o nome
    # vale para todo pedido).
    janela_conversa_s: float = 12.0
    similaridade_minima: float = 0.8
    # Quando você só chama o nome, o assistente responde "Pode falar."
    responder_ao_chamado: bool = True
    # Palavra que interrompe tudo na hora (o Claude e a fala), mesmo sem dizer o nome.
    # É de propósito uma palavra que quase ninguém fala sem querer.
    palavra_parar: str = "jabuticabal"
    # Palavra que manda o pedido na hora, como no rádio ("..., câmbio."). Só vale no fim da frase.
    palavra_enviar: str = "câmbio"
    # Sem a palavra de envio, o pedido vai depois desse silêncio. Dá tempo de pensar no meio do pedido:
    # o que você falar antes disso entra no mesmo pedido, sem repetir o nome. 0 = manda assim que você para.
    espera_envio_s: float = 5.0
    # Completou o pedido até esse tempo depois de mandar, e o Claude ainda não mexeu em nada? Ele é
    # interrompido e recebe o pedido inteiro, junto. Depois disso, o pedido novo vai para a fila. 0 desliga.
    juntar_pedido_s: float = 10.0


@dataclass
class Saudacao:
    # Ao ser chamado, o assistente cumprimenta com uma abertura e uma frase (com música de fundo, se quiser).
    # É fixa: não passa pelo Claude e não atrasa o pedido. As frases são sorteadas sem repetir as últimas.
    # Nas frases, {periodo} vira "Bom dia", "Boa tarde" ou "Boa noite" e {tratamento} vira como chamar você.
    # quando: "acordar" (na primeira chamada depois de um tempo parado), "sempre" ou "nunca".
    quando: str = "acordar"
    # Como o assistente chama você, na saudação e nas respostas do Claude.
    tratamento: str = "mestre"
    aberturas: list[str] = field(
        default_factory=lambda: [
            "{periodo}, {tratamento}.",
            "{periodo}, {tratamento}. É um prazer falar com você.",
            "Olá, {tratamento}.",
            "Às suas ordens, {tratamento}.",
            "Pois não, {tratamento}.",
            "Estou aqui, {tratamento}.",
            "{periodo}. Estou à sua disposição, {tratamento}.",
        ]
    )
    # Depois da abertura, quando você só chama o nome:
    frases_chamado: list[str] = field(
        default_factory=lambda: [
            "Em que posso ajudar?",
            "Como posso ser útil?",
            "O que deseja fazer?",
            "Aguardo as suas instruções.",
            "Qual é a próxima tarefa?",
            "Pode falar, estou ouvindo.",
            "Tudo pronto. Como posso ajudar?",
            "Todos os sistemas estão prontos. O que deseja?",
            "Diga o que precisa.",
            "Pronto para começar quando quiser.",
        ]
    )
    # Depois da abertura, quando você já fala o pedido junto com o nome (toca enquanto o Claude trabalha):
    frases_pedido: list[str] = field(
        default_factory=lambda: [
            "Certamente.",
            "Perfeitamente.",
            "Entendido. Vou providenciar.",
            "Pois não, já estou cuidando disso.",
            "Com certeza. Um momento, por favor.",
            "Entendido. Já estou trabalhando nisso.",
            "Muito bem, vou cuidar disso agora.",
            "Claro. Só um instante.",
            "Compreendido.",
            "Será feito.",
        ]
    )
    # Aberturas de ocasiões especiais: na hora certa, entram no lugar da abertura comum (metade das vezes).
    madrugada: list[str] = field(  # da meia-noite às 5h
        default_factory=lambda: [
            "Trabalhando até tarde, {tratamento}?",
            "{periodo}, {tratamento}. Ainda em atividade a esta hora?",
        ]
    )
    segunda: list[str] = field(  # segunda-feira de manhã
        default_factory=lambda: [
            "Bom dia, {tratamento}. Desejo uma ótima semana.",
            "Bom dia, {tratamento}. Vamos começar a semana.",
        ]
    )
    sexta: list[str] = field(
        default_factory=lambda: [
            "{periodo}, {tratamento}. Enfim, sexta-feira.",
            "{periodo}, {tratamento}. Vamos encerrar bem a semana.",
        ]
    )
    fim_de_semana: list[str] = field(
        default_factory=lambda: [
            "{periodo}, {tratamento}. Trabalhando no fim de semana?",
            "{periodo}, {tratamento}. Tenha um bom fim de semana.",
        ]
    )
    musica: str = ""  # vazio = vinheta do app (ou nenhuma); ou o caminho de uma música sua (mp3, wav, ogg...)
    estilo: str = "nenhuma"  # vinheta do app: "nenhuma" (só a voz), "rock" (rock pesado) ou "suave" (marimba)
    volume_musica: float = 0.45


@dataclass
class Audio:
    microfone: str = ""  # vazio = padrão do Windows; ou parte do nome do dispositivo
    saida: str = ""
    limiar_vad: float = 0.5  # 0 a 1: quanto maior, mais certeza de que é fala
    silencio_fim_ms: int = 800  # silêncio que encerra uma fala
    fala_minima_ms: int = 300
    fala_maxima_s: float = 45.0
    pre_fala_ms: int = 300
    sons: bool = True
    volume: float = 1.0


@dataclass
class Reconhecimento:
    modelo: str = "large-v3-turbo"
    dispositivo: str = "auto"  # auto | cuda | cpu
    precisao: str = "auto"  # auto (int8_float16 na placa, int8 no processador) | float16 | int8_float16 | int8
    idioma: str = "pt"
    beam_size: int = 5
    # Modelo leve, no processador, que só procura o nome em tudo o que o microfone ouve.
    # O modelo principal (placa de vídeo) só entra depois que você chama. Vazio = usar o principal.
    modelo_ativacao: str = "tiny"
    threads_ativacao: int = 2
    # Pastas extras com cublas64_12.dll (o app também procura sozinho; ver cuda.py).
    pastas_cuda: list[str] = field(default_factory=list)


@dataclass
class Espera:
    # Em espera ficam carregados só a detecção de voz e o modelo leve que procura o nome (no processador).
    # O reconhecimento preciso (placa de vídeo), a voz e o Claude Code carregam quando você chama
    # (uns 2 a 3 s a mais nessa vez) e saem de novo depois de um tempo sem uso.
    comecar_em_espera: bool = True
    voltar_apos_min: float = 10.0  # 0 = nunca volta para a espera sozinho


@dataclass
class Voz:
    motor: str = "kokoro"  # kokoro | sapi
    voz: str = "pm_alex"  # kokoro: pm_alex, pm_santa (masculinas), pf_dora (feminina)
    velocidade: float = 1.05
    # Voz do Windows: usada no motor "sapi" e como reserva se o Kokoro não carregar (mesmo gênero da voz acima).
    voz_sapi: str = "Daniel"


@dataclass
class Claude:
    # auto: um classificador do Claude Code aprova o que é seguro e só pergunta o que for arriscado
    # (como no Claude Code). acceptEdits: edita os arquivos do projeto sem perguntar; pergunta antes de
    # comandos. default: pergunta antes de editar e de rodar comandos. plan: só planeja, não altera nada.
    modo_permissao: str = "auto"
    modelo: str = "claude-opus-5-5"  # vazio = o padrão do seu Claude Code
    # Quanto o Claude pensa: low, medium, high, xhigh ou max (vazio = o Claude Code escolhe). Médio é o
    # equilíbrio para conversa por voz; dá para trocar falando ("Hércules, pensa com mais cuidado").
    esforco: str = "medium"
    cli: str = "auto"  # auto ou o caminho de um claude.exe
    # Ao abrir o app, começa numa conversa nova (as anteriores ficam nas conversas salvas).
    conversa_nova_ao_abrir: bool = True
    # Ao entrar num projeto, continua a conversa anterior dele (o Claude lembra do que foi feito ali).
    retomar_conversa: bool = True
    narrar_progresso: bool = True
    # Respostas curtas e diretas. Vale só nas conversas pelo app: abrir o projeto no Claude Code ou
    # no Claude Desktop continua do jeito de sempre.
    respostas_resumidas: bool = True
    tempo_aprovacao_s: float = 120.0
    instrucoes_extras: str = ""  # também só nas conversas pelo app


@dataclass
class Projeto:
    nome: str = ""
    caminho: str = ""
    apelidos: list[str] = field(default_factory=list)


@dataclass
class Projetos:
    # Cada subpasta destas pastas vira um projeto que dá para escolher por voz.
    pastas_raiz: list[str] = field(default_factory=list)
    ignorar: list[str] = field(default_factory=list)
    lista: list[Projeto] = field(default_factory=list)
    # O app abre na "Área livre" (nenhum projeto) e só entra num projeto quando você pedir.
    # Desligado, ele abre no último projeto usado.
    comecar_sem_projeto: bool = True


@dataclass
class Interface:
    iniciar_minimizado: bool = False
    fechar_para_bandeja: bool = True
    sempre_no_topo: bool = False
    # Bolinha flutuante (o orbe do assistente, com um balão do que ele fala) quando a janela está fechada.
    janela_compacta: bool = True
    iniciar_compacto: bool = True  # abre só a bolinha; a janela completa abre com um clique nela
    # A bolinha fica por cima de todas as janelas. Desligado, ela é uma janela comum (com botão na
    # barra de tarefas) que pode ficar atrás das outras. Também muda pelo botão direito na bolinha.
    bolinha_no_topo: bool = True
    # Prioridade "abaixo do normal" no Windows: em disputa (um jogo, por exemplo), o outro programa ganha.
    prioridade_baixa: bool = True


@dataclass
class Config:
    ativacao: Ativacao = field(default_factory=Ativacao)
    saudacao: Saudacao = field(default_factory=Saudacao)
    audio: Audio = field(default_factory=Audio)
    reconhecimento: Reconhecimento = field(default_factory=Reconhecimento)
    espera: Espera = field(default_factory=Espera)
    voz: Voz = field(default_factory=Voz)
    claude: Claude = field(default_factory=Claude)
    projetos: Projetos = field(default_factory=Projetos)
    interface: Interface = field(default_factory=Interface)


def _converter(tipo, valor):
    if tipo is bool:
        if isinstance(valor, str):
            return valor.strip().lower() in ("1", "true", "sim", "yes")
        return bool(valor)
    if tipo in (int, float, str):
        return tipo(valor)
    return valor


def _de_dict(cls, dados: dict):
    obj = cls()
    dicas = typing.get_type_hints(cls)
    for campo in fields(cls):
        if campo.name not in dados:
            continue
        valor = dados[campo.name]
        tipo = dicas[campo.name]
        try:
            atual = getattr(obj, campo.name)
            if is_dataclass(atual):
                if isinstance(valor, dict):
                    setattr(obj, campo.name, _de_dict(type(atual), valor))
            elif typing.get_origin(tipo) is list:
                (arg,) = typing.get_args(tipo)
                itens = valor if isinstance(valor, list) else [valor]
                if is_dataclass(arg):
                    setattr(obj, campo.name, [_de_dict(arg, v) for v in itens if isinstance(v, dict)])
                else:
                    setattr(obj, campo.name, [_converter(arg, v) for v in itens])
            else:
                setattr(obj, campo.name, _converter(tipo, valor))
        except (TypeError, ValueError) as erro:
            log.warning("Valor inválido em %s.%s (%r): %s", cls.__name__, campo.name, valor, erro)
    return obj


_RAIZES_COMUNS = (
    "C:\\dev",
    "~/dev",
    "~/projetos",
    "~/projects",
    "~/source/repos",
    "~/Documents/GitHub",
    "~/Documentos/GitHub",
)


def padrao_primeira_vez() -> Config:
    cfg = Config()
    raizes: list[str] = []
    for raiz in _RAIZES_COMUNS:
        pasta = Path(raiz).expanduser()
        if pasta.is_dir() and str(pasta) not in raizes:
            raizes.append(str(pasta))
    cfg.projetos.pastas_raiz = raizes
    return cfg


_CABECALHO = (
    "# Configuração do {app}.\n"
    "# Pode editar à mão com o app fechado; a janela de Configurações também salva aqui.\n\n"
)


def carregar(caminho: Path | None = None) -> Config:
    caminho = caminho or caminhos.arquivo_config()
    if not caminho.is_file():
        cfg = padrao_primeira_vez()
        salvar(cfg, caminho)
        return cfg
    try:
        dados = tomllib.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as erro:
        log.error("Não consegui ler %s (%s). Usando os padrões.", caminho, erro)
        return padrao_primeira_vez()
    return _de_dict(Config, _migrar(dados))


# Listas padrão de versões anteriores: quem nunca mexeu nelas recebe as listas novas.
_PADROES_ANTIGOS: dict[str, list[list[str]]] = {
    "aberturas": [
        [
            "{periodo}, {tratamento}!",
            "{periodo}, {tratamento}! Que bom te ouvir.",
            "E aí, {tratamento}!",
            "Olá, {tratamento}!",
            "Fala, {tratamento}!",
            "Opa! {periodo}, {tratamento}!",
            "Salve, {tratamento}!",
            "{tratamento}! Na escuta.",
            "Que bom ter você de volta, {tratamento}!",
            "Olha só quem chegou! {periodo}, {tratamento}!",
        ],
    ],
    "frases_chamado": [
        [
            "Seu assistente favorito na área. Manda ver!",
            "Sistemas ligados e café no ponto. Qual é a missão?",
            "Pronto pra mais uma. Pode falar!",
            "Às suas ordens! O que a gente vai aprontar hoje?",
            "Cheguei! Bora fazer acontecer?",
        ],
        [
            "Seu assistente favorito na área. Manda ver!",
            "Sistemas ligados e café no ponto. Qual é a missão?",
            "Pronto pra mais uma. Pode falar!",
            "Às suas ordens! O que a gente vai aprontar hoje?",
            "Cheguei! Bora fazer acontecer?",
            "Todos os sistemas operando a cem por cento. No que posso ajudar?",
            "Reatores aquecidos e motores ligados. Qual é o plano?",
            "Processadores a todo vapor. Manda a próxima!",
            "Estava aqui só esperando você chamar. O que vai ser hoje?",
            "Modo turbo ativado. Pode mandar!",
            "Café tomado, código compilado. O que manda?",
            "Online e com energia de sobra. Qual é o desafio?",
            "Calibrando os sensores... prontinho! Pode falar.",
            "Tudo pronto por aqui. Qual é a próxima aventura?",
            "Painel aceso e ideias na mesa. Qual é a boa?",
            "Manda a braba, que eu resolvo!",
            "Radar ligado, nenhuma missão impossível. O que vamos fazer?",
            "Mais uma rodada? Tô dentro!",
        ],
    ],
    "frases_pedido": [
        [
            "Deixa comigo!",
            "Já estou cuidando disso!",
            "Missão recebida, bora lá!",
            "É pra já!",
            "Pode deixar que eu resolvo!",
        ],
        [
            "Deixa comigo!",
            "Já estou cuidando disso!",
            "Missão recebida, bora lá!",
            "É pra já!",
            "Pode deixar que eu resolvo!",
            "Entendido! Já estou nisso.",
            "Considera feito!",
            "Na mesma hora!",
            "Anotado! Partiu.",
            "Bora! Colocando a mão na massa.",
            "Ordem recebida, executando!",
            "Agora mesmo!",
            "Com prazer!",
            "Missão aceita!",
        ],
    ],
    "madrugada": [
        [
            "Virando a noite, {tratamento}?",
            "Ainda na ativa a essa hora, {tratamento}?",
            "Madrugada produtiva, hein, {tratamento}?",
        ],
    ],
    "segunda": [
        [
            "Bom dia, {tratamento}! Segunda-feira chegou.",
            "Segundou, {tratamento}! Bora começar a semana com tudo.",
        ],
    ],
    "sexta": [
        [
            "Sextou, {tratamento}!",
            "Sexta-feira, {tratamento}! Bora fechar a semana com chave de ouro.",
        ],
    ],
    "fim_de_semana": [
        [
            "Até no fim de semana, {tratamento}? Gosto disso!",
            "Bom fim de semana, {tratamento}!",
        ],
    ],
}


def _migrar(dados: dict) -> dict:
    """Ajusta o que versões anteriores do app salvaram de outro jeito."""
    saudacao = dados.get("saudacao")
    if isinstance(saudacao, dict):
        if "abertura" in saudacao and "aberturas" not in saudacao:  # era uma abertura só
            antiga = str(saudacao.pop("abertura")).strip()
            if antiga and antiga != "{periodo}, {tratamento}!":  # quem personalizou não perde a sua
                saudacao["aberturas"] = list(dict.fromkeys([antiga, *Saudacao().aberturas]))
        for campo, antigos in _PADROES_ANTIGOS.items():
            if saudacao.get(campo) in antigos:
                del saudacao[campo]
    return dados


def salvar(cfg: Config, caminho: Path | None = None) -> None:
    caminho = caminho or caminhos.arquivo_config()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    texto = _CABECALHO.format(app=NOME_APP) + tomli_w.dumps(asdict(cfg))
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(texto, encoding="utf-8")
    temporario.replace(caminho)


def _chave(caminho: str) -> str:
    return os.path.normcase(os.path.abspath(caminho))


def projetos_disponiveis(cfg: Config) -> list[Projeto]:
    """Projetos da lista da configuração mais as subpastas das pastas raiz."""
    vistos: dict[str, Projeto] = {}
    for proj in cfg.projetos.lista:
        if proj.caminho:
            nome = proj.nome or Path(proj.caminho).name
            vistos[_chave(proj.caminho)] = Projeto(nome, proj.caminho, list(proj.apelidos))
    ignorar = {nome.lower() for nome in cfg.projetos.ignorar}
    for raiz in cfg.projetos.pastas_raiz:
        try:
            entradas = sorted(Path(raiz).expanduser().iterdir())
        except OSError:
            continue
        for pasta in entradas:
            if pasta.name.startswith((".", "_", "$")) or pasta.name.lower() in ignorar:
                continue
            try:
                if not pasta.is_dir():
                    continue
            except OSError:
                continue
            vistos.setdefault(_chave(str(pasta)), Projeto(pasta.name, str(pasta)))
    return sorted(vistos.values(), key=lambda p: p.nome.lower())
