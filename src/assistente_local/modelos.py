"""Baixa os modelos de voz (Kokoro) e de reconhecimento (Whisper) quando faltam."""

from __future__ import annotations

import logging
import os
import urllib.request
from pathlib import Path
from typing import Callable

from . import caminhos
from .marca import ID_APP, VERSAO

log = logging.getLogger(__name__)

Progresso = Callable[[str, "float | None"], None]  # (mensagem, fração de 0 a 1 ou None)

_BASE_KOKORO = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
_KOKORO = {"kokoro-v1.0.onnx": 310, "voices-v1.0.bin": 27}  # nome: tamanho aproximado em MB

WHISPER: dict[str, tuple[str, int]] = {
    "large-v3-turbo": ("mobiuslabsgmbh/faster-whisper-large-v3-turbo", 1600),
    "large-v3": ("Systran/faster-whisper-large-v3", 3100),
    "medium": ("Systran/faster-whisper-medium", 1500),
    "small": ("Systran/faster-whisper-small", 480),
    "base": ("Systran/faster-whisper-base", 145),
    "tiny": ("Systran/faster-whisper-tiny", 75),
}
_ARQUIVOS_WHISPER = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]


def pasta_kokoro() -> Path:
    return caminhos.pasta_modelos() / "kokoro"


def kokoro_pronto() -> bool:
    return all((pasta_kokoro() / nome).is_file() for nome in _KOKORO)


def baixar_kokoro(progresso: Progresso | None = None) -> None:
    pasta = pasta_kokoro()
    pasta.mkdir(parents=True, exist_ok=True)
    for nome, megas in _KOKORO.items():
        destino = pasta / nome
        if not destino.is_file():
            _baixar(_BASE_KOKORO + nome, destino, f"Baixando a voz ({nome}, ~{megas} MB)", progresso)


def _baixar(url: str, destino: Path, mensagem: str, progresso: Progresso | None) -> None:
    log.info("Baixando %s", url)
    parcial = destino.with_name(destino.name + ".parcial")
    pedido = urllib.request.Request(url, headers={"User-Agent": f"{ID_APP}/{VERSAO}"})
    with urllib.request.urlopen(pedido, timeout=60) as resposta, open(parcial, "wb") as saida:
        total = int(resposta.headers.get("Content-Length") or 0)
        lido = 0
        while bloco := resposta.read(1 << 20):
            saida.write(bloco)
            lido += len(bloco)
            if progresso:
                progresso(mensagem, lido / total if total else None)
    parcial.replace(destino)


def pasta_whisper(modelo: str) -> Path:
    return caminhos.pasta_modelos() / "whisper" / modelo.replace("/", "--")


def whisper_pronto(modelo: str) -> bool:
    return (pasta_whisper(modelo) / "model.bin").is_file()


def baixar_whisper(modelo: str, progresso: Progresso | None = None) -> Path:
    repositorio, megas = WHISPER.get(modelo, (modelo, 0))
    if "/" not in repositorio:
        raise ValueError(f"Modelo de reconhecimento desconhecido: {modelo}")
    tamanho = f", ~{megas} MB" if megas else ""
    if progresso:
        progresso(f"Baixando o reconhecimento de voz ({modelo}{tamanho}). Isso só acontece uma vez.", None)
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from huggingface_hub import snapshot_download

    snapshot_download(repositorio, local_dir=str(pasta_whisper(modelo)), allow_patterns=_ARQUIVOS_WHISPER)
    return pasta_whisper(modelo)
