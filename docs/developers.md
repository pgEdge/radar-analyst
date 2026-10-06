# Developer Resources

This page describes how to build, run, and test the analyst from a clone of the
[pgEdge/radar-analyst](https://github.com/pgEdge/radar-analyst) repository. The
[ARCHITECTURE.md](https://github.com/pgEdge/radar-analyst/blob/main/ARCHITECTURE.md)
document describes the design, including the module layers, the pipeline
stages, and the container layout. The
[CONTRIBUTING.md](https://github.com/pgEdge/radar-analyst/blob/main/CONTRIBUTING.md)
document describes how to propose a change.

## Building from Source

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

The overlay names the build `radar-analyst:local`, so the build never replaces
the published image. To run the guided walkthrough against an image built from
your checkout, set `WALKTHROUGH_BUILD=1`:

```bash
WALKTHROUGH_BUILD=1 make walkthrough
```

The guide then builds the analyst and replaces a running analyst of the clone's
compose project. Without the setting, the guide reuses a running analyst
whatever its image, so stop a locally built analyst first.

## Running the Analyst Outside a Container

The following command starts the service directly from the virtual environment:

```bash
.venv/bin/python -m radar_analyst
```

The service reads the settings in the
[Settings Reference](configuring.md#settings-reference). Outside a container,
the settings differ in four ways:

- the service does not read `.env`, so export each setting.
- `RADAR_ANALYST_OLLAMA_HOST` defaults to `http://localhost:11434`, the local
  Ollama server.
- `RADAR_ANALYST_DB_PASSWORD` has no effect, because only compose uses it.
- the admin token file is `admin-token` in the data directory.

The following table describes the remaining settings:

| Variable | Default | Purpose |
|---|---|---|
| `RADAR_ANALYST_STATE_DB_URL` | Required | This variable sets the connection URL of the state database. The database must meet the conditions in [Using Your Own PostgreSQL Server](configuring.md#using-your-own-postgresql-server). |
| `RADAR_ANALYST_LISTEN` | `127.0.0.1:8080` | This variable sets the listen address, as `host:port` or a bare port. The container image sets the variable to `0.0.0.0:8080`. |
| `RADAR_ANALYST_DATA_DIR` | `data` | This variable sets the directory for the uploaded archives and the admin token. The container image sets the variable to `/data`. |
| `RADAR_ANALYST_BLOB_DIR` | `<data dir>/archives` | This variable sets a separate directory for the uploaded archives, for example on separate storage. In a container, the startup ownership change covers only the data directory. |
| `RADAR_ANALYST_TEST` | Unset | A value of `1` enables the `mock` provider that the end-to-end tests use. |

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

## Running the Tests

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

# the checks CI runs, on one PostgreSQL version; they must pass
# before a commit
./run-ci-local.sh
```

CI runs `run-ci-local.sh` on each of PostgreSQL 16, 17, and 18.

The `test-radar-analyst.sh` script is the end-to-end suite, and the script
needs `curl` and `python3` on the host. The suite builds the analyst from the
checkout and runs the stack in `docker-compose.test.yml` with the mock
provider. The stack listens on port 28080, or on the port in
`RADAR_ANALYST_E2E_PORT`. The suite writes the walkthrough's sample archive
inside the analyst's container and uploads the archive. The suite then checks:

- the progress stream, the briefs, and the verdicts of the assessment.
- the sample archive's entries, which the analyst must all recognize.
- the database, which the host cannot reach and which refuses a wrong password.
- the analyst's user, which must not be root.
- the stored archive, which must stay under `/data/archives`.
- the database's log, which must go only to the container output.
- the assessment and the stored archive, which must survive replaced
  containers.
- deleting, which must refuse a request without the admin token and accept the
  generated token.

The `test_walkthrough_guide.py` test runs the walkthrough script itself against
a stub `docker` command.

The `test_real_radar_zip.py` test checks the analyst against the radar archive
that `RADAR_SAMPLE_ZIP` names. When the variable is unset, `./run-ci-local.sh`
generates a sample archive, and a plain [pytest](https://docs.pytest.org/) run
skips the test. The following command checks a real collection:

```bash
RADAR_SAMPLE_ZIP=/path/to/radar-host-YYYYMMDD-HHMMSS.zip \
    .venv/bin/pytest -v src/radar_analyst/tests/test_real_radar_zip.py
```

## Checking Archive Coverage

Radar adds collection tasks on its own schedule, and the analyst maintains its
list of recognized archive paths by hand. After you update a local clone of the
[radar repository](https://github.com/pgEdge/radar), check the clone against
the analyst's list. The following command lists the archive entries that the
analyst does not recognize yet:

```bash
make archive-coverage RADAR=<path-to-radar>
```

The target runs the `./check-archive-coverage.py` script, which you can also
run directly. Without a path, the script looks for the radar clone in
`../radar` from the current directory.

## Regenerating the API Description

The `make openapi` command regenerates `docs/api/openapi.json` from the routes.
The [API Browser](api/browser.md) page in the documentation renders that file.
The `test_openapi_spec.py` test compares the committed file with the running
application. After a route change, the tests fail until you regenerate the
description.

## Regenerating the Screenshots

The `make screenshots` command regenerates the console screenshots in
`docs/img/`. A change to what the console displays requires new screenshots.
The command starts an analyst built from the checkout and assesses three radar
collections. The command first collects and assesses two archives from
temporary PostgreSQL containers. The command then assesses the showcase, an
anonymized collection from a real server, which lives outside
[Git](https://git-scm.com/) in `data/showcase/`. Finally, the command captures
the front page and the showcase assessment in the light and dark themes. At
exit, the command removes the stack and the stack's volumes.

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
each run costs one assessment's provider calls.

## Next Steps

The following documents describe the interfaces that a change can affect:

- The [API Reference](api.md) document describes the JSON API that the console
  and any other client use.
- The [Changelog](changelog.md) document lists the user-facing changes in each
  release.
