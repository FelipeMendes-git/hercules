from assistente_local import config


def test_salva_e_le_de_volta(tmp_path):
    cfg = config.Config()
    cfg.ativacao.nome = "Teste"
    cfg.projetos.lista.append(config.Projeto("x", "C:/x", ["xis"]))
    cfg.reconhecimento.pastas_cuda = ["C:/cuda"]
    caminho = tmp_path / "config.toml"
    config.salvar(cfg, caminho)
    assert config.carregar(caminho) == cfg


def test_valor_invalido_usa_o_padrao(tmp_path):
    caminho = tmp_path / "config.toml"
    caminho.write_text('[audio]\nsilencio_fim_ms = "muito"\n[ativacao]\nnome = "Zé"\n', encoding="utf-8")
    lido = config.carregar(caminho)
    assert lido.audio.silencio_fim_ms == config.Audio().silencio_fim_ms
    assert lido.ativacao.nome == "Zé"


def test_saudacao_de_versao_antiga_ganha_as_frases_novas(tmp_path):
    caminho = tmp_path / "config.toml"
    antigo = {
        "abertura": "{periodo}, {tratamento}!",
        "frases_chamado": config._PADROES_ANTIGOS["frases_chamado"][0],
        "frases_pedido": ["Minha frase."],  # personalizada: fica
    }
    caminho.write_text(config.tomli_w.dumps({"saudacao": antigo}), encoding="utf-8")
    lido = config.carregar(caminho).saudacao
    novo = config.Saudacao()
    assert lido.aberturas == novo.aberturas  # a abertura antiga era a padrão
    assert lido.frases_chamado == novo.frases_chamado  # nunca mexeu: recebe as novas
    assert lido.frases_pedido == ["Minha frase."]

    caminho.write_text('[saudacao]\nabertura = "Fala, chefia!"\n', encoding="utf-8")
    lido = config.carregar(caminho).saudacao
    assert lido.aberturas[0] == "Fala, chefia!" and len(lido.aberturas) == len(novo.aberturas) + 1


def test_frases_informais_que_eram_o_padrao_viram_as_formais(tmp_path):
    caminho = tmp_path / "config.toml"
    antigo = {campo: versoes[-1] for campo, versoes in config._PADROES_ANTIGOS.items()}
    caminho.write_text(config.tomli_w.dumps({"saudacao": antigo}), encoding="utf-8")
    lido = config.carregar(caminho).saudacao
    novo = config.Saudacao()
    for campo in config._PADROES_ANTIGOS:
        assert getattr(lido, campo) == getattr(novo, campo), campo
    assert novo.estilo == "nenhuma"  # por padrão, a saudação vem sem música


def test_descobre_projetos_nas_pastas_raiz(tmp_path):
    for nome in ("a", "b", ".oculto"):
        (tmp_path / nome).mkdir()
    cfg = config.Config()
    cfg.projetos.pastas_raiz = [str(tmp_path)]
    cfg.projetos.ignorar = ["b"]
    assert [p.nome for p in config.projetos_disponiveis(cfg)] == ["a"]
