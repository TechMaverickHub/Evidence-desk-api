"""Build the frozen evaluation corpus from pinned upstream documentation (task 005b).

Usage:
    uv run python -m tools.build_corpus fetch          # network: fill .cache/corpus-src/
    uv run python -m tools.build_corpus build          # offline: regenerate corpus/
    uv run python -m tools.build_corpus diff-versions  # pages that differ between versions

`fetch` is the only step that touches the network. Downloaded files are untrusted data:
they are only read as UTF-8 text and copied, never executed or imported. `build` is
deterministic, so the same cache always produces byte-identical corpus files.
"""

import argparse
import fnmatch
import hashlib
import json
import posixpath
import re
import shutil
import sys
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = REPO_ROOT / "corpus" / "sources.yaml"
DEFAULT_CACHE = REPO_ROOT / ".cache" / "corpus-src"
DEFAULT_OUT = REPO_ROOT / "corpus"

# FastAPI's two include syntaxes. New: {* ../../docs_src/a.py ln[1:9] hl[3] *}, a whole code
# block. Old: {!> ../../../docs_src/a.py[ln:1-9]!}, placed inside a fence the page already
# opened. Both can select a 1-based, inclusive line range; `hl` only highlights and is dropped.
# The path may not start with "*", so Python's {**mapping} is never mistaken for a directive.
_BLOCK_INCLUDE = re.compile(r"\{\*\s*(?P<path>[^\s*]\S*)(?P<options>[^*\n]*)\*\}")
_BLOCK_LINES = re.compile(r"ln\[(?P<start>\d+):(?P<end>\d+)\]")
_INLINE_INCLUDE = re.compile(
    r"\{!>?\s*(?P<path>[^!\s\[]+)(?:\[ln:(?P<start>\d+)-(?P<end>\d+)\])?\s*!\}"
)
_HEADING = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*#*\s*$")
_FENCE_LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".html": "html",
    ".css": "css",
    ".toml": "toml",
    ".json": "json",
    ".sh": "bash",
}
HTTP_TIMEOUT_SECONDS = 30


class SourceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source: str
    repo: str
    licence: str
    versions: list[str]
    root: str
    include: list[str]
    exclude: list[str] = []
    code_root: str | None = None


class IncidentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    folder: str
    version: str
    licence: str


class SourcesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[SourceSpec]
    incidents: IncidentSpec


class BuildError(Exception):
    """All problems found while building, reported together."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("\n".join(f"- {problem}" for problem in problems))


@dataclass
class BuildReport:
    pages: dict[str, int] = field(default_factory=dict)  # "fastapi@0.115.0" -> count
    skipped: list[str] = field(default_factory=list)  # pages with no body text
    total_bytes: int = 0


def load_sources(path: Path) -> SourcesFile:
    return SourcesFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


# --- Selection and text transforms (pure) ----------------------------------------------


def select_pages(tree_paths: Iterable[str], spec: SourceSpec) -> list[str]:
    """Repo paths of the Markdown pages to take, relative to the repo root, sorted."""
    prefix = spec.root.rstrip("/") + "/"
    selected = []
    for path in tree_paths:
        if not path.startswith(prefix) or not path.endswith(".md"):
            continue
        relative = path[len(prefix) :]
        included = any(fnmatch.fnmatch(relative, pattern) for pattern in spec.include)
        excluded = any(fnmatch.fnmatch(relative, pattern) for pattern in spec.exclude)
        if included and not excluded:
            selected.append(path)
    return sorted(selected)


def code_include_paths(markdown: str, code_root: str) -> list[str]:
    """Repo paths of every code file a page includes (both syntaxes), in page order."""
    raw = [m["path"] for m in _BLOCK_INCLUDE.finditer(markdown)]
    raw += [m["path"] for m in _INLINE_INCLUDE.finditer(markdown)]
    return [_code_repo_path(path, code_root) for path in raw]


def inline_includes(markdown: str, code_root: str, read_code: Callable[[str], str]) -> str:
    """Replace include directives with the included file's text.

    Upstream pages resolve includes relative to different base folders per version, so the
    path is anchored at `code_root` instead; anything that would leave it is rejected.
    """

    def block(match: re.Match[str]) -> str:
        repo_path = _code_repo_path(match["path"], code_root)
        language = _FENCE_LANGUAGES.get(posixpath.splitext(repo_path)[1], "")
        lines = _BLOCK_LINES.search(match["options"])
        code = _select_lines(read_code(repo_path), lines and lines["start"], lines and lines["end"])
        return f"```{language}\n{code}\n```"

    def inline(match: re.Match[str]) -> str:
        code = read_code(_code_repo_path(match["path"], code_root))
        return _select_lines(code, match["start"], match["end"])

    return _INLINE_INCLUDE.sub(inline, _BLOCK_INCLUDE.sub(block, markdown))


def _select_lines(code: str, start: str | None, end: str | None) -> str:
    """The whole file, or lines start..end (1-based, inclusive) when a range is given."""
    if start is None or end is None:
        return code.rstrip()
    return "\n".join(code.splitlines()[int(start) - 1 : int(end)]).rstrip()


def _code_repo_path(include_path: str, code_root: str) -> str:
    marker = code_root.rstrip("/") + "/"
    if marker not in include_path:
        raise ValueError(f"include outside {code_root}/: {include_path}")
    relative = posixpath.normpath(include_path.split(marker, 1)[1])
    if relative.startswith("..") or relative.startswith("/"):
        raise ValueError(f"include escapes {code_root}/: {include_path}")
    return f"{marker}{relative}"


def has_body_text(markdown: str) -> bool:
    """False for pages that are only headings and blank lines (the worker rejects those)."""
    return any(line.strip() and not _HEADING.match(line) for line in markdown.splitlines())


def title_of(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        match = _HEADING.match(line)
        if match:
            return match["title"].strip()[:300]
    return fallback


# --- Fetch (network) -------------------------------------------------------------------


def fetch(sources: SourcesFile, cache_dir: Path) -> None:
    """Download each source version's selected pages, included code files and licence."""
    for spec in sources.sources:
        for version in spec.versions:
            _fetch_version(spec, version, cache_dir / f"{spec.name}@{version}")


def licence_path(tree_paths: Iterable[str]) -> str:
    """The repository's top-level licence file (named LICENSE, LICENSE.md, … per project)."""
    candidates = sorted(p for p in tree_paths if "/" not in p and p.upper().startswith("LICEN"))
    if not candidates:
        raise ValueError("no top-level licence file in the repository")
    return candidates[0]


def _fetch_version(spec: SourceSpec, version: str, target: Path) -> None:
    api = f"https://api.github.com/repos/{spec.repo}"
    tree = _get_json(f"{api}/git/trees/{version}?recursive=1")["tree"]
    commit = _get_json(f"{api}/commits/{version}")["sha"]
    tree_paths = sorted(entry["path"] for entry in tree if entry["type"] == "blob")

    pages = select_pages(tree_paths, spec)
    licence = licence_path(tree_paths)
    for path in [*pages, licence]:
        _download(spec.repo, version, path, target)
    if spec.code_root:
        code_paths = {
            code_path
            for page in pages
            for code_path in code_include_paths(_cached_text(target, page), spec.code_root)
        }
        for path in sorted(code_paths & set(tree_paths)):
            _download(spec.repo, version, path, target)

    meta = {
        "repo": spec.repo,
        "tag": version,
        "commit": commit,
        "licence_path": licence,
        "retrieved_at": datetime.now(UTC).date().isoformat(),
    }
    (target / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (target / "tree.json").write_text(json.dumps(tree_paths), encoding="utf-8")
    print(f"fetched {spec.repo}@{version}: {len(pages)} pages")


def _get_json(url: str) -> dict:
    return json.loads(_get(url))


def _get(url: str) -> bytes:
    # GitHub's API rejects requests without a User-Agent.
    request = urllib.request.Request(url, headers={"User-Agent": "evidencedesk-corpus-builder"})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.read()
    except OSError as exc:
        raise RuntimeError(f"download failed: {url}: {exc}") from exc


def _download(repo: str, version: str, path: str, target: Path) -> None:
    destination = _cache_path(target, path)
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(_get(f"https://raw.githubusercontent.com/{repo}/{version}/{path}"))


def _cache_path(target: Path, repo_path: str) -> Path:
    destination = (target / "files" / repo_path).resolve()
    # Upstream paths are untrusted: never write outside this source's cache folder.
    if not destination.is_relative_to(target.resolve()):
        raise ValueError(f"unsafe path from upstream: {repo_path}")
    return destination


def _cached_text(target: Path, repo_path: str) -> str:
    # Decoded from bytes (no newline translation); line endings are normalised once, in build.
    return _cache_path(target, repo_path).read_bytes().decode("utf-8")


# --- Build (offline, deterministic) ------------------------------------------------------


def build(sources: SourcesFile, cache_dir: Path, out_dir: Path) -> BuildReport:
    report, problems, entries, attributions = BuildReport(), [], [], []
    rendered: dict[Path, str] = {}
    for spec in sources.sources:
        for version in spec.versions:
            target = cache_dir / f"{spec.name}@{version}"
            meta = _read_meta(target, problems)
            if meta is None:
                continue
            count = _render_version(spec, version, target, rendered, entries, report, problems)
            report.pages[f"{spec.name}@{version}"] = count
            attributions.append((spec, meta, count))
    entries += _incident_entries(sources.incidents, out_dir, report)
    if problems:
        raise BuildError(problems)
    _write_outputs(sources, out_dir, cache_dir, rendered, entries, attributions)
    report.total_bytes = sum(len(text.encode()) for text in rendered.values())
    return report


def _read_meta(target: Path, problems: list[str]) -> dict | None:
    try:
        return json.loads((target / "meta.json").read_text(encoding="utf-8"))
    except OSError:
        problems.append(f"{target.name}: not fetched (run `fetch` first)")
        return None


def _render_version(
    spec: SourceSpec,
    version: str,
    target: Path,
    rendered: dict[Path, str],
    entries: list[dict],
    report: BuildReport,
    problems: list[str],
) -> int:
    tree_paths = json.loads((target / "tree.json").read_text(encoding="utf-8"))
    count = 0
    for repo_path in select_pages(tree_paths, spec):
        relative = repo_path[len(spec.root.rstrip("/")) + 1 :]
        text = _render_page(spec, target, repo_path, problems)
        if text is None:
            continue
        if not has_body_text(text):
            report.skipped.append(f"{spec.name}@{version}/{relative}")
            continue
        corpus_path = f"{spec.name}/{version}/{relative}"
        rendered[Path(corpus_path)] = text
        entries.append(
            {
                "path": corpus_path,
                "source": spec.source,
                "slug": f"{spec.name}/{relative[: -len('.md')]}",
                "version": version,
                "title": title_of(text, posixpath.basename(relative)),
                "license": spec.licence,
            }
        )
        count += 1
    return count


def _render_page(spec: SourceSpec, target: Path, repo_path: str, problems: list[str]) -> str | None:
    try:
        text = _cached_text(target, repo_path).replace("\r\n", "\n")
        if spec.code_root:
            text = inline_includes(text, spec.code_root, lambda path: _cached_text(target, path))
    except (OSError, ValueError) as exc:
        problems.append(f"{target.name}/{repo_path}: {exc}")
        return None
    return text if text.endswith("\n") else text + "\n"


def _incident_entries(spec: IncidentSpec, out_dir: Path, report: BuildReport) -> list[dict]:
    folder = out_dir / spec.folder
    entries = []
    for path in sorted(folder.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        entries.append(
            {
                "path": f"{spec.folder}/{path.name}",
                "source": spec.source,
                "slug": f"incidents/{path.stem}",
                "version": spec.version,
                "title": title_of(text, path.stem),
                "license": spec.licence,
            }
        )
    report.pages["incidents"] = len(entries)
    return entries


def _write_outputs(
    sources: SourcesFile,
    out_dir: Path,
    cache_dir: Path,
    rendered: dict[Path, str],
    entries: list[dict],
    attributions: list[tuple[SourceSpec, dict, int]],
) -> None:
    # Only folders this build owns are replaced; sources.yaml and incidents/ are untouched.
    for spec in sources.sources:
        shutil.rmtree(out_dir / spec.name, ignore_errors=True)
    for relative, text in sorted(rendered.items()):
        destination = out_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(text.encode("utf-8"))

    licences = out_dir / "licenses"
    licences.mkdir(parents=True, exist_ok=True)
    for spec in sources.sources:
        target = cache_dir / f"{spec.name}@{spec.versions[-1]}"
        meta = json.loads((target / "meta.json").read_text(encoding="utf-8"))
        licence_file = target / "files" / meta["licence_path"]
        (licences / f"{spec.name}.txt").write_bytes(licence_file.read_bytes())

    manifest = {"documents": sorted(entries, key=lambda e: (e["slug"], e["version"]))}
    manifest_text = "# Generated by tools/build_corpus.py; do not edit by hand.\n"
    manifest_text += yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=1000)
    (out_dir / "manifest.yaml").write_bytes(manifest_text.encode("utf-8"))
    (out_dir / "SOURCES.md").write_bytes(_sources_markdown(sources, attributions).encode("utf-8"))


def _sources_markdown(
    sources: SourcesFile, attributions: list[tuple[SourceSpec, dict, int]]
) -> str:
    lines = [
        "# Corpus v1 sources",
        "",
        "Generated by `tools/build_corpus.py` from `sources.yaml`. Upstream documentation is",
        "copied unchanged except that FastAPI's code includes are inlined. Licence texts are in",
        "`licenses/`.",
        "",
        "| Source | Repository | Tag | Commit | Licence | Pages | Retrieved |",
        "|---|---|---|---|---|---|---|",
    ]
    for spec, meta, count in attributions:
        lines.append(
            f"| {spec.source} | https://github.com/{spec.repo} | {meta['tag']} "
            f"| `{meta['commit'][:12]}` | {spec.licence} | {count} | {meta['retrieved_at']} |"
        )
    incidents = sources.incidents
    lines += [
        "",
        f"`{incidents.folder}/` holds **synthetic** incident reports written for this project "
        f"({incidents.licence}). They describe fictional events.",
    ]
    return "\n".join(lines) + "\n"


# --- Version diff ----------------------------------------------------------------------


def diff_versions(manifest_path: Path, name: str) -> dict[str, list[str]]:
    """Pages added, removed and changed between the first and last version of a source."""
    entries = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))["documents"]
    by_version: dict[str, dict[str, str]] = {}
    for entry in entries:
        if not entry["slug"].startswith(f"{name}/"):
            continue
        content = (manifest_path.parent / entry["path"]).read_bytes()
        by_version.setdefault(entry["version"], {})[entry["slug"]] = hashlib.sha256(
            content
        ).hexdigest()
    versions = sorted(by_version, key=_version_key)
    if len(versions) < 2:
        raise ValueError(f"{name} has fewer than two versions in the manifest")
    old, new = by_version[versions[0]], by_version[versions[-1]]
    return {
        "added": sorted(set(new) - set(old)),
        "removed": sorted(set(old) - set(new)),
        "changed": sorted(slug for slug in set(old) & set(new) if old[slug] != new[slug]),
        "unchanged": sorted(slug for slug in set(old) & set(new) if old[slug] == new[slug]),
    }


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.build_corpus")
    parser.add_argument("command", choices=["fetch", "build", "diff-versions"])
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--source-name", default="fastapi", help="For diff-versions")
    args = parser.parse_args(argv)

    if args.command == "fetch":
        fetch(load_sources(args.sources), args.cache)
        return 0
    if args.command == "diff-versions":
        diff = diff_versions(args.out / "manifest.yaml", args.source_name)
        for kind, slugs in diff.items():
            print(f"{kind} ({len(slugs)})" + "".join(f"\n  {slug}" for slug in slugs))
        return 0
    try:
        report = build(load_sources(args.sources), args.cache, args.out)
    except BuildError as exc:
        print(f"Build problems:\n{exc}", file=sys.stderr)
        return 1
    print(json.dumps(report.__dict__, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
