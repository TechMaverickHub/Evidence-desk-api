"""Build and inspect benchmark datasets.

Usage:
    uv run python -m app.evaluation.cli build-dataset --source eval/datasets/source/v1.yaml
        --manifest corpus/manifest.yaml --out eval/datasets/evidencedesk-v1.jsonl
    uv run python -m app.evaluation.cli stats --dataset eval/datasets/evidencedesk-v1.jsonl
"""

import argparse
import statistics
import sys
from collections import Counter
from pathlib import Path

from app.evaluation.dataset import (
    DEFAULT_DEV_FRACTION,
    Dataset,
    DatasetError,
    build_dataset,
    load_dataset,
    write_dataset,
)


def format_stats(dataset: Dataset) -> str:
    """Question counts per split and type, plus labelled span lengths (to spot huge spans)."""
    header = dataset.header
    lines = [
        f"{header.name}: {header.questions} questions, seed {header.seed!r}, "
        f"dev fraction {header.dev_fraction}",
        f"sha256 {dataset.sha256}",
        "",
        f"{'query_type':<18}{'dev':>6}{'test':>6}",
    ]
    counts = Counter((question.query_type, question.split) for question in dataset.questions)
    for query_type in sorted({query_type for query_type, _ in counts}):
        lines.append(
            f"{query_type:<18}{counts[(query_type, 'dev')]:>6}{counts[(query_type, 'test')]:>6}"
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

    stats = commands.add_parser("stats", help="Show counts per split and query type")
    stats.add_argument("--dataset", required=True, type=Path, help="Built .jsonl file")

    args = parser.parse_args(argv)
    try:
        if args.command == "build-dataset":
            dataset = build_dataset(
                args.source, args.manifest, args.name or args.out.stem, args.seed, args.dev_fraction
            )
            write_dataset(dataset, args.out)
        else:
            dataset = load_dataset(args.dataset)
    except DatasetError as exc:
        print(f"Dataset problems:\n{exc}", file=sys.stderr)
        return 1
    print(format_stats(dataset))
    return 0


if __name__ == "__main__":
    sys.exit(main())
