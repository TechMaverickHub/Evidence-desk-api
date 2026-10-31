"""Build, review and inspect benchmark datasets.

Usage:
    uv run python -m app.evaluation.cli build-dataset --source eval/datasets/source/v1.yaml
        --manifest corpus/manifest.yaml --out eval/datasets/evidencedesk-v1.jsonl
    uv run python -m app.evaluation.cli review-sheet --source eval/datasets/source/v1.yaml
        --manifest corpus/manifest.yaml --out .cache/review/batch-1.md
    uv run python -m app.evaluation.cli stats --dataset eval/datasets/evidencedesk-v1.jsonl
"""

import argparse
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.evaluation.cli")
    commands = parser.add_subparsers(dest="command", required=True)

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

    args = parser.parse_args(argv)
    try:
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
    print(format_stats(dataset))
    return 0


if __name__ == "__main__":
    sys.exit(main())
