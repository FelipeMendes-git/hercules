"""Dicionário de pronúncia: reescreve termos em inglês (e siglas) do jeito que um brasileiro fala.

A voz (Kokoro) lê tudo com as regras do português: "GitHub" sairia "jítchi úb". Antes de falar, cada
termo conhecido vira uma grafia "abrasileirada" ("guíti rábi") e a frase continua inteira em português,
com a mesma voz e o mesmo sotaque. Custa só uma troca de texto.

Termos em MAIÚSCULAS (siglas como "API" e "IA") só valem escritos assim, para não pegar palavras comuns
("ia", "os"). Os outros valem com qualquer caixa. O plural com "s" sai sozinho ("commits" → "comítis").

O seu dicionário fica em ``pronuncia.toml``, na pasta de dados. Ele completa e corrige o padrão abaixo
e é relido sozinho quando muda, sem reiniciar o app.
"""

from __future__ import annotations

import logging
import re
import threading
import tomllib
from pathlib import Path

from . import caminhos

log = logging.getLogger(__name__)

# Acentos marcam a sílaba forte (nunca numa vogal sozinha: "í" seria lido "i agudo"). O "â" sai como o
# "a" de "bad"; por isso o "u" de "bug" vira "á". "ti"/"di" no fim viram "tchi"/"dji", como no português falado; "r" no
# começo soa como o "h" do inglês ("rárduer" = hardware).
PADRAO: dict[str, str] = {
    # ------------------------------------------------------------ git e fluxo de trabalho
    "git": "guíti",
    "commit": "comíti",
    "commitar": "comitár",
    "commitei": "comitêi",
    "push": "púch",
    "pull": "púl",
    "pull request": "pul ríquest",
    "merge": "mérdji",
    "merge request": "mérdji ríquest",
    "rebase": "ribêis",
    "branch": "bréntchi",
    "checkout": "tchecáuti",
    "stash": "istéch",
    "fork": "fórqui",
    "issue": "íchu",
    "review": "riviú",
    "code review": "côudi riviú",
    "deploy": "diplói",
    "release": "rilís",
    "build": "bíldi",
    "bug": "bágui",
    "debug": "dibágui",
    "debugar": "dibagár",
    "debugger": "dibáguer",
    "fix": "fíquis",
    "hotfix": "rótfíquis",
    "feature": "fítchur",
    "backlog": "béclógui",
    "sprint": "isprínti",
    "daily": "dêili",
    "roadmap": "rôudmépi",
    "pipeline": "páiplaine",
    "workflow": "uôrquiflôu",
    "staging": "istêidjin",
    "rollback": "rôulbéqui",
    "changelog": "tchêindjlógui",
    # ------------------------------------------------------------ programação
    "framework": "frêimuôrqui",
    "library": "láibrari",
    "script": "iscrípiti",
    "string": "istríngui",
    "array": "arêi",
    "boolean": "búlian",
    "null": "nál",
    "undefined": "andifáindi",
    "callback": "cólbéqui",
    "token": "tôquen",
    "prompt": "prômpiti",
    "log": "lógui",
    "cache": "quéchi",
    "cookie": "cúqui",
    "backend": "béquend",
    "frontend": "frôntend",
    "fullstack": "fulistéqui",
    "stack": "istéqui",
    "host": "rôusti",
    "hosting": "rôustin",
    "localhost": "lôucal rôusti",
    "endpoint": "éndpointi",
    "query": "quêri",
    "request": "ríquest",
    "response": "rispônse",
    "payload": "pêilôudi",
    "header": "réder",
    "upload": "aplôudi",
    "download": "dáunlôudi",
    "update": "apdêiti",
    "upgrade": "apgrêidi",
    "setup": "setápi",
    "default": "difóuti",
    "input": "ínputi",
    "output": "áutputi",
    "loop": "lúpi",
    "thread": "trédi",
    "breakpoint": "brêiquipointi",
    "runtime": "rántáimi",
    "timeout": "táimáuti",
    "crash": "créchi",
    "hash": "réchi",
    "mock": "móqui",
    "refactor": "rifátor",
    "database": "dêitabêissi",
    "schema": "isquíma",
    "backup": "béquiápi",
    "plugin": "pláguin",
    "widget": "uídjeti",
    "template": "têmpleiti",
    "layout": "lêiáuti",
    "design": "dizáin",
    "designer": "dizáiner",
    "dashboard": "déchbórdi",
    "benchmark": "bêntchimárqui",
    "driver": "dráiver",
    "docker": "dóquer",
    "kubernetes": "cubernétis",
    "cluster": "cláster",
    "container": "contêiner",
    "cloud": "cláudi",
    "open source": "ôupen sórci",
    "machine learning": "machíni lérnin",
    "deep learning": "díp lérnin",
    "shell": "chél",
    "bash": "béch",
    "spam": "ispâm",
    "feedback": "fídbéqui",
    "login": "lóguin",
    "logout": "logáuti",
    "password": "péssuôrdi",
    "user": "iúzer",
    "username": "iúzernêimi",
    "online": "onláini",
    "offline": "ofláini",
    "software": "sóftuer",
    "hardware": "rárduer",
    "mouse": "máusi",
    "notebook": "nôutbúqui",
    "desktop": "déskitópi",
    "laptop": "léptópi",
    "smartphone": "ismártifôuni",
    "headset": "rédiséti",
    "email": "imêiu",
    "e-mail": "imêiu",
    "link": "línqui",
    "site": "sáiti",
    "website": "uébisáiti",
    "web": "uébi",
    "app": "épi",
    "chat": "tchéti",
    "chatbot": "tchétibóti",
    "bot": "bóti",
    "game": "guêimi",
    "player": "plêier",
    "streaming": "istrímin",
    "live": "láivi",
    "wifi": "uaifái",
    "wi-fi": "uaifái",
    "bluetooth": "blutúfi",
    # ------------------------------------------------------------ linguagens, ferramentas e marcas
    "python": "páiton",
    "javascript": "javaiscrípiti",
    "typescript": "táipiscrípiti",
    "node": "nôudi",
    "node.js": "nôudi jêi ésse",
    "react": "riécti",
    "vue": "viú",
    "rust": "rásti",
    "kotlin": "cótlin",
    "swift": "suífti",
    "powershell": "páuerchél",
    "windows": "uíndous",
    "microsoft": "maicrosófti",
    "google": "gúgol",
    "chrome": "crôumi",
    "firefox": "fáierfóquis",
    "edge": "édji",
    "github": "guíti rábi",
    "gitlab": "guíti lébi",
    "visual studio code": "vísual istúdio côudi",
    "vs code": "vi ésse côudi",
    "vscode": "vi ésse côudi",
    "claude": "clóudi",
    "claude code": "clóudi côudi",
    "claude desktop": "clóudi déskitópi",
    "anthropic": "antrópic",
    "openai": "ôupen êi ái",
    "chatgpt": "tchéti gê pê tê",
    "sonnet": "sónet",
    "haiku": "ráicu",
    "whisper": "uísper",
    "discord": "discórdi",
    "slack": "isléqui",
    "notion": "nôuchon",
    "youtube": "iutúbi",
    "whatsapp": "uótsápi",
    "spotify": "ispótifai",
    "powerpoint": "páuerpóinti",
    "word": "uôrdi",
    "onedrive": "uán dráivi",
    "dropbox": "drópbóquis",
    "iphone": "aifôuni",
    "ok": "ôquei",
    # ------------------------------------------------------------ siglas (só em maiúsculas)
    "README": "rídmi",
    "JSON": "jêisson",
    "YAML": "iémel",
    "TOML": "tómel",
    "API": "a pê i",
    "URL": "u érre éle",
    "HTML": "agá tê ême éle",
    "CSS": "cê ésse ésse",
    "SQL": "ésse quê éle",
    "PDF": "pê dê éfe",
    "CPU": "cê pê u",
    "GPU": "gê pê u",
    "RAM": "rãm",
    "SSD": "ésse ésse dê",
    "HD": "agá dê",
    "USB": "u ésse bê",
    "IA": "i á",
    "AI": "êi ái",
    "UI": "iu ái",
    "UX": "iu équis",
    "VPN": "vê pê êne",
    "DNS": "dê êne ésse",
    "IP": "i pê",
    "ID": "i dê",
    "HTTP": "agá tê tê pê",
    "HTTPS": "agá tê tê pê ésse",
    "SSH": "ésse ésse agá",
    "CLI": "cê éle i",
    "IDE": "i dê é",
    "SDK": "ésse dê cá",
    "NPM": "êne pê ême",
    "PR": "pê érre",
    "CI": "cê i",
    "AWS": "a dáblio ésse",
    "LLM": "éle éle ême",
    "MCP": "ême cê pê",
    "TTS": "tê tê ésse",
    "OK": "ôquei",
}

_CABECALHO = """\
# Dicionário de pronúncia da voz.
# Cada linha: "termo" = "como falar". Acentos marcam a sílaba forte ("diplói", "pul ríquest");
# "r" no começo soa como o "h" do inglês ("rárduer").
# Termo todo em MAIÚSCULAS (como "API") só vale escrito assim; os outros valem com qualquer caixa.
# O plural com "s" sai sozinho. Para desligar um termo do dicionário padrão, deixe vazio: "site" = ""
# As mudanças valem na próxima frase falada, sem reiniciar o app.

[termos]
"""


def arquivo() -> Path:
    return caminhos.pasta_dados() / "pronuncia.toml"


def garantir_arquivo() -> Path:
    """Cria o arquivo do seu dicionário (vazio, com as instruções) se ainda não existir."""
    caminho = arquivo()
    if not caminho.exists():
        caminho.write_text(_CABECALHO, encoding="utf-8")
    return caminho


def _eh_sigla(termo: str) -> bool:
    return any(c.isalpha() for c in termo) and termo == termo.upper()


def _alternativas(termos) -> str:
    return "|".join(re.escape(t) for t in sorted(termos, key=len, reverse=True))


class Pronuncia:
    def __init__(self, padrao: dict[str, str] | None = None, caminho: Path | None = None):
        self._padrao = dict(PADRAO if padrao is None else padrao)
        self._caminho = caminho
        self._versao: float | None = None
        self._trava = threading.Lock()
        self._montar({})

    def _montar(self, seus: dict[str, str]) -> None:
        desligados = {t.strip().lower() for t, v in seus.items() if not v.strip()}  # vazio = desliga o padrão
        termos = {t: v for t, v in self._padrao.items() if t.lower() not in desligados}
        termos.update(seus)
        termos = {t.strip(): v.strip() for t, v in termos.items() if t.strip() and v.strip()}
        self._siglas = {t: v for t, v in termos.items() if _eh_sigla(t)}
        self._palavras = {t.lower(): v for t, v in termos.items() if not _eh_sigla(t)}
        partes = []
        if self._siglas:
            partes.append(f"(?P<sigla>{_alternativas(self._siglas)})")
        if self._palavras:
            partes.append(f"(?i:(?P<palavra>{_alternativas(self._palavras)}))")
        # Uma passada só (o que já foi trocado não é trocado de novo). Plural: "s" sempre; "es" só depois
        # de ch/sh/x/s ("branches", "pushes"), para não pegar "testes".
        self._re = (
            re.compile(rf"(?<![\w-])(?:{'|'.join(partes)})(?P<plural>(?<=ch|sh)es|(?<=[xs])es|s)?(?![\w-])")
            if partes
            else None
        )

    def _trocar(self, m: re.Match[str]) -> str:
        sigla = m.groupdict().get("sigla")
        dito = self._siglas[sigla] if sigla is not None else self._palavras[m.group("palavra").lower()]
        return dito + ("s" if m.group("plural") else "")

    def _recarregar_se_mudou(self) -> None:
        if self._caminho is None:
            return
        try:
            versao = self._caminho.stat().st_mtime if self._caminho.exists() else None
        except OSError:
            return
        if versao == self._versao:
            return
        self._versao = versao
        seus: dict[str, str] = {}
        if versao is not None:
            try:
                dados = tomllib.loads(self._caminho.read_text(encoding="utf-8"))
                bruto = dados.get("termos", {})
                if isinstance(bruto, dict):
                    seus = {str(t): v for t, v in bruto.items() if isinstance(v, str)}
            except (OSError, tomllib.TOMLDecodeError) as erro:
                log.warning("Não consegui ler o dicionário de pronúncia %s: %s", self._caminho, erro)
        self._montar(seus)
        if seus:
            log.info("Dicionário de pronúncia: %d termos seus.", len(seus))

    def aplicar(self, texto: str) -> str:
        if not texto:
            return texto
        with self._trava:
            self._recarregar_se_mudou()
            if self._re is None:
                return texto
            return self._re.sub(self._trocar, texto)


_global: Pronuncia | None = None
_trava_global = threading.Lock()


def aplicar(texto: str) -> str:
    """Aplica o dicionário padrão mais o seu (``pronuncia.toml``) ao texto que a voz vai falar."""
    global _global
    with _trava_global:
        if _global is None:
            try:
                caminho = garantir_arquivo()
            except OSError:
                caminho = None
            _global = Pronuncia(caminho=caminho)
    return _global.aplicar(texto)
