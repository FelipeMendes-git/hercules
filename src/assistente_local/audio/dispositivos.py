"""Escolha de microfone e alto-falante."""

from __future__ import annotations

import sounddevice as sd


def _canais(entrada: bool) -> str:
    return "max_input_channels" if entrada else "max_output_channels"


def listar(entrada: bool) -> list[tuple[int, str]]:
    """Dispositivos da mesma API de áudio do padrão (para não repetir o mesmo aparelho)."""
    try:
        todos = sd.query_devices()
        padrao = sd.default.device[0 if entrada else 1]
        host = todos[padrao]["hostapi"] if padrao is not None and padrao >= 0 else None
    except Exception:
        return []
    return [
        (indice, d["name"])
        for indice, d in enumerate(todos)
        if d[_canais(entrada)] > 0 and (host is None or d["hostapi"] == host)
    ]


def resolver(nome: str, entrada: bool) -> int | None:
    """Índice do dispositivo cujo nome contém ``nome``; ``None`` usa o padrão do Windows."""
    nome = (nome or "").strip()
    if not nome:
        return None
    if nome.isdigit():
        return int(nome)
    alvo = nome.lower()
    for indice, rotulo in listar(entrada):
        if alvo in rotulo.lower():
            return indice
    try:
        for indice, d in enumerate(sd.query_devices()):
            if alvo in d["name"].lower() and d[_canais(entrada)] > 0:
                return indice
    except Exception:
        pass
    return None


def nome(indice: int | None, entrada: bool) -> str:
    try:
        info = sd.query_devices(indice, "input" if entrada else "output")
        return str(info["name"])
    except Exception:
        return "padrão do Windows"
