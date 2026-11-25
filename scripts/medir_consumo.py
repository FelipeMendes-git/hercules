"""Mede quanto o assistente custa para o PC enquanto fica ouvindo.

Não abre o microfone: alimenta ruído de ambiente simulado no mesmo ritmo do microfone real
(31 janelas de áudio por segundo), depois uma frase falada sem o nome do assistente (como
numa conversa com amigos durante um jogo) e, por fim, uma chamada pelo nome depois que a placa
de vídeo foi liberada. Mostra processador, memória e placa de vídeo.

Uso (na pasta do projeto, com o app fechado):
    .venv\\Scripts\\python scripts\\medir_consumo.py
"""

from __future__ import annotations

import os
import subprocess
import threading
import time

import numpy as np

_SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _vram_usada_mb() -> float | None:
    try:
        saida = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=_SEM_JANELA,
        )
        return float(saida.stdout.strip().splitlines()[0])
    except Exception:
        return None


def _processos_filhos(pid: int) -> list[int]:
    comando = f"(Get-CimInstance Win32_Process -Filter 'ParentProcessId={pid}').ProcessId"
    saida = subprocess.run(
        ["powershell", "-NoProfile", "-Command", comando], capture_output=True, text=True, timeout=30, creationflags=_SEM_JANELA
    )
    filhos = [int(x) for x in saida.stdout.split() if x.strip().isdigit()]
    return filhos + [neto for filho in filhos for neto in _processos_filhos(filho)]


def _abrir(pid: int):
    import win32api
    import win32con

    return win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ, False, pid)


def _memoria_mb(pid: int) -> float:
    import win32process

    return win32process.GetProcessMemoryInfo(_abrir(pid))["WorkingSetSize"] / 2**20


def _reservada_mb(pid: int) -> float:
    import win32process

    return win32process.GetProcessMemoryInfo(_abrir(pid))["PagefileUsage"] / 2**20


def _tempo_cpu_s(pid: int) -> float:
    import win32process

    tempos = win32process.GetProcessTimes(_abrir(pid))
    return (tempos["KernelTime"] + tempos["UserTime"]) / 1e7


def _nome(pid: int) -> str:
    import win32process

    try:
        return os.path.basename(win32process.GetModuleFileNameEx(_abrir(pid), 0))
    except Exception:
        return f"pid {pid}"


def _ultimas_linhas_do_log(trecho: str, depois: int) -> list[str]:
    caminho = os.path.join("dados", "logs", "app.log")
    linhas = open(caminho, encoding="utf-8").read().splitlines()[depois:]
    return [linha.split(": ", 1)[-1] for linha in linhas if trecho in linha]


def _tamanho_do_log() -> int:
    caminho = os.path.join("dados", "logs", "app.log")
    return len(open(caminho, encoding="utf-8").read().splitlines()) if os.path.exists(caminho) else 0


def _sintetizar_em_outro_processo(frases: list[str]) -> list[np.ndarray]:
    """Gera as frases de teste noutro processo, para a voz do teste não somar na memória medida."""
    import json
    import sys
    import tempfile
    from pathlib import Path

    pasta = Path(tempfile.mkdtemp(prefix="medir-consumo-"))
    codigo = (
        "import sys, json, numpy as np\n"
        "from assistente_local import voz\n"
        "from assistente_local.audio.reprodutor import reamostrar\n"
        "g = voz.VozKokoro('pf_dora', 1.0)\n"
        "for i, f in enumerate(json.loads(sys.argv[1])):\n"
        "    np.save(sys.argv[2] + f'/{i}.npy', reamostrar(g.sintetizar(f), g.taxa, 16000))\n"
    )
    subprocess.run(
        [sys.executable, "-c", codigo, json.dumps(frases), str(pasta)], check=True, creationflags=_SEM_JANELA
    )
    return [np.load(pasta / f"{i}.npy") for i in range(len(frases))]


def main() -> int:
    from assistente_local import ambiente, config, logs
    from assistente_local import eventos as ev
    from assistente_local.audio.vad import DetectorVoz
    from assistente_local.controlador import Controlador

    logs.configurar()
    ambiente.limpar_heranca_claude()
    cfg = config.carregar()
    cfg.espera.comecar_em_espera = True
    cfg.espera.voltar_apos_min = 0.25  # só para a medição: volta para a espera em 15 s
    nucleos = os.cpu_count() or 1
    frase_sem_nome, frase_com_nome = _sintetizar_em_outro_processo(
        [
            "Cuidado, tem um cara atrás de você, vai pela esquerda que eu te dou cobertura.",
            f"{cfg.ativacao.nome}, qual é o projeto atual?",
        ]
    )
    eventos: list[object] = []
    pronto = threading.Event()

    def emitir(evento: object) -> None:
        if isinstance(evento, ev.NivelMicrofone):
            return
        eventos.append(evento)
        if isinstance(evento, ev.Pronto):
            pronto.set()

    vad = DetectorVoz()
    janela = (np.random.default_rng(0).standard_normal(512) * 0.003).astype(np.float32)
    inicio = time.perf_counter()
    for _ in range(3000):
        vad(janela)
    vad_us = (time.perf_counter() - inicio) / 3000 * 1e6

    vram_antes = _vram_usada_mb()
    inicio = time.perf_counter()
    controlador = Controlador(cfg, emitir, simular_microfone=True, sem_som=True)
    controlador.iniciar()
    if not pronto.wait(240):
        print("O assistente não ficou pronto.")
        controlador.encerrar()
        return 1
    print(f"Pronto em {time.perf_counter() - inicio:.1f} s")
    time.sleep(2)
    pid = os.getpid()

    def fotografia(titulo: str) -> None:
        vram = _vram_usada_mb()
        print(f"\n== {titulo}")
        print(f"   RAM do app: {_memoria_mb(pid):,.0f} MB em uso ({_reservada_mb(pid):,.0f} MB reservados)")
        claude = [f for f in _processos_filhos(pid) if _nome(f).lower().startswith("claude")]
        for filho in claude:
            print(f"   RAM do Claude Code: {_memoria_mb(filho):,.0f} MB")
        if not claude:
            print("   Claude Code: fechado")
        if vram is not None and vram_antes is not None:
            print(f"   memória de vídeo do app: ~{max(0.0, vram - vram_antes):,.0f} MB")

    fotografia("Ao abrir (em espera)")
    ouvinte = controlador._ouvinte
    print("\n== Processador (Ryzen com 8 núcleos = 100% de um núcleo é 12,5% do total)")
    print(f"   detecção de voz: {vad_us:.0f} µs a cada 32 ms de áudio = {vad_us * 31.25 / 1e4:.2f}% de um núcleo")
    cpu0 = _tempo_cpu_s(pid)
    rng = np.random.default_rng(1)
    proximo = time.perf_counter()
    for _ in range(int(20 * 16000 / 512)):
        ouvinte.alimentar((rng.standard_normal(512) * 0.003).astype(np.float32))
        proximo += 512 / 16000
        if proximo > time.perf_counter():
            time.sleep(proximo - time.perf_counter())
    cpu_ouvindo = (_tempo_cpu_s(pid) - cpu0) / 20
    print(f"   app inteiro ouvindo o ambiente por 20 s: {cpu_ouvindo * 100 / nucleos:.2f}% do processador")

    def falar(audio: np.ndarray) -> tuple[float, list[str]]:
        marca_log = _tamanho_do_log()
        cpu0 = _tempo_cpu_s(pid)
        sinal = np.concatenate([np.zeros(8000, np.float32), audio, np.zeros(24000, np.float32)])
        for i in range(0, len(sinal) - 511, 512):
            ouvinte.alimentar(sinal[i : i + 512])
        time.sleep(4)
        return _tempo_cpu_s(pid) - cpu0, _ultimas_linhas_do_log("Ouvi", marca_log) + _ultimas_linhas_do_log(
            "Modelo principal carregado", marca_log
        )

    print("\n== Alguém falando perto do microfone sem chamar o nome")
    vram_frase0 = _vram_usada_mb()
    cpu, linhas = falar(frase_sem_nome)
    for linha in linhas:
        print(f"   {linha}")
    print(f"   processador gasto: {cpu:.2f} s de CPU")
    if vram_frase0 is not None:
        print(f"   memória de vídeo durante a frase: {(_vram_usada_mb() or 0) - vram_frase0:+.0f} MB")

    print("\n== Chamando pelo nome (acordando)")
    marca = len(eventos)
    _cpu, linhas = falar(frase_com_nome)
    for linha in linhas:
        print(f"   {linha}")
    entendeu = next((e for e in eventos[marca:] if isinstance(e, ev.FalaUsuario)), None)
    print(f"   entendeu o pedido: {'sim' if entendeu else 'não'}")
    time.sleep(4)  # voz e Claude Code terminam de abrir em paralelo
    fotografia("Acordado (depois de chamar)")

    prazo = time.time() + 60
    while time.time() < prazo and not controlador._em_espera:
        time.sleep(1)
    time.sleep(3)
    fotografia("De volta à espera (sem ser chamado)")

    proximo = time.perf_counter()
    for _ in range(int(15 * 16000 / 512)):
        ouvinte.alimentar((rng.standard_normal(512) * 0.003).astype(np.float32))
        proximo += 512 / 16000
        if proximo > time.perf_counter():
            time.sleep(proximo - time.perf_counter())
    falar(frase_sem_nome)
    fotografia("Em espera, depois de ouvir o ambiente e uma frase de novo")

    controlador.encerrar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
