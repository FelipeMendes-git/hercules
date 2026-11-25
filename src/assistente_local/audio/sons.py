"""Sons curtos de aviso, gerados na hora (sem arquivos)."""

from __future__ import annotations

import numpy as np

TAXA = 24000

_NOTAS: dict[str, list[tuple[float, float]]] = {
    "ativou": [(660.0, 0.07), (990.0, 0.10)],
    "pensando": [(523.25, 0.06)],
    "pronto": [(880.0, 0.06), (1174.66, 0.09)],
    "ok": [(880.0, 0.07)],
    "erro": [(440.0, 0.10), (330.0, 0.16)],
}
_cache: dict[tuple[str, float], np.ndarray] = {}


def som(nome: str, volume: float = 0.22) -> np.ndarray:
    chave = (nome, round(volume, 3))
    if chave not in _cache:
        partes = []
        for frequencia, duracao in _NOTAS.get(nome, _NOTAS["ok"]):
            t = np.arange(int(TAXA * duracao)) / TAXA
            onda = 0.8 * np.sin(2 * np.pi * frequencia * t) + 0.2 * np.sin(4 * np.pi * frequencia * t)
            envelope = np.clip(np.minimum(t / 0.006, (duracao - t) / 0.04), 0.0, 1.0)
            partes.append(onda * envelope)
            partes.append(np.zeros(int(TAXA * 0.015)))
        _cache[chave] = (np.concatenate(partes) * volume).astype(np.float32)
    return _cache[chave]
