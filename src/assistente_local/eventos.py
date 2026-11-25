"""Mensagens que o controlador manda para a interface (sempre de outra thread)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Estado(str, Enum):
    CARREGANDO = "carregando"
    ESPERA = "espera"  # ouvindo, com o mínimo carregado
    ACORDANDO = "acordando"  # carregando o resto depois de ser chamado
    OUVINDO = "ouvindo"  # esperando ser chamado pelo nome
    CONVERSA = "conversa"  # dá para falar sem repetir o nome
    GRAVANDO = "gravando"
    TRANSCREVENDO = "transcrevendo"
    RASCUNHO = "rascunho"  # pedido falado esperando um silêncio (ou a palavra de envio) para ir
    PENSANDO = "pensando"
    FALANDO = "falando"
    APROVACAO = "aprovacao"
    MUDO = "mudo"
    SEM_MICROFONE = "sem_microfone"
    ERRO = "erro"


@dataclass
class EstadoMudou:
    estado: Estado
    detalhe: str = ""


@dataclass
class Carregando:
    mensagem: str
    fracao: float | None = None


@dataclass
class Pronto:
    reconhecimento: str
    voz: str
    microfone: str
    saida: str
    claude: str


@dataclass
class InfoClaude:
    """Modelo, esforço e permissões do Claude Code. O modelo é confirmado quando a sessão abre."""

    modelo: str  # nome amigável, ex.: "Opus 5.5"
    esforco: str  # ex.: "alto"
    permissao: str  # ex.: "automático"
    confirmado: bool = False


@dataclass
class ConfigAlterada:
    """A configuração mudou fora da janela de configurações (por exemplo, esforço pedido por voz)."""

    cfg: object


@dataclass
class NivelMicrofone:
    nivel: float
    gravando: bool


@dataclass
class FalaUsuario:
    texto: str
    origem: str = "voz"  # voz | teclado


@dataclass
class FalaIgnorada:
    texto: str
    motivo: str = ""


@dataclass
class Rascunho:
    """O pedido que você está falando e que ainda não foi para o Claude. Texto vazio = acabou (foi ou saiu)."""

    texto: str
    envia_em: float = 0.0  # time.monotonic() em que ele vai sozinho; 0 = esperando você terminar de falar
    palavra: str = ""  # a palavra que manda na hora ("câmbio")


@dataclass
class Fila:
    """Pedidos esperando o Claude terminar o que está fazendo, na ordem: (id, pedido)."""

    itens: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class InicioResposta:
    pass


@dataclass
class TextoClaude:
    texto: str


@dataclass
class AcaoClaude:
    descricao: str
    ferramenta: str


@dataclass
class FimResposta:
    fala: str
    duracao_s: float
    custo_usd: float | None
    erro: str = ""
    interrompida: bool = False
    texto: str = ""  # resposta completa visível (para copiar)
    arquivos: list[str] = field(default_factory=list)  # arquivos e pastas criados ou citados


@dataclass
class PedidoAprovacao:
    id: str
    pergunta: str
    detalhe: str
    ferramenta: str
    chave_sempre: str = ""


@dataclass
class AprovacaoResolvida:
    id: str
    aprovado: bool
    por: str


@dataclass
class ProjetoAtual:
    nome: str
    caminho: str
    retomada: bool


@dataclass
class ConversaCarregada:
    """Conversa salva do projeto (vazia quando começa uma nova): a interface redesenha a lista."""

    projeto: str
    entradas: list[dict] = field(default_factory=list)


@dataclass
class ConversaNova:
    pass


@dataclass
class LoginNecessario:
    """O Claude Code deste PC não está logado: a interface mostra como entrar."""

    mensagem: str = ""


@dataclass
class LoginConfirmado:
    pass


@dataclass
class Copiar:
    """Pedido (por voz) para pôr um texto na área de transferência."""

    texto: str
    descricao: str = ""


@dataclass
class Abrir:
    """Pedido (por voz) para abrir um arquivo, ou a pasta dele."""

    caminho: str
    na_pasta: bool = False


@dataclass
class Aviso:
    mensagem: str
    nivel: str = "info"  # info | erro
