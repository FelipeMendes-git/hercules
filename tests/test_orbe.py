import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from assistente_local import eventos as ev  # noqa: E402
from assistente_local.interface.orbe import CORES_DA_BOLHA, aparencia  # noqa: E402
from assistente_local.interface.tema import COR_TRABALHANDO  # noqa: E402

Estado = ev.Estado


def test_toda_cor_de_estado_existe():
    assert set(CORES_DA_BOLHA) == set(Estado)


def test_falando_ondula_com_o_som():
    calada, alta = aparencia(Estado.FALANDO, 1.0, nivel=0.0), aparencia(Estado.FALANDO, 1.0, nivel=1.0)
    assert alta.amplitude > calada.amplitude * 3
    assert alta.forca == 1.0 and calada.forca == 0.0
    assert alta.respiro == 0.0  # quem mexe é o som


def test_pensando_e_trabalhando():
    pensando = aparencia(Estado.PENSANDO, 1.0)
    trabalhando = aparencia(Estado.PENSANDO, 1.0, trabalhando=True)
    assert (pensando.giro, pensando.pedacos) == (0.45, 1)
    assert (trabalhando.pedacos, trabalhando.cor) == (3, COR_TRABALHANDO)
    assert trabalhando.velocidade > pensando.velocidade
    assert aparencia(Estado.FALANDO, 1.0, trabalhando=True).cor != COR_TRABALHANDO  # só vale pensando


def test_cochilando_apagada_e_parada():
    espera = aparencia(Estado.ESPERA, 1.0)
    assert espera.apagada < 1.0 and espera.giro == 0 and espera.forca < 0.1


def test_permissao_pisca_e_erro_treme():
    assert aparencia(Estado.APROVACAO, 0.0).forca != aparencia(Estado.APROVACAO, 0.22).forca
    assert aparencia(Estado.ERRO, 0.05).tremor != 0.0
    assert aparencia(Estado.ERRO, 1.0).tremor == 0.0  # treme e para, de tempos em tempos


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_bolinha_sempre_em_primeiro_plano_e_opcional(app):
    from assistente_local.interface.janela_compacta import JanelaCompacta

    bolinha = JanelaCompacta(QMenu(), lambda: None, "Hércules", no_topo=True)
    assert bolinha.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    bolinha.definir_no_topo(False)
    assert not bolinha.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert not bolinha.no_topo
    bolinha.definir_no_topo(True)
    assert bolinha.windowFlags() & Qt.WindowType.WindowStaysOnTopHint

    bolinha.tratar_evento(ev.InfoClaude("Opus 5.5", "alto", "automático", True))
    bolinha.tratar_evento(ev.EstadoMudou(Estado.PENSANDO))
    bolinha.tratar_evento(ev.AcaoClaude("Editando notas.txt", "Edit"))
    dica = bolinha.orbe.toolTip()
    assert "Pensando" in dica and "Editando notas.txt" in dica and "Opus 5.5 · esforço alto" in dica
    assert bolinha.orbe.trabalhando
