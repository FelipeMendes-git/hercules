"""Teste de ponta a ponta com o Claude de verdade, sem microfone e sem som.

Cria uma pasta de teste em dados/, "fala" pedidos com a voz sintética (o áudio entra
no app como se viesse do microfone) e confere o resultado:
1. pedir para criar um arquivo;
2. pedir para desfazer (o arquivo some);
3. pedir um comando de terminal, que exige permissão, e responder "sim" por voz.

Usa a sua conta do Claude (três pedidos pequenos).

Uso (na pasta do projeto):
    .venv\\Scripts\\python scripts\\teste_ponta_a_ponta.py
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from pathlib import Path

import numpy as np


def main() -> int:
    from assistente_local import ambiente, caminhos, config, logs, voz
    from assistente_local import eventos as ev
    from assistente_local.audio.reprodutor import reamostrar
    from assistente_local.controlador import Controlador
    from assistente_local.estado import Estado
    from assistente_local.historico import Historico

    logs.configurar()
    ambiente.limpar_heranca_claude()
    cfg = config.carregar()
    nome = cfg.ativacao.nome
    pasta = caminhos.pasta_dados() / "teste-ponta-a-ponta"
    if pasta.exists():
        shutil.rmtree(pasta)
    pasta.mkdir(parents=True)
    temporaria = Path(tempfile.mkdtemp(prefix="assistente-local-teste-"))
    estado = Estado(temporaria / "estado.json")
    historico = Historico(temporaria / "conversas")

    eventos: list[object] = []
    trava = threading.Lock()

    def emitir(evento: object) -> None:
        if isinstance(evento, ev.NivelMicrofone):
            return
        with trava:
            eventos.append(evento)
        if isinstance(evento, (ev.FalaUsuario, ev.AcaoClaude, ev.TextoClaude, ev.FimResposta, ev.PedidoAprovacao,
                               ev.AprovacaoResolvida, ev.Aviso, ev.Pronto, ev.FalaIgnorada, ev.LoginNecessario)):
            print("   ", type(evento).__name__, {k: v for k, v in vars(evento).items() if v not in ("", None)}, flush=True)

    controlador = Controlador(
        cfg,
        emitir,
        simular_microfone=True,
        sem_som=True,
        estado_salvo=estado,
        historico=historico,
        projeto_inicial=config.Projeto("teste-ponta-a-ponta", str(pasta)),
    )
    controlador.iniciar()
    if not controlador.pronto.wait(240):
        print("O assistente não ficou pronto a tempo.")
        controlador.encerrar()
        return 1
    gerador = voz.VozKokoro(cfg.voz.voz, 1.0)

    def falar(frase: str) -> int:
        print(f"\n>>> falando: {frase}", flush=True)
        while controlador._falando:  # espera o assistente terminar de falar
            time.sleep(0.1)
        time.sleep(0.6)
        with trava:
            marca = len(eventos)
        audio = reamostrar(gerador.sintetizar(frase), gerador.taxa, 16000)
        sinal = np.concatenate([np.zeros(8000, np.float32), audio, np.zeros(24000, np.float32)])
        inicio = time.monotonic()
        for i in range(0, len(sinal) - 511, 512):
            controlador._ouvinte.alimentar(sinal[i : i + 512], inicio + i / 16000)
        return marca

    def esperar(tipo, depois: int, limite: float = 300.0):
        prazo = time.time() + limite
        while time.time() < prazo:
            with trava:
                for evento in eventos[depois:]:
                    if isinstance(evento, tipo):
                        return evento
            time.sleep(0.1)
        return None

    resultados: dict[str, bool] = {}
    try:
        time.sleep(3)  # dá tempo da checagem de login
        sem_login = esperar(ev.LoginNecessario, 0, 1) is not None
        marca = falar(f"{nome}, crie um arquivo chamado notas ponto txt com a palavra teste dentro.")
        fim = esperar(ev.FimResposta, marca)
        resultados["respondeu com fala"] = bool(fim and fim.fala)
        conversas = historico.listar()
        resultados["gravou a conversa"] = bool(conversas and conversas[0].titulo.lower().startswith(nome.lower()))
        if sem_login:
            print("\nO Claude Code não está logado: rode  claude auth login --claudeai  e teste de novo.")
            resultados["login do Claude Code"] = False
            return 1
        arquivos = [p for p in pasta.glob("*.txt")]
        criou = bool(fim and not fim.erro and arquivos and "teste" in arquivos[0].read_text(encoding="utf-8").lower())
        resultados["criou o arquivo"] = criou
        resultados["mostrou o arquivo na resposta"] = bool(fim and any(a.endswith(".txt") for a in fim.arquivos))

        marca = falar(f"{nome}, desfaz isso.")
        aviso = esperar(ev.Aviso, marca, 60)
        time.sleep(1.0)
        resultados["desfez a criação"] = bool(criou and aviso and "desfeitas" in aviso.mensagem and not list(pasta.glob("*.txt")))

        marca = falar(f"{nome}, rode o comando git init nesta pasta.")
        pedido = esperar(ev.PedidoAprovacao, marca, 240)
        resultados["pediu permissão"] = pedido is not None
        if pedido:
            time.sleep(0.5)
            falar("Sim, pode.")
            resolvido = esperar(ev.AprovacaoResolvida, marca, 60)
            resultados["aprovação por voz"] = bool(resolvido and resolvido.aprovado and resolvido.por == "voz")
            fim = esperar(ev.FimResposta, marca, 240)
            resultados["rodou o comando"] = bool(fim and not fim.erro and (pasta / ".git").is_dir())
    finally:
        controlador.encerrar()
        print("\n== Resultado")
        for nome_teste, ok in resultados.items():
            print(f"   {'OK   ' if ok else 'FALHOU'} {nome_teste}")
        shutil.rmtree(pasta, ignore_errors=True)
        shutil.rmtree(temporaria, ignore_errors=True)
    return 0 if resultados and all(resultados.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
