<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/img/pgedge-labs-dark.png">
    <img alt="pgEdge Labs" src="docs/img/pgedge-labs-light.png" width="320">
  </picture>
</div>

# pgEdge Radar Analyst

[![CI](https://github.com/pgEdge/radar-analyst/actions/workflows/ci.yml/badge.svg)](https://github.com/pgEdge/radar-analyst/actions/workflows/ci.yml)

## Table of Contents

The pgEdge Radar Analyst documentation covers these topics:

- Getting Started
    - [Introduction](docs/index.md)
    - [Guided Walkthrough](docs/walkthrough.md)
- [Installing the Analyst](docs/installing.md)
- [Configuring the Analyst](docs/configuring.md)
- [Using the Analyst](docs/using.md)
- [Managing an Installation](docs/managing.md)
- [Troubleshooting](docs/troubleshooting.md)
- For Developers
    - [API Reference](docs/api.md)
    - [API Browser](docs/api/browser.md)
    - [Developer Resources](docs/developers.md)
- [Changelog](docs/changelog.md)
- [License](docs/LICENSE.md)

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

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/console-assessment-dark.jpg">
  <img alt="An assessment in the console: the host's details, and PostgreSQL Configuration open on its verdict, brief, and findings" src="docs/img/console-assessment-light.jpg">
</picture>

## Installation

The analyst runs as two containers: the analyst itself and a PostgreSQL
database that stores the assessments. The installation requires
[Docker](https://docs.docker.com/get-started/get-docker/) with the
[Compose plugin](https://docs.docker.com/compose/install/). The following
commands download the compose file into a new directory and start the analyst:

```bash
mkdir radar-analyst && cd radar-analyst
curl -fsSLO https://raw.githubusercontent.com/pgEdge/radar-analyst/main/docker-compose.yml
docker compose up -d --wait
```

The last command returns once both containers are ready. The console is then
available at [http://localhost:8080/](http://localhost:8080/) on the local
machine. The [Installing the Analyst](docs/installing.md) page describes the
installation in detail. The [Developer Resources](docs/developers.md) page
describes building the analyst from source.

## Configuration

The analyst reads its settings from a `.env` file beside `docker-compose.yml`.
A provider writes the briefs, and the default provider needs only an Anthropic
API key. Add the following line to the `.env` file, and create the file if it
does not exist:

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

The following command recreates the analyst's container with the new setting:

```bash
docker compose up -d --wait
```

The [Configuring the Analyst](docs/configuring.md) page describes every
provider and every setting.

## Using pgEdge Radar Analyst

You assess a host by collecting a radar archive on the host and uploading the
archive to the console. To assess a host, perform the following steps:

1. Run radar on the PostgreSQL host to collect a diagnostic archive.
2. Open [http://localhost:8080/](http://localhost:8080/) in a browser on the
   machine that runs the analyst.
3. Drag the archive onto the upload area, and then select **Upload**.

The console shows the progress of the assessment and then opens the result. The
[Guided Walkthrough](docs/walkthrough.md) describes each step, and the
[Using the Analyst](docs/using.md) page describes the console in detail. The
[API Reference](docs/api.md) describes the JSON API that the console uses.

## Documentation

[MkDocs](https://www.mkdocs.org/) builds the documentation in the
[docs/](docs/) directory. The `make docs` command builds the site into `site/`
and stops on any warning. For more information about pgEdge products, visit
[docs.pgedge.com](https://docs.pgedge.com).

## Support & Resources

The [Troubleshooting](docs/troubleshooting.md) page describes common problems
and how to solve each one. For more information, visit
[docs.pgedge.com](https://docs.pgedge.com).

To report an issue with the software, visit
[GitHub Issues](https://github.com/pgEdge/radar-analyst/issues). To report a
security vulnerability, follow the [security policy](.github/SECURITY.md)
instead of opening a public issue.

## Contributing

We welcome your project contributions; for more information, see
[docs/developers.md](docs/developers.md) and
[CONTRIBUTING.md](CONTRIBUTING.md).

## Author

Jimmy Angelakos created Radar Analyst.

## License

This project is licensed under the [PostgreSQL License](LICENSE.md).
