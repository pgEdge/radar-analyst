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
- A finding when a database approaches multixact wraparound, a
  counter that exhausts separately from transaction IDs and can be
  the one in trouble while transaction IDs look healthy.
- A finding for tables overdue for autoanalyze, so planner
  statistics stale enough to cause bad row estimates are reported as
  the maintenance problem they are.
- A finding when a replication slot is retaining a large amount of
  WAL, which catches a slot whose consumer is connected but falling
  behind. Existing slot findings only covered a missing consumer.
- Unlogged tables are noted on hosts that replicate, since they are
  truncated on crash recovery and never reach a standby.
- Archives from newer radar releases are read without reporting
  their new files as unrecognised: Spock replication state, control
  file contents, subscription statistics, the server log directory
  listing, PgBouncer configuration, and pg_statviz blocking-lock
  history.

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
