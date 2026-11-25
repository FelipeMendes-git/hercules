"""Decide se uma fala é para o assistente.

Tudo aqui é determinístico (regras e comparação de texto). O app não interpreta os seus
pedidos: ele só reconhece o nome do assistente, a palavra de parar ("jabuticabal", que
interrompe na hora), a de mandar ("câmbio", que envia o pedido sem esperar o silêncio), o
"cancela" que descarta um pedido ainda não enviado e o "sim" ou "não" das permissões. Depois do nome, o pedido vai do
jeito que você falou para o Claude, que também controla o app pelas ferramentas dele.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable, Sequence


def normalizar(texto: str) -> str:
    """Minúsculas, sem acentos e só letras, números e espaços simples."""
    decomposto = unicodedata.normalize("NFKD", (texto or "").lower())
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", sem_acento).strip()


def similaridade(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


_PALAVRA = re.compile(r"\w+", re.UNICODE)
_SAUDACOES = frozenset(
    {"oi", "ola", "ei", "eii", "hey", "ok", "okay", "fala", "alo", "e", "ai", "eai", "o", "opa", "psiu",
     "bom", "dia", "boa", "tarde", "noite"}
)
_PONTUACAO = " ,.;:!?-–—\"'"


@dataclass(frozen=True)
class Deteccao:
    ativado: bool
    comando: str = ""
    posicao: str = ""  # "inicio" ou "fim" quando ativado


class DetectorNome:
    """Reconhece o nome do assistente no começo (ou no fim) de uma frase transcrita."""

    def __init__(self, nome: str, apelidos: Iterable[str] = (), minimo: float = 0.8, max_saudacoes: int = 3):
        variantes = [normalizar(n) for n in (nome, *apelidos)]
        self.variantes: list[list[str]] = [v.split() for v in dict.fromkeys(v for v in variantes if v)]
        self.minimo = minimo
        self.max_saudacoes = max_saudacoes

    def _pontuar(self, tokens: Sequence[str], variante: list[str]) -> float:
        if not tokens:
            return 0.0
        junto = similaridade("".join(tokens), "".join(variante))
        if len(tokens) == len(variante):
            return max(similaridade(" ".join(tokens), " ".join(variante)), junto)
        # O reconhecimento juntou ou separou palavras: só aceita se ficar bem parecido.
        return junto if junto >= max(self.minimo, 0.88) else 0.0

    def _casar_inicio(self, tokens: Sequence[str]) -> int:
        """Quantas palavras do começo de ``tokens`` formam o nome (0 = não é o nome)."""
        melhor_n, melhor = 0, 0.0
        for variante in self.variantes:
            k = len(variante)
            for n in (k, k + 1, k - 1):
                if n < 1 or n > len(tokens):
                    continue
                nota = self._pontuar(tokens[:n], variante)
                if nota >= self.minimo and nota > melhor + 1e-9:
                    melhor_n, melhor = n, nota
        return melhor_n

    def eh_nome(self, tokens: Sequence[str]) -> bool:
        return any(self._pontuar(tokens, v) >= self.minimo for v in self.variantes)

    def detectar(self, texto: str) -> Deteccao:
        if not self.variantes or not texto:
            return Deteccao(False)
        palavras = [m for m in _PALAVRA.finditer(texto) if normalizar(m.group())]
        if not palavras:
            return Deteccao(False)
        norm = [normalizar(m.group()) for m in palavras]
        # Nome no começo, depois de até `max_saudacoes` palavras como "oi", "ei", "e aí".
        for i in range(0, min(self.max_saudacoes, len(norm) - 1) + 1):
            if i > 0 and norm[i - 1] not in _SAUDACOES:
                break
            n = self._casar_inicio(norm[i:])
            if n:
                fim = palavras[i + n - 1].end()
                return Deteccao(True, texto[fim:].lstrip(_PONTUACAO).rstrip(), "inicio")
        # Nome no fim: "abre o arquivo de configuração, Hércules."
        for n in (1, 2, 3):
            if n >= len(norm):
                break
            if self.eh_nome(norm[-n:]):
                inicio = palavras[-n].start()
                return Deteccao(True, texto[:inicio].strip(_PONTUACAO), "fim")
        return Deteccao(False)


_ENCHIMENTO = frozenset({"por", "favor", "oi", "ei", "o", "e", "ai", "ok", "okay", "ja", "agora"})


class DetectorParada:
    """Reconhece a palavra que interrompe tudo na hora (por padrão, "jabuticabal").

    Vale com ou sem o nome do assistente, mas só quando a frase é praticamente só essa
    palavra: "procura um restaurante em Jaboticabal" é um pedido e segue para o Claude.
    O Claude não consegue se interromper sozinho; por isso essa é a única ordem do app.
    """

    def __init__(self, palavra: str, detector_nome: DetectorNome | None = None, minimo: float = 0.78):
        self.alvo = normalizar(palavra).replace(" ", "")
        self.detector_nome = detector_nome
        self.minimo = minimo

    def eh_parada(self, texto: str) -> bool:
        if not self.alvo or not texto:
            return False
        if self.detector_nome is not None:
            deteccao = self.detector_nome.detectar(texto)
            if deteccao.ativado:
                texto = deteccao.comando
        restantes = [t for t in normalizar(texto).split() if t not in _ENCHIMENTO]
        if not restantes or len(restantes) > 3:
            return False
        if similaridade("".join(restantes), self.alvo) >= self.minimo:  # "jabuti cabal", "ja boticabal"
            return True
        return all(similaridade(t, self.alvo) >= self.minimo for t in restantes)  # "jabuticabal, jabuticabal"


# Antes delas, "câmbio" é o substantivo ("como está o câmbio"), não a palavra de envio.
_ANTES_DE_SUBSTANTIVO = frozenset(
    {"o", "do", "no", "ao", "pelo", "um", "seu", "meu", "nosso", "esse", "este", "aquele", "de", "em", "sobre", "qual"}
)


class DetectorEnvio:
    """Reconhece a palavra de envio (por padrão, "câmbio") no fim da frase: o pedido vai na hora.

    Só vale no fim, como no rádio: "cria uma função que soma dois números, câmbio". Depois de um artigo
    ou preposição ela é o substantivo ("me diz como está o câmbio") e o texto fica como está.
    """

    def __init__(self, palavra: str, minimo: float = 0.8):
        self.alvo = normalizar(palavra).replace(" ", "")
        self.minimo = minimo

    def _eh_alvo(self, palavra: str) -> bool:
        return bool(self.alvo) and similaridade(normalizar(palavra), self.alvo) >= self.minimo

    def separar(self, texto: str) -> tuple[str, bool]:
        """Devolve o texto sem a palavra de envio do fim e se ela estava lá."""
        texto = (texto or "").strip()
        palavras = [m for m in _PALAVRA.finditer(texto) if normalizar(m.group())]
        corte = len(palavras)
        while corte > 0 and self._eh_alvo(palavras[corte - 1].group()):  # "câmbio, câmbio"
            corte -= 1
        if corte == len(palavras):
            return texto, False
        if corte > 0 and normalizar(palavras[corte - 1].group()) in _ANTES_DE_SUBSTANTIVO:
            return texto, False
        resto = texto[: palavras[corte].start()] if corte < len(palavras) else texto
        return resto.rstrip(_PONTUACAO), True


_CANCELAR = frozenset(
    {"cancela", "cancelar", "cancele", "cancela isso", "cancela tudo", "esquece", "esqueca", "esquece isso",
     "esqueca isso", "esquece tudo", "deixa pra la", "deixa para la", "deixa quieto", "deixa"}
)


def eh_cancelamento(texto: str) -> bool:
    """True se a frase inteira é só um "cancela" / "esquece": descarta o pedido que ainda não foi."""
    restantes = [t for t in normalizar(texto).split() if t not in _ENCHIMENTO]
    return " ".join(restantes) in _CANCELAR


_PALAVRAS_VAZIAS = frozenset({"o", "a", "os", "as", "do", "da", "dos", "das", "de", "chamado", "chamada", "que", "se", "chama"})


def achar_projeto(nome: str, projetos: Sequence[Any], minimo: float = 0.72) -> Any | None:
    """Projeto cujo nome (ou apelido) mais se parece com o que foi falado."""
    tokens = [t for t in normalizar(nome).split() if t not in _PALAVRAS_VAZIAS]
    if not tokens:
        return None
    alvo, alvo_junto = " ".join(tokens), "".join(tokens)
    melhor, melhor_nota = None, 0.0
    for projeto in projetos:
        for rotulo in (projeto.nome, *getattr(projeto, "apelidos", ())):
            normal = normalizar(rotulo)
            nota = max(similaridade(alvo, normal), similaridade(alvo_junto, normal.replace(" ", "")))
            if nota > melhor_nota:
                melhor, melhor_nota = projeto, nota
    return melhor if melhor_nota >= minimo else None


_SIM = frozenset(
    {"sim", "pode", "claro", "ok", "okay", "manda", "vai", "autorizo", "autorizado", "aprovado", "aprova", "aprovo",
     "confirmo", "confirma", "confirmado", "positivo", "isso", "beleza", "fechou", "certo", "faz", "faca",
     "pode fazer", "pode ir", "pode sim", "manda ver", "vai la", "segue", "pode seguir", "permitido", "permito",
     "com certeza", "uhum", "aham"}
)
_NAO = frozenset(
    {"nao", "nega", "negado", "nego", "recusa", "recusado", "recuso", "cancela", "cancelar", "para", "pare",
     "espera", "aguarda", "negativo", "jamais", "nunca", "deixa"}
)
_NAO_FRASES = ("nem pensar", "de jeito nenhum", "melhor nao", "agora nao")


def interpretar_resposta(texto: str) -> bool | None:
    """Sim (True), não (False) ou não deu para entender (None)."""
    normal = normalizar(texto)
    if not normal:
        return None
    palavras = normal.split()
    duas = " ".join(palavras[:2])
    if "nao" in palavras[:3] or any(f in normal for f in _NAO_FRASES):
        return False
    if palavras[0] in _NAO or duas in _NAO:
        return False
    if palavras[0] in _SIM or duas in _SIM:
        return True
    if len(palavras) <= 4 and any(p in _SIM for p in palavras):
        return True
    return None


def parece_eco(ouvido: str, falado: str, minimo: float = 0.6) -> bool:
    """True se o que o microfone ouviu é, provavelmente, a própria voz do assistente."""
    palavras_ouvidas = normalizar(ouvido).split()
    palavras_faladas = set(normalizar(falado).split())
    if not palavras_ouvidas or not palavras_faladas:
        return False
    em_comum = sum(1 for p in palavras_ouvidas if p in palavras_faladas)
    return em_comum / len(palavras_ouvidas) >= minimo
