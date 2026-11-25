"""O que o app lembra entre execuções: o projeto atual e a conversa de cada projeto."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from . import caminhos

log = logging.getLogger(__name__)


def _chave(caminho: str) -> str:
    return os.path.normcase(os.path.abspath(caminho))


class Estado:
    def __init__(self, caminho: Path | None = None):
        self._caminho = caminho or caminhos.arquivo_estado()
        self._dados: dict = {"projeto_atual": "", "sessoes": {}}
        try:
            if self._caminho.is_file():
                lido = json.loads(self._caminho.read_text(encoding="utf-8"))
                if isinstance(lido, dict):
                    self._dados.update(lido)
        except (OSError, ValueError) as erro:
            log.warning("Não consegui ler %s: %s", self._caminho, erro)
        if not isinstance(self._dados.get("sessoes"), dict):
            self._dados["sessoes"] = {}

    @property
    def projeto_atual(self) -> str:
        return str(self._dados.get("projeto_atual") or "")

    @projeto_atual.setter
    def projeto_atual(self, caminho: str) -> None:
        self._dados["projeto_atual"] = caminho
        self._salvar()

    def sessao(self, caminho_projeto: str) -> str | None:
        return self._dados["sessoes"].get(_chave(caminho_projeto)) or None

    def guardar_sessao(self, caminho_projeto: str, sessao: str) -> None:
        if sessao and self._dados["sessoes"].get(_chave(caminho_projeto)) != sessao:
            self._dados["sessoes"][_chave(caminho_projeto)] = sessao
            self._salvar()

    def esquecer_sessao(self, caminho_projeto: str) -> None:
        if self._dados["sessoes"].pop(_chave(caminho_projeto), None):
            self._salvar()

    def _salvar(self) -> None:
        try:
            self._caminho.parent.mkdir(parents=True, exist_ok=True)
            temporario = self._caminho.with_suffix(".tmp")
            temporario.write_text(json.dumps(self._dados, ensure_ascii=False, indent=2), encoding="utf-8")
            temporario.replace(self._caminho)
        except OSError as erro:
            log.warning("Não consegui salvar %s: %s", self._caminho, erro)
