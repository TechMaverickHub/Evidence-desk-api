"""Build, review and inspect benchmark datasets; run and compare retrieval evaluations.

Usage:
    uv run python -m app.evaluation.cli build-dataset --source eval/datasets/source/v1.yaml
        --manifest corpus/manifest.yaml --out eval/datasets/evidencedesk-v1.jsonl
    uv run python -m app.evaluation.cli review-sheet --source eval/datasets/source/v1.yaml
        --manifest corpus/manifest.yaml --out .cache/review/batch-1.md
    uv run python -m app.evaluation.cli stats --dataset eval/datasets/evidencedesk-v1.jsonl
    uv run python -m app.evaluation.cli run --config eval/configs/dense-baseline.yaml
        --dataset eval/datasets/evidencedesk-v1.jsonl --split dev --tenant eval-corpus-v1
    uv run python -m app.evaluation.cli compare eval/reports/a-dev.json eval/reports/b-dev.json
"""

import argparse
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.evaluation.dataset import (
    DEFAULT_DEV_FRACTION,
    BuiltQuestion,
    Dataset,
    DatasetError,
    build_dataset,
    load_dataset,
    read_corpus_texts,
    write_dataset,
)
from app.evaluation.records import RunReport
from app.evaluation.report import ComparisonError, render_comparison, render_run
from app.evaluation.runner import (
    RunError,
    effective_query_instruction,
    execute_run,
    load_run_config,
    tenant_id_by_name,
)
from app.ingestion.embedding import Embedder

# Long spans are cut in the review sheet so a batch stays readable; the build keeps them whole.
REVIEW_SPAN_CHARS = 1200


def format_stats(dataset: Dataset) -> str:
    """Counts per split and type, mean question/evidence word overlap per type, span lengths."""
    header = dataset.header
    lines = [
        f"{header.name}: {header.questions} questions, seed {header.seed!r}, "
        f"dev fraction {header.dev_fraction}",
        f"sha256 {dataset.sha256}",
        "",
        f"{'query_type':<18}{'dev':>6}{'test':>6}{'overlap':>9}",
    ]
    counts = Counter((question.query_type, question.split) for question in dataset.questions)
    overlaps: dict[str, list[float]] = defaultdict(list)
    for question in dataset.questions:
        if question.word_overlap is not None:
            overlaps[question.query_type].append(question.word_overlap)
    for query_type in sorted({query_type for query_type, _ in counts}):
        values = overlaps.get(query_type)
        overlap = f"{statistics.fmean(values):.2f}" if values else "-"
        lines.append(
            f"{query_type:<18}{counts[(query_type, 'dev')]:>6}"
            f"{counts[(query_type, 'test')]:>6}{overlap:>9}"
        )
    splits = Counter(question.split for question in dataset.questions)
    lines.append(f"{'total':<18}{splits['dev']:>6}{splits['test']:>6}")

    lengths = sorted(
        span.char_end - span.char_start
        for question in dataset.questions
        for item in question.evidence
        for span in item.spans
    )
    if lengths:
        p90 = lengths[max(0, int(0.9 * len(lengths)) - 1)]
        lines += [
            "",
            f"span chars: n={len(lengths)} median={statistics.median(lengths):.0f} "
            f"p90={p90} max={lengths[-1]}",
        ]
    return "\n".join(lines)


def format_review_sheet(
    questions: list[BuiltQuestion], documents: dict[tuple[str, str], str]
) -> str:
    """Markdown for a reviewer: each question with its answer and the exact evidence text."""
    lines = [
        "# Review sheet",
        "",
        "For each id reply ✅ accept, ✏️ change (say what), or ❌ drop.",
        "Overlap = share of the question's content words that appear in the evidence.",
        "",
    ]
    for question in questions:
        lines += _review_entry(question, documents)
    return "\n".join(lines) + "\n"


def _review_entry(question: BuiltQuestion, documents: dict[tuple[str, str], str]) -> list[str]:
    overlap = "-" if question.word_overlap is None else f"{question.word_overlap:.2f}"
    lines = [
        f"## {question.id} · {question.query_type} · {question.split} · overlap {overlap}",
        "",
        f"**Q:** {question.question}",
        "",
        f"**Reference answer:** {question.reference_answer or '—'}",
        "",
    ]
    if question.notes:
        lines += [f"**Notes:** {question.notes}", ""]
    if not question.evidence:
        lines += ["*No evidence (unanswerable).*", ""]
    for number, item in enumerate(question.evidence, start=1):
        lines += [f"**Evidence {number}** (grade {item.grade})", ""]
        for span in item.spans:
            text = documents[(span.slug, span.version)][span.char_start : span.char_end]
            if len(text) > REVIEW_SPAN_CHARS:
                text = text[:REVIEW_SPAN_CHARS] + " […]"
            quoted = "\n".join(f"> {line}" for line in text.splitlines())
            lines += [
                f"`{span.slug}@{span.version}` chars {span.char_start}–{span.char_end}",
                "",
                quoted,
                "",
            ]
    return lines + ["---", ""]


def _review_sheet(args: argparse.Namespace) -> Dataset:
    # Draft mode: unreviewed questions are shown; the strict build still refuses them.
    dataset = build_dataset(args.source, args.manifest, "review", args.seed, require_reviewed=False)
    pending = [q for q in dataset.questions if args.all or not q.reviewed]
    sheet = format_review_sheet(pending, read_corpus_texts(args.manifest))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(sheet, encoding="utf-8")
    print(f"{len(pending)} question(s) written to {args.out}")
    return dataset


def build_query_embedder(query_instruction: str) -> Embedder:
    """The real model. Imported here: importing torch takes tens of seconds."""
    from app.ingestion.local_models import SentenceTransformerEmbedder

    settings = get_settings()
    return SentenceTransformerEmbedder(
        settings.embedding_model_name,
        settings.embedding_batch_size,
        query_instruction=query_instruction,
    )


def _run(args: argparse.Namespace) -> int:
    if args.split == "test" and not args.allow_test:
        # Tuning happens on dev; a test run should be a deliberate, recorded act.
        print("Refusing to run on the test split without --allow-test.", file=sys.stderr)
        return 2
    config = load_run_config(args.config)
    dataset = load_dataset(args.dataset)
    corpus_texts = read_corpus_texts(args.manifest)
    query_instruction = effective_query_instruction(config)
    embedder = build_query_embedder(query_instruction)
    with get_sessionmaker()() as session:
        report = execute_run(
            session,
            tenant_id_by_name(session, args.tenant),
            embedder,
            config,
            dataset,
            args.split,
            corpus_texts,
            query_instruction,
        )
    json_path = args.out_dir / f"{report.header.run_name}.json"
    _write(json_path, report.model_dump_json(indent=1) + "\n")
    _write(json_path.with_suffix(".md"), render_run(report))
    _print_summary(report, json_path)
    return 0


def _compare(args: argparse.Namespace) -> int:
    base = _read_run(args.base)
    candidate = _read_run(args.candidate)
    markdown = render_comparison(base, candidate)
    out = args.out_dir / f"compare-{candidate.header.run_name}-vs-{base.header.run_name}.md"
    _write(out, markdown)
    print(f"Comparison written to {out}")
    return 0


def _read_run(path: Path) -> RunReport:
    try:
        return RunReport.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise RunError(f"Cannot read run record {path}: {exc}") from exc


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Bytes, not text mode: committed reports keep LF line endings on Windows too.
    path.write_bytes(text.encode("utf-8"))


def _print_summary(report: RunReport, json_path: Path) -> None:
    for k, rows in report.results.metrics.items():
        overall = rows["all"]
        print(
            f"@{k}: n={overall.count} P={overall.precision:.3f} R={overall.recall:.3f} "
            f"MRR={overall.mrr:.3f} nDCG={overall.ndcg:.3f}"
        )
    print(f"Run written to {json_path} and {json_path.with_suffix('.md')}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.evaluation.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    _add_dataset_commands(commands)
    _add_run_commands(commands)
    return parser


def _add_dataset_commands(commands: argparse._SubParsersAction) -> None:
    build = commands.add_parser("build-dataset", help="Resolve quotes, assign splits, write JSONL")
    build.add_argument("--source", required=True, type=Path, help="YAML written by reviewers")
    build.add_argument("--manifest", required=True, type=Path, help="Corpus manifest.yaml")
    build.add_argument("--out", required=True, type=Path, help="Output .jsonl path")
    build.add_argument("--name", help="Dataset name (default: output file name)")
    build.add_argument("--seed", default="evidencedesk", help="Split seed (keep it fixed)")
    build.add_argument("--dev-fraction", type=float, default=DEFAULT_DEV_FRACTION)

    review = commands.add_parser("review-sheet", help="Render questions as a Markdown sheet")
    review.add_argument("--source", required=True, type=Path)
    review.add_argument("--manifest", required=True, type=Path)
    review.add_argument("--out", required=True, type=Path, help="Output .md path")
    review.add_argument("--seed", default="evidencedesk")
    review.add_argument("--all", action="store_true", help="Include already reviewed questions")

    stats = commands.add_parser("stats", help="Show counts per split and query type")
    stats.add_argument("--dataset", required=True, type=Path, help="Built .jsonl file")


def _add_run_commands(commands: argparse._SubParsersAction) -> None:
    run = commands.add_parser("run", help="Score a retrieval config on a dataset split")
    run.add_argument("--config", required=True, type=Path, help="eval/configs/<name>.yaml")
    run.add_argument("--dataset", required=True, type=Path, help="Built .jsonl file")
    run.add_argument("--split", required=True, choices=["dev", "test"])
    run.add_argument("--tenant", required=True, help="Tenant holding the ingested corpus")
    run.add_argument("--manifest", type=Path, default=Path("corpus/manifest.yaml"))
    run.add_argument("--out-dir", type=Path, default=Path("eval/reports"))
    run.add_argument("--allow-test", action="store_true", help="Required for --split test")

    compare = commands.add_parser("compare", help="Compare two run records (candidate - base)")
    compare.add_argument("base", type=Path, help="Base run .json")
    compare.add_argument("candidate", type=Path, help="Candidate run .json")
    compare.add_argument("--out-dir", type=Path, default=Path("eval/reports"))


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "run":
            return _run(args)
        if args.command == "compare":
            return _compare(args)
        if args.command == "build-dataset":
            dataset = build_dataset(
                args.source, args.manifest, args.name or args.out.stem, args.seed, args.dev_fraction
            )
            write_dataset(dataset, args.out)
        elif args.command == "review-sheet":
            dataset = _review_sheet(args)
        else:
            dataset = load_dataset(args.dataset)
    except DatasetError as exc:
        print(f"Dataset problems:\n{exc}", file=sys.stderr)
        return 1
    except (RunError, ComparisonError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(format_stats(dataset))
    return 0


if __name__ == "__main__":
    sys.exit(main())
