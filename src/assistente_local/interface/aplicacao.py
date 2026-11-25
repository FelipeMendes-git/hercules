"""Abre a interface gráfica e liga o controlador a ela."""

from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from .. import config as cfgmod
from ..controlador import Controlador
from ..marca import ID_APP, NOME_APP
from . import icones
from .janela import JanelaPrincipal
from .tema import estilo_completo


class _Sinais(QObject):
    """Leva os eventos do controlador (outra thread) para a thread da interface."""

    evento = Signal(object)


def criar_aplicacao() -> QApplication:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ID_APP)  # ícone próprio na barra de tarefas
        except Exception:
            pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(NOME_APP)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(estilo_completo())
    app.setWindowIcon(icones.icone_app())
    return app


def executar(cfg: cfgmod.Config, ja_aberto: bool = False, na_bandeja: bool = False) -> int:
    app = criar_aplicacao()
    if ja_aberto:
        if not na_bandeja:
            QMessageBox.information(
                None, NOME_APP, f"O {NOME_APP} já está aberto. Procure o ícone dele perto do relógio do Windows."
            )
        return 0
    sinais = _Sinais()
    controlador = Controlador(cfg, sinais.evento.emit)
    janela = JanelaPrincipal(cfg, controlador)
    sinais.evento.connect(janela.tratar_evento)
    controlador.iniciar()
    i = cfg.interface
    so_bolinha = i.janela_compacta and i.iniciar_compacto
    escondido = (na_bandeja or i.iniciar_minimizado) and (janela.tem_bandeja or i.janela_compacta)
    if so_bolinha or escondido:
        janela.atualizar_compacta_depois()  # mostra a bolinha (se estiver ligada)
    else:
        janela.show()
    try:
        return app.exec()
    finally:
        controlador.encerrar()
