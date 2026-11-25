"""Ajustes do ambiente do processo antes de abrir o Claude Code."""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_PREFIXOS = ("CLAUDE_CODE_", "CLAUDE_AGENT_SDK_")
_EXATAS = {"CLAUDECODE", "CLAUDE_PID", "CLAUDE_PREVIEW_CLASSIFIER_FLOOR", "ANTHROPIC_BASE_URL"}
_MANTER = {"CLAUDE_CONFIG_DIR", "CLAUDE_CODE_GIT_BASH_PATH"}


def limpar_heranca_claude() -> list[str]:
    """Remove variáveis de uma sessão do Claude Code que abriu este app.

    Se o app for aberto de dentro de uma sessão do Claude Code (por exemplo, por um
    terminal do Claude Desktop), ele herdaria as variáveis daquela sessão, e o Claude
    Code que o app abre acharia que é parte dela. Aberto normalmente (atalho,
    Explorer, terminal comum), nada é removido.
    """
    if "CLAUDECODE" not in os.environ and "CLAUDE_CODE_HOST_SESSION_ID" not in os.environ:
        return []
    removidas = sorted(
        nome
        for nome in os.environ
        if nome not in _MANTER and (nome in _EXATAS or nome.startswith(_PREFIXOS))
    )
    for nome in removidas:
        os.environ.pop(nome, None)
    if removidas:
        log.info(
            "Aberto de dentro de uma sessão do Claude Code: ignorei %d variáveis herdadas (%s).",
            len(removidas),
            ", ".join(removidas),
        )
    return removidas
