"""Gera recursos/icone.ico a partir do ícone desenhado pelo app (usado no atalho do Windows)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> int:
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QApplication

    from assistente_local.interface import icones

    QApplication.instance() or QApplication(sys.argv)
    destino = Path(__file__).resolve().parents[1] / "recursos" / "icone.ico"
    destino.parent.mkdir(parents=True, exist_ok=True)
    imagem = icones.icone_app().pixmap(QSize(256, 256))
    if not imagem.save(str(destino), "ICO"):
        print("Não consegui salvar o ícone.")
        return 1
    print(destino)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
