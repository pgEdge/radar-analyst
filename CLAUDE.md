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
  the worst of its category verdicts; `UNKNOWN` means uncollected,
  so it cannot make a host look worse than what was measured.
- **Everything lives in the `radar` schema**, never `public`, and
  every query fully qualifies it. Do not rely on `search_path`.
- **The state database is never the assessed server.** The analyst
  works from the uploaded archive and holds no credentials for the
  host that archive came from.

## Conventions

- **Tests come first.** Every new function, class, or module begins
  with a failing test, wiring and glue code included. Plain
  `def test_*()` functions, no test classes.
- **No auto-formatter.** Code is written to comply with the linters;
  `ruff format` is never run.
- **One migration while pre-release.** A schema change edits
  `0001_init.sql` rather than adding a file beside it, because
  nothing deployed has data to preserve. Once something is deployed,
  a change gets its own file, because a newer build has to open an
  older data directory and apply only what is missing.
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
- KISS, DRY, stdlib-first, explicit error handling at system
  boundaries.

## Vocabulary

Fixed, and the API and the store depend on it.

Input is a **radar archive**; a complete result is an
**assessment**; a deterministic issue is a **finding**; category
health is a **verdict** (`HEALTHY` / `WARNING` / `CRITICAL`, plus
`UNKNOWN` for uncollected); a per-category narrative is a **brief**;
rendered output is a **report**; the Astro GUI is **the console**.

The product is *pgEdge Radar Analyst* or *radar-analyst*, and "the
analyst" in running prose. Never *pgEdge Radar-Analyst*, never
"Radar Analyst" standalone. The collector is *radar* or *pgEdge
Radar*. Never "archive" as a verb: say *retained assessments* or
*assessment history*. No AI vocabulary in customer-facing text.

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

## Where settings live

Change the value in the file that owns it. Do not restate it here.

| Concern | Owned by |
|---|---|
| Lint rules and invocation | `src/radar_analyst/flake.sh`, `[tool.ruff]` |
| Type checking | `[tool.mypy]`, `[tool.pyright]` |
| Test discovery, coverage floor, docstring floor | `[tool.pytest.ini_options]`, `[tool.coverage]`, `[tool.interrogate]` |
| What CI runs, and in what order | `run-ci-local.sh` |
| PostgreSQL versions under test | `.github/workflows/ci.yml`, `tests/conftest.py` |
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
- Tags carry the version alone: `v0.1.0`, never "Release v0.1.0".
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
