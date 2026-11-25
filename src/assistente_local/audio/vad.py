"""Detector de voz: Silero VAD v6, o mesmo modelo que vem dentro do faster-whisper."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import numpy as np
import onnxruntime as ort

_CONTEXTO = 64


def caminho_modelo() -> Path:
    return Path(str(files("faster_whisper") / "assets" / "silero_vad_v6.onnx"))


class DetectorVoz:
    """Probabilidade de haver voz numa janela de 512 amostras (16 kHz), com estado entre janelas."""

    def __init__(self, caminho: Path | None = None):
        opcoes = ort.SessionOptions()
        opcoes.inter_op_num_threads = 1
        opcoes.intra_op_num_threads = 1
        opcoes.log_severity_level = 4
        self._sessao = ort.InferenceSession(
            str(caminho or caminho_modelo()), providers=["CPUExecutionProvider"], sess_options=opcoes
        )
        self.reiniciar()

    def reiniciar(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._contexto = np.zeros(_CONTEXTO, dtype=np.float32)

    def __call__(self, janela: np.ndarray) -> float:
        janela = np.asarray(janela, dtype=np.float32)
        entrada = np.concatenate([self._contexto, janela])[None, :]
        saida, self._h, self._c = self._sessao.run(None, {"input": entrada, "h": self._h, "c": self._c})
        self._contexto = janela[-_CONTEXTO:].copy()
        return float(np.asarray(saida).reshape(-1)[0])
