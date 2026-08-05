"""Entrypoint: `python -m jarvis` for the full voice loop, or
`python -m jarvis --text-only` to exercise the same conversation/tools logic
by typing instead of speaking -- no mic, wake-word engine, or TTS needed.
`python -m jarvis index` scans authorized directories for résumé updates;
`python -m jarvis review-proposals` reviews the most recent proposal;
`python -m jarvis menubar` runs the macOS menu-bar on/off toggle;
`python -m jarvis calibrate-claps` prints live mic peak amplitude to help
tune CLAP_PEAK_THRESHOLD."""

from __future__ import annotations

import argparse


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

    from jarvis.assistant.conversation import run_text_loop, run_voice_loop

    if args.text_only:
        run_text_loop()
    else:
        run_voice_loop()


if __name__ == "__main__":
    main()
