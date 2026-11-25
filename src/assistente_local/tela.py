"""Captura da tela do usuário, para o Claude ver o que está nela (ferramenta ``ver_tela``).

Usa só a GDI do Windows (por ctypes) e codifica o PNG na mão com zlib e numpy: nada de
dependência nova. A imagem é reduzida para no máximo ``LADO_MAXIMO`` pixels no lado maior,
que é o que o Claude enxerga de fato (imagens maiores ele mesmo reduz, gastando mais).
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import struct
import sys
import time
import zlib
from ctypes import wintypes
from dataclasses import dataclass

import numpy as np

LADO_MAXIMO = 1568


@dataclass(frozen=True)
class Retangulo:
    x: int
    y: int
    largura: int
    altura: int


@dataclass
class Captura:
    png: bytes
    largura: int
    altura: int
    descricao: str


class ErroCaptura(RuntimeError):
    pass


# ---------------------------------------------------------------------- PNG
def codificar_png(rgb: np.ndarray) -> bytes:
    """Codifica uma matriz (altura, largura, 3) uint8 como PNG."""
    altura, largura, _ = rgb.shape
    linhas = np.empty((altura, largura * 3 + 1), dtype=np.uint8)
    linhas[:, 0] = 0  # filtro "nenhum" em cada linha
    linhas[:, 1:] = rgb.reshape(altura, largura * 3)

    def bloco(tipo: bytes, dados: bytes) -> bytes:
        return struct.pack(">I", len(dados)) + tipo + dados + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF)

    cabecalho = struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + bloco(b"IHDR", cabecalho)
        + bloco(b"IDAT", zlib.compress(linhas.tobytes(), 6))
        + bloco(b"IEND", b"")
    )


def tamanho_reduzido(largura: int, altura: int, lado_maximo: int = LADO_MAXIMO) -> tuple[int, int]:
    escala = min(1.0, lado_maximo / max(largura, altura, 1))
    return max(1, round(largura * escala)), max(1, round(altura * escala))


# ---------------------------------------------------------------------- Windows
if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    _dwmapi = ctypes.WinDLL("dwmapi")

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    _MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
    )
    _user32.GetDC.restype = wintypes.HDC
    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, _MONITORENUMPROC, wintypes.LPARAM]
    _user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
    _gdi32.CreateCompatibleDC.restype = wintypes.HDC
    _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    _gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    _gdi32.SelectObject.restype = wintypes.HGDIOBJ
    _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi32.SetStretchBltMode.argtypes = [wintypes.HDC, ctypes.c_int]
    _gdi32.SetBrushOrgEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    _gdi32.StretchBlt.argtypes = [wintypes.HDC] + [ctypes.c_int] * 4 + [wintypes.HDC] + [ctypes.c_int] * 4 + [
        wintypes.DWORD
    ]
    _gdi32.GetDIBits.argtypes = [
        wintypes.HDC,
        wintypes.HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.POINTER(_BITMAPINFOHEADER),
        wintypes.UINT,
    ]
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]

    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.GetWindow.restype = wintypes.HWND
    _user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    _dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

    _GW_HWNDNEXT = 2
    _DWMWA_CLOAKED = 14
    _WDA_EXCLUDEFROMCAPTURE = 0x11
    _SRCCOPY = 0x00CC0020
    _CAPTUREBLT = 0x40000000
    _HALFTONE = 4
    _MONITORINFOF_PRIMARY = 1
    _DWMWA_EXTENDED_FRAME_BOUNDS = 9


def monitores() -> list[Retangulo]:
    """Os monitores, com o principal primeiro e os outros da esquerda para a direita."""
    achados: list[tuple[bool, Retangulo]] = []

    def anotar(monitor, _hdc, _rect, _dados):
        info = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
        if _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            r = info.rcMonitor
            achados.append((bool(info.dwFlags & _MONITORINFOF_PRIMARY), Retangulo(r.left, r.top, r.right - r.left, r.bottom - r.top)))
        return True

    _user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(anotar), 0)
    achados.sort(key=lambda item: (not item[0], item[1].x, item[1].y))
    return [r for _, r in achados]


def _do_app(hwnd) -> bool:
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == os.getpid()


def _janela_de_verdade(hwnd) -> bool:
    """Visível, não minimizada e não escondida pelo Windows (como os apps de fundo da loja)."""
    if not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd):
        return False
    escondida = wintypes.DWORD()
    _dwmapi.DwmGetWindowAttribute(hwnd, _DWMWA_CLOAKED, ctypes.byref(escondida), ctypes.sizeof(escondida))
    return not escondida.value


def _janelas_do_app() -> list:
    achadas = []

    def anotar(hwnd, _dados):
        if _user32.IsWindowVisible(hwnd) and _do_app(hwnd):
            achadas.append(hwnd)
        return True

    _user32.EnumWindows(_WNDENUMPROC(anotar), 0)
    return achadas


@contextlib.contextmanager
def _sem_as_janelas_do_app():
    """Some com as janelas do Hércules só no print (na tela continuam). Fora do print nada muda, então
    gravações de tela do app continuam mostrando ele normalmente."""
    trocadas = []
    for hwnd in _janelas_do_app():
        antes = wintypes.DWORD()
        if not _user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(antes)):
            continue
        if _user32.SetWindowDisplayAffinity(hwnd, _WDA_EXCLUDEFROMCAPTURE):
            trocadas.append((hwnd, antes.value))
    if trocadas:
        time.sleep(0.15)  # o Windows aplica no próximo quadro da tela
    try:
        yield
    finally:
        for hwnd, antes in trocadas:
            _user32.SetWindowDisplayAffinity(hwnd, antes)


def _janela_ativa() -> tuple[Retangulo, str]:
    hwnd = _user32.GetForegroundWindow()
    # Quem está falando com o Hércules costuma deixar ele na frente: vale a janela logo atrás dele.
    while hwnd and (_do_app(hwnd) or not _janela_de_verdade(hwnd)):
        hwnd = _user32.GetWindow(hwnd, _GW_HWNDNEXT)
    if not hwnd:
        raise ErroCaptura("Não há janela ativa.")
    r = wintypes.RECT()
    if _dwmapi.DwmGetWindowAttribute(hwnd, _DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        _user32.GetWindowRect(hwnd, ctypes.byref(r))  # sem a borda invisível só pelo DWM
    tamanho = _user32.GetWindowTextLengthW(hwnd)
    titulo = ctypes.create_unicode_buffer(tamanho + 1)
    _user32.GetWindowTextW(hwnd, titulo, tamanho + 1)
    return Retangulo(r.left, r.top, r.right - r.left, r.bottom - r.top), titulo.value


def _copiar(area: Retangulo, largura: int, altura: int) -> np.ndarray:
    """Copia a área da tela, já reduzida para largura x altura, como RGB."""
    tela = _user32.GetDC(None)
    memoria = _gdi32.CreateCompatibleDC(tela)
    bitmap = _gdi32.CreateCompatibleBitmap(tela, largura, altura)
    if not tela or not memoria or not bitmap:
        raise ErroCaptura("O Windows não deixou copiar a tela.")
    anterior = _gdi32.SelectObject(memoria, bitmap)
    try:
        _gdi32.SetStretchBltMode(memoria, _HALFTONE)
        _gdi32.SetBrushOrgEx(memoria, 0, 0, None)
        ok = _gdi32.StretchBlt(
            memoria, 0, 0, largura, altura, tela, area.x, area.y, area.largura, area.altura, _SRCCOPY | _CAPTUREBLT
        )
        if not ok:
            raise ErroCaptura("Falha ao copiar a tela (a tela pode estar bloqueada).")
        cabecalho = _BITMAPINFOHEADER(
            biSize=ctypes.sizeof(_BITMAPINFOHEADER), biWidth=largura, biHeight=-altura, biPlanes=1, biBitCount=32
        )
        pixels = np.empty((altura, largura, 4), dtype=np.uint8)
        if not _gdi32.GetDIBits(memoria, bitmap, 0, altura, pixels.ctypes.data, ctypes.byref(cabecalho), 0):
            raise ErroCaptura("Falha ao ler os pixels da tela.")
    finally:
        _gdi32.SelectObject(memoria, anterior)
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(memoria)
        _user32.ReleaseDC(None, tela)
    return np.ascontiguousarray(pixels[:, :, 2::-1])  # BGRA -> RGB


def capturar(alvo: str = "monitor", monitor: int = 1) -> Captura:
    """Tira um print. ``alvo``: "monitor" (o número ``monitor``, 1 é o principal), "todos" ou "janela" (a ativa)."""
    if sys.platform != "win32":
        raise ErroCaptura("Ver a tela só funciona no Windows.")
    lista = monitores()
    if not lista:
        raise ErroCaptura("Não achei nenhum monitor.")
    if alvo == "janela":
        area, titulo = _janela_ativa()
        descricao = f"janela ativa: {titulo or 'sem título'}"
    elif alvo == "todos":
        esquerda, topo = min(r.x for r in lista), min(r.y for r in lista)
        direita = max(r.x + r.largura for r in lista)
        baixo = max(r.y + r.altura for r in lista)
        area = Retangulo(esquerda, topo, direita - esquerda, baixo - topo)
        descricao = f"todos os {len(lista)} monitores" if len(lista) > 1 else "a tela inteira"
    else:
        if not 1 <= monitor <= len(lista):
            raise ErroCaptura(f"O monitor {monitor} não existe; há {len(lista)} monitor(es).")
        area = lista[monitor - 1]
        descricao = "monitor principal" if monitor == 1 else f"monitor {monitor}"
    if area.largura <= 0 or area.altura <= 0:
        raise ErroCaptura("A área a capturar está vazia (janela minimizada?).")
    largura, altura = tamanho_reduzido(area.largura, area.altura)
    with _sem_as_janelas_do_app():
        pixels = _copiar(area, largura, altura)
    png = codificar_png(pixels)
    descricao += f" ({area.largura}x{area.altura}, {len(lista)} monitor(es) no PC)"
    return Captura(png, largura, altura, descricao)
