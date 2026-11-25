"""Ícones desenhados na hora (sem arquivos de imagem)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

_TAMANHOS = (16, 20, 24, 32, 40, 48, 64, 128, 256)
_cache: dict[str, QIcon] = {}


def _desenhar_microfone(pintor: QPainter, area: QRectF, cor: QColor, espessura: float) -> None:
    largura, altura = area.width(), area.height()
    centro_x = area.center().x()
    capsula = QRectF(centro_x - largura * 0.16, area.top() + altura * 0.06, largura * 0.32, altura * 0.50)
    pintor.setPen(Qt.PenStyle.NoPen)
    pintor.setBrush(cor)
    pintor.drawRoundedRect(capsula, largura * 0.16, largura * 0.16)
    caneta = QPen(cor, espessura)
    caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
    pintor.setPen(caneta)
    pintor.setBrush(Qt.BrushStyle.NoBrush)
    arco = QRectF(centro_x - largura * 0.28, area.top() + altura * 0.20, largura * 0.56, altura * 0.50)
    pintor.drawArc(arco, 200 * 16, 140 * 16)
    pintor.drawLine(QPointF(centro_x, area.top() + altura * 0.72), QPointF(centro_x, area.top() + altura * 0.88))
    pintor.drawLine(
        QPointF(centro_x - largura * 0.15, area.top() + altura * 0.90),
        QPointF(centro_x + largura * 0.15, area.top() + altura * 0.90),
    )


def icone_app(cor: str = "#7aa2ff") -> QIcon:
    """Círculo colorido com um microfone branco. A cor muda conforme o estado (na bandeja)."""
    if cor in _cache:
        return _cache[cor]
    icone = QIcon()
    for tamanho in _TAMANHOS:
        imagem = QPixmap(tamanho, tamanho)
        imagem.fill(Qt.GlobalColor.transparent)
        pintor = QPainter(imagem)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QColor(cor))
        margem = max(1.0, tamanho * 0.03)
        pintor.drawEllipse(QRectF(margem, margem, tamanho - 2 * margem, tamanho - 2 * margem))
        area = QRectF(tamanho * 0.22, tamanho * 0.18, tamanho * 0.56, tamanho * 0.64)
        _desenhar_microfone(pintor, area, QColor("white"), max(1.2, tamanho * 0.075))
        pintor.end()
        icone.addPixmap(imagem)
    _cache[cor] = icone
    return icone


# ---------------------------------------------------------------------- ícones de linha (botões)
_cache_linha: dict[tuple[str, str], QIcon] = {}


def _tracar(pintor: QPainter, nome: str, s: float) -> None:
    """Desenha o ícone ``nome`` num quadrado de lado ``s`` (traço já configurado no pintor)."""
    from PySide6.QtGui import QPainterPath

    m = s / 2
    if nome in ("mic", "mic_off"):
        pintor.drawRoundedRect(QRectF(s * 0.37, s * 0.12, s * 0.26, s * 0.46), s * 0.13, s * 0.13)
        pintor.drawArc(QRectF(s * 0.24, s * 0.28, s * 0.52, s * 0.44), 200 * 16, 140 * 16)
        pintor.drawLine(QPointF(m, s * 0.72), QPointF(m, s * 0.86))
        pintor.drawLine(QPointF(s * 0.36, s * 0.86), QPointF(s * 0.64, s * 0.86))
        if nome == "mic_off":
            pintor.drawLine(QPointF(s * 0.18, s * 0.14), QPointF(s * 0.82, s * 0.86))
    elif nome == "historico":
        pintor.drawArc(QRectF(s * 0.16, s * 0.16, s * 0.68, s * 0.68), 120 * 16, 300 * 16)
        caminho = QPainterPath(QPointF(s * 0.12, s * 0.30))
        caminho.lineTo(QPointF(s * 0.22, s * 0.40))
        caminho.lineTo(QPointF(s * 0.34, s * 0.31))
        pintor.drawPath(caminho)
        pintor.drawLine(QPointF(m, s * 0.32), QPointF(m, m))
        pintor.drawLine(QPointF(m, m), QPointF(s * 0.63, s * 0.60))
    elif nome == "config":
        import math

        pintor.drawEllipse(QPointF(m, m), s * 0.12, s * 0.12)
        caminho = QPainterPath()
        dentes = 8
        for i in range(dentes * 2):
            ang = math.pi * 2 * i / (dentes * 2)
            for k, raio in enumerate((0.36, 0.36) if i % 2 == 0 else (0.27, 0.27)):
                a = ang + (k - 0.5) * math.pi / (dentes * 2) * 0.9
                ponto = QPointF(m + s * raio * math.cos(a), m + s * raio * math.sin(a))
                if i == 0 and k == 0:
                    caminho.moveTo(ponto)
                else:
                    caminho.lineTo(ponto)
        caminho.closeSubpath()
        pintor.drawPath(caminho)
    elif nome == "recolher":
        pintor.drawRoundedRect(QRectF(s * 0.14, s * 0.14, s * 0.72, s * 0.72), s * 0.14, s * 0.14)
        pintor.drawEllipse(QPointF(s * 0.64, s * 0.64), s * 0.09, s * 0.09)
    elif nome == "enviar":
        pintor.drawLine(QPointF(m, s * 0.80), QPointF(m, s * 0.22))
        caminho = QPainterPath(QPointF(s * 0.28, s * 0.44))
        caminho.lineTo(QPointF(m, s * 0.22))
        caminho.lineTo(QPointF(s * 0.72, s * 0.44))
        pintor.drawPath(caminho)
    elif nome == "parar":
        pintor.setBrush(pintor.pen().color())
        pintor.drawRoundedRect(QRectF(s * 0.30, s * 0.30, s * 0.40, s * 0.40), s * 0.06, s * 0.06)
    elif nome == "mais":
        pintor.drawLine(QPointF(m, s * 0.22), QPointF(m, s * 0.78))
        pintor.drawLine(QPointF(s * 0.22, m), QPointF(s * 0.78, m))


def icone_linha(nome: str, cor: str = "#c9cfdb") -> QIcon:
    """Ícone de traço fino (estilo dos apps atuais), desenhado na hora."""
    chave = (nome, cor)
    if chave in _cache_linha:
        return _cache_linha[chave]
    icone = QIcon()
    for tamanho in (16, 20, 24, 32, 40, 48):
        imagem = QPixmap(tamanho, tamanho)
        imagem.fill(Qt.GlobalColor.transparent)
        pintor = QPainter(imagem)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        caneta = QPen(QColor(cor), max(1.4, tamanho * 0.085))
        caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
        caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pintor.setPen(caneta)
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        _tracar(pintor, nome, float(tamanho))
        pintor.end()
        icone.addPixmap(imagem)
    _cache_linha[chave] = icone
    return icone
