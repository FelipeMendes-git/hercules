from assistente_local import config, inicializacao
from assistente_local.audio.ouvinte import Ouvinte


class _StreamFalso:
    device = 0

    def abort(self):
        pass

    def close(self):
        pass


def test_percebe_microfone_parado_e_avisa_quando_volta(monkeypatch):
    avisos = []
    ouvinte = Ouvinte(config.Audio(), lambda fala: None, None, lambda ok, mensagem: avisos.append(ok))
    monkeypatch.setattr(ouvinte, "_abrir", lambda dispositivo, taxa: setattr(ouvinte, "_stream", _StreamFalso()))

    assert ouvinte.tentar_abrir()
    assert ouvinte.microfone_ok is True
    assert avisos == []

    ouvinte._ultimo_audio -= 10  # nenhum áudio há 10 s
    ouvinte._verificar_microfone()
    assert ouvinte.microfone_ok is False
    assert avisos == [False]

    assert ouvinte.tentar_abrir()
    assert avisos == [False, True]


def test_microfone_que_nao_abre_nao_derruba_o_app(monkeypatch):
    avisos = []
    ouvinte = Ouvinte(config.Audio(), lambda fala: None, None, lambda ok, mensagem: avisos.append(ok))

    def falhar(dispositivo, taxa):
        raise OSError("nenhum microfone")

    monkeypatch.setattr(ouvinte, "_abrir", falhar)
    monkeypatch.setattr("sounddevice.query_devices", lambda *a, **k: {"default_samplerate": 48000})
    assert ouvinte.tentar_abrir() is False
    assert ouvinte.microfone_ok is False
    assert avisos == [False]


def test_comando_de_inicializacao_abre_escondido():
    assert inicializacao.comando().endswith("--bandeja")
