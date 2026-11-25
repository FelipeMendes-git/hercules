"""Saudação ao ser chamado: uma abertura e uma frase divertida, com música de fundo.

Não passa pelo Claude. As frases são sorteadas sem repetir as últimas (com aberturas próprias
para a madrugada, a segunda de manhã, a sexta e o fim de semana), gravadas uma vez com a voz do
app (pasta ``dados/saudacoes``) e depois tocam na hora, sem precisar carregar a voz. A música é
uma vinheta composta aqui mesmo (sem direitos autorais de terceiros) ou um arquivo seu.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from . import caminhos

log = logging.getLogger(__name__)

TAXA = 24000


# ---------------------------------------------------------------------- vinheta
def _hz(nota_midi: float) -> float:
    return 440.0 * 2.0 ** ((nota_midi - 69) / 12)


def _nota(frequencia: float, duracao: float, timbre: str, taxa: int = TAXA) -> np.ndarray:
    t = np.arange(int(duracao * taxa)) / taxa
    if timbre == "marimba":
        onda = (
            np.sin(2 * np.pi * frequencia * t)
            + 0.15 * np.sin(4 * np.pi * frequencia * t)
            + 0.35 * np.sin(8 * np.pi * frequencia * t) * np.exp(-t * 30)
        )
        envelope = np.exp(-t * 6.0) * np.minimum(1.0, t / 0.004)
    elif timbre == "pad":
        onda = sum(np.sin(2 * np.pi * frequencia * (1 + d) * t) for d in (-0.003, 0.0, 0.003)) / 3
        envelope = np.minimum(1.0, t / 0.25) * np.clip((duracao - t) / 0.4, 0.0, 1.0)
    else:  # baixo
        onda = np.sin(2 * np.pi * frequencia * t) + 0.2 * np.sin(4 * np.pi * frequencia * t)
        envelope = np.exp(-t * 3.0) * np.minimum(1.0, t / 0.01)
    return (onda * envelope).astype(np.float32)


SEM_MUSICA = "nenhuma"
ESTILOS = {SEM_MUSICA: "Sem música (só a voz)", "rock": "Rock pesado", "suave": "Suave (marimba)"}
ATRASO_VOZ_S = {"rock": 1.0, "suave": 0.8}  # quando a voz entra por cima da música
ABAIXAR = {"rock": 0.35, "suave": 0.5}  # quanto a música abaixa enquanto a voz fala (o rock é mais denso)
_vinhetas: dict[str, np.ndarray] = {}


def vinheta(estilo: str = "rock") -> np.ndarray:
    """Vinheta gerada pelo próprio app (composição original, sem direitos de terceiros)."""
    estilo = estilo if estilo in ESTILOS else "rock"
    if estilo not in _vinhetas:
        _vinhetas[estilo] = _vinheta_rock() if estilo == "rock" else _vinheta_suave()
    return _vinhetas[estilo]


# ---------------------------------------------------------------------- vinheta de rock
def _eq(sinal: np.ndarray, pontos: list[tuple[float, float]]) -> np.ndarray:
    """Equalização por FFT: (frequência em Hz, ganho em dB), interpolada em escala logarítmica."""
    espectro = np.fft.rfft(sinal)
    frequencias = np.maximum(np.fft.rfftfreq(len(sinal), 1 / TAXA), 1.0)
    ganho_db = np.interp(np.log10(frequencias), np.log10([p[0] for p in pontos]), [p[1] for p in pontos])
    return np.fft.irfft(espectro * 10 ** (ganho_db / 20), n=len(sinal)).astype(np.float32)


def _corda(frequencia: float, duracao: float, rng, abafar: float = 0.0, decaimento: float = 0.998) -> np.ndarray:
    """Corda pinçada (Karplus-Strong), calculada um período por vez.

    ``abafar`` (0 a 1) escurece o ataque, como a palma da mão encostada nas cordas.
    """
    periodo = max(2, int(round(TAXA / frequencia - 0.5)))  # o filtro de média atrasa meia amostra
    total = int(duracao * TAXA)
    excitacao = rng.uniform(-1.0, 1.0, periodo)
    if abafar > 0:
        for n in range(1, periodo):  # passa-baixa de um polo no ataque
            excitacao[n] = (1.0 - abafar) * excitacao[n] + abafar * excitacao[n - 1]
    saida = np.zeros(total + periodo, np.float64)
    saida[:periodo] = excitacao - excitacao.mean()
    i = periodo
    while i < total:
        anterior = saida[i - periodo : i]
        atrasado = saida[i - periodo - 1 : i - 1] if i > periodo else np.concatenate(([0.0], anterior[:-1]))
        saida[i : i + periodo] = decaimento * 0.5 * (anterior + atrasado)
        i += periodo
    return saida[:total].astype(np.float32)


def _soltar(som: np.ndarray, segundos: float = 0.02) -> np.ndarray:
    """Termina a nota sem estalo."""
    n = min(len(som), int(segundos * TAXA))
    if n:
        som[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)
    return som


def _acorde_de_quinta(raiz_midi: int, duracao: float, abafado: bool, rng) -> np.ndarray:
    """Power chord (raiz, quinta e oitava) palhetado de cima para baixo e distorcido."""
    comprimento = int((duracao + 0.02) * TAXA)  # a nota e o tempo da mão abafar as cordas
    soma = np.zeros(comprimento, np.float32)
    for k, intervalo in enumerate((0, 7, 12)):
        frequencia = _hz(raiz_midi + intervalo)
        if abafado:  # palma da mão nas cordas: som escuro e curto
            corda = _corda(frequencia, duracao + 0.02, rng, abafar=0.75, decaimento=0.99)
            corda *= np.exp(-np.arange(len(corda)) / TAXA * 22)
        else:
            corda = _corda(frequencia, duracao + 0.02, rng, decaimento=0.9995)
        inicio = int(k * 0.006 * TAXA)  # 6 ms entre uma corda e outra
        soma[inicio:] += corda[: comprimento - inicio]
    soma = _eq(soma, [(40, -24), (100, -6), (200, 0), (800, 4), (2500, 0), (8000, -6)])  # pedal antes do amplificador
    soma = np.tanh(9.0 * soma / (float(np.max(np.abs(soma))) or 1.0))  # distorção
    return _soltar(soma)


def _sala(sinal: np.ndarray, rng, mistura: float = 0.15, duracao: float = 0.7) -> np.ndarray:
    """Reverberação simples (convolução com ruído que decai), para não soar seco demais."""
    t = np.arange(int(duracao * TAXA)) / TAXA
    resposta = _eq((rng.standard_normal(len(t)) * np.exp(-t * 6.9 / duracao)).astype(np.float32), [(200, -12), (500, 0), (4000, -3), (8000, -18)])
    n = len(sinal) + len(resposta)
    molhado = np.fft.irfft(np.fft.rfft(sinal, n) * np.fft.rfft(resposta, n), n)[: len(sinal)]
    molhado *= np.sqrt(np.mean(sinal**2)) / (np.sqrt(np.mean(molhado**2)) or 1.0)
    return (sinal + mistura * molhado).astype(np.float32)


def _bumbo(rng) -> np.ndarray:
    t = np.arange(int(0.35 * TAXA)) / TAXA
    frequencia = 50 + 120 * np.exp(-t * 35)
    corpo = np.sin(2 * np.pi * np.cumsum(frequencia) / TAXA) * np.exp(-t * 9)
    batida = _eq(rng.standard_normal(len(t)).astype(np.float32), [(1000, -20), (3000, 0), (6000, -10)]) * np.exp(-t * 300)
    return (corpo + 0.25 * batida / (np.max(np.abs(batida)) or 1)).astype(np.float32)


def _caixa(rng) -> np.ndarray:
    t = np.arange(int(0.25 * TAXA)) / TAXA
    ruido = _eq(rng.standard_normal(len(t)).astype(np.float32), [(100, -30), (300, -12), (1000, 0), (5000, 0), (10000, -10)])
    return (0.8 * ruido / (np.max(np.abs(ruido)) or 1) * np.exp(-t * 18) + 0.6 * np.sin(2 * np.pi * 185 * t) * np.exp(-t * 25)).astype(np.float32)


def _chimbal(rng) -> np.ndarray:
    ruido = np.diff(np.diff(rng.standard_normal(int(0.05 * TAXA)), prepend=0), prepend=0)
    return (ruido / (np.max(np.abs(ruido)) or 1) * np.exp(-np.arange(len(ruido)) / TAXA * 80)).astype(np.float32)


def _prato(rng) -> np.ndarray:
    t = np.arange(int(1.8 * TAXA)) / TAXA
    ruido = _eq(rng.standard_normal(len(t)).astype(np.float32), [(500, -40), (2000, -12), (5000, 0), (9000, 0), (11500, -6)])
    return (ruido / (np.max(np.abs(ruido)) or 1) * np.exp(-t * 2.2) * np.minimum(1.0, t / 0.002)).astype(np.float32)


def _vinheta_rock() -> np.ndarray:
    """Riff original de hard rock: mi com quinta, abafados, sol, lá, ré, dó e o mi final soando.

    O mi final fica soando e some aos poucos, para cobrir até as saudações mais longas (~9 s).
    """
    rng = np.random.default_rng(2026)
    colcheia = 60 / 128 / 2
    total = int(TAXA * 9.6)
    guitarra = np.zeros(total, np.float32)
    baixo = np.zeros(total, np.float32)
    bateria = np.zeros(total, np.float32)

    def colocar(destino: np.ndarray, som: np.ndarray, inicio_s: float, ganho: float) -> None:
        inicio = int(inicio_s * TAXA)
        fim = min(len(destino), inicio + len(som))
        if fim > inicio:
            destino[inicio:fim] += som[: fim - inicio] * ganho

    mi, sol, la, re, do = 40, 43, 45, 38, 36  # notas MIDI da raiz (cordas graves)
    riff = [
        (0, mi, 3, False), (3, mi, 1, True), (4, mi, 1, True), (5, sol, 1, False), (6, la, 2, False),
        (8, mi, 2, False), (10, mi, 1, True), (11, mi, 1, True), (12, re, 1, False), (13, do, 1, False),
        (14, mi, 26, False),
    ]
    inicio = 0.12
    for indice, raiz, colcheias, abafado in riff:
        t0 = inicio + indice * colcheia
        colocar(guitarra, _acorde_de_quinta(raiz, colcheias * colcheia, abafado, rng), t0, 0.5)
        if not abafado:  # segunda guitarra, uma oitava acima, só nos acordes abertos
            colocar(guitarra, _acorde_de_quinta(raiz + 12, colcheias * colcheia, False, rng), t0 + 0.008, 0.28)
        nota = _corda(_hz(raiz - 12), colcheias * colcheia + 0.02, rng, decaimento=0.999)
        colocar(baixo, _soltar(np.tanh(2.0 * nota)), t0, 0.6)

    bumbo, caixa, chimbal, prato = _bumbo(rng), _caixa(rng), _chimbal(rng), _prato(rng)
    for indice in (0, 3, 4, 8, 11, 12, 14):
        colocar(bateria, bumbo, inicio + indice * colcheia, 0.9)
    for indice in (2, 6, 10, 14):
        colocar(bateria, caixa, inicio + indice * colcheia, 0.6)
    for indice in (0, 8, 14):
        colocar(bateria, prato, inicio + indice * colcheia, 0.35)
    for indice in range(1, 14):
        if indice != 8:
            colocar(bateria, chimbal, inicio + indice * colcheia, 0.12)

    guitarra = _eq(
        guitarra,
        [(20, -40), (70, -12), (100, 0), (250, 2), (800, 0), (1500, 2), (2500, 4), (3500, 2), (5000, -6), (6500, -20), (9000, -40), (12000, -60)],
    )  # caixa de amplificador
    baixo = _eq(baixo, [(20, -40), (35, -6), (45, 0), (200, 2), (800, -6), (2000, -30), (12000, -60)])
    guitarra = _sala(guitarra, rng, mistura=0.12)
    bateria = _sala(bateria, rng, mistura=0.2)
    mistura = 0.55 * guitarra / (np.max(np.abs(guitarra)) or 1) + 0.4 * baixo / (np.max(np.abs(baixo)) or 1) + bateria
    mistura = np.tanh(1.2 * mistura / (float(np.max(np.abs(mistura))) or 1.0))  # "cola" a mixagem
    mistura *= 0.9 / (float(np.max(np.abs(mistura))) or 1.0)
    queda = len(mistura) - int(7.0 * TAXA)  # o acorde final some aos poucos a partir de 7 s
    mistura[-queda:] *= np.linspace(1.0, 0.0, queda, dtype=np.float32)
    return mistura.astype(np.float32)


# ---------------------------------------------------------------------- vinheta suave
def _vinheta_suave() -> np.ndarray:
    """Vinheta animada de ~7 s: abertura "tcharã" e a sequência C–G–Am–F em marimba, baixo e fundo."""
    batida = 60 / 116
    total = int(TAXA * 7.0)
    mistura = np.zeros(total, np.float32)

    def colocar(som: np.ndarray, inicio_s: float, ganho: float) -> None:
        inicio = int(inicio_s * TAXA)
        fim = min(total, inicio + len(som))
        if fim > inicio:
            mistura[inicio:fim] += som[: fim - inicio] * ganho

    for k, nota in enumerate((72, 76, 79, 84)):  # subida rápida: dó, mi, sol, dó
        colocar(_nota(_hz(nota), 0.6, "marimba"), k * 0.07, 0.35)
    acordes = ((60, (60, 64, 67)), (55, (55, 59, 62)), (57, (57, 60, 64)), (53, (53, 57, 60)))
    inicio = 0.45
    for n, (raiz, triade) in enumerate(acordes):
        t0 = inicio + n * 2 * batida
        colocar(_nota(_hz(raiz - 12), 2 * batida + 0.3, "baixo"), t0, 0.45)
        for nota in triade:
            colocar(_nota(_hz(nota + 12), 2 * batida + 0.5, "pad"), t0, 0.06)
        arpejo = (triade[0] + 12, triade[1] + 12, triade[2] + 12, triade[1] + 12)
        for k, nota in enumerate(arpejo):
            colocar(_nota(_hz(nota), 0.6, "marimba"), t0 + k * batida / 2, 0.28)
    final = inicio + 8 * batida
    for nota in (72, 76, 79, 84):
        colocar(_nota(_hz(nota), 2.2, "marimba"), final, 0.2)
    colocar(_nota(_hz(48), 2.5, "baixo"), final, 0.45)
    ruido = np.random.default_rng(7).standard_normal(int(0.04 * TAXA)).astype(np.float32)
    chimbal = np.diff(ruido, prepend=0.0) * np.exp(-np.arange(len(ruido)) / TAXA * 70)
    for k in range(16):  # chimbal leve nos contratempos
        colocar(chimbal, inicio + k * batida / 2 + batida / 4, 0.04)
    pico = float(np.max(np.abs(mistura))) or 1.0
    mistura *= 0.9 / pico
    queda = int(0.8 * TAXA)
    mistura[-queda:] *= np.linspace(1.0, 0.0, queda, dtype=np.float32)
    return mistura


# ---------------------------------------------------------------------- música do usuário
def carregar_musica(caminho: str, maximo_s: float = 30.0) -> np.ndarray | None:
    """Lê um arquivo de música (mp3, wav, ogg...) em mono, 24 kHz, só o começo."""
    try:
        import av

        pedacos: list[np.ndarray] = []
        lidos = 0
        with av.open(caminho) as arquivo:
            fluxo = arquivo.streams.audio[0]
            conversor = av.AudioResampler(format="flt", layout="mono", rate=TAXA)
            for quadro in arquivo.decode(fluxo):
                for saida in conversor.resample(quadro):
                    dados = saida.to_ndarray().reshape(-1).astype(np.float32)
                    pedacos.append(dados)
                    lidos += len(dados)
                if lidos >= maximo_s * TAXA:
                    break
        if not pedacos:
            return None
        musica = np.concatenate(pedacos)[: int(maximo_s * TAXA)]
        pico = float(np.max(np.abs(musica))) or 1.0
        return (musica * (0.9 / pico)).astype(np.float32)
    except Exception as erro:
        log.warning("Não consegui ler a música %s: %s", caminho, erro)
        return None


# ---------------------------------------------------------------------- mixagem
def mixar(
    voz: np.ndarray,
    musica: np.ndarray,
    volume_musica: float = 0.35,
    atraso_voz_s: float = 0.8,
    cauda_s: float = 1.0,
    abaixar: float = 0.5,
) -> np.ndarray:
    """Voz por cima da música: a música entra antes, abaixa enquanto a voz fala e some logo depois."""
    inicio_voz = int(atraso_voz_s * TAXA)
    fim_voz = inicio_voz + len(voz)
    total = fim_voz + int(cauda_s * TAXA)
    fundo = np.zeros(total, np.float32)
    trecho = musica[:total]
    fundo[: len(trecho)] = trecho
    ganho = np.ones(total, np.float32)
    rampa = int(0.2 * TAXA)
    ganho[inicio_voz:] = abaixar  # abaixa a música enquanto a voz fala
    ganho[max(0, inicio_voz - rampa) : inicio_voz] = np.linspace(1.0, abaixar, inicio_voz - max(0, inicio_voz - rampa))
    subida = min(rampa, total - fim_voz)
    ganho[fim_voz : fim_voz + subida] = np.linspace(abaixar, 0.8, subida)
    ganho[fim_voz + subida :] = 0.8
    queda = min(int(0.8 * TAXA), total)
    ganho[-queda:] *= np.linspace(1.0, 0.0, queda, dtype=np.float32)
    saida = fundo * ganho * float(volume_musica)
    saida[inicio_voz:fim_voz] += voz
    pico = float(np.max(np.abs(saida))) or 1.0
    if pico > 0.98:
        saida *= 0.98 / pico
    return saida.astype(np.float32)


def voz_confere(motor_voz, cfg_voz) -> bool:
    """O motor carregado é a voz escolhida, e não a reserva do Windows no lugar do Kokoro?"""
    motor = getattr(motor_voz, "motor", cfg_voz.motor)
    if motor != cfg_voz.motor:
        return False
    return motor != "kokoro" or getattr(motor_voz, "voz", cfg_voz.voz) == cfg_voz.voz


# ---------------------------------------------------------------------- frases e ocasiões
PERIODOS = ("Bom dia", "Boa tarde", "Boa noite")
# Na hora de uma ocasião especial, a abertura dela entra no lugar da comum com esta chance.
OCASIOES = {
    "madrugada": "Madrugada (0h–5h)",
    "segunda": "Segunda de manhã",
    "sexta": "Sexta-feira",
    "fim_de_semana": "Fim de semana",
}
CHANCE_OCASIAO = 0.5


def periodo(agora: datetime | None = None) -> str:
    hora = (agora or datetime.now()).hour
    if 5 <= hora < 12:
        return "Bom dia"
    if 12 <= hora < 18:
        return "Boa tarde"
    return "Boa noite"


def ocasiao(agora: datetime | None = None) -> str | None:
    """A ocasião especial do momento, se houver (a madrugada vale em qualquer dia)."""
    agora = agora or datetime.now()
    if agora.hour < 5:
        return "madrugada"
    if agora.weekday() == 0 and agora.hour < 12:
        return "segunda"
    if agora.weekday() == 4:
        return "sexta"
    if agora.weekday() >= 5:
        return "fim_de_semana"
    return None


def preencher(frase: str, periodo_do_dia: str, tratamento: str) -> str:
    """Troca {periodo} e {tratamento} na frase (outras chaves que você escrever ficam como estão)."""
    tratamento = tratamento.strip()
    if not tratamento:  # sem tratamento, "Boa noite, {tratamento}!" vira "Boa noite!"
        for trecho in (", {tratamento}", "{tratamento}, ", "{tratamento}! ", "{tratamento}"):
            frase = frase.replace(trecho, "")
    texto = " ".join(frase.replace("{periodo}", periodo_do_dia).replace("{tratamento}", tratamento).split())
    return texto[:1].upper() + texto[1:]


def _limpas(frases) -> list[str]:
    return [f.strip() for f in frases if isinstance(f, str) and f.strip()]


# ---------------------------------------------------------------------- frases gravadas
class Saudacoes:
    LISTAS = ("aberturas", "frases_chamado", "frases_pedido", *OCASIOES)

    def __init__(self, cfg_saudacao, cfg_voz, pasta: Path | None = None):
        self.cfg = cfg_saudacao
        self.cfg_voz = cfg_voz
        self.pasta = pasta or (caminhos.pasta_dados() / "saudacoes")
        self._musica: np.ndarray | None = None
        self._musica_de = None
        self._recentes: dict[str, list[str]] | None = None

    def _lista(self, nome: str) -> list[str]:
        return _limpas(getattr(self.cfg, nome, []))

    def textos(self) -> list[str]:
        """Todas as frases que precisam estar gravadas (uma versão para cada período do dia)."""
        todos = (
            preencher(frase, p, self.cfg.tratamento) for nome in self.LISTAS for frase in self._lista(nome) for p in PERIODOS
        )
        return list(dict.fromkeys(todos))

    def _arquivo(self, texto: str) -> Path:
        v = self.cfg_voz
        voz_usada = v.voz if v.motor == "kokoro" else v.voz_sapi  # trocar só a reserva não pede regravar
        chave = f"{texto}|{v.motor}|{voz_usada}|{v.velocidade}"
        return self.pasta / (hashlib.sha1(chave.encode("utf-8")).hexdigest()[:16] + ".wav")

    def faltando(self) -> list[str]:
        return [t for t in self.textos() if not self._arquivo(t).is_file()]

    def limpar(self) -> int:
        """Apaga as gravações que não servem mais (outra voz, frases trocadas). Devolve quantas apagou."""
        atuais = {self._arquivo(t).name for t in self.textos()}
        apagadas = 0
        for arquivo in self.pasta.glob("*.wav") if self.pasta.is_dir() else []:
            if len(arquivo.stem) == 16 and all(c in "0123456789abcdef" for c in arquivo.stem) and arquivo.name not in atuais:
                arquivo.unlink(missing_ok=True)
                apagadas += 1
        return apagadas

    def gravar(self, motor_voz, textos: list[str] | None = None) -> int:
        """Grava as frases com a voz do app. Devolve quantas gravou.

        Só grava com a voz escolhida (nunca com a reserva do Windows no lugar do Kokoro): assim a
        saudação sai sempre na mesma voz que lê as respostas do Claude.
        """
        if not voz_confere(motor_voz, self.cfg_voz):
            log.warning("Saudação não gravada: a voz carregada (%s) não é a escolhida.", getattr(motor_voz, "descricao", "?"))
            return 0
        self.pasta.mkdir(parents=True, exist_ok=True)
        feitas = 0
        for texto in textos if textos is not None else self.faltando():
            audio = np.asarray(motor_voz.sintetizar(texto), dtype=np.float32)
            _salvar_wav(self._arquivo(texto), audio, int(motor_voz.taxa))
            feitas += 1
        return feitas

    def _clip(self, texto: str) -> np.ndarray | None:
        arquivo = self._arquivo(texto.strip())
        return _ler_wav(arquivo) if arquivo.is_file() else None

    def _musica_atual(self) -> tuple[np.ndarray, float, float] | None:
        """A música de fundo, quando a voz entra por cima dela e quanto ela abaixa durante a voz (None = sem música)."""
        if self.cfg.musica:
            if self._musica_de != self.cfg.musica:
                self._musica = carregar_musica(self.cfg.musica)
                self._musica_de = self.cfg.musica
            if self._musica is not None:
                return self._musica, 0.8, 0.4
        if self.cfg.estilo == SEM_MUSICA:
            return None
        estilo = self.cfg.estilo if self.cfg.estilo in ATRASO_VOZ_S else "rock"
        return vinheta(estilo), ATRASO_VOZ_S[estilo], ABAIXAR[estilo]

    def preparar_musica(self) -> None:
        """Deixa a música pronta na memória (a vinheta é composta na primeira vez)."""
        self._musica_atual()

    def _sortear(self, lista: str, opcoes: list[str]) -> str:
        """Sorteia uma frase fugindo das últimas usadas dessa lista (lembra mesmo depois de fechar o app)."""
        arquivo = self.pasta / "recentes.json"
        if self._recentes is None:
            try:
                dados = json.loads(arquivo.read_text(encoding="utf-8"))
                self._recentes = {k: [str(x) for x in v] for k, v in dados.items() if isinstance(v, list)}
            except (OSError, ValueError, AttributeError):
                self._recentes = {}
        recentes = self._recentes.setdefault(lista, [])
        evitar = len(opcoes) // 2  # não repete nenhuma da metade mais recente
        ultimas = set(recentes[-evitar:]) if evitar else set()
        escolha = random.choice([o for o in opcoes if o not in ultimas] or opcoes)
        recentes.append(escolha)
        del recentes[:-30]
        try:
            self.pasta.mkdir(parents=True, exist_ok=True)
            temporario = arquivo.with_suffix(".tmp")
            temporario.write_text(json.dumps(self._recentes, ensure_ascii=False, indent=1), encoding="utf-8")
            temporario.replace(arquivo)
        except OSError as erro:
            log.warning("Não consegui guardar as saudações recentes: %s", erro)
        return escolha

    def montar(
        self,
        com_pedido: bool,
        agora: datetime | None = None,
        ocasiao_forcada: str | None = None,
        criar_voz=None,
    ) -> tuple[np.ndarray, str] | None:
        """Monta uma saudação (voz + música), sorteando a abertura e a frase.

        Só usa frases já gravadas (None se ainda não há nenhuma), a não ser que receba ``criar_voz``:
        aí sorteia entre todas e grava na hora as que faltarem. ``ocasiao_forcada`` usa a abertura de
        uma ocasião especial fora da hora. Os dois servem para ouvir nas configurações.
        """
        agora = agora or datetime.now()
        periodo_do_dia, tratamento = periodo(agora), self.cfg.tratamento

        def opcoes(nome: str) -> list[str]:
            frases = self._lista(nome)
            if criar_voz is not None:
                return frases
            return [f for f in frases if self._arquivo(preencher(f, periodo_do_dia, tratamento)).is_file()]

        especial = ocasiao_forcada or ocasiao(agora)
        lista_abertura = "aberturas"
        if especial in OCASIOES and opcoes(especial) and (ocasiao_forcada or random.random() < CHANCE_OCASIAO):
            lista_abertura = especial
        partes = []
        for nome in (lista_abertura, "frases_pedido" if com_pedido else "frases_chamado"):
            frases = opcoes(nome)
            if frases:
                partes.append(preencher(self._sortear(nome, frases), periodo_do_dia, tratamento))
        faltam = [parte for parte in partes if not self._arquivo(parte).is_file()]
        if faltam and criar_voz is not None:
            self.gravar(criar_voz(), faltam)
        clips = [self._clip(parte) for parte in partes]
        if not clips or any(c is None for c in clips):
            return None
        pausa = np.zeros(int(0.12 * TAXA), np.float32)
        voz = np.concatenate([x for c in clips for x in (c, pausa)][:-1])
        fundo = self._musica_atual()
        if fundo is None:
            return voz.astype(np.float32), " ".join(partes)
        musica, atraso, abaixar = fundo
        return mixar(voz, musica, self.cfg.volume_musica, atraso_voz_s=atraso, abaixar=abaixar), " ".join(partes)


def _salvar_wav(arquivo: Path, audio: np.ndarray, taxa: int) -> None:
    if taxa != TAXA:
        n = max(1, int(round(len(audio) * TAXA / taxa)))
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
    dados = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    temporario = arquivo.with_suffix(".tmp")
    with wave.open(str(temporario), "wb") as saida:
        saida.setnchannels(1)
        saida.setsampwidth(2)
        saida.setframerate(TAXA)
        saida.writeframes(dados.tobytes())
    temporario.replace(arquivo)


def _ler_wav(arquivo: Path) -> np.ndarray | None:
    try:
        with wave.open(str(arquivo), "rb") as entrada:
            dados = np.frombuffer(entrada.readframes(entrada.getnframes()), dtype="<i2")
        return dados.astype(np.float32) / 32768.0
    except (OSError, wave.Error) as erro:
        log.warning("Não consegui ler %s: %s", arquivo, erro)
        return None
