"""Ações de área de trabalho: abrir arquivos e pastas e copiar texto."""

from __future__ import annotations

import os
import subprocess

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication


def copiar(texto: str) -> None:
    QGuiApplication.clipboard().setText(texto)


def abrir(caminho: str) -> bool:
    """Abre o arquivo (ou pasta) com o programa padrão do Windows."""
    return QDesktopServices.openUrl(QUrl.fromLocalFile(caminho))


def mostrar_na_pasta(caminho: str) -> None:
    """Abre o Explorador de Arquivos com o arquivo selecionado."""
    caminho = os.path.normpath(caminho)
    if os.path.isdir(caminho):
        abrir(caminho)
    elif os.name == "nt":
        subprocess.Popen(f'explorer /select,"{caminho}"')
    else:
        abrir(os.path.dirname(caminho))
