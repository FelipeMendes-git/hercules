import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor  # noqa: E402

from assistente_local.eventos import Estado  # noqa: E402
from assistente_local.interface.fundo import cores_do_fundo  # noqa: E402
from assistente_local.interface.tema import COR_TRABALHANDO, ESTADOS  # noqa: E402


def _matiz(cor: str) -> float:
    return QColor(cor).getHsvF()[0]


def test_fundo_segue_a_cor_da_bolha_em_tom_pastel():
    falando = cores_do_fundo(Estado.FALANDO)
    assert len(falando) == 3 and len(set(falando)) == 3
    assert abs(_matiz(falando[0]) - _matiz(ESTADOS[Estado.FALANDO][1])) < 0.02  # mesma cor, mais clara
    assert QColor(falando[0]).lightness() > QColor(ESTADOS[Estado.FALANDO][1]).lightness()


def test_trabalhando_e_cochilando():
    trabalhando = cores_do_fundo(Estado.PENSANDO, trabalhando=True)
    assert abs(_matiz(trabalhando[0]) - _matiz(COR_TRABALHANDO)) < 0.02
    assert cores_do_fundo(Estado.FALANDO, trabalhando=True) == cores_do_fundo(Estado.FALANDO)  # só vale pensando
    cochilando = QColor(cores_do_fundo(Estado.ESPERA)[0])
    assert cochilando.saturation() < QColor(cores_do_fundo(Estado.PENSANDO)[0]).saturation()  # mais apagado
