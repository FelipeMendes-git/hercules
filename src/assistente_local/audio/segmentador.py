"""Corta o áudio do microfone em falas, usando a probabilidade de voz do VAD."""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass

import numpy as np

TAXA = 16000
JANELA = 512  # 32 ms

log = logging.getLogger(__name__)


@dataclass
class Fala:
    audio: np.ndarray  # float32, 16 kHz, mono
    inicio: float  # time.monotonic() do começo do áudio (inclui um pouco de antes da voz)
    fim: float
    inicio_voz: float = 0.0  # quando a voz começou de verdade (sem o trecho guardado de antes)
    curta: bool = False  # mais curta que o mínimo normal: só passa quando o app espera uma resposta

    @property
    def duracao(self) -> float:
        return len(self.audio) / TAXA


class Segmentador:
    """Junta janelas de áudio em falas completas.

    Começa a gravar depois de algumas janelas seguidas com voz (evita cliques), guarda
    um pouco do áudio de antes (para não cortar a primeira sílaba) e termina depois de
    um silêncio. Entre os dois limiares (histerese), hesitações não cortam a fala.

    Falas mais curtas que ``fala_minima_ms`` são descartadas como ruído, a não ser que comecem
    até ``curtas_ate``: é quando o app espera uma resposta (um "sim" tem uns 200 ms de voz).
    """

    def __init__(
        self,
        limiar: float = 0.5,
        silencio_fim_ms: int = 800,
        fala_minima_ms: int = 200,
        fala_maxima_s: float = 45.0,
        pre_fala_ms: int = 300,
        janelas_para_comecar: int = 3,
        fala_curta_ms: int = 120,
    ):
        self.dur_janela = JANELA / TAXA
        self.limiar = limiar
        self.limiar_baixo = max(0.1, limiar - 0.15)
        self.n_silencio = max(1, math.ceil(silencio_fim_ms / 1000 / self.dur_janela))
        self.n_minimo = max(1, math.ceil(fala_minima_ms / 1000 / self.dur_janela))
        self.n_minimo_curto = max(1, min(self.n_minimo, math.ceil(fala_curta_ms / 1000 / self.dur_janela)))
        self.curtas_ate = 0.0  # até quando (time.monotonic) aceitar falas curtas
        self.n_maximo = max(self.n_minimo + 1, int(fala_maxima_s / self.dur_janela))
        self.n_pre = max(0, math.ceil(pre_fala_ms / 1000 / self.dur_janela))
        self.n_comecar = max(1, janelas_para_comecar)
        self.n_cauda = math.ceil(0.25 / self.dur_janela)
        self.reiniciar()

    def reiniciar(self) -> None:
        self._antes: deque[np.ndarray] = deque(maxlen=self.n_pre + self.n_comecar)
        self._gravando = False
        self._buffer: list[np.ndarray] = []
        self._fala = 0
        self._silencio = 0
        self._seguidas = 0
        self._inicio = 0.0
        self._inicio_voz = 0.0

    @property
    def gravando(self) -> bool:
        return self._gravando

    def processar(self, janela: np.ndarray, prob: float, agora: float) -> Fala | None:
        """Recebe uma janela e a probabilidade de voz dela; devolve a fala quando ela termina."""
        if not self._gravando:
            self._antes.append(janela)
            if prob >= self.limiar:
                self._seguidas += 1
                if self._seguidas >= self.n_comecar:
                    self._gravando = True
                    self._buffer = list(self._antes)
                    self._antes.clear()
                    self._fala = self._seguidas
                    self._silencio = 0
                    self._inicio = agora - len(self._buffer) * self.dur_janela
                    self._inicio_voz = agora - self._seguidas * self.dur_janela
            else:
                self._seguidas = 0
            return None

        self._buffer.append(janela)
        if prob >= self.limiar:
            self._fala += 1
            self._silencio = 0
        elif prob >= self.limiar_baixo:
            self._silencio = 0
        else:
            self._silencio += 1
        if self._silencio >= self.n_silencio or len(self._buffer) >= self.n_maximo:
            return self._fechar(agora)
        return None

    def _fechar(self, agora: float) -> Fala | None:
        sobra = max(0, self._silencio - self.n_cauda)
        partes = self._buffer[: len(self._buffer) - sobra] if sobra else self._buffer
        curta = self._fala < self.n_minimo
        resposta_esperada = self._inicio_voz <= self.curtas_ate
        suficiente = not curta or (resposta_esperada and self._fala >= self.n_minimo_curto)
        inicio, inicio_voz, fala = self._inicio, self._inicio_voz, self._fala
        minimo = self.n_minimo_curto if resposta_esperada else self.n_minimo
        self.reiniciar()
        if not suficiente and partes:
            log.info("Fala curta descartada (%d ms de voz, mínimo %d ms).", round(fala * self.dur_janela * 1000), round(minimo * self.dur_janela * 1000))
        if not suficiente or not partes:
            return None
        return Fala(np.concatenate(partes).astype(np.float32, copy=False), inicio, agora, inicio_voz, curta)
