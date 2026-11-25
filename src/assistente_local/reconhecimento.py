"""Reconhecimento de fala com o faster-whisper, rodando no próprio PC.

São dois modelos:

- um **leve** (tiny, no processador), que transcreve tudo o que o microfone ouve só para
  procurar o nome do assistente. Custa ~0,15 s de dois núcleos por frase e não usa a placa
  de vídeo;
- o **principal** (large-v3-turbo, na placa de vídeo quando dá), preciso, que só entra
  depois que você chama o assistente, numa conversa aberta ou numa permissão.

O principal só é carregado quando precisa e pode ser descarregado no modo em espera.
"""

from __future__ import annotations

import gc
import logging
import os
import time
from dataclasses import dataclass

import numpy as np

from . import cuda, modelos
from .ativacao import normalizar

log = logging.getLogger(__name__)

# Frases que o Whisper costuma "ouvir" em ruído (vêm das legendas com que ele foi treinado).
_ALUCINACOES = {
    normalizar(frase)
    for frase in (
        "Legendas pela comunidade Amara.org",
        "Obrigado por assistir",
        "Obrigada por assistir",
        "Inscreva-se no canal",
        "Se inscreva no canal",
        "Legenda Adriana Zanotto",
    )
}


@dataclass
class Transcricao:
    texto: str
    confianca: float  # 0 a 1
    duracao_audio: float
    tempo_s: float


class Reconhecedor:
    """Não é seguro entre threads: use sempre da mesma thread (o controlador usa uma só)."""

    def __init__(self, cfg_reconhecimento):
        self.cfg = cfg_reconhecimento
        self.modelo = None
        self.modelo_rapido = None
        self.descricao = ""
        self._caminho = ""
        self._dispositivo = "cpu"
        self._fonte_cuda: str | None = None
        self._precisao_usada = "int8"

    @property
    def tem_modelo_rapido(self) -> bool:
        return self.modelo_rapido is not None

    @property
    def pode_esperar(self) -> bool:
        """Só dá para tirar o modelo principal da memória se o leve estiver ouvindo o nome."""
        return self.modelo_rapido is not None

    @property
    def principal_carregado(self) -> bool:
        return self.modelo is not None

    # ------------------------------------------------------------------ carregamento
    def preparar(self, progresso: modelos.Progresso | None = None) -> str:
        """Baixa o que faltar, escolhe onde o principal vai rodar e carrega só o modelo leve."""
        nome = self.cfg.modelo
        if not modelos.whisper_pronto(nome):
            modelos.baixar_whisper(nome, progresso)
        leve = (self.cfg.modelo_ativacao or "").strip()
        if leve and leve != nome and not modelos.whisper_pronto(leve):
            modelos.baixar_whisper(leve, progresso)
        self._caminho = str(modelos.pasta_whisper(nome))
        if progresso:
            progresso("Preparando o reconhecimento de voz", None)
        quer_gpu = self.cfg.dispositivo in ("auto", "cuda")
        fonte = cuda.preparar(self.cfg.pastas_cuda) if quer_gpu else None

        import ctranslate2

        if quer_gpu and fonte and ctranslate2.get_cuda_device_count() > 0:
            self._dispositivo, self._fonte_cuda = "cuda", fonte
        elif self.cfg.dispositivo == "cuda":
            raise RuntimeError("Não encontrei uma placa de vídeo NVIDIA com CUDA para o reconhecimento.")
        else:
            self._dispositivo, self._fonte_cuda = "cpu", None
        self._precisao_usada = self._precisao(self._dispositivo)
        self.modelo_rapido = None
        if leve and leve != nome:
            from faster_whisper import WhisperModel

            self.modelo_rapido = WhisperModel(
                str(modelos.pasta_whisper(leve)),
                device="cpu",
                compute_type="int8",
                cpu_threads=max(1, int(self.cfg.threads_ativacao)),
            )
            self._aquecer(self.modelo_rapido)
        self.descricao = self._descrever()
        return self.descricao

    def carregar(self, progresso: modelos.Progresso | None = None) -> str:
        """Prepara e já carrega o modelo principal (usado pelo diagnóstico)."""
        self.preparar(progresso)
        self.carregar_principal()
        return self.descricao

    def _descrever(self) -> str:
        onde = f"placa de vídeo, {self._fonte_cuda}" if self._dispositivo == "cuda" else "processador"
        if self.modelo_rapido is not None:
            onde += f"; nome ouvido pelo {self.cfg.modelo_ativacao} no processador"
        return onde

    def carregar_principal(self) -> None:
        """Carrega o modelo principal, se ainda não estiver na memória (cai para o processador se a placa falhar)."""
        if self.modelo is not None:
            return
        try:
            self._carregar_principal()
        except Exception as erro:
            if self._dispositivo != "cuda" or self.cfg.dispositivo == "cuda":
                raise
            log.warning("Não consegui usar a placa de vídeo (%s). Usando o processador.", erro)
            self._dispositivo, self._fonte_cuda = "cpu", None
            self._precisao_usada = self._precisao("cpu")
            self._carregar_principal()
            self.descricao = self._descrever()

    def liberar_principal(self) -> bool:
        """Tira o modelo principal da memória (e da placa de vídeo). Volta sozinho na próxima transcrição."""
        if self.modelo is None:
            return False
        self.modelo = None
        gc.collect()
        log.info("Modelo principal descarregado.")
        return True

    def _carregar_principal(self) -> None:
        from faster_whisper import WhisperModel

        inicio = time.perf_counter()
        if self._dispositivo == "cuda":
            self.modelo = WhisperModel(self._caminho, device="cuda", compute_type=self._precisao_usada)
        else:
            threads = max(2, (os.cpu_count() or 4) // 2)
            self.modelo = WhisperModel(
                self._caminho, device="cpu", compute_type=self._precisao_usada, cpu_threads=threads
            )
        self._aquecer(self.modelo)
        log.info("Modelo principal carregado em %.1f s (%s, %s)", time.perf_counter() - inicio, self._dispositivo, self._precisao_usada)

    def _precisao(self, dispositivo: str) -> str:
        if self.cfg.precisao and self.cfg.precisao != "auto":
            return self.cfg.precisao
        # int8_float16: metade da memória de vídeo do float16, mesma velocidade e qualidade (medido).
        return "int8_float16" if dispositivo == "cuda" else "int8"

    def _aquecer(self, modelo) -> None:
        segmentos, _ = modelo.transcribe(np.zeros(16000, np.float32), language=self.cfg.idioma or None, beam_size=1)
        list(segmentos)

    # ------------------------------------------------------------------ transcrição
    def transcrever_rapido(self, audio: np.ndarray, dica: str = "", nome: str = "") -> Transcricao:
        """Transcrição barata, só para procurar o nome. Sem modelo leve, usa o principal.

        O nome vai como "hotword" e a busca segue 3 caminhos (beam): com "Hércules" em voz sintética,
        o modelo leve passou de 8 para 18 acertos em 18, sem falsos positivos e quase sem custo a mais.
        """
        if self.modelo_rapido is None:
            return self.transcrever(audio, dica)
        return self._transcrever_com(self.modelo_rapido, audio, dica, beam=3, hotwords=nome)

    def transcrever(self, audio: np.ndarray, dica: str = "", palavras_chave: str = "") -> Transcricao:
        """Transcrição precisa. ``palavras_chave`` (hotwords) ajudam em respostas curtas como "sim" e "não"."""
        if self.modelo is None:
            self.carregar_principal()
        return self._transcrever_com(self.modelo, audio, dica, beam=self.cfg.beam_size, hotwords=palavras_chave)

    def _transcrever_com(self, modelo, audio: np.ndarray, dica: str, beam: int, hotwords: str = "") -> Transcricao:
        inicio = time.perf_counter()
        segmentos, _ = modelo.transcribe(
            audio,
            language=self.cfg.idioma or None,
            beam_size=beam,
            vad_filter=False,
            condition_on_previous_text=False,
            initial_prompt=dica or None,
            hotwords=hotwords or None,
            without_timestamps=True,
            temperature=(0.0, 0.2, 0.4),
        )
        partes, notas = [], []
        for segmento in segmentos:
            if segmento.no_speech_prob > 0.6 and segmento.avg_logprob < -1.0:
                continue
            if segmento.compression_ratio > 2.6:
                continue
            if segmento.text.strip():
                partes.append(segmento.text.strip())
                notas.append(segmento.avg_logprob)
        texto = " ".join(partes).strip()
        normal = normalizar(texto)
        if not normal or normal in _ALUCINACOES or "amara org" in normal:
            texto = ""
        confianca = float(np.exp(np.mean(notas))) if notas else 0.0
        return Transcricao(texto, confianca, len(audio) / 16000, time.perf_counter() - inicio)
