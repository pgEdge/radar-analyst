# Changelog

All notable changes to pgEdge Radar Analyst are documented here.
Only user-facing changes are listed.

## [Unreleased]

### Added
- Deploy with `docker compose up -d`: the analyst alongside a pgEdge
  PostgreSQL service, with the console published on loopback.
- An admin token is generated on first start and kept in the data
  directory, so deleting an upload works without configuring a
  shared secret first.
- The analyst waits for its database to accept connections at
  startup instead of failing when the two start together.
- Startup refuses a state database using the SQL_ASCII encoding,
  under which PostgreSQL returns text as raw bytes.

### Changed
- Uploaded radar archives are kept under `archives/` in the data
  directory, alongside the admin token.
- The analyst reaches PostgreSQL over a unix socket shared only with
  the database container, so the database has no network port
  anything else can reach.

## [0.1.0] - 2026-08-21

### Added
- Upload a radar archive and get an assessment: five diagnostic
  categories, each with a verdict, the deterministic findings behind
  it, and a written brief.
- A brief per user database when findings or meaningful activity are
  present.
- Progress streamed to the console while the assessment runs.
- Anthropic, Google Gemini, OpenAI (and any OpenAI-compatible
  endpoint), and local Ollama as briefing providers.
- Findings and verdicts still come back when no provider is
  reachable; only the briefs are omitted.
