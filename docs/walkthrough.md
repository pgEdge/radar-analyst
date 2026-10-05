# Guided Walkthrough

This walkthrough takes you from an empty directory to an assessment of one of
your own [PostgreSQL](https://www.postgresql.org/) hosts. You start the analyst
and take a radar collection on the host. You then upload the collection to the
console and read the result.

## Running the Interactive Guide

The repository includes an interactive guide that starts the analyst and opens
the console in your browser. The guide then explains each remaining step. The
guide requires only [Docker](https://docs.docker.com/get-started/get-docker/)
with the [Compose plugin](https://docs.docker.com/compose/install/). From a
clone of the [pgEdge/radar-analyst](https://github.com/pgEdge/radar-analyst)
repository, the following command starts the guide:

```bash
bash examples/walkthrough/guide.sh
```

By default, the guide runs the published image of the analyst. Docker pulls the
image when the image is not present locally. The following table describes the
environment variables that change how the guide runs:

| Variable | Effect |
|---|---|
| `WALKTHROUGH_BUILD=1` | This setting makes the guide build the analyst from the checkout. The build takes the published image's name locally. Later runs therefore use the build until you pull the published image again. |
| `WALKTHROUGH_NO_BROWSER=1` | This setting makes the guide print the console's address instead of opening a browser. |
| `WALKTHROUGH_NONINTERACTIVE=1` | This setting skips every prompt and takes each default answer. With this setting, `--down` removes everything without asking first. |
| `BROWSER` | This variable names the command that opens the console, in place of the platform's default. |

If an analyst is already running, the guide uses the running analyst instead of
starting another. The guide reads the `.env` file beside the clone's
`docker-compose.yml`. The guide also offers to write a sample archive,
`radar-sample.zip`, to the current directory. On Linux, the guide opens a
browser only in a graphical session and otherwise prints the console's address.

The rest of this page follows the same tour by hand, in a directory that
contains
[docker-compose.yml](https://github.com/pgEdge/radar-analyst/blob/main/docker-compose.yml)
from the repository.

## Starting the Analyst

The following command starts the analyst from the directory that contains
`docker-compose.yml`:

```bash
docker compose up -d --wait
```

The command starts two containers and returns once both containers are ready.
One container runs the analyst, and the other runs the PostgreSQL database that
stores the results. Only your own machine can reach the console, and only the
analyst can reach the database.

## Opening the Console

Open [http://localhost:8080/](http://localhost:8080/) in a browser on the
machine that runs the analyst. The console shows an upload area for radar
archives and, below the upload area, the most recent assessments. On a new
installation, the list of assessments is empty.

## Taking a Radar Collection

A radar archive is the input that the analyst assesses. Radar collects the
archive on the PostgreSQL host. The archive contains metadata about the machine
and the server, never table contents or query results.

Download the radar binary for the host's platform from
[github.com/pgEdge/radar/releases](https://github.com/pgEdge/radar/releases).
Current releases include:

- `radar-linux-amd64`
- `radar-linux-arm64`
- `radar-darwin-amd64`
- `radar-darwin-arm64`

Make the binary executable, then run the binary on the host as root. Connect to
PostgreSQL as a superuser or as a role with the privileges of `pg_monitor`. The
following commands prepare the Linux binary for x86-64 and take a collection,
connecting to the `mydb` database as `postgres`:

```bash
chmod +x radar-linux-amd64 && mv radar-linux-amd64 radar
sudo PGPASSWORD='...' ./radar -d mydb -U postgres
```

Add the `-h` and `-p` options when the server does not listen on `localhost`
port 5432. The collection writes a file named
`radar-<hostname>-<timestamp>.zip` to the current directory. Copy the file to
the machine that runs the analyst.

### Using a Sample Archive

If no PostgreSQL host is available, the analyst can write a synthetic sample
archive instead. The sample is enough to demonstrate an assessment, but only a
real collection produces a meaningful assessment. The sample's name does not
follow radar's naming. The console therefore lists the sample as "Unknown host"
with no collection time. The following commands write the sample inside the
analyst's container and copy the sample to the current directory:

```bash
docker compose exec -T app \
    python -m radar_analyst.tests.make_sample_zip /tmp/radar-sample.zip
docker compose cp app:/tmp/radar-sample.zip ./radar-sample.zip
```

## Uploading the Archive

To upload the archive, perform the following steps in the console:

1. Drag the archive onto the upload area, or click the upload area and choose
   the archive.
2. Press Upload to send the archive to the analyst.

The console moves to a progress page while the analyst reads the archive and
assesses each category. When the assessment finishes, the console opens the
result automatically. A sample takes seconds to assess, and a real collection
can take one to two minutes.

## Reading the Assessment

The assessment covers five categories: Host & OS, PostgreSQL Configuration,
Workload, Internals & I/O Health, and Replication. Each category has a verdict,
and so does each database card below the categories. The host's overall verdict
is the worst of the category verdicts and the database verdicts. A category for
which the archive holds no data reads `UNKNOWN`. An `UNKNOWN` category never
makes the host look worse than the measured evidence.

Open a category to read the brief and the findings behind the verdict. An open
category also lists the archive files that the category covers. Below the
categories, the assessment includes a card for each database on the server.
Template databases and databases that accept no connections have no card.

The analyst derives the findings from the archive alone, so the findings and a
verdict for every category always appear. A provider writes the briefs, and a
provider is optional. Without a provider, the briefs read as unavailable. The
[examples/compose.env](https://github.com/pgEdge/radar-analyst/blob/main/examples/compose.env)
file is a commented template for a `.env` file beside `docker-compose.yml`,
which holds the provider settings. The default provider, `claude`, needs only a
credential. Add the following line to the `.env` file, and create the file if
the file does not exist:

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

The following command recreates the analyst's container with the new setting:

```bash
docker compose up -d --wait
```

The
[Adding a Provider for the Briefs](index.md#adding-a-provider-for-the-briefs)
section describes the other providers, which also need
`RADAR_ANALYST_AI_PROVIDER`.

An assessment made before you add a provider keeps the findings and verdicts.
To add the briefs, open the assessment, press Assess again, and confirm. The
analyst then writes the briefs from the stored archive.

The console's front page lists the 50 most recent uploads, and you can open any
listed assessment again from there.

## Keeping and Deleting Assessments

Docker volumes hold the assessments and the archives behind the assessments.
The volumes survive `docker compose down` and survive pulling a newer image.

Each entry in the list has a delete button. The button asks for confirmation
and then for the admin token. The console remembers the token until you close
the browser tab. The analyst generates the admin token on first start. The
following command prints the admin token:

```bash
docker compose exec app cat /data/admin-token
```

To choose the token yourself, set `RADAR_ANALYST_ADMIN_TOKEN` in `.env` and run
`docker compose up -d --wait` again.

## Stopping or Removing the Analyst

The following table describes the commands that stop or remove the analyst:

| Command | Effect |
|---|---|
| `docker compose stop` | This command stops the containers without removing them. The `docker compose start` command starts the containers again. |
| `docker compose down` | This command removes the containers and keeps every assessment. |
| `docker compose down -v` | This command removes the containers and permanently deletes every assessment and archive. |

At startup, the analyst marks any assessment that was still running at the
previous stop as failed. To redo such an assessment from the stored archive,
open the assessment, press Assess again, and confirm.

From a clone of the repository, the `bash examples/walkthrough/guide.sh --down`
command asks for confirmation. The command then runs `docker compose down -v`
for the stack that the clone's `docker-compose.yml` defines. The command also
removes `radar-sample.zip` from the current directory.

## Next Steps

The following pages describe the analyst in more detail:

- The [pgEdge Radar Analyst](index.md) introduction describes how an assessment
  works and how to configure the analyst.
- The
  [Adding a Provider for the Briefs](index.md#adding-a-provider-for-the-briefs)
  section describes each provider and the provider's settings.
- The [Managing Your Data](index.md#managing-your-data) section describes the
  volumes, backups, and deleting an assessment.
- The [API Reference](api.md) document describes the JSON API that the console
  uses.
