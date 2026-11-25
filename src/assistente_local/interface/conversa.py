"""Peças da conversa: bolhas, respostas do Claude, arquivos, permissões, login e avisos."""

from __future__ import annotations

import math
import os
import time
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextFormat, QTextOption
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import eventos as ev
from ..texto_fala import FERRAMENTAS_DE_COMANDO
from . import acoes
from ..marca import NOME_APP
from .tema import CORES


def rotulo(texto: str = "", nome: str = "", markdown: bool = False, selecionavel: bool = True) -> QLabel:
    item = QLabel()
    if nome:
        item.setObjectName(nome)
    item.setWordWrap(True)
    item.setTextFormat(Qt.TextFormat.MarkdownText if markdown else Qt.TextFormat.PlainText)
    if selecionavel:
        item.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        item.setOpenExternalLinks(True)
    item.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    item.setText(texto)
    return item


def _repolir(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class TextoRico(QTextBrowser):
    """Markdown que quebra linha em qualquer ponto (caminhos longos) e cresce conforme o conteúdo.

    Dá para selecionar e copiar (Ctrl+C ou botão direito) e clicar nos links.
    """

    def __init__(self, markdown: str) -> None:
        super().__init__()
        self.setObjectName("texto")
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().setDocumentMargin(0)
        self.setMarkdown(markdown)
        try:
            self._estilizar_codigo()
        except Exception:  # só aparência: se falhar, o texto continua certo
            pass
        self.document().documentLayout().documentSizeChanged.connect(self._ajustar_altura)
        self._ajustar_altura()

    def _estilizar_codigo(self) -> None:
        """Fonte monoespaçada e fundo escuro para código (blocos e trechos entre crases)."""
        documento = self.document()
        letra = QTextCharFormat()
        letra.setFontFamilies(["Cascadia Mono", "Consolas", "Courier New"])
        letra.setForeground(QColor("#3b2f8a"))
        letra.setBackground(QColor("#f1efff"))
        fundo = QTextBlockFormat()
        fundo.setBackground(QColor("#f1efff"))
        bloco = documento.begin()
        while bloco.isValid():
            formato = bloco.blockFormat()
            eh_bloco_de_codigo = formato.hasProperty(QTextFormat.Property.BlockCodeFence) or formato.hasProperty(
                QTextFormat.Property.BlockCodeLanguage
            )
            if eh_bloco_de_codigo:
                cursor = QTextCursor(bloco)
                cursor.mergeBlockFormat(fundo)
            iterador = bloco.begin()
            while not iterador.atEnd():
                pedaco = iterador.fragment()
                if pedaco.isValid() and (eh_bloco_de_codigo or pedaco.charFormat().fontFixedPitch()):
                    cursor = QTextCursor(documento)
                    cursor.setPosition(pedaco.position())
                    cursor.setPosition(pedaco.position() + pedaco.length(), QTextCursor.MoveMode.KeepAnchor)
                    cursor.mergeCharFormat(letra)
                iterador += 1
            bloco = bloco.next()

    def _ajustar_altura(self, *_args) -> None:
        altura = max(18, int(self.document().size().height() + 0.5) + 2)
        if self.minimumHeight() != altura or self.maximumHeight() != altura:
            self.setFixedHeight(altura)

    def resizeEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        super().resizeEvent(evento)
        self.document().setTextWidth(self.viewport().width())
        self._ajustar_altura()

    def wheelEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        evento.ignore()  # deixa a lista da conversa rolar

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (nome do Qt)
        return QSize(60, self.height())


class RotuloElidido(QLabel):
    """Uma linha que encurta o texto no meio quando não cabe (o texto completo fica na dica)."""

    def __init__(self, texto: str, nome: str = "") -> None:
        super().__init__()
        self._completo = texto
        if nome:
            self.setObjectName(nome)
        self.setToolTip(texto)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setText(texto)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (nome do Qt)
        return QSize(40, super().minimumSizeHint().height())

    def sizeHint(self) -> QSize:  # noqa: N802 (nome do Qt)
        return QSize(min(super().sizeHint().width(), 360), super().sizeHint().height())

    def resizeEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        super().resizeEvent(evento)
        texto = self.fontMetrics().elidedText(self._completo, Qt.TextElideMode.ElideMiddle, max(10, self.width()))
        if texto != self.text():
            self.setText(texto)


def botao_pequeno(texto: str, acao: Callable[[], None], dica: str = "") -> QPushButton:
    botao = QPushButton(texto)
    botao.setObjectName("pequeno")
    if dica:
        botao.setToolTip(dica)
    botao.clicked.connect(lambda _marcado=False: acao())
    return botao


class BotaoCopiar(QPushButton):
    """Copia um texto e mostra "Copiado ✓" por um instante."""

    def __init__(self, obter_texto: Callable[[], str], texto: str = "Copiar") -> None:
        super().__init__(texto)
        self.setObjectName("pequeno")
        self._texto_original = texto
        self._obter_texto = obter_texto
        self.clicked.connect(self._copiar)

    def _copiar(self) -> None:
        acoes.copiar(self._obter_texto())
        self.setText("Copiado ✓")
        QTimer.singleShot(1500, lambda: self.setText(self._texto_original))


class MedidorNivel(QWidget):
    """Barrinha do volume do microfone; fica vermelha enquanto grava a sua fala."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(70, 10)
        self._mostrado = 0.0
        self._gravando = False

    def definir(self, nivel: float, gravando: bool) -> None:
        self._mostrado = max(nivel, self._mostrado * 0.75)
        self._gravando = gravando
        self.update()

    def paintEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.rect().adjusted(0, 1, 0, -1)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QColor(255, 255, 255, 150))
        pintor.drawRoundedRect(area, 4, 4)
        largura = int(area.width() * max(0.0, min(1.0, self._mostrado)))
        if largura > 0:
            pintor.setBrush(QColor(CORES["vermelho"] if self._gravando else CORES["verde"]))
            pintor.drawRoundedRect(QRect(area.left(), area.top(), largura, area.height()), 4, 4)


class BolhaUsuario(QWidget):
    def __init__(self, texto: str, origem: str) -> None:
        super().__init__()
        self._texto = texto
        linha = QHBoxLayout(self)
        linha.setContentsMargins(56, 0, 0, 0)
        linha.addStretch(1)
        self.bolha = QFrame()
        self.bolha.setObjectName("bolhaUsuario")
        coluna = QVBoxLayout(self.bolha)
        coluna.setContentsMargins(14, 9, 14, 10)
        coluna.setSpacing(2)
        self._rotulo = rotulo(texto, "textoUsuario")
        coluna.addWidget(self._rotulo)
        complemento = {"teclado": "digitado", "continuação": "continuação do pedido"}.get(origem, "")
        if complemento:
            coluna.addWidget(rotulo(complemento, "metaUsuario", selecionavel=False))
        linha.addWidget(self.bolha)

    def ajustar(self, limite: int) -> None:
        """Largura natural do texto, até ``limite`` (aí quebra linha)."""
        self.bolha.setMaximumWidth(limite)
        metricas = self._rotulo.fontMetrics()
        natural = max((metricas.horizontalAdvance(parte) for parte in self._texto.splitlines() or [""]), default=0)
        self._rotulo.setMinimumWidth(min(natural + 6, max(80, limite - 30)))


class ChipsArquivos(QWidget):
    """Arquivos e pastas da resposta, com botões para abrir, mostrar na pasta e copiar o caminho."""

    def __init__(self, caminhos: list[str]) -> None:
        super().__init__()
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 2, 0, 2)
        coluna.setSpacing(6)
        for caminho in caminhos:
            coluna.addWidget(self._linha(caminho))

    @staticmethod
    def _linha(caminho: str) -> QFrame:
        eh_pasta = os.path.isdir(caminho)
        quadro = QFrame()
        quadro.setObjectName("arquivo")
        linha = QHBoxLayout(quadro)
        linha.setContentsMargins(10, 6, 8, 6)
        linha.setSpacing(6)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        nome = RotuloElidido(("📁  " if eh_pasta else "📄  ") + (Path(caminho).name or caminho), "nomeArquivo")
        local = RotuloElidido(caminho, "meta")
        textos.addWidget(nome)
        textos.addWidget(local)
        linha.addLayout(textos, 1)
        linha.addWidget(botao_pequeno("Abrir", lambda: acoes.abrir(caminho), "Abrir com o programa padrão"))
        if not eh_pasta:
            linha.addWidget(
                botao_pequeno("Mostrar na pasta", lambda: acoes.mostrar_na_pasta(caminho), "Abrir a pasta com o arquivo selecionado")
            )
        linha.addWidget(BotaoCopiar(lambda: caminho, "Copiar caminho"))
        return quadro


class BlocoResposta(QFrame):
    """Uma resposta do Claude: textos e ações na ordem em que chegam e, no fim, arquivos e fala."""

    def __init__(self, do_historico: bool = False) -> None:
        super().__init__()
        self.setObjectName("bolhaClaude")  # um cartão de vidro
        self._coluna = QVBoxLayout(self)
        self._coluna.setContentsMargins(14, 11, 14, 11)
        self._coluna.setSpacing(8)
        topo = QHBoxLayout()
        topo.setSpacing(8)
        ponto = QLabel()
        ponto.setFixedSize(10, 10)
        ponto.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {CORES['acento']}, stop:1 {CORES['violeta']});"
            "border-radius: 5px;"
        )
        topo.addWidget(ponto)
        topo.addWidget(rotulo(NOME_APP, "nomeAssistente", selecionavel=False), 1)
        self._coluna.addLayout(topo)
        self._grupo_acoes: QVBoxLayout | None = None
        self._trabalhando = rotulo("Trabalhando…", "acao", selecionavel=False)
        self._coluna.addWidget(self._trabalhando)
        if do_historico:
            self._trabalhando.hide()
        self._textos: list[str] = []
        self.finalizado = False

    def _inserir(self, widget: QWidget) -> None:
        indice = self._coluna.indexOf(self._trabalhando)
        self._coluna.insertWidget(indice if indice >= 0 else self._coluna.count(), widget)

    def adicionar_texto(self, texto: str) -> None:
        self._textos.append(texto)
        self._grupo_acoes = None  # a próxima ação abre um grupo novo, depois deste texto
        self._inserir(TextoRico(texto))

    def adicionar_acao(self, descricao: str) -> None:
        """Ações seguidas ficam juntas num quadro discreto."""
        if self._grupo_acoes is None:
            quadro = QFrame()
            quadro.setObjectName("atividade")
            self._grupo_acoes = QVBoxLayout(quadro)
            self._grupo_acoes.setContentsMargins(12, 8, 12, 8)
            self._grupo_acoes.setSpacing(3)
            self._inserir(quadro)
        self._grupo_acoes.addWidget(rotulo(f"✓  {descricao}", "acao"))

    def texto_completo(self) -> str:
        return "\n\n".join(self._textos).strip()

    def finalizar(self, fim: ev.FimResposta) -> None:
        self.finalizado = True
        self._trabalhando.hide()
        if fim.erro:
            self._coluna.addWidget(rotulo(fim.erro, "avisoErro"))
        if fim.arquivos:
            self._coluna.addWidget(ChipsArquivos(fim.arquivos))
        if fim.fala:
            fala = rotulo(f"“{fim.fala}”", "fala")
            fala.setToolTip("O que foi falado em voz alta")
            self._coluna.addWidget(fala)
        partes = []
        if fim.duracao_s:
            partes.append(f"{fim.duracao_s:.0f} s")
        if fim.custo_usd:
            partes.append(f"US$ {fim.custo_usd:.2f}".replace(".", ","))
        if fim.interrompida:
            partes.append("interrompida")
        rodape = QHBoxLayout()
        rodape.setSpacing(6)
        rodape.addWidget(rotulo(" · ".join(partes), "meta", selecionavel=False), 1)
        if self._textos:
            rodape.addWidget(BotaoCopiar(self.texto_completo, "Copiar resposta"))
        self._coluna.addLayout(rodape)


class CartaoAprovacao(QFrame):
    def __init__(self, pedido: ev.PedidoAprovacao, responder: Callable[[str, bool, bool], None]) -> None:
        super().__init__()
        self.setObjectName("cartaoAprovacao")
        self._id = pedido.id
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(14, 12, 14, 12)
        coluna.setSpacing(8)
        coluna.addWidget(rotulo("PERMISSÃO", "autor", selecionavel=False))
        coluna.addWidget(rotulo(pedido.pergunta, "tituloCartao"))
        if pedido.detalhe and pedido.detalhe not in pedido.pergunta:
            coluna.addWidget(rotulo(pedido.detalhe, "detalhe"))
        coluna.addWidget(rotulo("Responda falando “sim” ou “não”, ou use os botões.", "meta", selecionavel=False))
        botoes = QHBoxLayout()
        self._aprovar = QPushButton("Aprovar")
        self._aprovar.setObjectName("primario")
        self._negar = QPushButton("Negar")
        texto_sempre = "Sempre nesta conversa"
        ferramenta, _, comando = pedido.chave_sempre.partition(":")
        if ferramenta in FERRAMENTAS_DE_COMANDO and comando:
            texto_sempre = f"Sempre permitir “{comando}”"
        self._sempre = QPushButton(texto_sempre)
        self._sempre.setToolTip("Aprova agora e não pergunta de novo por esse tipo de ação até a próxima conversa.")
        for botao in (self._aprovar, self._negar, self._sempre):
            botoes.addWidget(botao)
        botoes.addStretch(1)
        coluna.addLayout(botoes)
        self._situacao = rotulo("", "meta", selecionavel=False)
        self._situacao.hide()
        coluna.addWidget(self._situacao)
        self._aprovar.clicked.connect(lambda: responder(self._id, True, False))
        self._negar.clicked.connect(lambda: responder(self._id, False, False))
        self._sempre.clicked.connect(lambda: responder(self._id, True, True))

    def resolver(self, aprovado: bool, por: str) -> None:
        for botao in (self._aprovar, self._negar, self._sempre):
            botao.setEnabled(False)
        complemento = {"voz": " por voz", "tempo esgotado": " (sem resposta a tempo)", "parar": " (cancelado)"}.get(por, "")
        self._situacao.setText(("Aprovado" if aprovado else "Negado") + complemento)
        self._situacao.show()
        self.setObjectName("cartao")
        _repolir(self)


class CartaoLogin(QFrame):
    """Explica e resolve a falta de login no Claude Code."""

    def __init__(self, fazer_login: Callable[[], bool], confirmar: Callable[[], None]) -> None:
        super().__init__()
        self.setObjectName("cartaoAprovacao")
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(14, 12, 14, 12)
        coluna.setSpacing(8)
        coluna.addWidget(rotulo("LOGIN", "autor", selecionavel=False))
        coluna.addWidget(rotulo("Falta entrar com a sua conta no Claude Code", "tituloCartao"))
        coluna.addWidget(
            rotulo(
                "O app usa o Claude Code instalado neste PC, com a sua conta do Claude (a mesma do Claude Desktop). "
                "Clique em **Fazer login**: abre uma janela que leva você ao site da Anthropic para entrar. "
                "Depois volte aqui e clique em **Já fiz login**.",
                markdown=True,
            )
        )
        coluna.addWidget(rotulo("Isso usa a sua assinatura do Claude, não uma chave de API.", "meta", selecionavel=False))
        botoes = QHBoxLayout()
        self._login = QPushButton("Fazer login")
        self._login.setObjectName("primario")
        self._confirmar = QPushButton("Já fiz login")
        botoes.addWidget(self._login)
        botoes.addWidget(self._confirmar)
        botoes.addStretch(1)
        coluna.addLayout(botoes)
        self._situacao = rotulo("", "meta", selecionavel=False)
        self._situacao.hide()
        coluna.addWidget(self._situacao)
        self._login.clicked.connect(lambda: self._abrir(fazer_login))
        self._confirmar.clicked.connect(confirmar)
        self.concluido = False

    def _abrir(self, fazer_login: Callable[[], bool]) -> None:
        if fazer_login():
            self._situacao.setText("Abri a janela de login. Termine de entrar no navegador e clique em “Já fiz login”.")
        else:
            self._situacao.setText("Não achei o Claude Code para abrir o login.")
        self._situacao.show()

    def concluir(self) -> None:
        self.concluido = True
        self._login.setEnabled(False)
        self._confirmar.setEnabled(False)
        self._situacao.setText("Login feito. Pode falar com o Claude.")
        self._situacao.show()
        self.setObjectName("cartao")
        _repolir(self)


class CartaoInfo(QFrame):
    def __init__(self, titulo: str, texto_markdown: str = "") -> None:
        super().__init__()
        self.setObjectName("cartao")
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(16, 14, 16, 14)
        coluna.setSpacing(8)
        coluna.addWidget(rotulo(titulo, "tituloCartao"))
        corpo = rotulo(texto_markdown, markdown=True)
        coluna.addWidget(corpo)
        corpo.setVisible(bool(texto_markdown))


class CartaoCarregando(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("cartao")
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(16, 14, 16, 14)
        coluna.setSpacing(10)
        coluna.addWidget(rotulo("Preparando o assistente", "tituloCartao", selecionavel=False))
        self._mensagem = rotulo("Começando…", "aviso", selecionavel=False)
        coluna.addWidget(self._mensagem)
        self._barra = QProgressBar()
        self._barra.setTextVisible(False)
        self._barra.setRange(0, 0)
        coluna.addWidget(self._barra)

    def atualizar(self, mensagem: str, fracao: float | None) -> None:
        self._mensagem.setText(mensagem)
        if fracao is None:
            self._barra.setRange(0, 0)
        else:
            self._barra.setRange(0, 1000)
            self._barra.setValue(int(fracao * 1000))


class LinhaAviso(QWidget):
    def __init__(self, texto: str, erro: bool = False) -> None:
        super().__init__()
        linha = QHBoxLayout(self)
        linha.setContentsMargins(8, 0, 8, 0)
        item = rotulo(texto, "avisoErro" if erro else "aviso")
        item.setAlignment(Qt.AlignmentFlag.AlignCenter)
        linha.addWidget(item)


class PainelEspera(QFrame):
    """Acima da caixa de texto: o pedido que você está falando (com a contagem) e a fila de pedidos."""

    def __init__(
        self, enviar: Callable[[], None], descartar: Callable[[], None], tirar_da_fila: Callable[[str], None]
    ) -> None:
        super().__init__()
        self.setObjectName("cartao")
        self._tirar_da_fila = tirar_da_fila
        self._envia_em = 0.0
        self._palavra = ""
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(14, 10, 14, 10)
        coluna.setSpacing(6)

        self._caixa_rascunho = QWidget()
        rascunho = QVBoxLayout(self._caixa_rascunho)
        rascunho.setContentsMargins(0, 0, 0, 0)
        rascunho.setSpacing(4)
        rascunho.addWidget(rotulo("SEU PEDIDO · AINDA NÃO FOI", "autor", selecionavel=False))
        self._texto = rotulo("", "textoUsuario")
        rascunho.addWidget(self._texto)
        linha = QHBoxLayout()
        self._contagem = rotulo("", "meta", selecionavel=False)
        linha.addWidget(self._contagem, 1)
        linha.addWidget(botao_pequeno("Mandar agora", enviar, "Manda já, sem esperar o silêncio"))
        linha.addWidget(botao_pequeno("Descartar", descartar, "Joga fora o pedido (por voz: “cancela”)"))
        rascunho.addLayout(linha)
        coluna.addWidget(self._caixa_rascunho)

        self._caixa_fila = QWidget()
        self._fila = QVBoxLayout(self._caixa_fila)
        self._fila.setContentsMargins(0, 0, 0, 0)
        self._fila.setSpacing(4)
        coluna.addWidget(self._caixa_fila)

        self._relogio = QTimer(self)
        self._relogio.setInterval(250)
        self._relogio.timeout.connect(self._atualizar_contagem)
        self._caixa_rascunho.hide()
        self._caixa_fila.hide()
        self.hide()

    def definir_rascunho(self, rascunho: ev.Rascunho) -> None:
        self._envia_em, self._palavra = rascunho.envia_em, rascunho.palavra
        self._texto.setText(rascunho.texto)
        self._caixa_rascunho.setVisible(bool(rascunho.texto))
        if rascunho.texto:
            self._relogio.start()
            self._atualizar_contagem()
        else:
            self._relogio.stop()
        self._ajustar_visibilidade()

    def definir_fila(self, itens: list[tuple[str, str]]) -> None:
        while self._fila.count():
            item = self._fila.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
            elif item.layout() is not None:
                while item.layout().count():
                    filho = item.layout().takeAt(0)
                    if filho.widget() is not None:
                        filho.widget().deleteLater()
        if itens:
            titulo = "NA FILA · VAI QUANDO O CLAUDE TERMINAR"
            self._fila.addWidget(rotulo(titulo, "autor", selecionavel=False))
        for id_, texto in itens:
            linha = QHBoxLayout()
            linha.addWidget(rotulo(texto), 1)
            linha.addWidget(botao_pequeno("✕", lambda i=id_: self._tirar_da_fila(i), "Tira da fila"))
            self._fila.addLayout(linha)
        self._caixa_fila.setVisible(bool(itens))
        self._ajustar_visibilidade()

    def _ajustar_visibilidade(self) -> None:
        self.setVisible(self._caixa_rascunho.isVisibleTo(self) or self._caixa_fila.isVisibleTo(self))

    def _atualizar_contagem(self) -> None:
        palavra = f"“{self._palavra}”" if self._palavra else "a palavra de envio"
        if self._envia_em <= 0:
            texto = f"Ouvindo… pode continuar. Diga {palavra} para mandar já."
        else:
            restante = self._envia_em - time.monotonic()
            quando = f"Mando em {math.ceil(restante)} s" if restante > 0.05 else "Mandando…"
            texto = f"{quando} · continue falando para completar, ou diga {palavra}."
        self._contagem.setText(texto)


class ListaConversa(QScrollArea):
    """A conversa, com rolagem que acompanha o fim enquanto você não rola para cima."""

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.viewport().setAutoFillBackground(False)  # transparente: o fundo vivo da janela aparece
        self._conteudo = QWidget()
        self._conteudo.setObjectName("lista")
        self._conteudo.setAutoFillBackground(False)
        self._coluna = QVBoxLayout(self._conteudo)
        self._coluna.setContentsMargins(2, 4, 4, 4)
        self._coluna.setSpacing(10)
        self._coluna.addStretch(1)
        self.setWidget(self._conteudo)
        self._grudado = True
        barra = self.verticalScrollBar()
        barra.rangeChanged.connect(self._ao_mudar_altura)
        barra.valueChanged.connect(self._ao_rolar)

    def adicionar(self, widget: QWidget) -> QWidget:
        self._coluna.insertWidget(self._coluna.count() - 1, widget)
        self._ajustar_larguras()
        return widget

    def remover(self, widget: QWidget) -> None:
        self._coluna.removeWidget(widget)
        widget.deleteLater()

    def limpar(self) -> None:
        while self._coluna.count() > 1:
            item = self._coluna.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._grudado = True

    def rolar_para_o_fim(self) -> None:
        self._grudado = True
        barra = self.verticalScrollBar()
        barra.setValue(barra.maximum())

    def _ao_rolar(self, valor: int) -> None:
        self._grudado = valor >= self.verticalScrollBar().maximum() - 40

    def _ao_mudar_altura(self, _minimo: int, maximo: int) -> None:
        if self._grudado:
            self.verticalScrollBar().setValue(maximo)

    def _ajustar_larguras(self) -> None:
        limite = max(220, int(self.viewport().width() * 0.82))
        for i in range(self._coluna.count()):
            widget = self._coluna.itemAt(i).widget()
            if isinstance(widget, BolhaUsuario):
                widget.ajustar(limite)

    def resizeEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        super().resizeEvent(evento)
        self._ajustar_larguras()


def renderizar_entradas(lista: ListaConversa, entradas: list[dict]) -> None:
    """Desenha uma conversa salva (do histórico) na lista."""
    bloco: BlocoResposta | None = None
    pedidos: dict[str, dict] = {}
    for entrada in entradas:
        tipo = entrada.get("tipo")
        if tipo == "voce":
            lista.adicionar(BolhaUsuario(entrada.get("texto", ""), entrada.get("origem", "voz")))
            bloco = None
        elif tipo == "inicio_resposta":
            bloco = lista.adicionar(BlocoResposta(do_historico=True))
        elif tipo in ("claude", "acao", "fim"):
            if bloco is None or bloco.finalizado:
                bloco = lista.adicionar(BlocoResposta(do_historico=True))
            if tipo == "claude":
                bloco.adicionar_texto(entrada.get("texto", ""))
            elif tipo == "acao":
                bloco.adicionar_acao(entrada.get("texto", ""))
            else:
                arquivos = [c for c in entrada.get("arquivos") or [] if os.path.exists(c)]
                bloco.finalizar(
                    ev.FimResposta(
                        entrada.get("fala", ""),
                        float(entrada.get("duracao") or 0.0),
                        entrada.get("custo"),
                        entrada.get("erro", ""),
                        bool(entrada.get("interrompida")),
                        arquivos=arquivos,
                    )
                )
        elif tipo == "pedido":
            pedidos[entrada.get("id", "")] = entrada
        elif tipo == "resposta_pedido":
            pedido = pedidos.pop(entrada.get("id", ""), {})
            resultado = "aprovado" if entrada.get("aprovado") else "negado"
            lista.adicionar(LinhaAviso(f"Permissão: {pedido.get('pergunta', '')} → {resultado}"))
        elif tipo == "aviso":
            lista.adicionar(LinhaAviso(entrada.get("texto", ""), entrada.get("nivel") == "erro"))
    if bloco is not None and not bloco.finalizado:
        bloco.finalizar(ev.FimResposta("", 0.0, None, interrompida=True))
