"""Toca a voz e os sons de aviso, com fila e interrupção imediata."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

import numpy as np
import sounddevice as sd

from . import dispositivos

log = logging.getLogger(__name__)

FOLGA_S = 0.15  # áudio que fica adiantado na saída (o "parar" demora no máximo isso)
_PRIORIDADE_ALTA = 2  # THREAD_PRIORITY_HIGHEST


def _subir_prioridade_da_thread() -> None:
    """Na thread que toca o áudio: o app roda com prioridade baixa, mas o som não pode esperar."""
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetThreadPriority(kernel32.GetCurrentThread(), _PRIORIDADE_ALTA)
    except Exception:  # fora do Windows ou sem permissão: segue como está
        pass


def reamostrar(audio: np.ndarray, de: int, para: int) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32)
    if de == para or len(audio) == 0:
        return audio
    n = max(1, int(round(len(audio) * para / de)))
    return np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)


class Reprodutor:
    """Mantém a saída de áudio aberta e toca o que entra na fila.

    ``silencioso=True`` não abre a saída: só simula o tempo de cada áudio (testes).
    """

    def __init__(self, dispositivo: str = "", volume: float = 1.0, silencioso: bool = False):
        self._nome_dispositivo = dispositivo
        self.volume = volume
        self._silencioso = silencioso
        self._fim_simulado = 0.0
        self._trava = threading.Lock()
        self._fila: deque[np.ndarray] = deque()
        self._atual: np.ndarray | None = None
        self._posicao = 0
        self._ocioso = threading.Event()
        self._ocioso.set()
        self._stream: sd.OutputStream | None = None
        self.taxa = 24000
        self.nome_dispositivo = ""
        self.nivel = 0.0  # volume (RMS) do que está tocando agora; a interface pulsa com ele
        self.faltas = 0  # vezes em que a placa pediu som e não havia a tempo (vão para o log)
        self._prioridade_ajustada = False

    def iniciar(self) -> None:
        if self._silencioso:
            self.nome_dispositivo = "sem som (teste)"
            return
        dispositivo = dispositivos.resolver(self._nome_dispositivo, entrada=False)
        try:
            self._abrir(dispositivo, 24000)
        except Exception as erro:
            taxa = int(sd.query_devices(dispositivo, "output")["default_samplerate"])
            log.info("A saída não aceitou 24 kHz (%s); abrindo em %d Hz.", erro, taxa)
            self._abrir(dispositivo, taxa)

    def _abrir(self, dispositivo: int | None, taxa: int) -> None:
        # Folga de 150 ms: quem enche a placa de som é código Python, que disputa a vez com a interface, o
        # microfone e o reconhecimento. Com folga curta, qualquer atraso vira um soluço no meio da palavra.
        stream = sd.OutputStream(
            device=dispositivo, samplerate=taxa, channels=1, dtype="float32", callback=self._callback,
            latency=FOLGA_S,
        )
        stream.start()
        self._stream = stream
        self.taxa = taxa
        self.nome_dispositivo = dispositivos.nome(stream.device, entrada=False)
        log.info("Saída de áudio: %s (%d Hz)", self.nome_dispositivo, taxa)

    def fechar(self) -> None:
        self.parar()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def tocar(self, audio: np.ndarray, taxa: int) -> None:
        if self._silencioso:
            with self._trava:
                self._fim_simulado = max(time.monotonic(), self._fim_simulado) + len(audio) / float(taxa)
            return
        dados = np.clip(reamostrar(audio, taxa, self.taxa) * float(self.volume), -1.0, 1.0)
        if len(dados) == 0:
            return
        with self._trava:
            self._fila.append(dados.astype(np.float32, copy=False))
            self._ocioso.clear()

    def silencio(self, segundos: float) -> None:
        """Põe uma pausa na fila (entre um trecho falado e o próximo)."""
        if segundos > 0:
            self.tocar(np.zeros(int(round(segundos * self.taxa)), dtype=np.float32), self.taxa)

    def parar(self) -> None:
        with self._trava:
            self._fila.clear()
            self._atual = None
            self._posicao = 0
            self._fim_simulado = 0.0
            self._ocioso.set()
            self.nivel = 0.0

    @property
    def tocando(self) -> bool:
        if self._silencioso:
            return time.monotonic() < self._fim_simulado
        return not self._ocioso.is_set()

    def esperar(self, timeout: float | None = None) -> bool:
        if self._silencioso:
            restante = max(0.0, self._fim_simulado - time.monotonic())
            if timeout is not None and restante > timeout:
                time.sleep(timeout)
                return False
            time.sleep(restante)
            return True
        return self._ocioso.wait(timeout)

    def _callback(self, saida, frames, tempo, status) -> None:
        if not self._prioridade_ajustada:
            self._prioridade_ajustada = True
            _subir_prioridade_da_thread()
        if status.output_underflow:
            self.faltas += 1
            if self.faltas in (1, 10, 100) or self.faltas % 1000 == 0:
                log.warning("A saída de áudio ficou sem som a tempo %d vez(es) (soluço na voz).", self.faltas)
        saida.fill(0)
        escrito = 0
        with self._trava:
            while escrito < frames:
                if self._atual is None:
                    if not self._fila:
                        break
                    self._atual = self._fila.popleft()
                    self._posicao = 0
                n = min(len(self._atual) - self._posicao, frames - escrito)
                saida[escrito : escrito + n, 0] = self._atual[self._posicao : self._posicao + n]
                escrito += n
                self._posicao += n
                if self._posicao >= len(self._atual):
                    self._atual = None
            if self._atual is None and not self._fila:
                self._ocioso.set()
        self.nivel = float(np.sqrt(np.mean(np.square(saida[:escrito, 0])))) if escrito else 0.0
