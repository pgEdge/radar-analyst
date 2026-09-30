# Guided walkthrough

This page takes you from nothing to an assessment of one of your
PostgreSQL hosts: start the analyst, take a radar collection on the
host, upload it to the console, and read the result.

From a checkout of the repository, the interactive guide starts the
analyst, opens the console in your browser, and explains the rest as
it goes:

```bash
bash examples/walkthrough/guide.sh
```

It needs only Docker with the Compose plugin. Set
`WALKTHROUGH_NO_BROWSER=1` to have it print the console's address
instead of opening it. It runs the published image; from a checkout
with changes of your own, `WALKTHROUGH_BUILD=1` builds the analyst
from that checkout instead. The rest of this page is the same tour
by hand, in a directory holding `docker-compose.yml` from the
repository.

## 1. Start the analyst

```bash
docker compose up -d --wait
```

That starts two containers and returns once they are ready: the
analyst, and a PostgreSQL it keeps its results in. The console is
reachable only from your own machine, and the database only from the
analyst.

## 2. Open the console

Open [http://localhost:8080/](http://localhost:8080/). The console
has an upload area for radar archives and, below it, the most recent
assessments. On a fresh install that list is empty.

## 3. Take a radar collection

A radar archive is what the analyst assesses. Radar collects it on
the PostgreSQL host: metadata about the machine and the server, never
table contents or query results.

Download the binary for the host's platform from
[github.com/pgEdge/radar/releases](https://github.com/pgEdge/radar/releases),
`radar-linux-amd64`, `radar-linux-arm64`, `radar-darwin-amd64` or
`radar-darwin-arm64`, make it executable, and run it on the host as
root, connecting as a superuser or as a role with `pg_monitor`:

```bash
chmod +x radar-linux-amd64 && mv radar-linux-amd64 radar
sudo PGPASSWORD='...' ./radar -d mydb -U postgres
```

Add `-h` and `-p` if the server is not on the default local socket.
The collection takes a minute or two and writes one file beside you,
`radar-<hostname>-<timestamp>.zip`. Copy it to the machine running
the analyst.

No PostgreSQL to hand yet? The analyst can write a small sample
archive to try with: one database and a handful of settings, enough
to see an assessment happen. A real collection gives a real
assessment.

```bash
docker compose exec -T app python -m radar_analyst.tests.make_sample_zip /tmp/radar-sample.zip
docker compose cp app:/tmp/radar-sample.zip ./radar-sample.zip
```

## 4. Upload it

Drag the archive onto the console's upload area, or click the area
and choose it, and press Upload. The console moves to a progress page
while the archive is read and each category is assessed, then to the
finished assessment on its own. A sample takes seconds; a real
collection, up to a minute or two.

## 5. Read the assessment

The assessment covers five categories: Host & OS, PostgreSQL
Configuration, Workload, Internals & I/O Health, and Replication.
Each has a verdict, and the host's own verdict is the worst of the
five. A category the archive holds no data for reads `UNKNOWN`, and
never makes the host look worse than what was measured. Open a
category to read its brief, the findings behind its verdict, and the
list of archive files the category covers. Below the categories,
each database on the server has a card of its own.

The findings are worked out from the archive alone and always come
back, and so does a verdict for every category. The written briefs
come from a provider, which is optional: without one, each brief
reads as unavailable. To add a provider, put a credential in a
`.env` file beside `docker-compose.yml` and start the analyst again;
`examples/compose.env` in the repository is a commented `.env` file
to start from.

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
docker compose up -d --wait
```

An assessment made before that keeps its findings and verdicts. Open
it and press Assess again to have the briefs written from the stored
archive.

Every assessment you make is added to the list on the console's
front page, and can be opened again from there.

## 6. Your assessments stay

Assessments, and the archives behind them, are kept in Docker
volumes. They survive `docker compose down`, and they survive
pulling a newer image.

Each entry in the list has a delete button. It asks you to confirm,
then asks for the admin token, which the analyst wrote for you on
first start:

```bash
docker compose exec app cat /data/admin-token
```

Set `RADAR_ANALYST_ADMIN_TOKEN` in `.env` to choose the token
yourself.

## 7. Stop, or remove

```bash
docker compose stop       # pause; docker compose start brings it back
docker compose down       # remove the containers, keep every assessment
docker compose down -v    # remove the containers AND delete every
                          # assessment and archive. There is no undo.
```

An assessment that was running when the analyst stopped is marked
failed when it starts again. Open it and press Assess again to redo
it from the stored archive.

From a checkout, `bash examples/walkthrough/guide.sh --down` is the
last of those with a confirmation first, and it removes the sample
archive as well.

The [introduction](index.md) covers providers, backups, and using a
PostgreSQL you already run.
