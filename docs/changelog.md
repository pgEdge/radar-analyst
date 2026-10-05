# Changelog

This file documents all notable changes to pgEdge Radar Analyst and lists only
user-facing changes.

The format follows [Keep a Changelog](https://keepachangelog.com/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- The overall verdict and the front-page status now count each database's
  verdict. A critical finding in one database, such as data-page checksum
  failures, no longer leaves the overall verdict better than that database's
  verdict.

## [0.2.0] - 2026-09-29

### Added

- The analyst deploys with `docker compose up -d` alongside a pgEdge PostgreSQL
  service and publishes the console on the loopback interface only.
- The analyst generates an admin token on first start and keeps the token in
  the data directory, so deleting an upload works without configuring a shared
  secret first.
- The analyst waits for its database to accept connections at startup instead
  of failing when the two start together.
- The analyst refuses to start with a state database that uses the SQL_ASCII
  encoding, under which PostgreSQL returns text as raw bytes.
- A new finding reports a database that approaches multixact ID wraparound.
  Multixact IDs run out independently of transaction IDs, so a database can
  approach multixact ID wraparound while the transaction ID age is low.
- A new finding reports tables that are overdue for autoanalyze, whose stale
  planner statistics can cause poor row estimates.
- A new finding reports a replication slot that retains a large amount of
  write-ahead log (WAL). The finding detects a slot whose consumer is connected
  but falling behind; the earlier slot findings covered only a missing
  consumer.
- The assessment notes unlogged tables on hosts that replicate, because
  PostgreSQL truncates unlogged tables during crash recovery and never sends
  them to a standby.
- The analyst no longer lists the files that newer radar releases add as
  unknown archive entries: Spock replication state, control file contents,
  subscription statistics, the server log directory listing, PgBouncer
  configuration, and pg_statviz blocking-lock history.
- The analyst no longer lists the system files of archives taken on macOS, or
  the per-table freeze ages, as unknown archive entries.
- A guided walkthrough is available. The `bash examples/walkthrough/guide.sh`
  command starts the analyst, opens the console in the browser, and explains
  how to take and assess a radar collection. The
  [walkthrough page](walkthrough.md) describes the same tour by hand.
- The analyst stores the findings behind each category's verdict with the
  assessment. The API returns the findings and the console lists the findings
  under the brief, so each verdict explains itself without a provider.
- An Assess again button on the assessment page, backed by
  `POST /api/uploads/{id}/assess`, redoes an assessment from the stored
  archive. The button adds the briefs after you configure a provider, or
  completes an interrupted assessment.

### Changed

- At startup, the analyst marks an assessment that was running at the previous
  stop as failed, instead of showing the assessment as running indefinitely.
- The console's front page shows a compact upload bar above a single table of
  assessments. Each row shows the host, the time radar collected the archive,
  and the verdict, or that the assessment is still running. The analyst reads
  the host and the collection time from radar's archive name at upload, then
  confirms the host from the archive's contents.
- The progress page keeps following an assessment when the connection to the
  analyst drops. The page shows that the console is reconnecting and also
  checks the job's record. A finished assessment therefore opens even if the
  progress stream never recovers.
- The console shows the progress of an upload with a progress bar, the
  percentage sent, and an Uploading state on the button. A refused upload shows
  the analyst's reason beside the button.
- The analyst requires version 1.x of the `anthropic` Python library.
  Installing from source requires `anthropic>=1,<2`; the container image
  already includes the correct version.
- The analyst keeps uploaded radar archives under `archives/` in the data
  directory, alongside the admin token.
- The analyst connects to PostgreSQL over a Unix socket that only the database
  container shares, so the database has no network port that anything else can
  reach.
- The database list omits databases that accept no connections, as the list
  already omitted template databases. Nothing can run in such a database, and
  radar cannot connect to collect the database's contents.

### Fixed

- The default Ollama address works on Docker Engine for Linux. The compose file
  now maps `host.docker.internal`, which only Docker Desktop defined, to the
  machine that runs Docker.

## [0.1.0] - 2026-08-21

### Added

- Uploading a radar archive produces an assessment of five diagnostic
  categories, each with a verdict that deterministic findings support and a
  written brief.
- The assessment includes a card for each user database, with a brief for each
  database that has findings.
- The analyst streams the progress of a running assessment to the console.
- Anthropic, Google Gemini, OpenAI, any OpenAI-compatible endpoint, and a local
  Ollama server can write the briefs.
- The verdicts still return when no provider is reachable, because the
  deterministic findings decide the verdicts; only the briefs are missing.
