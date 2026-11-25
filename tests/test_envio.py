"""Pedido falado em rascunho (silêncio ou "câmbio" para mandar) e fila de pedidos com o Claude ocupado."""

import asyncio
import time

import pytest

from assistente_local import config
from assistente_local import eventos as ev
from assistente_local.ativacao import DetectorEnvio, eh_cancelamento
from assistente_local.controlador import Controlador
from assistente_local.estado import Estado
from assistente_local.historico import Historico
from assistente_local.ponte_claude import EventoFim


@pytest.mark.parametrize(
    "texto, resto, enviar",
    [
        ("Cria uma função que soma dois números, câmbio.", "Cria uma função que soma dois números", True),
        ("cria o arquivo Câmbio", "cria o arquivo", True),
        ("Câmbio.", "", True),
        ("faz isso. Cambio, câmbio!", "faz isso", True),
        ("Me diz como está o câmbio.", "Me diz como está o câmbio.", False),  # o substantivo
        ("Qual é o câmbio do dólar hoje?", "Qual é o câmbio do dólar hoje?", False),  # não está no fim
        ("cria uma função que soma dois números", "cria uma função que soma dois números", False),
        ("", "", False),
    ],
)
def test_palavra_de_envio_so_no_fim(texto, resto, enviar):
    assert DetectorEnvio("câmbio").separar(texto) == (resto, enviar)


@pytest.mark.parametrize(
    "texto, cancela",
    [
        ("Cancela.", True),
        ("esquece isso", True),
        ("Ok, deixa pra lá.", True),
        ("cancela a reunião de amanhã", False),  # é um pedido
        ("esquece o que eu falei sobre o banco e usa o arquivo novo", False),
    ],
)
def test_cancelamento_so_quando_e_a_frase_inteira(texto, cancela):
    assert eh_cancelamento(texto) is cancela


def _pronto(tmp_path, monkeypatch, espera=5.0, juntar=10.0):
    monkeypatch.setenv("ASSISTENTE_LOCAL_DADOS", str(tmp_path / "dados"))
    eventos: list = []
    cfg = config.Config()
    cfg.ativacao.espera_envio_s = espera
    cfg.ativacao.juntar_pedido_s = juntar
    cfg.saudacao.quando = "nunca"
    controlador = Controlador(
        cfg, eventos.append, simular_microfone=True, sem_som=True,
        estado_salvo=Estado(tmp_path / "estado.json"), historico=Historico(tmp_path / "conversas"),
    )
    controlador._carregado = True
    controlador._em_espera = False
    turnos: list[str] = []
    monkeypatch.setattr(controlador, "_iniciar_turno", turnos.append)
    monkeypatch.setattr(controlador, "_acordar", lambda: None)
    return controlador, eventos, turnos


def _no_loop(controlador, cenario):
    async def rodar():
        controlador._loop = asyncio.get_running_loop()
        controlador._falas = asyncio.Queue()
        await cenario()

    asyncio.run(rodar())


def test_pedido_falado_espera_e_cambio_manda_na_hora(tmp_path, monkeypatch):
    controlador, eventos, turnos = _pronto(tmp_path, monkeypatch)

    async def cenario():
        await controlador._comando("cria um arquivo de notas", origem="voz")
        assert turnos == []  # ainda não foi: você pode estar pensando
        assert controlador._calcular_estado() == (ev.Estado.RASCUNHO, "câmbio")
        rascunhos = [e for e in eventos if isinstance(e, ev.Rascunho)]
        assert rascunhos[-1].texto == "cria um arquivo de notas" and rascunhos[-1].envia_em > time.monotonic()
        controlador._receber_trecho("com a data de hoje, câmbio.")
        assert turnos == ["cria um arquivo de notas com a data de hoje"]
        assert not controlador._rascunho
        assert any(isinstance(e, ev.FalaUsuario) and e.texto == turnos[0] for e in eventos)
        assert [e.texto for e in eventos if isinstance(e, ev.Rascunho)][-1] == ""  # o painel some

    _no_loop(controlador, cenario)


def test_teclado_continua_mandando_na_hora(tmp_path, monkeypatch):
    controlador, _eventos, turnos = _pronto(tmp_path, monkeypatch)

    async def cenario():
        await controlador._comando("lista os arquivos", origem="teclado")
        assert turnos == ["lista os arquivos"] and not controlador._rascunho

    _no_loop(controlador, cenario)


def test_pedido_vai_sozinho_depois_do_silencio_e_nao_corre_enquanto_voce_fala(tmp_path, monkeypatch):
    controlador, _eventos, turnos = _pronto(tmp_path, monkeypatch, espera=0.3)

    async def cenario():
        await controlador._comando("explica esse projeto", origem="voz")
        controlador._definir_gravando(True)  # você voltou a falar
        await asyncio.sleep(0.5)
        assert turnos == []  # o prazo não corre enquanto você fala
        controlador._definir_gravando(False)
        controlador._fim_voz = time.monotonic()
        controlador._receber_trecho("e o que falta fazer")
        await asyncio.sleep(0.1)
        assert turnos == []
        await asyncio.sleep(0.4)
        assert turnos == ["explica esse projeto e o que falta fazer"]

    _no_loop(controlador, cenario)


def test_cancela_descarta_o_rascunho_e_depois_esvazia_a_fila(tmp_path, monkeypatch):
    controlador, eventos, turnos = _pronto(tmp_path, monkeypatch)

    async def cenario():
        await controlador._comando("apaga a pasta de testes", origem="voz")
        controlador._receber_trecho("Cancela.")
        assert not controlador._rascunho and turnos == []
        controlador._pendentes = [("a1", "outro pedido")]
        await controlador._comando("esquece isso", origem="voz")
        assert controlador._pendentes == [] and turnos == []
        assert eventos[-1] == ev.Aviso("Fila esvaziada. O Claude continua só no pedido atual.")

    _no_loop(controlador, cenario)


def test_pedido_com_o_claude_ocupado_vai_para_a_fila_e_sai_dela(tmp_path, monkeypatch):
    controlador, eventos, turnos = _pronto(tmp_path, monkeypatch)
    controlador._pensando = True
    controlador._texto_turno = "pedido antigo"
    controlador._inicio_turno = time.monotonic() - 60  # faz tempo: não junta
    controlador._mandar_para_o_claude("roda os testes")
    controlador._mandar_para_o_claude("e me fala o resultado")
    assert [t for _i, t in controlador._pendentes] == ["roda os testes", "e me fala o resultado"]
    fila = [e for e in eventos if isinstance(e, ev.Fila)][-1]
    assert [t for _i, t in fila.itens] == ["roda os testes", "e me fala o resultado"]
    controlador._tirar_da_fila(fila.itens[0][0])
    assert [t for _i, t in controlador._pendentes] == ["e me fala o resultado"]
    assert turnos == []


def test_complemento_logo_depois_junta_com_o_pedido_e_refaz(tmp_path, monkeypatch):
    controlador, _eventos, _turnos = _pronto(tmp_path, monkeypatch)
    interrompeu = []

    async def interromper():
        interrompeu.append(True)

    monkeypatch.setattr(controlador._ponte, "interromper", interromper)
    monkeypatch.setattr(type(controlador._ponte), "ocupado", property(lambda _self: True))

    async def cenario():
        controlador._pensando = True
        controlador._texto_turno = "cria um script de backup"
        controlador._inicio_turno = time.monotonic()
        assert controlador._completa_pedido(time.monotonic())  # dá para completar sem o nome
        controlador._mandar_para_o_claude("que rode toda noite")
        await asyncio.sleep(0)
        assert interrompeu == [True] and controlador._pendentes == []
        assert controlador._refazer_com == "cria um script de backup que rode toda noite"
        controlador._mandar_para_o_claude("e mande um e-mail")  # entra junto, sem interromper de novo
        assert controlador._refazer_com.endswith("toda noite e mande um e-mail") and interrompeu == [True]

        controlador._refazer_com = ""
        controlador._turno_agiu = True  # o Claude já mexeu em algo: agora vai para a fila
        assert not controlador._completa_pedido(time.monotonic())
        controlador._mandar_para_o_claude("outra coisa")
        assert [t for _i, t in controlador._pendentes] == ["outra coisa"] and not controlador._refazer_com

    _no_loop(controlador, cenario)


def test_turno_interrompido_para_juntar_manda_o_pedido_inteiro(tmp_path, monkeypatch):
    controlador, _eventos, turnos = _pronto(tmp_path, monkeypatch)
    falou = []

    async def falar(texto, se_livre=False):
        falou.append(texto)

    async def perguntar(texto):
        controlador._refazer_com = "pedido A e o complemento B"  # o complemento chegou no meio
        yield EventoFim("<falar>resposta parcial</falar>", "sessao-1", 1.0, None, interrompido=True)

    monkeypatch.setattr(controlador, "_falar", falar)
    monkeypatch.setattr(controlador._ponte, "perguntar", perguntar)

    async def cenario():
        controlador._pendentes = [("x", "fica para depois")]
        await controlador._turno("pedido A")

    _no_loop(controlador, cenario)
    assert turnos == ["pedido A e o complemento B"]  # a fila espera o pedido inteiro terminar
    assert falou == [] and controlador._pendentes == [("x", "fica para depois")]


def test_pedido_novo_por_cima_da_resposta_corta_a_fala(tmp_path, monkeypatch):
    controlador, _eventos, _turnos = _pronto(tmp_path, monkeypatch)

    async def cenario():
        controlador._falando = True  # lendo a resposta anterior
        await controlador._comando("agora abre o readme", origem="voz")
        assert controlador._fala_cancelada

    _no_loop(controlador, cenario)


def test_palavra_de_parar_joga_fora_rascunho_e_fila(tmp_path, monkeypatch):
    controlador, _eventos, turnos = _pronto(tmp_path, monkeypatch)

    async def cenario():
        await controlador._comando("faz um relatório", origem="voz")
        controlador._pendentes = [("a", "outro")]
        await controlador._parar_tudo()
        assert not controlador._rascunho and not controlador._pendentes and turnos == []

    _no_loop(controlador, cenario)


# ---------------------------------------------------------------------- o nome só acorda
class _ReconhecedorFalso:
    tem_modelo_rapido = True
    principal_carregado = True

    def __init__(self):
        self.ouvidos: list[str] = []
        self.rapidos = 0

    def transcrever(self, audio, dica="", palavras=""):
        from assistente_local.reconhecimento import Transcricao

        return Transcricao(self.ouvidos.pop(0), 0.9, 1.0, 0.1)

    def transcrever_rapido(self, audio, dica="", nome=""):
        self.rapidos += 1
        return self.transcrever(audio)


def _fala():
    import numpy as np

    from assistente_local.audio.segmentador import Fala

    agora = time.monotonic()
    return Fala(np.zeros(16000, dtype=np.float32), agora - 1.5, agora, agora - 1.2)


def test_acordado_toda_fala_e_com_ele_sem_o_nome(tmp_path, monkeypatch):
    controlador, eventos, turnos = _pronto(tmp_path, monkeypatch)
    reconhecedor = _ReconhecedorFalso()
    controlador._reconhecedor = reconhecedor

    async def cenario():
        assert controlador._calcular_estado()[0] is ev.Estado.CONVERSA  # acordado: "Pode falar"
        reconhecedor.ouvidos = ["Lista os arquivos da pasta, câmbio."]
        await controlador._tratar_fala(_fala())
        assert turnos == ["Lista os arquivos da pasta"]
        assert reconhecedor.rapidos == 0  # nem procura o nome
        assert not any(isinstance(e, ev.FalaIgnorada) for e in eventos)

    _no_loop(controlador, cenario)


def test_acordado_fala_com_o_claude_ocupado_vai_para_a_fila(tmp_path, monkeypatch):
    controlador, _eventos, turnos = _pronto(tmp_path, monkeypatch)
    controlador._reconhecedor = reconhecedor = _ReconhecedorFalso()

    async def cenario():
        controlador._pensando = True
        controlador._texto_turno = "pedido antigo"
        controlador._inicio_turno = time.monotonic() - 60
        reconhecedor.ouvidos = ["e depois roda os testes, câmbio"]
        await controlador._tratar_fala(_fala())
        assert [t for _i, t in controlador._pendentes] == ["e depois roda os testes"] and turnos == []

    _no_loop(controlador, cenario)


def test_depois_da_palavra_de_parar_volta_a_precisar_do_nome(tmp_path, monkeypatch):
    controlador, eventos, turnos = _pronto(tmp_path, monkeypatch)
    controlador._reconhecedor = reconhecedor = _ReconhecedorFalso()

    async def entrar_em_espera():
        controlador._em_espera = True

    monkeypatch.setattr(controlador, "_entrar_em_espera", entrar_em_espera)

    async def cenario():
        reconhecedor.ouvidos = ["Jabuticabal."]
        await controlador._tratar_fala(_fala())
        assert controlador._em_espera and controlador._calcular_estado()[0] is ev.Estado.ESPERA
        reconhecedor.ouvidos = ["lista os arquivos, câmbio"]  # sem o nome: o modelo leve ignora
        await controlador._tratar_fala(_fala())
        assert turnos == [] and reconhecedor.rapidos == 1
        assert isinstance(eventos[-1], ev.FalaIgnorada)

    _no_loop(controlador, cenario)


def test_com_a_opcao_desligada_o_nome_vale_para_todo_pedido(tmp_path, monkeypatch):
    controlador, _eventos, turnos = _pronto(tmp_path, monkeypatch)
    controlador.cfg.ativacao.nome_so_para_acordar = False
    controlador._reconhecedor = reconhecedor = _ReconhecedorFalso()

    async def cenario():
        assert controlador._calcular_estado()[0] is ev.Estado.OUVINDO
        reconhecedor.ouvidos = ["lista os arquivos, câmbio"]
        await controlador._tratar_fala(_fala())
        assert turnos == []

    _no_loop(controlador, cenario)
