"""A bolha do Hércules: uma gota colorida que ondula com o som e muda de cor e de movimento conforme o estado.

- Cochilando (em espera): apagadinha, respira bem devagar.
- Na escuta / pode falar: verde, ondulando de leve.
- Ouvindo você: rosa, ondula com o volume do microfone.
- Pensando: azul, com um brilho girando em volta. Trabalhando (o Claude usando ferramentas):
  ciano, ondula mais rápido e gira em três pedaços.
- Falando: âmbar, ondula no ritmo da voz de verdade (o volume do que está tocando).
- Pedindo permissão: laranja, piscando. Erro: vermelha, tremendo.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from ..eventos import Estado
from .tema import COR_TRABALHANDO, ESTADOS

CORES_DA_BOLHA: dict[Estado, str] = {estado: cor for estado, (_texto, cor) in ESTADOS.items()}
_REAGEM_AO_SOM = {Estado.FALANDO, Estado.GRAVANDO}
_RAPIDOS = {
    Estado.CARREGANDO,
    Estado.ACORDANDO,
    Estado.GRAVANDO,
    Estado.TRANSCREVENDO,
    Estado.PENSANDO,
    Estado.FALANDO,
    Estado.APROVACAO,
    Estado.ERRO,
}
_SEGUNDOS_TRABALHANDO = 3.0  # depois de cada ação do Claude, a bolha fica com cara de "trabalhando"


@dataclass
class Aparencia:
    cor: str
    amplitude: float  # quanto a borda ondula (fração do raio)
    velocidade: float  # quão rápido as ondas andam
    forca: float  # brilho em volta (0 a 1)
    respiro: float  # aumento ou diminuição do tamanho agora
    apagada: float  # 1 = cor cheia; menos = apagadinha
    giro: float  # voltas por segundo do brilho que gira (0 = sem)
    pedacos: int  # 1 (pensando) ou 3 (trabalhando)
    tremor: float  # deslocamento para o lado (erro)


def _misturar(cor: str, alvo: str, k: float) -> str:
    a, b = QColor(cor), QColor(alvo)
    return QColor(
        round(a.red() + (b.red() - a.red()) * k),
        round(a.green() + (b.green() - a.green()) * k),
        round(a.blue() + (b.blue() - a.blue()) * k),
    ).name()


def aparencia(estado: Estado, t: float, nivel: float = 0.0, trabalhando: bool = False) -> Aparencia:
    """Como a bolha está agora: ``t`` em segundos e ``nivel`` (0 a 1) do som que ela acompanha."""
    reage = estado in _REAGEM_AO_SOM
    trabalhando = trabalhando and estado is Estado.PENSANDO
    cor = COR_TRABALHANDO if trabalhando else CORES_DA_BOLHA.get(estado, "#8a8fa8")
    if estado is Estado.ESPERA:
        cor = _misturar(cor, "#5a5675", 0.35)
    piscando = 0.5 + 0.5 * math.sin(t * 7.0)
    girando = estado in (Estado.PENSANDO, Estado.TRANSCREVENDO, Estado.ACORDANDO, Estado.CARREGANDO)

    if reage:
        forca, amplitude, velocidade = nivel, 0.04 + 0.2 * nivel, 2.0
    elif trabalhando:
        forca, amplitude, velocidade = 0.3 + 0.1 * math.sin(t * 3.0), 0.10, 2.4
    elif girando:
        forca, amplitude, velocidade = 0.3 + 0.1 * math.sin(t * 3.0), 0.07 if estado is not Estado.CARREGANDO else 0.05, 1.3
    elif estado is Estado.APROVACAO:
        forca, amplitude, velocidade = 0.3 + 0.45 * piscando, 0.05 + 0.05 * math.sin(t * 7.0), 0.9
    elif estado is Estado.ERRO:
        forca, amplitude, velocidade = 0.55, 0.05, 1.2
    elif estado is Estado.ESPERA:
        forca, amplitude, velocidade = 0.05, 0.035, 0.7
    elif estado in (Estado.CONVERSA, Estado.RASCUNHO):
        forca, amplitude, velocidade = 0.25 + 0.1 * math.sin(t * 3.0), 0.045, 1.0
    else:
        forca, amplitude, velocidade = 0.18, 0.035, 0.7

    if reage:
        respiro = 0.0
    elif estado is Estado.ESPERA:
        respiro = 0.035 * math.sin(t * 0.9)
    else:
        respiro = 0.02 * math.sin(t * 1.7)

    if trabalhando:
        giro, pedacos = 1.3, 3
    elif estado is Estado.PENSANDO:
        giro, pedacos = 0.45, 1
    elif estado is Estado.TRANSCREVENDO:
        giro, pedacos = 0.6, 1
    elif estado in (Estado.ACORDANDO, Estado.CARREGANDO):
        giro, pedacos = 0.35, 1
    else:
        giro, pedacos = 0.0, 0

    apagada = 0.55 if estado is Estado.ESPERA else 0.6 if estado is Estado.MUDO else 1.0
    tremor = math.sin(t * 46.0) * max(0.0, 1.0 - (t % 2.4) / 0.5) if estado is Estado.ERRO else 0.0
    return Aparencia(cor, amplitude, velocidade, max(0.0, min(1.0, forca)), respiro, apagada, giro, pedacos, tremor)


def _fala_de_mentira(t: float) -> float:
    """Volume parecido com o de uma fala (para quando não há som de verdade, como nas prévias)."""
    silaba = max(0.0, math.sin(t * 2 * math.pi * 4.4)) ** 1.4
    palavras = 1.0 if math.sin(t * 2 * math.pi * 0.85) + math.sin(t * 2 * math.pi * 0.37 + 1) > -0.7 else 0.08
    return 0.12 + 0.78 * silaba * palavras * (0.78 + 0.22 * math.sin(t * 13))


def _com_alfa(cor: QColor, alfa: float) -> QColor:
    nova = QColor(cor)
    nova.setAlphaF(max(0.0, min(1.0, alfa)))
    return nova


def _girar_matiz(cor: QColor, graus: float) -> QColor:
    h, s, v, a = cor.getHsvF()
    return QColor.fromHsvF(((h if h >= 0 else 0.0) + graus / 360.0) % 1.0, s, v, a)


class Orbe(QWidget):
    def __init__(self, tamanho: int = 64, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(tamanho, tamanho)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._estado = Estado.CARREGANDO
        self._mic = 0.0
        self._nivel = 0.0
        self._fonte_voz: Callable[[], float] | None = None
        self._trabalho_ate = 0.0
        self._inicio = time.monotonic()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._passo)
        self._ajustar_ritmo()

    # ------------------------------------------------------------------ dados
    def definir_estado(self, estado: Estado) -> None:
        self._estado = estado
        self._ajustar_ritmo()
        self.update()

    def definir_nivel(self, nivel: float) -> None:
        """Volume do microfone (0 a 1)."""
        self._mic = max(float(nivel), self._mic * 0.8)

    def definir_fonte_voz(self, fonte: Callable[[], float] | None) -> None:
        """Função que diz o volume do que o Hércules está falando agora."""
        self._fonte_voz = fonte

    def marcar_acao(self, ferramenta: str = "") -> None:
        """O Claude usou uma ferramenta: a bolha fica com cara de "trabalhando" por alguns segundos."""
        self._trabalho_ate = time.monotonic() + _SEGUNDOS_TRABALHANDO

    @property
    def trabalhando(self) -> bool:
        return self._estado is Estado.PENSANDO and time.monotonic() < self._trabalho_ate

    # ------------------------------------------------------------------ animação
    def _ajustar_ritmo(self) -> None:
        if self._estado in _RAPIDOS:
            self._timer.setInterval(33)
        elif self._estado is Estado.ESPERA:
            self._timer.setInterval(80)  # quase parada: gasta quase nada enquanto cochila
        else:
            self._timer.setInterval(50)

    def showEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        super().showEvent(evento)
        self._timer.start()

    def hideEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        super().hideEvent(evento)
        self._timer.stop()

    def _volume_da_voz(self, t: float) -> float:
        if self._fonte_voz is None:
            return _fala_de_mentira(t) * 0.16
        try:
            return float(self._fonte_voz())
        except Exception:
            return 0.0

    def _passo(self) -> None:
        t = time.monotonic() - self._inicio
        if self._estado is Estado.FALANDO:
            alvo = min(1.0, self._volume_da_voz(t) / 0.16)
        elif self._estado is Estado.GRAVANDO:
            alvo = min(1.0, self._mic * 1.6)
        else:
            alvo = 0.0
        self._nivel += (alvo - self._nivel) * (0.55 if alvo > self._nivel else 0.16)
        self._mic *= 0.85
        self.update()

    # ------------------------------------------------------------------ desenho
    def paintEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        t = time.monotonic() - self._inicio
        a = aparencia(self._estado, t, self._nivel, self.trabalhando)
        lado = float(min(self.width(), self.height()))
        c = QPointF(self.width() / 2 + a.tremor * lado * 0.012, self.height() / 2)
        raio = lado * 0.26 * (1.0 + a.respiro)
        cor = QColor(a.cor)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # brilho em volta (mais forte com o som)
        alcance = min(lado / 2, raio + lado * (0.08 + 0.16 * a.forca))
        halo = QRadialGradient(c, alcance)
        borda = min(0.99, raio * 0.95 / alcance)
        halo.setColorAt(0.0, _com_alfa(cor, (0.45 + 0.4 * a.forca) * a.apagada))
        halo.setColorAt(borda, _com_alfa(cor, (0.45 + 0.4 * a.forca) * a.apagada))
        halo.setColorAt(1.0, _com_alfa(cor, 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(c, alcance, alcance)

        # a gota: um círculo com três ondas somadas na borda
        pontos = []
        for i in range(90):
            ang = 2 * math.pi * i / 90
            onda = (
                0.55 * math.sin(3 * ang + t * a.velocidade * 1.3)
                + 0.30 * math.sin(5 * ang - t * a.velocidade * 1.7 + 1)
                + 0.15 * math.sin(7 * ang + t * a.velocidade * 2.3 + 2)
            )
            r = raio * (1.0 + a.amplitude * onda)
            pontos.append(QPointF(c.x() + math.cos(ang) * r, c.y() + math.sin(ang) * r))
        gota = QPainterPath()
        gota.moveTo((pontos[-1] + pontos[0]) * 0.5)
        for i, ponto in enumerate(pontos):
            gota.quadTo(ponto, (ponto + pontos[(i + 1) % len(pontos)]) * 0.5)
        gota.closeSubpath()
        tinta = QLinearGradient(c.x() - raio, c.y() - raio, c.x() + raio, c.y() + raio)
        tinta.setColorAt(0.0, _com_alfa(QColor(_misturar(_girar_matiz(cor, -35).name(), "#ffffff", 0.15)), a.apagada))
        tinta.setColorAt(0.55, _com_alfa(cor, a.apagada))
        tinta.setColorAt(1.0, _com_alfa(_girar_matiz(cor, 40), a.apagada))
        p.setBrush(tinta)
        p.drawPath(gota)

        # reflexo no alto, à esquerda
        p.save()
        p.setClipPath(gota)
        luz = QRadialGradient(QPointF(c.x() - raio * 0.35, c.y() - raio * 0.4), raio * 0.8)
        luz.setColorAt(0.0, _com_alfa(QColor("#ffffff"), 0.45 * a.apagada))
        luz.setColorAt(1.0, _com_alfa(QColor("#ffffff"), 0.0))
        p.setBrush(luz)
        p.drawEllipse(c, raio * 1.3, raio * 1.3)
        p.restore()

        # brilho girando em volta enquanto pensa (três pedaços quando está trabalhando)
        if a.giro:
            self._desenhar_giro(p, c, raio * 1.35, cor, t, lado, a)
        p.end()

    @staticmethod
    def _desenhar_giro(p: QPainter, c: QPointF, r: float, cor: QColor, t: float, lado: float, a: Aparencia) -> None:
        comprimento = 0.7 if a.pedacos > 1 else 1.9  # radianos
        caixa = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
        clara = QColor(_misturar(cor.name(), "#ffffff", 0.35))
        for pedaco in range(a.pedacos):
            inicio = t * a.giro * 2 * math.pi + pedaco * 2 * math.pi / a.pedacos
            for k in range(14):  # da ponta para o rabo, cada pedacinho mais apagado
                caneta = QPen(_com_alfa(clara, (1 - k / 14) * 0.95), max(1.0, lado * 0.018 * (1 - k / 22)))
                caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(caneta)
                ponta = inicio - k * comprimento / 14
                # o ângulo do Qt cresce no sentido anti-horário; o da animação, no horário
                p.drawArc(caixa, int(-math.degrees(ponta) * 16), int(math.degrees(comprimento / 14) * 16))
