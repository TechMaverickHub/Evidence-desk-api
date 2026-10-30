from pathlib import Path

import pytest
import yaml

from app.evaluation.dataset import (
    Dataset,
    DatasetError,
    SourceQuestion,
    assign_split,
    build_dataset,
    load_dataset,
    paragraph_span,
    write_dataset,
)

FIXTURES = Path(__file__).parents[1] / "fixtures"
MANIFEST = FIXTURES / "corpus" / "manifest.yaml"
MINI = FIXTURES / "datasets" / "mini.yaml"
DEPENDENCIES = {"slug": "fastapi/dependencies", "version": "0.115"}


def _build(source: Path = MINI) -> Dataset:
    return build_dataset(source, MANIFEST, name="mini", seed="test-seed")


def _corpus_text(slug: str, version: str) -> str:
    entries = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["documents"]
    entry = next(e for e in entries if e["slug"] == slug and e["version"] == version)
    return (MANIFEST.parent / entry["path"]).read_text(encoding="utf-8")


def _evidence(quote: str, slug: str = "fastapi/dependencies", version: str = "0.115") -> list:
    return [{"grade": 3, "spans": [{"slug": slug, "version": version, "quote": quote}]}]


def _question(**overrides: object) -> dict:
    question: dict[str, object] = {
        "id": "q-0100",
        "query_type": "factual",
        "question": "How is a dependency declared?",
        "reviewed": True,
        "evidence": _evidence("Depends(get_db)"),
    }
    question.update(overrides)
    return question


def _write_source(tmp_path: Path, questions: list[dict]) -> Path:
    path = tmp_path / "source.yaml"
    path.write_text(yaml.safe_dump({"questions": questions}), encoding="utf-8")
    return path


def test_spans_are_exact_paragraph_slices_of_the_corpus() -> None:
    (span,) = _build().questions[0].evidence[0].spans

    content = _corpus_text(**DEPENDENCIES)
    assert content[span.char_start : span.char_end] == (
        "Declare a dependency by adding a parameter with `Depends(get_db)` to a path operation."
    )


def test_quote_only_labels_just_the_quote() -> None:
    (span,) = _build().questions[1].evidence[0].spans

    content = _corpus_text(**DEPENDENCIES)
    assert content[span.char_start : span.char_end] == "use_cache=False"


def test_unanswerable_questions_have_no_evidence() -> None:
    unanswerable = _build().questions[-1]

    assert (unanswerable.answerable, unanswerable.evidence) == (False, [])


def test_paragraph_expansion_stops_at_blank_lines() -> None:
    content = "First para.\n\nSecond para line one\nline two.\n\nThird."
    quote_start = content.index("line one")

    start, end = paragraph_span(content, quote_start, quote_start + len("line one"))

    assert content[start:end] == "Second para line one\nline two."


def test_build_is_reproducible_byte_for_byte(tmp_path: Path) -> None:
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    write_dataset(_build(), first)
    write_dataset(_build(), second)

    assert first.read_bytes() == second.read_bytes()
    loaded = load_dataset(first)
    assert loaded.sha256 == _build().sha256
    assert loaded.header.questions == 5
    assert [question.id for question in loaded.questions] == [
        "q-0001",
        "q-0002",
        "q-0003",
        "q-0004",
        "q-0005",
    ]


def test_questions_about_one_page_share_a_split_in_every_version() -> None:
    def on_page(question_id: str, version: str) -> SourceQuestion:
        evidence = _evidence("x", version=version)
        return SourceQuestion.model_validate(_question(id=question_id, evidence=evidence))

    for seed in ("a", "b", "c", "d", "e"):
        old = assign_split(on_page("q-0001", "0.110"), seed, 0.6)
        new = assign_split(on_page("q-0002", "0.115"), seed, 0.6)
        assert old == new


def test_split_fraction_is_roughly_respected() -> None:
    questions = [
        SourceQuestion(id=f"q-{n:04d}", query_type="unanswerable", question="?", reviewed=True)
        for n in range(1000)
    ]

    dev = sum(assign_split(question, "seed", 0.6) == "dev" for question in questions)

    assert 550 <= dev <= 650


def test_all_problems_are_reported_together(tmp_path: Path) -> None:
    source = _write_source(
        tmp_path,
        [
            _question(id="q-0001", reviewed=False),
            _question(id="q-0001"),
            _question(id="q-0002", query_type="unanswerable"),
            _question(id="q-0003", evidence=[]),
            _question(id="q-0004", evidence=_evidence("dependency")),
            _question(id="q-0005", evidence=_evidence("not in the text")),
            _question(id="q-0006", evidence=_evidence("x", slug="missing/page", version="1")),
        ],
    )

    with pytest.raises(DatasetError) as error:
        _build(source)

    problems = "\n".join(error.value.problems)
    assert "duplicate id q-0001" in problems
    assert "q-0001: not reviewed" in problems
    assert "q-0002: unanswerable" in problems
    assert "q-0003: unanswerable" in problems
    assert "q-0004: quote found 2 times" in problems
    assert "q-0005: quote found 0 times" in problems
    assert "q-0006: no document missing/page@1" in problems


@pytest.mark.parametrize("grade", [0, 4])
def test_grade_outside_one_to_three_is_rejected(tmp_path: Path, grade: int) -> None:
    question = _question(evidence=[{**_evidence("Depends(get_db)")[0], "grade": grade}])

    with pytest.raises(DatasetError, match="grade"):
        _build(_write_source(tmp_path, [question]))


def test_built_question_converts_to_relevance_labels() -> None:
    items = _build().questions[2].evidence_items()

    assert [item.grade for item in items] == [3, 1]
    assert items[0].spans[0].slug == "incidents/0001"
