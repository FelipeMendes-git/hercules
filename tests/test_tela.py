import asyncio
import base64
import struct
import sys
import zlib

import numpy as np
import pytest

from assistente_local import tela
from assistente_local.ponte_claude import ver_a_tela


def test_png_codificado_tem_os_pixels_certos():
    rgb = np.array([[[255, 0, 0], [0, 255, 0]], [[0, 0, 255], [10, 20, 30]]], dtype=np.uint8)
    png = tela.codificar_png(rgb)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    largura, altura = struct.unpack(">II", png[16:24])
    assert (largura, altura) == (2, 2)
    inicio = png.index(b"IDAT") + 4
    tamanho = struct.unpack(">I", png[inicio - 8 : inicio - 4])[0]
    linhas = np.frombuffer(zlib.decompress(png[inicio : inicio + tamanho]), dtype=np.uint8).reshape(2, 7)
    assert (linhas[:, 0] == 0).all() and (linhas[:, 1:].reshape(2, 2, 3) == rgb).all()


def test_reduz_so_o_que_passa_do_limite():
    assert tela.tamanho_reduzido(1920, 1080) == (1568, 882)
    assert tela.tamanho_reduzido(800, 600) == (800, 600)
    assert tela.tamanho_reduzido(1080, 3840)[1] == 1568


def test_ver_a_tela_devolve_imagem_ou_erro():
    def capturar_falso(alvo, monitor):
        assert (alvo, monitor) == ("janela", 1)
        return tela.Captura(b"PNGFALSO", 10, 10, "janela ativa: Chrome")

    resposta = asyncio.run(ver_a_tela("janela", 1, capturar_falso))
    texto, imagem = resposta["content"]
    assert "Chrome" in texto["text"] and "is_error" not in resposta
    assert imagem["mimeType"] == "image/png" and base64.b64decode(imagem["data"]) == b"PNGFALSO"

    def capturar_quebrado(alvo, monitor):
        raise tela.ErroCaptura("O monitor 3 não existe")

    erro = asyncio.run(ver_a_tela("monitor", 3, capturar_quebrado))
    assert erro["is_error"] is True and "monitor 3" in erro["content"][0]["text"]


@pytest.mark.skipif(sys.platform != "win32", reason="captura só no Windows")
def test_captura_de_verdade_no_windows():
    captura = tela.capturar("monitor", 1)
    assert captura.png.startswith(b"\x89PNG") and max(captura.largura, captura.altura) <= tela.LADO_MAXIMO
    with pytest.raises(tela.ErroCaptura):
        tela.capturar("monitor", 99)
