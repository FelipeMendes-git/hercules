import asyncio

from assistente_local import config
from assistente_local import eventos as ev
from assistente_local.controlador import _FerramentasDoApp
from assistente_local.ponte_claude import (
    FERRAMENTAS_DO_APP,
    criar_ferramentas_do_app,
    nome_do_modelo,
    normalizar_esforco,
    normalizar_modelo,
    rotulo_esforco,
)


class _AcoesFalsas:
    def __init__(self):
        self.chamadas = []

    async def listar_projetos(self):
        return "- a: C:/a", False

    async def trocar_projeto(self, projeto, continuar_com):
        self.chamadas.append(("trocar", projeto, continuar_com))
        return "ok", False

    async def nova_conversa(self, continuar_com):
        self.chamadas.append(("nova", continuar_com))
        return "ok", False

    async def copiar(self, texto):
        self.chamadas.append(("copiar", texto))
        return "ok", False

    async def abrir(self, caminho, na_pasta):
        self.chamadas.append(("abrir", caminho, na_pasta))
        return "não existe", True

    async def desfazer(self):
        return "ok", False

    async def ajustar_claude(self, esforco, modelo):
        self.chamadas.append(("ajustar", esforco, modelo))
        return "ok", False


def test_ferramentas_chamam_as_acoes_do_app():
    acoes = _AcoesFalsas()
    ferramentas = {f.name: f for f in criar_ferramentas_do_app(acoes)}
    assert set(ferramentas) == set(FERRAMENTAS_DO_APP)

    resposta = asyncio.run(ferramentas["trocar_projeto"].handler({"projeto": "educai", "continuar_com": "roda os testes"}))
    assert resposta["content"][0]["text"] == "ok" and "is_error" not in resposta
    asyncio.run(ferramentas["copiar"].handler({"texto": "C:/x.pdf"}))
    erro = asyncio.run(ferramentas["abrir"].handler({"caminho": "C:/nada", "mostrar_na_pasta": True}))
    assert erro["is_error"] is True
    asyncio.run(ferramentas["ajustar_claude"].handler({"esforco": "medium"}))
    assert acoes.chamadas == [
        ("trocar", "educai", "roda os testes"),
        ("copiar", "C:/x.pdf"),
        ("abrir", "C:/nada", True),
        ("ajustar", "medium", ""),
    ]


class _PonteFalsa:
    pode_desfazer = False


class _ControladorFalso:
    def __init__(self, raiz):
        self._lista = [config.Projeto("educai", str(raiz / "educai")), config.Projeto("site", str(raiz / "site"))]
        for projeto in self._lista:
            (raiz / projeto.nome).mkdir()
        self.projeto_atual = self._lista[0]
        self.eventos = []
        self.depois = []
        self._ponte = _PonteFalsa()
        self.cfg = config.Config()
        self.mudancas = []

    async def _mudar_claude(self, **mudancas):
        self.mudancas.append(mudancas)

    def projetos(self):
        return self._lista

    def _projeto_por_caminho(self, caminho):
        return next((p for p in self._lista if p.caminho == caminho), None)

    def _emitir(self, evento):
        self.eventos.append(evento)

    def _depois_do_turno(self, acao):
        self.depois.append(acao)


def test_trocar_projeto_fica_para_o_fim_da_resposta(tmp_path):
    controlador = _ControladorFalso(tmp_path)
    ferramentas = _FerramentasDoApp(controlador)
    texto, erro = asyncio.run(ferramentas.trocar_projeto("o site", "me diz o que falta"))
    assert not erro and "site" in texto
    assert len(controlador.depois) == 1  # executa quando a resposta terminar

    texto, erro = asyncio.run(ferramentas.trocar_projeto("banana", ""))
    assert erro and "educai" in texto  # lista os projetos para o Claude escolher

    texto, erro = asyncio.run(ferramentas.trocar_projeto("educai", ""))
    assert not erro and "já está" in texto
    assert len(controlador.depois) == 1


def test_copiar_abrir_e_desfazer(tmp_path):
    controlador = _ControladorFalso(tmp_path)
    ferramentas = _FerramentasDoApp(controlador)
    (tmp_path / "educai" / "relatorio.pdf").write_bytes(b"%PDF")

    asyncio.run(ferramentas.copiar("C:/caminho/relatorio.pdf"))
    texto, erro = asyncio.run(ferramentas.abrir("relatorio.pdf", True))  # relativo ao projeto atual
    assert not erro
    texto, erro = asyncio.run(ferramentas.abrir("nao-existe.pdf", False))
    assert erro
    copiar, abrir = controlador.eventos
    assert isinstance(copiar, ev.Copiar) and copiar.texto == "C:/caminho/relatorio.pdf"
    assert isinstance(abrir, ev.Abrir) and abrir.na_pasta and abrir.caminho.endswith("relatorio.pdf")

    texto, erro = asyncio.run(ferramentas.desfazer())
    assert erro and not controlador.depois  # nada para desfazer


def test_ajustar_claude_fica_para_o_fim_da_resposta(tmp_path):
    controlador = _ControladorFalso(tmp_path)
    ferramentas = _FerramentasDoApp(controlador)
    assert controlador.cfg.claude.esforco == "medium" and controlador.cfg.claude.modelo == "claude-opus-5-5"

    texto, erro = asyncio.run(ferramentas.ajustar_claude("alto", ""))
    assert not erro and "alto" in texto and "Opus 5.5" in texto
    assert len(controlador.depois) == 1 and not controlador.mudancas  # só muda quando a resposta terminar
    asyncio.run(controlador.depois[0]())
    assert controlador.mudancas == [{"esforco": "high"}]

    texto, erro = asyncio.run(ferramentas.ajustar_claude("low", "sonnet"))
    assert not erro and "Sonnet 5.5" in texto and "baixo" in texto
    asyncio.run(controlador.depois[1]())
    assert controlador.mudancas[1] == {"esforco": "low", "modelo": "claude-sonnet-5-5"}


def test_entende_o_esforco_e_o_modelo_falados():
    assert normalizar_esforco("Médio") == "medium"
    assert normalizar_esforco(" rápido ") == "low"
    assert normalizar_esforco("máximo") == "max"
    assert normalizar_esforco("auto") == "" and normalizar_esforco("padrão") == ""  # o Claude Code escolhe
    assert normalizar_esforco("turbo") is None
    assert normalizar_modelo("Sonnet") == "claude-sonnet-5-5"
    assert normalizar_modelo("Opus 5.5") == "claude-opus-5-5"
    assert normalizar_modelo("claude-haiku-5-5") == "claude-haiku-5-5"
    assert normalizar_modelo("padrão") == ""
    assert normalizar_modelo("opus 4.1") is None and normalizar_modelo("gpt") is None  # não inventa modelo
    assert nome_do_modelo("claude-sonnet-5-5") == "Sonnet 5.5"
    assert rotulo_esforco("medium") == "médio" and rotulo_esforco("") == "padrão"


def test_ajustar_claude_recusa_valor_estranho_e_avisa_quando_ja_esta(tmp_path):
    controlador = _ControladorFalso(tmp_path)
    ferramentas = _FerramentasDoApp(controlador)

    texto, erro = asyncio.run(ferramentas.ajustar_claude("turbo", ""))
    assert erro and "medium" in texto
    texto, erro = asyncio.run(ferramentas.ajustar_claude("", "gpt"))
    assert erro and "sonnet" in texto
    texto, erro = asyncio.run(ferramentas.ajustar_claude("", ""))  # sem mudança: só conta o que está em uso
    assert not erro and "Opus 5.5" in texto and "médio" in texto
    texto, erro = asyncio.run(ferramentas.ajustar_claude("médio", "opus"))  # já é o que está em uso
    assert not erro and "Já está" in texto
    assert not controlador.depois
