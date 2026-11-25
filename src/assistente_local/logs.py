"""Configuração de logs (arquivo em dados/logs/app.log)."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from . import caminhos

_RUIDOSOS = ("httpx", "httpcore", "huggingface_hub", "urllib3", "faster_whisper", "phonemizer", "asyncio")


def configurar(nivel: int = logging.INFO, console: bool = False) -> None:
    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    formato = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    arquivo = logging.handlers.RotatingFileHandler(
        caminhos.pasta_logs() / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    arquivo.setFormatter(formato)
    raiz.addHandler(arquivo)
    if console and sys.stderr is not None:
        tela = logging.StreamHandler()
        tela.setFormatter(formato)
        raiz.addHandler(tela)
    for nome in _RUIDOSOS:
        logging.getLogger(nome).setLevel(logging.WARNING)
