"""Escuta o microfone numa thread própria: detecção de voz + corte em falas completas.

Feito para ficar ligado o tempo todo: se o microfone não abre ou some (headset desligado,
dongle desconectado), o ouvinte avisa e o controlador tenta de novo de tempos em tempos.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable

import numpy as np
import sounddevice as sd

from . import dispositivos
from .segmentador import JANELA, TAXA, Fala, Segmentador
from .vad import DetectorVoz

log = logging.getLogger(__name__)

_SEM_AUDIO_S = 4.0  # sem nenhuma janela por esse tempo = microfone parou


def _ajustar_tamanho(janela: np.ndarray, n: int) -> np.ndarray:
    if len(janela) == n:
        return janela
    if len(janela) % n == 0:
        return janela.reshape(n, -1).mean(axis=1).astype(np.float32)
    return np.interp(np.linspace(0, len(janela) - 1, n), np.arange(len(janela)), janela).astype(np.float32)


class Ouvinte:
    """Lê o microfone, roda o VAD e entrega cada fala completa para ``ao_falar``.

    ``ao_nivel(nivel, gravando)`` recebe o volume (0 a 1) umas dez vezes por segundo.
    ``ao_estado(ok, mensagem)`` avisa quando o microfone cai ou volta.
    """

    def __init__(
        self,
        cfg_audio,
        ao_falar: Callable[[Fala], None],
        ao_nivel: Callable[[float, bool], None] | None = None,
        ao_estado: Callable[[bool, str], None] | None = None,
    ):
        self.cfg = cfg_audio
        self._ao_falar = ao_falar
        self._ao_nivel = ao_nivel
        self._ao_estado = ao_estado
        self._vad = DetectorVoz()
        self._segmentador = self._novo_segmentador()
        self._fila: queue.SimpleQueue = queue.SimpleQueue()
        self._stream: sd.InputStream | None = None
        self._thread: threading.Thread | None = None
        self._trava_stream = threading.Lock()
        self._rodando = False
        self._simulado = False
        self._mudo = False
        self._ignorar_ate = 0.0
        self._curtas_ate = 0.0
        self._ultimo_audio = 0.0
        self._descartar = threading.Event()
        self._trocar_segmentador = threading.Event()
        self.microfone_ok: bool | None = None
        self.taxa_dispositivo = TAXA
        self.nome_dispositivo = ""

    def _novo_segmentador(self) -> Segmentador:
        c = self.cfg
        segmentador = Segmentador(
            limiar=c.limiar_vad,
            silencio_fim_ms=c.silencio_fim_ms,
            fala_minima_ms=c.fala_minima_ms,
            fala_maxima_s=c.fala_maxima_s,
            pre_fala_ms=c.pre_fala_ms,
        )
        segmentador.curtas_ate = getattr(self, "_curtas_ate", 0.0)
        return segmentador

    def aceitar_falas_curtas_ate(self, ate: float) -> None:
        """Até ``ate`` (time.monotonic), aceita falas bem curtas, como um "sim" ou um "não".

        Fora disso, elas continuam descartadas como ruído (evita acordar o app à toa).
        """
        self._curtas_ate = ate
        self._segmentador.curtas_ate = ate

    # ------------------------------------------------------------------ controle
    def iniciar(self, simulado: bool = False) -> None:
        """Começa a escutar. ``simulado`` não abre o microfone (testes). Não falha se o microfone faltar."""
        self._simulado = simulado
        if simulado:
            self.microfone_ok = True
        else:
            self.tentar_abrir()
        self._rodando = True
        self._thread = threading.Thread(target=self._laco, name="ouvinte", daemon=True)
        self._thread.start()

    def tentar_abrir(self) -> bool:
        """(Re)abre o microfone. Devolve True se conseguiu."""
        if self._simulado:
            return True
        self.fechar_microfone()
        dispositivo = dispositivos.resolver(self.cfg.microfone, entrada=True)
        try:
            try:
                self._abrir(dispositivo, TAXA)
            except Exception as erro:
                taxa = int(sd.query_devices(dispositivo, "input")["default_samplerate"])
                log.info("O microfone não aceitou 16 kHz (%s); abrindo em %d Hz.", erro, taxa)
                self._abrir(dispositivo, taxa)
        except Exception as erro:
            if self.microfone_ok is not False:
                log.warning("Microfone indisponível: %s", erro)
                self._avisar(False, f"Microfone indisponível ({erro}). Vou tentar de novo sozinho.")
            self.microfone_ok = False
            return False
        self._ultimo_audio = time.monotonic()
        if self.microfone_ok is False:
            self._avisar(True, f"Microfone de volta: {self.nome_dispositivo}.")
        self.microfone_ok = True
        return True

    def _abrir(self, dispositivo: int | None, taxa: int) -> None:
        bloco = int(round(JANELA * taxa / TAXA))

        def receber(indata, frames, tempo, status):  # thread do PortAudio: só enfileira
            self._fila.put((indata[:, 0].copy(), time.monotonic()))

        stream = sd.InputStream(
            device=dispositivo, samplerate=taxa, channels=1, dtype="float32", blocksize=bloco, callback=receber
        )
        stream.start()
        with self._trava_stream:
            self._stream = stream
        self.taxa_dispositivo = taxa
        self.nome_dispositivo = dispositivos.nome(stream.device, entrada=True)
        log.info("Microfone: %s (%d Hz)", self.nome_dispositivo, taxa)

    def fechar_microfone(self) -> None:
        with self._trava_stream:
            stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.abort()
                stream.close()
            except Exception:
                pass

    def parar(self) -> None:
        self._rodando = False
        self.fechar_microfone()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def aplicar_config(self, cfg_audio) -> None:
        self.cfg = cfg_audio
        self._trocar_segmentador.set()

    def definir_mudo(self, mudo: bool) -> None:
        self._mudo = mudo

    @property
    def mudo(self) -> bool:
        return self._mudo

    def descartar(self, ignorar_por_s: float = 0.0) -> None:
        """Joga fora o que estava sendo gravado e ignora o microfone por um instante."""
        self._ignorar_ate = time.monotonic() + ignorar_por_s
        self._descartar.set()

    def alimentar(self, janela: np.ndarray, agora: float | None = None) -> None:
        """Entrega áudio de 16 kHz como se viesse do microfone (testes e simulação)."""
        self._fila.put((np.asarray(janela, dtype=np.float32), time.monotonic() if agora is None else agora))

    def _avisar(self, ok: bool, mensagem: str) -> None:
        if self._ao_estado is not None:
            try:
                self._ao_estado(ok, mensagem)
            except Exception:
                log.exception("Falha ao avisar sobre o microfone")

    # ------------------------------------------------------------------ thread
    def _laco(self) -> None:
        contador = 0
        while self._rodando:
            try:
                janela, agora = self._fila.get(timeout=0.5)
            except queue.Empty:
                self._verificar_microfone()
                continue
            self._ultimo_audio = time.monotonic()
            if self._trocar_segmentador.is_set():
                self._trocar_segmentador.clear()
                self._segmentador = self._novo_segmentador()
            if self._descartar.is_set():
                self._descartar.clear()
                self._segmentador.reiniciar()
                self._vad.reiniciar()
            if len(janela) != JANELA:
                janela = _ajustar_tamanho(janela, JANELA)
            contador += 1
            if self._mudo or agora < self._ignorar_ate:
                if self._segmentador.gravando:
                    self._segmentador.reiniciar()
                if self._ao_nivel and contador % 3 == 0:
                    self._ao_nivel(0.0, False)
                continue
            try:
                prob = self._vad(janela)
            except Exception:
                log.exception("Falha no detector de voz")
                continue
            fala = self._segmentador.processar(janela, prob, agora)
            if self._ao_nivel and contador % 3 == 0:
                rms = float(np.sqrt(np.mean(janela * janela)))
                nivel = (20.0 * np.log10(rms + 1e-9) + 60.0) / 50.0  # -60 dB a -10 dB
                self._ao_nivel(float(min(1.0, max(0.0, nivel))), self._segmentador.gravando)
            if fala is not None:
                try:
                    self._ao_falar(fala)
                except Exception:
                    log.exception("Falha ao entregar a fala")

    def _verificar_microfone(self) -> None:
        """Sem áudio por alguns segundos com o microfone "aberto" = ele parou (desconectado)."""
        if self._simulado or self.microfone_ok is not True:
            return
        with self._trava_stream:
            aberto = self._stream is not None
        if aberto and time.monotonic() - self._ultimo_audio > _SEM_AUDIO_S:
            log.warning("O microfone parou de mandar áudio.")
            self.fechar_microfone()
            self.microfone_ok = False
            self._segmentador.reiniciar()
            self._avisar(False, "O microfone parou de responder. Vou tentar reconectar sozinho.")
