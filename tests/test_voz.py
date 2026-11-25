from assistente_local import config, voz


def test_reserva_do_windows_tem_o_mesmo_genero(monkeypatch):
    class KokoroQuebrado:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("modelo corrompido")

    monkeypatch.setattr(voz.modelos, "kokoro_pronto", lambda: True)
    monkeypatch.setattr(voz, "VozKokoro", KokoroQuebrado)
    motor = voz.criar(config.Config().voz)  # padrão: Alex (masculina)
    assert isinstance(motor, voz.VozWindows) and motor.motor == "sapi"
    assert motor.nome_voz == "Daniel"
    for kokoro, windows in voz.RESERVA_WINDOWS.items():
        assert kokoro in voz.VOZES_KOKORO
        assert kokoro.startswith("pm_") == (windows == "Daniel")
