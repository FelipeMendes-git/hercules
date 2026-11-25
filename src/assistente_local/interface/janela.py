"""Janela principal e ícone na bandeja do Windows."""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QActionGroup, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import config as cfgmod
from .. import eventos as ev
from ..marca import NOME_APP
from . import acoes, icones
from .conversa import (
    BlocoResposta,
    BolhaUsuario,
    CartaoAprovacao,
    CartaoCarregando,
    CartaoInfo,
    CartaoLogin,
    LinhaAviso,
    ListaConversa,
    PainelEspera,
    renderizar_entradas,
)
from .fundo import FundoVivo
from .janela_compacta import JanelaCompacta
from .orbe import Orbe
from .tema import CORES, ESTADOS


def _mesmo_caminho(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


class JanelaPrincipal(QMainWindow):
    def __init__(self, cfg: cfgmod.Config, controlador) -> None:
        super().__init__()
        self.cfg = cfg
        self.controlador = controlador
        self._bloco: BlocoResposta | None = None
        self._cartoes: dict[str, CartaoAprovacao] = {}
        self._cartao_login: CartaoLogin | None = None
        self._estado = ev.Estado.CARREGANDO
        self._info_base = ""
        self._avisou_bandeja = False
        self._saindo = False
        self.setWindowTitle(NOME_APP)
        self.setWindowIcon(icones.icone_app())
        self.resize(560, 800)
        self.setMinimumSize(420, 520)
        if cfg.interface.sempre_no_topo:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._montar()
        self._menu = self._criar_menu()
        self._bandeja = self._criar_bandeja()
        self._compacta = JanelaCompacta(
            self._menu,
            self._ao_clicar_compacta,
            cfg.ativacao.nome,
            fonte_voz=controlador.nivel_da_voz,
            no_topo=cfg.interface.bolinha_no_topo,
        )
        self._preencher_projetos()
        self._carregando: CartaoCarregando | None = self._lista.adicionar(CartaoCarregando())
        self._timer_info = QTimer(self)
        self._timer_info.setSingleShot(True)
        self._timer_info.timeout.connect(self._info.hide)
        self._pintar_estado(ev.Estado.CARREGANDO, "")

    @property
    def tem_bandeja(self) -> bool:
        return self._bandeja is not None

    # ------------------------------------------------------------------ montagem
    def _montar(self) -> None:
        # O fundo vivo (cores suaves que seguem a bolha) fica atrás; os painéis de vidro, por cima.
        central = FundoVivo()
        self._fundo = central
        coluna = QVBoxLayout(central)
        coluna.setContentsMargins(12, 12, 12, 10)
        coluna.setSpacing(10)

        # cabeçalho: painel de vidro com a bolha, o nome e o estado; à direita, botões de ícone
        cabecalho = QFrame()
        cabecalho.setObjectName("cabecalho")
        topo = QHBoxLayout(cabecalho)
        topo.setContentsMargins(8, 6, 10, 6)
        topo.setSpacing(10)
        self._orbe = Orbe(58)
        self._orbe.definir_fonte_voz(self.controlador.nivel_da_voz)
        central.definir_fonte_trabalhando(lambda: self._orbe.trabalhando)
        identidade = QVBoxLayout()
        identidade.setSpacing(0)
        marca = QLabel(NOME_APP)
        marca.setObjectName("marca")
        self._rotulo_estado = QLabel("Inicializando…")
        self._rotulo_estado.setObjectName("estado")
        identidade.addStretch(1)
        identidade.addWidget(marca)
        identidade.addWidget(self._rotulo_estado)
        identidade.addStretch(1)
        self._botao_mic = self._botao_icone("mic", "Microfone ligado (Ctrl+M desliga)", "iconeMic")
        self._botao_mic.setCheckable(True)
        self._botao_mic.setChecked(True)
        self._botao_compacto = self._botao_icone("recolher", "Recolher para a bolinha flutuante")
        self._botao_historico = self._botao_icone("historico", "Conversas salvas")
        self._botao_config = self._botao_icone("config", "Configurações")
        topo.addWidget(self._orbe)
        topo.addLayout(identidade, 1)
        for botao in (self._botao_mic, self._botao_compacto, self._botao_historico, self._botao_config):
            topo.addWidget(botao)
        # projeto e "Nova conversa", em pílulas de vidro
        baixo = QHBoxLayout()
        baixo.setSpacing(8)
        self._combo = QComboBox()
        self._combo.setObjectName("projeto")
        self._combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._combo.setToolTip("Projeto: a pasta em que o Claude trabalha")
        self._botao_nova = QPushButton(" Nova conversa")
        self._botao_nova.setObjectName("fantasma")
        self._botao_nova.setIcon(icones.icone_linha("mais", CORES["suave"]))
        baixo.addWidget(self._combo, 1)
        baixo.addWidget(self._botao_nova)

        self._lista = ListaConversa()

        # rodapé: caixa de mensagem em pílula, com o botão redondo de enviar (ou parar)
        rodape = QFrame()
        rodape.setObjectName("rodape")
        coluna_rodape = QVBoxLayout(rodape)
        coluna_rodape.setContentsMargins(0, 0, 0, 0)
        coluna_rodape.setSpacing(7)
        compositor = QFrame()
        compositor.setObjectName("compositor")
        entrada = QHBoxLayout(compositor)
        entrada.setContentsMargins(14, 5, 5, 5)
        entrada.setSpacing(6)
        self._entrada = QLineEdit()
        self._entrada.setObjectName("entradaChat")
        self._entrada.setPlaceholderText(f"Fale “{self.cfg.ativacao.nome}” ou escreva aqui…")
        self._botao_parar = QPushButton()
        self._botao_parar.setObjectName("pararRedondo")
        self._botao_parar.setIcon(icones.icone_linha("parar", CORES["vermelho"]))
        self._botao_parar.setFixedSize(36, 36)
        self._botao_parar.setToolTip("Interrompe o Claude e a fala (Esc)")
        self._botao_parar.hide()
        self._botao_enviar = QPushButton()
        self._botao_enviar.setObjectName("enviarRedondo")
        self._botao_enviar.setIcon(icones.icone_linha("enviar", "#ffffff"))
        self._botao_enviar.setFixedSize(36, 36)
        self._botao_enviar.setToolTip("Enviar (Enter)")
        for botao in (self._botao_parar, self._botao_enviar):
            botao.setIconSize(QSize(18, 18))
            botao.setCursor(Qt.CursorShape.PointingHandCursor)
        entrada.addWidget(self._entrada, 1)
        entrada.addWidget(self._botao_parar)
        entrada.addWidget(self._botao_enviar)
        chips = QHBoxLayout()
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(6)
        chips.addStretch(1)
        self._chip_modelo = QToolButton()
        self._chip_modelo.setText("…")
        self._chip_modelo.setObjectName("chip")
        self._chip_modelo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chip_modelo.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu_claude = QMenu(self._chip_modelo)
        self._menu_claude.aboutToShow.connect(self._preencher_menu_claude)
        self._chip_modelo.setMenu(self._menu_claude)
        self._chip_permissao = QLabel("…")
        self._chip_permissao.setObjectName("chip")
        self._chip_permissao.setToolTip("Quando o Claude pede a sua permissão")
        self._info = QLabel("")
        self._info.setObjectName("suave")
        self._info.setWordWrap(True)
        self._info.setContentsMargins(6, 0, 0, 0)
        self._info.hide()  # só para avisos rápidos (copiei, não era comigo...)
        chips.addWidget(self._chip_modelo)
        chips.addWidget(self._chip_permissao)
        chips.addStretch(1)
        coluna_rodape.addWidget(compositor)
        coluna_rodape.addLayout(chips)
        coluna_rodape.addWidget(self._info)

        coluna.addWidget(cabecalho)
        coluna.addLayout(baixo)
        coluna.addWidget(self._lista, 1)
        self._espera = PainelEspera(
            self.controlador.enviar_rascunho, self.controlador.descartar_rascunho, self.controlador.tirar_da_fila
        )
        coluna.addWidget(self._espera)
        coluna.addWidget(rodape)
        self.setCentralWidget(central)

        self._botao_mic.toggled.connect(self._alternar_mic)
        self._botao_compacto.clicked.connect(self.recolher)
        self._botao_historico.clicked.connect(self._abrir_historico)
        self._botao_config.clicked.connect(self._abrir_configuracoes)
        self._botao_nova.clicked.connect(self.controlador.nova_conversa)
        self._combo.activated.connect(self._ao_escolher_projeto)
        self._entrada.returnPressed.connect(self._enviar)
        self._botao_enviar.clicked.connect(self._enviar)
        self._botao_parar.clicked.connect(self.controlador.interromper)
        QShortcut(QKeySequence("Esc"), self, activated=self.controlador.interromper)
        QShortcut(QKeySequence("Ctrl+M"), self, activated=self._botao_mic.toggle)

    @staticmethod
    def _botao_icone(nome: str, dica: str, objeto: str = "icone") -> QToolButton:
        botao = QToolButton()
        botao.setObjectName(objeto)
        botao.setIcon(icones.icone_linha(nome, CORES["suave"]))
        botao.setIconSize(QSize(20, 20))
        botao.setToolTip(dica)
        botao.setCursor(Qt.CursorShape.PointingHandCursor)
        return botao

    def _criar_menu(self) -> QMenu:
        """Menu da bandeja e do botão direito na bolinha."""
        menu = QMenu(self)
        menu.addAction("Mostrar janela", self.mostrar)
        self._acao_mic = menu.addAction("Microfone ligado")
        self._acao_mic.setCheckable(True)
        self._acao_mic.setChecked(True)
        self._acao_mic.toggled.connect(self._botao_mic.setChecked)
        menu.addAction("Nova conversa", self.controlador.nova_conversa)
        menu.addAction("Conversas salvas…", self._abrir_historico)
        menu.addAction("Configurações…", self._abrir_configuracoes)
        menu.addSeparator()
        self._acao_no_topo = menu.addAction("Sempre em primeiro plano")
        self._acao_no_topo.setCheckable(True)
        self._acao_no_topo.setChecked(self.cfg.interface.bolinha_no_topo)
        self._acao_no_topo.setToolTip("A bolinha fica por cima de todas as janelas")
        self._acao_no_topo.toggled.connect(self._definir_bolinha_no_topo)
        menu.addSeparator()
        menu.addAction("Sair", self.sair)
        return menu

    def _definir_bolinha_no_topo(self, ligado: bool) -> None:
        """Liga ou desliga "Sempre em primeiro plano" da bolinha e guarda a escolha."""
        if self.cfg.interface.bolinha_no_topo != ligado:
            self.cfg.interface.bolinha_no_topo = ligado
            cfgmod.salvar(self.cfg)
        self._compacta.definir_no_topo(ligado)

    def _criar_bandeja(self) -> QSystemTrayIcon | None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        bandeja = QSystemTrayIcon(icones.icone_app(CORES["cinza"]), self)
        bandeja.setContextMenu(self._menu)
        bandeja.activated.connect(self._ao_clicar_bandeja)
        bandeja.setToolTip(NOME_APP)
        bandeja.show()
        return bandeja

    # ------------------------------------------------------------------ eventos do controlador
    def tratar_evento(self, evento: object) -> None:
        self._compacta.tratar_evento(evento)
        if isinstance(evento, ev.NivelMicrofone):
            self._orbe.definir_nivel(evento.nivel)
        elif isinstance(evento, ev.EstadoMudou):
            self._pintar_estado(evento.estado, evento.detalhe)
        elif isinstance(evento, ev.Carregando):
            if self._carregando is not None:
                self._carregando.atualizar(evento.mensagem, evento.fracao)
        elif isinstance(evento, ev.Pronto):
            self._ao_ficar_pronto(evento)
        elif isinstance(evento, ev.ProjetoAtual):
            self._ao_mudar_projeto(evento)
        elif isinstance(evento, ev.FalaUsuario):
            self._lista.adicionar(BolhaUsuario(evento.texto, evento.origem))
            self._lista.rolar_para_o_fim()
        elif isinstance(evento, ev.FalaIgnorada):
            self._info_temporaria(
                f"Ouvi “{evento.texto}”, mas não era comigo. Comece com “{self.cfg.ativacao.nome}”."
            )
        elif isinstance(evento, ev.Rascunho):
            self._espera.definir_rascunho(evento)
        elif isinstance(evento, ev.Fila):
            self._espera.definir_fila(evento.itens)
        elif isinstance(evento, ev.InicioResposta):
            self._bloco = self._lista.adicionar(BlocoResposta())
        elif isinstance(evento, ev.TextoClaude):
            self._bloco_atual().adicionar_texto(evento.texto)
        elif isinstance(evento, ev.AcaoClaude):
            self._bloco_atual().adicionar_acao(evento.descricao)
            self._orbe.marcar_acao(evento.ferramenta)
        elif isinstance(evento, ev.InfoClaude):
            self._mostrar_info_claude(evento)
        elif isinstance(evento, ev.ConfigAlterada):
            self.cfg = evento.cfg  # as configurações abrem já com o que mudou por voz
        elif isinstance(evento, ev.FimResposta):
            self._bloco_atual().finalizar(evento)
            self._bloco = None
        elif isinstance(evento, ev.PedidoAprovacao):
            cartao = CartaoAprovacao(evento, self.controlador.responder_aprovacao)
            self._cartoes[evento.id] = cartao
            self._lista.adicionar(cartao)
            self._lista.rolar_para_o_fim()
            if not self.isVisible() and self._bandeja is not None:
                self._bandeja.showMessage(NOME_APP, evento.pergunta, QSystemTrayIcon.MessageIcon.Warning, 8000)
        elif isinstance(evento, ev.AprovacaoResolvida):
            cartao = self._cartoes.pop(evento.id, None)
            if cartao is not None:
                cartao.resolver(evento.aprovado, evento.por)
        elif isinstance(evento, ev.ConversaCarregada):
            self._carregar_conversa(evento)
        elif isinstance(evento, ev.ConversaNova):
            self._lista.adicionar(LinhaAviso("Nova conversa"))
        elif isinstance(evento, ev.LoginNecessario):
            self._mostrar_login()
        elif isinstance(evento, ev.LoginConfirmado):
            if self._cartao_login is not None:
                self._cartao_login.concluir()
        elif isinstance(evento, ev.Copiar):
            acoes.copiar(evento.texto)
            self._info_temporaria(f"Copiei {evento.descricao or 'o texto'} para a área de transferência (Ctrl+V cola).")
        elif isinstance(evento, ev.Abrir):
            if evento.na_pasta:
                acoes.mostrar_na_pasta(evento.caminho)
            else:
                acoes.abrir(evento.caminho)
        elif isinstance(evento, ev.Aviso):
            self._lista.adicionar(LinhaAviso(evento.mensagem, evento.nivel == "erro"))

    def _carregar_conversa(self, evento: ev.ConversaCarregada) -> None:
        """Redesenha a lista com a conversa salva do projeto (ou vazia, numa conversa nova)."""
        self._lista.limpar()
        self._carregando = None
        self._bloco = None
        self._cartoes.clear()
        login_pendente = self._cartao_login is not None and not self._cartao_login.concluido
        self._cartao_login = None
        if evento.entradas:
            renderizar_entradas(self._lista, evento.entradas)
            self._lista.adicionar(LinhaAviso("Conversa salva · continua daqui"))
        if login_pendente:
            self._mostrar_login()
        self._lista.rolar_para_o_fim()

    def _mostrar_login(self) -> None:
        if self._cartao_login is not None and not self._cartao_login.concluido:
            return
        self._cartao_login = CartaoLogin(self.controlador.abrir_login, self.controlador.confirmar_login)
        self._lista.adicionar(self._cartao_login)
        self._lista.rolar_para_o_fim()
        self.mostrar()

    def _abrir_historico(self) -> None:
        from .janela_historico import JanelaHistorico

        self.mostrar()
        JanelaHistorico(self.controlador.historico, self.controlador.continuar_conversa, self).exec()

    def _bloco_atual(self) -> BlocoResposta:
        if self._bloco is None or self._bloco.finalizado:
            self._bloco = self._lista.adicionar(BlocoResposta())
        return self._bloco

    def _ao_ficar_pronto(self, evento: ev.Pronto) -> None:
        if self._carregando is not None:
            self._lista.remover(self._carregando)
            self._carregando = None
        nome = self.cfg.ativacao.nome
        if self.cfg.ativacao.modo == "continuo":
            como = "Modo contínuo: tudo o que você falar vai para o Claude."
        else:
            como = (
                f"Diga **“{nome}”** e o seu pedido. Por exemplo: "
                f"*“{nome}, explica o que esse projeto faz.”*"
            )
        janela = self.cfg.ativacao.janela_conversa_s
        texto = como
        palavra = self.cfg.ativacao.palavra_parar
        if self.cfg.ativacao.modo == "continuo":
            pass
        elif self.cfg.ativacao.nome_so_para_acordar:
            texto += (
                f"\n\nO nome só acorda: depois disso, tudo o que você falar é com ele, sem repetir o nome. "
                f"*“{palavra}”* o põe para dormir de novo, e aí é preciso chamar “{nome}” outra vez."
            )
        elif janela > 0:
            texto += f"\n\nDepois de cada resposta, por {janela:.0f} segundos, dá para continuar sem repetir o nome."
        espera, enviar = self.cfg.ativacao.espera_envio_s, self.cfg.ativacao.palavra_enviar
        if espera > 0:
            texto += (
                f"\n\nPode parar para pensar no meio do pedido: ele só vai depois de {espera:g} segundos de silêncio. "
                f"Para mandar na hora, termine com *“{enviar}”*. “Cancela” descarta o pedido antes de ir."
            )
        texto += (
            "\n\nDepois do nome, o Claude assume: fale do seu jeito, inclusive para trocar de projeto, começar "
            f"uma conversa nova, abrir ou copiar um arquivo, repetir ou desfazer. Para interromper na hora, diga "
            f"*“{palavra}”* (não precisa do nome).\n\n"
            "Tudo fica salvo: o botão do relógio, lá em cima, mostra as conversas anteriores. Esc interrompe; Ctrl+M liga e desliga "
            "o microfone."
        )
        self._lista.adicionar(CartaoInfo("Tudo pronto", texto))
        self._info_base = f"Reconhecimento: {evento.reconhecimento} · Voz: {evento.voz} · {evento.claude}"
        self._orbe.setToolTip(self._info_base)

    def _mostrar_info_claude(self, evento: ev.InfoClaude) -> None:
        self._chip_modelo.setText(f"{evento.modelo} · esforço {evento.esforco}")
        self._chip_permissao.setText(f"Permissões: {evento.permissao}")
        origem = "confirmado pelo Claude Code" if evento.confirmado else "configurado; o Claude Code confirma ao abrir"
        self._chip_modelo.setToolTip(f"Modelo e esforço do Claude ({origem}). Clique para trocar.")

    def _preencher_menu_claude(self) -> None:
        """Menu do chip de modelo e esforço: a opção atual vem marcada; escolher outra troca na hora."""
        from .configuracoes import _ESFORCOS, _MODELOS

        menu = self._menu_claude
        menu.clear()
        atual = self.cfg.claude
        for titulo, campo, opcoes, valor_atual in (
            ("Modelo", "modelo", _MODELOS, atual.modelo),
            ("Esforço", "esforco", _ESFORCOS, atual.esforco),
        ):
            if not menu.isEmpty():
                menu.addSeparator()
            cabecalho = menu.addAction(titulo)
            cabecalho.setEnabled(False)
            fonte = cabecalho.font()
            fonte.setBold(True)
            cabecalho.setFont(fonte)
            grupo = QActionGroup(menu)
            grupo.setExclusive(True)
            valores = [valor for valor, _ in opcoes]
            if valor_atual not in valores:  # um modelo escrito à mão nas configurações
                opcoes = [*opcoes, (valor_atual, valor_atual)]
            for valor, texto in opcoes:
                acao = menu.addAction(texto)
                acao.setCheckable(True)
                acao.setChecked(valor == valor_atual)
                grupo.addAction(acao)
                acao.triggered.connect(lambda _=False, c=campo, v=valor: self._escolher_claude(c, v))

    def _escolher_claude(self, campo: str, valor: str) -> None:
        if getattr(self.cfg.claude, campo) == valor:
            return
        self.controlador.mudar_claude(**{campo: valor})

    def _ao_mudar_projeto(self, evento: ev.ProjetoAtual) -> None:
        indice = -1
        for i in range(self._combo.count()):
            dado = self._combo.itemData(i)
            if dado and _mesmo_caminho(dado, evento.caminho):
                indice = i
                break
        if indice < 0:
            self._combo.addItem(evento.nome, evento.caminho)
            indice = self._combo.count() - 1
        self._combo.blockSignals(True)
        self._combo.setCurrentIndex(indice)
        self._combo.blockSignals(False)
        self._combo.setToolTip(evento.caminho)
        sufixo = " · continuando a conversa de antes" if evento.retomada else ""
        self._lista.adicionar(LinhaAviso(f"Projeto: {evento.nome}{sufixo}"))

    def _pintar_estado(self, estado: ev.Estado, detalhe: str) -> None:
        self._estado = estado
        texto, cor = ESTADOS.get(estado, ("", CORES["cinza"]))
        texto = texto.format(nome=self.cfg.ativacao.nome, detalhe=detalhe)
        if estado is ev.Estado.ERRO and detalhe:
            texto = f"Erro: {detalhe[:90]}"
        self._rotulo_estado.setText(texto)
        self._rotulo_estado.setStyleSheet(f"color: {QColor(cor).darker(145).name()};")  # legível no vidro claro
        self._orbe.definir_estado(estado)
        self._fundo.definir_estado(estado)
        self._botao_parar.setVisible(estado in (ev.Estado.PENSANDO, ev.Estado.FALANDO, ev.Estado.APROVACAO))
        if self._bandeja is not None:
            self._bandeja.setIcon(icones.icone_app(cor))
            self._bandeja.setToolTip(f"{NOME_APP}: {texto}")

    def _info_temporaria(self, texto: str, ms: int = 7000) -> None:
        self._info.setText(texto)
        self._info.show()
        self._timer_info.start(ms)

    # ------------------------------------------------------------------ ações
    def _preencher_projetos(self) -> None:
        atual = self.controlador.projeto_atual
        self._combo.blockSignals(True)
        self._combo.clear()
        for projeto in self.controlador.projetos():
            self._combo.addItem(projeto.nome, projeto.caminho)
            self._combo.setItemData(self._combo.count() - 1, projeto.caminho, Qt.ItemDataRole.ToolTipRole)
        if atual is not None:
            for i in range(self._combo.count()):
                if _mesmo_caminho(self._combo.itemData(i), atual.caminho):
                    self._combo.setCurrentIndex(i)
                    break
        self._combo.blockSignals(False)

    def _ao_escolher_projeto(self, indice: int) -> None:
        caminho = self._combo.itemData(indice)
        if caminho:
            self.controlador.trocar_projeto(caminho)

    def _enviar(self) -> None:
        texto = self._entrada.text().strip()
        if texto:
            self.controlador.enviar_texto(texto)
            self._entrada.clear()

    def _alternar_mic(self, ligado: bool) -> None:
        self.controlador.definir_microfone(ligado)
        self._botao_mic.setIcon(icones.icone_linha("mic" if ligado else "mic_off", CORES["suave"] if ligado else CORES["vermelho"]))
        self._botao_mic.setToolTip("Microfone ligado (Ctrl+M desliga)" if ligado else "Microfone desligado (Ctrl+M liga)")
        acao = getattr(self, "_acao_mic", None)
        if acao is not None:
            acao.setChecked(ligado)
            acao.setText("Microfone ligado" if ligado else "Microfone desligado")

    def _abrir_configuracoes(self) -> None:
        from .configuracoes import DialogoConfiguracoes

        self.mostrar()
        dialogo = DialogoConfiguracoes(self.cfg, self)
        if dialogo.exec():
            novo = dialogo.resultado()
            cfgmod.salvar(novo)
            no_topo_mudou = novo.interface.sempre_no_topo != self.cfg.interface.sempre_no_topo
            self.cfg = novo
            self.controlador.aplicar_config(novo)
            self._preencher_projetos()
            self._pintar_estado(self._estado, "")
            self._compacta.nome_ativacao = novo.ativacao.nome
            self._acao_no_topo.blockSignals(True)
            self._acao_no_topo.setChecked(novo.interface.bolinha_no_topo)
            self._acao_no_topo.blockSignals(False)
            self._compacta.definir_no_topo(novo.interface.bolinha_no_topo)
            self._atualizar_compacta()
            if no_topo_mudou:
                self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, novo.interface.sempre_no_topo)
                self.show()

    # ------------------------------------------------------------------ janela e bandeja
    def mostrar(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def recolher(self) -> None:
        """Esconde a janela e deixa só a bolinha (ou a bandeja, se a bolinha estiver desligada)."""
        if self.cfg.interface.janela_compacta or self._bandeja is not None:
            self.hide()
        else:
            self.showMinimized()

    def _ao_clicar_compacta(self) -> None:
        self.mostrar()

    def _atualizar_compacta(self) -> None:
        """A bolinha aparece quando a janela principal não está à vista."""
        janela_a_vista = self.isVisible() and not self.isMinimized()
        mostrar = self.cfg.interface.janela_compacta and not janela_a_vista and not self._saindo
        if mostrar and not self._compacta.isVisible():
            self._compacta.show()
        elif not mostrar and self._compacta.isVisible():
            self._compacta.hide()

    def atualizar_compacta_depois(self) -> None:
        QTimer.singleShot(0, self._atualizar_compacta)

    def showEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        super().showEvent(evento)
        self.atualizar_compacta_depois()

    def hideEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        super().hideEvent(evento)
        self.atualizar_compacta_depois()

    def changeEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        super().changeEvent(evento)
        if evento.type() == QEvent.Type.WindowStateChange:
            self.atualizar_compacta_depois()

    def _ao_clicar_bandeja(self, motivo) -> None:
        if motivo in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.mostrar()

    def closeEvent(self, evento) -> None:  # noqa: N802 (nome do Qt)
        if not self._saindo and self.cfg.interface.fechar_para_bandeja and self._bandeja is not None:
            evento.ignore()
            self.hide()
            if not self._avisou_bandeja and not self.cfg.interface.janela_compacta:
                self._bandeja.showMessage(
                    NOME_APP,
                    "Continuo ouvindo aqui na bandeja. Para fechar de vez, use “Sair” no menu deste ícone.",
                    QSystemTrayIcon.MessageIcon.Information,
                    5000,
                )
                self._avisou_bandeja = True
            return
        self._saindo = True
        evento.accept()
        QApplication.instance().quit()

    def sair(self) -> None:
        self._saindo = True
        self._compacta.hide()
        if self._bandeja is not None:
            self._bandeja.hide()
        QApplication.instance().quit()
