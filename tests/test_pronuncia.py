from assistente_local import texto_fala
from assistente_local.pronuncia import PADRAO, Pronuncia


def test_troca_termos_e_siglas_mantendo_o_resto():
    p = Pronuncia()
    assert p.aplicar("Fiz o commit e abri o pull request no GitHub.") == (
        "Fiz o comíti e abri o pul ríquest no guíti rábi."
    )
    assert p.aplicar("A API devolveu um JSON.") == "A a pê i devolveu um jêisson."


def test_plural_sai_sozinho_sem_pegar_palavras_em_portugues():
    p = Pronuncia()
    assert p.aplicar("Dois commits, três bugs e as branches.") == "Dois comítis, três báguis e as bréntchis."
    assert p.aplicar("Os testes passaram.") == "Os testes passaram."  # "es" só depois de ch/sh/x/s


def test_siglas_so_em_maiusculas():
    p = Pronuncia()
    assert p.aplicar("Ele ia usar IA.") == "Ele ia usar i á."
    assert p.aplicar("os PRs") == "os pê érres"


def test_palavra_inteira_so():
    p = Pronuncia()
    assert p.aplicar("bugado, logística, sitezinho") == "bugado, logística, sitezinho"


def test_seu_dicionario_completa_corrige_e_desliga(tmp_path):
    arquivo = tmp_path / "pronuncia.toml"
    arquivo.write_text('[termos]\nKubectl = "cube contrôl"\nsite = ""\ndeploy = "dêplói"\n', encoding="utf-8")
    p = Pronuncia(caminho=arquivo)
    assert p.aplicar("kubectl no site, deploy feito") == "cube contrôl no site, dêplói feito"
    arquivo.write_text('[termos]\n"Hércules" = "Érculis"\n', encoding="utf-8")
    import os

    os.utime(arquivo, (1, 1))  # mudou: relê sozinho
    assert p.aplicar("Hércules, o site") == "Érculis, o sáiti"


def test_arquivo_quebrado_nao_derruba_a_voz(tmp_path):
    arquivo = tmp_path / "pronuncia.toml"
    arquivo.write_text("isso não é toml [[[", encoding="utf-8")
    assert Pronuncia(caminho=arquivo).aplicar("o deploy") == "o diplói"


def test_dicionario_padrao_sem_chaves_repetidas_nem_vazias():
    assert all(t.strip() and v.strip() for t, v in PADRAO.items())
    minusculas = [t.lower() for t in PADRAO if t != t.upper()]
    assert len(minusculas) == len(set(minusculas))


def test_agrupa_frases_curtas_para_a_voz_nao_travar():
    frases = ["Pronto.", "Fiz o que você pediu.", ("Agora vem uma frase bem mais longa " * 6).strip()]
    grupos = texto_fala.agrupar_frases(frases)
    assert grupos[0] == "Pronto. Fiz o que você pediu."
    assert len(grupos) == 2
    assert texto_fala.agrupar_frases(["a" * 200, "b" * 50]) == ["a" * 200, "b" * 50]  # não passa do máximo
