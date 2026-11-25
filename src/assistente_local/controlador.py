"""O maestro do app: liga microfone, reconhecimento, voz, Claude, histórico e interface.

Roda numa thread própria com um loop asyncio. A interface usa os métodos públicos
(seguros para chamar de qualquer thread) e recebe tudo o que acontece pela função
``emitir``, sempre com objetos do módulo ``eventos``.
"""

from __future__ import annotations

import asyncio
import copy
import gc
import logging
import math
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Awaitable, Callable

from . import caminhos, modelos, texto_fala, voz
from . import config as cfgmod
from . import eventos as ev
from .ativacao import (
    DetectorEnvio,
    DetectorNome,
    DetectorParada,
    achar_projeto,
    eh_cancelamento,
    interpretar_resposta,
    parece_eco,
)
from .audio import sons
from .audio.ouvinte import Ouvinte
from .audio.reprodutor import Reprodutor
from .audio.segmentador import Fala
from .estado import Estado as EstadoSalvo
from .historico import Historico
from .ponte_claude import (
    EventoAcao,
    EventoFim,
    EventoInfo,
    EventoTexto,
    PonteClaude,
    eh_erro_de_login,
    nome_do_modelo,
    normalizar_esforco,
    normalizar_modelo,
    rotulo_esforco,
    rotulo_permissao,
)
from .saudacao import TAXA as TAXA_SAUDACAO
from .saudacao import Saudacoes, voz_confere

log = logging.getLogger(__name__)

NOME_AREA_LIVRE = "Área livre"

# Pausa entre dois trechos falados: a mesma que o Kokoro põe entre frases dentro de um trecho.
_PAUSA_ENTRE_TRECHOS_S = 0.25

# Ferramentas que só leem: depois delas, completar o pedido ainda junta com ele (o Claude não mexeu em nada).
_SO_LEITURA = frozenset(
    {"Read", "Glob", "Grep", "LS", "NotebookRead", "WebSearch", "WebFetch", "TodoWrite", "ToolSearch"}
)


def _mesmo_caminho(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _devolver_memoria_ao_windows() -> None:
    """Depois de descarregar modelos, devolve ao Windows as páginas de memória que sobraram."""
    gc.collect()
    if os.name != "nt":
        return
    try:
        import win32api
        import win32process

        win32process.SetProcessWorkingSetSize(win32api.GetCurrentProcess(), -1, -1)
    except Exception as erro:
        log.debug("Não consegui reduzir a memória em uso: %s", erro)


@dataclass
class _Aprovacao:
    id: str
    futuro: asyncio.Future
    pergunta: str


class _FerramentasDoApp:
    """O que o Claude pode fazer no próprio app, pelas ferramentas do servidor "app" (ver ponte_claude)."""

    def __init__(self, controlador: "Controlador") -> None:
        self._c = controlador

    async def listar_projetos(self) -> tuple[str, bool]:
        atual = self._c.projeto_atual
        linhas = []
        for projeto in self._c.projetos():
            marca = "  (atual)" if atual is not None and _mesmo_caminho(projeto.caminho, atual.caminho) else ""
            linhas.append(f"- {projeto.nome}: {projeto.caminho}{marca}")
        return "Projetos que o app conhece:\n" + "\n".join(linhas), False

    def _achar(self, projeto: str) -> cfgmod.Projeto | None:
        texto = projeto.strip().strip('"')
        if not texto:
            return None
        if os.path.isabs(texto):
            return self._c._projeto_por_caminho(texto)
        return achar_projeto(texto, self._c.projetos())

    async def trocar_projeto(self, projeto: str, continuar_com: str) -> tuple[str, bool]:
        alvo = self._achar(projeto)
        if alvo is None:
            nomes = ", ".join(p.nome for p in self._c.projetos())
            return f"Não achei o projeto {projeto!r}. Os projetos são: {nomes}.", True
        atual = self._c.projeto_atual
        if atual is not None and _mesmo_caminho(alvo.caminho, atual.caminho):
            return f"Você já está no projeto {alvo.nome} ({alvo.caminho}).", False
        self._c._depois_do_turno(
            lambda: self._c._trocar_projeto(alvo, anunciar=False, continuar_com=continuar_com, parar=False)
        )
        extra = " e manda para você, lá, o pedido de continuar_com" if continuar_com.strip() else ""
        return (
            f"Combinado: quando a sua resposta terminar, o app troca para o projeto {alvo.nome} ({alvo.caminho})"
            f"{extra}. Avise o usuário em poucas palavras.",
            False,
        )

    async def nova_conversa(self, continuar_com: str) -> tuple[str, bool]:
        self._c._depois_do_turno(
            lambda: self._c._nova_conversa(anunciar=False, continuar_com=continuar_com, parar=False)
        )
        return "Combinado: quando a sua resposta terminar, o app começa uma conversa nova neste projeto.", False

    async def copiar(self, texto: str) -> tuple[str, bool]:
        if not texto:
            return "Nada para copiar.", True
        self._c._emitir(ev.Copiar(texto, "o texto pedido"))
        return "Copiado para a área de transferência do usuário.", False

    async def abrir(self, caminho: str, na_pasta: bool) -> tuple[str, bool]:
        alvo = Path(caminho.strip().strip('"'))
        if not alvo.is_absolute() and self._c.projeto_atual is not None:
            alvo = Path(self._c.projeto_atual.caminho) / alvo
        try:
            existe = alvo.exists()
        except OSError:
            existe = False
        if not existe:
            return f"Não existe: {alvo}", True
        self._c._emitir(ev.Abrir(str(alvo.resolve()), na_pasta))
        return f"Aberto no PC do usuário: {alvo.resolve()}", False

    async def desfazer(self) -> tuple[str, bool]:
        if not self._c._ponte.pode_desfazer:
            return "Não há alterações de arquivo para desfazer (comandos de terminal não são desfeitos).", True
        self._c._depois_do_turno(lambda: self._c._desfazer(anunciar=False))
        return (
            "Combinado: quando a sua resposta terminar, o app desfaz as alterações de arquivo do último pedido "
            "que alterou arquivos.",
            False,
        )

    async def ajustar_claude(self, esforco: str, modelo: str) -> tuple[str, bool]:
        novo_esforco = normalizar_esforco(esforco) if esforco.strip() else None
        novo_modelo = normalizar_modelo(modelo) if modelo.strip() else None
        if esforco.strip() and novo_esforco is None:
            return f"Esforço {esforco!r} não existe. Use low, medium, high, xhigh, max ou padrao.", True
        if modelo.strip() and novo_modelo is None:
            return f"Modelo {modelo!r} não reconhecido. Use opus, sonnet, haiku ou padrao.", True
        atual = self._c.cfg.claude
        mudancas = {}
        if novo_esforco is not None and novo_esforco != atual.esforco:
            mudancas["esforco"] = novo_esforco
        if novo_modelo is not None and novo_modelo != atual.modelo:
            mudancas["modelo"] = novo_modelo
        modelo_final = nome_do_modelo(mudancas.get("modelo", atual.modelo))
        esforco_final = rotulo_esforco(mudancas.get("esforco", atual.esforco))
        if not mudancas:
            return f"Já está assim: {modelo_final}, esforço {esforco_final}.", False
        self._c._depois_do_turno(lambda: self._c._mudar_claude(**mudancas))
        return (
            f"Combinado: a partir da próxima resposta, {modelo_final} com esforço {esforco_final} (fica salvo). "
            "O app reabre o Claude Code quando esta resposta terminar; a conversa continua.",
            False,
        )


class Controlador:
    def __init__(
        self,
        cfg: cfgmod.Config,
        emitir: Callable[[object], None],
        *,
        simular_microfone: bool = False,
        sem_som: bool = False,
        estado_salvo: EstadoSalvo | None = None,
        historico: Historico | None = None,
        projeto_inicial: cfgmod.Projeto | None = None,
    ):
        from .reconhecimento import Reconhecedor

        self.cfg = cfg
        self._emitir_externo = emitir
        self._simular_microfone = simular_microfone
        self._projeto_forcado = projeto_inicial
        self._estado_salvo = estado_salvo or EstadoSalvo()
        self.historico = historico or Historico()
        self._reconhecedor = Reconhecedor(cfg.reconhecimento)
        self._reprodutor = Reprodutor(cfg.audio.saida, cfg.audio.volume, silencioso=sem_som)
        self._motor_voz = None
        self._voz_de_reserva = False  # a voz escolhida não carregou e quem fala é a reserva do Windows
        self._ouvinte: Ouvinte | None = None
        self._ponte = PonteClaude(
            cfg.claude, self._pedir_permissao, _FerramentasDoApp(self)
        )
        self._saudacoes = Saudacoes(cfg.saudacao, cfg.voz)
        self._criar_detectores()
        self._executor_stt = ThreadPoolExecutor(1, thread_name_prefix="reconhecimento")
        self._executor_voz = ThreadPoolExecutor(1, thread_name_prefix="voz")

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._parar: asyncio.Event | None = None
        self._trava_fala: asyncio.Lock | None = None
        self._trava_voz: asyncio.Lock | None = None
        self._falas: asyncio.Queue | None = None
        self.pronto = threading.Event()

        self._carregado = False
        self._em_espera = False
        self._acordando = False
        self._ultimo_uso = time.monotonic()
        self._comeco_de_sessao = True  # a próxima chamada ganha a saudação
        self._tarefa_saudacao: asyncio.Task | None = None
        self._erro_fatal = ""
        self._gravando = False
        self._transcrevendo = False
        self._pensando = False
        self._falando = False
        self._mic_ligado = True
        self._microfone_ok = True
        self._aprovacao: _Aprovacao | None = None
        self._janela_ate = 0.0
        self._fim_ultima_fala = 0.0
        self._texto_falando = ""
        self._ultima_fala = ""
        self._ultima_resposta = ""
        self._ultimos_arquivos: list[str] = []
        self._fala_cancelada = False
        self._pendentes: list[tuple[str, str]] = []  # (id, pedido) esperando o Claude terminar
        # O pedido falado que ainda não foi: espera um silêncio de `espera_envio_s` ou a palavra de envio.
        self._rascunho: list[str] = []
        self._rascunho_inicio = 0.0
        self._rascunho_ate = 0.0
        self._fim_voz = 0.0  # quando a sua última fala terminou (time.monotonic)
        self._tarefa_envio: asyncio.Task | None = None
        self._tratando_fala = False
        # O turno em andamento, para juntar um complemento que chegue logo depois.
        self._texto_turno = ""
        self._inicio_turno = 0.0
        self._turno_agiu = False  # o Claude já usou uma ferramenta que muda alguma coisa
        self._refazer_com = ""  # pedido inteiro para mandar de novo assim que o turno interrompido acabar
        self._apos_turno: list[Callable[[], Awaitable[None]]] = []  # pedidos do Claude ao app (trocar projeto...)
        self._projeto: cfgmod.Projeto | None = None
        self._tarefa_turno: asyncio.Task | None = None
        self._ultima_narracao = 0.0
        self._estado_emitido: tuple[ev.Estado, str] | None = None

    # ================================================================== API pública (qualquer thread)
    def iniciar(self) -> None:
        self._thread = threading.Thread(target=self._rodar, name="controlador", daemon=True)
        self._thread.start()

    def encerrar(self, timeout: float = 12.0) -> None:
        if self._loop is not None and self._parar is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._parar.set)
        if self._thread is not None:
            self._thread.join(timeout)

    def enviar_texto(self, texto: str) -> None:
        self._agendar(self._comando(texto, origem="teclado"))

    def responder_aprovacao(self, id_: str, aprovado: bool, sempre: bool = False) -> None:
        self._chamar(self._resolver_aprovacao, id_, aprovado, sempre, "janela")

    def interromper(self) -> None:
        self._agendar(self._parar_tudo(avisar=True))

    def nova_conversa(self) -> None:
        self._agendar(self._nova_conversa())

    def trocar_projeto(self, caminho: str) -> None:
        self._agendar(self._trocar_projeto_por_caminho(caminho))

    def continuar_conversa(self, caminho_projeto: str, sessao: str) -> None:
        self._agendar(self._continuar_conversa(caminho_projeto, sessao))

    def definir_microfone(self, ligado: bool) -> None:
        self._chamar(self._definir_microfone, ligado)

    def repetir(self) -> None:
        self._agendar(self._falar(self._ultima_fala or "Ainda não falei nada nesta conversa."))

    def parar_fala(self) -> None:
        self._chamar(self._parar_fala)

    def enviar_rascunho(self) -> None:
        """Manda já o pedido que você está falando (o mesmo que dizer a palavra de envio)."""
        self._chamar(self._enviar_rascunho)

    def descartar_rascunho(self) -> None:
        self._chamar(self._descartar_rascunho, True)

    def tirar_da_fila(self, id_: str) -> None:
        self._chamar(self._tirar_da_fila, id_)

    def aplicar_config(self, cfg: cfgmod.Config) -> None:
        self._agendar(self._aplicar_config(cfg))

    def mudar_claude(self, **mudancas: str) -> None:
        """Modelo ou esforço escolhido na janela (no chip lá embaixo)."""
        self._agendar(self._mudar_claude_pela_janela(mudancas))

    def abrir_login(self) -> bool:
        return self._ponte.abrir_login()

    def confirmar_login(self) -> None:
        self._agendar(self._confirmar_login())

    def projetos(self) -> list[cfgmod.Projeto]:
        livre = cfgmod.Projeto(NOME_AREA_LIVRE, str(caminhos.pasta_dados() / "area-livre"))
        return [livre, *cfgmod.projetos_disponiveis(self.cfg)]

    def nivel_da_voz(self) -> float:
        """Volume do que o Hércules está falando agora (0 a ~0,5); a interface pulsa com ele."""
        return self._reprodutor.nivel

    def _emitir_info_claude(self, modelo: str = "", permissao: str = "") -> None:
        """Modelo, esforço e permissões para a interface (o modelo vem confirmado pela sessão, se já abriu)."""
        c = self.cfg.claude
        if not modelo and self._ponte.info[0]:
            modelo, permissao = self._ponte.info
        self._emitir(
            ev.InfoClaude(
                nome_do_modelo(modelo or c.modelo),
                rotulo_esforco(c.esforco),
                rotulo_permissao(permissao or c.modo_permissao),
                confirmado=bool(modelo),
            )
        )

    @property
    def projeto_atual(self) -> cfgmod.Projeto | None:
        return self._projeto

    @property
    def microfone_ligado(self) -> bool:
        return self._mic_ligado

    # ================================================================== infraestrutura
    def _agendar(self, corrotina) -> None:
        if self._loop is None or self._loop.is_closed():
            corrotina.close()
            log.warning("Pedido ignorado: o assistente ainda não está rodando.")
            return
        asyncio.run_coroutine_threadsafe(self._seguro(corrotina), self._loop)

    def _chamar(self, funcao, *argumentos) -> None:
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(funcao, *argumentos)

    async def _seguro(self, corrotina) -> None:
        try:
            await corrotina
        except asyncio.CancelledError:
            raise
        except Exception as erro:
            log.exception("Erro inesperado")
            self._emitir(ev.Aviso(f"Algo deu errado: {erro}", "erro"))

    def _emitir(self, evento: object) -> None:
        try:
            self.historico.registrar_evento(evento)
        except Exception:
            log.exception("Falha ao gravar o histórico")
        try:
            self._emitir_externo(evento)
        except Exception:
            log.exception("Falha ao avisar a interface")

    def _criar_detectores(self) -> None:
        a = self.cfg.ativacao
        self._detector = DetectorNome(a.nome, a.apelidos, a.similaridade_minima)
        # O modelo leve erra mais a grafia: aceita um pouco menos de semelhança (o principal confere depois).
        self._detector_leniente = DetectorNome(a.nome, a.apelidos, max(0.6, a.similaridade_minima - 0.08))
        self._parada = DetectorParada(a.palavra_parar, self._detector)
        self._parada_leniente = DetectorParada(a.palavra_parar, self._detector_leniente, minimo=0.72)
        self._envio = DetectorEnvio(a.palavra_enviar)

    def _som(self, nome: str) -> None:
        if self.cfg.audio.sons and not self._falando:
            self._reprodutor.tocar(sons.som(nome), sons.TAXA)

    def _dica(self) -> str:
        a = self.cfg.ativacao
        nomes = [a.nome, "Claude", a.palavra_parar.capitalize(), a.palavra_enviar.capitalize()]
        if self._projeto and self._projeto.nome != NOME_AREA_LIVRE:
            nomes.append(self._projeto.nome)
        return ", ".join(dict.fromkeys(n for n in nomes if n)) + "."

    # ================================================================== estado para a interface
    def _calcular_estado(self) -> tuple[ev.Estado, str]:
        if self._erro_fatal:
            return ev.Estado.ERRO, self._erro_fatal
        if not self._carregado:
            return ev.Estado.CARREGANDO, ""
        if self._aprovacao is not None:
            return ev.Estado.APROVACAO, self._aprovacao.pergunta
        if self._falando:
            return ev.Estado.FALANDO, ""
        if self._acordando:
            return ev.Estado.ACORDANDO, ""
        if self._transcrevendo:
            return ev.Estado.TRANSCREVENDO, ""
        if self._rascunho:  # você está no meio de um pedido (mesmo com o Claude ainda no anterior)
            if self._gravando:
                return ev.Estado.GRAVANDO, ""
            return ev.Estado.RASCUNHO, self.cfg.ativacao.palavra_enviar
        if self._pensando:
            return ev.Estado.PENSANDO, ""
        if not self._mic_ligado:
            return ev.Estado.MUDO, ""
        if not self._microfone_ok:
            return ev.Estado.SEM_MICROFONE, ""
        if self._em_espera and self.cfg.ativacao.modo != "continuo":
            # Cochilando, ele só procura o nome em segundo plano: não mostra que está ouvindo você.
            return ev.Estado.ESPERA, self.cfg.ativacao.nome
        if self._gravando:
            return ev.Estado.GRAVANDO, ""
        if self._acordado_sem_nome() or time.monotonic() < self._janela_ate:
            return ev.Estado.CONVERSA, ""
        return ev.Estado.OUVINDO, self.cfg.ativacao.nome

    def _atualizar_estado(self) -> None:
        novo = self._calcular_estado()
        if novo != self._estado_emitido:
            self._estado_emitido = novo
            self._emitir(ev.EstadoMudou(*novo))

    def _abrir_janela(self) -> None:
        duracao = float(self.cfg.ativacao.janela_conversa_s)
        if self._em_espera:  # cochilando (ex.: depois da palavra de parar), só o nome acorda
            self._atualizar_estado()
            return
        if duracao > 0 and self._loop is not None:
            self._janela_ate = time.monotonic() + duracao
            self._loop.call_later(duracao + 0.05, self._atualizar_estado)
            if self._aprovacao is None:
                self._aceitar_respostas_curtas(self._janela_ate)  # ex.: "sim" para uma pergunta do Claude
        self._atualizar_estado()

    def _aceitar_respostas_curtas(self, ate: float) -> None:
        """Até ``ate``, o microfone aceita falas bem curtas ("sim", "não"); fora disso elas são ruído."""
        if self._ouvinte is not None:
            self._ouvinte.aceitar_falas_curtas_ate(ate)

    # ================================================================== ciclo de vida
    def _rodar(self) -> None:
        try:
            asyncio.run(self._principal())
        except Exception:
            log.exception("O controlador parou com erro")

    async def _principal(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._parar = asyncio.Event()
        self._trava_fala = asyncio.Lock()
        self._trava_voz = asyncio.Lock()
        self._falas = asyncio.Queue()
        try:
            await self._carregar()
        except Exception as erro:
            log.exception("Falha ao iniciar")
            self._erro_fatal = str(erro)
            self._atualizar_estado()
            self._emitir(ev.Aviso(f"Não consegui iniciar: {erro}", "erro"))
            await self._parar.wait()
            await self._desligar()
            return
        tarefas = [
            asyncio.create_task(self._laco_falas(), name="falas"),
            asyncio.create_task(self._manutencao(), name="manutencao"),
            asyncio.create_task(self._seguro(self._gravar_saudacoes()), name="saudacoes"),
        ]
        self.pronto.set()
        await self._checar_login()
        await self._parar.wait()
        for tarefa in tarefas:
            tarefa.cancel()
        await self._desligar()

    async def _manutencao(self) -> None:
        """A cada 10 s: reconecta o microfone que caiu e volta para a espera depois de um tempo sem uso."""
        while True:
            await asyncio.sleep(10)
            try:
                ouvinte = self._ouvinte
                if (
                    not self._simular_microfone
                    and ouvinte is not None
                    and ouvinte.microfone_ok is False
                    and not self._falando
                ):
                    await self._loop.run_in_executor(None, self._reabrir_audio)
                minutos = float(self.cfg.espera.voltar_apos_min)
                if minutos > 0 and not self._em_espera and time.monotonic() - self._ultimo_uso > minutos * 60:
                    await self._entrar_em_espera()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Falha na manutenção")

    # ================================================================== modo em espera
    def _acordar(self) -> None:
        """Você chamou: carrega a voz e abre o Claude Code em paralelo (o reconhecimento carrega na transcrição)."""
        agora = time.monotonic()
        minutos = float(self.cfg.espera.voltar_apos_min) or 10.0
        if self._em_espera or agora - self._ultimo_uso > max(60.0, minutos * 60):
            self._comeco_de_sessao = True  # depois de um tempo parado: a chamada ganha a saudação
        self._ultimo_uso = agora
        if not self._em_espera:
            return
        self._em_espera = False
        log.info("Acordando: carregando voz e Claude Code.")
        asyncio.create_task(self._seguro(self._garantir_voz()))
        asyncio.create_task(self._seguro(self._preaquecer_claude()))
        self._atualizar_estado()

    async def _preaquecer_claude(self) -> None:
        try:
            await self._ponte.preaquecer()
        except Exception as erro:
            log.warning("Falha ao abrir o Claude Code: %s", erro)
            self._emitir(ev.Aviso(str(erro), "erro"))

    async def _entrar_em_espera(self) -> None:
        """Solta o que só é preciso depois de ser chamado: reconhecimento preciso, voz e Claude Code."""
        if self._em_espera or self._pensando or self._falando or self._transcrevendo or self._aprovacao is not None:
            return
        self._em_espera = True
        self._atualizar_estado()
        if self._reconhecedor.pode_esperar:
            await self._loop.run_in_executor(self._executor_stt, self._reconhecedor.liberar_principal)
        if not self._em_espera:
            return  # chamaram no meio do caminho
        self._motor_voz = None
        try:
            await self._ponte.descansar()
        except Exception as erro:
            log.warning("Falha ao fechar o Claude Code: %s", erro)
        if self._em_espera:
            _devolver_memoria_ao_windows()
            log.info("Em espera: só a detecção de voz e o modelo leve ficaram carregados.")

    async def _garantir_voz(self) -> bool:
        if self._motor_voz is not None:
            return True
        async with self._trava_voz:
            if self._motor_voz is None:
                try:
                    motor = await self._loop.run_in_executor(self._executor_voz, voz.criar, self.cfg.voz, None)
                    reserva = not voz_confere(motor, self.cfg.voz)
                    if reserva and not self._voz_de_reserva:
                        self._emitir(ev.Aviso(f"A voz escolhida não carregou; usando a {motor.descricao}."))
                    self._motor_voz, self._voz_de_reserva = motor, reserva
                except Exception as erro:
                    log.exception("Falha ao carregar a voz")
                    self._emitir(ev.Aviso(f"Não consegui carregar a voz: {erro}", "erro"))
                    return False
        return True

    def _reabrir_audio(self) -> bool:
        """Atualiza a lista de dispositivos do Windows e reabre saída e microfone (roda fora do loop)."""
        import sounddevice as sd

        self._ouvinte.fechar_microfone()
        self._reprodutor.fechar()
        try:
            sd._terminate()  # o PortAudio só enxerga aparelhos novos depois de reiniciar
            sd._initialize()
        except Exception as erro:
            log.warning("Falha ao reiniciar o áudio: %s", erro)
        try:
            self._reprodutor.iniciar()
        except Exception as erro:
            log.warning("Saída de áudio indisponível: %s", erro)
        return self._ouvinte.tentar_abrir()

    def _ao_estado_microfone(self, ok: bool, mensagem: str) -> None:  # qualquer thread
        def aplicar() -> None:
            self._microfone_ok = ok
            self._emitir(ev.Aviso(mensagem, "info" if ok else "erro"))
            self._atualizar_estado()

        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(aplicar)
        else:
            self._microfone_ok = ok

    async def _carregar(self) -> None:
        loop = asyncio.get_running_loop()

        def progresso(mensagem: str, fracao: float | None = None) -> None:
            self._emitir(ev.Carregando(mensagem, fracao))

        def progresso_de_thread(mensagem: str, fracao: float | None = None) -> None:
            loop.call_soon_threadsafe(progresso, mensagem, fracao)

        self._atualizar_estado()
        progresso("Preparando o áudio")
        await loop.run_in_executor(None, self._reprodutor.iniciar)
        if self.cfg.voz.motor == "kokoro" and not modelos.kokoro_pronto():
            await loop.run_in_executor(self._executor_voz, modelos.baixar_kokoro, progresso_de_thread)
        descricao_reconhecimento = await loop.run_in_executor(
            self._executor_stt, self._reconhecedor.preparar, progresso_de_thread
        )
        em_espera = bool(self.cfg.espera.comecar_em_espera) and self._reconhecedor.pode_esperar
        if not em_espera:
            progresso("Carregando o reconhecimento de voz")
            await loop.run_in_executor(self._executor_stt, self._reconhecedor.carregar_principal)
            progresso("Carregando a voz")
            await self._garantir_voz()
        progresso("Ligando o microfone")
        self._ouvinte = Ouvinte(self.cfg.audio, self._ao_ouvir_fala, self._ao_nivel, self._ao_estado_microfone)
        await loop.run_in_executor(None, self._ouvinte.iniciar, self._simular_microfone)
        progresso("Preparando o Claude Code")
        await self._ponte.iniciar()
        self._em_espera = em_espera
        await self._preparar_projeto(
            self._escolher_projeto_inicial(), anunciar=False, nova=self.cfg.claude.conversa_nova_ao_abrir
        )
        self._ultimo_uso = time.monotonic()
        self._carregado = True
        if em_espera:
            descricao_reconhecimento += " (o preciso carrega quando você chama)"
        self._emitir(
            ev.Pronto(
                descricao_reconhecimento,
                voz.descrever(self.cfg.voz),
                self._ouvinte.nome_dispositivo or ("simulado" if self._simular_microfone else "indisponível"),
                self._reprodutor.nome_dispositivo,
                self._ponte.descricao_cli,
            )
        )
        self._emitir_info_claude()
        self._atualizar_estado()
        self._som("pronto")

    def _escolher_projeto_inicial(self) -> cfgmod.Projeto:
        if self._projeto_forcado is not None:
            return self._projeto_forcado
        projetos = self.projetos()
        if self.cfg.projetos.comecar_sem_projeto:
            return projetos[0]  # a Área livre: só entra num projeto quando você pedir
        salvo = self._estado_salvo.projeto_atual
        if salvo:
            for projeto in projetos:
                if _mesmo_caminho(projeto.caminho, salvo):
                    return projeto
            if os.path.isdir(salvo):
                return cfgmod.Projeto(Path(salvo).name, salvo)
        return projetos[0]

    async def _desligar(self) -> None:
        try:
            if self._pensando:
                await self._ponte.interromper()
            await asyncio.wait_for(self._ponte.fechar(), 10)
        except Exception as erro:
            log.warning("Falha ao fechar o Claude Code: %s", erro)
        if self._ouvinte is not None:
            self._ouvinte.parar()
        self._reprodutor.fechar()
        self._executor_stt.shutdown(wait=False, cancel_futures=True)
        self._executor_voz.shutdown(wait=False, cancel_futures=True)

    # ================================================================== login
    async def _checar_login(self, anunciar: bool = False) -> bool:
        logado = await self._ponte.verificar_login()
        if logado is False:
            self._emitir(ev.LoginNecessario())
            if anunciar:
                await self._falar("O Claude Code precisa de login. As instruções estão na tela.")
            return False
        return True

    async def _confirmar_login(self) -> None:
        if not await self._checar_login():
            await self._falar("Ainda não encontrei o login. Termine de entrar na janela que abriu e tente de novo.")
            return
        try:
            await self._ponte.descansar()  # fecha a sessão aberta antes do login
            await self._ponte.preaquecer()
        except Exception as erro:
            self._emitir(ev.Aviso(str(erro), "erro"))
            return
        self._em_espera = False
        self._ultimo_uso = time.monotonic()
        self._emitir(ev.LoginConfirmado())
        await self._falar("Pronto, agora estou ligado ao Claude.")
        self._abrir_janela()

    # ================================================================== projeto e conversa
    async def _preparar_projeto(
        self,
        projeto: cfgmod.Projeto,
        anunciar: bool = True,
        nova: bool = False,
        sessao_forcada: str | None = None,
    ) -> None:
        """Escolhe o projeto e a conversa. O Claude Code só abre agora se o app não estiver em espera."""
        if nova:
            self._estado_salvo.esquecer_sessao(projeto.caminho)
        if sessao_forcada:
            sessao = sessao_forcada
        elif nova or not self.cfg.claude.retomar_conversa:
            sessao = None
        else:
            sessao = self._estado_salvo.sessao(projeto.caminho)
        if projeto.nome == NOME_AREA_LIVRE:
            Path(projeto.caminho).mkdir(parents=True, exist_ok=True)
        self._projeto = projeto
        self._estado_salvo.projeto_atual = projeto.caminho
        retomada = bool(sessao)
        try:
            await self._ponte.definir_destino(projeto.caminho, sessao)
            if not self._em_espera:
                em_uso = await self._ponte.preaquecer()
                retomada = bool(sessao) and em_uso == sessao
        except Exception as erro:
            log.error("Falha ao abrir o Claude Code em %s: %s", projeto.caminho, erro)
            self._emitir(ev.Aviso(str(erro), "erro"))
        self._ultima_resposta = ""
        self._ultimos_arquivos = []
        entradas = self.historico.abrir(projeto.nome, projeto.caminho, sessao)
        self._emitir(ev.ConversaCarregada(projeto.nome, entradas))
        self._emitir(ev.ProjetoAtual(projeto.nome, projeto.caminho, retomada))
        if anunciar:
            await self._falar(f"Projeto {projeto.nome}." + (" Continuando a conversa de antes." if retomada else ""))

    async def _trocar_projeto(
        self, projeto: cfgmod.Projeto, anunciar: bool = True, continuar_com: str = "", parar: bool = True
    ) -> None:
        if self._projeto is not None and _mesmo_caminho(projeto.caminho, self._projeto.caminho):
            if anunciar:
                await self._falar(f"Já estamos no projeto {projeto.nome}.")
            self._seguir_com(continuar_com)
            return
        if parar:
            await self._parar_tudo()
            await self._esperar_turno()
        await self._preparar_projeto(projeto, anunciar=anunciar)
        self._seguir_com(continuar_com)

    def _seguir_com(self, pedido: str) -> None:
        """Depois de trocar de projeto ou de conversa, manda o resto do pedido para o Claude, se houver."""
        pedido = (pedido or "").strip()
        if pedido:
            self._emitir(ev.FalaUsuario(pedido, "continuação"))
            self._mandar_para_o_claude(pedido, juntar=False)
        else:
            self._abrir_janela()

    def _depois_do_turno(self, acao: Callable[[], Awaitable[None]]) -> None:
        self._apos_turno.append(acao)

    def _projeto_por_caminho(self, caminho: str) -> cfgmod.Projeto | None:
        for projeto in self.projetos():
            if _mesmo_caminho(projeto.caminho, caminho):
                return projeto
        if os.path.isdir(caminho):
            return cfgmod.Projeto(Path(caminho).name, caminho)
        return None

    async def _trocar_projeto_por_caminho(self, caminho: str) -> None:
        projeto = self._projeto_por_caminho(caminho)
        if projeto is not None:
            await self._trocar_projeto(projeto)

    async def _continuar_conversa(self, caminho_projeto: str, sessao: str) -> None:
        projeto = self._projeto_por_caminho(caminho_projeto)
        if projeto is None:
            self._emitir(ev.Aviso(f"A pasta {caminho_projeto} não existe mais.", "erro"))
            return
        await self._parar_tudo()
        await self._esperar_turno()
        await self._preparar_projeto(projeto, anunciar=True, sessao_forcada=sessao)
        self._abrir_janela()

    async def _nova_conversa(self, anunciar: bool = True, continuar_com: str = "", parar: bool = True) -> None:
        if parar:
            await self._parar_tudo()
            await self._esperar_turno()
        if self._projeto is not None:
            await self._preparar_projeto(self._projeto, anunciar=False, nova=True)
        self._emitir(ev.ConversaNova())
        if anunciar:
            await self._falar("Certo, nova conversa.")
        self._seguir_com(continuar_com)

    async def _desfazer(self, anunciar: bool = True) -> None:
        if self._pensando:
            if anunciar:
                await self._falar("Espere ele terminar, e aí eu desfaço.")
            return
        try:
            desfeito = await self._ponte.desfazer()
        except Exception as erro:
            log.warning("Falha ao desfazer: %s", erro)
            desfeito = False
        if desfeito:
            self._emitir(ev.Aviso("Alterações de arquivo do último pedido desfeitas."))
            if anunciar:
                await self._falar("Pronto, desfiz as alterações nos arquivos do último pedido.")
        elif anunciar:
            await self._falar("Não tenho nenhuma alteração de arquivo para desfazer.")
        self._abrir_janela()

    async def _esperar_turno(self, limite: float = 20.0) -> None:
        tarefa = self._tarefa_turno
        if tarefa is None or tarefa.done() or tarefa is asyncio.current_task():
            return
        try:
            await asyncio.wait_for(asyncio.shield(tarefa), limite)
        except (asyncio.TimeoutError, Exception) as erro:
            log.warning("O turno anterior não terminou a tempo: %s", erro)

    async def _parar_tudo(self, avisar: bool = False) -> None:
        self._limpar_fila()
        self._descartar_rascunho()
        self._refazer_com = ""
        self._parar_fala()
        if self._aprovacao is not None:
            self._resolver_aprovacao(self._aprovacao.id, False, False, "parar")
        if self._pensando:
            await self._ponte.interromper()
        if avisar:
            self._som("ok")

    async def _mudar_claude_pela_janela(self, mudancas: dict[str, str]) -> None:
        atual = self.cfg.claude
        mudancas = {campo: valor for campo, valor in mudancas.items() if getattr(atual, campo) != valor}
        if not mudancas:
            return
        modelo = nome_do_modelo(mudancas.get("modelo", atual.modelo))
        esforco = rotulo_esforco(mudancas.get("esforco", atual.esforco))
        if self._pensando:  # o Claude Code só fecha depois desta resposta (a ponte faz um pedido por vez)
            self._emitir(ev.Aviso(f"{modelo} com esforço {esforco} vale a partir da próxima resposta."))
        else:
            self._emitir(ev.Aviso(f"Agora: {modelo} com esforço {esforco}."))
        await self._mudar_claude(**mudancas)

    async def _mudar_claude(self, **mudancas) -> None:
        """Outro esforço ou modelo (por voz ou na janela): salva, reabre o Claude Code (a conversa continua) e avisa a janela."""
        novo = copy.deepcopy(self.cfg)
        for campo, valor in mudancas.items():
            setattr(novo.claude, campo, valor)
        cfgmod.salvar(novo)
        self.cfg = novo
        self._ponte.cfg = novo.claude
        self._ponte.info = ("", "")
        self._emitir_info_claude()
        self._emitir(ev.ConfigAlterada(novo))
        try:
            await self._ponte.descansar()  # a próxima pergunta reabre com as opções novas, na mesma conversa
        except Exception as erro:
            log.warning("Falha ao fechar o Claude Code: %s", erro)
        if not self._em_espera:
            asyncio.create_task(self._seguro(self._preaquecer_claude()))
        log.info("Claude ajustado por voz: %s", mudancas)

    async def _dormir_agora(self) -> None:
        """A palavra de parar: interrompe tudo e volta a cochilar. Só acorda de novo quando chamam o nome."""
        await self._parar_tudo(avisar=True)
        self._janela_ate = 0.0
        self._aceitar_respostas_curtas(0.0)
        await self._esperar_turno(limite=8.0)  # o Claude termina de parar (resposta interrompida não é falada)
        prazo = time.monotonic() + 3.0
        while self._falando and time.monotonic() < prazo:
            await asyncio.sleep(0.05)
        await self._entrar_em_espera()
        if not self._em_espera:
            # Algo ainda ocupado impediu de soltar os modelos; mesmo assim, só o nome acorda de novo.
            self._em_espera = True
            self._atualizar_estado()
        log.info("Palavra de parar: voltei a cochilar.")

    def _definir_microfone(self, ligado: bool) -> None:
        self._mic_ligado = bool(ligado)
        if self._ouvinte is not None:
            self._ouvinte.definir_mudo(not self._mic_ligado)
        self._atualizar_estado()

    async def _aplicar_config(self, novo: cfgmod.Config) -> None:
        antigo = self.cfg
        self.cfg = novo
        self._criar_detectores()
        if self._ouvinte is not None:
            self._ouvinte.aplicar_config(novo.audio)
        self._reprodutor.volume = novo.audio.volume
        self._ponte.cfg = novo.claude
        if asdict(novo.voz) != asdict(antigo.voz):
            self._motor_voz = None  # carrega a voz nova na próxima fala
            self._voz_de_reserva = False
            if not self._em_espera:
                await self._garantir_voz()
        if asdict(novo.voz) != asdict(antigo.voz) or asdict(novo.saudacao) != asdict(antigo.saudacao):
            self._saudacoes = Saudacoes(novo.saudacao, novo.voz)
            asyncio.create_task(self._seguro(self._gravar_saudacoes()))  # grava as frases novas
        reiniciar = []
        if asdict(novo.reconhecimento) != asdict(antigo.reconhecimento):
            reiniciar.append("reconhecimento de voz")
        if (novo.audio.microfone, novo.audio.saida) != (antigo.audio.microfone, antigo.audio.saida):
            reiniciar.append("microfone e saída de áudio")
        if asdict(novo.claude) != asdict(antigo.claude):
            self._ponte.info = ("", "")
            self._emitir_info_claude()  # o modelo novo é confirmado quando a sessão reabrir
            await self._parar_tudo()
            await self._esperar_turno()
            await self._ponte.descansar()  # reabre com as opções novas
            if not self._em_espera:
                await self._preaquecer_claude()
        mensagem = "Configurações aplicadas."
        if reiniciar:
            mensagem += " Reinicie o app para aplicar: " + ", ".join(reiniciar) + "."
        self._emitir(ev.Aviso(mensagem))
        self._atualizar_estado()

    # ================================================================== falas do usuário
    def _ao_ouvir_fala(self, fala: Fala) -> None:  # thread do ouvinte
        if self._loop is not None and self._falas is not None:
            self._loop.call_soon_threadsafe(self._falas.put_nowait, fala)

    def _ao_nivel(self, nivel: float, gravando: bool) -> None:  # thread do ouvinte
        self._emitir(ev.NivelMicrofone(nivel, gravando and not self._em_espera))
        if gravando != self._gravando and self._loop is not None:
            self._loop.call_soon_threadsafe(self._definir_gravando, gravando)

    def _definir_gravando(self, gravando: bool) -> None:
        self._gravando = gravando
        if not gravando:
            # O corte da fala só acontece depois de `silencio_fim_ms` calado: a voz parou antes disso.
            self._fim_voz = time.monotonic() - self.cfg.audio.silencio_fim_ms / 1000
            if self._rascunho:
                self._adiar_envio()
        if self._rascunho:
            self._emitir_rascunho()
        self._atualizar_estado()

    async def _laco_falas(self) -> None:
        while True:
            fala = await self._falas.get()
            self._tratando_fala = True
            try:
                await self._tratar_fala(fala)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Falha ao tratar uma fala")
            finally:
                self._tratando_fala = False

    async def _tratar_fala(self, fala: Fala) -> None:
        if not self._mic_ligado or not self._carregado:
            return
        comeco = fala.inicio_voz or fala.inicio  # quando a voz começou (sem o trecho guardado de antes)
        durante_fala = self._falando or comeco < self._fim_ultima_fala + 0.2
        texto_falado = self._texto_falando or self._ultima_fala
        acordado = self._acordado_sem_nome()
        esperando_voce = (
            self._aprovacao is not None
            or acordado  # acordado: toda fala é com ele (o eco da própria voz sai mais abaixo)
            or bool(self._rascunho)  # no meio de um pedido: a continuação não precisa do nome
            or (comeco <= self._janela_ate and not durante_fala)
            or (self._completa_pedido(comeco) and not durante_fala)
        )
        if not esperando_voce and self._reconhecedor.tem_modelo_rapido:
            # 1º estágio: o modelo leve, no processador, só procura o nome. A placa de vídeo fica livre.
            previa = await self._loop.run_in_executor(
                self._executor_stt,
                self._reconhecedor.transcrever_rapido,
                fala.audio,
                self._dica(),
                self.cfg.ativacao.nome,
            )
            texto_previa = previa.texto.strip()
            if not texto_previa or (durante_fala and parece_eco(texto_previa, texto_falado)):
                return
            if self._parada_leniente.eh_parada(texto_previa):
                log.info("Palavra de parar (modelo leve): %s", texto_previa)
                await self._dormir_agora()
                return
            deteccao_previa = self._detector_leniente.detectar(texto_previa)
            if not deteccao_previa.ativado:
                log.info("Ouvi sem o nome (%.2f s, modelo leve): %s", previa.tempo_s, texto_previa)
                self._emitir(ev.FalaIgnorada(texto_previa, "não chamou pelo nome"))
                return
            self._acordar()  # chamou: voz e Claude Code já começam a carregar, em paralelo
            if self._quer_saudar():
                # A saudação é fixa: toca já, enquanto o reconhecimento preciso e o Claude carregam.
                self._tarefa_saudacao = asyncio.create_task(
                    self._seguro(self._saudar(com_pedido=bool(deteccao_previa.comando))), name="saudacao"
                )
        # 2º estágio: o modelo principal transcreve com precisão (carrega antes, se estava em espera).
        self._acordando = not self._reconhecedor.principal_carregado
        self._transcrevendo = True
        self._atualizar_estado()
        # Palavra solta, sem contexto, o Whisper erra ("Sim." vira "Sänge."): numa resposta, ele recebe a
        # pergunta e as palavras esperadas.
        if self._aprovacao is not None:
            dica, palavras = f"{self._aprovacao.pergunta} Responda sim ou não.", "sim não pode"
        elif fala.curta:
            dica, palavras = f"{self._ultima_fala} {self._dica()}".strip(), "sim não"
        else:
            dica, palavras = self._dica(), ""
        try:
            transcricao = await self._loop.run_in_executor(
                self._executor_stt, self._reconhecedor.transcrever, fala.audio, dica, palavras
            )
        finally:
            self._acordando = False
            self._transcrevendo = False
            self._atualizar_estado()
        texto = transcricao.texto.strip()
        if not texto:
            return
        log.info("Ouvi (%.2f s, confiança %.2f): %s", transcricao.tempo_s, transcricao.confianca, texto)
        if fala.curta and self._aprovacao is None and interpretar_resposta(texto) is None:
            log.info("Fala curta ignorada (não parece uma resposta): %s", texto)  # tosse, estalo...
            return
        deteccao = self._detector.detectar(texto)
        if durante_fala and parece_eco(texto, texto_falado):
            log.debug("Ignorado (eco da própria voz): %s", texto)
            return
        if self._parada.eh_parada(texto):
            log.info("Palavra de parar: %s", texto)
            await self._dormir_agora()
            return

        if self._aprovacao is not None:
            # O eco da própria voz já saiu acima (pelas palavras); um "sim" logo depois da pergunta vale.
            resposta = interpretar_resposta(deteccao.comando if deteccao.ativado else texto)
            self._emitir(ev.FalaUsuario(texto))
            if resposta is None:
                await self._falar("Não entendi. Responda sim ou não.")
                return
            self._resolver_aprovacao(self._aprovacao.id, resposta, False, "voz")
            return

        if self._rascunho:  # continuação do pedido que você está falando (com ou sem o nome)
            self._receber_trecho(deteccao.comando if deteccao.ativado else texto)
            return
        if deteccao.ativado:
            await self._comando(deteccao.comando, origem="voz", texto_ouvido=texto, inicio_voz=comeco)
            return
        if acordado:  # mesmo por cima da resposta ou com o Claude ocupado (vira rascunho e depois fila)
            await self._comando(texto, origem="voz", texto_ouvido=texto, inicio_voz=comeco)
            return
        livre =(self.cfg.ativacao.modo == "continuo" or comeco <= self._janela_ate) and not self._pensando
        if (livre or self._completa_pedido(comeco)) and not durante_fala:
            await self._comando(texto, origem="voz", texto_ouvido=texto, inicio_voz=comeco)
            return
        self._emitir(ev.FalaIgnorada(texto, "não chamou pelo nome"))

    def _acordado_sem_nome(self) -> bool:
        """O nome só acorda: acordado, ele assume que toda fala é com ele (até a palavra de parar)."""
        a = self.cfg.ativacao
        return a.modo == "continuo" or (a.nome_so_para_acordar and not self._em_espera)

    def _completa_pedido(self, comeco: float) -> bool:
        """Logo depois de mandar um pedido, antes de o Claude mexer em algo, dá para completá-lo sem o nome."""
        limite = self.cfg.ativacao.juntar_pedido_s
        return (
            self._pensando
            and limite > 0
            and bool(self._texto_turno)
            and not self._turno_agiu
            and self._aprovacao is None
            and comeco - self._inicio_turno <= limite
        )

    async def _comando(
        self, comando: str, origem: str, texto_ouvido: str = "", inicio_voz: float | None = None
    ) -> None:
        comando = (comando or "").strip()
        if comando and self._parada.eh_parada(comando):  # a única ordem que o app trata sozinho
            self._emitir(ev.FalaUsuario(texto_ouvido or comando, origem))
            await self._dormir_agora()
            return
        self._acordar()
        saudando = self._tarefa_saudacao is not None and not self._tarefa_saudacao.done()
        if not comando:
            if saudando:
                return  # a saudação já convida você a falar e abre a conversa no fim
            if origem == "voz" and self._quer_saudar():
                self._tarefa_saudacao = asyncio.create_task(self._seguro(self._saudar(com_pedido=False)))
                return
            self._som("ativou")
            if self.cfg.ativacao.responder_ao_chamado and not self._pensando and not self._falando:
                await self._falar("Pode falar.")
            self._abrir_janela()
            return
        if origem == "voz":
            # Falado: vira rascunho e só vai depois de um silêncio (ou da palavra de envio).
            self._receber_trecho(comando, inicio_voz=inicio_voz, cortar_fala=not saudando)
        else:
            self._emitir(ev.FalaUsuario(texto_ouvido or comando, origem))
            self._mandar_para_o_claude(comando)
        if not saudando and origem == "voz" and self._quer_saudar():
            self._tarefa_saudacao = asyncio.create_task(self._seguro(self._saudar(com_pedido=True)))

    # ================================================================== saudação
    def _quer_saudar(self) -> bool:
        quando = self.cfg.saudacao.quando
        comeco, self._comeco_de_sessao = self._comeco_de_sessao, False
        return quando == "sempre" or (quando == "acordar" and comeco)

    async def _saudar(self, com_pedido: bool) -> None:
        """Toca a saudação fixa (voz gravada + música). Não passa pelo Claude."""
        montado = None
        if not self._voz_de_reserva:  # com a reserva, a gravação soaria diferente das respostas
            try:
                montado = await self._loop.run_in_executor(None, self._saudacoes.montar, com_pedido)
            except Exception:
                log.exception("Falha ao montar a saudação")
        if montado is None:  # frases ainda não gravadas: um cumprimento simples
            if not com_pedido:
                await self._falar("Pode falar.")
        else:
            audio, texto = montado
            await self._tocar_audio_falado(audio, TAXA_SAUDACAO, texto)
        self._abrir_janela()

    async def _gravar_saudacoes(self) -> None:
        """Grava as frases da saudação com a voz do app (uma vez; depois tocam na hora)."""
        if self.cfg.saudacao.quando == "nunca":
            return
        saudacoes = self._saudacoes
        await self._loop.run_in_executor(None, saudacoes.preparar_musica)  # compõe a vinheta antes da 1ª chamada
        await self._loop.run_in_executor(None, saudacoes.limpar)  # gravações de outra voz ou de frases antigas
        faltando = await self._loop.run_in_executor(None, saudacoes.faltando)
        if not faltando:
            return
        cfg_voz = self.cfg.voz
        motor = self._motor_voz or await self._loop.run_in_executor(self._executor_voz, voz.criar, cfg_voz, None)
        if not voz_confere(motor, cfg_voz):
            log.warning("Saudação não gravada: a voz escolhida não carregou.")
            return
        feitas = 0
        for texto in faltando:  # uma frase por vez: as falas do Claude não esperam a gravação inteira
            if saudacoes is not self._saudacoes:
                break  # a configuração mudou; a gravação nova cuida do resto
            feitas += await self._loop.run_in_executor(self._executor_voz, saudacoes.gravar, motor, [texto])
        log.info("Saudação: %d frases gravadas.", feitas)
        del motor
        if self._em_espera:
            _devolver_memoria_ao_windows()  # a voz carregada só para gravar já foi solta

    # ================================================================== rascunho (pedido falado ainda não enviado)
    def _receber_trecho(self, trecho: str, inicio_voz: float | None = None, cortar_fala: bool = False) -> None:
        """Junta um trecho falado ao pedido; ele vai depois de `espera_envio_s` calado ou da palavra de envio."""
        trecho, enviar = self._envio.separar(trecho)
        if trecho and eh_cancelamento(trecho):
            if self._rascunho:
                self._descartar_rascunho(avisar=True)
                return
            if self._pendentes:
                self._limpar_fila(avisar=True)
                return
        if trecho:
            if not self._rascunho:
                self._rascunho_inicio = inicio_voz if inicio_voz is not None else time.monotonic()
                self._rascunho_ate = 0.0
                if cortar_fala:
                    self._parar_fala()  # pedido novo por cima da resposta: ele para de falar e escuta
            self._rascunho.append(trecho)
        if not self._rascunho:
            return  # só o nome ou só "câmbio", sem nada para mandar
        if enviar or self.cfg.ativacao.espera_envio_s <= 0:
            self._enviar_rascunho()
            return
        self._adiar_envio()
        if self._tarefa_envio is None or self._tarefa_envio.done():
            self._tarefa_envio = asyncio.create_task(self._seguro(self._esperar_envio()), name="envio")
        self._emitir_rascunho()
        self._atualizar_estado()

    def _adiar_envio(self) -> None:
        """O prazo conta a partir do fim da sua última fala (ou de agora, se não houve fala há pouco)."""
        agora = time.monotonic()
        fim = self._fim_voz if agora - self._fim_voz < 10.0 else agora
        self._rascunho_ate = max(self._rascunho_ate, fim + float(self.cfg.ativacao.espera_envio_s))

    async def _esperar_envio(self) -> None:
        while self._rascunho:
            ocupado = self._gravando or self._tratando_fala or (self._falas is not None and not self._falas.empty())
            if ocupado or time.monotonic() < self._rascunho_ate:
                await asyncio.sleep(0.1)  # enquanto você fala (ou a fala é entendida), o prazo não corre
                continue
            self._enviar_rascunho()

    def _emitir_rascunho(self) -> None:
        texto = " ".join(self._rascunho)
        envia_em = 0.0 if self._gravando or not texto else self._rascunho_ate
        self._emitir(ev.Rascunho(texto, envia_em, self.cfg.ativacao.palavra_enviar))

    def _enviar_rascunho(self) -> None:
        if not self._rascunho:
            return
        pedido = " ".join(self._rascunho)
        inicio = self._rascunho_inicio
        self._rascunho.clear()
        self._rascunho_ate = 0.0
        self._emitir_rascunho()
        self._emitir(ev.FalaUsuario(pedido, "voz"))
        self._mandar_para_o_claude(pedido, comecou=inicio)
        self._atualizar_estado()

    def _descartar_rascunho(self, avisar: bool = False) -> None:
        if not self._rascunho:
            return
        log.info("Pedido descartado antes de ir: %s", " ".join(self._rascunho))
        self._rascunho.clear()
        self._rascunho_ate = 0.0
        self._emitir_rascunho()
        if avisar:
            self._som("ok")
            self._emitir(ev.Aviso("Pedido descartado. Ele não foi para o Claude."))
            self._abrir_janela()  # dá para falar de novo sem o nome
        self._atualizar_estado()

    # ================================================================== fila (pedidos com o Claude ocupado)
    def _emitir_fila(self) -> None:
        self._emitir(ev.Fila(list(self._pendentes)))

    def _limpar_fila(self, avisar: bool = False) -> None:
        if not self._pendentes:
            return
        self._pendentes.clear()
        self._emitir_fila()
        if avisar:
            self._som("ok")
            self._emitir(ev.Aviso("Fila esvaziada. O Claude continua só no pedido atual."))

    def _tirar_da_fila(self, id_: str) -> None:
        antes = len(self._pendentes)
        self._pendentes = [(i, t) for i, t in self._pendentes if i != id_]
        if len(self._pendentes) != antes:
            self._emitir_fila()

    def _pode_juntar(self, comecou: float | None) -> bool:
        """O pedido novo completa o atual? Só se começou logo depois dele e o Claude ainda não mexeu em nada."""
        limite = self.cfg.ativacao.juntar_pedido_s
        if limite <= 0 or not self._texto_turno or self._turno_agiu or self._aprovacao is not None:
            return False
        comecou = time.monotonic() if comecou is None else comecou
        return comecou - self._inicio_turno <= limite

    async def _interromper_para_juntar(self) -> None:
        # Com o Claude Code ainda abrindo, interromper não faz nada: espera a pergunta sair e aí interrompe.
        prazo = time.monotonic() + 15.0
        while self._refazer_com and self._pensando and not self._ponte.ocupado and time.monotonic() < prazo:
            await asyncio.sleep(0.2)
        if self._refazer_com and self._pensando:
            await self._ponte.interromper()

    def _mandar_para_o_claude(self, comando: str, comecou: float | None = None, juntar: bool = True) -> None:
        if self._pensando:
            if self._refazer_com:  # já está sendo refeito: entra junto
                self._refazer_com = f"{self._refazer_com} {comando}"
                return
            if juntar and self._pode_juntar(comecou):
                self._refazer_com = f"{self._texto_turno} {comando}"
                log.info("Complemento do pedido: interrompo e mando tudo junto.")
                self._emitir(ev.Aviso("Juntei com o pedido anterior. Mando tudo de novo, junto."))
                asyncio.create_task(self._seguro(self._interromper_para_juntar()), name="juntar")
                return
            self._pendentes.append((uuid.uuid4().hex[:8], comando))
            self._som("ok")
            self._emitir(ev.Aviso("Anotado. Mando para o Claude quando ele terminar."))
            self._emitir_fila()
            return
        self._iniciar_turno(comando)

    # ================================================================== turno com o Claude
    def _iniciar_turno(self, texto: str) -> None:
        self._janela_ate = 0.0
        self._texto_turno = texto
        self._inicio_turno = time.monotonic()
        self._turno_agiu = False
        self._refazer_com = ""
        self._pensando = True
        self._atualizar_estado()
        self._tarefa_turno = asyncio.create_task(self._seguro(self._turno(texto)), name="turno")

    async def _turno(self, texto: str) -> None:
        self._som("pensando")
        self._emitir(ev.InicioResposta())
        inicio = time.monotonic()
        self._ultima_narracao = inicio
        fim: EventoFim | None = None
        editados: list[str] = []
        try:
            async for evento in self._ponte.perguntar(texto):
                if isinstance(evento, EventoTexto):
                    visivel = texto_fala.sem_marcacao_de_fala(evento.texto)
                    if visivel:
                        self._emitir(ev.TextoClaude(visivel))
                elif isinstance(evento, EventoAcao):
                    if evento.ferramenta not in _SO_LEITURA:
                        self._turno_agiu = True  # daqui em diante, um pedido novo vai para a fila
                    if evento.caminho:
                        editados.append(evento.caminho)
                    self._emitir(ev.AcaoClaude(evento.detalhe, evento.ferramenta))
                    self._narrar(evento.fala, inicio)
                elif isinstance(evento, EventoInfo):
                    self._emitir_info_claude(evento.modelo, evento.permissao)
                elif isinstance(evento, EventoFim):
                    fim = evento
        finally:
            self._pensando = False
            self._atualizar_estado()
        if fim is None:
            fim = EventoFim("", None, time.monotonic() - inicio, None, "A resposta terminou sem resultado.")
        if fim.sessao and self._projeto is not None:
            self._estado_salvo.guardar_sessao(self._projeto.caminho, fim.sessao)
        self.historico.associar_sessao(fim.sessao)

        fala, visivel = texto_fala.extrair_fala(fim.texto_final)
        if not fala and visivel and not fim.erro:
            fala = texto_fala.resumo_falavel(visivel)
        login = bool(fim.erro) and eh_erro_de_login(fim.erro)
        if fim.erro:
            fala = (
                "O Claude Code precisa de login. As instruções estão na tela."
                if login
                else "Deu um problema com o Claude. Os detalhes estão na tela."
            )
        refazer, self._refazer_com = self._refazer_com, ""
        if fim.interrompido or refazer:
            fala = ""  # interrompido para juntar com o complemento: a resposta parcial não é falada
        if fim.erro:
            visivel = ""  # o texto cru do erro (em inglês) não é resposta; a explicação vai em fim.erro
        arquivos = self._arquivos_da_resposta(editados, visivel)
        if visivel:
            self._ultima_resposta = visivel
            self._ultimos_arquivos = arquivos
        self._emitir(ev.FimResposta(fala, fim.duracao_s, fim.custo_usd, fim.erro, fim.interrompido, visivel, arquivos))
        if login:
            self._emitir(ev.LoginNecessario())
        if refazer and not login:
            self._ultimo_uso = time.monotonic()
            self._apos_turno = []  # o pedido inteiro, mandado de novo, pede de novo o que precisar
            self._iniciar_turno(refazer)
            return
        if fala:
            self._ultima_fala = fala
            await self._falar(fala)
        elif not fim.interrompido:
            self._som("pronto")
        self._ultimo_uso = time.monotonic()
        acoes, self._apos_turno = self._apos_turno, []
        if not fim.interrompido and not fim.erro:
            for acao in acoes:  # o que o Claude pediu ao app (trocar de projeto, conversa nova, desfazer)
                try:
                    await acao()
                except Exception:
                    log.exception("Falha numa ação pedida pelo Claude")
        if self._pensando:
            return  # a troca já mandou o resto do pedido para o Claude
        self._abrir_janela()
        if self._pendentes:
            proximo = " ".join(texto for _id, texto in self._pendentes)
            self._pendentes.clear()
            self._emitir_fila()
            self._iniciar_turno(proximo)

    def _arquivos_da_resposta(self, editados: list[str], texto: str) -> list[str]:
        """Arquivos criados ou editados no turno, mais os que a resposta cita e que existem."""
        base = self._projeto.caminho if self._projeto else None
        achados: list[str] = []
        vistos: set[str] = set()
        candidatos = []
        for caminho in editados:
            candidato = Path(caminho)
            if not candidato.is_absolute() and base:
                candidato = Path(base) / candidato
            candidatos.append(candidato)
        candidatos += [Path(c) for c in texto_fala.encontrar_caminhos(texto, base)]
        for candidato in candidatos:
            try:
                if not candidato.exists():
                    continue
                absoluto = str(candidato.resolve())
            except (OSError, ValueError):
                continue
            chave = os.path.normcase(absoluto)
            if chave not in vistos:
                vistos.add(chave)
                achados.append(absoluto)
        return achados[:10]

    def _narrar(self, frase: str, inicio_turno: float) -> None:
        if not self.cfg.claude.narrar_progresso or self._falando or self._aprovacao is not None:
            return
        agora = time.monotonic()
        if agora - inicio_turno < 6.0 or agora - self._ultima_narracao < 12.0:
            return
        self._ultima_narracao = agora
        asyncio.create_task(self._seguro(self._falar(frase, se_livre=True)))

    # ================================================================== permissões
    async def _pedir_permissao(self, ferramenta: str, entrada: dict, contexto, chave: str) -> tuple[bool, bool]:
        clausula, detalhe = texto_fala.descrever_pedido(ferramenta, entrada)
        pergunta = f"Posso {clausula}?"
        falada = pergunta
        if ferramenta in texto_fala.FERRAMENTAS_DE_COMANDO and detalhe and detalhe not in clausula:
            falada += " O comando está na tela."
        id_ = uuid.uuid4().hex[:8]
        futuro = self._loop.create_future()
        self._aprovacao = _Aprovacao(id_, futuro, pergunta)
        self._emitir(ev.PedidoAprovacao(id_, pergunta, detalhe, ferramenta, chave))
        self._aceitar_respostas_curtas(math.inf)  # "sim" e "não" são curtos demais para o corte normal
        self._atualizar_estado()
        try:
            self._som("ativou")
            await self._falar(falada)
            try:
                aprovado, sempre = await asyncio.wait_for(asyncio.shield(futuro), self.cfg.claude.tempo_aprovacao_s)
            except asyncio.TimeoutError:
                self._resolver_aprovacao(id_, False, False, "tempo esgotado")
                await self._falar("Como você não respondeu, eu recusei.")
                return False, False
            return aprovado, sempre
        finally:
            if self._aprovacao is not None and self._aprovacao.id == id_:
                self._aprovacao = None
            if self._aprovacao is None:
                self._aceitar_respostas_curtas(self._janela_ate)
            self._atualizar_estado()

    def _resolver_aprovacao(self, id_: str, aprovado: bool, sempre: bool, por: str) -> None:
        atual = self._aprovacao
        if atual is None or atual.id != id_:
            return
        if not atual.futuro.done():
            atual.futuro.set_result((bool(aprovado), bool(sempre)))
        self._aprovacao = None
        self._emitir(ev.AprovacaoResolvida(id_, bool(aprovado), por))
        self._parar_fala()
        self._som("ok" if aprovado else "erro")
        self._atualizar_estado()

    # ================================================================== voz do assistente
    def _sintetizar(self, frase: str):
        audio = self._motor_voz.sintetizar(frase)
        return audio, self._motor_voz.taxa

    def _parar_fala(self) -> None:
        if self._falando:
            self._fala_cancelada = True
            self._reprodutor.parar()

    async def _tocar_audio_falado(self, audio, taxa: int, texto: str) -> None:
        """Toca um áudio pronto (a saudação) como se fosse fala: dá para interromper e não vira eco."""
        async with self._trava_fala:
            self._fala_cancelada = False
            self._falando = True
            self._texto_falando = texto
            self._atualizar_estado()
            try:
                self._reprodutor.tocar(audio, taxa)
                while self._reprodutor.tocando and not self._fala_cancelada:
                    await asyncio.sleep(0.04)
            finally:
                if self._fala_cancelada:
                    self._reprodutor.parar()
                self._falando = False
                self._texto_falando = ""
                self._fim_ultima_fala = time.monotonic()
                self._ultimo_uso = self._fim_ultima_fala
                self._atualizar_estado()

    async def _falar(self, texto: str, se_livre: bool = False) -> None:
        texto = (texto or "").strip()
        if not texto or self._trava_fala is None:
            return
        if se_livre and (self._trava_fala.locked() or self._motor_voz is None):
            return  # narração de progresso só quando a voz já está pronta
        if not await self._garantir_voz():
            return
        async with self._trava_fala:
            self._fala_cancelada = False
            self._falando = True
            self._texto_falando = texto
            self._atualizar_estado()
            try:
                frases = texto_fala.agrupar_frases(texto_fala.dividir_frases(texto)) or [texto]
                proxima = self._loop.run_in_executor(self._executor_voz, self._sintetizar, frases[0])
                for i in range(len(frases)):
                    audio, taxa = await proxima
                    if i + 1 < len(frases):
                        proxima = self._loop.run_in_executor(self._executor_voz, self._sintetizar, frases[i + 1])
                    if self._fala_cancelada:
                        break
                    self._reprodutor.tocar(audio, taxa)
                    if i + 1 < len(frases):
                        self._reprodutor.silencio(_PAUSA_ENTRE_TRECHOS_S)  # o Kokoro corta o silêncio das pontas
                while self._reprodutor.tocando and not self._fala_cancelada:
                    await asyncio.sleep(0.04)
            except Exception:
                log.exception("Falha ao falar")
                self._emitir(ev.Aviso("Não consegui falar a resposta (veja o log).", "erro"))
            finally:
                if self._fala_cancelada:
                    self._reprodutor.parar()
                self._falando = False
                self._texto_falando = ""
                self._fim_ultima_fala = time.monotonic()
                self._ultimo_uso = self._fim_ultima_fala
                self._atualizar_estado()
