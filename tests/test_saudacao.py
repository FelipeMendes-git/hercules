from datetime import datetime

import numpy as np
import pytest

from assistente_local import config, saudacao
from assistente_local.ponte_claude import instrucoes_de_voz
from assistente_local.saudacao import (
    ESTILOS,
    TAXA,
    Saudacoes,
    mixar,
    ocasiao,
    periodo,
    preencher,
    vinheta,
    voz_confere,
)


class _VozFalsa:
    taxa = 24000

    def sintetizar(self, texto):
        return np.full(int(0.4 * self.taxa), 0.3, np.float32)  # 0,4 s de "voz"


@pytest.mark.parametrize("estilo", [e for e in ESTILOS if e != "nenhuma"])
def test_vinheta_sem_estouro_e_com_fim_suave(estilo):
    musica = vinheta(estilo)
    assert 6 * TAXA <= len(musica) <= 10 * TAXA
    assert not np.isnan(musica).any()
    assert float(np.max(np.abs(musica))) <= 0.91
    assert abs(float(musica[-1])) < 1e-3  # termina em silêncio, sem estalo
    assert float(np.sqrt(np.mean(musica[: 3 * TAXA] ** 2))) > 0.05  # tem música de verdade no começo


def test_vinheta_de_rock_e_pesada():
    rock = vinheta("rock")
    espectro = np.abs(np.fft.rfft(rock)) ** 2
    frequencias = np.fft.rfftfreq(len(rock), 1 / TAXA)
    graves = espectro[frequencias < 250].sum() / espectro.sum()
    assert graves > 0.35  # bumbo, baixo e guitarra distorcida
    assert vinheta("desconhecido") is rock  # estilo inválido cai no rock


def test_mixagem_poe_a_voz_por_cima_e_termina_logo():
    voz = np.full(TAXA, 0.5, np.float32)  # 1 s
    saida = mixar(voz, vinheta(), volume_musica=0.35, atraso_voz_s=0.8, cauda_s=1.0)
    assert len(saida) == int(0.8 * TAXA) + TAXA + TAXA  # entrada + voz + cauda
    assert float(np.max(np.abs(saida))) <= 0.98
    assert abs(float(saida[-1])) < 1e-3
    meio_da_voz = saida[int(1.2 * TAXA) : int(1.4 * TAXA)]
    assert float(np.mean(meio_da_voz)) > 0.3  # a voz está lá, acima da música


def test_mixagem_abaixa_a_musica_durante_a_voz():
    musica = np.full(6 * TAXA, 0.5, np.float32)
    silencio = np.zeros(2 * TAXA, np.float32)  # "voz" muda, para medir só a música
    saida = mixar(silencio, musica, volume_musica=1.0, atraso_voz_s=1.0, cauda_s=1.0, abaixar=0.35)
    assert float(saida[int(0.5 * TAXA)]) == pytest.approx(0.5)  # antes da voz: volume cheio
    assert float(saida[int(2.0 * TAXA)]) == pytest.approx(0.5 * 0.35)  # durante a voz: abaixada


QUINTA_A_TARDE = datetime(2026, 1, 1, 15)  # sem ocasião especial
SEXTA_A_NOITE = datetime(2026, 1, 2, 20)


def test_grava_uma_vez_e_monta_na_hora(tmp_path):
    cfg = config.Config()
    saudacoes = Saudacoes(cfg.saudacao, cfg.voz, pasta=tmp_path)
    assert saudacoes.montar(com_pedido=False) is None  # ainda não gravou
    faltando = saudacoes.faltando()
    assert "Boa tarde, mestre." in faltando and "Certamente." in faltando
    assert "Boa noite, mestre. Enfim, sexta-feira." in faltando
    assert saudacoes.gravar(_VozFalsa()) == len(faltando)
    assert saudacoes.faltando() == []

    audio, texto = saudacoes.montar(com_pedido=True, agora=QUINTA_A_TARDE)
    aberturas = [preencher(a, "Boa tarde", "mestre") for a in cfg.saudacao.aberturas]
    assert any(texto.startswith(a + " ") for a in aberturas)
    assert texto.endswith(tuple(cfg.saudacao.frases_pedido))
    assert len(audio) > 0


def test_preencher_frases():
    assert preencher("{periodo}, {tratamento}!", "Boa noite", "mestre") == "Boa noite, mestre!"
    assert preencher("{tratamento}! Na escuta.", "Bom dia", "mestre") == "Mestre! Na escuta."
    assert preencher("{periodo}, {tratamento}!", "Bom dia", "") == "Bom dia!"
    assert preencher("Olá, {tratamento}! {outra} chave", "Bom dia", "chefe") == "Olá, chefe! {outra} chave"


@pytest.mark.parametrize(
    ("agora", "esperada"),
    [
        (datetime(2026, 1, 1, 3), "madrugada"),  # quinta, 3h
        (datetime(2026, 1, 5, 9), "segunda"),
        (datetime(2026, 1, 5, 15), None),  # segunda à tarde
        (SEXTA_A_NOITE, "sexta"),
        (datetime(2026, 1, 3, 10), "fim_de_semana"),  # sábado
        (datetime(2026, 1, 4, 2), "madrugada"),  # domingo, 2h
        (QUINTA_A_TARDE, None),
    ],
)
def test_ocasioes_especiais(agora, esperada):
    assert ocasiao(agora) == esperada


def test_sorteio_nao_repete_as_ultimas_nem_depois_de_reabrir(tmp_path):
    cfg = config.Config()
    Saudacoes(cfg.saudacao, cfg.voz, pasta=tmp_path).gravar(_VozFalsa())
    falas = []
    for rodada in range(30):  # um objeto novo a cada vez, como se o app tivesse reiniciado
        _, texto = Saudacoes(cfg.saudacao, cfg.voz, pasta=tmp_path).montar(com_pedido=True, agora=QUINTA_A_TARDE)
        falas.append(texto)
    preenchidas = [preencher(a, "Boa tarde", "mestre") for a in cfg.saudacao.aberturas]
    aberturas = [max((a for a in preenchidas if f.startswith(a + " ")), key=len) for f in falas]
    pedidos = [max((p for p in cfg.saudacao.frases_pedido if f.endswith(" " + p)), key=len) for f in falas]
    for sequencia, lista in ((aberturas, cfg.saudacao.aberturas), (pedidos, cfg.saudacao.frases_pedido)):
        janela = len(lista) // 2 + 1
        for i in range(len(sequencia) - janela + 1):
            assert len(set(sequencia[i : i + janela])) == janela  # nada se repete dentro da janela


def test_abertura_da_ocasiao_especial(tmp_path, monkeypatch):
    cfg = config.Config()
    saudacoes = Saudacoes(cfg.saudacao, cfg.voz, pasta=tmp_path)
    saudacoes.gravar(_VozFalsa())
    sexta = [preencher(f, "Boa noite", "mestre") for f in cfg.saudacao.sexta]
    monkeypatch.setattr(saudacao, "CHANCE_OCASIAO", 1.0)
    _, texto = saudacoes.montar(com_pedido=False, agora=SEXTA_A_NOITE)
    assert texto.startswith(tuple(sexta))
    monkeypatch.setattr(saudacao, "CHANCE_OCASIAO", 0.0)
    _, texto = saudacoes.montar(com_pedido=False, agora=SEXTA_A_NOITE)
    assert not texto.startswith(tuple(sexta))
    _, texto = saudacoes.montar(com_pedido=False, agora=QUINTA_A_TARDE, ocasiao_forcada="sexta")  # botão de ouvir
    assert texto.startswith(tuple(preencher(f, "Boa tarde", "mestre") for f in cfg.saudacao.sexta))


def test_usa_so_o_que_ja_foi_gravado_ou_grava_na_hora(tmp_path):
    cfg = config.Config()
    saudacoes = Saudacoes(cfg.saudacao, cfg.voz, pasta=tmp_path)
    saudacoes.gravar(_VozFalsa(), ["Olá, mestre.", "Certamente."])  # gravação ainda no começo
    for _ in range(5):
        _, texto = saudacoes.montar(com_pedido=True, agora=QUINTA_A_TARDE)
        assert texto == "Olá, mestre. Certamente."
    outra = Saudacoes(cfg.saudacao, cfg.voz, pasta=tmp_path / "vazia")
    montado = outra.montar(com_pedido=False, agora=QUINTA_A_TARDE, criar_voz=_VozFalsa)  # grava só as sorteadas
    assert montado is not None and len(list((tmp_path / "vazia").glob("*.wav"))) == 2


def test_estilo_da_vinheta_e_musica_que_falha(tmp_path):
    cfg = config.Config()
    Saudacoes(cfg.saudacao, cfg.voz, pasta=tmp_path).gravar(_VozFalsa())
    agora = datetime(2026, 1, 1, 15)
    so_voz, _ = Saudacoes(cfg.saudacao, cfg.voz, pasta=tmp_path).montar(com_pedido=True, agora=agora)
    cfg.saudacao.estilo = "rock"
    rock, _ = Saudacoes(cfg.saudacao, cfg.voz, pasta=tmp_path).montar(com_pedido=True, agora=agora)
    cfg.saudacao.estilo = "suave"
    suave, _ = Saudacoes(cfg.saudacao, cfg.voz, pasta=tmp_path).montar(com_pedido=True, agora=agora)
    assert not np.allclose(rock[: TAXA // 2], suave[: TAXA // 2])  # músicas diferentes antes da voz
    cfg.saudacao.musica = str(tmp_path / "nao-existe.mp3")
    reserva, _ = Saudacoes(cfg.saudacao, cfg.voz, pasta=tmp_path).montar(com_pedido=True, agora=agora)
    assert np.allclose(reserva[: TAXA // 2], suave[: TAXA // 2])  # arquivo ruim: volta para a vinheta
    assert len(so_voz) < len(rock)  # sem música (o padrão): só a voz, sem a introdução nem a cauda


def test_trocar_a_voz_pede_nova_gravacao_e_limpa_as_antigas(tmp_path):
    cfg = config.Config()
    antigas = Saudacoes(cfg.saudacao, cfg.voz, pasta=tmp_path)
    antigas.gravar(_VozFalsa())
    (tmp_path / "exemplo.wav").write_bytes(b"")  # arquivos que não são do app ficam
    cfg.voz.voz_sapi = "Maria"  # só a reserva do Windows: as gravações do Kokoro continuam valendo
    assert Saudacoes(cfg.saudacao, cfg.voz, pasta=tmp_path).faltando() == []
    cfg.voz.voz = "pm_santa"
    novas = Saudacoes(cfg.saudacao, cfg.voz, pasta=tmp_path)
    assert novas.faltando()
    novas.gravar(_VozFalsa())
    assert novas.limpar() == len(antigas.textos())
    assert novas.faltando() == [] and (tmp_path / "exemplo.wav").exists()
    assert len(list(tmp_path.glob("*.wav"))) == len(novas.textos()) + 1


class _Motor:
    taxa = 24000
    descricao = "teste"

    def __init__(self, motor, voz=""):
        self.motor, self.voz = motor, voz

    def sintetizar(self, texto):
        return np.full(int(0.4 * self.taxa), 0.3, np.float32)


def test_nao_grava_a_saudacao_com_a_voz_de_reserva(tmp_path):
    cfg = config.Config()  # Kokoro, pm_alex
    saudacoes = Saudacoes(cfg.saudacao, cfg.voz, pasta=tmp_path)
    assert not voz_confere(_Motor("sapi"), cfg.voz)  # Kokoro falhou e veio a voz do Windows
    assert not voz_confere(_Motor("kokoro", "pf_dora"), cfg.voz)  # outra voz do Kokoro
    assert voz_confere(_Motor("kokoro", "pm_alex"), cfg.voz)
    assert saudacoes.gravar(_Motor("sapi")) == 0
    assert list(tmp_path.glob("*.wav")) == []
    assert saudacoes.gravar(_Motor("kokoro", "pm_alex")) == len(saudacoes.textos())
    cfg.voz.motor = "sapi"  # quem escolheu a voz do Windows grava com ela
    assert voz_confere(_Motor("sapi"), cfg.voz)


def test_claude_nao_usa_o_tratamento_nas_respostas():
    texto = instrucoes_de_voz()
    assert "Chame-o" not in texto  # o tratamento fica só na saudação
    # proibido de forma explícita: conversas antigas, retomadas, já tinham o "mestre" no histórico
    assert "Não chame o usuário por apelidos ou tratamentos" in texto and "mesmo que você já tenha usado" in texto
    assert "{" not in texto and "# Controle do app" in texto


def test_respostas_resumidas_so_no_app():
    resumidas = instrucoes_de_voz(resumir=True)
    normais = instrucoes_de_voz(resumir=False)
    assert "responda de forma resumida" in resumidas and "responda de forma resumida" not in normais
    assert "escreva normalmente" in normais
    for texto in (resumidas, normais):
        assert '"Hércules"' in texto  # o nome do app, que é como ele chama o Claude
        assert "Não salve nada em memória, CLAUDE.md ou configurações por conta própria" in texto
        assert "Quando ele pedir, mexa no que for preciso" in texto
        assert "não as grave em lugar nenhum, a não ser que ele peça" in texto  # não vaza para o uso normal
        assert "{" not in texto
