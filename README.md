<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/img/pgedge-labs-dark.png">
    <img alt="pgEdge Labs" src="docs/img/pgedge-labs-light.png" width="320">
  </picture>
</div>

# pgEdge Radar Analyst

[![CI](https://github.com/pgEdge/radar-analyst/actions/workflows/ci.yml/badge.svg)](https://github.com/pgEdge/radar-analyst/actions/workflows/ci.yml)

## Table of Contents

The pgEdge Radar Analyst documentation includes:

- [Understanding an Assessment](#understanding-an-assessment)
- [Installing the Analyst](#installing-the-analyst)
- [Configuring the Analyst](#configuring-the-analyst)
    - [Adding a Provider for the Briefs](#adding-a-provider-for-the-briefs)
    - [Using Your Own PostgreSQL Server](#using-your-own-postgresql-server)
    - [Settings Reference](#settings-reference)
- [Assessing a Radar Archive](#assessing-a-radar-archive)
    - [Following the Guided Walkthrough](docs/walkthrough.md)
- [Managing Your Data](#managing-your-data)
- [Using the API](#using-the-api)
    - [API Reference](docs/api.md)
    - [API Browser](docs/api/browser.md)
- [Documentation](#documentation)
- [Support & Resources](#support--resources)
- [Developing the Analyst](#developing-the-analyst)
- [Contributing](#contributing)
- [Release Notes](docs/changelog.md)

pgEdge Radar Analyst assesses the health of a
[PostgreSQL](https://www.postgresql.org/) host from a
[pgEdge Radar](https://github.com/pgEdge/radar) diagnostic archive. The analyst
checks the archive against deterministic rules and gives each diagnostic
category a verdict. For each category, the analyst also writes a brief that
explains the verdict. You can read each assessment in the analyst's web console
or retrieve the assessment from a JSON API.

The analyst works from the uploaded archive alone. The analyst never connects
to the assessed host and holds no credentials for that host.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/console-assessment-dark.jpg">
  <img alt="An assessment in the console: the host's details, and PostgreSQL Configuration open on its verdict, brief, and findings" src="docs/img/console-assessment-light.jpg">
</picture>

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
also shows the findings behind the verdict and a brief that explains those
findings. Each brief lists the archive files that the category covers. A
category for which the archive holds no data has the verdict `UNKNOWN`.

The verdict of the assessment as a whole is the worst of the category verdicts
and the database verdicts. `UNKNOWN` means only that the archive holds no data
for a category. An `UNKNOWN` category therefore never makes the overall verdict
worse than the measured evidence.

The assessment also includes a card for each database on the server. Template
databases and databases that accept no connections have no card. The card for a
database with findings lists those findings and includes a brief for that
database. The card for a database without findings reads "No issues observed
for this database." Each database card shows a verdict of its own. That verdict
counts toward the overall verdict once the analyst has assessed the databases.

Findings are the issues that the analyst's deterministic rules detect in the
archive. The same archive always produces the same findings. A provider writes
each brief and proposes a verdict along with the brief. The analyst keeps a
proposed verdict only when that verdict is at least as severe as the worst
finding. A provider can therefore raise a verdict but never lower one. Without
a provider, or when the provider fails, the findings alone decide each verdict.
In that case, the briefs read as unavailable. The
[Adding a Provider for the Briefs](#adding-a-provider-for-the-briefs) section
describes the supported providers.

## Installing the Analyst

The analyst runs as two containers: the analyst itself and a PostgreSQL
database that stores the assessments. The only requirement is
[Docker](https://docs.docker.com/get-started/get-docker/) with the
[Compose plugin](https://docs.docker.com/compose/install/).

To install the analyst, save [docker-compose.yml](docker-compose.yml) into an
empty directory and run the following command in that directory:

```bash
docker compose up -d --wait
```

The command returns once both containers are ready, and the console is then
available at [http://localhost:8080/](http://localhost:8080/). The compose file
publishes the console on `127.0.0.1:8080`, so only the local machine can reach
the console. The database publishes no port at all.

To stop the analyst, run `docker compose stop`. To start the analyst again with
every upload and assessment in place, run `docker compose start`. At startup,
the analyst marks any assessment that was still running at the previous stop as
failed. To redo such an assessment from the stored archive, open the assessment
and press Assess again.

## Configuring the Analyst

The analyst reads its configuration from environment variables. This section
describes adding a provider for the briefs and using your own PostgreSQL
server. The [Settings Reference](#settings-reference) section describes every
setting.

### Adding a Provider for the Briefs

The analyst derives the findings, and a verdict for every category, from the
archive itself. A provider writes the briefs and can raise a verdict, as
[Understanding an Assessment](#understanding-an-assessment) describes. To add a
provider, set `RADAR_ANALYST_AI_PROVIDER` and the provider's credential in a
`.env` file beside `docker-compose.yml`. Then recreate the analyst's container
to apply the settings. The default provider, `claude`, needs only a credential.
Add the following line to the `.env` file, and create the file if the file does
not exist:

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

The following command recreates the analyst's container with the new setting:

```bash
docker compose up -d --wait
```

Existing assessments keep their findings and verdicts. To add briefs to an
existing assessment, open the assessment and press Assess again.

The [examples/compose.env](examples/compose.env) file is a commented template
for the `.env` file. The `RADAR_ANALYST_AI_PROVIDER` setting selects the
provider and defaults to `claude`. The following table describes the supported
providers:

| Provider | Service | Credential | Default model |
|---|---|---|---|
| `claude` | [Anthropic](https://platform.claude.com/) | `ANTHROPIC_API_KEY` | `claude-sonnet-5` |
| `gemini` | [Google AI Studio](https://aistudio.google.com/) | `GOOGLE_API_KEY` or `GEMINI_API_KEY` | `gemini-3.7-flash` |
| `openai` | [OpenAI](https://platform.openai.com/), or an OpenAI-compatible server | `OPENAI_API_KEY` | `gpt-5.6-luna` |
| `local` | [Ollama](https://ollama.com/) | None | `gemma4:e4b` |

The `claude` and `gemini` providers always use the default model in the table.
The `OPENAI_MODEL` setting selects the model for `openai`, and
`RADAR_ANALYST_OLLAMA_MODEL` selects the model for `local`. Every provider
other than `claude` also needs `RADAR_ANALYST_AI_PROVIDER` set to the
provider's name. The following `.env` lines select Google AI Studio:

```bash
RADAR_ANALYST_AI_PROVIDER=gemini
GOOGLE_API_KEY=...
```

#### Using an OpenAI-Compatible Server

The `openai` provider works with any server that implements the OpenAI chat
completions API. Such servers include [vLLM](https://docs.vllm.ai/),
[LM Studio](https://lmstudio.ai/),
[llama.cpp](https://github.com/ggml-org/llama.cpp),
[OpenRouter](https://openrouter.ai/), and [Groq](https://groq.com/). To use
such a server, set the server's address and model name in `.env`. Set
`OPENAI_API_KEY` even when the server ignores the key, because the
[OpenAI client library](https://github.com/openai/openai-python) requires a
key. The following `.env` file selects a server at `inference.example.com`:

```bash
RADAR_ANALYST_AI_PROVIDER=openai
OPENAI_BASE_URL=http://inference.example.com:8000/v1
OPENAI_API_KEY=unused
OPENAI_MODEL=Qwen/Qwen3-32B
```

Inside the analyst's container, `localhost` in `OPENAI_BASE_URL` refers to that
container rather than the machine that runs Docker. Use an address that the
analyst's container can reach.

#### Using a Local Ollama Server

The `local` provider sends requests to an [Ollama](https://ollama.com/) server
that you run, at the address in `RADAR_ANALYST_OLLAMA_HOST`. The analyst then
writes the briefs without sending data to an outside service. The following
`.env` line selects the provider:

```bash
RADAR_ANALYST_AI_PROVIDER=local
```

The compose file sets `RADAR_ANALYST_OLLAMA_HOST` to
`http://host.docker.internal:11434`, which addresses an Ollama server on the
machine that runs Docker. The compose file maps the `host.docker.internal` name
itself. The name therefore resolves on both
[Docker Desktop](https://docs.docker.com/desktop/) and
[Docker Engine](https://docs.docker.com/engine/install/) for Linux. On Docker
Engine for Linux, the Ollama server must also listen on an address that
containers can reach. Ollama listens only on `127.0.0.1` by default, and the
`OLLAMA_HOST` environment variable of the Ollama server changes that address.
To use a different Ollama server, set `RADAR_ANALYST_OLLAMA_HOST` in `.env` to
an address that the analyst's container can reach.

The Ollama server must already have the model, because the analyst does not
download models. The following command downloads the default model on the
Ollama server:

```bash
ollama pull gemma4:e4b
```

The default model needs approximately 10 GB of GPU memory to run entirely on
the GPU. The model runs more slowly on a GPU with less memory.

### Using Your Own PostgreSQL Server

The analyst stores its assessments in PostgreSQL. The compose file includes a
database for this purpose, but the analyst can use an existing PostgreSQL
server instead. The compose file sets `RADAR_ANALYST_STATE_DB_URL` directly and
ignores any value in `.env`. To use your own server, edit the
`RADAR_ANALYST_STATE_DB_URL` entry under the `app` service in
`docker-compose.yml`. Set the entry to the connection URL of your database:

```yaml
      RADAR_ANALYST_STATE_DB_URL: >-
        postgresql://radar_analyst:PASSWORD@db.example.com/radar_analyst?sslmode=require
```

To stop running the bundled database, also remove the `db` service from the
compose file. Then remove the `depends_on` entry that waits for the `db`
service.

This database holds only the analyst's own state and is never the server under
assessment. Before you start the analyst, make sure that:

- the database uses the UTF8 encoding, which the analyst checks at startup.
- the role in the URL has the `CREATE` privilege on the database.

Under SQL_ASCII, PostgreSQL returns text as raw bytes, so the analyst refuses
to start rather than misread its own rows. With any other encoding, the analyst
logs a warning. Such an encoding may not represent all text in a radar archive
correctly. The analyst uses the privilege at startup to create the `radar`
schema for all of its tables.

### Settings Reference

Every setting in this section is optional. The following table describes the
settings that the compose file reads from the `.env` file beside
`docker-compose.yml`:

| Variable | Default | Purpose |
|---|---|---|
| `RADAR_ANALYST_AI_PROVIDER` | `claude` | This setting selects the provider that writes the briefs: `claude`, `gemini`, `openai`, or `local`. Any other value stops the analyst at startup. |
| `ANTHROPIC_API_KEY` | Unset | This variable sets the credential that the `claude` provider uses. |
| `GOOGLE_API_KEY` or `GEMINI_API_KEY` | Unset | Either variable sets the credential that the `gemini` provider uses. When both are set, `GOOGLE_API_KEY` takes precedence. |
| `OPENAI_API_KEY` | Unset | This variable sets the credential that the `openai` provider uses. The OpenAI client library requires a key, even for a server that ignores the key. |
| `OPENAI_BASE_URL` | OpenAI's own endpoint | This variable sets the address of an OpenAI-compatible server. |
| `OPENAI_MODEL` | `gpt-5.6-luna` | This variable selects the model that the `openai` provider uses. A compatible server needs the name of a model that the server provides. |
| `RADAR_ANALYST_OLLAMA_HOST` | `http://host.docker.internal:11434` | This variable sets the address of the Ollama server for `local`. |
| `RADAR_ANALYST_OLLAMA_MODEL` | `gemma4:e4b` | This variable selects the model that the `local` provider uses. |
| `RADAR_ANALYST_ADMIN_TOKEN` | Generated | This variable sets the token that authorizes deletes. When the variable is unset, the analyst generates a token into `/data/admin-token` on first start. |
| `RADAR_ANALYST_DB_PASSWORD` | `radar_analyst` | This variable sets the password of the bundled database when the `db` volume is first initialized. The bundled database publishes no port to the host. |

The analyst also reads the following settings, which the compose file does not
pass through from `.env`. To change one of these settings, add the variable to
the `environment` section of the `app` service in `docker-compose.yml`. The
following table describes these settings:

| Variable | Default | Purpose |
|---|---|---|
| `RADAR_ANALYST_MAX_UPLOAD_BYTES` | `524288000` (500 MiB) | This variable sets the largest upload that the analyst accepts, in bytes. An invalid value logs a warning, and the analyst uses the default. |
| `RADAR_ANALYST_OLLAMA_CONCURRENCY` | `3` | This variable sets how many requests `local` sends to Ollama at once, as a positive integer. The analyst ignores a value that is not an integer. |
| `RADAR_ANALYST_LOG_LEVEL` | `INFO` | This variable sets the log level, such as `DEBUG`, `INFO`, `WARNING`, or `ERROR`, in any letter case. An unknown level stops the analyst at startup. |

The compose file sets `RADAR_ANALYST_STATE_DB_URL` directly, as
[Using Your Own PostgreSQL Server](#using-your-own-postgresql-server)
describes.

## Assessing a Radar Archive

Radar collects the diagnostic archive on the PostgreSQL host, and you then
upload the archive to the analyst. The
[guided walkthrough](docs/walkthrough.md) describes how to take a radar
collection. The walkthrough covers every step from an empty directory to a
finished assessment.

From a clone of the
[pgEdge/radar-analyst](https://github.com/pgEdge/radar-analyst) repository, the
following command runs the same tour interactively:

```bash
bash examples/walkthrough/guide.sh
```

The command also opens the console in your browser.

To assess an archive in the console, perform the following steps:

1. Open [http://localhost:8080/](http://localhost:8080/) in a browser on the
   machine that runs the analyst.
2. Drag the radar archive onto the upload area, or click the upload area and
   choose the archive.
3. Press Upload to send the archive to the analyst.

The console shows the progress while the analyst reads the archive and assesses
each category. When the assessment finishes, the console opens the result. The
analyst accepts zip archives of up to 500 MiB and refuses any other file at
upload.

The front page of the console lists the 50 most recent uploads, newest first.
Each entry shows the host, the file name and size, the collection time, the
status, and the upload time. The status is the verdict, "Assessing…" while the
assessment runs, or "Failed" if the assessment fails. The collection time comes
from the name that radar gives the archive, so a renamed archive has no
collection time.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/console-front-page-dark.jpg">
  <img alt="The console's front page: the upload bar, and the list of assessments with each host, its collection time, and its verdict" src="docs/img/console-front-page-light.jpg">
</picture>

To redo an assessment from the stored archive, open the assessment, press
Assess again, and confirm. The new result replaces the previous result.
Assessing again is useful after you configure a provider, or after a stop
interrupts an assessment.

## Managing Your Data

The compose file defines three Docker volumes. The following table describes
the contents of each volume:

| Volume | Contents |
|---|---|
| `db` | This volume holds the state database, which stores every assessment. |
| `archives` | This volume holds the uploaded radar archives and the admin token. |
| `sock` | This volume holds the socket that the analyst uses to connect to the database. |

The volumes outlive the containers, so running `docker compose down` or pulling
a newer image leaves the volumes in place. However, `docker compose down -v`
deletes the volumes permanently.

Each service writes its log to the container output, which
`docker compose logs` displays. Docker keeps at most three 10 MB log files for
each service. Each service therefore uses no more than 30 MB for logs.

To keep the uploaded archives in a host directory, replace the `archives`
volume of the `app` service with that directory. Keep the `sock` volume, as the
following example shows:

```yaml
    volumes:
      - /srv/radar-analyst:/data
      - sock:/run/postgresql
```

The analyst's container runs the analyst as user ID 10001. At startup, when
that user does not own the directory, the container recursively changes the
directory's owner to that user.

### Backing Up Your Data

A backup copies the state database and the uploaded archives out of the Docker
volumes. Stop the stack before copying the volumes, because a copy of a running
server's data directory is not consistent. The following commands write the
database and the uploaded archives to `radar-analyst-backup.tar.gz` in the
current directory:

```bash
docker compose stop
docker run --rm -v radar-analyst_db:/db -v radar-analyst_archives:/archives \
    -v "$PWD:/backup" alpine \
    tar czf /backup/radar-analyst-backup.tar.gz /db /archives
docker compose start
```

Compose prefixes each volume name with the name of the directory that holds the
compose file. These commands therefore assume a directory named
`radar-analyst`. Run `docker volume ls` to list the actual volume names.

### Deleting an Assessment

Each entry in the console's list of assessments has a delete button. The button
asks for confirmation and then for the admin token. The console remembers the
token until you close the browser tab. Deleting an assessment also deletes the
uploaded archive.

The analyst generates the admin token on first start and stores the token in
the `archives` volume. The following command prints the admin token:

```bash
docker compose exec app cat /data/admin-token
```

To choose the token yourself, set `RADAR_ANALYST_ADMIN_TOKEN` in `.env` and run
`docker compose up -d --wait` again. The analyst then accepts only that token
and ignores the token in `/data/admin-token`.

## Using the API

The console reads everything that it displays from a JSON API, and any other
client can use the same endpoints. The [API reference](docs/api.md) describes
each endpoint that the API provides. The [API browser](docs/api/browser.md)
page renders the OpenAPI description of the API for browsing. A running analyst
also serves an interactive browser at
[http://localhost:8080/docs](http://localhost:8080/docs) and the description
itself at `/openapi.json`.

## Documentation

The `make docs` command builds the documentation in [docs/](docs/) with
[MkDocs](https://www.mkdocs.org/) and writes the site to `site/`. The
[docs/index.md](docs/index.md) page repeats the user sections of this README. A
change to a shared section therefore belongs in both files. The pgEdge
documentation site, [docs.pgedge.com](https://docs.pgedge.com), describes the
pgEdge products.

## Support & Resources

For more information about pgEdge products, visit
[docs.pgedge.com](https://docs.pgedge.com).

To report an issue or request a feature, visit
[GitHub Issues](https://github.com/pgEdge/radar-analyst/issues). To report a
security vulnerability, follow the [security policy](.github/SECURITY.md)
instead of opening a public issue.

The [changelog](docs/changelog.md) lists the changes in each release.

## Developing the Analyst

This section describes how to build, run, and test the analyst from source. The
[ARCHITECTURE.md](ARCHITECTURE.md) document describes the design, including the
module layers, the pipeline stages, and the container layout.

### Building from Source

Development requires [Python](https://www.python.org/downloads/) 3.11 or later,
[Node.js](https://nodejs.org/) 22.12 or later for the console, and Docker for
the tests. The following commands create a virtual environment with the
development dependencies, then build the console and the Python wheel:

```bash
make venv
make build
```

Run `make help` to list the common targets. To run the compose stack with an
image built from your checkout, add the build overlay file:

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml \
    up -d --build
```

To run the guided tour against an image built from your checkout, set
`WALKTHROUGH_BUILD=1`:

```bash
WALKTHROUGH_BUILD=1 make walkthrough
```

### Running the Analyst Outside a Container

The following command starts the service directly from the virtual environment:

```bash
.venv/bin/python -m radar_analyst
```

The service reads the settings in [Settings Reference](#settings-reference),
with four differences:

- The service does not read the `.env` file, so export each setting in the
  shell instead.
- The default of `RADAR_ANALYST_OLLAMA_HOST` is `http://localhost:11434`
  instead.
- `RADAR_ANALYST_DB_PASSWORD` has no effect, because only the compose file uses
  that variable.
- The admin token file is `admin-token` in the data directory, which defaults
  to `data/` under the working directory.

The following table describes the remaining settings:

| Variable | Default | Purpose |
|---|---|---|
| `RADAR_ANALYST_STATE_DB_URL` | Required | This variable sets the connection URL of the state database. The database must meet the conditions in [Using Your Own PostgreSQL Server](#using-your-own-postgresql-server). |
| `RADAR_ANALYST_LISTEN` | `127.0.0.1:8080` | This variable sets the listen address, as `host:port` or a bare port. The container image sets the variable to `0.0.0.0:8080`. |
| `RADAR_ANALYST_DATA_DIR` | `data` | This variable sets the directory for the uploaded archives and the admin token. The container image sets the variable to `/data`. |
| `RADAR_ANALYST_BLOB_DIR` | `<data dir>/archives` | This variable sets a separate directory for the uploaded archives, for example on separate storage. |
| `RADAR_ANALYST_TEST` | Unset | This variable enables the `mock` provider that the end-to-end tests use, when set to `1`. |

The listen address defaults to the loopback interface, and a bare port or a
`:port` value keeps the loopback host. The following examples show how the
analyst reads each form:

```bash
RADAR_ANALYST_LISTEN=9000          # 127.0.0.1:9000
RADAR_ANALYST_LISTEN=:9000         # 127.0.0.1:9000
RADAR_ANALYST_LISTEN=0.0.0.0:8080  # every interface
RADAR_ANALYST_LISTEN='[::]:8080'   # every interface, IPv6
```

The analyst logs a warning at startup for any address other than loopback. Such
an address makes the analyst reachable from other machines. A malformed value
stops the analyst at startup. Inside a container, the service must bind
`0.0.0.0`, because the host cannot reach the container's own loopback
interface. The compose file keeps the analyst local by publishing the port on
`127.0.0.1` only.

### Running the Tests

The tests run against the same pgEdge Postgres image as the deployment, in
containers that [Testcontainers](https://testcontainers.com/) starts. The tests
therefore require a running Docker daemon. The `RADAR_ANALYST_PG_MAJOR`
variable selects the PostgreSQL version and defaults to 18. The following
commands run the tests at increasing depth:

```bash
# unit and integration tests, with the coverage floor
make test

# the tests and the end-to-end suite on PostgreSQL 16, 17, and 18
make matrix

# the checks CI runs, on one PostgreSQL version; it must exit 0
# before a commit
./run-ci-local.sh
```

CI runs `run-ci-local.sh` on each of PostgreSQL 16, 17, and 18.

The `test-radar-analyst.sh` script is the end-to-end suite. The suite builds
the analyst from the checkout and runs the stack in `docker-compose.test.yml`
with the mock provider. The stack listens on port 28080, or on the port in
`RADAR_ANALYST_E2E_PORT`. The suite writes the walkthrough's sample archive
inside the analyst's container, as the walkthrough does, and uploads the
archive. The suite then checks the progress stream, the briefs, and the
verdicts. The suite also checks that the host cannot connect to the database's
port. Another check confirms that the analyst does not run as root. Next, the
suite replaces the containers and checks that the assessment and the stored
archive survived. Finally, the suite deletes the upload with the generated
admin token. The `test_walkthrough_guide.py` test runs the walkthrough script
itself against a stub `docker` command.

The `test_real_radar_zip.py` test checks the analyst against the radar archive
that `RADAR_SAMPLE_ZIP` names. When the variable is unset, `./run-ci-local.sh`
generates a sample archive, and a plain [pytest](https://docs.pytest.org/) run
skips the test. The following command checks a real collection:

```bash
RADAR_SAMPLE_ZIP=/path/to/radar-host-YYYYMMDD-HHMMSS.zip \
    .venv/bin/pytest -v src/radar_analyst/tests/test_real_radar_zip.py
```

Radar adds collection tasks on its own schedule, and the analyst maintains its
list of recognized archive paths by hand. After you update a local clone of the
[radar repository](https://github.com/pgEdge/radar), check the clone against
the analyst's list. The following command lists the archive entries that the
analyst does not recognize yet:

```bash
./check-archive-coverage.py <path-to-radar>
```

Without an argument, the script looks for the radar clone in `../radar`.

### Regenerating the API Description

The `make openapi` command regenerates
[docs/api/openapi.json](docs/api/openapi.json) from the routes. The
[API browser](docs/api/browser.md) page in the documentation renders that file.
The `test_openapi_spec.py` test compares the committed file with the running
application. After a route change, the tests fail until you regenerate the
description.

### Regenerating the Screenshots

The `make screenshots` command regenerates the console screenshots in
[docs/img/](docs/img/). A change to what the console displays requires new
screenshots. The command starts an analyst built from the checkout and assesses
three radar collections. The command first collects and assesses two archives
from temporary PostgreSQL containers. The command then assesses the showcase,
an anonymized collection from a real server, which lives outside
[Git](https://git-scm.com/) in `data/showcase/`. The command then captures the
front page and the showcase assessment in the light and dark themes. At exit,
the command removes the stack and the stack's volumes.

The repository does not include the showcase, because the showcase comes from a
real server. Any anonymized radar collection can replace the showcase. To use
such a collection, set `SHOWCASE_ARCHIVE` to the collection's path.

The command requires Docker, [curl](https://curl.se/), Node.js 22 or later,
[Chromium](https://www.chromium.org/getting-involved/download-chromium/) or
[Chrome](https://www.google.com/chrome/), and a provider configured in `.env`.
The command also needs network access to download the latest radar release, and
runs only on x86-64 or ARM64 hosts. The command refuses to start when another
service answers on port 8080. When Chromium or Chrome is not on the `PATH`, set
`CHROME` to the browser's binary. The provider writes the showcase's briefs, so
each run costs one assessment's worth of provider calls.

## Contributing

We welcome your contributions to the pgEdge Radar Analyst project. For more
information about contributing, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Author

Jimmy Angelakos created the pgEdge Radar Analyst project.

## License

This project is licensed under the [PostgreSQL License](LICENSE.md).
