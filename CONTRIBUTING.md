# Contributing to pgEdge Radar Analyst

Thank you for your interest in contributing to pgEdge Radar Analyst. This guide
describes how to propose a change, what a pull request needs, and how to report
an issue.

## Getting Started

To propose a change, complete the following steps:

1. Fork the [pgEdge/radar-analyst](https://github.com/pgEdge/radar-analyst)
   repository.
2. Create a feature branch, such as `feat/your-feature` or `fix/your-fix`.
3. Make your changes, starting each new function, class, or module with a
   failing test.
4. Run the full local CI with `./run-ci-local.sh`, which must exit 0.
5. Submit a pull request.

## Development Setup

The [Developing the Analyst](README.md#developing-the-analyst) section of the
README describes the prerequisites, the build, and the tests.

## Pull Request Guidelines

A pull request should meet the following guidelines:

- The pull request contains one logical change.
- The pull request title uses the same prefix as a commit message: `fix:`,
  `feat:`, `build:`, `deps:`, `refactor:`, `test:`, `docs:`, or a plain verb,
  but never `chore:`.
- New functionality comes with tests.
- A change in behavior comes with the matching documentation update.
- A change to what the console displays comes with new screenshots from
  `make screenshots`.
- Every CI check passes before you request a review.

## Code Style

The [CLAUDE.md](CLAUDE.md) file describes the project-specific conventions. The
`./run-ci-local.sh` script runs the same checks as CI:

- the flake8 and ruff linters, and the interrogate docstring check.
- the mypy and pyright type checkers.
- the Python tests, and the console's lint and unit tests.
- the builds of the console, the Python wheel, and the container image.
- the end-to-end suite inside Docker.

Every check must pass before you commit.

## Reporting Issues

To report an issue, use the template that matches the issue:

- The [bug report template](.github/ISSUE_TEMPLATE/bug_report.md) covers bugs.
- The [feature request template](.github/ISSUE_TEMPLATE/feature_request.md)
  covers new features.

To report a security vulnerability, follow the
[security policy](.github/SECURITY.md) instead of opening a public issue.

## License

By contributing, you agree that your contributions will be licensed under the
[PostgreSQL License](LICENSE.md).
