# Managing an Installation

The analyst keeps its data in Docker volumes and writes its log to the
container output. This page describes the volumes, the logs, backups, and
upgrades.

## Storing Data in Docker Volumes

The compose file defines three Docker volumes. The following table describes
the contents of each volume:

| Volume | Contents |
|---|---|
| `db` | This volume holds the state database, which stores every assessment. |
| `archives` | This volume holds the uploaded radar archives and the admin token. |
| `sock` | This volume holds the socket that the analyst uses to connect to the database. |

The volumes outlive the containers, so running `docker compose down` or pulling
a newer image leaves the volumes in place. However, the
`docker compose down -v` command deletes the volumes permanently.

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

## Viewing the Logs

Each service writes its log to the container output. Docker keeps at most three
10 MB log files for each service. Each service therefore uses no more than 30
MB for logs. The following command follows the analyst's log:

```bash
docker compose logs -f app
```

## Backing Up Your Data

A backup copies the state database and the uploaded archives out of the Docker
volumes. Stop the analyst before copying the volumes, because a copy of a
running server's data directory is not consistent. The following commands write
the database and the uploaded archives to `radar-analyst-backup.tar.gz` in the
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

## Upgrading the Analyst

An upgrade replaces the containers with newer images and keeps the volumes. At
startup, the analyst brings its tables in the state database up to date. Back
up your data first, and then run the following commands in the directory that
contains `docker-compose.yml`:

```bash
docker compose pull
docker compose up -d --wait
```

## Next Steps

The following documents describe related tasks:

- The [Using the Analyst](using.md) document describes how to assess a radar
  archive and delete an assessment.
- The [Troubleshooting](troubleshooting.md) document describes common problems
  and how to solve each one.
