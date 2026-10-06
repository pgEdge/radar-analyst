# Installing the Analyst

Docker Compose runs the analyst as two containers: the analyst itself and a
PostgreSQL database that stores the assessments. This page describes the
requirements, the installation, and how to start and stop the analyst.

## Prerequisites

The installation requires
[Docker](https://docs.docker.com/get-started/get-docker/) with the
[Compose plugin](https://docs.docker.com/compose/install/). pgEdge publishes
the analyst's container image for x86-64 (`linux/amd64`) hosts. The
[Developer Resources](developers.md) page describes building the analyst from
source instead.

## Installing with Docker Compose

The repository's compose file defines both containers and the volumes that hold
their data. The following commands download the compose file into a new
`radar-analyst` directory and start the analyst:

```bash
mkdir radar-analyst && cd radar-analyst
curl -fsSLO https://raw.githubusercontent.com/pgEdge/radar-analyst/main/docker-compose.yml
docker compose up -d --wait
```

The `docker compose up` command returns once both containers are ready. The
console is then available at [http://localhost:8080/](http://localhost:8080/).
The compose file publishes the console on `127.0.0.1:8080`, so only the local
machine can reach it. The database publishes no port at all.

## Starting and Stopping the Analyst

Docker Compose starts and stops both containers together. Run each of the
following commands in the directory that contains `docker-compose.yml`. The
following table describes the commands that stop, start, or remove the analyst:

| Command | Effect |
|---|---|
| `docker compose stop` | This command stops the containers without removing them. |
| `docker compose start` | This command starts the stopped containers again, with every upload and assessment in place. |
| `docker compose down` | This command removes the containers and keeps every assessment in the Docker volumes. |
| `docker compose down -v` | This command removes the containers and permanently deletes every assessment and archive. |

Docker restarts both containers after Docker itself or the host restarts,
unless you stopped the containers. At startup, the analyst marks any assessment
that was still running at the previous stop as failed. To redo such an
assessment, open the assessment and select **Assess again**.

## Next Steps

The following documents describe the next steps after the installation:

- The [Configuring the Analyst](configuring.md) document describes how to add a
  provider for the briefs.
- The [Using the Analyst](using.md) document describes how to assess a radar
  archive.
- The [Managing an Installation](managing.md) document describes the volumes,
  the logs, backups, and upgrades.
