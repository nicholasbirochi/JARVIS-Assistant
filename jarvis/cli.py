"""Entrypoint: `python -m jarvis` for the full voice loop, or
`python -m jarvis --text-only` to exercise the same conversation/tools logic
by typing instead of speaking -- no mic, wake-word engine, or TTS needed.
`python -m jarvis index` scans authorized directories for résumé updates;
`python -m jarvis review-proposals` reviews the most recent proposal;
`python -m jarvis menubar` runs the macOS menu-bar on/off toggle;
`python -m jarvis calibrate-claps` prints live mic peak amplitude to help
tune CLAP_PEAK_THRESHOLD; `python -m jarvis gupy-login` / `gupy-preview` /
`gupy-apply` drive the Gupy site adapter (jarvis/sites/gupy.py);
`vagas-login` / `vagas-preview` / `vagas-apply` drive the Vagas.com one
(jarvis/sites/vagas.py, paused at login/check_session -- see its module
docstring); `catho-login` / `catho-preview` / `catho-apply` drive Catho
(jarvis/sites/catho.py); `infojobs-login` / `infojobs-preview` /
`infojobs-apply` drive InfoJobs (jarvis/sites/infojobs.py);
`indeed-login` / `indeed-preview` / `indeed-apply` drive Indeed
(jarvis/sites/indeed.py); `linkedin-login` opens LinkedIn for manual login
(jarvis/sites/linkedin.py, search_jobs() only -- profile editing is
permanently out of scope there, so there's no linkedin-preview/-apply)."""

from __future__ import annotations

import argparse


def _run_site(adapter, display_name: str, login_command: str, apply_changes: bool) -> None:
    """Shared preview/apply flow for every site adapter -- adapter-specific
    logic lives entirely in the adapter (jarvis/sites/<site>.py); this is
    just the generic "check session, diff, show, confirm, apply" shell."""
    from jarvis.resume import store
    from jarvis.sites.base import SessionStatus

    status = adapter.check_session()
    if status != SessionStatus.AUTHENTICATED:
        print(f"Sessão da {display_name}: {status.value}. Rode `python -m jarvis {login_command}` primeiro.")
        return

    try:
        current = adapter.inspect_current_profile()
    except NotImplementedError as exc:
        print(f"Ainda não: {exc}")
        return

    plan = adapter.build_update_plan(store.load(), current)
    preview = adapter.preview_changes(plan)
    print(preview.summary_text)

    if not apply_changes or not plan.changes:
        return

    answer = input(f"Aplicar essas mudanças na {display_name} de verdade? [s/N] ").strip().lower()
    if not answer.startswith("s"):
        print("Cancelado -- nada foi enviado.")
        return

    try:
        result = adapter.apply_changes(plan, confirmed=True)
    except NotImplementedError as exc:
        print(f"Ainda não: {exc}")
        return

    if result.applied:
        print(f"Aplicado: {len(result.changes_applied)} mudança(s).")
    else:
        print(f"Falhou: {result.error}")


def _run_gupy(apply_changes: bool) -> None:
    from jarvis.sites.gupy import GupyAdapter

    _run_site(GupyAdapter(), "Gupy", "gupy-login", apply_changes)


def _run_vagas(apply_changes: bool) -> None:
    from jarvis.sites.vagas import VagasAdapter

    _run_site(VagasAdapter(), "Vagas.com", "vagas-login", apply_changes)


def _run_catho(apply_changes: bool) -> None:
    from jarvis.sites.catho import CathoAdapter

    _run_site(CathoAdapter(), "Catho", "catho-login", apply_changes)


def _run_infojobs(apply_changes: bool) -> None:
    from jarvis.sites.infojobs import InfoJobsAdapter

    _run_site(InfoJobsAdapter(), "InfoJobs", "infojobs-login", apply_changes)


def _run_indeed(apply_changes: bool) -> None:
    from jarvis.sites.indeed import IndeedAdapter

    _run_site(IndeedAdapter(), "Indeed", "indeed-login", apply_changes)


def main() -> None:
    parser = argparse.ArgumentParser(prog="jarvis")
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="Modo de depuração: digite em vez de falar, sem wake word/mic/TTS.",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "index", help="Escaneia diretórios autorizados e gera uma proposta de atualização do currículo."
    )
    subparsers.add_parser("review-proposals", help="Revisa interativamente a proposta mais recente.")
    subparsers.add_parser("menubar", help="App de menu bar do macOS com botão liga/desliga.")
    subparsers.add_parser(
        "calibrate-claps",
        help="Mostra o pico de amplitude de cada som captado, para ajustar CLAP_PEAK_THRESHOLD.",
    )
    subparsers.add_parser("gupy-login", help="Abre um navegador para login manual (uma vez só) na Gupy.")
    subparsers.add_parser(
        "gupy-preview", help="Mostra (sem aplicar) o que mudaria no perfil da Gupy vs. o currículo local."
    )
    subparsers.add_parser(
        "gupy-apply", help="Aplica de verdade as mudanças no perfil da Gupy, após confirmação explícita."
    )
    subparsers.add_parser("vagas-login", help="Abre um navegador para login manual (uma vez só) no Vagas.com.")
    subparsers.add_parser(
        "vagas-preview", help="Mostra (sem aplicar) o que mudaria no perfil do Vagas.com vs. o currículo local."
    )
    subparsers.add_parser(
        "vagas-apply", help="Aplica de verdade as mudanças no perfil do Vagas.com, após confirmação explícita."
    )
    subparsers.add_parser("catho-login", help="Abre um navegador para login manual (uma vez só) na Catho.")
    subparsers.add_parser(
        "catho-preview", help="Mostra (sem aplicar) o que mudaria no perfil da Catho vs. o currículo local."
    )
    subparsers.add_parser(
        "catho-apply", help="Aplica de verdade as mudanças no perfil da Catho, após confirmação explícita."
    )
    subparsers.add_parser("infojobs-login", help="Abre um navegador para login manual (uma vez só) no InfoJobs.")
    subparsers.add_parser(
        "infojobs-preview", help="Mostra (sem aplicar) o que mudaria no perfil do InfoJobs vs. o currículo local."
    )
    subparsers.add_parser(
        "infojobs-apply", help="Aplica de verdade as mudanças no perfil do InfoJobs, após confirmação explícita."
    )
    subparsers.add_parser("indeed-login", help="Abre um navegador para login manual (uma vez só) no Indeed.")
    subparsers.add_parser(
        "indeed-preview", help="Mostra (sem aplicar) o que mudaria no perfil do Indeed vs. o currículo local."
    )
    subparsers.add_parser(
        "indeed-apply", help="Aplica de verdade as mudanças no perfil do Indeed, após confirmação explícita."
    )
    subparsers.add_parser(
        "linkedin-login", help="Abre um navegador para login manual (uma vez só) no LinkedIn (só busca de vagas)."
    )
    args = parser.parse_args()

    if args.command == "index":
        from jarvis.indexing.runner import run

        result = run()
        if result is None:
            print("Nenhum arquivo novo ou alterado encontrado.")
        else:
            print(f"Proposta escrita em {result}")
            print("Rode `python -m jarvis review-proposals` para revisar.")
        return

    if args.command == "review-proposals":
        from jarvis.indexing.review import main as review_main

        review_main()
        return

    if args.command == "menubar":
        from jarvis.menubar import main as menubar_main

        menubar_main()
        return

    if args.command == "calibrate-claps":
        from jarvis.voice.calibrate import run as calibrate_run

        calibrate_run()
        return

    if args.command == "gupy-login":
        from jarvis.sites.gupy import GupyAdapter

        GupyAdapter().login()
        return

    if args.command in ("gupy-preview", "gupy-apply"):
        _run_gupy(apply_changes=args.command == "gupy-apply")
        return

    if args.command == "vagas-login":
        from jarvis.sites.vagas import VagasAdapter

        VagasAdapter().login()
        return

    if args.command in ("vagas-preview", "vagas-apply"):
        _run_vagas(apply_changes=args.command == "vagas-apply")
        return

    if args.command == "catho-login":
        from jarvis.sites.catho import CathoAdapter

        CathoAdapter().login()
        return

    if args.command in ("catho-preview", "catho-apply"):
        _run_catho(apply_changes=args.command == "catho-apply")
        return

    if args.command == "infojobs-login":
        from jarvis.sites.infojobs import InfoJobsAdapter

        InfoJobsAdapter().login()
        return

    if args.command in ("infojobs-preview", "infojobs-apply"):
        _run_infojobs(apply_changes=args.command == "infojobs-apply")
        return

    if args.command == "indeed-login":
        from jarvis.sites.indeed import IndeedAdapter

        IndeedAdapter().login()
        return

    if args.command in ("indeed-preview", "indeed-apply"):
        _run_indeed(apply_changes=args.command == "indeed-apply")
        return

    if args.command == "linkedin-login":
        from jarvis.sites.linkedin import LinkedInAdapter

        LinkedInAdapter().login()
        return

    from jarvis.assistant.conversation import run_text_loop, run_voice_loop

    if args.text_only:
        run_text_loop()
    else:
        run_voice_loop()


if __name__ == "__main__":
    main()
