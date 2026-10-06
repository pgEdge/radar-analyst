# pgEdge Radar Analyst

pgEdge Radar Analyst assesses the health of a
[PostgreSQL](https://www.postgresql.org/) host from a
[pgEdge Radar](https://github.com/pgEdge/radar) diagnostic archive. The analyst
checks the archive against deterministic rules and gives each diagnostic
category a verdict. For each category, the analyst also writes a brief that
explains the verdict. You can read each assessment in a web console or retrieve
it from a JSON API.

The analyst works from the uploaded archive alone, so it never connects to the
assessed host. You can therefore review a host's health without giving the
analyst any access to that host.

![An assessment in the console: the host's details, and PostgreSQL Configuration open on its verdict, brief, and findings](img/console-assessment-light.jpg#only-light)
![An assessment in the console: the host's details, and PostgreSQL Configuration open on its verdict, brief, and findings](img/console-assessment-dark.jpg#only-dark)

## Understanding an Assessment

An assessment covers five diagnostic categories, and each category answers one
question about the host:

- Host & OS asks whether the machine's size and tuning suit a database
  workload.
- PostgreSQL Configuration asks whether the server settings suit the hardware
  and the workload.
- Workload asks what the server is doing and whether any work has stalled.
- Internals & I/O Health asks whether the background processes, the write-ahead
  log pipeline, and storage I/O are healthy.
- Replication asks whether replication is safe and caught up, and whether
  write-ahead log retention is under control.

Each category has a verdict of `HEALTHY`, `WARNING`, or `CRITICAL`. A category
also shows the findings behind its verdict and a brief that explains those
findings. Each brief lists the archive files that the category covers. A
category for which the archive holds no data has the verdict `UNKNOWN`.

The assessment also includes a card for each database on the server. Template
databases and databases that accept no connections have no card. The card for a
database with findings lists those findings and includes a brief for that
database. The card for a database without findings reads "No issues observed
for this database." Each database card shows a verdict of its own.

### Deriving the Verdicts

The verdict of the assessment as a whole is the worst of the category verdicts
and the database verdicts. `UNKNOWN` means only that the archive holds no data
for a category. An `UNKNOWN` category therefore never makes the overall verdict
worse than the measured evidence.

Findings are the issues that the analyst's deterministic rules detect in the
archive. The same archive always produces the same findings. A provider writes
each brief and proposes a verdict along with it. The analyst keeps a proposed
verdict only when the verdict is at least as severe as the worst finding. A
provider can therefore raise a verdict but never lower one.

Without a provider, or when the provider fails, the findings alone decide each
verdict and the briefs read as unavailable. The
[Configuring the Analyst](configuring.md) page describes the supported
providers.

## Next Steps

The following documents describe the analyst in more detail:

- The [Guided Walkthrough](walkthrough.md) document describes a first
  assessment of one of your own hosts, step by step.
- The [Installing the Analyst](installing.md) document describes the
  requirements and the installation.
- The [Configuring the Analyst](configuring.md) document describes the
  providers that write the briefs and every setting.
- The [Using the Analyst](using.md) document describes how to upload an archive
  and work with the assessments.
