# Task 005b — Corpus v1 snapshot

**Status:** ✅ Done (2026-10-31); 136 tests passed; 285 documents, 5,005 chunks; downloads approved and done
**Week:** W2 · **Modules:** `tools/`, `corpus/` · **Branch:** `task/005b-corpus-v1`

## Goal

A frozen, licensed, reproducible document corpus checked into `corpus/`, with a
`manifest.yaml` the existing loader ingests unchanged. It must contain:
- the same docs at two versions (for version-specific questions)
- code identifiers inline (for exact-match questions)
- incident reports (for the diagnosis scenario)

A script rebuilds it byte-for-byte from pinned upstream tags.

## Decision needed: corpus sources (changes PROJECT.md)

PROJECT.md planned FastAPI + PostgreSQL + Python docs. PostgreSQL docs are DocBook XML and
Python docs are reStructuredText, so the heading-aware Markdown chunker would see them as
flat text, and converting them needs pandoc or similar. **Proposal: a Markdown-native
"FastAPI stack" corpus** (all checked via the GitHub API on 2026-10-31):

| Source | Tag(s) | Folders taken | Licence | Why |
|---|---|---|---|---|
| FastAPI docs | **0.115.0** and **0.162.0** | `docs/en/docs/{tutorial,advanced,deployment,how-to}/` + the `docs_src/` files they include | MIT | Core corpus; two versions for version-specific questions. 0.162.0 is also the version this project runs |
| Pydantic docs | v2.14.2 | `docs/concepts/`, `docs/errors/` | MIT | Validation behaviour and **error codes** (exact-identifier questions) |
| Starlette docs | 1.10.0 (`Kludex/starlette`, moved from `encode/`) | `docs/*.md` | BSD-3-Clause | Middleware, requests and lifespan beneath FastAPI |
| Uvicorn docs | 0.54.0 (`Kludex/uvicorn`) | `docs/**/*.md` | BSD-3-Clause | Workers, deployment and timeouts: what incidents are about |
| Synthetic incidents | v1 | written for this project, ~20 reports | CC0-1.0, marked "synthetic" | The diagnosis scenario; questions whose answer is in an incident, not the docs |

Excluded everywhere: release notes (one 0.7 MB page of changelog noise), translations,
images, Pydantic's `docs/api/` (auto-generated stubs such as `::: pydantic.main` with no text).

PostgreSQL / Python docs stay possible later via a converter; that would be a new task.

## Download approval requested

Nothing is downloaded until you approve this list. The script fetches **text files only**
over HTTPS into `.cache/corpus-src/<repo>@<tag>/` (git-ignored, one new directory per source).
It never executes or imports downloaded content: it reads it as text and copies the chosen
files into `corpus/`.

| # | What | From | Approx. size |
|---|---|---|---|
| 1 | 5 file-tree listings (JSON, one per repo@tag) | `api.github.com/repos/<repo>/git/trees/<tag>?recursive=1` | ~2 MB total, mostly FastAPI's tree |
| 2 | FastAPI 0.115.0: ~99 Markdown pages + only the `docs_src/*.py` files they include (of 701) | `raw.githubusercontent.com/fastapi/fastapi/0.115.0/…` | ≤ 1.1 MB |
| 3 | FastAPI 0.162.0: ~107 Markdown pages + included `docs_src/*.py` (of 485) | `raw.githubusercontent.com/fastapi/fastapi/0.162.0/…` | ≤ 0.9 MB |
| 4 | Pydantic v2.14.2: 23 Markdown pages | `raw.githubusercontent.com/pydantic/pydantic/v2.14.2/…` | ~0.45 MB |
| 5 | Starlette 1.10.0: ~24 Markdown pages | `raw.githubusercontent.com/Kludex/starlette/1.10.0/…` | ~0.21 MB |
| 6 | Uvicorn 0.54.0: ~14 Markdown pages | `raw.githubusercontent.com/Kludex/uvicorn/0.54.0/…` | ~0.12 MB |
| 7 | 4 `LICENSE` files (FastAPI, Pydantic, Starlette, Uvicorn) | same raw host, at each tag | ~5 KB |

**Total ≤ ~5 MB, at most ~800 small text files**, five unauthenticated API calls (the limit
is 60 per hour). The committed `corpus/` will be ~3 MB of Markdown.

## Scope

In:
- `corpus/sources.yaml`: pinned repos, tags, include/exclude globs, licence. This is data, not code.
- `tools/build_corpus.py` with two commands:
  - `fetch` (network → cache)
  - `build` (cache → `corpus/`, offline and deterministic)
  - plus a `diff-versions` report: FastAPI pages added, removed or changed between the two tags
- **Inlining FastAPI code includes:**
  - 0.162.0's `{* ../../docs_src/x.py hl[8:9] *}` becomes a fenced `python` block
  - 0.115.0's `{!> ../../../docs_src/x.py!}` (already inside a fence) becomes the file text
  - Include paths must resolve inside that tag's `docs_src/`, otherwise the build fails
- `corpus/<source>/<version>/…md`, `corpus/manifest.yaml`, `corpus/licenses/*`, `corpus/SOURCES.md`
  (attribution, tag, commit SHA, retrieval date)
- ~20 synthetic incident reports in `corpus/incidents/`. I draft them; you skim them as part
  of reviewing the 005b commit.
- `.gitignore`: `.cache/`.
- Manual check: load the whole corpus into a throw-away tenant on the dev DB with the real
  model and record document, chunk and failure counts plus timing; then delete it.

Out: questions and labels (005c); other source formats; any change to the loader or chunker.

## Assumptions

1. Upstream files at a tag never change, so tag + path is a stable source. The commit SHA
   of each tag is recorded too.
2. Docs are kept as written, apart from include inlining. Admonition markers (`/// note`,
   `!!! warning`) and mermaid blocks stay as text, because that is what a real ingestion of
   these docs would see.
3. 0.115.0's tabbed code variants (py39 / py310 / annotated) are kept as they are, which
   repeats similar code in that version's chunks. Faithful to the source; the duplication is a
   realistic retrieval challenge.

## Architecture decisions

| Decision | Choice | Reason / trade-off |
|---|---|---|
| Fetch method | Tree API (one call per repo@tag) + raw per-file URLs | Downloads only selected text files (≤ 5 MB) instead of full tarballs (FastAPI repo 55 MB, Pydantic 463 MB) |
| Fetch vs build split | `fetch` is the only network step; `build` is offline and deterministic | Rebuilding never needs the network, and two builds from the same cache are byte-identical (tested) |
| Code location | `tools/build_corpus.py` (+ `tools/__init__.py`), not `app/` | Operator tooling, never imported by the API or worker |
| Slugs and versions | slug `<source>/<path without .md>` (e.g. `fastapi/tutorial/dependencies/index`); version = upstream tag; incidents `incidents/0007`, version `1` | Stable, readable ids for labels; same slug across FastAPI versions, so 005a's split groups both versions together |
| Title | First `# ` heading, else the file name | Matches how the docs present themselves |
| Pages with no body text | Skipped with a warning in the build report | The worker rejects heading-only documents (task 003) |
| Untrusted content | Downloads go to their own directories, are read as UTF-8 text only, and include paths are checked to stay inside `docs_src/` | Treated as data, never code |
| No new dependencies | `urllib.request`, `pathlib`, `yaml` (already present) | Nothing else needed |

### Design principles applied

| Principle | Where it shows up |
|---|---|
| SRP | `fetch` (network), `select` (which files), `inline_includes` (text transform), `write_corpus` (files + manifest) are separate functions; source rules live in `sources.yaml` |
| OCP | Adding a source is a new entry in `sources.yaml`, not code |
| DRY | The manifest format is the loader's `ManifestEntry`; the build validates its own output by calling `read_manifest` on it |
| Flat control flow / errors | Unresolvable includes, escaping paths and missing files collect into one build error; network errors in `fetch` name the URL; no bare `except` |
| Test by risk | Include inlining (both syntaxes, `hl[...]` stripping, path escape), selection globs, deterministic output, manifest round-trip through `read_manifest` |

## Files to create / modify

```
.gitignore                         + .cache/
corpus/sources.yaml                pinned sources and globs
corpus/manifest.yaml               generated
corpus/SOURCES.md                  generated attribution (tag, commit, licence, date)
corpus/licenses/*.txt              upstream licence texts
corpus/{fastapi,pydantic,starlette,uvicorn}/<version>/**.md   generated
corpus/incidents/*.md              ~20 synthetic incident reports (hand-written, CC0)
tools/__init__.py
tools/build_corpus.py              fetch / build / diff-versions
tests/tools/test_build_corpus.py   offline tests with a fake cache in tmp_path
.claude/PROJECT.md                 corpus section updated to the FastAPI-stack corpus
.claude/{architecture,tasks,plan}.md, README.md   at handover
```

## Step-by-step implementation plan

0. `git switch -c task/005b-corpus-v1` from `task/005a-eval-foundations`.
1. `sources.yaml`, `.gitignore`; `build_corpus.py` selection and include-inlining with
   offline tests (fake cache tree in `tmp_path`).
2. `build` + `diff-versions` + determinism and manifest round-trip tests.
3. **Run `fetch`** (the approved downloads). Check the cache holds only the expected files and sizes.
4. Run `build`; review the report (pages, skipped pages, unresolved includes = must be 0,
   total size); spot-check a few inlined pages against GitHub.
5. Write ~20 synthetic incidents, each with Summary / Impact / Timeline / Root cause / Fix /
   Follow-ups, using real identifiers from the corpus (e.g. `--timeout-graceful-shutdown`,
   `value_error.missing`) so questions can link incidents and docs. Marked synthetic in the title.
6. Manual load into a throw-away tenant on the dev DB with the real model; record counts
   and time; delete.
7. Update PROJECT.md (corpus), README, docs, handover (incl. the version diff summary for
   005c); propose commit message.

## Tests (chosen by risk)

| Risk | Test |
|---|---|
| Code missing from docs (breaks exact-identifier questions) | Both include syntaxes inlined; `hl[...]` / `ln[...]` options stripped; result has no `{*` / `{!` left |
| Path traversal from upstream content | An include of `../../../../etc/x` → build error, nothing written |
| Silent gaps | A missing include file is a build error, not an empty block |
| Wrong selection | Globs include tutorial/advanced and exclude `release-notes.md`, `docs/api/`, images |
| Non-reproducible corpus | Two builds from the same cache → identical bytes and identical manifest |
| Manifest drift | Generated manifest is read by `app.ingestion.cli.read_manifest` without errors |
| Heading-only pages | Skipped and listed in the report |

## Risks

- **Upstream docs use syntax I haven't seen in the samples** (other include forms, macros).
  Mitigation: the build fails on any leftover `{*` / `{!` and lists the pages; I then extend
  the inliner or exclude the page, and record it in the handover.
- **Corpus too large for comfortable CPU embedding.** At ~3 MB the expected chunk count is
  ~3,000–4,000. Mitigation: the manual load in step 6 measures it; if ingestion takes much
  longer than ~15 minutes, drop FastAPI `how-to/` first.
- **Incident realism.** They are synthetic and labelled as such everywhere; the report says so.

## Future improvements

- A converter for reStructuredText / DocBook sources (Python, PostgreSQL docs).
- Refresh tags in a later corpus v2. A new version means new labels, so it gets its own task.

## Checklist

- [x] Branch `task/005b-corpus-v1`
- [x] `sources.yaml`, `.gitignore`
- [x] Selection + include inlining + offline tests
- [x] `build`, `diff-versions` + determinism / manifest tests
- [x] `fetch` run (approved downloads only); cache checked
- [x] `build` run: 0 unresolved includes, report reviewed, spot checks done
- [x] ~20 synthetic incidents written
- [x] Full corpus loaded on the dev DB with the real model; counts and time recorded; cleaned up
- [x] `ruff check`, `ruff format --check`, full test suite clean
- [x] Self-review against the design-principles table
- [x] Update [PROJECT.md](../PROJECT.md), [architecture.md](../architecture.md), [tasks.md](../tasks.md), README, handover below
- [x] Propose commit message, commit after confirmation

---

## Handover

### Summary
`corpus/` now holds a frozen, licensed, Markdown-only "FastAPI stack" corpus of **285
documents (~3 MB)**:

| Source | Pages |
|---|---|
| FastAPI 0.115.0 | 98 |
| FastAPI 0.162.0 | 106 |
| Pydantic v2.14.2 | 23 |
| Starlette 1.10.0 | 24 |
| Uvicorn 0.54.0 | 14 |
| Synthetic incidents | 20 |

It also has a generated `manifest.yaml`, `SOURCES.md` (tag, commit, licence, retrieval
date) and `licenses/`. `tools/build_corpus.py` rebuilds it:
- `fetch` downloads text only into `.cache/`
- `build` regenerates the corpus offline; two builds are byte-identical
- `diff-versions` reports page changes between versions

FastAPI code includes are inlined, including line ranges. The whole corpus ingests with the
real model with 0 failures. 136 tests pass (16 new).

### Architecture Notes
- **Include paths are anchored at `docs_src/`**, whatever relative base the page used
  (0.115.0 and 0.162.0 use different ones). A path that leaves the folder is a build error.
- **Line ranges are honoured:** `[ln:a-b]` in the old syntax and `ln[a:b]` in the new one.
  `hl[...]` options only highlight lines and are dropped.
- **Downloads are only ever read as text.** Upstream paths are checked to stay inside each
  source's cache folder.
- **The build checks its own output** by loading the manifest through
  `app.ingestion.cli.read_manifest`, the same path the loader takes.
- **Only folders the build owns are replaced.** `sources.yaml` and `incidents/` are never touched.

### Deviations from the plan
- **The licence file is looked up in the repository tree.** Starlette and Uvicorn name it
  `LICENSE.md`, so the first fetch got a 404. Each source's `meta.json` now records which
  file it is.
- **Line-range includes** (7 in 0.115.0) were not in the plan; added with a test.
- **`how-to/configure-swagger-ui.md` is excluded from both FastAPI versions.** In 0.115.0 it
  includes FastAPI's own package source (`fastapi/openapi/docs.py`), which was outside the
  approved downloads.
- **The include pattern was tightened** so Python's `{**mapping}` is never read as a directive
  (regression test added). The earlier looser pattern had not altered any page.
- **10 GitHub API calls instead of 5:** one extra per source version, to record its tag's
  commit SHA.
- **`.gitignore` already covered `.cache`,** so no change was needed.
- **`corpus/` and `tests/fixtures/corpus/` are excluded from ruff** (`extend-exclude` in
  `pyproject.toml`). This ruff version also formats Python code blocks inside Markdown, and
  `ruff format --check` flagged 86 corpus pages: running `ruff format .` would have rewritten
  upstream code and shifted every labelled offset. The corpus was rebuilt afterwards to make
  sure no file had been touched.
- **`.js`, `.css` and `.html` example files** included by FastAPI pages get matching fence languages.
- The first fetch took 7 min 45 s (about 1,140 sequential small downloads); re-runs skip
  cached files (15 s).

### Database Changes
None.

### API Changes
None.

### Evaluation Results
No benchmark yet (005c). Corpus measurements:

| Measurement | Result |
|---|---|
| Download | 1,143 text files, 2.5 MB, all from the approved hosts |
| Built corpus | 285 documents, 3.1 MB of page text; 0 unresolved includes; 0 pages skipped |
| Full ingest (real model, CPU, dev machine) | model + tokenizer load 70.8 s; queue processed in 651 s (~11 min); 285/285 ingested; 0 failed jobs |
| Chunks (`tokens-300-overlap-50`) | 5,005 total: FastAPI 3,738, Pydantic 685, Starlette 269, Uvicorn 173, incidents 140 |
| Chunks per document | min 1, median 11, max 349 |
| FastAPI 0.115.0 → 0.162.0 | 12 pages added, 4 removed, 94 changed, 0 identical |

**Findings for 005c and 010:**
- **One page dominates the chunk count.** The 349-chunk document is FastAPI 0.115.0's
  `advanced/security/oauth2-scopes.md` (274 KB). Its tabbed code variants each inline the full
  example file, which is faithful to the source (assumption 3) but means heavy near-duplication.
  Expect lower precision on OAuth questions about 0.115.0; worth a look in Experiment D.
- **5,005 chunks is above the 3,000–4,000 estimate.** Exact search at this size is inside the
  20k-chunk latency measurement from task 004.
- **No page is identical across the two FastAPI versions**, so a version-independent question
  needs a span for each version (005a's alternative spans), or a quote that exists in both.

### Future Work
- 005c: draft and review ~150 questions against this corpus, using the version diff for
  version-specific questions.
- Consider de-duplicating tabbed code variants as an Experiment D option (task 010), keeping
  the faithful corpus as the baseline.
- A converter for reStructuredText / DocBook sources, if PostgreSQL or Python docs are wanted later.

### Modified Files
| File | Why |
|---|---|
| `corpus/sources.yaml` | Pinned sources, globs, exclusion |
| `corpus/{fastapi,pydantic,starlette,uvicorn}/**`, `corpus/manifest.yaml`, `corpus/SOURCES.md`, `corpus/licenses/*` | Generated corpus |
| `corpus/incidents/0001–0020.md` | Synthetic incidents |
| `tools/__init__.py`, `tools/build_corpus.py` | Build script |
| `tests/tools/*` | Offline tests |
| `README.md`, `.claude/{PROJECT,architecture,tasks,plan}.md`, this file | Docs |
