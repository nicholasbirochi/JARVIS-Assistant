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
non-résumé tools -- respectively jarvis/roadmap.py (appends to this
project's own README.md "## Roadmap" section) and jarvis/reminders.py
(a flat local JSON note list). Both act directly, no clipboard hop --
unlike a real code change, appending one line to a list needs no human
review step to be safe.

find_matching_jobs()/list_recent_job_matches() drive jarvis/job_search.py
-- a real, live search across InfoJobs/Catho/Gupy (bounded on purpose:
this runs synchronously inside a tool call, see that module's docstring
for why Indeed/LinkedIn are excluded from this automatic path).

evaluate_investments() drives jarvis/finance.py -- reads the user's own
manually-maintained net-worth spreadsheet (Patrimônio.xlsx) as a local
stand-in for real bank integration, which is still pending the user
creating a Meu Pluggy account themselves."""

from __future__ import annotations

import json
import subprocess

from pydantic import ValidationError

from jarvis.resume import store

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
    from jarvis.roadmap import RoadmapSectionMissing, add_item

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
    from jarvis import reminders

    reminders.add_reminder(text)
    return "Lembrete anotado."


def list_reminders() -> str:
    """Lista todos os lembretes já anotados, do mais antigo ao mais recente."""
    from jarvis import reminders

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
    from jarvis.job_search import run_job_search, save_report, summarize

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
    from jarvis.job_search import latest_report_path

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
    from jarvis.finance import load_snapshot, summarize_finances

    try:
        snapshot = load_snapshot()
    except FileNotFoundError:
        return "Não encontrei a planilha Patrimônio.xlsx no caminho esperado."
    except Exception as exc:
        return f"Não consegui ler a planilha: {exc}"
    _publish_finance_chart(snapshot)
    return summarize_finances(snapshot)


def _publish_jobs_chart(report) -> None:
    """Pushes a live bar chart (vagas por site, local vs. home office) to
    the HUD (jarvis/visualizer/) -- best-effort, same reasoning as
    _log_claude_prompt below: a visualization failing (HUD not open, or
    running headless in a test) must never break the actual tool result
    it's illustrating."""
    try:
        from collections import Counter

        from jarvis.visualizer import state as visualizer_state

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
    """Pushes a live bar chart (patrimônio por conta) to the HUD --
    best-effort, see _publish_jobs_chart's docstring for why."""
    try:
        from jarvis.finance import format_brl
        from jarvis.visualizer import state as visualizer_state

        bars = [{"label": b.bank, "value": round(b.total_brl, 2)} for b in snapshot.banks]
        title = f"Patrimônio: R$ {format_brl(snapshot.final_money)}" if snapshot.final_money is not None else "Patrimônio"
        visualizer_state.publish_data("finance", {"title": title, "bars": bars})
    except Exception:
        pass


def _log_claude_prompt(prompt: str) -> None:
    """Best-effort durability net so a prompt isn't lost if it isn't
    pasted right away -- never raises, since a logging hiccup here must
    never turn an already-successful clipboard copy into a reported
    failure."""
    try:
        from datetime import datetime, timezone

        from jarvis.config import LOCAL_STATE_DIR

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
    evaluate_investments,
]
