from assistente_local import eventos as ev
from assistente_local.historico import Historico


def _conversa(historico: Historico) -> None:
    historico.registrar_evento(ev.FalaUsuario("cria um PDF com o relatório"))
    historico.registrar_evento(ev.InicioResposta())
    historico.registrar_evento(ev.AcaoClaude("Escrevendo C:/x/relatorio.pdf", "Write"))
    historico.registrar_evento(ev.TextoClaude("Criei o arquivo `C:/x/relatorio.pdf`."))
    historico.registrar_evento(ev.FimResposta("Criei o relatório.", 3.2, 0.01, arquivos=["C:/x/relatorio.pdf"]))


def test_grava_e_retoma_pela_sessao(tmp_path):
    historico = Historico(tmp_path)
    assert historico.abrir("projeto", "C:/projeto", None) == []
    _conversa(historico)
    historico.associar_sessao("sessao-1")

    outro = Historico(tmp_path)  # como se o app tivesse sido reaberto
    entradas = outro.abrir("projeto", "C:/projeto", "sessao-1")
    tipos = [e["tipo"] for e in entradas]
    assert tipos == ["voce", "inicio_resposta", "acao", "claude", "fim"]
    assert entradas[-1]["arquivos"] == ["C:/x/relatorio.pdf"]


def test_conversa_nova_vai_para_outro_arquivo(tmp_path):
    historico = Historico(tmp_path)
    historico.abrir("projeto", "C:/projeto", None)
    _conversa(historico)
    primeiro = historico.arquivo_atual
    historico.abrir("projeto", "C:/projeto", None)
    assert historico.arquivo_atual is None  # só cria o arquivo na primeira mensagem
    historico.registrar_evento(ev.FalaUsuario("outra coisa"))
    assert historico.arquivo_atual != primeiro
    assert len(historico.listar()) == 2


def test_nada_e_gravado_sem_mensagens(tmp_path):
    historico = Historico(tmp_path)
    historico.abrir("projeto", "C:/projeto", None)
    historico.registrar_evento(ev.NivelMicrofone(0.5, False))
    assert historico.listar() == []


def test_exporta_markdown(tmp_path):
    historico = Historico(tmp_path)
    historico.abrir("projeto", "C:/projeto", None)
    _conversa(historico)
    texto = historico.exportar_markdown(historico.arquivo_atual)
    assert "**Você:** cria um PDF com o relatório" in texto
    assert "`C:/x/relatorio.pdf`" in texto
    assert "🔊 *Criei o relatório.*" in texto
    resumo = historico.listar()[0]
    assert resumo.titulo == "cria um PDF com o relatório"
    assert resumo.projeto == "projeto"
