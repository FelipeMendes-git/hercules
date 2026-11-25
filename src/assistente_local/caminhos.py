"""Onde o app guarda configuração, modelos, conversas e logs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .marca import ID_APP

VAR_DADOS = "ASSISTENTE_LOCAL_DADOS"


def raiz_app() -> Path:
    """Raiz do repositório (desenvolvimento) ou pasta do executável (app empacotado)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def pasta_dados() -> Path:
    """Pasta de dados do app.

    Ordem de escolha:
    1. a variável de ambiente ``ASSISTENTE_LOCAL_DADOS``;
    2. uma pasta ``dados`` ao lado do app (modo portátil, usado no desenvolvimento);
    3. ``%LOCALAPPDATA%\\<ID_APP>``.
    """
    valor = os.environ.get(VAR_DADOS)
    if valor:
        pasta = Path(valor).expanduser()
    elif (raiz_app() / "dados").is_dir():
        pasta = raiz_app() / "dados"
    else:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        pasta = Path(base) / ID_APP
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _subpasta(nome: str) -> Path:
    pasta = pasta_dados() / nome
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def pasta_modelos() -> Path:
    return _subpasta("modelos")


def pasta_logs() -> Path:
    return _subpasta("logs")


def arquivo_config() -> Path:
    return pasta_dados() / "config.toml"


def arquivo_estado() -> Path:
    return pasta_dados() / "estado.json"
