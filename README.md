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

Estado atual: **Etapas 1-4 completas** (diagnóstico, consolidação de dados + indexação
incremental, voz totalmente local, app de menu bar). A implementação real do primeiro
adaptador de site (**Etapa 5**, já com design e recomendação prontos) fica para uma
próxima rodada.

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
- **`jarvis/sites/base.py`** — interface `SiteAdapter` (design pronto, nenhum adaptador
  implementado ainda). Ver seção "Próximo adaptador de site" abaixo.
- **`jarvis/menubar.py`** — app de menu bar (macOS) com botão liga/desliga; roda o loop
  de voz em background thread, controlado por `VoiceLoopController`. Sempre iniciado
  manualmente (`python -m jarvis menubar`), nunca no login.

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
```

Nenhuma chave é obrigatória por padrão. `.env` só é necessário se você quiser usar o
Porcupine como motor de wake word (`WAKE_WORD_ENGINE=porcupine` + `PICOVOICE_ACCESS_KEY`)
em vez do openWakeWord padrão, ou apontar para um Ollama/modelo diferente.

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

App de menu bar (mesma coisa, com um ícone e botão liga/desliga):

```bash
python -m jarvis menubar
```

## Próximo adaptador de site

Recomendação: **Gupy primeiro, não LinkedIn.** O LinkedIn tem infraestrutura de
anti-automação bem documentada e agressiva (impressão digital comportamental/de
dispositivo, rate limiting, CAPTCHA, e termos de uso explícitos contra automatizar edição
de perfil) — risco real de restrição de conta desproporcional a automatizar algumas
edições pontuais. A Gupy é um ATS brasileiro voltado a candidatos, com perfil editável
como ação de usuário esperada e de primeira classe — mais próximo de um CRUD de
formulário comum do que um alvo adversarial. Ainda assim, isso é um julgamento
comparativo, não um fato verificado — validar com uma sessão lenta e de baixo volume
contra a conta real antes de investir engenharia de verdade. A interface `SiteAdapter`
(`jarvis/sites/base.py`) já está pronta: sessão persistente via Playwright (login manual
único, sem senha armazenada), leitura do perfil atual, plano de atualização, *dry run*
com diff, confirmação explícita antes de qualquer envio real.

## Roadmap

- **Etapa 5**: implementar o primeiro adaptador real (Gupy, ver acima) seguindo a
  interface já definida em `jarvis/sites/base.py`.
- Depois: adaptadores restantes (Catho, InfoJobs, Vagas.com, Indeed, Academia do
  Universitário) + mapeamento de campos por site; MLXProvider como opção de menor
  latência; detecção de duplicatas entre propostas do indexador; itens extras no menu
  bar (abrir logs/perfil, revisar propostas pendentes direto do menu -- hoje só tem
  liga/desliga).
