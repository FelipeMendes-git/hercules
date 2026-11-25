"""Diagnóstico: testa cada peça do assistente sem precisar falar no microfone.

Uso (na pasta do projeto):
    .venv\\Scripts\\python scripts\\diagnostico.py

Gera uma frase com a voz sintética, passa pelo detector de voz, pelo reconhecimento
(Whisper) e pelo detector do nome, e confere se microfone e alto-falante abrem.
"""

from __future__ import annotations

import time

import numpy as np


def etapa(nome: str) -> None:
    print(f"\n== {nome}", flush=True)


def main() -> int:
    import sounddevice as sd

    from assistente_local import ambiente, config, voz
    from assistente_local.ativacao import DetectorNome
    from assistente_local.audio import dispositivos
    from assistente_local.audio.ouvinte import Ouvinte
    from assistente_local.audio.reprodutor import reamostrar
    from assistente_local.reconhecimento import Reconhecedor

    ambiente.limpar_heranca_claude()
    cfg = config.carregar()
    tudo_ok = True

    def mostrar(mensagem, fracao):
        print("  ", mensagem, f"{fracao:.0%}" if fracao is not None else "", flush=True)

    etapa("Voz sintética")
    inicio = time.perf_counter()
    motor = voz.criar(cfg.voz, mostrar)
    frase = f"{cfg.ativacao.nome}, crie um arquivo chamado olá ponto txt com a palavra teste."
    audio = motor.sintetizar(frase)
    print(f"   {motor.descricao}: {len(audio) / motor.taxa:.1f} s de áudio em {time.perf_counter() - inicio:.1f} s")

    etapa("Voz do Windows (reserva)")
    try:
        windows = voz.VozWindows(cfg.voz.voz_sapi)
        amostra = windows.sintetizar("Teste da voz do Windows.")
        print(f"   ok: {len(amostra) / windows.taxa:.1f} s a {windows.taxa} Hz")
    except Exception as erro:
        print("   falhou:", erro)

    etapa("Reconhecimento de fala (Whisper)")
    reconhecedor = Reconhecedor(cfg.reconhecimento)
    inicio = time.perf_counter()
    descricao = reconhecedor.carregar(mostrar)
    print(f"   {cfg.reconhecimento.modelo} carregado em {time.perf_counter() - inicio:.1f} s ({descricao})")

    etapa("Detecção de voz, corte da fala, transcrição e nome")
    audio16 = reamostrar(audio, motor.taxa, 16000)
    sinal = np.concatenate([np.zeros(16000, np.float32), audio16, np.zeros(24000, np.float32)])
    falas = []
    ouvinte = Ouvinte(cfg.audio, falas.append)
    ouvinte.iniciar(simulado=True)
    agora = time.monotonic()
    for i in range(0, len(sinal) - 511, 512):
        ouvinte.alimentar(sinal[i : i + 512], agora + i / 16000)
    prazo = time.time() + 10
    while not falas and time.time() < prazo:
        time.sleep(0.05)
    ouvinte.parar()
    if not falas:
        print("   nenhuma fala detectada")
        tudo_ok = False
    else:
        fala = falas[0]
        print(f"   fala detectada: {fala.duracao:.1f} s")
        transcricao = reconhecedor.transcrever(fala.audio, dica=f"{cfg.ativacao.nome}, Claude.")
        print(f"   transcrição em {transcricao.tempo_s:.2f} s: {transcricao.texto}")
        detector = DetectorNome(cfg.ativacao.nome, cfg.ativacao.apelidos, cfg.ativacao.similaridade_minima)
        deteccao = detector.detectar(transcricao.texto)
        print(f"   chamou o assistente: {'sim' if deteccao.ativado else 'não'}; pedido: {deteccao.comando!r}")
        tudo_ok = tudo_ok and deteccao.ativado

    etapa("Dispositivos de áudio")
    print("   microfones:", "; ".join(n for _, n in dispositivos.listar(True)[:6]) or "nenhum")
    print("   saídas:", "; ".join(n for _, n in dispositivos.listar(False)[:6]) or "nenhuma")
    try:
        with sd.InputStream(samplerate=16000, channels=1, dtype="float32", blocksize=512):
            time.sleep(0.3)
        print("   o microfone padrão abre: ok")
    except Exception as erro:
        print("   o microfone padrão falhou:", erro)
        tudo_ok = False
    try:
        with sd.OutputStream(samplerate=24000, channels=1, dtype="float32"):
            pass
        print("   a saída padrão abre: ok")
    except Exception as erro:
        print("   a saída padrão falhou:", erro)
        tudo_ok = False

    print("\nTudo certo." if tudo_ok else "\nAlgo falhou; veja acima.")
    return 0 if tudo_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
