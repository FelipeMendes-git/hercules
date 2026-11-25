"""Cores e estilo da interface: "vidro claro" (painéis de vidro branco sobre um fundo vivo de cores suaves).

O fundo é desenhado pelo próprio app (``fundo.py``) e muda de cor junto com a bolha; os painéis por cima
são translúcidos, com borda clara e cantos bem arredondados.
"""

from __future__ import annotations

from ..eventos import Estado

CORES = {
    "fundo": "#eef0fa",
    "superficie": "#f7f7fd",
    "superficie2": "#ffffff",
    "superficie3": "#f0eefc",
    "borda": "#dcd9ef",
    "borda_viva": "#b9b2ec",
    "texto": "#1c1a2e",
    "suave": "#5f5a7a",
    "fraco": "#8a86a3",
    "acento": "#6d5cff",
    "acento_escuro": "#5443e0",
    "violeta": "#3f8cff",
    "verde": "#1fb57d",
    "verde_escuro": "#14875c",
    "ciano": "#0aa8c9",
    "azul": "#3f6fe0",
    "roxo": "#8a5cff",
    "vermelho": "#d92e4f",
    "laranja": "#d97a00",
    "cinza": "#8a86a3",
}

FONTE_MONO = '"Cascadia Mono", "Cascadia Code", Consolas, monospace'

# Texto e cor de cada estado ({nome} vira o nome de ativação; {detalhe}, o detalhe do estado). A cor é a mesma da bolha e do fundo vivo.
ESTADOS: dict[Estado, tuple[str, str]] = {
    Estado.CARREGANDO: ("Inicializando…", "#8a8fa8"),
    Estado.ESPERA: ("Cochilando · diga “{nome}”", "#8b7bff"),
    Estado.ACORDANDO: ("Acordando…", "#ff9f43"),
    Estado.OUVINDO: ("Na escuta · diga “{nome}”", "#2ee6a0"),
    Estado.CONVERSA: ("Pode falar", "#36e2c8"),
    Estado.GRAVANDO: ("Ouvindo você…", "#ff4f8b"),
    Estado.TRANSCREVENDO: ("Entendendo…", "#ff9f43"),
    Estado.RASCUNHO: ("Pode continuar · “{detalhe}” manda já", "#e05cff"),
    Estado.PENSANDO: ("Pensando…", "#4d8dff"),
    Estado.FALANDO: ("Falando…", "#ffb020"),
    Estado.APROVACAO: ("Esperando a sua permissão", "#ff8a00"),
    Estado.MUDO: ("Microfone desligado", "#8a8fa8"),
    Estado.SEM_MICROFONE: ("Sem microfone · tentando de novo", "#ff3d5a"),
    Estado.ERRO: ("Erro", "#ff3d5a"),
}
COR_TRABALHANDO = "#00d1ff"  # a bolha enquanto o Claude usa ferramentas (editando, rodando comandos...)

# Vidro: branco translúcido (alfa de 0 a 255), borda mais clara que o painel e sombra quase nenhuma.
_VIDRO = "rgba(255, 255, 255, 140)"
_VIDRO_FORTE = "rgba(255, 255, 255, 190)"
_VIDRO_BORDA = "rgba(255, 255, 255, 220)"
_LINHA = "rgba(90, 80, 160, 38)"

_ESTILO = """
QMainWindow { background: @fundo; }
QDialog { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f5f1ff, stop:0.5 #eef0fa, stop:1 #e8f2ff); }
QWidget { color: @texto; font-family: "Segoe UI"; font-size: 10pt; }

/* cabeçalho: um painel de vidro com a bolha, o nome, o estado e os botões */
QFrame#cabecalho { background: @vidro; border: 1px solid @vborda; border-radius: 22px; }
QLabel#marca { font-family: "Segoe UI Semibold", "Segoe UI"; font-size: 13.5pt; font-weight: 600; color: @texto; }
QLabel#versao { font-size: 8pt; color: @fraco; }
QLabel#estado { font-size: 9pt; font-weight: 600; }
QLabel#chip { background: @vidro; border: 1px solid @vborda; border-radius: 11px; padding: 3px 11px;
              color: @suave; font-size: 8.5pt; }
QToolButton#chip { background: @vidro; border: 1px solid @vborda; border-radius: 11px; padding: 3px 11px;
                   color: @suave; font-size: 8.5pt; }
QToolButton#chip:hover { background: @vforte; color: @texto; }
QToolButton#chip::menu-indicator { image: none; width: 0; }
QToolButton#icone, QToolButton#iconeMic { background: transparent; border: 1px solid transparent; border-radius: 17px;
                                          padding: 7px; }
QToolButton#icone:hover, QToolButton#iconeMic:hover { background: @vforte; border-color: @vborda; }
QToolButton#icone:pressed { background: @vborda; }
QToolButton#iconeMic:!checked { background: rgba(217, 46, 79, 30); }
QComboBox#projeto { background: @vidro; border: 1px solid @vborda; border-radius: 17px; padding: 7px 14px; font-weight: 600; }
QComboBox#projeto:hover { background: @vforte; }
QPushButton#fantasma { background: @vidro; border: 1px solid @vborda; border-radius: 17px; padding: 7px 14px; color: @texto; }
QPushButton#fantasma:hover { background: @vforte; }

/* conversa: a lista fica transparente para o fundo vivo aparecer */
QScrollArea { border: none; background: transparent; }
QWidget#lista { background: transparent; }
QFrame#bolhaUsuario { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6d5cff, stop:1 #3f8cff);
                      border: none; border-radius: 18px; border-bottom-right-radius: 6px; }
QLabel#textoUsuario { color: #ffffff; font-size: 10.5pt; }
QLabel#metaUsuario { color: rgba(255, 255, 255, 190); font-size: 8pt; }
QFrame#bolhaClaude { background: @vidro; border: 1px solid @vborda; border-radius: 18px; border-top-left-radius: 6px; }
QLabel#nomeAssistente { font-family: "Segoe UI Semibold", "Segoe UI"; font-size: 9.5pt; font-weight: 600; color: @texto; }
QFrame#atividade { background: rgba(255, 255, 255, 120); border: 1px solid @vborda; border-radius: 12px; }
QFrame#cartaoAprovacao { background: rgba(255, 240, 220, 210); border: 1px solid rgba(255, 138, 0, 150); border-radius: 20px; }
QFrame#cartaoAprovacao QLabel#autor { color: #c96a00; }
QFrame#cartao { background: @vidro; border: 1px solid @vborda; border-radius: 20px; }
QLabel#autor { color: @acento; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }
QLabel#acao { color: @suave; font-size: 9pt; }
QLabel#fala { color: #7a4a00; background: rgba(255, 214, 140, 90); border-left: 3px solid #ffb020;
              border-radius: 10px; padding: 7px 12px; font-style: italic; }
QLabel#meta { color: @fraco; font-size: 8.5pt; }
QLabel#aviso { color: @suave; font-size: 8.5pt; }
QLabel#avisoErro { color: @vermelho; font-size: 9pt; }
QLabel#tituloCartao { font-size: 11.5pt; font-weight: 600; color: @texto; }
QLabel#detalhe { background: rgba(255, 255, 255, 215); border: 1px solid @linha; border-radius: 10px; padding: 8px;
                 font-family: @mono; font-size: 9pt; color: #3b2f8a; }
QFrame#arquivo { background: @vforte; border: 1px solid @vborda; border-radius: 14px; }
QLabel#nomeArquivo { font-weight: 600; }
QTextBrowser#texto { background: transparent; border: none; selection-background-color: rgba(109, 92, 255, 70); }

/* rodapé: caixa de mensagem em pílula de vidro */
QFrame#rodape { background: transparent; border: none; }
QFrame#compositor { background: @vforte; border: 1px solid @vborda; border-radius: 24px; }
QLineEdit#entradaChat { background: transparent; border: none; padding: 8px 6px; font-size: 10.5pt; }
QPushButton#enviarRedondo { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6d5cff, stop:1 #3f8cff);
                            border: none; border-radius: 18px; padding: 0; }
QPushButton#enviarRedondo:hover { background: @acento; }
QPushButton#pararRedondo { background: rgba(217, 46, 79, 30); border: none; border-radius: 18px; padding: 0; }
QPushButton#pararRedondo:hover { background: rgba(217, 46, 79, 55); }
QLabel#suave { color: @suave; font-size: 8pt; }
QLabel#rotulo { color: @suave; font-size: 8.5pt; }

/* botões */
QPushButton, QToolButton { background: @vidro; border: 1px solid @vborda; border-radius: 14px; padding: 7px 15px; }
QPushButton:hover, QToolButton:hover { background: @vforte; }
QPushButton:pressed, QToolButton:pressed { background: @vborda; }
QPushButton:disabled, QToolButton:disabled { color: @fraco; background: rgba(255, 255, 255, 80); }
QPushButton#primario { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #6d5cff, stop:1 #3f8cff);
                       border: none; color: #ffffff; font-weight: 700; }
QPushButton#primario:hover { background: @acento; }
QPushButton#primario:disabled { background: rgba(109, 92, 255, 70); color: rgba(255, 255, 255, 200); }
QFrame#cartaoAprovacao QPushButton#primario { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffb347, stop:1 #ff7a1a);
                                              color: #3a1a00; }
QPushButton#perigo { background: rgba(217, 46, 79, 30); border: none; color: @vermelho; }
QPushButton#perigo:hover { background: rgba(217, 46, 79, 55); }
QPushButton#pequeno { padding: 4px 11px; font-size: 8.5pt; border-radius: 11px; }
QToolButton { padding: 4px 8px; font-size: 12pt; }

/* formulários e diálogos */
QListWidget { background: @vidro; border: 1px solid @vborda; border-radius: 16px; padding: 6px; outline: none; }
QListWidget::item { padding: 9px 8px; border-radius: 10px; margin: 1px 0; }
QListWidget::item:hover { background: @vforte; }
QListWidget::item:selected { background: rgba(109, 92, 255, 38); color: @texto; }
QSplitter::handle { background: transparent; width: 8px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
    background: @vforte; border: 1px solid @vborda; border-radius: 12px; padding: 6px 10px;
    selection-background-color: rgba(109, 92, 255, 70); selection-color: @texto; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: @acento; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox QAbstractItemView { background: #ffffff; border: 1px solid @borda; border-radius: 10px; padding: 4px;
                              selection-background-color: rgba(109, 92, 255, 38); selection-color: @texto; outline: none; }
QTabWidget::pane { background: @vidro; border: 1px solid @vborda; border-radius: 18px; top: -1px; }
QTabBar::tab { background: transparent; border: none; padding: 7px 14px; margin-right: 4px; color: @suave; border-radius: 12px; }
QTabBar::tab:selected { background: @vforte; color: @texto; }
QTabBar::tab:hover { color: @texto; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 3px; }
QScrollBar::handle:vertical { background: rgba(90, 80, 160, 60); border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: rgba(90, 80, 160, 110); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 9px; margin: 3px; }
QScrollBar::handle:horizontal { background: rgba(90, 80, 160, 60); border-radius: 4px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button { width: 16px; border: none; background: transparent; }
QAbstractSpinBox::up-arrow { image: none; width: 0; height: 0; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-bottom: 5px solid @suave; }
QAbstractSpinBox::down-arrow { image: none; width: 0; height: 0; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid @suave; }
QProgressBar { background: rgba(255, 255, 255, 150); border: none; border-radius: 4px; max-height: 8px; }
QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6d5cff, stop:1 #3f8cff); border-radius: 4px; }
QToolTip { background: #ffffff; color: @texto; border: 1px solid @borda; border-radius: 8px; padding: 5px 8px; }
QMenu { background: rgba(255, 255, 255, 245); border: 1px solid @borda; border-radius: 12px; padding: 6px; }
QMenu::item { padding: 7px 18px; border-radius: 8px; }
QMenu::item:selected { background: rgba(109, 92, 255, 32); color: @texto; }
QMenu::separator { height: 1px; background: @borda; margin: 4px 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid @borda_viva; border-radius: 6px; background: @vforte; }
QCheckBox::indicator:checked { background: @acento; border-color: @acento; }
"""


def _montar_estilo() -> str:
    texto = (
        _ESTILO.replace("@mono", FONTE_MONO)
        .replace("@vidro", _VIDRO)
        .replace("@vforte", _VIDRO_FORTE)
        .replace("@vborda", _VIDRO_BORDA)
        .replace("@linha", _LINHA)
    )
    for nome in sorted(CORES, key=len, reverse=True):  # "@superficie2" antes de "@superficie"
        texto = texto.replace(f"@{nome}", CORES[nome])
    return texto


ESTILO = _montar_estilo()


def estilo_completo() -> str:
    """O estilo mais as setinhas das listas e dos campos de número, desenhadas na hora (precisa do app Qt).

    O Qt não desenha setas com o truque de bordas do CSS; com imagens, elas aparecem certinhas.
    """
    import tempfile
    from pathlib import Path

    try:
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

        pasta = Path(tempfile.gettempdir()) / "hercules-tema"
        pasta.mkdir(parents=True, exist_ok=True)

        def seta(nome: str, pontos: tuple[tuple[float, float], ...], cor: str = CORES["suave"], lado: int = 24) -> str:
            imagem = QImage(lado, lado, QImage.Format.Format_ARGB32)
            imagem.fill(Qt.GlobalColor.transparent)
            pintor = QPainter(imagem)
            pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
            caneta = QPen(QColor(cor), 2.4 * lado / 24)
            caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
            caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pintor.setPen(caneta)
            caminho = QPainterPath(QPointF(*pontos[0]))
            for ponto in pontos[1:]:
                caminho.lineTo(QPointF(*ponto))
            pintor.drawPath(caminho)
            pintor.end()
            arquivo = pasta / f"{nome}.png"
            imagem.save(str(arquivo))
            return arquivo.as_posix()

        baixo = seta("baixo", ((6, 9), (12, 15), (18, 9)))
        cima = seta("cima", ((6, 15), (12, 9), (18, 15)))
        marca = seta("marca", ((4, 8.5), (7, 11.5), (12.5, 4.5)), "#ffffff", 16)
    except Exception:
        return ESTILO
    return ESTILO + f"""
QComboBox::down-arrow {{ image: url({baixo}); width: 12px; height: 12px; border: none; margin-right: 8px; }}
QAbstractSpinBox::down-arrow {{ image: url({baixo}); width: 10px; height: 10px; border: none; }}
QAbstractSpinBox::up-arrow {{ image: url({cima}); width: 10px; height: 10px; border: none; }}
QCheckBox::indicator:checked {{ image: url({marca}); }}
"""
