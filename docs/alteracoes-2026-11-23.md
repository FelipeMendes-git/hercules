# Alterações de 23/11/2026 (sessão pelo Hércules) — para continuar

Estado: tudo abaixo está escrito no código e os 115 testes passam (`.venv\Scripts\python.exe -m pytest -q`).
O app **ainda não foi reiniciado** para conferir na prática. Nada foi commitado (o repositório ainda não tem
nenhum commit).

## 1. "Mestre" só na saudação (feito)

- `src/assistente_local/ponte_claude.py`: `instrucoes_de_voz()` não recebe mais `tratamento`; a linha
  "Chame-o de …" saiu do prompt do modo voz. `PonteClaude` não tem mais o atributo `tratamento`.
- `src/assistente_local/controlador.py`: não passa nem atualiza `tratamento` na ponte; mudar o tratamento
  não reinicia mais a conexão com o Claude.
- `interface/configuracoes.py`: dica do campo diz "Usado só na saudação de abertura."
- `README.md` e `tests/test_saudacao.py` atualizados.

## 2. Voz trocada para a Santa (feito)

- `dados/config.toml`: `[voz] voz = "pm_santa"` (era `pm_alex`). O padrão do código continua `pm_alex`.
- As frases de saudação gravadas devem ser regravadas sozinhas com a voz nova ao abrir o app (não conferido).
- Amostras das vozes ficaram em `C:\dev\amostras_voz\` (pasta descartável, fora do repositório; também tem
  os scripts `gerar.py` e `print_ui.py` usados nos testes). Pode apagar.
- Opções avaliadas e não feitas: Piper (pt_BR, offline) e vozes neurais da Microsoft (Antônio/Francisca,
  online). O sotaque do Kokoro vem do modelo, treinado quase todo em inglês.

## 3. Sem janela preta do terminal (feito, não testado no app)

- Causa: o Claude Code é um programa de console; aberto pelo app (que é GUI, sem console), o Windows criava
  uma janela de terminal para ele.
- Solução em `ponte_claude.py`, função `_abrir_processos_sem_janela()` (chamada ao importar o módulo):
  embrulha `anyio.open_process` (que o Claude Agent SDK usa em
  `claude_agent_sdk/_internal/transport/subprocess_cli.py`) para somar `CREATE_NO_WINDOW` ao `creationflags`.
  Os comandos que o Claude roda herdam o console invisível.
- Conferir: abrir o app pelo atalho e ver se a janela preta sumiu.

## 4. Visual novo "tecnológico" (feito, falta revisar na tela)

- `interface/tema.py` reescrito: paleta HUD (fundo quase preto, acento ciano neon `#00d9ff`, roxo, etc.),
  rótulos em fonte monoespaçada (Cascadia Mono/Consolas) com letras espaçadas, cantos menos arredondados.
  O CSS usa marcadores `@nome` trocados pelas cores de `CORES` em `_montar_estilo()`; `FONTE_MONO` exportada.
- `interface/conversa.py`: cores fixas do código e do medidor ajustadas à paleta nova.
- `interface/orbe.py` (novo): widget `Orbe`, um "reator" animado (brilho, três arcos girando, anel tracejado,
  marcações, núcleo pulsando). Cor e giro dependem do `Estado`; pulsa com o volume do microfone
  (`definir_nivel`) e com uma onda sintética enquanto fala. O timer só roda com o widget visível.
- `interface/janela.py`: o cabeçalho tem o orbe (40 px), o nome "HÉRCULES" e o estado embaixo; o "●"
  saiu. Novo botão "◉" para recolher para a bolinha. O menu da bandeja virou `_criar_menu()` e é usado
  também pela bolinha.

## 5. Bolinha flutuante (janela compacta) (feito, falta testar de verdade)

- `interface/janela_compacta.py` (novo): `JanelaCompacta`, janela sem borda, transparente, sempre por cima
  e fora da barra de tarefas. Mostra o orbe (76 px) e um balão com: progresso ao carregar, "ONLINE",
  o que você falou, a ação atual do Claude, a fala da resposta, pedidos de permissão e erros. O balão some
  5 s depois de voltar ao estado ocioso.
  - Clique: abre a janela principal. Arrastar: muda o lugar (salvo com `QSettings`, chave `ID_APP`,
    "janela_compacta"). Botão direito: o menu.
  - O balão abre para o lado da tela que tem mais espaço; o orbe fica parado no lugar.
- `janela.py`: `_atualizar_compacta()` mostra a bolinha quando a janela principal não está à vista
  (escondida ou minimizada), chamada por `showEvent`/`hideEvent`/`changeEvent`. `sair()` esconde a bolinha.
  O aviso "continuo na bandeja" só aparece com a bolinha desligada.
- `config.py` (`Interface`): `janela_compacta = True` e `iniciar_compacto = True`.
- `interface/configuracoes.py`, aba da janela: duas caixas novas para essas opções.
- `interface/aplicacao.py`: ao abrir, com `iniciar_compacto`, mostra só a bolinha.

Uma prévia da bolinha foi gerada (`C:\dev\amostras_voz\compacta.png`) e está como planejado. A prévia
da janela principal (`janela.png`) foi gerada, mas não chegou a ser revisada.

## 6. Continuação pelo Claude Code (mesmo dia, depois)

- **Claude:** padrão agora é Opus 5.5 (`claude-opus-5-5`), esforço alto e permissões no modo `auto`
  (testado: a sessão abre no Opus 5.5 e um comando seguro roda sem pedir permissão). Na aba Claude, o
  modelo virou uma lista. O app mostra o modelo e o esforço: evento `InfoClaude` (o modelo é confirmado
  pela mensagem `init` da sessão), chips no topo da janela e na dica da bolinha.
- **Bolha líquida** (escolhida num protótipo): `interface/orbe.py` foi reescrito. A gota ondula com o som
  de verdade (`Reprodutor.nivel`, via `Controlador.nivel_da_voz()`) e com o microfone; cor e movimento por
  estado em `aparencia()` (função pura, testada). As cores dos estados ficam em `tema.ESTADOS` e valem
  para a bolha e para o texto de estado.
- **Bolinha** (`janela_compacta.py`): só a bolha, sem balão. Opção "Sempre em primeiro plano" no menu do
  botão direito e em ⚙ → Janela (`interface.bolinha_no_topo`): desligada, a bolinha vira janela comum.
- O mascote testado nesse meio-tempo foi descartado.
- Testes: 104 passando. README atualizado.

## 7. Janela de conversa com visual moderno (pelo Hércules)

- `interface/tema.py`: paleta neutra mais limpa (fundo `#0c0e13`, acento ciano `#5cc8ff` com degradê para
  violeta `#7b6cff`, cor nova `violeta`), cantos arredondados (10 a 22 px), quase sem bordas, fonte
  Segoe UI (monoespaçada só em código). Cores dos estados (`ESTADOS`) e da bolha não mudaram.
- `interface/icones.py`: `icone_linha(nome, cor)` desenha ícones de traço fino (mic, mic_off, historico,
  config, recolher, enviar, parar, mais) no lugar dos emojis.
- `interface/janela.py`: cabeçalho em uma linha (bolha de 48 px, nome e estado, botões de ícone
  sem borda); embaixo o projeto em pílula e "Nova conversa" como botão vazado. O medidor de nível saiu
  (a bolha já reage ao microfone). Rodapé: caixa de mensagem em pílula com botões redondos de enviar e
  parar; os chips do modelo e das permissões ficam embaixo dela; o texto técnico (reconhecimento, voz)
  virou dica da bolha e a linha `_info` só aparece para avisos rápidos.
- `interface/conversa.py`: a sua fala vira uma bolha arredondada em degradê azul (sem o rótulo "VOCÊ");
  a resposta não tem mais caixa (ponto colorido + "Hércules"), as ações seguidas ficam agrupadas num
  quadro discreto com ✓, e a frase falada aparece entre aspas num quadro lilás.
- Prévia: `C:\dev\amostras_voz\janela_depois.png` (antes: `janela_antes.png`). Testes: 109 passando.

## 8. Visual "vidro claro" (escolhido num protótipo) e conversa nova ao abrir

- `interface/tema.py`: tema claro com vidro (painéis `rgba(255,255,255,140)` com borda branca, cantos de
  12 a 24 px), botões em pílula, primário em degradê violeta→azul. `estilo_completo()` gera na hora as
  imagens das setinhas e do check (o Qt não desenha setas com o truque de bordas do CSS).
- `interface/fundo.py` (novo): `FundoVivo`, o fundo da janela com três manchas pastel na cor do estado
  (`cores_do_fundo()`, testada). 8 quadros/s com a janela em foco, 2 atrás de outras, parado quando escondida
  (~3,4 ms por quadro com uma conversa longa).
- `interface/janela.py`: cabeçalho como painel de vidro (bolha de 58 px); projeto e "Nova conversa" em
  pílulas fora dele; lista transparente; rótulo de estado escurecido para ler no claro.
- `interface/conversa.py`: resposta do Claude num cartão de vidro; código em bloco em cores claras.
- `config.Claude.conversa_nova_ao_abrir = True`: o app abre numa conversa nova; `retomar_conversa` agora
  vale só ao entrar num projeto. As duas opções ficam em ⚙ → Claude.
- Testes: 111 passando.

## 9. Esforço e modelo por voz

- Nova ferramenta `ajustar_claude` no servidor "app" (`ponte_claude.py`), com `esforco` (low, medium, high,
  xhigh, max ou padrao) e `modelo` (opus, sonnet, haiku ou padrao). `normalizar_esforco()` e
  `normalizar_modelo()` entendem o que o Claude manda ("médio", "Opus 5.5"...) e recusam modelos fora da
  lista: um modelo inválido travaria as respostas seguintes, e aí nem daria para pedir a troca por voz.
  Os dois vazios só dizem o que está em uso.
- `controlador.py`: `_FerramentasDoApp.ajustar_claude` agenda `Controlador._mudar_claude` para quando a
  resposta terminar. Ele salva o `config.toml`, avisa a janela (`InfoClaude` e o evento novo
  `ConfigAlterada`, para a engrenagem abrir com o valor novo) e fecha o Claude Code; a próxima pergunta
  reabre com o esforço novo, na mesma conversa (`resume`).
- Não existe esforço "auto" no Claude Code; "auto" e "padrão" deixam o Claude Code escolher. Na engrenagem,
  os rótulos dos esforços dizem o que cada um troca (rapidez e gasto contra capricho).
- Testado com o Claude de verdade: "responde mais rápido, pode usar o esforço baixo" chamou
  `ajustar_claude(low)`; depois, na mesma sessão, a pergunta seguinte respondeu em 3,7 s. Testes: 115 passando.
- **Esforço padrão agora é o médio** (escolha do usuário, para gastar menos e responder mais rápido):
  `config.Claude.esforco = "medium"`, e o `dados/config.toml` foi trocado de `high` para `medium`. Para
  pedidos difíceis: "Hércules, pensa com mais cuidado" (alto).

## Próximos passos

1. Reiniciar o app e conferir: terminal preto sumiu, voz Santa, saudação regravada, bolinha e tema.
2. Revisar `C:\dev\amostras_voz\janela.png` e ajustar o tema se preciso.
3. Testar a bolinha em uso real: arrastar, clicar, menu, balão durante uma conversa, permissão por voz,
   e com dois monitores.
4. Atualizar o `README.md` com a bolinha, as opções novas e o tema.
5. Opcional: adicionar testes para `JanelaCompacta` (lógica do balão por estado).
6. Fazer o primeiro commit quando estiver tudo certo.

## Planos para o futuro: controlar tudo por voz

Hoje, por voz (ferramentas do servidor "app" em `ponte_claude.py`), dá para listar e trocar de projeto,
começar conversa nova, copiar, abrir e desfazer. Ainda falta:

1. **Trocar as permissões falando.** Modelo e esforço já mudam por voz (`ajustar_claude`, seção 9). As
   permissões ficaram de fora de propósito: o Claude não deve poder afrouxar as próprias permissões.
   Se for feito, só com confirmação dita pelo usuário, fora do Claude (como o "sim" das permissões).
2. **Retomar uma conversa antiga falando.** Ferramentas para listar as conversas salvas do histórico
   (`Controlador.historico`) e continuar uma delas (`Controlador.continuar_conversa`), por exemplo "volta
   naquela conversa de ontem sobre a voz". Hoje só dá pelo botão do relógio (histórico).
