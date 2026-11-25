import pytest

from assistente_local.midia import interpretar_midia


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("Próxima música.", ("proxima", 1)),
        ("Pula essa música, por favor", ("proxima", 1)),
        ("Pode passar pra próxima música", ("proxima", 1)),
        ("Toca a próxima música", ("proxima", 1)),
        ("Volta a música", ("anterior", 1)),
        ("Música anterior", ("anterior", 1)),
        ("Pausa a música", ("pausar", 1)),
        ("Para a música", ("pausar", 1)),
        ("Continua a música", ("tocar", 1)),
        ("Volta a tocar", ("tocar", 1)),
        ("Aumenta o volume", ("aumentar", 5)),
        ("Aumenta muito o volume", ("aumentar", 10)),
        ("Abaixa o volume um pouco", ("diminuir", 2)),
        ("Volume para baixo", ("diminuir", 5)),
        ("Abaixa a música", ("diminuir", 5)),
    ],
)
def test_reconhece_comandos(texto, esperado):
    assert interpretar_midia(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    ["Para de falar", "O volume da reunião estava alto", "Volta para o projeto anterior", "Pula essa parte",
     "Aumenta a fonte", "Toca", "Para", "Pode fazer", "Me explica o que é essa música"],
)
def test_conversa_nao_vira_comando(texto):
    assert interpretar_midia(texto) is None
