"""Comandos de música e volume que o próprio app resolve, sem passar pelo Claude.

A música é controlada pelo painel de mídia do Windows (o mesmo das teclas de mídia), escolhendo o
app que está tocando: o YouTube Music no navegador, o Spotify... Nada de janela em primeiro plano,
então dá para usar com um jogo em tela cheia. O volume é o geral do Windows (teclas de volume).
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
from datetime import datetime, timezone

from .ativacao import normalizar

log = logging.getLogger(__name__)

PROXIMA, ANTERIOR, PAUSAR, TOCAR, AUMENTAR, DIMINUIR = "proxima", "anterior", "pausar", "tocar", "aumentar", "diminuir"

_VERBOS = {
    PROXIMA: {"pula", "pular", "pule", "passa", "passar", "passe", "avanca", "avancar", "avance", "adianta",
              "adiantar", "adiante", "proxima", "proximo", "seguinte", "troca", "trocar", "troque", "muda", "mudar",
              "mude"},
    ANTERIOR: {"volta", "voltar", "volte", "anterior", "retorna", "retornar", "retorne"},
    PAUSAR: {"pausa", "pausar", "pause", "para", "parar", "pare"},
    TOCAR: {"toca", "tocar", "toque", "continua", "continuar", "continue", "solta", "soltar", "solte",
            "despausa", "despausar", "play", "retoma", "retomar", "retome"},
    AUMENTAR: {"aumenta", "aumentar", "aumente", "sobe", "subir", "suba", "alto", "aumentando"},
    DIMINUIR: {"abaixa", "abaixar", "abaixe", "baixa", "baixar", "baixe", "diminui", "diminuir", "diminua",
               "baixo", "abaixando"},
}
_MUSICA = {"musica", "musicas", "faixa", "som", "cancao", "video", "playlist"}
_VOLUME = {"volume", "som", "musica", "audio"}
_ENCHIMENTO = {"por", "favor", "o", "a", "e", "ai", "ok", "okay", "agora", "ja", "pra", "mim", "me", "pro",
               "da", "de", "do", "um", "uma", "pouco", "pouquinho", "ae", "mais", "essa", "esta", "isso", "outra",
               "tocando", "ta", "que", "pode", "vai", "muito", "bastante", "bem", "nessa", "no", "na"}
_MUITO = {"muito", "bastante", "bem"}
_POUCO = {"pouco", "pouquinho"}


def interpretar_midia(texto: str) -> tuple[str, int] | None:
    """("proxima", 1), ("aumentar", 5)... ou None quando a frase não é só um comando de música/volume.

    Só vale quando a frase inteira é o comando ("próxima música", "abaixa o volume"), como a palavra de
    parar: "o volume da reunião estava alto" é conversa e segue o caminho normal.
    """
    palavras = normalizar(texto).split()
    if not palavras or len(palavras) > 7:
        return None
    if palavras[0] == "para" and len(palavras) > 1 and palavras[1] not in {"a", "o"} | _MUSICA:
        return None  # "para de falar", "para com isso": não é pausar a música
    # "para" só é verbo no começo ("para a música"); no meio é preposição ("volume para baixo").
    restantes = [p for i, p in enumerate(palavras) if p not in _ENCHIMENTO and not (p == "para" and i > 0)]
    if not restantes or len(restantes) > 3:
        return None
    verbos = [acao for acao, formas in _VERBOS.items() if any(p in formas for p in restantes)]
    objetos = set(restantes)
    if "tocar" in objetos and ANTERIOR in verbos:  # "volta a tocar"
        return TOCAR, 1
    if set(verbos) == {TOCAR, PROXIMA}:  # "toca a próxima"
        verbos = [PROXIMA]
    if len(verbos) != 1:
        return None
    acao = verbos[0]
    formas = set().union(*(_VERBOS[v] for v in _VERBOS if v in (acao, TOCAR)))
    sobra = [p for p in restantes if p not in formas and p not in _MUSICA and p not in _VOLUME]
    if sobra:
        return None  # sobrou palavra que não é de comando: é outra coisa
    if acao in (AUMENTAR, DIMINUIR):
        if not objetos & _VOLUME:
            return None
        passos = 10 if set(palavras) & _MUITO else 2 if set(palavras) & _POUCO else 5
        return acao, passos
    if not objetos & _MUSICA and not (acao == PROXIMA and restantes[0] in {"proxima", "proximo"} and len(restantes) == 1):
        return None
    return acao, 1


# ------------------------------------------------------------------ execução
_VK_VOLUME = {AUMENTAR: 0xAF, DIMINUIR: 0xAE}  # cada toque muda 2% do volume do Windows
_VK_MIDIA = {PROXIMA: 0xB0, ANTERIOR: 0xB1, PAUSAR: 0xB3, TOCAR: 0xB3}
_KEYEVENTF_KEYUP = 0x0002


def _tecla(vk: int, vezes: int = 1) -> None:
    usuario = ctypes.windll.user32
    for _ in range(vezes):
        usuario.keybd_event(vk, 0, 0, 0)
        usuario.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)


async def _sessao_midia(acao: str):
    """A sessão de mídia certa: a que está tocando (ou, para tocar, a pausada mais recente)."""
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Gerente
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status

    gerente = await Gerente.request_async()
    sessoes = list(gerente.get_sessions())
    tocando = [s for s in sessoes if s.get_playback_info().playback_status == Status.PLAYING]
    if tocando:
        return tocando[0]
    if acao in (TOCAR, ANTERIOR, PROXIMA):
        pausadas = [s for s in sessoes if s.get_playback_info().playback_status == Status.PAUSED]
        atual = gerente.get_current_session()
        if atual is not None and atual in pausadas:
            return atual
        if pausadas:
            return pausadas[0]
    return gerente.get_current_session()


# Os players (YouTube Music, Spotify...) usam o "voltar" para recomeçar a música quando ela já passou
# dos primeiros segundos; só o segundo toque vai para a anterior.
_RECOMECA_APOS_S = 3.0


def _segundos_tocados(sessao) -> float | None:
    """Em que ponto a música está agora (None se o app não informa)."""
    try:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status

        linha = sessao.get_timeline_properties()
        if not linha.end_time.total_seconds():
            return None
        posicao = linha.position.total_seconds()
        if sessao.get_playback_info().playback_status == Status.PLAYING:  # a posição é a da última atualização
            posicao += max(0.0, (datetime.now(timezone.utc) - linha.last_updated_time).total_seconds())
        return posicao
    except Exception:
        return None


async def executar(acao: str, passos: int = 1) -> bool:
    """Faz o comando. True se deu certo (ou pelo menos a tecla foi mandada)."""
    if acao in _VK_VOLUME:
        _tecla(_VK_VOLUME[acao], passos)
        return True
    try:
        sessao = await _sessao_midia(acao)
        if sessao is None:
            log.info("Nenhum app tocando música para %s.", acao)
            return False
        metodo = {
            PROXIMA: sessao.try_skip_next_async,
            ANTERIOR: sessao.try_skip_previous_async,
            PAUSAR: sessao.try_pause_async,
            TOCAR: sessao.try_play_async,
        }[acao]
        if acao == ANTERIOR:
            tocado = _segundos_tocados(sessao)
            if tocado is not None and tocado > _RECOMECA_APOS_S:  # o 1º toque só recomeçaria esta música
                await metodo()
                await asyncio.sleep(0.4)
        ok = bool(await metodo())
        log.info("Música: %s em %s (%s).", acao, sessao.source_app_user_model_id, "ok" if ok else "recusado")
        return ok
    except ImportError:
        log.warning("Pacotes winrt ausentes: usando as teclas de mídia.")
    except Exception:
        log.exception("Falha no painel de mídia do Windows: usando as teclas de mídia.")
    _tecla(_VK_MIDIA[acao])
    return True
