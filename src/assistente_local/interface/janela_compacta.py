"""A bolinha flutuante do Hércules: só a bolha, que pulsa com o som e muda conforme o estado (``orbe.py``).

Aparece quando a janela principal está fechada ou minimizada. Clique abre a janela (conversas e
configurações); arrastar muda o lugar (o app lembra); o botão direito abre o menu. Passando o mouse,
aparecem o estado, o que o Claude está fazendo, o modelo e o esforço.

"Sempre em primeiro plano" (no menu e nas configurações): ligado, a bolinha fica por cima de todas as
janelas; desligado, vira uma janela comum, com botão na barra de tarefas, que pode ficar atrás das outras.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget

from .. import eventos as ev
from ..marca import ID_APP, NOME_APP
from . import icones
from .orbe import Orbe
from .tema import ESTADOS

_TAMANHO = 126


class JanelaCompacta(QWidget):
    def __init__(
        self,
        menu: QMenu,
        ao_clicar: Callable[[], None],
        nome_ativacao: str = "",
        fonte_voz: Callable[[], float] | None = None,
        no_topo: bool = True,
    ) -> None:
        super().__init__(None)
        self.setWindowTitle(NOME_APP)
        self.setWindowIcon(icones.icone_app())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._menu = menu
        self._ao_clicar = ao_clicar
        self.nome_ativacao = nome_ativacao
        self.no_topo = no_topo
        self._aplicar_bandeiras()
        self._estado = ev.Estado.CARREGANDO
        self._detalhe = ""
        self._acao = ""
        self._info = ""
        self._clique: QPoint | None = None
        self._arrastou = False
        self._preferencias = QSettings(ID_APP, "janela_compacta")
        caixa = QVBoxLayout(self)
        caixa.setContentsMargins(0, 0, 0, 0)
        self.orbe = Orbe(_TAMANHO)
        self.orbe.setCursor(Qt.CursorShape.PointingHandCursor)
        self.orbe.definir_fonte_voz(fonte_voz)
        caixa.addWidget(self.orbe)
        self.setFixedSize(_TAMANHO, _TAMANHO)
        self._ancora = self._ancora_salva()  # centro da bolinha na tela
        self._posicionar()
        self._atualizar_dica()

    # ------------------------------------------------------------------ primeiro plano
    def _aplicar_bandeiras(self) -> None:
        bandeiras = Qt.WindowType.FramelessWindowHint
        if self.no_topo:  # por cima de tudo, sem botão na barra de tarefas
            bandeiras |= Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
        else:  # janela comum: vai para frente ou para trás das outras
            bandeiras |= Qt.WindowType.Window
        self.setWindowFlags(bandeiras)

    def definir_no_topo(self, ligado: bool) -> None:
        if ligado == self.no_topo:
            return
        visivel = self.isVisible()
        self.no_topo = ligado
        self._aplicar_bandeiras()  # trocar as bandeiras esconde a janela; mostra de novo se estava à vista
        self._posicionar()
        if visivel:
            self.show()

    # ------------------------------------------------------------------ eventos do controlador
    def tratar_evento(self, evento: object) -> None:
        if isinstance(evento, ev.NivelMicrofone):
            self.orbe.definir_nivel(evento.nivel)
            return
        if isinstance(evento, ev.EstadoMudou):
            self._estado, self._detalhe = evento.estado, evento.detalhe
            self.orbe.definir_estado(evento.estado)
            if evento.estado is not ev.Estado.PENSANDO:
                self._acao = ""
        elif isinstance(evento, ev.AcaoClaude):
            self.orbe.marcar_acao(evento.ferramenta)
            self._acao = evento.descricao
        elif isinstance(evento, ev.InfoClaude):
            self._info = f"⚡ {evento.modelo} · esforço {evento.esforco} · 🛡 {evento.permissao}"
        else:
            return
        self._atualizar_dica()

    def _atualizar_dica(self) -> None:
        texto = ESTADOS.get(self._estado, ("", ""))[0].format(nome=self.nome_ativacao, detalhe=self._detalhe)
        if self._estado is ev.Estado.ERRO and self._detalhe:
            texto = f"Erro: {self._detalhe[:120]}"
        linhas = [f"{NOME_APP} · {texto}"]
        if self._acao and self._estado is ev.Estado.PENSANDO:
            linhas.append(self._acao[:120])
        if self._info:
            linhas.append(self._info)
        linhas.append("Clique para abrir · arraste para mover · botão direito: menu")
        self.orbe.setToolTip("\n".join(linhas))

    # ------------------------------------------------------------------ posição
    def _ancora_salva(self) -> QPoint:
        x, y = self._preferencias.value("x"), self._preferencias.value("y")
        if x is not None and y is not None:
            ponto = QPoint(int(x), int(y))
            if QGuiApplication.screenAt(ponto) is not None:
                return ponto
        area = QGuiApplication.primaryScreen().availableGeometry()
        return QPoint(area.right() - _TAMANHO // 2 - 18, area.bottom() - _TAMANHO // 2 - 18)

    def _posicionar(self) -> None:
        tela = QGuiApplication.screenAt(self._ancora) or QGuiApplication.primaryScreen()
        area = tela.availableGeometry()
        x = max(area.left(), min(self._ancora.x() - _TAMANHO // 2, area.right() - _TAMANHO))
        y = max(area.top(), min(self._ancora.y() - _TAMANHO // 2, area.bottom() - _TAMANHO))
        self.move(x, y)

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        if evento.button() == Qt.MouseButton.LeftButton:
            self._clique = evento.globalPosition().toPoint()
            self._inicio_janela = self.pos()
            self._arrastou = False
        elif evento.button() == Qt.MouseButton.RightButton:
            self._menu.popup(evento.globalPosition().toPoint())

    def mouseMoveEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        if self._clique is None:
            return
        delta = evento.globalPosition().toPoint() - self._clique
        if not self._arrastou and delta.manhattanLength() < 5:
            return
        self._arrastou = True
        self.move(self._inicio_janela + delta)

    def mouseReleaseEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        if evento.button() != Qt.MouseButton.LeftButton or self._clique is None:
            return
        self._clique = None
        if self._arrastou:
            self._ancora = self.mapToGlobal(self.rect().center())
            self._preferencias.setValue("x", self._ancora.x())
            self._preferencias.setValue("y", self._ancora.y())
            self._posicionar()
        else:
            self._ao_clicar()
