"""Encontra as bibliotecas CUDA (cuBLAS 12) para o Whisper rodar na placa NVIDIA.

O app não instala um CUDA próprio quando já existe um compatível no PC. Ele procura,
nesta ordem:

1. as pastas de ``reconhecimento.pastas_cuda`` na configuração;
2. os pacotes pip ``nvidia-*`` (extra ``gpu`` do pyproject);
3. o CUDA Toolkit (variável ``CUDA_PATH``);
4. o ambiente do VoiceStudio (PyTorch com CUDA 12).

O cuDNN 9.10 já vem dentro do CTranslate2; o que falta é o cuBLAS 12.
Chame :func:`preparar` antes de importar ``faster_whisper``.
"""

from __future__ import annotations

import logging
import os
import sysconfig
from pathlib import Path

log = logging.getLogger(__name__)

_DLLS_CUBLAS = ("cublas64_12.dll", "cublasLt64_12.dll")
_registradas: list = []  # mantém os registros de pasta vivos


def _grupos(extras: list[str]) -> list[tuple[str, list[Path]]]:
    grupos: list[tuple[str, list[Path]]] = []
    for pasta in extras:
        if pasta:
            grupos.append((pasta, [Path(pasta).expanduser()]))
    nvidia = Path(sysconfig.get_paths()["purelib"]) / "nvidia"
    if nvidia.is_dir():
        grupos.append(("pacotes nvidia do pip", sorted(nvidia.glob("*/bin"))))
    if os.environ.get("CUDA_PATH"):
        grupos.append(("CUDA Toolkit", [Path(os.environ["CUDA_PATH"]) / "bin"]))
    if os.environ.get("APPDATA"):
        torch_lib = (
            Path(os.environ["APPDATA"])
            / "VoiceStudio/runtime/project/.venv/Lib/site-packages/torch/lib"
        )
        grupos.append(("CUDA do VoiceStudio", [torch_lib]))
    return grupos


def _tem_cublas(pastas: list[Path]) -> bool:
    return any(all((pasta / dll).is_file() for dll in _DLLS_CUBLAS) for pasta in pastas)


def preparar(extras: list[str] | None = None) -> str | None:
    """Registra a primeira fonte de cuBLAS 12 encontrada.

    Retorna uma descrição curta da fonte (para mostrar na tela) ou ``None`` se não
    achou nenhuma; nesse caso o reconhecimento roda no processador.
    """
    if os.name != "nt":
        return "bibliotecas do sistema"
    for rotulo, pastas in _grupos(list(extras or [])):
        pastas = [pasta for pasta in pastas if pasta.is_dir()]
        if not _tem_cublas(pastas):
            continue
        for pasta in pastas:
            try:
                _registradas.append(os.add_dll_directory(str(pasta)))
            except OSError:
                pass
        os.environ["PATH"] = os.pathsep.join([*map(str, pastas), os.environ.get("PATH", "")])
        log.info("CUDA: usando %s (%s)", rotulo, "; ".join(map(str, pastas)))
        return rotulo
    log.info("CUDA: nenhuma cópia do cuBLAS 12 encontrada; o reconhecimento vai usar o processador.")
    return None
