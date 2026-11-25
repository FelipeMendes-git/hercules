"""Janela de configurações."""

from __future__ import annotations

import copy
import logging
import threading

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import config as cfgmod
from .. import inicializacao, modelos, pronuncia, voz
from ..audio import dispositivos
from ..marca import NOME_APP, NOME_ATIVACAO_PADRAO
from ..saudacao import ESTILOS, OCASIOES

log = logging.getLogger(__name__)

_LISTAS_FRASES = [
    ("aberturas", "Aberturas"),
    ("frases_chamado", "Depois da abertura, quando eu só chamo"),
    ("frases_pedido", "Depois da abertura, quando já peço junto"),
    *[(chave, f"Abertura especial: {rotulo}") for chave, rotulo in OCASIOES.items()],
]
_OUVIR = "Ouvir uma saudação"

_MODOS_ATIVACAO = [
    ("nome", "Chamar pelo nome antes de pedir"),
    ("continuo", "Contínuo: tudo o que eu falar vai para o Claude"),
]
_MODOS_PERMISSAO = [
    ("auto", "Automático: só pergunta o que for arriscado (como no Claude Code)"),
    ("acceptEdits", "Edita arquivos sem perguntar; pergunta antes de comandos"),
    ("default", "Pergunta antes de editar arquivos e de rodar comandos"),
    ("plan", "Só planeja, sem alterar nada"),
]
_MODELOS = [
    ("claude-opus-5-5", "Opus 5.5 (o mais capaz)"),
    ("claude-sonnet-5-5", "Sonnet 5.5 (mais rápido)"),
    ("claude-haiku-5-5", "Haiku 5.5 (o mais rápido)"),
    ("", "Padrão do Claude Code"),
]
_ESFORCOS = [
    ("", "Padrão do Claude Code"),
    ("low", "Baixo (mais rápido e econômico)"),
    ("medium", "Médio (equilíbrio)"),
    ("high", "Alto (pensa com cuidado)"),
    ("xhigh", "Muito alto"),
    ("max", "Máximo"),
]


def _combo(opcoes: list[tuple[str, str]], atual: str) -> QComboBox:
    caixa = QComboBox()
    for valor, texto in opcoes:
        caixa.addItem(texto, valor)
    indice = caixa.findData(atual)
    if indice < 0 and atual:
        caixa.addItem(atual, atual)
        indice = caixa.count() - 1
    caixa.setCurrentIndex(max(0, indice))
    return caixa


def _juntar(valores: list[str]) -> str:
    return ", ".join(valores)


def _separar(texto: str) -> list[str]:
    return [parte.strip() for parte in texto.replace(";", ",").split(",") if parte.strip()]


def _dica(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setObjectName("suave")
    rotulo.setWordWrap(True)
    return rotulo


def _numero(minimo: float, maximo: float, valor: float, passo: float = 1.0, casas: int = 0, sufixo: str = ""):
    caixa = QDoubleSpinBox() if casas else QSpinBox()
    caixa.setRange(minimo, maximo)
    caixa.setSingleStep(passo)
    if casas:
        caixa.setDecimals(casas)
    if sufixo:
        caixa.setSuffix(sufixo)
    caixa.setValue(valor)
    return caixa


class DialogoConfiguracoes(QDialog):
    _voz_testada = Signal(str)
    _saudacao_testada = Signal(str)

    def __init__(self, cfg: cfgmod.Config, pai=None) -> None:
        super().__init__(pai)
        self.setWindowTitle("Configurações")
        self.setMinimumWidth(780)
        self._cfg = copy.deepcopy(cfg)
        abas = QTabWidget()
        abas.addTab(self._aba_ativacao(), "Ativação")
        abas.addTab(self._aba_saudacao(), "Saudação")
        abas.addTab(self._aba_audio(), "Áudio")
        abas.addTab(self._aba_voz(), "Voz")
        abas.addTab(self._aba_reconhecimento(), "Reconhecimento")
        abas.addTab(self._aba_desempenho(), "Desempenho")
        abas.addTab(self._aba_claude(), "Claude")
        abas.addTab(self._aba_projetos(), "Projetos")
        abas.addTab(self._aba_janela(), "Janela")
        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        botoes.button(QDialogButtonBox.StandardButton.Save).setText("Salvar")
        botoes.button(QDialogButtonBox.StandardButton.Save).setObjectName("primario")
        botoes.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        coluna = QVBoxLayout(self)
        coluna.addWidget(abas)
        coluna.addWidget(botoes)
        self._voz_testada.connect(self._fim_teste_voz)
        self._saudacao_testada.connect(self._fim_teste_saudacao)

    # ------------------------------------------------------------------ abas
    def _aba_ativacao(self) -> QWidget:
        a = self._cfg.ativacao
        aba = QWidget()
        form = QFormLayout(aba)
        self._modo = _combo(_MODOS_ATIVACAO, a.modo)
        self._nome = QLineEdit(a.nome)
        self._apelidos = QLineEdit(_juntar(a.apelidos))
        self._apelidos.setPlaceholderText("outras grafias, separadas por vírgula")
        self._janela = _numero(0, 120, a.janela_conversa_s, 1, 0, " s")
        self._similaridade = _numero(0.5, 1.0, a.similaridade_minima, 0.02, 2)
        self._responder = QCheckBox("Responder “Pode falar.” quando eu só chamar o nome (sem saudação)")
        self._responder.setChecked(a.responder_ao_chamado)
        self._so_acordar = QCheckBox("O nome só acorda: depois disso, tudo o que eu falar é com ele")
        self._so_acordar.setChecked(a.nome_so_para_acordar)
        self._so_acordar.toggled.connect(lambda ligado: self._janela.setEnabled(not ligado))
        self._palavra_parar = QLineEdit(a.palavra_parar)
        self._palavra_enviar = QLineEdit(a.palavra_enviar)
        self._espera_envio = _numero(0, 30, a.espera_envio_s, 0.5, 1, " s")
        self._juntar = _numero(0, 60, a.juntar_pedido_s, 1, 0, " s")
        form.addRow("Como chamar", self._modo)
        form.addRow("Nome do assistente", self._nome)
        form.addRow("Outras grafias", self._apelidos)
        form.addRow("", self._so_acordar)
        form.addRow("Palavra para parar", self._palavra_parar)
        form.addRow("Palavra para mandar", self._palavra_enviar)
        form.addRow("Mandar depois de um silêncio de", self._espera_envio)
        form.addRow("Juntar com o pedido anterior até", self._juntar)
        form.addRow("Continuar sem o nome por", self._janela)
        form.addRow("Exigência ao reconhecer o nome", self._similaridade)
        form.addRow("", self._responder)
        self._janela.setEnabled(not a.nome_so_para_acordar)
        form.addRow(
            _dica(
                "O nome é o que você fala para chamar o assistente. Escolha um nome que não apareça muito nas suas "
                "conversas. Se o reconhecimento escrever o nome de outro jeito, ponha essa grafia em “Outras grafias”. "
                "Com “O nome só acorda” marcado, depois de chamar, tudo o que você fala vai para ele, até a palavra "
                "para parar (ou até ele cochilar sozinho, sem uso, como em ⚙ → Desempenho); aí o nome volta a ser "
                "preciso. A palavra para parar interrompe o Claude e a fala na hora, mesmo sem o nome; por isso deve "
                "ser incomum. Em “Continuar sem o nome” (quando o nome vale para todo pedido), 0 desliga a janela. "
                "O pedido falado só vai para o Claude depois do silêncio escolhido (0 = assim que você para), ou "
                "na hora, se você terminar com a palavra para mandar. Se você completar o pedido logo depois de "
                "mandar, e o Claude ainda não tiver mexido em nada, ele recebe tudo junto; senão, vai para a fila."
            )
        )
        return aba

    def _aba_saudacao(self) -> QWidget:
        s = self._cfg.saudacao
        aba = QWidget()
        form = QFormLayout(aba)
        self._quando_saudar = _combo(
            [
                ("acordar", "Na primeira chamada depois de um tempo parado"),
                ("sempre", "Toda vez que eu chamar"),
                ("nunca", "Nunca"),
            ],
            s.quando,
        )
        self._tratamento = QLineEdit(s.tratamento)
        self._tratamento.setPlaceholderText("como o assistente chama você (ex.: mestre)")
        self._tratamento.setToolTip("Usado só na saudação de abertura.")
        # Uma caixa só para as frases; o seletor escolhe qual lista está sendo editada.
        self._lista_frases = _combo(_LISTAS_FRASES, "aberturas")
        self._frases_por_lista = {campo: "\n".join(getattr(s, campo)) for campo, _ in _LISTAS_FRASES}
        self._lista_editada = "aberturas"
        self._editor_frases = QPlainTextEdit(self._frases_por_lista["aberturas"])
        self._editor_frases.setFixedHeight(165)
        self._lista_frases.currentIndexChanged.connect(self._trocar_lista_frases)
        self._musica = QLineEdit(s.musica)
        self._musica.setPlaceholderText("vazio = vinheta do app")
        escolher = QPushButton("Escolher…")
        escolher.clicked.connect(self._escolher_musica)
        vinheta = QPushButton("Usar a vinheta")
        vinheta.clicked.connect(lambda: self._musica.setText(""))
        linha_musica = QHBoxLayout()
        linha_musica.addWidget(self._musica, 1)
        linha_musica.addWidget(escolher)
        linha_musica.addWidget(vinheta)
        self._estilo = _combo(list(ESTILOS.items()), s.estilo)
        self._estilo.setEnabled(not s.musica.strip())
        self._musica.textChanged.connect(lambda texto: self._estilo.setEnabled(not texto.strip()))
        self._volume_musica = _numero(0.0, 1.0, s.volume_musica, 0.05, 2)
        self._botao_ouvir = QPushButton(_OUVIR)
        self._botao_ouvir.setToolTip("Toca uma saudação sorteada da lista que está aberta acima.")
        self._botao_ouvir.clicked.connect(self._testar_saudacao)
        form.addRow("Quando cumprimentar", self._quando_saudar)
        form.addRow("Como chamar você", self._tratamento)
        form.addRow("Frases", self._lista_frases)
        form.addRow("", self._editor_frases)
        form.addRow("Vinheta", self._estilo)
        form.addRow("Música de fundo", linha_musica)
        form.addRow("Volume da música", self._volume_musica)
        form.addRow("", self._botao_ouvir)
        form.addRow(
            _dica(
                "A saudação é fixa e não passa pelo Claude: uma abertura e uma frase, uma por linha, sorteadas sem "
                "repetir as últimas. {periodo} vira “Bom dia”, “Boa tarde” ou “Boa noite” e {tratamento} vira como "
                "chamar você (o Claude também passa a chamar você assim). Nas ocasiões especiais, metade das vezes a "
                "abertura é a da ocasião. Quando você já fala o pedido junto, a saudação toca enquanto o Claude "
                "trabalha, sem atrasar nada. As frases são gravadas uma vez com a voz escolhida e depois tocam na hora."
            )
        )
        return aba

    def _trocar_lista_frases(self) -> None:
        self._frases_por_lista[self._lista_editada] = self._editor_frases.toPlainText()
        self._lista_editada = self._lista_frases.currentData()
        self._editor_frases.setPlainText(self._frases_por_lista[self._lista_editada])

    def _escolher_musica(self) -> None:
        arquivo, _ = QFileDialog.getOpenFileName(
            self, "Escolha a música de fundo", "", "Áudio (*.mp3 *.wav *.ogg *.flac *.m4a *.aac *.opus)"
        )
        if arquivo:
            self._musica.setText(arquivo.replace("/", "\\"))

    def _ler_saudacao(self) -> cfgmod.Saudacao:
        self._frases_por_lista[self._lista_editada] = self._editor_frases.toPlainText()

        def linhas(campo: str) -> list[str]:
            return [linha.strip() for linha in self._frases_por_lista[campo].splitlines() if linha.strip()]

        return cfgmod.Saudacao(
            quando=self._quando_saudar.currentData(),
            tratamento=self._tratamento.text().strip(),
            musica=self._musica.text().strip(),
            estilo=self._estilo.currentData(),
            volume_musica=float(self._volume_musica.value()),
            **{campo: linhas(campo) for campo, _ in _LISTAS_FRASES},
        )

    def _testar_saudacao(self) -> None:
        cfg_saudacao, cfg_voz = self._ler_saudacao(), self._ler_voz()
        lista = self._lista_editada  # toca uma saudação da lista aberta (a da ocasião, se for uma)
        com_pedido = lista == "frases_pedido"
        ocasiao_forcada = lista if lista in OCASIOES else None
        self._botao_ouvir.setEnabled(False)
        self._botao_ouvir.setText("Preparando…")

        def trabalho() -> None:
            erro = ""
            try:
                import sounddevice as sd

                from ..saudacao import TAXA, Saudacoes

                saudacoes = Saudacoes(cfg_saudacao, cfg_voz)
                montado = saudacoes.montar(
                    com_pedido=com_pedido, ocasiao_forcada=ocasiao_forcada, criar_voz=lambda: voz.criar(cfg_voz)
                )
                if montado is None:
                    raise RuntimeError("não consegui montar a saudação")
                sd.play(montado[0], TAXA)
                sd.wait()
            except Exception as falha:
                log.exception("Falha ao testar a saudação")
                erro = str(falha)
            self._saudacao_testada.emit(erro)

        threading.Thread(target=trabalho, daemon=True).start()

    def _fim_teste_saudacao(self, erro: str) -> None:
        self._botao_ouvir.setEnabled(True)
        self._botao_ouvir.setText(_OUVIR if not erro else "Falhou; ouvir de novo")

    def _aba_audio(self) -> QWidget:
        a = self._cfg.audio
        aba = QWidget()
        form = QFormLayout(aba)
        self._microfone = _combo([("", "Padrão do Windows")] + [(n, n) for _, n in dispositivos.listar(True)], a.microfone)
        self._saida = _combo([("", "Padrão do Windows")] + [(n, n) for _, n in dispositivos.listar(False)], a.saida)
        self._limiar = _numero(0.2, 0.95, a.limiar_vad, 0.05, 2)
        self._silencio = _numero(300, 3000, a.silencio_fim_ms, 50, 0, " ms")
        self._volume = _numero(0.1, 2.0, a.volume, 0.1, 1)
        self._sons = QCheckBox("Tocar sons curtos de aviso")
        self._sons.setChecked(a.sons)
        form.addRow("Microfone", self._microfone)
        form.addRow("Saída de som", self._saida)
        form.addRow("Sensibilidade da detecção de voz", self._limiar)
        form.addRow("Silêncio que encerra a fala", self._silencio)
        form.addRow("Volume da voz", self._volume)
        form.addRow("", self._sons)
        form.addRow(
            _dica(
                "Na sensibilidade, valores maiores pedem mais certeza de que é voz (bom em lugar barulhento). "
                "Se o app cortar você no meio da frase, aumente o silêncio que encerra a fala. "
                "Trocar de microfone ou de saída vale depois de reiniciar o app."
            )
        )
        return aba

    def _aba_voz(self) -> QWidget:
        v = self._cfg.voz
        aba = QWidget()
        form = QFormLayout(aba)
        self._motor = _combo([("kokoro", "Kokoro (natural, roda no PC)"), ("sapi", "Voz do Windows")], v.motor)
        self._voz_kokoro = _combo(list(voz.VOZES_KOKORO.items()), v.voz)
        vozes_windows = voz.vozes_windows()
        # A config pode guardar só parte do nome ("Daniel"): seleciona a voz completa que contém esse nome.
        atual_windows = next((n for n in vozes_windows if v.voz_sapi and v.voz_sapi.lower() in n.lower()), v.voz_sapi)
        self._voz_windows = _combo([(n, n) for n in vozes_windows] or [(v.voz_sapi, v.voz_sapi)], atual_windows)
        self._voz_kokoro.currentIndexChanged.connect(self._sugerir_reserva)
        self._velocidade = _numero(0.6, 1.6, v.velocidade, 0.05, 2)
        self._botao_testar = QPushButton("Testar voz")
        self._botao_testar.clicked.connect(self._testar_voz)
        self._botao_pronuncia = QPushButton("Abrir dicionário de pronúncia")
        self._botao_pronuncia.setToolTip("Como a voz fala termos em inglês e siglas (vale na hora, sem reiniciar)")
        self._botao_pronuncia.clicked.connect(self._abrir_pronuncia)
        form.addRow("Motor", self._motor)
        form.addRow("Voz do Kokoro", self._voz_kokoro)
        form.addRow("Voz do Windows", self._voz_windows)
        form.addRow("Velocidade", self._velocidade)
        form.addRow("", self._botao_testar)
        form.addRow("", self._botao_pronuncia)
        form.addRow(
            _dica(
                "A mesma voz faz a saudação e lê as respostas do Claude. A voz do Windows é a reserva: o app usa "
                "ela sozinho se o Kokoro não carregar e, ao trocar a voz do Kokoro, ela muda junto para uma do "
                "mesmo gênero. O dicionário de pronúncia diz como falar termos em inglês e siglas (“deploy” "
                "vira “diplói”); o app já vem com os mais comuns de TI e você completa ou corrige."
            )
        )
        return aba

    def _abrir_pronuncia(self) -> None:
        from . import acoes

        caminho = str(pronuncia.garantir_arquivo())
        if not acoes.abrir(caminho):  # .toml sem programa associado: abre no Bloco de Notas
            import subprocess

            subprocess.Popen(["notepad.exe", caminho])

    def _sugerir_reserva(self) -> None:
        """Ao trocar a voz do Kokoro, deixa a reserva do Windows com o mesmo gênero (se existir no PC)."""
        nome = voz.RESERVA_WINDOWS.get(self._voz_kokoro.currentData() or "", "").lower()
        if not nome:
            return
        for i in range(self._voz_windows.count()):
            if nome in str(self._voz_windows.itemData(i)).lower():
                self._voz_windows.setCurrentIndex(i)
                return

    def _aba_reconhecimento(self) -> QWidget:
        r = self._cfg.reconhecimento
        aba = QWidget()
        form = QFormLayout(aba)
        self._modelo_rec = _combo(
            [(nome, f"{nome}  (~{megas} MB)") for nome, (_, megas) in modelos.WHISPER.items()], r.modelo
        )
        self._dispositivo_rec = _combo(
            [("auto", "Automático (placa de vídeo se der)"), ("cuda", "Só placa de vídeo"), ("cpu", "Só processador")],
            r.dispositivo,
        )
        self._pastas_cuda = QLineEdit(_juntar(r.pastas_cuda))
        self._pastas_cuda.setPlaceholderText("vazio = procurar sozinho")
        form.addRow("Modelo", self._modelo_rec)
        form.addRow("Onde rodar", self._dispositivo_rec)
        form.addRow("Pastas com CUDA", self._pastas_cuda)
        form.addRow(
            _dica(
                "O large-v3-turbo é o mais preciso que ainda é rápido. Sem placa de vídeo, o small é mais leve. "
                "O app reaproveita o CUDA que já existe no PC (VoiceStudio, CUDA Toolkit ou pacotes pip). "
                "Mudanças aqui valem depois de reiniciar o app; um modelo novo é baixado na primeira vez."
            )
        )
        return aba

    def _aba_desempenho(self) -> QWidget:
        e, r, i = self._cfg.espera, self._cfg.reconhecimento, self._cfg.interface
        aba = QWidget()
        form = QFormLayout(aba)
        self._comecar_em_espera = QCheckBox("Abrir em espera (gastando o mínimo até eu chamar)")
        self._comecar_em_espera.setChecked(e.comecar_em_espera)
        self._voltar_espera = _numero(0, 240, e.voltar_apos_min, 5, 0, " min")
        self._voltar_espera.setSpecialValueText("nunca")
        self._modelo_leve = _combo(
            [
                ("tiny", "tiny, no processador (recomendado)"),
                ("base", "base, no processador (um pouco mais preciso)"),
                ("", "nenhum: usar o modelo principal para tudo (sem modo em espera)"),
            ],
            r.modelo_ativacao,
        )
        self._prioridade = QCheckBox("Prioridade baixa (jogos e outros programas ganham na disputa)")
        self._prioridade.setChecked(i.prioridade_baixa)
        form.addRow("", self._comecar_em_espera)
        form.addRow("Voltar para a espera depois de", self._voltar_espera)
        form.addRow("Ouvir o nome com", self._modelo_leve)
        form.addRow("", self._prioridade)
        form.addRow(
            _dica(
                "Em espera ficam carregados só a detecção de voz e um modelo leve no processador, que procura o nome "
                "no que o microfone ouve: cerca de 0,2 GB de memória e nada na placa de vídeo. Quando você chama, o "
                "reconhecimento preciso (placa de vídeo), a voz e o Claude Code carregam em paralelo, uns 2 a 3 s a "
                "mais nessa vez. Sem ser chamado pelo tempo escolhido, ele volta para a espera (sobram ~0,17 GB na "
                "placa de vídeo até fechar o app); a conversa continua salva. Ouvir o nome e a prioridade valem "
                "depois de reiniciar o app."
            )
        )
        return aba

    def _aba_claude(self) -> QWidget:
        c = self._cfg.claude
        aba = QWidget()
        form = QFormLayout(aba)
        self._modo_permissao = _combo(_MODOS_PERMISSAO, c.modo_permissao)
        self._modelo_claude = _combo(_MODELOS, c.modelo)
        self._esforco = _combo(_ESFORCOS, c.esforco)
        self._esforco.setToolTip(
            "Quanto o Claude pensa antes de responder. Menos esforço responde mais rápido e gasta menos, "
            f"mas erra mais em pedidos difíceis. Também dá para pedir falando: \"{NOME_APP}, usa esforço médio\"."
        )
        self._nova_ao_abrir = QCheckBox("Abrir o app sempre numa conversa nova")
        self._nova_ao_abrir.setToolTip("As conversas anteriores continuam em Conversas salvas.")
        self._nova_ao_abrir.setChecked(c.conversa_nova_ao_abrir)
        self._retomar = QCheckBox("Ao entrar num projeto, continuar a conversa anterior dele")
        self._retomar.setChecked(c.retomar_conversa)
        self._narrar = QCheckBox("Contar em voz alta o que ele está fazendo em tarefas longas")
        self._narrar.setChecked(c.narrar_progresso)
        self._resumir = QCheckBox(f"Respostas resumidas (só no {NOME_APP})")
        self._resumir.setToolTip("Abrir o projeto no Claude Code ou no Claude Desktop continua do jeito de sempre.")
        self._resumir.setChecked(c.respostas_resumidas)
        self._tempo_aprovacao = _numero(10, 900, c.tempo_aprovacao_s, 10, 0, " s")
        self._extras = QPlainTextEdit(c.instrucoes_extras)
        self._extras.setPlaceholderText("Instruções extras para o Claude (opcional)")
        self._extras.setFixedHeight(90)
        form.addRow("Permissões", self._modo_permissao)
        form.addRow("Modelo", self._modelo_claude)
        form.addRow("Esforço", self._esforco)
        form.addRow("Tempo para responder a uma permissão", self._tempo_aprovacao)
        form.addRow("", self._nova_ao_abrir)
        form.addRow("", self._retomar)
        form.addRow("", self._resumir)
        form.addRow("", self._narrar)
        form.addRow("Instruções extras", self._extras)
        form.addRow(
            _dica(
                "O Claude Code usa o seu login (o mesmo do terminal e do Claude Desktop). Mudanças aqui reabrem o "
                f"Claude Code e valem a partir da próxima resposta. As instruções do {NOME_APP} (respostas resumidas, "
                "como chamar você e as extras) vão só nas conversas pelo app: nada é gravado no projeto."
            )
        )
        return aba

    def _aba_projetos(self) -> QWidget:
        p = self._cfg.projetos
        aba = QWidget()
        coluna = QVBoxLayout(aba)
        coluna.addWidget(_dica("Cada subpasta destas pastas vira um projeto que dá para escolher por voz ou na lista."))
        self._raizes = QListWidget()
        self._raizes.addItems(p.pastas_raiz)
        coluna.addWidget(self._raizes)
        botoes = QHBoxLayout()
        adicionar = QPushButton("Adicionar pasta…")
        remover = QPushButton("Remover")
        adicionar.clicked.connect(self._adicionar_raiz)
        remover.clicked.connect(lambda: [self._raizes.takeItem(self._raizes.row(i)) for i in self._raizes.selectedItems()])
        botoes.addWidget(adicionar)
        botoes.addWidget(remover)
        botoes.addStretch(1)
        coluna.addLayout(botoes)
        form = QFormLayout()
        self._ignorar = QLineEdit(_juntar(p.ignorar))
        self._ignorar.setPlaceholderText("nomes de subpastas para esconder, separados por vírgula")
        form.addRow("Esconder", self._ignorar)
        self._sem_projeto = QCheckBox("Abrir sempre sem projeto (só entra num projeto quando você pedir)")
        self._sem_projeto.setChecked(p.comecar_sem_projeto)
        self._sem_projeto.setToolTip("Desligado, o app abre no último projeto usado.")
        form.addRow("", self._sem_projeto)
        coluna.addLayout(form)
        return aba

    def _aba_janela(self) -> QWidget:
        i = self._cfg.interface
        aba = QWidget()
        form = QFormLayout(aba)
        self._minimizado = QCheckBox("Abrir escondido na bandeja (perto do relógio)")
        self._minimizado.setChecked(i.iniciar_minimizado)
        self._bandeja = QCheckBox("Fechar a janela deixa o assistente ouvindo na bandeja")
        self._bandeja.setChecked(i.fechar_para_bandeja)
        self._no_topo = QCheckBox("Janela sempre por cima das outras")
        self._no_topo.setChecked(i.sempre_no_topo)
        self._compacta = QCheckBox("Com a janela fechada, mostrar o assistente como uma bolinha flutuante")
        self._compacta.setChecked(i.janela_compacta)
        self._iniciar_compacto = QCheckBox("Abrir só a bolinha (a janela completa abre com um clique nela)")
        self._iniciar_compacto.setChecked(i.iniciar_compacto)
        self._bolinha_no_topo = QCheckBox("Bolinha sempre em primeiro plano (por cima de todas as janelas)")
        self._bolinha_no_topo.setChecked(i.bolinha_no_topo)
        self._bolinha_no_topo.setToolTip("Desligado, a bolinha vira uma janela comum, que pode ficar atrás das outras.")
        self._com_windows = QCheckBox("Iniciar junto com o Windows (abre escondido na bandeja, já ouvindo)")
        self._com_windows_antes = inicializacao.ativo()
        self._com_windows.setChecked(self._com_windows_antes)
        for caixa in (
            self._com_windows,
            self._compacta,
            self._iniciar_compacto,
            self._bolinha_no_topo,
            self._minimizado,
            self._bandeja,
            self._no_topo,
        ):
            form.addRow("", caixa)
        return aba

    def accept(self) -> None:
        if self._com_windows.isChecked() != self._com_windows_antes:
            try:
                inicializacao.definir(self._com_windows.isChecked())
            except OSError as erro:
                QMessageBox.warning(self, "Iniciar com o Windows", f"Não consegui mudar essa opção: {erro}")
        super().accept()

    # ------------------------------------------------------------------ ações
    def _adicionar_raiz(self) -> None:
        pasta = QFileDialog.getExistingDirectory(self, "Escolha uma pasta de projetos")
        if pasta:
            self._raizes.addItem(pasta.replace("/", "\\"))

    def _ler_voz(self) -> cfgmod.Voz:
        return cfgmod.Voz(
            motor=self._motor.currentData(),
            voz=self._voz_kokoro.currentData(),
            velocidade=float(self._velocidade.value()),
            voz_sapi=self._voz_windows.currentData() or "",
        )

    def _testar_voz(self) -> None:
        cfg_voz = self._ler_voz()
        self._botao_testar.setEnabled(False)
        self._botao_testar.setText("Gerando…")

        def trabalho() -> None:
            erro = ""
            try:
                import sounddevice as sd

                motor = voz.criar(cfg_voz)
                audio = motor.sintetizar("Olá! É assim que eu vou falar com você.")
                sd.play(audio, motor.taxa)
                sd.wait()
            except Exception as falha:
                log.exception("Falha ao testar a voz")
                erro = str(falha)
            self._voz_testada.emit(erro)

        threading.Thread(target=trabalho, daemon=True).start()

    def _fim_teste_voz(self, erro: str) -> None:
        self._botao_testar.setEnabled(True)
        self._botao_testar.setText("Testar voz" if not erro else "Falhou; testar de novo")

    def resultado(self) -> cfgmod.Config:
        c = self._cfg
        c.ativacao.modo = self._modo.currentData()
        c.ativacao.nome = self._nome.text().strip() or NOME_ATIVACAO_PADRAO
        c.ativacao.apelidos = _separar(self._apelidos.text())
        c.ativacao.janela_conversa_s = float(self._janela.value())
        c.ativacao.similaridade_minima = float(self._similaridade.value())
        c.ativacao.responder_ao_chamado = self._responder.isChecked()
        c.ativacao.nome_so_para_acordar = self._so_acordar.isChecked()
        c.ativacao.palavra_parar = self._palavra_parar.text().strip() or "jabuticabal"
        c.ativacao.palavra_enviar = self._palavra_enviar.text().strip() or "câmbio"
        c.ativacao.espera_envio_s = float(self._espera_envio.value())
        c.ativacao.juntar_pedido_s = float(self._juntar.value())
        c.saudacao = self._ler_saudacao()
        c.audio.microfone = self._microfone.currentData() or ""
        c.audio.saida = self._saida.currentData() or ""
        c.audio.limiar_vad = float(self._limiar.value())
        c.audio.silencio_fim_ms = int(self._silencio.value())
        c.audio.volume = float(self._volume.value())
        c.audio.sons = self._sons.isChecked()
        c.voz = self._ler_voz()
        c.reconhecimento.modelo = self._modelo_rec.currentData()
        c.reconhecimento.dispositivo = self._dispositivo_rec.currentData()
        c.reconhecimento.pastas_cuda = _separar(self._pastas_cuda.text())
        c.reconhecimento.modelo_ativacao = self._modelo_leve.currentData() or ""
        c.espera.comecar_em_espera = self._comecar_em_espera.isChecked()
        c.espera.voltar_apos_min = float(self._voltar_espera.value())
        c.claude.modo_permissao = self._modo_permissao.currentData()
        c.claude.modelo = self._modelo_claude.currentData() or ""
        c.claude.esforco = self._esforco.currentData()
        c.claude.conversa_nova_ao_abrir = self._nova_ao_abrir.isChecked()
        c.claude.retomar_conversa = self._retomar.isChecked()
        c.claude.narrar_progresso = self._narrar.isChecked()
        c.claude.respostas_resumidas = self._resumir.isChecked()
        c.claude.tempo_aprovacao_s = float(self._tempo_aprovacao.value())
        c.claude.instrucoes_extras = self._extras.toPlainText().strip()
        c.projetos.pastas_raiz = [self._raizes.item(i).text() for i in range(self._raizes.count())]
        c.projetos.ignorar = _separar(self._ignorar.text())
        c.projetos.comecar_sem_projeto = self._sem_projeto.isChecked()
        c.interface.iniciar_minimizado = self._minimizado.isChecked()
        c.interface.fechar_para_bandeja = self._bandeja.isChecked()
        c.interface.sempre_no_topo = self._no_topo.isChecked()
        c.interface.janela_compacta = self._compacta.isChecked()
        c.interface.iniciar_compacto = self._iniciar_compacto.isChecked()
        c.interface.bolinha_no_topo = self._bolinha_no_topo.isChecked()
        c.interface.prioridade_baixa = self._prioridade.isChecked()
        return c
