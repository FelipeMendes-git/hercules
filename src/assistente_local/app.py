"""Ponto de entrada do app."""

from __future__ import annotations

import argparse
import logging
import sys

from . import ambiente, config, logs
from .marca import ID_APP, NOME_APP, VERSAO

_trava_instancia = None  # mantém o mutex vivo enquanto o app roda


def _argumentos(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="hercules", description=f"{NOME_APP} {VERSAO}")
    parser.add_argument("--console", action="store_true", help="roda sem janela, mostrando tudo no terminal")
    parser.add_argument("--bandeja", action="store_true", help="abre escondido na bandeja (ao iniciar com o Windows)")
    parser.add_argument("--debug", action="store_true", help="grava mais detalhes no log")
    return parser.parse_args(argv)


def _prioridade_baixa() -> None:
    """Prioridade "abaixo do normal": em disputa por processador (um jogo), o outro programa ganha.

    O Claude Code, aberto por este processo, herda a mesma prioridade.
    """
    if sys.platform != "win32":
        return
    try:
        import win32api
        import win32process

        win32process.SetPriorityClass(win32api.GetCurrentProcess(), win32process.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception as erro:
        logging.getLogger(__name__).warning("Não consegui baixar a prioridade: %s", erro)


def _sou_a_unica_instancia() -> bool:
    """Evita dois assistentes ouvindo o mesmo microfone (e respondendo em dobro)."""
    global _trava_instancia
    if sys.platform != "win32":
        return True
    import win32api
    import win32event
    import winerror

    _trava_instancia = win32event.CreateMutex(None, False, f"Local\\{ID_APP}-instancia-unica")
    return win32api.GetLastError() != winerror.ERROR_ALREADY_EXISTS


def main(argv: list[str] | None = None) -> int:
    args = _argumentos(sys.argv[1:] if argv is None else argv)
    logs.configurar(logging.DEBUG if args.debug else logging.INFO, console=args.console)
    log = logging.getLogger(__name__)
    log.info("Iniciando %s %s", NOME_APP, VERSAO)
    ambiente.limpar_heranca_claude()
    unica = _sou_a_unica_instancia()
    cfg = config.carregar()
    if cfg.interface.prioridade_baixa:
        _prioridade_baixa()
    if args.console:
        if not unica:
            print(f"O {NOME_APP} já está aberto. Feche a outra janela primeiro.")
            return 1
        from .console import executar

        return executar(cfg)
    from .interface.aplicacao import executar

    return executar(cfg, ja_aberto=not unica, na_bandeja=args.bandeja)


def main_console() -> int:
    return main(["--console", *sys.argv[1:]])
