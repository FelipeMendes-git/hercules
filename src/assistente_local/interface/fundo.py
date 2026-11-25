"""O fundo vivo da janela: manchas de cor suaves que flutuam devagar e mudam de cor junto com a bolha.

Os painéis de vidro (translúcidos) ficam por cima. O movimento é lento, então 8 quadros por segundo
bastam; com a janela atrás de outras, cai para 2, e para de vez quando ela fica escondida.
"""

from __future__ import annotations

import math
import time
from typing import Callable

from PySide6.QtCore import QPointF, QTimer
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

from ..eventos import Estado
from .tema import COR_TRABALHANDO, CORES, ESTADOS


def _misturar(a: QColor, b: QColor, k: float) -> QColor:
    return QColor(
        round(a.red() + (b.red() - a.red()) * k),
        round(a.green() + (b.green() - a.green()) * k),
        round(a.blue() + (b.blue() - a.blue()) * k),
    )


def _girar(cor: QColor, graus: float) -> QColor:
    h, s, v, a = cor.getHsvF()
    return QColor.fromHsvF(((h if h >= 0 else 0.0) + graus / 360.0) % 1.0, s, v, a)


def cores_do_fundo(estado: Estado, trabalhando: bool = False) -> list[str]:
    """As três cores das manchas: a do estado (a mesma da bolha) e duas vizinhas, em tom pastel."""
    if trabalhando and estado is Estado.PENSANDO:
        base = QColor(COR_TRABALHANDO)
    else:
        base = QColor(ESTADOS.get(estado, ("", "#8a8fa8"))[1])
    if estado is Estado.ESPERA:
        base = _misturar(base, QColor("#9a96b8"), 0.35)
    return [_misturar(cor, QColor("#ffffff"), 0.35).name() for cor in (base, _girar(base, 48), _girar(base, -55))]


class FundoVivo(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._estado = Estado.CARREGANDO
        self._fonte_trabalhando: Callable[[], bool] | None = None
        self._cores = [QColor(c) for c in cores_do_fundo(self._estado)]
        self._inicio = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(125)
        self._timer.timeout.connect(self._passo)

    def definir_estado(self, estado: Estado) -> None:
        self._estado = estado

    def definir_fonte_trabalhando(self, fonte: Callable[[], bool] | None) -> None:
        """Diz se o Claude está usando ferramentas agora (o fundo fica na cor de "trabalhando")."""
        self._fonte_trabalhando = fonte

    def showEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        super().showEvent(evento)
        self._timer.start()

    def hideEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        super().hideEvent(evento)
        self._timer.stop()

    def _passo(self) -> None:
        ativa = self.window().isActiveWindow()
        intervalo = 125 if ativa else 500
        if self._timer.interval() != intervalo:
            self._timer.setInterval(intervalo)
        trabalhando = bool(self._fonte_trabalhando and self._fonte_trabalhando())
        alvo = [QColor(c) for c in cores_do_fundo(self._estado, trabalhando)]
        passo = 0.2 if ativa else 0.5  # a cor muda em pouco mais de um segundo
        self._cores = [_misturar(c, a, passo) for c, a in zip(self._cores, alvo)]
        self.update()

    def paintEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(CORES["fundo"]))
        w, h = float(self.width()), float(self.height())
        t = time.monotonic() - self._inicio
        manchas = (
            (0.25 + 0.15 * math.sin(t * 0.11), 0.18 + 0.08 * math.cos(t * 0.09), 0.85),
            (0.85 + 0.10 * math.cos(t * 0.08), 0.50 + 0.12 * math.sin(t * 0.10), 0.75),
            (0.30 + 0.18 * math.cos(t * 0.07 + 1), 0.90 + 0.06 * math.sin(t * 0.12), 0.80),
        )
        alfa = 0.5 * (0.6 if self._estado is Estado.ESPERA else 1.0)
        for i, (fx, fy, fr) in enumerate(manchas):
            raio = fr * w * (1 + 0.05 * math.sin(t * 0.3 + i))
            gradiente = QRadialGradient(QPointF(fx * w, fy * h), raio)
            for posicao, fator in ((0.0, 1.0), (0.55, 0.35), (1.0, 0.0)):
                cor = QColor(self._cores[i])
                cor.setAlphaF(alfa * fator)
                gradiente.setColorAt(posicao, cor)
            p.fillRect(self.rect(), gradiente)
        p.end()
