"""Histórico das conversas.

Cada conversa vira um arquivo ``.jsonl`` (uma linha por mensagem) em
``dados/conversas/<projeto>/<data e hora>.jsonl``. A primeira linha descreve a conversa
(projeto, pasta e sessão do Claude Code). Assim o app mostra de novo a conversa quando
você volta a ela, e a janela "Conversas" lista todas, com opção de exportar como texto.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import caminhos
from . import eventos as ev

log = logging.getLogger(__name__)


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _nome_de_pasta(nome: str) -> str:
    return re.sub(r'[<>:"/\\|?*\s]+', "_", nome).strip("._") or "projeto"


@dataclass
class ResumoConversa:
    arquivo: Path
    projeto: str
    caminho_projeto: str
    sessao: str | None
    inicio: datetime
    titulo: str
    mensagens: int


class Historico:
    def __init__(self, pasta: Path | None = None):
        self.pasta = pasta or (caminhos.pasta_dados() / "conversas")
        self.pasta.mkdir(parents=True, exist_ok=True)
        self._arquivo_indice = self.pasta / "indice.json"
        self._indice: dict[str, str] = self._ler_indice()
        self._trava = threading.Lock()
        self._atual: Path | None = None
        self._cabecalho: dict = {}

    # ------------------------------------------------------------------ conversa atual
    @property
    def arquivo_atual(self) -> Path | None:
        return self._atual

    def abrir(self, projeto: str, caminho_projeto: str, sessao: str | None) -> list[dict]:
        """Passa a gravar na conversa desta sessão (ou numa nova) e devolve o que já estava salvo."""
        with self._trava:
            self._cabecalho = {
                "tipo": "conversa",
                "projeto": projeto,
                "caminho_projeto": caminho_projeto,
                "sessao": sessao,
                "inicio": _agora(),
            }
            self._atual = None
            if sessao and sessao in self._indice:
                arquivo = self.pasta / self._indice[sessao]
                if arquivo.is_file():
                    self._atual = arquivo
        if self._atual is None:
            return []  # o arquivo só é criado na primeira mensagem
        return [e for e in self.ler(self._atual) if e.get("tipo") not in ("conversa", "sessao")]

    def associar_sessao(self, sessao: str | None) -> None:
        if not sessao:
            return
        with self._trava:
            if self._cabecalho.get("sessao") == sessao and (self._atual is None or sessao in self._indice):
                return
            self._cabecalho["sessao"] = sessao
            if self._atual is not None:
                self._escrever({"t": _agora(), "tipo": "sessao", "sessao": sessao})
                self._indexar(sessao)

    def registrar(self, entrada: dict) -> None:
        with self._trava:
            if not self._cabecalho:
                return
            if self._atual is None:
                self._atual = self._novo_arquivo()
                self._escrever(self._cabecalho)
                if self._cabecalho.get("sessao"):
                    self._indexar(self._cabecalho["sessao"])
            self._escrever({"t": _agora(), **entrada})

    def registrar_evento(self, evento: object) -> None:
        """Grava o que importa de cada evento do controlador."""
        if isinstance(evento, ev.FalaUsuario):
            self.registrar({"tipo": "voce", "texto": evento.texto, "origem": evento.origem})
        elif isinstance(evento, ev.InicioResposta):
            self.registrar({"tipo": "inicio_resposta"})
        elif isinstance(evento, ev.TextoClaude):
            self.registrar({"tipo": "claude", "texto": evento.texto})
        elif isinstance(evento, ev.AcaoClaude):
            self.registrar({"tipo": "acao", "texto": evento.descricao, "ferramenta": evento.ferramenta})
        elif isinstance(evento, ev.FimResposta):
            self.registrar(
                {
                    "tipo": "fim",
                    "fala": evento.fala,
                    "duracao": round(evento.duracao_s, 1),
                    "custo": evento.custo_usd,
                    "erro": evento.erro,
                    "interrompida": evento.interrompida,
                    "arquivos": evento.arquivos,
                }
            )
        elif isinstance(evento, ev.PedidoAprovacao):
            self.registrar({"tipo": "pedido", "id": evento.id, "pergunta": evento.pergunta, "detalhe": evento.detalhe})
        elif isinstance(evento, ev.AprovacaoResolvida):
            self.registrar({"tipo": "resposta_pedido", "id": evento.id, "aprovado": evento.aprovado, "por": evento.por})
        elif isinstance(evento, ev.Aviso) and evento.nivel == "erro":
            self.registrar({"tipo": "aviso", "texto": evento.mensagem, "nivel": "erro"})

    # ------------------------------------------------------------------ consulta
    def listar(self) -> list[ResumoConversa]:
        resumos = []
        for arquivo in self.pasta.glob("*/*.jsonl"):
            entradas = self.ler(arquivo)
            if not entradas or entradas[0].get("tipo") != "conversa":
                continue
            cabecalho = entradas[0]
            sessao = cabecalho.get("sessao")
            for entrada in entradas:
                if entrada.get("tipo") == "sessao":
                    sessao = entrada.get("sessao") or sessao
            falas = [e for e in entradas if e.get("tipo") == "voce"]
            titulo = (falas[0].get("texto", "") if falas else "(sem mensagens)").strip()
            try:
                inicio = datetime.fromisoformat(cabecalho.get("inicio", ""))
            except ValueError:
                inicio = datetime.fromtimestamp(arquivo.stat().st_mtime)
            resumos.append(
                ResumoConversa(
                    arquivo,
                    cabecalho.get("projeto", arquivo.parent.name),
                    cabecalho.get("caminho_projeto", ""),
                    sessao,
                    inicio,
                    titulo[:140],
                    sum(1 for e in entradas if e.get("tipo") in ("voce", "fim")),
                )
            )
        return sorted(resumos, key=lambda r: r.inicio, reverse=True)

    @staticmethod
    def ler(arquivo: Path) -> list[dict]:
        entradas = []
        try:
            with open(arquivo, encoding="utf-8") as leitura:
                for linha in leitura:
                    linha = linha.strip()
                    if not linha:
                        continue
                    try:
                        entradas.append(json.loads(linha))
                    except ValueError:
                        continue
        except OSError as erro:
            log.warning("Não consegui ler %s: %s", arquivo, erro)
        return entradas

    def exportar_markdown(self, arquivo: Path) -> str:
        entradas = self.ler(arquivo)
        cabecalho = entradas[0] if entradas and entradas[0].get("tipo") == "conversa" else {}
        try:
            data = datetime.fromisoformat(cabecalho.get("inicio", "")).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            data = ""
        linhas = [f"# Conversa · {cabecalho.get('projeto', '')} · {data}".rstrip(" ·"), ""]
        pedidos: dict[str, dict] = {}
        for entrada in entradas:
            tipo = entrada.get("tipo")
            if tipo == "voce":
                linhas += [f"**Você:** {entrada.get('texto', '')}", ""]
            elif tipo == "claude":
                linhas += ["**Claude:**", "", entrada.get("texto", ""), ""]
            elif tipo == "acao":
                linhas.append(f"> {entrada.get('texto', '')}")
            elif tipo == "fim":
                if entrada.get("erro"):
                    linhas += [f"*Erro: {entrada['erro']}*", ""]
                if entrada.get("fala"):
                    linhas += [f"🔊 *{entrada['fala']}*", ""]
                for caminho in entrada.get("arquivos") or []:
                    linhas.append(f"- `{caminho}`")
                linhas.append("")
            elif tipo == "pedido":
                pedidos[entrada.get("id", "")] = entrada
            elif tipo == "resposta_pedido":
                pedido = pedidos.pop(entrada.get("id", ""), {})
                resultado = "aprovado" if entrada.get("aprovado") else "negado"
                linhas += [f"*Permissão: {pedido.get('pergunta', '')} → {resultado}*", ""]
            elif tipo == "aviso":
                linhas += [f"*{entrada.get('texto', '')}*", ""]
        return "\n".join(linhas).strip() + "\n"

    # ------------------------------------------------------------------ arquivos
    def _novo_arquivo(self) -> Path:
        pasta = self.pasta / _nome_de_pasta(self._cabecalho.get("projeto", "projeto"))
        pasta.mkdir(parents=True, exist_ok=True)
        base = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        arquivo = pasta / f"{base}.jsonl"
        contador = 2
        while arquivo.exists():
            arquivo = pasta / f"{base}_{contador}.jsonl"
            contador += 1
        return arquivo

    def _escrever(self, entrada: dict) -> None:
        try:
            with open(self._atual, "a", encoding="utf-8") as saida:
                saida.write(json.dumps(entrada, ensure_ascii=False) + "\n")
        except OSError as erro:
            log.warning("Não consegui gravar a conversa em %s: %s", self._atual, erro)

    def _ler_indice(self) -> dict[str, str]:
        try:
            if self._arquivo_indice.is_file():
                dados = json.loads(self._arquivo_indice.read_text(encoding="utf-8"))
                if isinstance(dados, dict):
                    return {str(k): str(v) for k, v in dados.items()}
        except (OSError, ValueError) as erro:
            log.warning("Não consegui ler o índice das conversas: %s", erro)
        return {}

    def _indexar(self, sessao: str) -> None:
        if self._atual is None:
            return
        self._indice[sessao] = os.path.relpath(self._atual, self.pasta)
        try:
            temporario = self._arquivo_indice.with_suffix(".tmp")
            temporario.write_text(json.dumps(self._indice, ensure_ascii=False, indent=1), encoding="utf-8")
            temporario.replace(self._arquivo_indice)
        except OSError as erro:
            log.warning("Não consegui salvar o índice das conversas: %s", erro)
