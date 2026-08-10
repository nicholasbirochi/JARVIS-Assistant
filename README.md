# J • A • R • V • I • S

Assistente de voz pessoal do Nicholas. Ativado por wake word sem depender de nenhuma
conta/chave externa, conversa em português por voz, e mantém um perfil profissional
único e estruturado (`data/resume.json`) com procedência (evidência/fonte) por fato, que
futuramente será publicado em sites de vagas (LinkedIn, Gupy, Catho, InfoJobs, Vagas.com,
Indeed, Academia do Universitário e outros via adaptadores).

100% local: o "cérebro" roda via [Ollama](https://ollama.com) na própria máquina —
nenhum dado do currículo ou da conversa sai do Mac, sem API paga, sem chave de nenhum
serviço em nuvem. O reconhecimento de voz (wake word + transcrição) também é
inteiramente local e não exige conta de nenhum tipo. Ativa por "Hey Jarvis" ou por duas
palmas -- o que vier primeiro.

Estado atual: **Etapas 1-5 em andamento**. Diagnóstico, consolidação de dados + indexação
incremental, voz totalmente local e app de menu bar estão completos. O primeiro adaptador
de site (Gupy) já lê o perfil real, compara com o currículo local (*dry run*) e **grava
de verdade** nome e telefone -- tudo **verificado contra a conta ao vivo**, inclusive o
clique real em "Salvar". E-mail fica de fora por enquanto (é também o identificador de
login, e mudá-lo pode disparar um fluxo de verificação nunca testado); o restante do
currículo (experiência, formação, certificações) vive num sub-formulário da Gupy ainda
não inspecionado.

## Arquitetura

- **`jarvis/assistant/providers.py`** — abstração `LocalLLMProvider`; hoje só existe
  `OllamaProvider`, mas qualquer chamador (conversa, importação, indexador) passa por essa
  interface, não por `ollama` diretamente — trocar para MLX no futuro não deve exigir
  tocar em nenhum desses chamadores. Manda `keep_alive` em toda chamada (`OLLAMA_KEEP_ALIVE`,
  padrão 30min) -- o padrão do próprio Ollama (5min) foi a causa real de respostas lentas
  medida na prática: qualquer intervalo maior entre ativações do JARVIS forçava um recarregamento
  frio do modelo (~30s) na resposta seguinte.
- **`jarvis/resume/schema.py`** — currículo canônico com procedência: cada item
  (experiência, certificação, projeto...) carrega uma lista de `Evidence` (arquivo de
  origem, tipo, data de leitura, trecho, confiança, status de revisão). Conflitos entre
  fontes viram um registro em `conflicts`, nunca uma sobrescrita silenciosa. Toda mudança
  aplicada gera uma entrada em `change_log` (auditoria).
- **`jarvis/indexing/`** — escaneia apenas diretórios autorizados (`jarvis/config.py` →
  `AUTHORIZED_INDEX_ROOTS`), ignora o próprio repositório do JARVIS e ruído de
  dependências (`node_modules`, `.git`, `obj/`, etc.), calcula hash de cada arquivo para
  pular o que já foi processado, e gera uma **proposta** revisável
  (`data/proposals/proposal_*.json`) — nunca escreve direto em `data/resume.json`.
- **`jarvis/voice/`** — `wake_word.py` seleciona o motor via `WAKE_WORD_ENGINE`
  (`openwakeword`, padrão, usa o modelo pré-treinado "hey jarvis"; ou `porcupine`,
  adaptador opcional que exige `PICOVOICE_ACCESS_KEY`). `stt.py` (faster-whisper) carrega
  o modelo só quando necessário e libera a memória (`unload()`) ao fim de cada sessão de
  conversa.
- **`jarvis/sites/`** — `base.py` define a interface `SiteAdapter` (dry run sempre antes,
  `apply_changes` recusa sem `confirmed=True`, login sempre manual). `session.py` é a
  sessão Playwright persistente e reutilizável por qualquer site (login numa janela real
  e visível). `gupy.py` é o primeiro adaptador real -- ver "Adaptador da Gupy" abaixo.
  **Onde os dados de sessão ficam:** `~/Library/Application Support/JARVIS/sites/`
  (`LOCAL_STATE_DIR` em `jarvis/config.py`), de propósito **fora** da pasta do projeto --
  todo o projeto vive dentro de uma pasta sincronizada com o OneDrive, e cookies de login
  reais (e, se algum dia houver, screenshots de evidência) nunca devem sair desta máquina
  nem pra uma nuvem que já é "confiada" por outro motivo. `data/resume.json` pode
  continuar em `data/` (dentro do projeto) porque o schema já exclui de propósito CPF/RG/
  endereço/data de nascimento -- ver `.env.example` para trocar o caminho
  (`JARVIS_LOCAL_STATE_DIR`).
- **`jarvis/menubar.py`** — app de menu bar (macOS) com botão liga/desliga; roda o loop
  de voz em background thread, controlado por `VoiceLoopController`. Inicia **desligado**
  (ícone visível, mas não ouvindo até você clicar) e sem ícone no Dock/Cmd-Tab (política de
  ativação "accessory"). Pode ser iniciado manualmente (`python -m jarvis menubar`) ou
  automaticamente no login via LaunchAgent -- ver "Iniciar automaticamente" abaixo. O botão
  "Abrir"/"Fechar" abre e fecha o HUD de `jarvis/visualizer/` -- ver seção própria abaixo.
- **`jarvis/visualizer/`** — HUD visual (círculo azul animado, estilo painel futurista) que
  reflete o estado real do JARVIS (desligado/em espera/ouvindo/falando) e o texto sendo
  ouvido/falado. `state.py` é um pub/sub em memória que `conversation.py`/`tts.py`/
  `menubar.py` publicam a cada transição real; `server.py` é um servidor HTTP local (só
  `127.0.0.1`, stdlib puro, sem dependência nova) que expõe `page.html` e um stream de
  eventos (Server-Sent Events). `native_window.py` abre isso numa janela nativa de verdade
  (WKWebView via PyObjC -- o mesmo motor do Safari) em vez de uma aba de navegador --
  tentamos primeiro abrir o Chromium do Playwright em modo app (`--app=`), mas ele mostrava
  um aviso "atualize o Chrome" por cima da página, o que não é problema com WebKit direto.

## Setup

```bash
brew install python@3.12
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # opcional -- ver abaixo

# Modelo local (Ollama) -- roda como serviço em background, gerenciado pelo Homebrew
brew install ollama
brew services start ollama
ollama pull qwen2.5:7b   # ~4.7GB, baixa uma vez -- ~4x mais rápido que o 14b uma vez "aquecido"

# Só necessário se for usar os adaptadores de site (jarvis/sites/) -- baixa o Chromium
# que o Playwright controla (não é o seu navegador normal, ~150MB, uma vez só)
playwright install chromium

# Só necessário para a voz clonada (jarvis/voice/xtts_engine.py) -- ~4GB de
# dependências (torch/coqui-tts) + FFmpeg do sistema (não é pacote Python,
# é lib nativa que o torchaudio carrega em runtime pra decodificar o
# clipe de referência). Ver "Voz clonada (XTTS-v2)" abaixo.
brew install ffmpeg
pip install -e ".[voice-cloning]"
```

Nenhuma chave é obrigatória por padrão. `.env` só é necessário se você quiser usar o
Porcupine como motor de wake word (`WAKE_WORD_ENGINE=porcupine` + `PICOVOICE_ACCESS_KEY`)
em vez do openWakeWord padrão, apontar para um Ollama/modelo diferente, trocar a voz
do TTS padrão (`TTS_VOICE` -- ver `.env.example` para como achar uma boa voz masculina, já
que as que o macOS instala por padrão são de baixa qualidade), ou desligar a voz clonada
(`TTS_ENGINE=say`).

## Uso

Consolidar o currículo mestre a partir dos currículos existentes (rodar uma vez, revisar
o resultado antes de confiar nele):

```bash
python scripts/import_resume.py
# revise data/review/resume_review.md e data/resume.json
python scripts/migrate_schema_v2.py   # só necessário se o resume.json for de antes do schema v2
```

Escanear currículos/certificados/cursos/projetos em busca de atualizações (nunca altera
`data/resume.json` diretamente -- gera uma proposta para revisão):

```bash
python -m jarvis index
python -m jarvis review-proposals   # aceitar/rejeitar/pular cada mudança, uma a uma
```

Conversar em modo texto (sem microfone, útil para depurar):

```bash
python -m jarvis --text-only
```

Modo de voz completo (diga "Hey Jarvis" ou bata duas palmas para ativar):

```bash
python -m jarvis
```

Ao ativar (palavra de ativação ou palma), o JARVIS fica em silêncio e só passa a ouvir --
sem falar nada antes de você dizer o que quer. Era diferente antes (um briefing/saudação
falado imediatamente), mas isso competia com o tempo de carregamento do worker de voz
clonada (~15-20s) e às vezes saía com a voz genérica em vez da voz do JARVIS -- um bug real,
não só um incômodo de UX. O briefing de pendências (mudanças de currículo, conflitos em
aberto, manchetes do dia sobre dados/IA -- `jarvis/assistant/news.py`, RSS público do Olhar
Digital, nenhum dado seu enviado a lugar nenhum) continua existindo em `--text-only`
(`jarvis/assistant/briefing.py`), só não é mais falado automaticamente no modo de voz.
O JARVIS também conhece as habilidades e certificações reais do currículo (Python, R, SQL,
Power BI, estatística, etc.) e comenta sobre dados com entusiasmo quando o assunto surge --
grounded no `data/resume.json`, não inventado (`jarvis/assistant/llm_client.py`).

Se as palmas não estiverem sendo detectadas (ou disparando à toa), meça o pico real do
seu microfone/ambiente antes de ajustar `CLAP_PEAK_THRESHOLD` no `.env`:

```bash
python -m jarvis calibrate-claps
```

App de menu bar (mesma coisa, com um ícone e botão liga/desliga -- e, acima dele, um botão
"Abrir"/"Fechar" pro HUD visual numa janela própria, sem navegador nenhum envolvido,
independente de JARVIS estar ligado ou não):

```bash
python -m jarvis menubar
```

Pra ele iniciar sozinho a cada login (ícone sempre disponível, sem precisar abrir terminal),
registre como LaunchAgent -- ajuste os caminhos pro seu usuário/pasta do projeto:

```bash
cp com.nicholasbirochi.jarvis.menubar.plist.example ~/Library/LaunchAgents/com.SEUUSUARIO.jarvis.menubar.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.SEUUSUARIO.jarvis.menubar.plist
```

`RunAtLoad` liga sozinho no login; sem `KeepAlive`, então "Sair" no menu realmente encerra
até o próximo login (não fica sendo religado). Logs em `~/Library/Logs/JARVIS/menubar.log`.

**Ou como um app de verdade**, pra abrir pelo Launchpad/Spotlight/Finder em vez do terminal:

```bash
.venv/bin/pip install -e '.[packaging]'   # só a primeira vez -- instala o py2app
python scripts/generate_app_icon.py       # gera jarvis/assets/AppIcon.icns -- só precisa rodar uma vez
python scripts/build_app.py               # cria /Applications/JARVIS.app
```

`JARVIS.app` é construído com o modo "alias" do `py2app` (`packaging/setup.py`) -- não é
um build congelado, continua rodando direto do `.venv`/código-fonte deste projeto (nada de
dependência empacotada junto). Um wrapper de bash simples foi tentado primeiro e não
funcionava de verdade: o `python@3.12` do Homebrew é um build "framework" do macOS, e o
próprio interpretador reexecuta silenciosamente pra dentro de
`.../Resources/Python.app/Contents/MacOS/Python` sempre que não é executado já como esse
binário exato -- isso troca a identidade do processo de `com.nicholasbirochi.jarvis` pra
`org.python.python`, e foi exatamente isso que quebrava o ícone da barra de menu (o processo
ficava vivo, sem erro nenhum no Python, e o ícone nunca aparecia -- só visível pelo
Console.app: `AppKit:StatusBar] scene activation failed`). O modo alias do py2app usa um
stub compilado próprio que embute o interpretador via API C em vez de reexecutar o binário
do Python, então esse problema nunca acontece. **Não rode o app manual e o LaunchAgent
automático ao mesmo tempo** -- duas instâncias tentando pegar o microfone ao mesmo tempo
causa exatamente o tipo de falha silenciosa que já vimos antes (o JARVIS já tem uma trava
própria contra isso, mas é melhor nem depender dela).

**Primeira vez que for abrir, um passo manual é obrigatório:** clique com o botão direito
(ou Control-clique) em `JARVIS.app` → **Abrir** → confirme no aviso. Isso não é bug --
`build_app.py` já assina o app com uma assinatura ad-hoc (`codesign --sign -`, gratuita,
sem conta de desenvolvedor), mas isso sozinho não satisfaz o Gatekeeper do macOS pra um
duplo-clique direto normal em Apple Silicon; sem clicar em "Abrir" uma vez, o clique
simplesmente **não faz nada visível, sem erro nenhum** (`spctl --assess` mostra
`rejected`). Depois desse primeiro "Abrir" confirmado, duplo-clique normal funciona
para sempre. `spctl --add` (que permitiria liberar isso via terminal, sem esse passo
manual) foi descontinuado pelo próprio macOS -- não tem como pular essa etapa.

## Pedir uma mudança de código por voz

Pedir pro JARVIS ("mude a cor do HUD pra verde", "peça pro Claude Code revisar o
adaptador da Gupy") faz ele escrever um prompt completo e bem estruturado -- não a sua
fala ao pé da letra -- e copiar pra área de transferência (`prepare_claude_prompt` em
`jarvis/assistant/tools.py`). Não existe uma forma de o JARVIS colocar texto direto numa
conversa já aberta com o Claude Code, então isso é proposital, não uma limitação: é só
colar (`Cmd+V`) onde e quando você quiser -- nesta conversa, numa nova, sobre este
projeto ou outro. Cada prompt também fica salvo em
`~/Library/Application Support/JARVIS/claude_prompts.log`, como rede de segurança caso
você não cole na hora.

## Voz clonada (XTTS-v2)

`jarvis/voice/xtts_engine.py` clona uma voz a partir de um clipe curto de referência (em
vez de usar uma das vozes prontas do macOS). É o motor padrão (`TTS_ENGINE=xtts`), mas só
entra em ação se as duas condições abaixo forem verdadeiras -- **sem elas, `speak()` cai
de volta pra voz padrão (`TTS_VOICE`, ex: Felipe) automaticamente, sem erro nenhum**:

1. `pip install -e ".[voice-cloning]"` rodado (~4GB: torch + coqui-tts).
2. Um clipe de referência salvo em `~/Library/Application Support/JARVIS/voice/jarvis_reference.wav`
   (`TTS_XTTS_SPEAKER_WAV_PATH` em `jarvis/config.py`) -- **de propósito fora da pasta do
   projeto** (que é sincronizada com o OneDrive) e **nunca baixado por mim/pelo JARVIS**:
   é dado biométrico de voz, você quem coloca esse arquivo lá.

Também precisa do FFmpeg instalado no sistema (`brew install ffmpeg`) -- não é dependência
Python, é a lib nativa que o `torchcodec` (leitor de áudio do torchaudio) carrega em tempo
de execução para decodificar o clipe de referência; sem ela, a síntese falha com um erro
claro (`Could not load libtorchcodec`) apontando exatamente pra isso.

**Roda num processo separado, de propósito.** Achado ao vivo: carregar o XTTS no mesmo
processo do loop de voz fazia o `torchcodec` carregar o FFmpeg do Homebrew no mesmo espaço
de memória que já tinha a própria cópia do FFmpeg do `faster-whisper` (via PyAV) carregada
-- o macOS registrava uma colisão de classe Objective-C real
(`AVFFrameReceiver`/`AVFAudioReceiver` definidas nas duas cópias), e a detecção de wake
word/palmas parava de disparar por completo, silenciosamente. Corrigido de verdade
rodando a síntese como um processo próprio:

- `jarvis/voice/xtts_worker.py` -- sobe um servidor HTTP local (só `127.0.0.1`, stdlib
  puro) e carrega o modelo, isolado do processo principal. Nunca importa `faster-whisper`
  nem toca no microfone -- confirmado ao vivo que roda sem nenhum aviso de colisão.
- `jarvis/voice/xtts_client.py` -- roda no processo principal (`conversation.py`), sobe o
  worker como subprocesso (`ensure_worker_started()`) e fala com ele por HTTP
  (`/health`, `/synthesize`). `tts.py` só conhece esse client, nunca o `xtts_engine`
  diretamente.

**Números reais medidos neste Mac (M5, 24GB RAM), incluindo o processo isolado:**
- Carregar o modelo no worker: ~13-18s. Roda em `device="cpu"`, não `mps` -- medido CPU
  mais rápido que MPS pra esse modelo (3,4s vs 11,4s pra gerar a mesma frase curta).
- Gerar fala: **7,8s para uma frase de ~7s** (quase tempo real) e **21,3s para uma fala de
  29,7s** (0,72x -- mais rápido que tempo real) -- medido isolado, antes de mover pro worker.
- **Confirmado ao vivo, de ponta a ponta**: worker isolado sobe, fica pronto, sintetiza via
  HTTP, e o processo principal (mesmo importando `faster-whisper` junto) não mostra nenhum
  aviso de colisão -- os três cenários testados separadamente antes de religar no loop real.
- Enquanto o worker ainda não carregou (ou não há clipe de referência), `speak()` usa a voz
  padrão normalmente -- nunca trava esperando.

## Adaptador da Gupy

Recomendação seguida: **Gupy primeiro, não LinkedIn.** O LinkedIn tem infraestrutura de
anti-automação bem documentada e agressiva (impressão digital comportamental/de
dispositivo, rate limiting, CAPTCHA, e termos de uso explícitos contra automatizar edição
de perfil) — risco real de restrição de conta desproporcional a automatizar algumas
edições pontuais. A Gupy é um ATS brasileiro voltado a candidatos, com perfil editável
como ação de usuário esperada e de primeira classe.

Login (uma vez só -- abre uma janela real de navegador, você loga normalmente, a sessão
fica salva):

```bash
python -m jarvis gupy-login
```

Ver o que mudaria no perfil da Gupy vs. o currículo local, sem aplicar nada:

```bash
python -m jarvis gupy-preview
```

Aplicar de verdade (pede confirmação explícita antes de enviar):

```bash
python -m jarvis gupy-apply
```

**O que já está verificado contra o site real, incluindo o envio de verdade:** login
persistente, leitura do perfil (nome/e-mail/telefone), comparação com o currículo local,
e a gravação real de **nome** e **telefone** -- clique real em "Salvar", confirmado ao
vivo (toast "Dados salvos com sucesso!", re-leitura do perfil depois do envio pra provar
que a mudança realmente pegou, registro de auditoria em JSON -- campo/valor
antigo/valor novo/quando, **não** um screenshot, já que a mesma tela também mostra CPF e
data de nascimento -- salvo fora da pasta do projeto, ver a seção "Arquitetura" acima,
`jarvis/sites/`, para onde exatamente). **O que falta, de propósito:** **e-mail** não é
escrito -- é também o identificador de login, e mudar esse campo pode disparar um fluxo
de verificação (código, confirmação por e-mail) que nunca foi observado; um plano que
inclua uma mudança de e-mail faz `apply_changes` recusar o pacote inteiro
(`NotImplementedError`) em vez de aplicar só parte dele. Experiência, formação e
certificações também ficam de fora -- vivem num sub-formulário separado da Gupy
("Meu currículo") ainda não inspecionado.

## Roadmap

- E-mail na Gupy: testar ao vivo, supervisionado, se mudar o e-mail dispara algum fluxo
  de verificação -- só então liberar em `_WRITABLE_FIELDS` (`jarvis/sites/gupy.py`).
- Sub-formulário "Meu currículo" da Gupy (experiência, formação, certificações,
  habilidades) -- inspeção ao vivo ainda não feita, hoje o adaptador só cobre a tela de
  contato.
- Catho: login/check_session funcionando (`jarvis/sites/catho.py`) -- falta inspecionar a
  página real do perfil (precisa de sessão autenticada) para implementar o resto. Só
  funciona com navegador visível (`headless=False`); a versão headless leva 403 do próprio
  site, confirmado ao vivo.
- Vagas.com: **pausado** de propósito -- o site fica atrás de Cloudflare e derruba a conexão
  do Playwright mesmo com navegador visível (`net::ERR_CONNECTION_RESET`), sinal mais forte
  de anti-automação que a Gupy. Mesmo raciocínio do LinkedIn (`jarvis/sites/base.py`): não
  vale escalar para técnicas de evasão. Só `check_session`/`login` implementados.
- Adaptadores restantes (InfoJobs, Indeed, Academia do Universitário) -- cada um precisa da
  mesma verificação ao vivo (domínios, seletores reais, e depois o envio real) feita para a
  Gupy, não dá pra generalizar sem repetir esse processo por site.
- MLXProvider como opção de menor latência.
- Itens extras no menu bar (abrir logs/perfil, revisar propostas pendentes direto do
  menu -- hoje só tem liga/desliga).
