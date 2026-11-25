from assistente_local import config
from assistente_local import eventos as ev
from assistente_local.controlador import NOME_AREA_LIVRE, Controlador
from assistente_local.estado import Estado
from assistente_local.historico import Historico


def _controlador(tmp_path, monkeypatch, cfg=None, estado=None, emitir=None):
    monkeypatch.setenv("ASSISTENTE_LOCAL_DADOS", str(tmp_path / "dados"))
    return Controlador(
        cfg or config.Config(), emitir or (lambda evento: None), simular_microfone=True, sem_som=True,
        estado_salvo=estado or Estado(tmp_path / "estado.json"), historico=Historico(tmp_path / "conversas"),
    )


def test_abre_sem_projeto_e_so_entra_quando_pedir(tmp_path, monkeypatch):
    (tmp_path / "dev" / "site").mkdir(parents=True)
    cfg = config.Config()
    cfg.projetos.pastas_raiz = [str(tmp_path / "dev")]
    estado = Estado(tmp_path / "estado.json")
    estado.projeto_atual = str(tmp_path / "dev" / "site")  # o último projeto usado
    controlador = _controlador(tmp_path, monkeypatch, cfg, estado)
    assert controlador._escolher_projeto_inicial().nome == NOME_AREA_LIVRE
    cfg.projetos.comecar_sem_projeto = False  # o jeito antigo: abre no último projeto
    assert controlador._escolher_projeto_inicial().nome == "site"


def test_cochilando_nao_mostra_que_esta_ouvindo(tmp_path, monkeypatch):
    eventos = []
    controlador = _controlador(tmp_path, monkeypatch, emitir=eventos.append)
    controlador._carregado = True
    controlador._em_espera = True
    controlador._gravando = True  # alguém falando perto, sem chamar o nome
    assert controlador._calcular_estado()[0] is ev.Estado.ESPERA
    controlador._ao_nivel(0.6, True)
    assert eventos[-1] == ev.NivelMicrofone(0.6, False)  # a barrinha também não fica "gravando"

    controlador._em_espera = False  # acordado (depois de chamar "Hércules")
    assert controlador._calcular_estado()[0] is ev.Estado.GRAVANDO


def test_palavra_de_parar_faz_ele_voltar_a_dormir(tmp_path, monkeypatch):
    import asyncio
    import time

    controlador = _controlador(tmp_path, monkeypatch)
    controlador._carregado = True

    async def cenario():
        controlador._loop = asyncio.get_running_loop()
        controlador._em_espera = False  # acordado, na janela de conversa ("Pode falar")
        controlador._janela_ate = time.monotonic() + 12
        assert controlador._calcular_estado()[0] is ev.Estado.CONVERSA
        await controlador._comando("Jabuticabal.", origem="voz")
        assert controlador._em_espera and controlador._janela_ate == 0.0
        assert controlador._calcular_estado()[0] is ev.Estado.ESPERA
        controlador._abrir_janela()  # o fim de uma resposta interrompida não reabre a conversa
        assert controlador._calcular_estado()[0] is ev.Estado.ESPERA

    asyncio.run(cenario())


def test_mudar_esforco_por_voz_salva_e_reabre_o_claude(tmp_path, monkeypatch):
    import asyncio

    eventos = []
    controlador = _controlador(tmp_path, monkeypatch, emitir=eventos.append)
    controlador._em_espera = True  # cochilando: não reabre o Claude Code agora
    fechou = []

    async def descansar():
        fechou.append(True)

    monkeypatch.setattr(controlador._ponte, "descansar", descansar)
    antes = controlador.cfg
    asyncio.run(controlador._mudar_claude(esforco="high"))

    assert controlador.cfg.claude.esforco == "high" and antes.claude.esforco == "medium"  # config nova, não a mesma
    assert controlador._ponte.cfg.esforco == "high" and fechou == [True]  # reabre com o esforço novo
    assert config.carregar().claude.esforco == "high"  # ficou salvo para a próxima vez
    info = next(e for e in eventos if isinstance(e, ev.InfoClaude))
    assert info.esforco == "alto" and info.modelo == "Opus 5.5"
    assert any(isinstance(e, ev.ConfigAlterada) and e.cfg is controlador.cfg for e in eventos)


def test_escolher_modelo_na_janela_troca_e_ignora_o_que_ja_esta(tmp_path, monkeypatch):
    import asyncio

    eventos = []
    controlador = _controlador(tmp_path, monkeypatch, emitir=eventos.append)
    controlador._em_espera = True
    fechou = []

    async def descansar():
        fechou.append(True)

    monkeypatch.setattr(controlador._ponte, "descansar", descansar)
    asyncio.run(controlador._mudar_claude_pela_janela({"modelo": "claude-opus-5-5"}))  # já é o atual
    assert fechou == [] and not eventos

    controlador._pensando = True  # no meio de uma resposta: avisa que vale para a próxima
    asyncio.run(controlador._mudar_claude_pela_janela({"modelo": "claude-sonnet-5-5", "esforco": "medium"}))
    assert controlador.cfg.claude.modelo == "claude-sonnet-5-5" and fechou == [True]
    assert config.carregar().claude.modelo == "claude-sonnet-5-5"
    aviso = next(e for e in eventos if isinstance(e, ev.Aviso))
    assert "Sonnet 5.5" in aviso.mensagem and "próxima resposta" in aviso.mensagem
