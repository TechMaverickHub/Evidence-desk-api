"""Answer-evaluation commands, registered on `python -m app.evaluation.cli`:

answer-run    --config eval/configs/answers-rerank20.yaml --dataset ... --split dev
              --tenant eval-corpus-v1 [--allow-test] [--pace 2.0]
answer-judge  eval/reports/answers-rerank20-dev.json --dataset ... --tenant ...
answer-report eval/reports/answers-rerank20-dev.json --dataset ... [--sheet PATH]
              [--agreement 18/20] [--gate 1.5]
"""

import argparse
import re
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.evaluation.answer_records import AnswerRunReport, JudgeAgreement
from app.evaluation.answer_report import render_answer_run, render_spot_check
from app.evaluation.answer_runner import (
    AnswerDeps,
    Pacer,
    execute_answer_run,
    load_answer_config,
)
from app.evaluation.dataset import load_dataset, read_corpus_texts
from app.evaluation.judge import judge_run
from app.evaluation.runner import RunError, tenant_id_by_name
from app.generation.deps import build_llm_client
from app.generation.llm_client import LLMClient
from app.generation.prompts import load_judge_prompts, load_prompts
from app.retrieval.deps import get_query_embedder, get_reranker

ANSWER_COMMANDS = {"answer-run", "answer-judge", "answer-report"}


def build_llm(model: str) -> LLMClient:
    llm = build_llm_client(model)
    if llm is None:
        raise RunError("No GROQ_API_KEY is configured; answer runs need the LLM provider.")
    return llm


def build_answer_deps() -> AnswerDeps:
    """The API's own dependencies, so a run answers exactly as /v1/answers does."""
    llm = build_llm(get_settings().llm_model)
    return AnswerDeps(get_query_embedder(), get_reranker, llm, load_prompts())


def run_answer_command(args: argparse.Namespace) -> int:
    handlers = {
        "answer-run": _answer_run,
        "answer-judge": _answer_judge,
        "answer-report": _answer_report,
    }
    return handlers[args.command](args)


def _answer_run(args: argparse.Namespace) -> int:
    if args.split == "test" and not args.allow_test:
        print("Refusing to run on the test split without --allow-test.", file=sys.stderr)
        return 2
    config = load_answer_config(args.config)
    dataset = load_dataset(args.dataset)
    corpus_texts = read_corpus_texts(args.manifest)
    deps = build_answer_deps()
    base = args.out_dir / f"answers-{config.name}-{args.split}"
    partial = base.with_suffix(".partial.jsonl")
    with get_sessionmaker()() as session:
        tenant_id = tenant_id_by_name(session, args.tenant)
        report = execute_answer_run(
            session, tenant_id, config, dataset, args.split, corpus_texts, deps,
            partial, Pacer(args.pace),
        )  # fmt: skip
    _save(report, base.with_suffix(".json"))
    if not any(record.outcome == "error" for record in report.records):
        # Complete: the partial file has served its purpose. With errors, it stays so a
        # rerun retries only the failed questions.
        partial.unlink()
    print(f"Answer run written to {base.with_suffix('.json')} and {base.with_suffix('.md')}")
    return 0


def _answer_judge(args: argparse.Namespace) -> int:
    report = _read(args.record)
    dataset = load_dataset(args.dataset)
    llm = build_llm(get_settings().llm_judge_model)
    with get_sessionmaker()() as session:
        tenant_id = tenant_id_by_name(session, args.tenant)
        judge_run(
            session, tenant_id, report, {q.id: q for q in dataset.questions}, llm,
            load_judge_prompts(), Pacer(args.pace), lambda r: _save(r, args.record),
        )  # fmt: skip
    _save(report, args.record)
    print(f"Judged {args.record}")
    return 0


def _answer_report(args: argparse.Namespace) -> int:
    report = _read(args.record)
    if args.agreement:
        agreed, checked = _parse_agreement(args.agreement)
        report.header.judge_agreement = JudgeAgreement(checked=checked, agreed=agreed)
    _save(report, args.record, gate=args.gate)
    if args.sheet:
        questions = {q.id: q for q in load_dataset(args.dataset).questions}
        _write_text(args.sheet, render_spot_check(report, questions))
        print(f"Spot-check sheet written to {args.sheet}")
    return 0


def _parse_agreement(text: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)/(\d+)", text)
    if match is None or int(match[1]) > int(match[2]):
        raise RunError(f"--agreement must look like 18/20, got {text!r}")
    return int(match[1]), int(match[2])


def _read(path: Path) -> AnswerRunReport:
    try:
        return AnswerRunReport.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise RunError(f"Cannot read answer run {path}: {exc}") from exc


def _save(report: AnswerRunReport, json_path: Path, gate: float | None = None) -> None:
    _write_text(json_path, report.model_dump_json(indent=1) + "\n")
    _write_text(json_path.with_suffix(".md"), render_answer_run(report, gate))


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Bytes, not text mode: committed reports keep LF line endings on Windows too.
    path.write_bytes(text.encode("utf-8"))


def add_answer_commands(commands: argparse._SubParsersAction) -> None:
    run = commands.add_parser("answer-run", help="Answer every question of a split")
    run.add_argument("--config", required=True, type=Path, help="eval/configs/answers-*.yaml")
    run.add_argument("--dataset", required=True, type=Path)
    run.add_argument("--split", required=True, choices=["dev", "test"])
    run.add_argument("--tenant", required=True)
    run.add_argument("--manifest", type=Path, default=Path("corpus/manifest.yaml"))
    run.add_argument("--out-dir", type=Path, default=Path("eval/reports"))
    run.add_argument("--allow-test", action="store_true")
    run.add_argument("--pace", type=float, default=2.0, help="Min seconds between questions")

    judge = commands.add_parser("answer-judge", help="Add LLM verdicts to an answer run")
    judge.add_argument("record", type=Path)
    judge.add_argument("--dataset", required=True, type=Path)
    judge.add_argument("--tenant", required=True)
    judge.add_argument("--pace", type=float, default=2.0)

    report = commands.add_parser("answer-report", help="Re-render an answer run report")
    report.add_argument("record", type=Path)
    report.add_argument("--dataset", type=Path, help="Needed for --sheet")
    report.add_argument("--sheet", type=Path, help="Write a judge spot-check sheet here")
    report.add_argument("--agreement", help="Record human agreement, e.g. 18/20")
    report.add_argument("--gate", type=float, help="Report with and without this threshold")
