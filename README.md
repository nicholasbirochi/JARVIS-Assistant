# J.A.R.V.I.S

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
  tocar em nenhum desses chamadores.
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
  automaticamente no login via LaunchAgent -- ver "Iniciar automaticamente" abaixo.

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
ollama pull qwen2.5:14b   # ~9GB, baixa uma vez

# Só necessário se for usar os adaptadores de site (jarvis/sites/) -- baixa o Chromium
# que o Playwright controla (não é o seu navegador normal, ~150MB, uma vez só)
playwright install chromium
```

Nenhuma chave é obrigatória por padrão. `.env` só é necessário se você quiser usar o
Porcupine como motor de wake word (`WAKE_WORD_ENGINE=porcupine` + `PICOVOICE_ACCESS_KEY`)
em vez do openWakeWord padrão, apontar para um Ollama/modelo diferente, ou trocar a voz
do TTS (`TTS_VOICE` -- ver `.env.example` para como achar uma boa voz masculina, já que
as que o macOS instala por padrão são de baixa qualidade).

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

Se as palmas não estiverem sendo detectadas (ou disparando à toa), meça o pico real do
seu microfone/ambiente antes de ajustar `CLAP_PEAK_THRESHOLD` no `.env`:

```bash
python -m jarvis calibrate-claps
```

App de menu bar (mesma coisa, com um ícone e botão liga/desliga):

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
- Adaptadores restantes (Catho, InfoJobs, Vagas.com, Indeed, Academia do Universitário) --
  cada um precisa da mesma verificação ao vivo (domínios, seletores reais, e depois o
  envio real) feita para a Gupy, não dá pra generalizar sem repetir esse processo por
  site.
- MLXProvider como opção de menor latência.
- Itens extras no menu bar (abrir logs/perfil, revisar propostas pendentes direto do
  menu -- hoje só tem liga/desliga).
