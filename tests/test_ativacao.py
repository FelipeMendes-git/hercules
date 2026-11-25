import pytest

from assistente_local.ativacao import (
    DetectorNome,
    DetectorParada,
    achar_projeto,
    interpretar_resposta,
    parece_eco,
)
from assistente_local.config import Projeto


@pytest.fixture
def detector():
    return DetectorNome("Assistente", ["assistant"])


@pytest.mark.parametrize(
    "texto, comando",
    [
        ("Assistente, cria um arquivo chamado teste.txt.", "cria um arquivo chamado teste.txt."),
        ("Oi assistente, abre o projeto educai", "abre o projeto educai"),
        ("Olá, Assistente! Tudo bem?", "Tudo bem?"),
        ("E aí, assistente, como vai?", "como vai?"),
        ("Assis tente, roda os testes", "roda os testes"),
        ("Assistant, roda os testes", "roda os testes"),
        ("Abre o arquivo de configuração, assistente.", "Abre o arquivo de configuração"),
    ],
)
def test_detecta_nome_e_separa_o_pedido(detector, texto, comando):
    deteccao = detector.detectar(texto)
    assert deteccao.ativado
    assert deteccao.comando == comando


@pytest.mark.parametrize(
    "texto, comando",
    [  # o que o Whisper escreveu nos testes com voz sintética
        ("Hércules, abre o projeto do site.", "abre o projeto do site."),
        ("E aí, Hércules, tudo certo.", "tudo certo."),
        ("Ercules, que horas são?", "que horas são?"),  # o H não se pronuncia
        ("Cria um arquivo de teste Hercules.", "Cria um arquivo de teste"),
        ("Hércules.", ""),
    ],
)
def test_nome_hercules(texto, comando):
    deteccao = DetectorNome("Hércules").detectar(texto)
    assert deteccao.ativado and deteccao.comando == comando


@pytest.mark.parametrize("texto", ["Os 12 trabalhos de Hercules são famosos.", "É colisão de carros.", "Era uma vez."])
def test_hercules_no_meio_da_frase_nao_chama(texto):
    assert not DetectorNome("Hércules").detectar(texto).ativado


def test_modelo_leve_aceita_o_nome_grudado():
    assert DetectorNome("Hércules", minimo=0.72).detectar("Oiércules, abri o projeto do site.").ativado


@pytest.mark.parametrize("texto", ["Oi assistente", "Assistente.", "Ei, Assistente!"])
def test_so_chamou_o_nome(detector, texto):
    deteccao = detector.detectar(texto)
    assert deteccao.ativado
    assert deteccao.comando == ""


@pytest.mark.parametrize(
    "texto",
    [
        "Hoje eu fui ao mercado comprar pão.",
        "A assistência técnica ligou de novo.",
        "Assistência técnica, boa tarde.",
        "",
        "Liga para a minha mãe",
    ],
)
def test_ignora_conversa_comum(detector, texto):
    assert not detector.detectar(texto).ativado


def test_nome_novo_funciona_sem_codigo():
    detector = DetectorNome("Sexta-feira")
    assert detector.detectar("Sexta feira, abre o terminal").comando == "abre o terminal"


@pytest.mark.parametrize(
    "texto, para",
    [
        ("Jabuticabal!", True),
        ("Jaboticabal.", True),  # grafia da cidade, que o reconhecimento costuma usar
        ("Assistente, jabuticabal!", True),
        ("jabuticabal, por favor", True),
        ("Jabuti cabal", True),  # o reconhecimento separou a palavra
        ("jabuticabal jabuticabal", True),
        ("Procura um restaurante em Jaboticabal", False),  # é um pedido: vai para o Claude
        ("Assistente, para", False),  # "para" não interrompe mais: é comum demais
        ("cancela", False),
        ("", False),
    ],
)
def test_palavra_de_parar(detector, texto, para):
    assert DetectorParada("jabuticabal", detector).eh_parada(texto) is para


def test_acha_projeto_pelo_nome_falado():
    projetos = [
        Projeto("educai", "C:/dev/educai"),
        Projeto("Botechquim", "C:/dev/Botechquim"),
        Projeto("assistenteLocal", "C:/dev/assistenteLocal"),
        Projeto("felipemendesdev", "C:/dev/felipemendesdev"),
    ]
    assert achar_projeto("educai", projetos).nome == "educai"
    assert achar_projeto("edu ai", projetos).nome == "educai"
    assert achar_projeto("boteco quim", projetos).nome == "Botechquim"
    assert achar_projeto("do assistente local", projetos).nome == "assistenteLocal"
    assert achar_projeto("banana", projetos) is None


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("Sim.", True),
        ("pode", True),
        ("Pode rodar.", True),
        ("Claro, manda ver!", True),
        ("Não.", False),
        ("não pode", False),
        ("Espera um pouco.", False),
        ("sim, mas não agora", False),
        ("hoje está calor", None),
        ("", None),
    ],
)
def test_resposta_sim_ou_nao(texto, esperado):
    assert interpretar_resposta(texto) is esperado


def test_reconhece_eco_da_propria_voz():
    assert parece_eco("criei o arquivo teste", "Criei o arquivo teste.txt na pasta do projeto.")
    assert not parece_eco("assistente para", "Criei o arquivo teste na pasta.")
