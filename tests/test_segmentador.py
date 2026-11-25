import numpy as np

from assistente_local.audio.segmentador import JANELA, TAXA, Segmentador


def alimentar(segmentador, probabilidades):
    falas = []
    duracao = JANELA / TAXA
    for i, prob in enumerate(probabilidades):
        fala = segmentador.processar(np.full(JANELA, i, np.float32), prob, (i + 1) * duracao)
        if fala:
            falas.append(fala)
    return falas


def test_uma_fala_completa():
    seg = Segmentador(silencio_fim_ms=320, fala_minima_ms=200, pre_fala_ms=96)
    falas = alimentar(seg, [0.0] * 10 + [0.9] * 20 + [0.0] * 15)
    assert len(falas) == 1
    assert 0.6 < falas[0].duracao < 1.3


def test_ruido_curto_nao_vira_fala():
    seg = Segmentador(silencio_fim_ms=320, fala_minima_ms=300)
    assert alimentar(seg, [0.0] * 5 + [0.9] * 4 + [0.0] * 20) == []


def test_cliques_soltos_nao_comecam_gravacao():
    assert alimentar(Segmentador(), [0.9, 0.0] * 10 + [0.0] * 30) == []


def test_hesitacao_nao_corta_a_fala():
    seg = Segmentador(silencio_fim_ms=320, fala_minima_ms=200)
    assert len(alimentar(seg, [0.9] * 15 + [0.4] * 12 + [0.9] * 15 + [0.0] * 15)) == 1


def test_resposta_curta_so_passa_quando_o_app_espera_uma():
    sim = [0.0] * 5 + [0.9] * 6 + [0.0] * 30  # ~190 ms de voz, como um "sim" rápido
    normal = Segmentador(fala_minima_ms=300)
    assert alimentar(normal, sim) == []  # fora de uma pergunta: ruído
    esperando = Segmentador(fala_minima_ms=300)
    esperando.curtas_ate = float("inf")  # o app fez uma pergunta
    falas = alimentar(esperando, sim)
    assert len(falas) == 1 and falas[0].curta
    duracao = JANELA / TAXA
    assert abs(falas[0].inicio_voz - 5 * duracao) < 0.04  # o começo da voz, não o trecho guardado antes
    assert falas[0].inicio < falas[0].inicio_voz
    assert alimentar(esperando, [0.0] * 5 + [0.9] * 2 + [0.0] * 30) == []  # estalo continua sendo ruído


def test_fala_normal_nao_e_curta():
    seg = Segmentador(silencio_fim_ms=320, fala_minima_ms=300)
    falas = alimentar(seg, [0.0] * 5 + [0.9] * 20 + [0.0] * 15)
    assert len(falas) == 1 and not falas[0].curta


def test_fala_longa_e_dividida_no_limite():
    seg = Segmentador(fala_maxima_s=1.0, silencio_fim_ms=800)
    assert len(alimentar(seg, [0.9] * 100)) >= 2
