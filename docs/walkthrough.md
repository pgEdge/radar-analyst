# Guided Walkthrough

This walkthrough takes you from an empty directory to an assessment of one of
your own [PostgreSQL](https://www.postgresql.org/) hosts. You start the analyst
and take a radar collection on the host. You then upload the collection to the
console and read the result. The
[Running the Interactive Guide](#running-the-interactive-guide) section
describes a script that performs the same steps.

## Starting the Analyst

The analyst needs only
[Docker](https://docs.docker.com/get-started/get-docker/) with the
[Compose plugin](https://docs.docker.com/compose/install/). The following
commands download the compose file into a new directory and start the analyst:

```bash
mkdir radar-analyst && cd radar-analyst
curl -fsSLO https://raw.githubusercontent.com/pgEdge/radar-analyst/main/docker-compose.yml
docker compose up -d --wait
```

The last command starts two containers and returns once both containers are
ready. One container runs the analyst, and the other runs the PostgreSQL
database that stores the results. Only your own machine can reach the console,
and only the analyst can reach the database.

## Opening the Console

Open [http://localhost:8080/](http://localhost:8080/) in a browser on the
machine that runs the analyst. The console shows an upload area for radar
archives and, below the upload area, the most recent assessments. On a new
installation, the list of assessments is empty.

## Taking a Radar Collection

A radar archive is the input that the analyst assesses. Radar collects the
archive on the PostgreSQL host. The archive contains metadata about the machine
and the server, never table contents or query results.

Download the radar binary for the host's platform from the
[radar releases page](https://github.com/pgEdge/radar/releases). Save the
binary as `radar` on the host, and run it as root. Connect to PostgreSQL as a
superuser or as a role with the privileges of `pg_monitor`. The following
commands make the binary executable and take a collection from the `mydb`
database as `postgres`:

```bash
chmod +x radar
sudo PGPASSWORD='...' ./radar -d mydb -U postgres
```

Add the `-h` and `-p` options when the server does not listen on `localhost`
port 5432. The collection writes a file named
`radar-<hostname>-<timestamp>.zip` to the current directory. Copy the file to
the machine that runs the analyst.

### Using a Sample Archive

If no PostgreSQL host is available, the analyst can write a synthetic sample
archive instead. The sample demonstrates an assessment, but only a real
collection produces a meaningful assessment. The sample records no host name,
and the sample's file name does not follow radar's naming. The console
therefore lists the sample as "Unknown host" with no collection time. The
following commands write the sample inside the analyst's container and copy it
to the current directory:

```bash
docker compose exec -T app python -m radar_analyst.sample /tmp/radar-sample.zip
docker compose cp app:/tmp/radar-sample.zip ./radar-sample.zip
```

## Uploading the Archive

The console assesses an archive as soon as the upload finishes. To upload the
archive, perform the following steps in the console:

1. Drag the archive onto the upload area, or click the upload area and choose
   the archive.
2. Select **Upload** to send the archive to the analyst.

The console moves to a progress page while the analyst reads the archive and
assesses each category. When the assessment finishes, the console opens the
result. A sample takes seconds to assess, and a real collection can take one to
two minutes.

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
default provider, `claude`, needs only a credential in a `.env` file beside
`docker-compose.yml`. Add the following line to the `.env` file, and create the
file if it does not exist:

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

The following command recreates the analyst's container with the new setting:

```bash
docker compose up -d --wait
```

The [Configuring the Analyst](configuring.md#adding-a-provider-for-the-briefs)
page describes the other providers, which also need
`RADAR_ANALYST_AI_PROVIDER`. An assessment made before you add a provider keeps
its findings and verdicts. To add the briefs, open the assessment, select
**Assess again**, and confirm.

## Keeping and Deleting Assessments

Docker volumes hold the assessments and the uploaded archives, and the volumes
survive `docker compose down`. The console's front page lists the 50 most
recent uploads, and you can open any listed assessment again from there.

Each entry in the list has a delete button, which asks for confirmation and
then for the admin token. The analyst generates the admin token on first start.
The following command prints the admin token:

```bash
docker compose exec app cat /data/admin-token
```

## Stopping or Removing the Analyst

Docker Compose stops and removes both containers together. The following table
describes the commands that stop or remove the analyst:

| Command | Effect |
|---|---|
| `docker compose stop` | This command stops the containers without removing them. The `docker compose start` command starts the containers again. |
| `docker compose down` | This command removes the containers and keeps every assessment. |
| `docker compose down -v` | This command removes the containers and permanently deletes every assessment and archive. |

## Running the Interactive Guide

The repository includes a script that performs the steps on this page and opens
the console in your browser. The script also needs only Docker with the Compose
plugin. From a clone of the
[pgEdge/radar-analyst](https://github.com/pgEdge/radar-analyst) repository, the
following command starts the guide:

```bash
bash examples/walkthrough/guide.sh
```

The guide runs the published image of the analyst, which Docker pulls when the
image is not present locally. The guide reads the `.env` file beside the
clone's `docker-compose.yml`. The guide also offers to write the sample
archive, `radar-sample.zip`, to the current directory.

When the clone's `docker-compose.yml` already runs an analyst, the guide uses
that analyst instead of starting another. An analyst started from another
directory already holds port 8080, so stop that analyst before you run the
guide.

The following table describes the environment variables that change how the
guide runs:

| Variable | Effect |
|---|---|
| `WALKTHROUGH_NO_BROWSER=1` | This setting makes the guide print the console's address instead of opening a browser. |
| `WALKTHROUGH_NONINTERACTIVE=1` | This setting skips every prompt and takes each default answer. As the one exception, `--down` then removes everything without asking first. |
| `BROWSER` | This variable names the command that opens the console. The guide runs the command with the console's address as its only argument. |

Without `BROWSER`, the guide opens the console with `open` on macOS. On other
systems, the guide uses `xdg-open` in a graphical session and otherwise prints
the console's address.

The `bash examples/walkthrough/guide.sh --down` command asks for confirmation.
The command then runs `docker compose down -v` for the stack that the clone's
`docker-compose.yml` defines. The command also removes `radar-sample.zip` from
the current directory.

!!! warning
    With `WALKTHROUGH_NONINTERACTIVE=1` set, the `--down` command does not ask
    for confirmation. The command deletes every assessment and every uploaded
    archive at once, and nothing can undo the deletion. To keep the data, unset
    the variable before you run the command.

## Next Steps

The following documents describe the analyst in more detail:

- The [Using the Analyst](using.md) document describes the upload, the list of
  assessments, and deleting an assessment.
- The [Configuring the Analyst](configuring.md) document describes each
  provider and every setting.
- The [Managing an Installation](managing.md) document describes the volumes,
  the logs, backups, and upgrades.
- The [API Reference](api.md) document describes the JSON API that the console
  uses.
