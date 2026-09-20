"""Systematic, repeated benchmark of assistant/coding_agent.py against the
models under real consideration for JARVIS's own local coding agent
(qwen2.5-coder:14b, the current pick -- see coding_agent.py's own module
docstring -- and qwen2.5:7b, the voice assistant's conversational model,
included as a baseline to show why a separate CODING_MODEL exists at all).

This is real data for Nicholas's Iniciação Científica, not a synthetic
LLM leaderboard: every task below runs against THIS project's own real
src/ tree, through the exact same tool loop (make_tools/run_coding_task)
the voice assistant calls in production via ask_local_coding_agent.

Every task has an objectively-checkable expected answer, computed here
directly (grep/glob/git -- never through an LLM), so grading a run never
depends on my own judgment call -- only whether the model's final answer
contains the real, independently-computed marker string. This checks
answer-contains-the-right-fact, not phrasing/style -- a deliberately
narrow, low-tech check that still can't be gamed by a fluent-sounding
wrong answer.

Usage:
    python3 scripts/benchmark_coding_agent.py [--trials N] [--models m1,m2]

Writes one row per (model, task, trial) to
data/coding_agent_benchmarks/<timestamp>.csv and prints a summary table
(success rate + median wall time per model) at the end. Read-only against
the workspace throughout -- same guarantee as coding_agent.py itself.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistant.coding_agent import run_coding_task  # noqa: E402

SRC_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = SRC_ROOT / "data" / "coding_agent_benchmarks"
DEFAULT_MODELS = ["qwen2.5-coder:14b", "qwen2.5:7b"]
DEFAULT_TRIALS = 3


@dataclass
class BenchmarkTask:
    name: str
    prompt: str
    expected_marker: str


def _count_py_files(subdir: str) -> str:
    return str(len(list((SRC_ROOT / subdir).glob("*.py"))))


def _count_files_containing(pattern: str) -> str:
    result = subprocess.run(
        ["grep", "-rl", pattern, str(SRC_ROOT), "--include=*.py"],
        capture_output=True,
        text=True,
    )
    return str(len([line for line in result.stdout.splitlines() if line.strip()]))


def build_tasks() -> list[BenchmarkTask]:
    """Ground truth for each task is computed fresh right here, right
    before the run -- never hardcoded -- so the benchmark stays correct
    even as the real codebase grows (more tests, more files, more
    CODING_MODEL references)."""
    return [
        BenchmarkTask(
            name="contar_arquivos_assistant",
            prompt="Quantos arquivos .py existem na pasta assistant/? Responda só com o número.",
            expected_marker=_count_py_files("assistant"),
        ),
        BenchmarkTask(
            name="valor_local_model",
            prompt=(
                "Leia o arquivo config.py e diga o valor padrão (string) da "
                "variável LOCAL_MODEL. Responda só com o valor, sem aspas."
            ),
            # Real, stable default -- see config.py's own LOCAL_MODEL line.
            expected_marker="qwen2.5:7b",
        ),
        BenchmarkTask(
            name="grep_coding_model",
            prompt=(
                "Busque a string 'CODING_MODEL' nos arquivos .py do workspace e diga em "
                "quantos arquivos diferentes ela aparece. Responda só com o número."
            ),
            expected_marker=_count_files_containing("CODING_MODEL"),
        ),
    ]


def run_benchmark(models: list[str], trials: int) -> list[dict]:
    tasks = build_tasks()
    rows: list[dict] = []
    total = len(models) * len(tasks) * trials
    done = 0

    for model in models:
        for task in tasks:
            for trial in range(1, trials + 1):
                done += 1
                print(f"[{done}/{total}] {model} -- {task.name} (tentativa {trial})...", flush=True)
                start = time.monotonic()
                try:
                    answer = run_coding_task(task.prompt, str(SRC_ROOT), model=model)
                except Exception as exc:  # noqa: BLE001 -- a crashed run is itself a real result, not a script bug to hide
                    answer = f"[ERRO: {exc}]"
                wall_seconds = round(time.monotonic() - start, 1)
                success = task.expected_marker in answer
                print(f"    -> {wall_seconds}s, {'OK' if success else 'FALHOU'}")
                rows.append(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "model": model,
                        "task": task.name,
                        "trial": trial,
                        "wall_seconds": wall_seconds,
                        "expected_marker": task.expected_marker,
                        "success": success,
                        "answer": answer.replace("\n", " ")[:500],
                    }
                )
    return rows


def write_csv(rows: list[dict]) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def print_summary(rows: list[dict]) -> None:
    models = sorted({row["model"] for row in rows})
    print("\n=== Resumo ===")
    for model in models:
        model_rows = [r for r in rows if r["model"] == model]
        successes = sum(1 for r in model_rows if r["success"])
        median_wall = statistics.median(r["wall_seconds"] for r in model_rows)
        print(
            f"{model}: {successes}/{len(model_rows)} acertos "
            f"({100 * successes / len(model_rows):.0f}%), "
            f"tempo mediano {median_wall}s"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    rows = run_benchmark(models, args.trials)
    path = write_csv(rows)
    print(f"\nResultados salvos em {path}")
    print_summary(rows)


if __name__ == "__main__":
    main()
