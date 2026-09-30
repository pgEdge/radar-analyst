# Contributing to radar-analyst

Thank you for your interest in contributing to radar-analyst.

## Getting Started

1. Fork the repository
2. Create a feature branch (`feat/your-feature` or
   `fix/your-fix`)
3. Make your changes
4. Run the full local CI (`./run-ci-local.sh`); it must exit 0
5. Submit a pull request

## Development Setup

See the [README](README.md) for prerequisites and setup
instructions.

## Pull Request Guidelines

- One logical change per PR
- Prefix your PR title the way commits are prefixed: `fix:`,
  `feat:`, `build:`, `deps:`, `refactor:`, `test:`, `docs:`, or a
  plain verb. Never `chore:`
- Include tests for new functionality
- Ensure all CI checks pass before requesting review
- Update documentation if behavior changes

## Code Style

- See `CLAUDE.md` for project-specific conventions
- `./run-ci-local.sh` runs flake8, ruff, mypy, and pyright;
  all four must be clean
- Tests come first: every new function, class, or module
  begins with a failing test

## Reporting Issues

- Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md)
  for bugs
- Use the [feature request template](.github/ISSUE_TEMPLATE/feature_request.md)
  for new features

## License

By contributing, you agree that your contributions will be
licensed under the [PostgreSQL Licence](LICENCE).
