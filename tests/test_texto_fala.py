from assistente_local.ponte_claude import chave_permissao
from assistente_local.texto_fala import (
    descrever_ferramenta,
    descrever_pedido,
    dividir_frases,
    encontrar_caminhos,
    extrair_fala,
    limpar_para_fala,
    resumo_falavel,
)


def test_encontra_caminhos_que_existem(tmp_path):
    pdf = tmp_path / "Meu Relatório.pdf"
    pdf.write_bytes(b"%PDF")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print()", encoding="utf-8")
    texto = (
        f"Salvei em `{pdf}` e alterei `src/app.py`. Também vi {tmp_path}\\naoexiste.txt "
        "e rodei `npm install`."
    )
    achados = encontrar_caminhos(texto, base=str(tmp_path))
    assert str(pdf.resolve()) in achados
    assert str((tmp_path / "src" / "app.py").resolve()) in achados
    assert len(achados) == 2


def test_extrai_a_linha_de_fala():
    texto = (
        "Alterei o arquivo `app.py`:\n\n```python\nprint('oi')\n```\n\n"
        "<falar>Pronto, alterei o arquivo app.py.</falar>"
    )
    fala, visivel = extrair_fala(texto)
    assert fala == "Pronto, alterei o arquivo app.py."
    assert "<falar>" not in visivel
    assert "print('oi')" in visivel


def test_sem_linha_de_fala():
    assert extrair_fala("Só texto.") == ("", "Só texto.")


def test_limpa_markdown_para_voz():
    texto = limpar_para_fala(
        "## Resumo\n- Criei **dois** arquivos em `src/app.py` e C:\\dev\\x\\config.toml\n"
        "- Veja https://exemplo.com\n\n| a | b |\n|---|---|\n| 1 | 2 |"
    )
    for proibido in ("#", "**", "|", "https", "src/"):
        assert proibido not in texto
    assert "app.py" in texto
    assert "config.toml" in texto
    assert "um link" in texto


def test_mantem_barras_do_portugues():
    assert "e/ou" in limpar_para_fala("Use um e/ou outro.")


def test_divide_em_frases_curtas():
    assert dividir_frases("Primeira frase. Segunda frase! Terceira?") == [
        "Primeira frase.",
        "Segunda frase!",
        "Terceira?",
    ]
    assert all(len(f) <= 220 for f in dividir_frases("palavra " * 80))


def test_resumo_quando_falta_a_linha_de_fala():
    resumo = resumo_falavel("Fiz três coisas. Primeiro isso. Depois aquilo. Por fim outra.")
    assert resumo.startswith("Fiz três coisas. Primeiro isso.")
    assert resumo.endswith("Os detalhes estão na tela.")


def test_descreve_acoes_e_pedidos():
    assert descrever_ferramenta("Edit", {"file_path": "C:\\dev\\x\\main.py"})[0] == "Editando main.py."
    assert descrever_pedido("Bash", {"command": "npm install"})[0] == "rodar o comando npm install"
    complicado = descrever_pedido("Bash", {"command": "rm -rf build && npm run build | tee log.txt"})
    assert complicado[0] == "rodar um comando no terminal"
    assert complicado[1].startswith("rm -rf build")


def test_comandos_do_powershell():  # no Windows o Claude Code roda comandos pelo PowerShell
    assert descrever_pedido("PowerShell", {"command": "git init"})[0] == "rodar o comando git init"
    assert descrever_ferramenta("PowerShell", {"command": "git status"})[1] == "Rodando: git status"
    assert chave_permissao("PowerShell", {"command": "git init"}) == "PowerShell:git"
    assert descrever_ferramenta("ToolSearch", {"query": "select:mcp__app__desfazer"})[1] == "Buscando a ferramenta certa"
