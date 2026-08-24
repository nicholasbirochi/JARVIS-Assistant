"""The tool surface the local model uses to read/edit the résumé, push it
to job sites (eventually), and relay a prompt to Claude Code. Plain
functions with Google-style docstrings -- Ollama's client introspects
these directly into tool schemas, no decorator needed. Each résumé-editing
call re-loads/re-saves data/resume.json rather than sharing in-memory
state -- this is a low-throughput personal CLI, so the extra file IO is
irrelevant and it guarantees tools never see stale state.

prepare_claude_prompt() is how "tell Claude Code to do X" by voice
actually reaches Claude Code -- there's no API for JARVIS to inject text
into a running Claude Code conversation, so it copies a prompt to the
clipboard (and logs it locally as a durability net) for the user to
paste themselves, wherever/whenever they choose. That choice is
deliberate, not a limitation to route around: which project a request is
even about is Nicholas's call, not something to guess.

add_roadmap_item()/add_reminder()/list_reminders() are the two other
non-résumé tools -- respectively roadmap.py (appends to this
project's own README.md "## Roadmap" section) and reminders.py
(a flat local JSON note list). Both act directly, no clipboard hop --
unlike a real code change, appending one line to a list needs no human
review step to be safe.

find_matching_jobs()/list_recent_job_matches() drive job_search.py
-- a real, live search across InfoJobs/Catho/Gupy (bounded on purpose:
this runs synchronously inside a tool call, see that module's docstring
for why Indeed/LinkedIn are excluded from this automatic path).

evaluate_investments() drives finance.py -- reads the user's own
manually-maintained net-worth spreadsheet (Patrimônio.xlsx) as a local
stand-in for real bank integration, which is still pending the user
creating a Meu Pluggy account themselves.

check_job_application() drives GupyAdapter.preview_application()
(sites/gupy.py) -- two real, live, human-supervised pilots
(2026-08-12/13, two unrelated companies) both hit a company-specific
screening question before any submit screen was reachable (RG + salary
at one; salary expectation + culture-fit at the other) -- a real signal
that this is the Gupy norm, not an edge case. This tool never guesses at
an answer -- it walks the safe, verified steps (Gupy's own standard
referral questions, always answered "Não") and stops at the first
company-specific question, reporting each one individually with whether
it's genuine government-ID/birth-date data or another kind of block.

continue_job_application()/setup_application_profile() drive
GupyAdapter.continue_application_with_profile() and
sites/application_profile.py -- 2026-08-13, Nicholas explicitly
confirmed (after being told this reverses this project's original
"never capture RG/CPF, even incidentally" rule) that he wants a local,
never-synced file (LOCAL_STATE_DIR/application_profile.env) where he
provides his own RG/CPF/salary expectation/estado civil, so JARVIS can
fill company-specific screening questions that ask for exactly those
fields. All-or-nothing per step (refuses to partially fill a form), and
the real values never appear in a returned ApplicationQuestion, evidence
file, or log -- only whether a field was filled. Still never clicks a
genuine final submit -- that step has never been observed live -- so
even full success only means "advanced one more step," not "sent."
Gupy-only for now; other sites need their own live investigation
first.

open_job_portal() drives job_portal/ -- 2026-08-14, Nicholas
asked to move off the Claude Artifact ("mude para local...") after
being told the hosted page structurally can't reach local Playwright.
This is a real local HTTP server (127.0.0.1 only, port 8767) whose
buttons call the exact same check_job_application()/
continue_job_application() functions above -- opened in Nicholas's real
default browser, not a WKWebView."""

from __future__ import annotations

import json
import subprocess

from pydantic import ValidationError

from resume import store

SUPPORTED_SITES = ["LinkedIn", "Gupy", "Catho", "InfoJobs", "Vagas.com", "Indeed"]


def read_resume() -> str:
    """Retorna o currículo completo do Nicholas em JSON.

    Use sempre que precisar consultar os dados atuais do currículo, antes de
    responder uma pergunta sobre ele ou antes de editar um campo.
    """
    resume = store.load()
    return json.dumps(resume.model_dump(mode="json"), ensure_ascii=False)


def update_resume_field(path: str, value: str) -> str:
    """Atualiza um único campo do currículo, identificado por um caminho com pontos.

    Args:
        path: Caminho do campo, ex.: "personal_info.phone" ou "experience.0.title.pt".
              Índices de lista são números (0, 1, 2...).
        value: Novo valor como string. Para campos booleanos, numéricos ou listas,
               envie como JSON (ex.: "true", "42", '["item1", "item2"]').
    """
    resume = store.load()
    try:
        updated = store.update_field(resume, path, store.coerce_value(value), source="voice")
    except store.FieldPathError as exc:
        return f"Erro: {exc}"
    except ValidationError as exc:
        return f"Valor inválido para {path}: {exc}"
    store.save(updated)
    return f"Campo {path} atualizado com sucesso."


def list_supported_sites() -> str:
    """Lista os sites de vagas que o JARVIS já sabe (ou vai saber) atualizar."""
    return ", ".join(SUPPORTED_SITES)


def push_resume_to_site(site: str) -> str:
    """Publica o currículo atual no site de vagas indicado.

    Args:
        site: Nome do site, ex.: "LinkedIn", "Gupy", "Catho", "InfoJobs",
              "Vagas.com" ou "Indeed".
    """
    if site not in SUPPORTED_SITES:
        return f"'{site}' não está na lista de sites suportados: {', '.join(SUPPORTED_SITES)}."
    return (
        f"A atualização automática do {site} ainda não foi implementada "
        "-- isso chega numa fase futura do projeto."
    )


def prepare_claude_prompt(prompt: str) -> str:
    """Copia um prompt para a área de transferência, pronto para colar numa conversa com o Claude Code.

    Use quando o Nicholas pedir para mudar algo no código do JARVIS, em outro
    projeto, ou quiser passar um pedido para o Claude Code implementar. Escreva
    você mesmo o prompt completo e bem estruturado, com todo o contexto
    necessário -- não apenas repita a fala dele ao pé da letra, capriche como se
    estivesse escrevendo para um desenvolvedor de verdade. Ele mesmo decide, ao
    colar, se é sobre este projeto ou outro -- por isso nunca invente qual
    projeto/arquivo é, a menos que o Nicholas tenha dito.

    Args:
        prompt: O prompt completo, pronto para ser colado no Claude Code.
    """
    try:
        subprocess.run(["pbcopy"], input=prompt.encode("utf-8"), check=True)
    except Exception as exc:
        return f"Não consegui copiar para a área de transferência: {exc}"

    _log_claude_prompt(prompt)
    return "Prompt copiado para a área de transferência -- já pode colar numa conversa com o Claude Code."


def add_roadmap_item(description: str) -> str:
    """Adiciona um item à seção "## Roadmap" do README.md deste projeto.

    Use quando o Nicholas pedir para anotar uma ideia futura, uma
    melhoria pendente ou algo para revisitar depois no próprio JARVIS --
    diferente de prepare_claude_prompt, que é para pedir uma mudança já,
    isso só registra a ideia para depois.

    Args:
        description: Descrição curta e clara do item, pronta para virar
                      um marcador de lista (sem o "- " inicial).
    """
    from roadmap import RoadmapSectionMissing, add_item

    try:
        add_item(description)
    except RoadmapSectionMissing as exc:
        return f"Erro: {exc}"
    return "Adicionado ao roadmap do README."


def add_reminder(text: str) -> str:
    """Anota um lembrete pessoal para o Nicholas ver depois.

    Args:
        text: O texto do lembrete, como o Nicholas pediria para anotar.
    """
    import reminders

    reminders.add_reminder(text)
    return "Lembrete anotado."


def list_reminders() -> str:
    """Lista todos os lembretes já anotados, do mais antigo ao mais recente."""
    import reminders

    items = reminders.list_reminders()
    if not items:
        return "Nenhum lembrete anotado ainda."
    return "\n".join(f"- {r['text']} ({r['created_at']})" for r in items)


def find_matching_jobs() -> str:
    """Busca vagas de emprego reais que combinam com o currículo do Nicholas,
    em InfoJobs, Catho e Gupy -- separadas em presencial/híbrido perto dele
    (São Bernardo do Campo, Centro de São Paulo, região do ABC) e home
    office (nacional e internacional).

    Use quando o Nicholas pedir para buscar/procurar vagas de emprego.
    Essa busca é REAL (abre navegador de verdade, pode levar 1 a 2
    minutos) -- avise que vai demorar um pouco antes de chamar esta
    ferramenta. Não inclui Indeed (bloqueado no momento, ver roadmap) nem
    LinkedIn (precisa de login manual supervisionado) -- para esses dois,
    é preciso um pedido explícito à parte, fora desta ferramenta.
    """
    from job_search import run_job_search, save_report, summarize

    resume = store.load()
    report = run_job_search(resume)
    path = save_report(report)
    _publish_jobs_chart(report)
    return summarize(report, path)


def list_recent_job_matches() -> str:
    """Mostra o resultado da última busca de vagas já feita, sem buscar de novo.

    Use quando o Nicholas pedir para ver de novo as vagas encontradas
    antes, ou perguntar o que já tinha achado.
    """
    from job_search import latest_report_path

    path = latest_report_path()
    if path is None:
        return "Ainda não fiz nenhuma busca de vagas. Peça para eu buscar primeiro."
    return path.read_text(encoding="utf-8")


def evaluate_investments() -> str:
    """Avalia o patrimônio e os investimentos do Nicholas, lendo a planilha
    Patrimônio.xlsx que ele mesmo mantém (enquanto não há integração direta
    com os bancos).

    Use quando ele perguntar sobre patrimônio, investimentos, quanto tem
    guardado, quanto gastou, ou pedir uma avaliação financeira geral.
    """
    from finance import load_snapshot, summarize_finances

    try:
        snapshot = load_snapshot()
    except FileNotFoundError:
        return "Não encontrei a planilha Patrimônio.xlsx no caminho esperado."
    except Exception as exc:
        return f"Não consegui ler a planilha: {exc}"
    _publish_finance_chart(snapshot)
    return summarize_finances(snapshot)


def check_job_application(url: str) -> str:
    """Verifica até onde dá pra avançar com segurança numa candidatura de
    uma vaga específica (hoje só funciona para links do Gupy) -- NUNCA
    envia a candidatura de verdade. Só passa pelos passos já verificados
    ao vivo como seguros (a etapa inicial e as duas perguntas padrão da
    Gupy sobre indicação/vínculo, sempre respondidas "Não", o que é
    verdade para qualquer candidatura externa) e para assim que aparece
    qualquer pergunta própria da empresa -- nunca inventa uma resposta,
    mesmo que a pergunta pareça simples.

    Use quando o Nicholas pedir para verificar ou tentar se candidatar
    numa vaga específica pelo link. Deixe claro na resposta que isso NÃO
    é um envio automático de candidatura -- é uma checagem de até onde dá
    pra ir sozinho, e o que falta ele preencher manualmente.

    Args:
        url: Link da vaga (ex.: um dos retornados por find_matching_jobs).
    """
    if "gupy.io" not in url:
        return (
            "Só sei verificar candidaturas em vagas do Gupy por enquanto -- essa vaga não "
            "parece ser do Gupy. Abra o link e se candidate manualmente."
        )

    from sites.gupy import GupyAdapter

    try:
        preview = GupyAdapter().preview_application(url)
    except Exception as exc:
        return f"Não consegui verificar essa vaga: {exc}"

    return preview.summary_text or (preview.blocked_reason or "Não deu pra avançar nessa vaga.")


def continue_job_application(url: str) -> str:
    """Avança de verdade numa candidatura (vagas do Gupy) usando os dados
    do arquivo local de perfil de candidatura (RG, CPF, pretensão
    salarial, estado civil) -- só preenche uma pergunta da empresa se
    TODAS as perguntas daquela etapa tiverem valor real no arquivo local;
    se faltar uma só, não preenche nada (tudo ou nada, pra não deixar o
    formulário pela metade). NUNCA clica no envio final -- essa etapa
    nunca foi confirmada ao vivo, então sempre para antes dela, mesmo
    quando consegue preencher tudo.

    Use quando o Nicholas pedir explicitamente para continuar/avançar
    numa candidatura específica usando os dados que ele já configurou.
    Deixe claro que isso preenche de verdade mas NÃO envia -- ele ainda
    precisa confirmar manualmente o envio final no navegador.

    Args:
        url: Link da vaga (ex.: um dos retornados por find_matching_jobs).
    """
    if "gupy.io" not in url:
        return (
            "Só sei avançar candidaturas em vagas do Gupy por enquanto -- essa vaga não "
            "parece ser do Gupy."
        )

    from sites.gupy import GupyAdapter

    try:
        preview = GupyAdapter().continue_application_with_profile(url, confirmed=True)
    except Exception as exc:
        return f"Não consegui avançar essa candidatura: {exc}"

    return preview.summary_text or (preview.blocked_reason or "Não deu pra avançar nessa vaga.")


def setup_application_profile() -> str:
    """Cria (se ainda não existir) o arquivo local onde o Nicholas
    preenche RG, órgão/estado de emissão do RG, CPF, nome da mãe, nome
    do pai, naturalidade, pretensão salarial (estágio/júnior/pleno,
    separadas) e estado civil -- nunca sincronizado, nunca versionado,
    lido só localmente pelo JARVIS.

    Use quando ele pedir para configurar/criar o arquivo de dados para
    candidaturas automáticas.
    """
    from sites.application_profile import ensure_profile_template

    path = ensure_profile_template()
    return (
        f"Arquivo pronto em {path}. Abra com um editor de texto e preencha os valores "
        "depois do '=' em cada linha (RG e detalhes, CPF, nome da mãe/pai, naturalidade, "
        "pretensão salarial por nível, estado civil). "
        "Nunca digo em voz alta o que está nesse arquivo."
    )


def open_job_portal() -> str:
    """Abre a página local de vagas por empresa (bancos/bigtechs/
    startups) no navegador de verdade do Nicholas -- diferente do
    artefato hospedado na Anthropic, essa página roda um servidor local
    (job_portal/) e os botões "Verificar"/"Continuar candidatura"
    de fato chamam check_job_application()/continue_job_application()
    aqui no Mac dele.

    2026-08-21, real bug fixed: this used to run the WHOLE deep search
    (12-15 terms across 9 sites, up to ~an hour) BEFORE ever starting the
    HTTP server, so the page was completely unreachable ("o site
    continua sem funcionar") for the entire wait, with zero feedback.
    Now the server starts and the browser opens immediately (showing the
    real empty state page_template.html already handles), and the first
    search runs in a background thread -- the page is reachable right
    away and just fills in once the search actually finishes; a later
    "Atualizar vagas agora" click, or reopening the tool, shows what's
    there so far.

    Use quando o Nicholas pedir para abrir/ver as vagas localmente, ou
    pedir para poder se candidatar clicando em botões em vez de te
    pedir link por link.
    """
    import threading

    from job_portal import server

    page_url = server.open_portal()

    if server._tiers is None:  # first open this process -- fetch real data now
        def _refresh_in_background() -> None:
            try:
                # include_linkedin=True -- opening the portal is itself
                # an explicit, attended action (see _portal_adapters()'s
                # docstring for why that's the bar for including
                # LinkedIn).
                server.refresh_data(adapters=server._portal_adapters(include_linkedin=True))
            except Exception:
                pass  # best-effort -- the page's own empty state already tells Nicholas nothing loaded yet

        threading.Thread(target=_refresh_in_background, daemon=True, name="jarvis-job-portal-first-search").start()
        return (
            f"Abri {page_url} no seu navegador -- já dá pra acessar, mas a primeira busca "
            "ainda está rodando em segundo plano (pode levar uns minutos). A página não "
            "atualiza sozinha -- dê um F5/Cmd+R nela daqui a pouco pra ver as vagas."
        )

    return f"Abri {page_url} no seu navegador -- os botões ali rodam de verdade, local."


def _publish_jobs_chart(report) -> None:
    """Pushes a live bar chart (vagas por site, local vs. home office) to
    the HUD (visualizer/) -- best-effort, same reasoning as
    _log_claude_prompt below: a visualization failing (HUD not open, or
    running headless in a test) must never break the actual tool result
    it's illustrating."""
    try:
        from collections import Counter

        from visualizer import state as visualizer_state

        local_counts = Counter(listing.site_name for listing in report.local)
        remote_counts = Counter(listing.site_name for listing in report.remote)
        bars = []
        for site in report.sites_searched:
            bars.append({"label": f"{site} local", "value": local_counts.get(site, 0)})
            bars.append({"label": f"{site} remoto", "value": remote_counts.get(site, 0)})
        title = f"{len(report.local)} presencial + {len(report.remote)} home office"
        visualizer_state.publish_data("jobs", {"title": title, "bars": bars})
    except Exception:
        pass


def _publish_finance_chart(snapshot) -> None:
    """Pushes live charts (patrimônio por conta, maiores despesas, salário
    por mês) to the HUD -- best-effort, see _publish_jobs_chart's
    docstring for why."""
    try:
        from finance import expenses_by_category, format_brl, format_month, salary_by_month
        from visualizer import state as visualizer_state

        sections = []
        if snapshot.banks:
            sections.append(
                {
                    "type": "bar",
                    "title": "Por conta",
                    "bars": [{"label": b.bank, "value": round(b.total_brl, 2)} for b in snapshot.banks],
                }
            )
        top_expenses = expenses_by_category(snapshot, top_n=5)
        if top_expenses:
            sections.append(
                {
                    "type": "bar",
                    "title": "Maiores despesas",
                    "bars": [{"label": kind, "value": round(total, 2)} for kind, total in top_expenses],
                }
            )
        salary_trend = salary_by_month(snapshot)
        if len(salary_trend) >= 2:
            sections.append(
                {
                    "type": "line",
                    "title": "Salário por mês",
                    "points": [
                        {"label": format_month(when), "value": round(amount, 2)} for when, amount in salary_trend
                    ],
                }
            )

        title = f"Patrimônio: R$ {format_brl(snapshot.final_money)}" if snapshot.final_money is not None else "Patrimônio"
        visualizer_state.publish_data("finance", {"title": title, "sections": sections})
    except Exception:
        pass


def _log_claude_prompt(prompt: str) -> None:
    """Best-effort durability net so a prompt isn't lost if it isn't
    pasted right away -- never raises, since a logging hiccup here must
    never turn an already-successful clipboard copy into a reported
    failure."""
    try:
        from datetime import datetime, timezone

        from config import LOCAL_STATE_DIR

        log_path = LOCAL_STATE_DIR / "claude_prompts.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat()
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"--- {timestamp} ---\n{prompt}\n\n")
    except Exception:
        pass


TOOLS = [
    read_resume,
    update_resume_field,
    list_supported_sites,
    push_resume_to_site,
    prepare_claude_prompt,
    add_roadmap_item,
    add_reminder,
    list_reminders,
    find_matching_jobs,
    list_recent_job_matches,
    check_job_application,
    continue_job_application,
    setup_application_profile,
    open_job_portal,
    evaluate_investments,
]
