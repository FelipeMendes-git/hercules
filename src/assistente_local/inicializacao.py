"""Iniciar com o Windows: um valor na chave Run do usuário (aparece no Gerenciador de Tarefas,
em "Aplicativos de inicialização", onde também dá para desligar)."""

from __future__ import annotations

import sys
from pathlib import Path

from .marca import ID_APP

_CHAVE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"


def comando() -> str:
    """Comando que o Windows roda ao entrar: o app escondido na bandeja."""
    scripts = Path(sys.prefix) / "Scripts"
    executavel = scripts / "hercules.exe"
    if executavel.is_file():
        return f'"{executavel}" --bandeja'
    pythonw = scripts / "pythonw.exe"
    if not pythonw.is_file():
        pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" -m assistente_local --bandeja'


def ativo() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CHAVE_RUN) as chave:
            valor, _tipo = winreg.QueryValueEx(chave, ID_APP)
            return bool(valor)
    except OSError:
        return False


def definir(ativar: bool) -> None:
    """Liga ou desliga a inicialização com o Windows (só para o seu usuário)."""
    if sys.platform != "win32":
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CHAVE_RUN, 0, winreg.KEY_SET_VALUE) as chave:
        if ativar:
            winreg.SetValueEx(chave, ID_APP, 0, winreg.REG_SZ, comando())
        else:
            try:
                winreg.DeleteValue(chave, ID_APP)
            except FileNotFoundError:
                pass
