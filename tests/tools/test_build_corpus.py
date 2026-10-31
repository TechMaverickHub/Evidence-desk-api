"""Offline tests: a fake fetch cache in tmp_path stands in for GitHub."""

import json
from pathlib import Path

import pytest
import yaml

from app.ingestion.cli import read_manifest
from tools.build_corpus import (
    BuildError,
    SourcesFile,
    SourceSpec,
    build,
    code_include_paths,
    diff_versions,
    has_body_text,
    inline_includes,
    licence_path,
    select_pages,
    title_of,
)

FASTAPI = SourceSpec(
    name="fastapi",
    source="fastapi-docs",
    repo="fastapi/fastapi",
    licence="MIT",
    versions=["0.115.0", "0.162.0"],
    root="docs/en/docs",
    include=["tutorial/*.md"],
    exclude=["tutorial/skip.md"],
    code_root="docs_src",
)
CODE = {"docs_src/deps/tutorial001.py": "def get_db():\n    yield session\n"}


def _read_code(path: str) -> str:
    return CODE[path]


# --- Pure transforms --------------------------------------------------------------------


def test_select_pages_applies_root_include_and_exclude() -> None:
    tree = [
        "docs/en/docs/tutorial/index.md",
        "docs/en/docs/tutorial/deps/index.md",  # nested: "*" matches "/"
        "docs/en/docs/tutorial/skip.md",
        "docs/en/docs/tutorial/diagram.png",
        "docs/en/docs/release-notes.md",
        "docs/es/docs/tutorial/index.md",
    ]

    assert select_pages(tree, FASTAPI) == [
        "docs/en/docs/tutorial/deps/index.md",
        "docs/en/docs/tutorial/index.md",
    ]


def test_new_block_include_becomes_a_python_fence_without_highlight_options() -> None:
    page = "Intro\n\n{* ../../docs_src/deps/tutorial001.py hl[8:9] *}\n\nAfter\n"

    result = inline_includes(page, "docs_src", _read_code)

    assert result == "Intro\n\n```python\ndef get_db():\n    yield session\n```\n\nAfter\n"


def test_old_inline_include_is_replaced_inside_the_existing_fence() -> None:
    page = '```Python hl_lines="1"\n{!> ../../../docs_src/deps/tutorial001.py!}\n```\n'

    result = inline_includes(page, "docs_src", _read_code)

    assert result == '```Python hl_lines="1"\ndef get_db():\n    yield session\n```\n'
    assert "{!" not in result and "{*" not in result


def test_line_ranges_select_inclusive_one_based_lines() -> None:
    code = {"docs_src/a.py": "one\ntwo\nthree\nfour\n"}

    old_syntax = inline_includes("{!> ../../../docs_src/a.py[ln:2-3]!}", "docs_src", code.get)
    new_syntax = inline_includes("{* ../../docs_src/a.py ln[2:3] hl[2] *}", "docs_src", code.get)

    assert old_syntax == "two\nthree"
    assert new_syntax == "```python\ntwo\nthree\n```"
    assert code_include_paths("{!> ../../../docs_src/a.py[ln:2-3]!}", "docs_src") == [
        "docs_src/a.py"
    ]


def test_python_dict_unpacking_is_not_an_include() -> None:
    page = 'return {**note.dict(), "id": 1}\nresponses={**responses, 200: {}} *}\n'

    assert inline_includes(page, "docs_src", _read_code) == page


def test_include_paths_are_listed_for_fetching() -> None:
    page = "{* ../../docs_src/a.py *}\n```\n{!../../../docs_src/sub/b.py!}\n```\n"

    assert code_include_paths(page, "docs_src") == ["docs_src/a.py", "docs_src/sub/b.py"]


@pytest.mark.parametrize(
    "include",
    ["{* ../../docs_src/../../etc/passwd *}", "{* ../../elsewhere/x.py *}"],
)
def test_includes_cannot_leave_the_code_folder(include: str) -> None:
    with pytest.raises(ValueError, match="docs_src"):
        inline_includes(include, "docs_src", _read_code)


def test_licence_file_is_found_whatever_its_name() -> None:
    assert licence_path(["docs/a.md", "LICENSE.md", "README.md"]) == "LICENSE.md"
    assert licence_path(["LICENSE", "src/LICENSE.txt"]) == "LICENSE"
    with pytest.raises(ValueError, match="licence"):
        licence_path(["README.md"])


def test_body_text_and_title_detection() -> None:
    assert has_body_text("# Title\n\nSome text.\n") is True
    assert has_body_text("# Title\n\n## Sub\n\n") is False
    assert title_of("Intro line\n\n# Dependencies #\n", "fallback") == "Dependencies"
    assert title_of("no heading here\n", "fallback") == "fallback"


# --- Build from a fake cache -------------------------------------------------------------


def _fake_cache(cache: Path) -> None:
    pages = {
        "0.115.0": {
            "docs/en/docs/tutorial/deps.md": (
                "# Dependencies\n\n```Python\n{!> ../../../docs_src/deps/tutorial001.py!}\n```\n"
            ),
            "docs/en/docs/tutorial/removed.md": "# Removed\n\nOld page.\n",
            "docs/en/docs/tutorial/empty.md": "# Empty\n\n## Nothing\n",
        },
        "0.162.0": {
            "docs/en/docs/tutorial/deps.md": (
                "# Dependencies\r\n\r\n{* ../../docs_src/deps/tutorial001.py hl[1] *}\r\n"
            ),
            "docs/en/docs/tutorial/added.md": "# Added\n\nNew page.\n",
        },
    }
    for version, files in pages.items():
        target = cache / f"fastapi@{version}"
        all_files = {**files, **CODE, "LICENSE": "MIT licence text\n"}
        for path, text in all_files.items():
            destination = target / "files" / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(text.encode())
        meta = {
            "repo": "fastapi/fastapi",
            "tag": version,
            "commit": "a" * 40,
            "licence_path": "LICENSE",
            "retrieved_at": "2026-10-31",
        }
        (target / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        (target / "tree.json").write_text(json.dumps(sorted(all_files)), encoding="utf-8")


def _sources() -> SourcesFile:
    return SourcesFile.model_validate(
        {
            "sources": [FASTAPI.model_dump()],
            "incidents": {
                "source": "synthetic-incidents",
                "folder": "incidents",
                "version": "1",
                "licence": "CC0-1.0",
            },
        }
    )


@pytest.fixture
def built(tmp_path: Path) -> Path:
    cache, out = tmp_path / "cache", tmp_path / "corpus"
    _fake_cache(cache)
    (out / "incidents").mkdir(parents=True)
    (out / "incidents" / "0001.md").write_text(
        "# INC-0001 (synthetic)\n\nText.\n", encoding="utf-8"
    )
    report = build(_sources(), cache, out)
    assert report.pages == {"fastapi@0.115.0": 2, "fastapi@0.162.0": 2, "incidents": 1}
    assert report.skipped == ["fastapi@0.115.0/tutorial/empty.md"]
    return out


def test_build_writes_pages_with_code_inlined_and_lf_endings(built: Path) -> None:
    new_page = (built / "fastapi/0.162.0/tutorial/deps.md").read_bytes()

    assert b"\r\n" not in new_page
    assert b"def get_db():" in new_page
    assert (built / "licenses/fastapi.txt").read_text(encoding="utf-8") == "MIT licence text\n"
    assert "| fastapi-docs | https://github.com/fastapi/fastapi | 0.162.0 |" in (
        built / "SOURCES.md"
    ).read_text(encoding="utf-8")


def test_manifest_is_readable_by_the_corpus_loader(built: Path) -> None:
    requests = read_manifest(built / "manifest.yaml")

    keys = [(request.slug, request.version) for request in requests]
    assert keys == [
        ("fastapi/tutorial/added", "0.162.0"),
        ("fastapi/tutorial/deps", "0.115.0"),
        ("fastapi/tutorial/deps", "0.162.0"),
        ("fastapi/tutorial/removed", "0.115.0"),
        ("incidents/0001", "1"),
    ]
    assert requests[1].title == "Dependencies"
    assert requests[1].metadata["license"] == "MIT"


def test_build_is_byte_for_byte_reproducible(tmp_path: Path, built: Path) -> None:
    before = {p.relative_to(built): p.read_bytes() for p in built.rglob("*") if p.is_file()}

    build(_sources(), tmp_path / "cache", built)

    after = {p.relative_to(built): p.read_bytes() for p in built.rglob("*") if p.is_file()}
    assert after == before


def test_missing_include_and_unfetched_source_are_build_errors(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _fake_cache(cache)
    (cache / "fastapi@0.115.0/files/docs_src/deps/tutorial001.py").unlink()
    sources = _sources()
    sources.sources[0].versions.append("0.200.0")

    with pytest.raises(BuildError) as error:
        build(sources, cache, tmp_path / "corpus")

    problems = "\n".join(error.value.problems)
    assert "fastapi@0.115.0/docs/en/docs/tutorial/deps.md" in problems
    assert "fastapi@0.200.0: not fetched" in problems
    assert not (tmp_path / "corpus" / "manifest.yaml").exists()


def test_diff_versions_reports_added_removed_and_changed(built: Path) -> None:
    diff = diff_versions(built / "manifest.yaml", "fastapi")

    assert diff == {
        "added": ["fastapi/tutorial/added"],
        "removed": ["fastapi/tutorial/removed"],
        "changed": ["fastapi/tutorial/deps"],
        "unchanged": [],
    }


def test_generated_manifest_has_a_do_not_edit_header(built: Path) -> None:
    text = (built / "manifest.yaml").read_text(encoding="utf-8")

    assert text.startswith("# Generated by tools/build_corpus.py")
    assert yaml.safe_load(text)["documents"][0]["source"] == "fastapi-docs"
