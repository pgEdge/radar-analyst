# Contributing to pgEdge Radar Analyst

Thank you for your interest in contributing to pgEdge Radar Analyst. This guide
describes how to propose a change, what a pull request needs, and how to report
an issue.

## Getting Started

To propose a change, complete the following steps:

1. Fork the [pgEdge/radar-analyst](https://github.com/pgEdge/radar-analyst)
   repository to your own GitHub account.
2. Create a feature branch, such as `feat/your-feature` or `fix/your-fix`.
3. Make your changes, starting each new function, class, or module with a
   failing test.
4. Run the full local CI with `./run-ci-local.sh`, which must exit 0.
5. Submit a pull request against the `main` branch.

## Development Setup

The [Developer Resources](docs/developers.md) page describes the prerequisites,
the build, and the tests.

## Pull Request Guidelines

Reviewers check each pull request against these guidelines. A pull request
should:

- contain one logical change.
- have a title that starts with a commit message prefix or a plain verb.
- include tests for new functionality.
- update the documentation to match any change in behavior.
- include new screenshots from `make screenshots` when what the console
  displays changes.
- pass every CI check before you request a review.

The commit message prefixes are `fix:`, `feat:`, `build:`, `deps:`,
`refactor:`, `test:`, and `docs:`. A pull request title must not start with the
`chore:` prefix.

## Code Style

The [CLAUDE.md](CLAUDE.md) file describes the project-specific conventions. The
`./run-ci-local.sh` script runs the same checks as CI. The checks cover:

- the [flake8](https://flake8.pycqa.org/) and
  [ruff](https://docs.astral.sh/ruff/) linters, and the
  [interrogate](https://interrogate.readthedocs.io/) docstring check.
- the [mypy](https://mypy.readthedocs.io/) and
  [pyright](https://github.com/microsoft/pyright) type checkers.
- the Python tests, and the console's lint and unit tests.
- the builds of the console, the Python wheel, and the container image.
- the end-to-end suite inside
  [Docker](https://docs.docker.com/get-started/get-docker/).

Every check must pass before you commit.

## Reporting Issues

To report an issue, use the template that matches the issue:

- The [bug report template](.github/ISSUE_TEMPLATE/bug_report.md) covers bugs
  in the analyst.
- The [feature request template](.github/ISSUE_TEMPLATE/feature_request.md)
  covers new features.

To report a security vulnerability, follow the
[security policy](.github/SECURITY.md) instead of opening a public issue.

## License

By contributing, you agree that your contributions will be licensed under the
[PostgreSQL License](LICENSE.md).
