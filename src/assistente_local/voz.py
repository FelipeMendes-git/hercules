"""Voz sintética: Kokoro (natural, roda no PC) ou a voz do Windows (SAPI) como reserva."""

from __future__ import annotations

import logging
from typing import Protocol

import numpy as np

from . import modelos, pronuncia

log = logging.getLogger(__name__)

VOZES_KOKORO = {"pf_dora": "Dora (feminina)", "pm_alex": "Alex (masculina)", "pm_santa": "Santa (masculina)"}
# Voz do Windows do mesmo gênero, sugerida como reserva para cada voz do Kokoro.
RESERVA_WINDOWS = {"pf_dora": "Maria", "pm_alex": "Daniel", "pm_santa": "Daniel"}
# Vozes "OneCore" do Windows (onde fica a Daniel): o app só lê a lista, sem mexer no registro.
_CATEGORIA_ONECORE = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices"


class MotorVoz(Protocol):
    taxa: int
    descricao: str

    def sintetizar(self, texto: str) -> np.ndarray: ...


class VozKokoro:
    motor = "kokoro"

    def __init__(self, voz: str = "pf_dora", velocidade: float = 1.0):
        from kokoro_onnx import Kokoro

        pasta = modelos.pasta_kokoro()
        self._kokoro = Kokoro(str(pasta / "kokoro-v1.0.onnx"), str(pasta / "voices-v1.0.bin"))
        if voz not in set(self._kokoro.get_voices()):
            log.warning("Voz %r não existe no Kokoro; usando pf_dora.", voz)
            voz = "pf_dora"
        self.voz = voz
        self.velocidade = float(velocidade)
        self.taxa = 24000
        self.descricao = f"Kokoro, {VOZES_KOKORO.get(voz, voz)}"

    def sintetizar(self, texto: str) -> np.ndarray:
        texto = pronuncia.aplicar(texto)  # termos em inglês e siglas do jeito que um brasileiro fala
        audio, taxa = self._kokoro.create(texto, voice=self.voz, speed=self.velocidade, lang="pt-br")
        self.taxa = int(taxa)
        return np.asarray(audio, dtype=np.float32)


def _tokens_de_voz() -> list:
    """Vozes do SAPI e as vozes OneCore do Windows (precisa de CoInitialize antes)."""
    import win32com.client

    colecao = win32com.client.Dispatch("SAPI.SpVoice").GetVoices()
    tokens = [colecao.Item(i) for i in range(colecao.Count)]
    try:
        categoria = win32com.client.Dispatch("SAPI.SpObjectTokenCategory")
        categoria.SetId(_CATEGORIA_ONECORE, False)
        colecao = categoria.EnumerateTokens()
        tokens += [colecao.Item(i) for i in range(colecao.Count)]
    except Exception:  # Windows sem vozes OneCore
        pass
    return tokens


class VozWindows:
    """Voz do próprio Windows (SAPI). Não precisa baixar nada."""

    motor = "sapi"

    def __init__(self, nome_voz: str = "Daniel", velocidade: float = 1.0):
        self.nome_voz = nome_voz
        self.velocidade = float(velocidade)
        self.taxa = 24000
        self.descricao = f"voz do Windows ({nome_voz or 'padrão'})"

    def sintetizar(self, texto: str) -> np.ndarray:
        import pythoncom

        pythoncom.CoInitialize()
        try:
            return self._sintetizar(pronuncia.aplicar(texto))  # os objetos COM são soltos antes do CoUninitialize
        finally:
            pythoncom.CoUninitialize()

    def _sintetizar(self, texto: str) -> np.ndarray:
        import win32com.client

        voz = win32com.client.Dispatch("SAPI.SpVoice")
        if self.nome_voz:
            for token in _tokens_de_voz():
                if self.nome_voz.lower() in token.GetDescription().lower():
                    voz.Voice = token
                    break
        voz.Rate = max(-10, min(10, int(round((self.velocidade - 1.0) * 10))))
        fluxo = win32com.client.Dispatch("SAPI.SpMemoryStream")
        formato = win32com.client.Dispatch("SAPI.SpAudioFormat")
        formato.Type = 26  # SAFT24kHz16BitMono
        fluxo.Format = formato
        voz.AudioOutputStream = fluxo
        voz.Speak(texto, 0)
        onda = fluxo.Format.GetWaveFormatEx()
        self.taxa = int(onda.SamplesPerSec)
        dados = np.frombuffer(bytes(fluxo.GetData()), dtype=np.int16).astype(np.float32) / 32768.0
        if int(onda.Channels) == 2:
            dados = dados.reshape(-1, 2).mean(axis=1)
        return dados


def vozes_windows() -> list[str]:
    try:
        import pythoncom

        pythoncom.CoInitialize()
        try:
            return list(dict.fromkeys(token.GetDescription() for token in _tokens_de_voz()))
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        return []


def descrever(cfg_voz) -> str:
    if cfg_voz.motor == "kokoro":
        return f"Kokoro, {VOZES_KOKORO.get(cfg_voz.voz, cfg_voz.voz)}"
    return f"voz do Windows ({cfg_voz.voz_sapi or 'padrão'})"


def criar(cfg_voz, progresso: modelos.Progresso | None = None) -> MotorVoz:
    if cfg_voz.motor == "kokoro":
        try:
            if not modelos.kokoro_pronto():
                modelos.baixar_kokoro(progresso)
            return VozKokoro(cfg_voz.voz, cfg_voz.velocidade)
        except Exception as erro:
            log.warning("Kokoro indisponível (%s). Usando a voz do Windows.", erro)
    return VozWindows(cfg_voz.voz_sapi, cfg_voz.velocidade)
