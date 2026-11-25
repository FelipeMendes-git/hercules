"""Modo terminal: o assistente sem janela (bom para testar e ver o que acontece)."""

from __future__ import annotations

import os
import subprocess
import sys

from . import eventos as ev
from .controlador import Controlador

_AJUDA = (
    "Fale normalmente ou digite uma mensagem e Enter. Comandos: /sim  /nao  /sempre  /parar  /nova  "
    "/mudo  /ligar  /repete  /login  /logado  /sair"
)


def _copiar(texto: str) -> None:
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(texto, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    except Exception as erro:
        print(f"(não consegui copiar: {erro})")


def _abrir(caminho: str, na_pasta: bool) -> None:
    if na_pasta and os.path.isfile(caminho):
        subprocess.Popen(f'explorer /select,"{os.path.normpath(caminho)}"')
    else:
        os.startfile(caminho)  # noqa: S606 (abre com o programa padrão do Windows)


class _Impressora:
    def __init__(self) -> None:
        self.aprovacao_pendente = ""

    def __call__(self, evento: object) -> None:
        texto = self._formatar(evento)
        if texto:
            print(texto, flush=True)

    def _formatar(self, evento: object) -> str:
        if isinstance(evento, (ev.NivelMicrofone, ev.InicioResposta, ev.ConversaNova)):
            return ""
        if isinstance(evento, ev.EstadoMudou):
            return f"[{evento.estado.value}]" + (f" {evento.detalhe}" if evento.detalhe else "")
        if isinstance(evento, ev.Carregando):
            fracao = f" {evento.fracao:.0%}" if evento.fracao is not None else ""
            return f"... {evento.mensagem}{fracao}"
        if isinstance(evento, ev.Pronto):
            return (
                f"Pronto. Reconhecimento: {evento.reconhecimento}. Voz: {evento.voz}. "
                f"Microfone: {evento.microfone}. {evento.claude}.\n{_AJUDA}"
            )
        if isinstance(evento, ev.ConversaCarregada):
            return f"(conversa salva com {len(evento.entradas)} registros)" if evento.entradas else ""
        if isinstance(evento, ev.ProjetoAtual):
            return f"Projeto: {evento.nome} ({evento.caminho})" + (" - conversa retomada" if evento.retomada else "")
        if isinstance(evento, ev.FalaUsuario):
            return f"\nVocê ({evento.origem}): {evento.texto}"
        if isinstance(evento, ev.FalaIgnorada):
            return f"(ouvi, mas não era comigo: {evento.texto})"
        if isinstance(evento, ev.TextoClaude):
            return f"Claude: {evento.texto}"
        if isinstance(evento, ev.AcaoClaude):
            return f"   > {evento.descricao}"
        if isinstance(evento, ev.FimResposta):
            partes = [f"{evento.duracao_s:.0f} s"]
            if evento.custo_usd:
                partes.append(f"US$ {evento.custo_usd:.4f}")
            linha = f"   ({', '.join(partes)})"
            for caminho in evento.arquivos:
                linha += f"\n   Arquivo: {caminho}"
            if evento.erro:
                linha += f"\n   ERRO: {evento.erro}"
            if evento.interrompida:
                linha += "\n   (interrompido)"
            if evento.fala:
                linha += f"\n   Falando: {evento.fala}"
            return linha
        if isinstance(evento, ev.PedidoAprovacao):
            self.aprovacao_pendente = evento.id
            return f"\n!! {evento.pergunta}\n   {evento.detalhe}\n   (responda falando, ou digite /sim, /nao ou /sempre)"
        if isinstance(evento, ev.AprovacaoResolvida):
            self.aprovacao_pendente = ""
            return f"   -> {'aprovado' if evento.aprovado else 'recusado'} ({evento.por})"
        if isinstance(evento, ev.LoginNecessario):
            return "\n!! O Claude Code precisa de login. Digite /login (abre a janela de login) e depois /logado."
        if isinstance(evento, ev.LoginConfirmado):
            return "Login confirmado."
        if isinstance(evento, ev.Copiar):
            _copiar(evento.texto)
            return f"(copiei {evento.descricao or 'o texto'})"
        if isinstance(evento, ev.Abrir):
            _abrir(evento.caminho, evento.na_pasta)
            return f"(abrindo {evento.caminho})"
        if isinstance(evento, ev.Aviso):
            return ("ERRO: " if evento.nivel == "erro" else "Aviso: ") + evento.mensagem
        return f"{type(evento).__name__}: {evento}"


def executar(cfg) -> int:
    impressora = _Impressora()
    controlador = Controlador(cfg, impressora)
    controlador.iniciar()
    try:
        for linha in sys.stdin:
            linha = linha.strip()
            if not linha:
                continue
            if linha == "/sair":
                break
            if linha in ("/sim", "/nao", "/sempre"):
                if impressora.aprovacao_pendente:
                    controlador.responder_aprovacao(impressora.aprovacao_pendente, linha != "/nao", linha == "/sempre")
                continue
            acoes = {
                "/parar": controlador.interromper,
                "/nova": controlador.nova_conversa,
                "/mudo": lambda: controlador.definir_microfone(False),
                "/ligar": lambda: controlador.definir_microfone(True),
                "/repete": controlador.repetir,
                "/login": controlador.abrir_login,
                "/logado": controlador.confirmar_login,
            }
            if linha in acoes:
                acoes[linha]()
            else:
                controlador.enviar_texto(linha)
    except KeyboardInterrupt:
        pass
    finally:
        print("Fechando...", flush=True)
        controlador.encerrar()
    return 0
