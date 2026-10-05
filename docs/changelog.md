# Changelog

This file documents all notable changes to pgEdge Radar Analyst and lists only
user-facing changes.

The format follows [Keep a Changelog](https://keepachangelog.com/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The assessment page shows why an assessment failed. `GET /api/uploads` and
  `GET /api/uploads/{id}` return the reason in an `error` field.

### Fixed

- The overall verdict and the front-page status now count each database's
  verdict. A critical finding in one database no longer leaves the overall
  verdict better than that database's verdict. Data-page checksum failures are
  one example of such a finding.
- A progress stream opened as an assessment finished no longer stays open
  forever. The stream now sends the final `done` or `error` event and closes.
- `GET /api/uploads/{id}/assessment` returns status 404 for an upload that does
  not exist, instead of an empty assessment.
- `RADAR_ANALYST_OLLAMA_CONCURRENCY` and `RADAR_ANALYST_MAX_UPLOAD_BYTES` treat
  a value that is not a positive integer as invalid. The analyst logs a warning
  and uses the default. A concurrency of `0` no longer stalls every `local`
  request, and a negative concurrency no longer fails the assessment.
- An unknown `RADAR_ANALYST_LOG_LEVEL` stops the analyst with a one-line
  message instead of a traceback.
- `/readyz` queries the database and returns status 503 when the database does
  not answer. The image's healthcheck therefore reports an analyst that lost
  its database as unhealthy.
- `GET /api/config` returns the provider that `RADAR_ANALYST_AI_PROVIDER`
  selects in `default`, rather than always `claude`.
- A brief that no provider wrote no longer names a provider and a model. Such a
  brief covers a category without data, or follows a provider failure.
- The `archive_timestamp` field no longer labels the host's local collection
  time as UTC. The field returns the time without a time zone, as the archive's
  name gives the time.
- The `parsed_kinds` field of the archive details lists only the kinds of data
  read from the archive. The field no longer lists `sys.is_container` and
  `sys.cloud_provider`, which the analyst derives.
- With `WALKTHROUGH_BUILD=1`, the walkthrough guide builds the analyst even
  while an analyst is already running. The guide no longer skips the build and
  keeps the running analyst.
- An analyst built from the checkout with `docker-compose.build.yml` is named
  `radar-analyst:local`. A later run without the build overlay therefore uses
  the published image again.
- A call to the Ollama server for the `local` provider ends after 10 minutes
  without an answer. A stalled Ollama server leaves the brief unavailable
  instead of keeping the assessment running indefinitely.
- The analyst refuses an oversized upload as soon as the upload passes the
  limit. Such an upload no longer fills a temporary file before the analyst
  answers with status 413.

### Security

- The analyst no longer writes the database password to its log at startup. The
  startup log names only the host and port of the database.

## [0.2.0] - 2026-09-29

### Added

- The analyst deploys with `docker compose up -d` alongside a pgEdge Postgres
  service. The compose file publishes the console on the loopback interface
  only.
- The analyst generates an admin token on first start and keeps the token in
  the data directory. Deleting an upload therefore works without configuring a
  shared secret first.
- The analyst waits for its database to accept connections at startup instead
  of failing when the two start together.
- The analyst refuses to start with a state database that uses the SQL_ASCII
  encoding. Under that encoding, PostgreSQL returns text as raw bytes.
- A new finding reports a database that approaches multixact ID wraparound.
  Multixact IDs run out independently of transaction IDs. A database can
  therefore approach multixact ID wraparound while the transaction ID age is
  low.
- A new finding reports tables that are overdue for autoanalyze, whose stale
  planner statistics can cause poor row estimates.
- A new finding reports a replication slot that retains a large amount of
  write-ahead log (WAL). The finding detects a slot whose consumer is connected
  but falling behind. The earlier slot findings covered only a missing
  consumer.
- The assessment notes unlogged tables on hosts that replicate. The note exists
  because PostgreSQL truncates unlogged tables during crash recovery and never
  sends those tables to a standby.
- The analyst no longer lists the files that newer radar releases add as
  unknown archive entries. These files contain Spock replication state, control
  file contents, subscription statistics, and the server log directory listing.
  The files also contain PgBouncer configuration and pg_statviz blocking-lock
  history.
- The analyst no longer lists the system files of archives taken on macOS as
  unknown archive entries. The per-table freeze ages no longer appear as
  unknown archive entries either.
- The `bash examples/walkthrough/guide.sh` command starts a guided walkthrough.
  The guide starts the analyst, opens the console, and explains how to take and
  assess a radar collection. The [walkthrough page](walkthrough.md) describes
  the same tour by hand.
- The analyst stores the findings behind each category's verdict with the
  assessment. The API returns the findings, and the console lists the findings
  under the brief. Each verdict therefore explains itself without a provider.
- An Assess again button on the assessment page, backed by
  `POST /api/uploads/{id}/assess`, redoes an assessment from the stored
  archive. The button adds the briefs after you configure a provider, or
  completes an interrupted assessment.

### Changed

- At startup, the analyst marks an assessment that was running at the previous
  stop as failed. The console no longer shows such an assessment as running
  indefinitely.
- The console's front page shows a compact upload bar above a single table of
  assessments. Each row shows the host, the time radar collected the archive,
  and the verdict. While an assessment runs, the row shows "Assessing…" in
  place of the verdict. The analyst reads the host and the collection time from
  radar's archive name at upload. The analyst then confirms the host from the
  archive's contents.
- The progress page keeps following an assessment when the connection to the
  analyst drops. The page shows that the console is reconnecting and also
  checks the job's record. A finished assessment therefore opens even if the
  progress stream never recovers.
- The console shows the progress of an upload with a progress bar and the
  percentage sent. During the upload, the button shows an Uploading state. A
  refused upload shows the analyst's reason beside the button.
- The analyst requires version 1.x of the `anthropic` Python library.
  Installing from source requires the version range `anthropic>=1,<2`. The
  container image already includes the correct version.
- The analyst keeps uploaded radar archives under `archives/` in the data
  directory, alongside the admin token.
- The analyst connects to PostgreSQL over a Unix socket that only the database
  container shares. The database therefore has no network port that anything
  else can reach.
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
  categories. Each category has a written brief and a verdict that
  deterministic findings support.
- The assessment includes a card for each user database, with a brief for each
  database that has findings.
- The analyst streams the progress of a running assessment to the console.
- Anthropic, Google Gemini, OpenAI, any OpenAI-compatible endpoint, and a local
  Ollama server can write the briefs.
- The verdicts still return when no provider is reachable, because the
  deterministic findings decide the verdicts. In that case, only the briefs are
  missing.
