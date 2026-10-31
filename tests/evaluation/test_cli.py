from pathlib import Path

import pytest
import yaml

from app.evaluation import cli

FIXTURES = Path(__file__).parents[1] / "fixtures"
MANIFEST = FIXTURES / "corpus" / "manifest.yaml"
MINI = FIXTURES / "datasets" / "mini.yaml"


def test_build_then_stats(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "mini-v1.jsonl"
    build_args = ["build-dataset", "--source", str(MINI), "--manifest", str(MANIFEST)]

    assert cli.main([*build_args, "--out", str(out), "--seed", "s"]) == 0
    built_report = capsys.readouterr().out
    assert cli.main(["stats", "--dataset", str(out)]) == 0
    stats_report = capsys.readouterr().out

    assert built_report == stats_report
    assert "mini-v1: 5 questions" in stats_report
    assert "unanswerable" in stats_report
    assert "span chars: n=6" in stats_report


def test_build_problems_exit_non_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "bad.yaml"
    source.write_text("questions: []\n", encoding="utf-8")

    exit_code = cli.main(
        ["build-dataset", "--source", str(source), "--manifest", str(MANIFEST), "--out", "x.jsonl"]
    )

    assert exit_code == 1
    assert "Invalid source" in capsys.readouterr().err
    assert not Path("x.jsonl").exists()


def test_review_sheet_shows_unreviewed_questions_with_exact_evidence(tmp_path: Path) -> None:
    draft = yaml.safe_load(MINI.read_text(encoding="utf-8"))
    draft["questions"][1]["reviewed"] = False  # q-0002 becomes a draft
    source = tmp_path / "draft.yaml"
    source.write_text(yaml.safe_dump(draft), encoding="utf-8")
    out = tmp_path / "sheet.md"

    exit_code = cli.main(
        ["review-sheet", "--source", str(source), "--manifest", str(MANIFEST), "--out", str(out)]
    )

    sheet = out.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "## q-0002 · exact_identifier" in sheet
    assert "## q-0001" not in sheet  # reviewed questions are left out by default
    assert "> use_cache=False" in sheet  # the exact labelled text, quote_only span
    assert "`fastapi/dependencies@0.115`" in sheet
