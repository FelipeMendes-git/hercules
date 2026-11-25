"""Janela "Conversas salvas": ver, continuar, copiar e exportar conversas anteriores."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QStandardPaths, Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
)

from ..historico import Historico
from . import acoes
from .conversa import ListaConversa, renderizar_entradas


class JanelaHistorico(QDialog):
    def __init__(self, historico: Historico, continuar: Callable[[str, str], None], pai=None) -> None:
        super().__init__(pai)
        self.setWindowTitle("Conversas salvas")
        self.resize(1000, 700)
        self._historico = historico
        self._continuar = continuar
        self._resumos = historico.listar()

        self._lista = QListWidget()
        self._lista.setMinimumWidth(300)
        self._lista.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._lista.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._lista.setWordWrap(True)
        for resumo in self._resumos:
            item = QListWidgetItem(f"{resumo.inicio:%d/%m/%Y %H:%M} · {resumo.projeto}\n{resumo.titulo}")
            item.setToolTip(str(resumo.arquivo))
            self._lista.addItem(item)
        self._visualizacao = ListaConversa()
        divisor = QSplitter()
        divisor.addWidget(self._lista)
        divisor.addWidget(self._visualizacao)
        divisor.setStretchFactor(1, 1)
        divisor.setSizes([320, 680])

        self._botao_continuar = QPushButton("Continuar esta conversa")
        self._botao_continuar.setObjectName("primario")
        self._botao_continuar.setToolTip("Volta a esta conversa no app, com o Claude lembrando do que foi dito")
        self._botao_copiar = QPushButton("Copiar conversa")
        self._botao_exportar = QPushButton("Exportar como texto…")
        botao_pasta = QPushButton("Abrir pasta das conversas")
        botao_fechar = QPushButton("Fechar")
        botoes = QHBoxLayout()
        for botao in (self._botao_continuar, self._botao_copiar, self._botao_exportar, botao_pasta):
            botoes.addWidget(botao)
        botoes.addStretch(1)
        botoes.addWidget(botao_fechar)

        coluna = QVBoxLayout(self)
        if not self._resumos:
            aviso = QLabel("Nenhuma conversa salva ainda. Elas aparecem aqui depois do primeiro pedido.")
            aviso.setObjectName("suave")
            coluna.addWidget(aviso)
        coluna.addWidget(divisor, 1)
        coluna.addLayout(botoes)

        self._lista.currentRowChanged.connect(self._mostrar)
        self._botao_continuar.clicked.connect(self._ao_continuar)
        self._botao_copiar.clicked.connect(self._copiar)
        self._botao_exportar.clicked.connect(self._exportar)
        botao_pasta.clicked.connect(lambda: acoes.abrir(str(self._historico.pasta)))
        botao_fechar.clicked.connect(self.reject)
        for botao in (self._botao_continuar, self._botao_copiar, self._botao_exportar):
            botao.setEnabled(False)
        if self._resumos:
            self._lista.setCurrentRow(0)

    def _atual(self):
        linha = self._lista.currentRow()
        return self._resumos[linha] if 0 <= linha < len(self._resumos) else None

    def _mostrar(self, _linha: int) -> None:
        resumo = self._atual()
        self._visualizacao.limpar()
        if resumo is None:
            return
        entradas = [e for e in self._historico.ler(resumo.arquivo) if e.get("tipo") not in ("conversa", "sessao")]
        renderizar_entradas(self._visualizacao, entradas)
        pode_continuar = bool(resumo.sessao and resumo.caminho_projeto and os.path.isdir(resumo.caminho_projeto))
        self._botao_continuar.setEnabled(pode_continuar)
        self._botao_copiar.setEnabled(True)
        self._botao_exportar.setEnabled(True)

    def _ao_continuar(self) -> None:
        resumo = self._atual()
        if resumo is not None and resumo.sessao:
            self._continuar(resumo.caminho_projeto, resumo.sessao)
            self.accept()

    def _copiar(self) -> None:
        resumo = self._atual()
        if resumo is None:
            return
        acoes.copiar(self._historico.exportar_markdown(resumo.arquivo))
        self._botao_copiar.setText("Copiado ✓")
        QTimer.singleShot(1500, lambda: self._botao_copiar.setText("Copiar conversa"))

    def _exportar(self) -> None:
        resumo = self._atual()
        if resumo is None:
            return
        documentos = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        sugestao = os.path.join(documentos, f"Conversa {resumo.projeto} {resumo.inicio:%Y-%m-%d %H-%M}.md")
        destino, _ = QFileDialog.getSaveFileName(self, "Exportar conversa", sugestao, "Markdown (*.md);;Texto (*.txt)")
        if destino:
            Path(destino).write_text(self._historico.exportar_markdown(resumo.arquivo), encoding="utf-8")
            acoes.mostrar_na_pasta(destino)
