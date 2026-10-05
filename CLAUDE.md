# CLAUDE.md

Decisions and conventions for this repository that are not already
encoded somewhere executable. Where a rule *is* encoded, this file
names the file that owns it instead of repeating the value: a
setting written down twice drifts, and the copy in prose is the one
that goes stale.

`CLAUDE.local.md` is gitignored and holds machine-specific notes.

## Context

pgEdge Radar Analyst reads a radar diagnostic archive, checks it
against deterministic rules, writes a brief per diagnostic category,
and serves the assessment over a JSON API with an Astro console.

Deployed with docker-compose: the analyst's container image next to
a pgEdge PostgreSQL image. The image is the distribution.

The AI SDKs (`anthropic`, `google-genai`, `openai`, `ollama`) are
required runtime dependencies, not optional extras: the briefing
step is the point of the tool. The `openai` adapter also serves any
OpenAI-compatible endpoint via `OPENAI_BASE_URL`.

## Guarantees the code must keep

[ARCHITECTURE.md](ARCHITECTURE.md) carries the design. These are the
invariants a change must not break.

- **Findings are deterministic.** Only `rules/` may construct a
  `Finding`. Never emit an LLM-originated finding: reproducibility
  is the guarantee the word carries.
- **Verdicts survive an LLM outage.** Every category verdict must be
  derivable from the worst finding severity alone, so an assessment
  always carries findings and verdicts even when every brief is
  missing. `test_degraded_mode.py` pins it.
- **`UNKNOWN` never outranks evidence.** The assessment's verdict is
  the worst of its category verdicts and its assessed databases'
  verdicts; `UNKNOWN` means uncollected, so it cannot make a host
  look worse than what was measured.
- **Everything lives in the `radar` schema**, never `public`, and
  every query fully qualifies it. Do not rely on `search_path`.
- **The state database is never the assessed server.** The analyst
  works from the uploaded archive and holds no credentials for the
  host that archive came from.

## Conventions

- **Tests come first.** Every new function, class, or module begins
  with a failing test, wiring and glue code included. Plain
  `def test_*()` functions, no test classes.
- **Integration before unit.** Smoke tests, integration tests, and
  endpoint tests come before unit tests, and every public function
  still has a unit test. Run `make test` after every change.
- **Never rig a test.** Never change its timing, ordering or inputs
  so it stops meeting the case where it fails. A failing test gets a
  product fix. An assertion is weakened only to a guarantee agreed
  beforehand, and the change says it is weaker. Before changing a
  test alongside a fix, confirm the changed test still fails on the
  unfixed code in every interleaving and input it can meet.
- **Hand-written fakes.** No mock frameworks: tests define their
  fakes locally and patch with pytest's `monkeypatch`.
- **No auto-formatter.** Code is written to comply with the linters;
  `ruff format` is never run.
- **One new migration file per release.** A git tag freezes the
  migration files it ships: the runner records each file by name and
  never applies it twice, so an edit to a shipped file never reaches
  a database that release created. Schema changes after a tag go
  into one new file, the next in sequence, which may change until
  the next tag.
- **No ORM.** Plain SQL with parameterized queries.
- **Derive, don't hardcode.** Don't hardcode lists that can be
  derived at runtime (for example, column names from `pg_catalog`).
  Every hardcoded value is a future bug.
- **One run is not a result.** Briefs and the verdicts a provider
  proposes vary from run to run, so a prompt or model change is
  judged over several runs, reporting the spread, before drawing a
  conclusion.
- **A dependency workaround is pinned and tested.** It names the
  dependency and the version it was verified against, and gets a
  test that runs the dependency without the workaround and fails
  once the defect is gone. Moving the pin starts by running those
  tests, and a workaround whose test fails is removed in the same
  change.
- **Comments describe the current code**, never its history.
- **Screenshots follow the console.** A change that alters what the
  user sees in the console, whether in `web/` or in what an
  assessment returns (a finding's wording, a category, a field on a
  page), comes with new screenshots in the same PR. `make
  screenshots` regenerates `docs/img/console-*.jpg`, which the README
  and the docs show; review the pictures before committing them. The
  showcase they open is an anonymized real radar collection in
  `data/showcase/`, outside git: every name in it is fake, and
  nothing from it but the screenshots is ever committed.
- KISS: the minimum code that does the job. DRY: no repeated logic;
  extract shared code only when there are at least two real callers.
  stdlib first, explicit error handling at system boundaries. No
  speculative abstractions, no backwards-compatibility shims for
  scenarios that can't happen, no hypothetical-future
  configurability.

## Working style

- Before making changes that span multiple files, trace the full
  end-to-end path: where the data comes from, what the code does
  with it, where it lands, and how the API and the console read it.
- Don't refactor interfaces (add parameters, rename types) until the
  concrete scenario works. Test the simple case first, abstract
  second.
- When a test fails, read the full error, find the root cause, and
  make one targeted change.
- Never use `sudo`. If an operation needs root, tell the user and
  let them handle it.

## Vocabulary

Fixed, and the API and the store depend on it.

Input is a **radar archive**; a complete result is an
**assessment**; a deterministic issue is a **finding**; category
health is a **verdict** (`HEALTHY` / `WARNING` / `CRITICAL`, plus
`UNKNOWN` for uncollected); a per-category narrative is a **brief**;
rendered output is a **report**; the Astro GUI is **the console**.

The product is *pgEdge Radar Analyst* or *radar-analyst*, and "the
analyst" in running prose. Never *pgEdge Radar-Analyst*, never
"Radar Analyst" standalone, except as `site_name` in `mkdocs.yml`,
where the pgEdge logo beside it supplies "pgEdge". The collector is
*radar* or *pgEdge Radar*. Never "archive" as a verb: say *retained
assessments* or *assessment history*. No AI vocabulary in
customer-facing text.

Rules, rule modules, facts, parsers and snapshots are internal terms
and stay out of that list. The ten rule modules are not the five
briefing categories.

## Documentation

Each file has one audience, and they stay in sync on anything they
share.

| File | Audience |
|---|---|
| `README.md` | users first: what an assessment is, deploying, configuring, using; then developers: building, testing, contributing |
| `docs/index.md` | users only: the README's user sections, identical apart from link targets |
| `ARCHITECTURE.md` | engineering design, layering, trade-offs |
| `docs/changelog.md` | user-facing changes only |

ARCHITECTURE.md changes in the same PR as the structure it
describes. Documentation is updated as functionality lands, not
afterwards. Developer content stays in the root: no
`docs/contributing.md`, no `docs/code-of-conduct.md`.

ARCHITECTURE.md is reference material, not a work log: brief,
present tense, no history and no narration of rejected alternatives.
Keep the rationale that explains the design; cut the journey.

`make docs` runs `mkdocs build --strict`, which must pass with no
warnings. It passes on a page that nothing links to, so adding,
renaming or removing a page under `docs/` updates the `mkdocs.yml`
nav and the README's Table of Contents in the same commit. Apart
from the README's mirror in `docs/index.md`, each topic has one
home; when a section moves, fix every anchor that pointed at it.

The changelog's `Fixed` is for bugs that existed in the previous
release, not for something broken and fixed in the same cycle.

Internal notes (audits, plans, problem lists) stay out of git and
are never linked from published docs.

## Where settings live

Change the value in the file that owns it. Do not restate it here.

| Concern | Owned by |
|---|---|
| Lint rules and invocation | `src/radar_analyst/flake.sh`, `[tool.ruff]` |
| Type checking | `[tool.mypy]`, `[tool.pyright]` |
| Test discovery, coverage floor, docstring floor | `[tool.pytest.ini_options]`, `[tool.coverage]`, `[tool.interrogate]` |
| What CI runs, and in what order | `run-ci-local.sh` |
| PostgreSQL versions under test | `.github/workflows/ci.yml`, `src/radar_analyst/tests/conftest.py` |
| Deployment topology and exposure | `docker-compose.yml` |
| Pre-commit hooks | `.pre-commit-config.yaml` |
| Common commands | `Makefile` |
| Archive paths the classifier must know | `check-archive-coverage.py` |
| Console screenshots: what taking them needs, their framing, width and quality | `capture-screenshots.sh` (`make screenshots`), `capture-screenshots.mjs` |

`./run-ci-local.sh` must exit 0 before a commit.

`archive/reader.py` mirrors radar's collection tasks by hand, and
radar is upstream: a path it adds is unknown here until somebody
lists it, and the only symptom is a valid archive reporting
unrecognised files. `./check-archive-coverage.py [path-to-radar]`
compares the two and is the first step of a harvest. It needs a
radar checkout, so it cannot run in CI. Run it after pulling radar,
and before adding parser or rule support for an archive entry.

## Git and review

- Commit messages are short, one line, imperative, prefixed with
  `fix:`, `feat:`, `build:`, `deps:`, `refactor:`, `test:`, `docs:`
  or a plain verb. No `chore:`, no multi-paragraph bodies.
- No `Co-Authored-By`, and no Claude or AI attribution anywhere in a
  commit.
- Add specific files by name, never `git add -A` or `git add .`, so
  a secret or a large binary is never staged by accident.
- When splitting a commit, land dependency declarations after the
  code that consumes them: every commit in history is a working
  state.
- Never push, force-push, or open a PR without explicit user
  instruction. Never skip hooks (`--no-verify` and the like) without
  explicit user instruction.
- Before `gh pr create`, show the title, the body and the exact
  commit list, and wait for approval of all three; a branch carries
  only the commits asked to go through it. Once a PR is open and
  under review, don't rebase, amend or push its branch without a
  separate go-ahead.
- PR bodies are public: state what changes for someone using the
  analyst (the version, the behaviour, the check that pins it), and
  never name internal test functions or local CI runs.
- Fixes that come out of one audit or review pass land on one branch
  and one PR, one commit per item, never a branch per fix.
- Tags are 3-part SemVer with the version alone: `v0.1.0`, never
  "Release v0.1.0". The image tags and the changelog use the same
  version.
- Changes go through PRs with at least one peer review, and CI green
  on every PostgreSQL version, before merge.
- Never commit real hostnames, database names, schema or role names,
  file paths, or IP addresses.

## Sub-agents

`.claude/agents/` holds the definitions.

| Agent | Use for |
|---|---|
| `python-expert` | implementation, tests, typing, packaging |
| `postgres-expert` | schema, queries, pool, the state database |
| `security-auditor` | exposure, secrets, untrusted input |
| `documentation-writer` | README, docs/, ARCHITECTURE, changelog |
